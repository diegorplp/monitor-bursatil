import gspread
import pandas as pd
import time
import streamlit as st
from gspread.exceptions import APIError
from datetime import datetime
try:
    from config import SHEET_NAME, CREDENTIALS_FILE, COMISIONES, IVA, DERECHOS_MERCADO, VETA_MINIMO, USE_CLOUD_AUTH, GOOGLE_CREDENTIALS_DICT, TICKERS_CONFIG
except ImportError:
    SHEET_NAME = ""
    CREDENTIALS_FILE = ""
    COMISIONES = {}
    IVA = 1.21
    DERECHOS_MERCADO = 0.0008
    VETA_MINIMO = 50
    USE_CLOUD_AUTH = False
    GOOGLE_CREDENTIALS_DICT = {}
    TICKERS_CONFIG = {}

# --- UTILIDADES ---
def _calcular_costo_operacion(monto_bruto, broker):
    broker = str(broker).upper().strip()
    if broker == 'VETA':
        TASA = 0.0015
        comision_base = max(VETA_MINIMO, monto_bruto * TASA)
        gastos = (comision_base * IVA) + (monto_bruto * DERECHOS_MERCADO)
        return gastos
    else:
        # COCOS usa 0.6% desde config si está configurado así, o default
        tasa = COMISIONES.get(broker, 0.006)
        return monto_bruto * tasa

def _clean_number_str(val):
    if pd.isna(val) or val == "": return 0.0
    if isinstance(val, (int, float)): return float(val)
    s = str(val).strip().replace('$', '').replace(' ', '')
    if '.' in s and ',' in s:
        if s.rfind('.') < s.rfind(','): s = s.replace('.', '').replace(',', '.') 
        else: s = s.replace(',', '') 
    elif ',' in s: s = s.replace(',', '.')
    try: return float(s)
    except: return 0.0

def retry_api_call(func):
    def wrapper(*args, **kwargs):
        max_retries = 3
        for i in range(max_retries):
            try:
                return func(*args, **kwargs)
            except APIError as e:
                if e.response.status_code == 429: time.sleep((i + 1) * 2)
                else: raise e
            except Exception as e:
                if "Quota exceeded" in str(e): time.sleep((i + 1) * 2)
                else: raise e
        return func(*args, **kwargs)
    return wrapper

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

# --- LIMPIEZA CACHÉ ---
def clear_db_cache():
    get_portafolio_df.clear()
    get_historial_df.clear()
    get_favoritos.clear()

