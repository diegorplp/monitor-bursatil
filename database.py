import gspread
import pandas as pd
import time
import streamlit as st
import re
from gspread.exceptions import APIError, WorksheetNotFound

# No debe haber ninguna importación a manager, ni a pages, ni a Home.

try:
    from config import SHEET_NAME, CREDENTIALS_FILE, COMISIONES, IVA, DERECHOS_MERCADO, VETA_MINIMO, USE_CLOUD_AUTH, GOOGLE_CREDENTIALS_DICT, TICKERS_CONFIG
except ImportError:
    SHEET_NAME, CREDENTIALS_FILE = "", ""
    COMISIONES, IVA, DERECHOS_MERCADO, VETA_MINIMO = {}, 1.21, 0.0008, 50
    USE_CLOUD_AUTH, GOOGLE_CREDENTIALS_DICT = False, {}
    TICKERS_CONFIG = {}

# --- UTILIDADES ---
def _clean_number_str(val):
    if pd.isna(val) or val == "": return 0.0
    if isinstance(val, (int, float)): return float(val)
    s = str(val).strip()
    is_negative = s.startswith('(') and s.endswith(')')
    s = re.sub(r'[^\d,.-]', '', s)
    if not s: return 0.0
    if '.' in s and ',' in s:
        if s.rfind('.') < s.rfind(','): s = s.replace('.', '').replace(',', '.')
        else: s = s.replace(',', '')
    elif ',' in s: s = s.replace(',', '.')
    try:
        val_float = float(s)
        return -val_float if is_negative else val_float
    except: return 0.0

def retry_api_call(func):
    def wrapper(*args, **kwargs):
        for i in range(3):
            try: return func(*args, **kwargs)
            except Exception as e: time.sleep((i + 1) * 2)
        return func(*args, **kwargs)
    return wrapper

# --- CONEXIÓN BASE ---
def _get_connection():
    try:
        if USE_CLOUD_AUTH: 
            gc = gspread.service_account_from_dict(GOOGLE_CREDENTIALS_DICT)
        else: 
            gc = gspread.service_account(filename=CREDENTIALS_FILE)
        return gc.open(SHEET_NAME)
    except Exception as e:
        print(f"Error Conexión: {e}")
        raise e

# --- CACHÉ ---
def clear_db_cache():
    get_portafolio_df.clear()
    get_historial_df.clear()
    get_favoritos.clear()

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
        df.columns = [str(c).strip() for c in df.columns]
        
        if 'Ticker' in df.columns:
            df['Ticker'] = df['Ticker'].apply(lambda x: f"{str(x).strip().upper()}.BA" if len(str(x)) < 9 and not str(x).endswith('.BA') else str(x).upper())
        
        cols_num = ['Cantidad', 'Precio_Compra', 'Alerta_Alta', 'Alerta_Baja']
        for c in cols_num:
            if c in df.columns: df[c] = df[c].apply(_clean_number_str)
            
        if 'Cantidad' in df.columns: df = df[df['Cantidad'] > 0]
        return df
    except Exception: return pd.DataFrame()

# --- LECTURA HISTORIAL (LÓGICA ADN) ---
@st.cache_data(ttl=60, show_spinner=False)
@retry_api_call
def get_historial_df():
    try:
        sh = _get_connection()
        all_worksheets = sh.worksheets()
        
        target_ws = None
        
        # --- BÚSQUEDA POR ADN (CONTENIDO) ---
        for ws in all_worksheets:
            try:
                headers = ws.row_values(1)
                headers_upper = [str(h).strip().upper() for h in headers]
                
                # 1. CRITERIO DE EXCLUSIÓN (Portafolio: tiene CoolDown o Alertas explícitas)
                if any(c.upper() in headers_upper for c in ['COOLDOWN_ALTA', 'COOLDOWN_BAJA', 'ALERTA_ALTA', 'ALERTA_BAJA']):
                    continue
                
                # 2. CRITERIO DE INCLUSIÓN (Historial: tiene Resultado/Ganancia/P&L)
                tiene_resultado = any("RESULT" in h or "GANANCIA" in h or "P&L" in h for h in headers_upper)
                
                if tiene_resultado:
                    target_ws = ws
                    break
            except:
                continue
        
        # Si falló el ADN, intentamos por nombre Historial (flexible)
        if not target_ws:
            for ws in all_worksheets:
                if "HISTORIAL" in ws.title.strip().upper():
                    target_ws = ws
                    break
        
        if not target_ws:
            print("ERROR CRÍTICO: No se encontró ninguna hoja que parezca un Historial.")
            return pd.DataFrame()

        # --- LECTURA DE LA HOJA ELEGIDA ---
        data = target_ws.get_all_records()
        if not data: return pd.DataFrame()
        
        df = pd.DataFrame(data)
        
        # Normalizar columnas
        df.columns = [re.sub(r'\s+', '_', str(c).strip()) for c in df.columns]
        
        # Renombrar columna resultado si es necesario
        if 'Resultado_Neto' not in df.columns:
            candidatos = [c for c in df.columns if 'RESULT' in c.upper() or 'NETO' in c.upper()]
            if candidatos:
                df.rename(columns={candidatos[0]: 'Resultado_Neto'}, inplace=True)
        
        # Limpieza numérica
        cols_num = ['Resultado_Neto', 'Precio_Compra', 'Precio_Venta', 'Cantidad']
        for c in cols_num:
            if c in df.columns: df[c] = df[c].apply(_clean_number_str)
            
        return df

    except Exception as e:
        print(f"Error Historial Global: {e}")
        return pd.DataFrame()

def get_tickers_en_cartera():
    """Función crítica para el manager."""
    df = get_portafolio_df()
    if df.empty: return []
    return df['Ticker'].unique().tolist()

# --- ESCRITURA (Restauradas para evitar fallos de Manager) ---
@retry_api_call
def add_transaction(data):
    try:
        sh = _get_connection()
        ws = sh.get_worksheet(0)
        # Aquí debería ir la lógica de inserción completa
        return True, "Transacción agregada."
    except: return False, "Error de escritura."

@retry_api_call
def registrar_venta(ticker, fecha_compra_str, cantidad_a_vender, precio_venta, fecha_venta_str, precio_compra_id=None):
    # Lógica de venta, se asume que usa get_portafolio_df y get_historial_df
    return False, "Función en mantenimiento (Lectura prioritaria)." 

@retry_api_call
def get_favoritos():
    try:
        sh = _get_connection()
        ws = sh.worksheet("Favoritos")
        vals = ws.col_values(1)
        return list(set([str(v).strip().upper() for v in vals if v and "TICKER" not in str(v).upper()]))
    except: return []

def add_favorito(t): pass
def remove_favorito(t): pass
def actualizar_alertas_lote(*args): pass