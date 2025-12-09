import gspread
import pandas as pd
import time
import streamlit as st
import re
from gspread.exceptions import APIError, WorksheetNotFound

# --- CONFIGURACIÓN ---
try:
    from config import SHEET_NAME, CREDENTIALS_FILE, USE_CLOUD_AUTH, GOOGLE_CREDENTIALS_DICT, COMISIONES, IVA, DERECHOS_ACCIONES, DERECHOS_BONOS, VETA_MINIMO
except ImportError:
    SHEET_NAME, CREDENTIALS_FILE = "", ""
    USE_CLOUD_AUTH, GOOGLE_CREDENTIALS_DICT = False, {}
    COMISIONES = {'DEFAULT': 0.0045} 
    IVA = 1.21
    DERECHOS_ACCIONES = 0.0005
    DERECHOS_BONOS = 0.0001
    VETA_MINIMO = 50

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

def _es_bono(ticker):
    """Detecta bonos (divisor 100)."""
    if not ticker: return False
    t = str(ticker).strip().upper()
    bonos_letras = ['DICP', 'PARP', 'CUAP', 'DICY', 'PARY', 'TO26', 'PR13', 'CER']
    if any(b in t for b in bonos_letras): return True
    prefijos = ['AL', 'GD', 'TX', 'TO', 'BA', 'BP', 'TV', 'AE', 'SX', 'MR', 'CL', 'NO']
    if any(t.startswith(p) for p in prefijos):
        if any(char.isdigit() for char in t): return True
    return False

def _calcular_comision_real(broker, monto_bruto, es_bono=False):
    """
    Calcula comisiones diferenciando Bonos vs Acciones.
    Bonos: Derechos 0.01% y SIN IVA.
    Acciones: Derechos 0.05% y CON IVA.
    """
    broker = str(broker).upper().strip()
    
    # Definir variables según tipo de activo
    if es_bono:
        tasa_derechos = DERECHOS_BONOS
        multiplicador_iva = 1.0 # No paga IVA
    else:
        tasa_derechos = DERECHOS_ACCIONES
        multiplicador_iva = IVA # 1.21
        
    # CASO VETA
    if broker == 'VETA':
        tasa_veta = COMISIONES.get('VETA', 0.0015)
        comision_base = max(VETA_MINIMO, monto_bruto * tasa_veta)
        
        # En Veta el IVA suele aplicar a la comisión mínima también
        gastos = (comision_base * multiplicador_iva) + (monto_bruto * tasa_derechos)
        return gastos
    
    # CASO GENERAL
    tasa = COMISIONES.get(broker, COMISIONES.get('DEFAULT', 0.0045))
    
    comision_base = monto_bruto * tasa
    derechos = monto_bruto * tasa_derechos
    
    # Fórmula: (Comisión + Derechos) * IVA (Solo si corresponde)
    # Nota: Si es bono, multiplicador_iva es 1.0 (neutro).
    if es_bono:
        costo_total = comision_base + derechos
    else:
        # Acciones: La factura mostraba (Comision + Derechos) * 1.21
        costo_total = (comision_base + derechos) * multiplicador_iva
        
    return costo_total

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

# --- LECTURA PORTAFOLIO (Con Caché - NORMALIZACIÓN AÑADIDA) ---
@st.cache_data(ttl=60, show_spinner=False)
@retry_api_call
def get_portafolio_df():
    try:
        sh = _get_connection()
        ws = sh.get_worksheet(0) 
        data = ws.get_all_records()
        if not data: return pd.DataFrame()
        df = pd.DataFrame(data)
        
        # --- CRÍTICO: NORMALIZACIÓN DE TICKERS ---
        if 'Ticker' in df.columns:
            def normalize_ticker(t):
                t_raw = str(t).strip().upper()
                if not t_raw: return None
                
                # Regla 1: Si ya tiene .BA (o .C), es correcto.
                if '.' in t_raw:
                    return t_raw
                
                # Regla 2: Excepciones (activos que cotizan sin sufijo en Yahoo/IOL, si los hubiera)
                if len(t_raw) < 5 and not t_raw.endswith('.BA'): # Cederars suelen tener 4 letras
                    pass # Dejamos la normalización al manager para no romper tickers internacionales

                # Regla 3: Si es Argentino y no tiene sufijo, lo agregamos.
                # Asumo que cualquier ticker corto de la cartera es local (Ej: GGAL, AL30)
                if len(t_raw) < 9 and not t_raw.endswith('.BA'):
                    return f"{t_raw}.BA"
                
                return t_raw # Devuelve la versión cruda si no aplica ninguna regla

            # Aplicar la normalización
            df['Ticker'] = df['Ticker'].apply(normalize_ticker)
            df = df.dropna(subset=['Ticker'])
            df['Ticker'] = df['Ticker'].apply(lambda x: str(x).upper().strip()) # Limpieza final
        
        cols_num = ['Cantidad', 'Precio_Compra', 'Alerta_Alta', 'Alerta_Baja', 'CoolDown_Alta', 'CoolDown_Baja']
        for c in cols_num:
            if c in df.columns:
                df[c] = df[c].apply(_clean_number_str)
                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)
            
        if 'Cantidad' in df.columns: df = df[df['Cantidad'] > 0]
        return df
    except Exception: return pd.DataFrame()

# --- LECTURA HISTORIAL (SIN CACHÉ) ---
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

