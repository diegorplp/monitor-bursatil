import gspread
import pandas as pd
from datetime import datetime
try:
    from config import SHEET_NAME, CREDENTIALS_FILE, COMISIONES, IVA, DERECHOS_MERCADO, VETA_MINIMO, USE_CLOUD_AUTH, GOOGLE_CREDENTIALS_DICT
except ImportError:
    SHEET_NAME = ""
    CREDENTIALS_FILE = ""
    COMISIONES = {}
    IVA = 1.21
    DERECHOS_MERCADO = 0.0008
    VETA_MINIMO = 50
    USE_CLOUD_AUTH = False
    GOOGLE_CREDENTIALS_DICT = {}

# --- UTILIDADES ---
def _calcular_costo_operacion(monto_bruto, broker):
    broker = str(broker).upper().strip()
    if broker == 'VETA':
        TASA = 0.0015
        comision_base = max(VETA_MINIMO, monto_bruto * TASA)
        gastos = (comision_base * IVA) + (monto_bruto * DERECHOS_MERCADO)
        return gastos
    elif broker == 'COCOS':
        return monto_bruto * DERECHOS_MERCADO
    else:
        tasa = COMISIONES.get(broker, 0.006)
        return monto_bruto * tasa

def _clean_number_str(val):
    """
    Limpia strings numéricos con formatos mixtos (latino/inglés).
    Ej: "1.500,50" -> 1500.50
    Ej: "$ 1,500.50" -> 1500.50
    """
    if pd.isna(val) or val == "":
        return 0.0
    
    # Si ya es número, devolver
    if isinstance(val, (int, float)):
        return float(val)
        
    s = str(val).strip()
    s = s.replace('$', '').replace(' ', '')
    
    # Detección de formato:
    # Si tiene punto Y coma (ej: 1.500,50 o 1,500.50)
    if '.' in s and ',' in s:
        # Asumimos formato latino (punto es mil, coma es decimal) si el punto está antes
        # O formato USA (coma es mil, punto decimal)
        last_point = s.rfind('.')
        last_comma = s.rfind(',')
        
        if last_point < last_comma:
            # Caso Latino: 1.500,50 -> Quitamos puntos, reemplazamos coma
            s = s.replace('.', '').replace(',', '.')
        else:
            # Caso USA: 1,500.50 -> Quitamos comas
            s = s.replace(',', '')
    
    elif ',' in s:
        # Solo tiene comas. Asumimos que es decimal (100,50)
        s = s.replace(',', '.')
        
    # Si solo tiene puntos (100.50), Python ya lo entiende.
    
    try:
        return float(s)
    except:
        return 0.0

# --- CONEXIÓN ---
def _get_worksheet(name=None):
    try:
        if USE_CLOUD_AUTH:
            gc = gspread.service_account_from_dict(GOOGLE_CREDENTIALS_DICT)
        else:
            gc = gspread.service_account(filename=CREDENTIALS_FILE)
            
        sh = gc.open(SHEET_NAME)
        if name: return sh.worksheet(name)
        return sh.get_worksheet(0)
    except Exception as e:
        print(f"ERROR CONEXIÓN SHEETS: {e}")
        raise e

# --- LECTURA ---
def get_portafolio_df():
    try:
        ws = _get_worksheet()
        data = ws.get_all_records()
        if not data: return pd.DataFrame()

        df = pd.DataFrame(data)
        # Limpiar nombres de columnas (quita espacios extra invisibles)
        df.columns = [str(c).strip() for c in df.columns]
        
        expected = ['Ticker', 'Fecha_Compra', 'Cantidad', 'Precio_Compra']
        if not all(c in df.columns for c in expected): return pd.DataFrame()

        def fix_ticker(t):
            t = str(t).strip().upper()
            if not t.endswith('.BA') and len(t) < 9 and len(t) > 0: return f"{t}.BA"
            return t
        df['Ticker'] = df['Ticker'].apply(fix_ticker)

        # Defaults
        cols_defs = {'Broker': 'DEFAULT', 'Alerta_Alta': 0.0, 'Alerta_Baja': 0.0, 
                     'CoolDown_Alta': 0, 'CoolDown_Baja': 0}
        for c, default in cols_defs.items():
            if c not in df.columns: df[c] = default

        # Limpieza Numérica ROBUSTA
        for c in ['Cantidad', 'Precio_Compra', 'Alerta_Alta', 'Alerta_Baja']:
            df[c] = df[c].apply(_clean_number_str)
        
        df.dropna(subset=['Ticker', 'Cantidad', 'Precio_Compra'], inplace=True)
        df = df[df['Cantidad'] > 0]
        df['Fecha_Compra'] = pd.to_datetime(df['Fecha_Compra'], errors='coerce')

        return df
    except Exception as e:
        print(f"ERROR LEYENDO DB: {e}")
        return pd.DataFrame()

