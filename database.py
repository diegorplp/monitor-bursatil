import gspread
import pandas as pd
import time
import streamlit as st
import re
from gspread.exceptions import APIError, WorksheetNotFound

# --- CONFIGURACIÓN ---
try:
    from config import SHEET_NAME, CREDENTIALS_FILE, USE_CLOUD_AUTH, GOOGLE_CREDENTIALS_DICT, COMISIONES, IVA, DERECHOS_MERCADO, VETA_MINIMO
except ImportError:
    SHEET_NAME, CREDENTIALS_FILE = "", ""
    USE_CLOUD_AUTH, GOOGLE_CREDENTIALS_DICT = False, {}
    # Valores por defecto de seguridad
    COMISIONES, IVA, DERECHOS_MERCADO, VETA_MINIMO = {}, 1.21, 0.0008, 50

# --- UTILIDADES ---
def _clean_number_str(val):
    if pd.isna(val) or val == "": return 0.0
    if isinstance(val, (int, float)): return float(val)
    s = str(val).strip()
    is_negative = s.startswith('(') and s.endswith(')') or s.startswith('-')
    if is_negative: s = s.replace('(', '').replace(')', '').replace('-', '')
    s = re.sub(r'[^\d,.-]', '', s) 
    if not s: return 0.0
    if ',' in s and '.' in s:
        if s.rfind(',') > s.rfind('.'): s = s.replace('.', '').replace(',', '.') 
        else: s = s.replace(',', '') 
    elif ',' in s:
        if s.count(',') > 1: s = s.replace(',', '') 
        else: s = s.replace(',', '.') 
    elif '.' in s:
        if s.count('.') > 1: s = s.replace('.', '') 
    try:
        val_float = float(s)
        return -val_float if is_negative else val_float
    except: return 0.0

def _calcular_comision_real(broker, monto_bruto):
    """Calcula la comisión exacta según broker."""
    broker = str(broker).upper().strip()
    
    if broker == 'COCOS':
        return monto_bruto * 0.0 # Cocos no cobra comisión, solo derechos (que van aparte)
        
    tasa = COMISIONES.get(broker, 0.006) # Default 0.6%
    
    if broker == 'VETA':
        comision_base = monto_bruto * tasa
        if comision_base < VETA_MINIMO: comision_base = VETA_MINIMO
        comision_total = (comision_base * IVA) + (monto_bruto * DERECHOS_MERCADO)
        return comision_total
    
    # Brokers estándar (Bull, PPI, IOL)
    comision_total = (monto_bruto * tasa * IVA) + (monto_bruto * DERECHOS_MERCADO)
    return comision_total

def retry_api_call(func):
    def wrapper(*args, **kwargs):
        for i in range(3):
            try: return func(*args, **kwargs)
            except Exception as e: time.sleep((i + 1) * 2)
        return func(*args, **kwargs)
    return wrapper

def _get_connection():
    if USE_CLOUD_AUTH: gc = gspread.service_account_from_dict(GOOGLE_CREDENTIALS_DICT)
    else: gc = gspread.service_account(filename=CREDENTIALS_FILE)
    return gc.open(SHEET_NAME)

# --- LECTURA PORTAFOLIO ---
@st.cache_data(ttl=60, show_spinner=False)
@retry_api_call
def get_portafolio_df():
    try:
        sh = _get_connection()
        ws = sh.get_worksheet(0) 
        data = ws.get_all_records()
        if not data: return pd.DataFrame()
        df = pd.DataFrame(data)
        
        if 'Ticker' in df.columns:
            df['Ticker'] = df['Ticker'].apply(lambda x: str(x).upper().strip())
        
        cols_num = ['Cantidad', 'Precio_Compra', 'Alerta_Alta', 'Alerta_Baja', 'CoolDown_Alta', 'CoolDown_Baja']
        for c in cols_num:
            if c in df.columns:
                df[c] = df[c].apply(_clean_number_str)
                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)
            
        if 'Cantidad' in df.columns: df = df[df['Cantidad'] > 0]
        return df
    except Exception: return pd.DataFrame()