# --- ESCRITURA COMPRA ---
@retry_api_call
def add_transaction(datos):
    try:
        sh = _get_connection()
        ws = sh.get_worksheet(0)
        
        ticker_raw = str(datos['Ticker']).strip().upper()
        if '.' not in ticker_raw and len(ticker_raw) < 10:
            ticker_raw += ".BA"
            
        fecha = datos['Fecha_Compra']
        cantidad = datos['Cantidad']
        precio = datos['Precio_Compra']
        broker = datos['Broker']
        alerta_alta = datos.get('Alerta_Alta', 0.0)
        alerta_baja = datos.get('Alerta_Baja', 0.0)
        
        # No se calculan costos en la compra (se calculan al visualizar o vender)
        # Se guarda el dato crudo
        
        nueva_fila = [ticker_raw, fecha, cantidad, precio, broker, alerta_alta, alerta_baja, 0, 0]
        ws.append_row(nueva_fila)
        
        get_portafolio_df.clear()
        return True, f"Compra de {ticker_raw} guardada correctamente."
        
    except Exception as e: return False, f"Error: {e}"

# --- ESCRITURA VENTA ---
@retry_api_call
def registrar_venta(ticker, fecha_compra_str, cantidad_a_vender, precio_venta, fecha_venta_str, precio_compra_id=None):
    try:
        sh = _get_connection()
        ws_port = sh.get_worksheet(0)
        ws_hist = None
        for w in sh.worksheets():
            if "HISTORIAL" in w.title.strip().upper():
                ws_hist = w
                break
        if not ws_hist: return False, "No se encontró hoja Historial."

        data = ws_port.get_all_records()
        fila_idx = -1
        row_data = None
        
        for i, d in enumerate(data):
            t_data = str(d.get('Ticker', '')).upper().strip()
            f_data = str(d.get('Fecha_Compra', '')).strip()[:10]
            p_data = _clean_number_str(d.get('Precio_Compra', 0))
            if t_data == ticker.upper().strip() and f_data == fecha_compra_str.strip()[:10]:
                if precio_compra_id is None or abs(p_data - float(precio_compra_id)) < 0.01:
                    fila_idx = i + 2
                    row_data = d
                    break
        
        if fila_idx == -1: return False, "Lote no encontrado."

        cant_actual = int(_clean_number_str(row_data.get('Cantidad', 0)))
        precio_compra = float(_clean_number_str(row_data.get('Precio_Compra', 0)))
        broker = str(row_data.get('Broker', 'DEFAULT')).upper()
        
        if cantidad_a_vender > cant_actual: return False, "Cantidad insuficiente."

        # 1. Ajuste por Bonos
        es_bono = _es_bono(ticker)
        divisor = 100 if es_bono else 1
        
        # 2. Cálculos con distinción Bono/Acción
        monto_bruto_compra = (cantidad_a_vender * precio_compra) / divisor
        
        # Pasamos es_bono=True/False a la calculadora
        comision_compra = _calcular_comision_real(broker, monto_bruto_compra, es_bono=es_bono)
        costo_total_origen = monto_bruto_compra + comision_compra

        monto_bruto_venta = (cantidad_a_vender * precio_venta) / divisor
        comision_venta = _calcular_comision_real(broker, monto_bruto_venta, es_bono=es_bono)
        ingreso_total_venta = monto_bruto_venta - comision_venta

        resultado_neto = ingreso_total_venta - costo_total_origen

        # 3. Escritura
        nueva_fila = [ticker, fecha_compra_str, precio_compra, fecha_venta_str, precio_venta, cantidad_a_vender, costo_total_origen, ingreso_total_venta, resultado_neto, broker, 0, 0]
        ws_hist.append_row(nueva_fila)

        # 4. Actualización
        if cantidad_a_vender == cant_actual:
            ws_port.delete_rows(fila_idx)
            msg = "Venta Total OK."
        else:
            nueva_cantidad = cant_actual - cantidad_a_vender
            headers = ws_port.row_values(1)
            col_cant = -1
            for i, h in enumerate(headers):
                if str(h).strip() == 'Cantidad':
                    col_cant = i + 1
                    break
            if col_cant > 0:
                ws_port.update_cell(fila_idx, col_cant, nueva_cantidad)
                msg = "Venta Parcial OK."
            else:
                return False, "Error estructura Excel."

        get_portafolio_df.clear()
        return True, msg
    except Exception as e: return False, f"Error: {str(e)}"

@retry_api_call
def actualizar_alertas_lote(ticker, fecha_compra_str, alerta_alta, alerta_baja):
    try:
        sh = _get_connection()
        ws = sh.get_worksheet(0)
        data = ws.get_all_records()
        fila_idx = -1
        for i, d in enumerate(data):
            if str(d.get('Ticker')).upper().strip() == ticker.upper().strip() and str(d.get('Fecha_Compra')).strip()[:10] == fecha_compra_str.strip()[:10]:
                fila_idx = i + 2
                break
        if fila_idx == -1: return False, "Lote no encontrado."
        headers = ws.row_values(1)
        col_a, col_b = -1, -1
        for i, h in enumerate(headers):
            if str(h).strip() == 'Alerta_Alta': col_a = i + 1
            if str(h).strip() == 'Alerta_Baja': col_b = i + 1
        if col_a > 0: ws.update_cell(fila_idx, col_a, alerta_alta)
        if col_b > 0: ws.update_cell(fila_idx, col_b, alerta_baja)
        get_portafolio_df.clear()
        return True, "Alertas OK."
    except Exception as e: return False, f"Error: {e}"

def get_tickers_en_cartera():
    df = get_portafolio_df()
    return df['Ticker'].unique().tolist() if not df.empty else []
def get_favoritos(): return []