def get_historial_df():
    """Lee la pestaña Historial con limpieza numérica agresiva."""
    try:
        ws = _get_worksheet("Historial")
        data = ws.get_all_records()
        if not data: return pd.DataFrame()
        
        df = pd.DataFrame(data)
        # Limpiar headers
        df.columns = [str(c).strip() for c in df.columns]
        
        # Columnas que deben ser números
        cols_num = ['Resultado_Neto', 'Precio_Compra', 'Precio_Venta', 'Cantidad']
        
        for c in cols_num:
            if c in df.columns:
                df[c] = df[c].apply(_clean_number_str)
                
        return df
    except Exception as e:
        print(f"Error Historial: {e}")
        return pd.DataFrame()

def get_tickers_en_cartera():
    df = get_portafolio_df()
    if df.empty: return []
    return df['Ticker'].unique().tolist()

# --- ESCRITURA ---
def add_transaction(data):
    try:
        ws = _get_worksheet()
        row = [
            str(data['Ticker']), str(data['Fecha_Compra']),
            int(data['Cantidad']), float(data['Precio_Compra']),
            str(data.get('Broker', 'DEFAULT')),
            float(data.get('Alerta_Alta', 0.0)), float(data.get('Alerta_Baja', 0.0))
        ]
        ws.append_row(row)
        return True, "Transacción agregada."
    except Exception as e:
        return False, f"Error al guardar: {e}"

def actualizar_alertas_lote(ticker, fecha_compra_str, nueva_alta, nueva_baja):
    try:
        ws = _get_worksheet()
        records = ws.get_all_records()
        idx_fila = -1
        for i, row in enumerate(records):
            r_tick = str(row['Ticker']).strip().upper()
            if not r_tick.endswith('.BA') and len(r_tick) < 9: r_tick += '.BA'
            r_fecha = str(row['Fecha_Compra']).split(" ")[0]
            t_fecha = str(fecha_compra_str).split(" ")[0]
            if r_tick == ticker and r_fecha == t_fecha:
                idx_fila = i + 2 
                break
        
        if idx_fila == -1: return False, "Lote no encontrado."
        # Asumimos Cols 6 y 7
        ws.update_cell(idx_fila, 6, float(nueva_alta))
        ws.update_cell(idx_fila, 7, float(nueva_baja))
        return True, "Alertas guardadas."
    except Exception as e:
        return False, f"Error: {e}"

def registrar_venta(ticker, fecha_compra_str, cantidad_a_vender, precio_venta, fecha_venta_str, precio_compra_id=None):
    try:
        ws_port = _get_worksheet()
        try: ws_hist = _get_worksheet("Historial")
        except: return False, "Falta pestaña 'Historial'."

        records = ws_port.get_all_records()
        fila_encontrada = None
        idx_fila = -1 
        
        for i, row in enumerate(records):
            r_tick = str(row['Ticker']).strip().upper()
            if not r_tick.endswith('.BA') and len(r_tick) < 9: r_tick += '.BA'
            r_fecha = str(row['Fecha_Compra']).split(" ")[0]
            t_fecha = str(fecha_compra_str).split(" ")[0]
            
            match_precio = True
            if precio_compra_id is not None:
                # Limpiamos el precio de la DB antes de comparar
                p_db = _clean_number_str(row['Precio_Compra'])
                if abs(p_db - float(precio_compra_id)) > 0.05: match_precio = False

            if r_tick == ticker and r_fecha == t_fecha and match_precio:
                fila_encontrada = row
                idx_fila = i + 2 
                break
        
        if not fila_encontrada: return False, "Lote no encontrado."

        # Parseo seguro
        cant_tenencia = int(_clean_number_str(fila_encontrada['Cantidad']))
        precio_compra = _clean_number_str(fila_encontrada['Precio_Compra'])
        
        cant_vender = int(cantidad_a_vender)
        precio_vta = float(precio_venta)
        broker = str(fila_encontrada.get('Broker', 'DEFAULT'))
        a_alta = _clean_number_str(fila_encontrada.get('Alerta_Alta', 0))
        a_baja = _clean_number_str(fila_encontrada.get('Alerta_Baja', 0))
        
        if cant_vender > cant_tenencia: return False, "Cantidad insuficiente."

        # Cálculos
        monto_compra_bruto = precio_compra * cant_vender
        monto_venta_bruto = precio_vta * cant_vender
        
        costo_entrada = _calcular_costo_operacion(monto_compra_bruto, broker)
        costo_salida = _calcular_costo_operacion(monto_venta_bruto, broker)
        
        costo_total_origen = monto_compra_bruto + costo_entrada
        ingreso_neto_venta = monto_venta_bruto - costo_salida
        
        resultado = ingreso_neto_venta - costo_total_origen

        # Guardar en Historial (12 cols)
        row_h = [
            str(ticker), str(fecha_compra_str), precio_compra,
            str(fecha_venta_str), precio_vta, cant_vender,
            float(costo_total_origen), float(ingreso_neto_venta), float(resultado),
            broker, float(a_alta), float(a_baja)
        ]

        if cant_vender == cant_tenencia:
            ws_hist.append_row(row_h)
            ws_port.delete_rows(idx_fila)
            msg = "Venta TOTAL registrada."
        else:
            ws_hist.append_row(row_h)
            nueva_cant = int(cant_tenencia - cant_vender)
            ws_port.update_cell(idx_fila, 3, nueva_cant)
            msg = "Venta PARCIAL registrada."
            
        return True, msg

    except Exception as e:
        return False, f"Error venta: {e}"