# --- LECTURA HISTORIAL ---
@retry_api_call
def get_historial_df():
    try:
        sh = _get_connection()
        worksheets = sh.worksheets()
        target_ws = None
        for ws in worksheets:
            if "HISTORIAL" in ws.title.strip().upper():
                target_ws = ws
                break
        if not target_ws:
            for ws in worksheets:
                try:
                    headers = [str(h).upper() for h in ws.row_values(1)]
                    if "COOLDOWN_ALTA" in headers and "ALERTA_ALTA" in headers: continue 
                    if any(k in h for h in headers for k in ["RESULT", "GANANCIA", "P&L"]):
                        target_ws = ws
                        break
                except: continue
        if not target_ws: return pd.DataFrame()

        data = target_ws.get_all_records()
        if not data: return pd.DataFrame()
        df = pd.DataFrame(data)
        df.columns = [str(c).strip().replace(" ", "_") for c in df.columns]
        
        col_map = {}
        for c in df.columns:
            cu = c.upper()
            if "RESULTADO" in cu and "NETO" in cu: col_map[c] = 'Resultado_Neto'
            elif "GANANCIA" in cu and "REALIZADA" in cu: col_map[c] = 'Resultado_Neto'
            elif cu == "P&L": col_map[c] = 'Resultado_Neto'
        if col_map: df.rename(columns=col_map, inplace=True)

        cols_num = ['Resultado_Neto', 'Precio_Compra', 'Precio_Venta', 'Cantidad', 
                    'Alerta_Alta', 'Alerta_Baja', 'CoolDown_Alta', 'CoolDown_Baja',
                    'Costo_Total_Origen', 'Ingreso_Total_Venta']
        for c in cols_num:
            if c in df.columns:
                df[c] = df[c].apply(_clean_number_str)
                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)
        return df
    except Exception as e:
        print(f"Error Historial: {e}")
        return pd.DataFrame()

# --- FUNCIONES DE ESCRITURA (NUEVO) ---