# --- LECTURA PORTAFOLIO ---
@st.cache_data(ttl=60, show_spinner=False)
@retry_api_call
def get_portafolio_df():
    try:
        ws = _get_worksheet()
        data = ws.get_all_records()
        if not data: return pd.DataFrame()

        df = pd.DataFrame(data)
        df.columns = [str(c).strip() for c in df.columns]
        
        expected = ['Ticker', 'Fecha_Compra', 'Cantidad', 'Precio_Compra']
        if not all(c in df.columns for c in expected): return pd.DataFrame()

        def fix_ticker(t):
            t = str(t).strip().upper()
            if not t.endswith('.BA') and len(t) < 9 and len(t) > 0: return f"{t}.BA"
            return t
        df['Ticker'] = df['Ticker'].apply(fix_ticker)

        cols_defs = {'Broker': 'DEFAULT', 'Alerta_Alta': 0.0, 'Alerta_Baja': 0.0, 
                     'CoolDown_Alta': 0, 'CoolDown_Baja': 0}
        for c, default in cols_defs.items():
            if c not in df.columns: df[c] = default

        for c in ['Cantidad', 'Precio_Compra', 'Alerta_Alta', 'Alerta_Baja']:
            df[c] = df[c].apply(_clean_number_str)
        
        df.dropna(subset=['Ticker', 'Cantidad', 'Precio_Compra'], inplace=True)
        df = df[df['Cantidad'] > 0]
        df['Fecha_Compra'] = pd.to_datetime(df['Fecha_Compra'], errors='coerce')

        return df
    except Exception as e:
        print(f"ERROR LEYENDO DB: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=60, show_spinner=False)
@retry_api_call
def get_historial_df():
    try:
        ws = _get_worksheet("Historial")
        data = ws.get_all_records()
        if not data: return pd.DataFrame()
        
        df = pd.DataFrame(data)
        df.columns = [str(c).strip() for c in df.columns]
        
        if 'Resultado_Neto' not in df.columns and 'Ticker' in df.columns:
             df.columns = [c.replace(' ', '_') for c in df.columns]

        cols_num = ['Resultado_Neto', 'Precio_Compra', 'Precio_Venta', 'Cantidad']
        for c in cols_num:
            if c in df.columns: df[c] = df[c].apply(_clean_number_str)
        
        return df
    except Exception as e:
        print(f"Error Historial: {e}")
        return pd.DataFrame()

def get_tickers_en_cartera():
    """Obtiene lista única de tickers de forma segura."""
    try:
        df = get_portafolio_df()
        
        # BLINDAJE: Si df no es DataFrame o está vacío, retornar lista vacía
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return []
            
        return df['Ticker'].unique().tolist()
    except:
        return []

# --- ESCRITURA ---
@retry_api_call
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
        clear_db_cache()
        return True, "Transacción agregada."
    except Exception as e: return False, f"Error: {e}"

@retry_api_call
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
        ws.update_cell(idx_fila, 6, float(nueva_alta))
        ws.update_cell(idx_fila, 7, float(nueva_baja))
        clear_db_cache()
        return True, "Alertas guardadas."
    except Exception as e: return False, f"Error: {e}"

@retry_api_call
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
                p_db = _clean_number_str(row['Precio_Compra'])
                if abs(p_db - float(precio_compra_id)) > 0.05: match_precio = False

            if r_tick == ticker and r_fecha == t_fecha and match_precio:
                fila_encontrada = row
                idx_fila = i + 2 
                break
        
        if not fila_encontrada: return False, "Lote no encontrado."

        cant_tenencia = int(_clean_number_str(fila_encontrada['Cantidad']))
        precio_compra = _clean_number_str(fila_encontrada['Precio_Compra'])
        cant_vender = int(cantidad_a_vender)
        precio_vta = float(precio_venta)
        broker = str(fila_encontrada.get('Broker', 'DEFAULT'))
        a_alta = _clean_number_str(fila_encontrada.get('Alerta_Alta', 0))
        a_baja = _clean_number_str(fila_encontrada.get('Alerta_Baja', 0))
        
        if cant_vender > cant_tenencia: return False, "Cantidad insuficiente."

        # --- LÓGICA DE BONOS (RECUPERADA) ---
        es_bono = ticker in TICKERS_CONFIG.get('Bonos', [])
        divisor = 100 if es_bono else 1
        
        monto_compra_bruto = (precio_compra * cant_vender) / divisor
        monto_venta_bruto = (precio_vta * cant_vender) / divisor
        
        costo_entrada = _calcular_costo_operacion(monto_compra_bruto, broker)
        costo_salida = _calcular_costo_operacion(monto_venta_bruto, broker)
        
        costo_total_origen = monto_compra_bruto + costo_entrada
        ingreso_neto_venta = monto_venta_bruto - costo_salida
        resultado = ingreso_neto_venta - costo_total_origen

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
            
        clear_db_cache()
        return True, msg
    except Exception as e: return False, f"Error venta: {e}"

# --- FAVORITOS ---
@st.cache_data(ttl=60, show_spinner=False)
@retry_api_call
def get_favoritos():
    try:
        ws = _get_worksheet("Favoritos")
        vals = ws.col_values(1)
        if not vals: return []
        clean = []
        for v in vals:
            v_str = str(v).strip().upper()
            if v_str and v_str != "TICKER":
                if not v_str.endswith(".BA") and len(v_str) < 9: v_str += ".BA"
                clean.append(v_str)
        return list(set(clean))
    except: return []

@retry_api_call
def add_favorito(ticker):
    try:
        ws = _get_worksheet("Favoritos")
        ticker = ticker.strip().upper()
        if not ticker.endswith(".BA") and len(ticker) < 9: ticker += ".BA"
        existentes = get_favoritos()
        if ticker in existentes: return False, "Ya existe."
        ws.append_row([ticker])
        clear_db_cache()
        return True, "Agregado."
    except Exception as e: return False, f"Error: {e}"

@retry_api_call
def remove_favorito(ticker):
    try:
        ws = _get_worksheet("Favoritos")
        cell = ws.find(ticker)
        if cell:
            ws.delete_rows(cell.row)
            clear_db_cache()
            return True, "Eliminado."
        cell = ws.find(ticker.replace('.BA', ''))
        if cell:
            ws.delete_rows(cell.row)
            clear_db_cache()
            return True, "Eliminado."
        return False, "No encontrado."
    except Exception as e: return False, f"Error: {e}"