@retry_api_call
def registrar_venta(ticker, fecha_compra_str, cantidad_a_vender, precio_venta, fecha_venta_str, precio_compra_id=None):
    """
    Ejecuta la venta moviendo datos de Portafolio a Historial.
    Maneja venta parcial (update) y total (delete).
    """
    try:
        sh = _get_connection()
        ws_port = sh.get_worksheet(0)
        
        # 1. Buscar la hoja Historial (Usando la misma lógica robusta)
        ws_hist = None
        for w in sh.worksheets():
            if "HISTORIAL" in w.title.strip().upper():
                ws_hist = w
                break
        if not ws_hist: return False, "No se encontró hoja Historial para escribir."

        # 2. Leer Portafolio para encontrar la fila exacta
        data = ws_port.get_all_records()
        fila_idx = -1
        row_data = None
        
        # Búsqueda manual de la fila por Ticker, Fecha y Precio
        # Nota: gspread rows son 1-indexed y header es row 1, asi que data[0] es row 2.
        for i, d in enumerate(data):
            # Normalización para comparar
            t_data = str(d.get('Ticker', '')).upper().strip()
            f_data = str(d.get('Fecha_Compra', '')).strip()[:10] # Solo YYYY-MM-DD
            p_data = _clean_number_str(d.get('Precio_Compra', 0))
            
            ticker_match = t_data == ticker.upper().strip()
            # Comparación de fecha flexible
            fecha_match = f_data == fecha_compra_str.strip()[:10]
            
            # Comparación de precio (opcional pero recomendada para desempatar lotes del mismo día)
            precio_match = True
            if precio_compra_id is not None:
                precio_match = abs(p_data - float(precio_compra_id)) < 0.01

            if ticker_match and fecha_match and precio_match:
                fila_idx = i + 2 # +2 porque data empieza en 0 y sheet tiene header
                row_data = d
                break
        
        if fila_idx == -1:
            return False, f"No se encontró el lote en Portafolio (T:{ticker} F:{fecha_compra_str})."

        # 3. Datos del Lote
        cant_actual = int(_clean_number_str(row_data.get('Cantidad', 0)))
        precio_compra = float(_clean_number_str(row_data.get('Precio_Compra', 0)))
        broker = str(row_data.get('Broker', 'DEFAULT')).upper()
        
        if cantidad_a_vender > cant_actual:
            return False, f"Error: Quieres vender {cantidad_a_vender} pero tienes {cant_actual}."

        # 4. Cálculos Financieros
        # Costo Origen (proporcional a lo que vendo)
        monto_bruto_compra = cantidad_a_vender * precio_compra
        comision_compra = _calcular_comision_real(broker, monto_bruto_compra)
        costo_total_origen = monto_bruto_compra + comision_compra

        # Ingreso Venta
        monto_bruto_venta = cantidad_a_vender * precio_venta
        comision_venta = _calcular_comision_real(broker, monto_bruto_venta)
        ingreso_total_venta = monto_bruto_venta - comision_venta

        resultado_neto = ingreso_total_venta - costo_total_origen

        # 5. Escribir en Historial
        # Orden: Ticker, Fecha_Compra, Precio_Compra, Fecha_Venta, Precio_Venta, Cantidad, Costo, Ingreso, Resultado, Broker, Alertas
        nueva_fila = [
            ticker, 
            fecha_compra_str, 
            precio_compra, 
            fecha_venta_str, 
            precio_venta, 
            cantidad_a_vender, 
            costo_total_origen, 
            ingreso_total_venta, 
            resultado_neto, 
            broker,
            0, 0 # Alertas reseteadas en historial
        ]
        ws_hist.append_row(nueva_fila)

        # 6. Actualizar Portafolio
        if cantidad_a_vender == cant_actual:
            # Venta Total -> Borrar fila
            ws_port.delete_rows(fila_idx)
            msg = "Venta Total registrada con éxito."
        else:
            # Venta Parcial -> Actualizar cantidad
            nueva_cantidad = cant_actual - cantidad_a_vender
            col_cant_idx = -1
            # Buscar índice de columna Cantidad
            headers = ws_port.row_values(1)
            for i, h in enumerate(headers):
                if str(h).strip() == 'Cantidad':
                    col_cant_idx = i + 1
                    break
            
            if col_cant_idx > 0:
                ws_port.update_cell(fila_idx, col_cant_idx, nueva_cantidad)
                msg = f"Venta Parcial registrada. Quedan {nueva_cantidad} nominales."
            else:
                return False, "Error crítico: No encuentro columna Cantidad para actualizar."

        # Limpiar caché para reflejar cambios
        get_portafolio_df.clear()
        # get_historial_df.clear() # No tiene caché, pero por si acaso

        return True, msg

    except Exception as e:
        return False, f"Error al escribir: {str(e)}"

@retry_api_call
def actualizar_alertas_lote(ticker, fecha_compra_str, alerta_alta, alerta_baja):
    """Actualiza Stop Loss y Take Profit en la hoja Portafolio."""
    try:
        sh = _get_connection()
        ws = sh.get_worksheet(0)
        data = ws.get_all_records()
        
        fila_idx = -1
        
        # Búsqueda (simplificada sin precio porque la fecha suele bastar)
        for i, d in enumerate(data):
            t_data = str(d.get('Ticker', '')).upper().strip()
            f_data = str(d.get('Fecha_Compra', '')).strip()[:10]
            
            if t_data == ticker.upper().strip() and f_data == fecha_compra_str.strip()[:10]:
                fila_idx = i + 2
                break
        
        if fila_idx == -1: return False, "Lote no encontrado."
        
        # Buscar índices de columnas
        headers = ws.row_values(1)
        col_alta = -1
        col_baja = -1
        
        for i, h in enumerate(headers):
            h_clean = str(h).strip()
            if h_clean == 'Alerta_Alta': col_alta = i + 1
            if h_clean == 'Alerta_Baja': col_baja = i + 1
            
        if col_alta > 0: ws.update_cell(fila_idx, col_alta, alerta_alta)
        if col_baja > 0: ws.update_cell(fila_idx, col_baja, alerta_baja)
        
        get_portafolio_df.clear() # Limpiar caché obligatorio
        return True, "Alertas guardadas."
        
    except Exception as e:
        return False, f"Error: {e}"

# --- COMPATIBILIDAD ---
def get_tickers_en_cartera():
    df = get_portafolio_df()
    return df['Ticker'].unique().tolist() if not df.empty else []
def get_favoritos(): return []
def add_transaction(d): return True, "Ok"