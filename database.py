import gspread
import pandas as pd
import time
import streamlit as st
import re
from gspread.exceptions import APIError, WorksheetNotFound

# --- CONFIGURACIÓN ---
try:
    from config import SHEET_NAME, CREDENTIALS_FILE, USE_CLOUD_AUTH, GOOGLE_CREDENTIALS_DICT
except ImportError:
    SHEET_NAME, CREDENTIALS_FILE, USE_CLOUD_AUTH, GOOGLE_CREDENTIALS_DICT = "", "", False, {}

# --- UTILIDADES ---
def _clean_number_str(val):
    """Limpia números manejando formatos AR (1.000,00) y US (1,000.00)."""
    if pd.isna(val) or val == "": return 0.0
    if isinstance(val, (int, float)): return float(val)
    
    s = str(val).strip()
    is_negative = s.startswith('(') and s.endswith(')')
    if is_negative: s = s.replace('(', '').replace(')', '')
    s = re.sub(r'[^\d,.-]', '', s) 
    if not s: return 0.0

    if ',' in s and '.' in s:
        if s.rfind(',') > s.rfind('.'): s = s.replace('.', '').replace(',', '.') # AR
        else: s = s.replace(',', '') # US
    elif ',' in s:
        if s.count(',') > 1: s = s.replace(',', '') # US Miles
        else: s = s.replace(',', '.') # AR Decimal
    elif '.' in s:
        if s.count('.') > 1: s = s.replace('.', '') # AR Miles
    
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

def _get_connection():
    if USE_CLOUD_AUTH: gc = gspread.service_account_from_dict(GOOGLE_CREDENTIALS_DICT)
    else: gc = gspread.service_account(filename=CREDENTIALS_FILE)
    return gc.open(SHEET_NAME)

# --- DEBUGGING PÚBLICO ---
def get_all_sheet_names():
    """Devuelve nombres de las hojas para diagnóstico en UI."""
    try:
        sh = _get_connection()
        return [ws.title for ws in sh.worksheets()]
    except: return []

# --- LECTURA ---
@st.cache_data(ttl=60, show_spinner=False)
@retry_api_call
def get_portafolio_df():
    try:
        sh = _get_connection()
        # Asumimos que Portafolio siempre es la primera o se llama 'Transacciones'/'Portafolio'
        ws = sh.get_worksheet(0) 
        data = ws.get_all_records()
        if not data: return pd.DataFrame()
        df = pd.DataFrame(data)
        
        if 'Ticker' in df.columns:
            df['Ticker'] = df['Ticker'].apply(lambda x: str(x).upper().strip())
        
        cols_num = ['Cantidad', 'Precio_Compra', 'Alerta_Alta', 'Alerta_Baja']
        for c in cols_num:
            if c in df.columns: df[c] = df[c].apply(_clean_number_str)
            
        if 'Cantidad' in df.columns: df = df[df['Cantidad'] > 0]
        return df
    except: return pd.DataFrame()

@st.cache_data(ttl=60, show_spinner=False)
@retry_api_call
def get_historial_df():
    """
    ESTRATEGIA BLINDADA:
    1. Itera todas las hojas.
    2. Lee SOLO la primera fila (headers).
    3. Si tiene columnas prohibidas (Alerta, CoolDown), la descarta.
    4. Si tiene columnas deseadas (Resultado, Ganancia, P&L), esa es la buena.
    """
    try:
        sh = _get_connection()
        worksheets = sh.worksheets()
        target_ws = None
        
        # --- BÚSQUEDA INTELIGENTE DE HOJA ---
        for ws in worksheets:
            try:
                # Leemos solo headers para no gastar cuota leyendo toda la hoja
                headers = ws.row_values(1) 
                headers_upper = [str(h).strip().upper() for h in headers]
                
                # 1. FILTRO DE RECHAZO (Si tiene esto, ES EL PORTAFOLIO, HUIR)
                if "COOLDOWN_ALTA" in headers_upper or "ALERTA_ALTA" in headers_upper:
                    continue 

                # 2. FILTRO DE ACEPTACIÓN
                keywords = ["RESULT", "GANANCIA", "P&L", "NETO"]
                if any(k in h for h in headers_upper for k in keywords):
                    target_ws = ws
                    break
                
                # 3. FILTRO POR NOMBRE (Fallback si los headers están raros)
                if "HISTORIAL" in ws.title.strip().upper():
                    target_ws = ws
                    # No hacemos break inmediato por si acaso es un historial viejo,
                    # pero si no encontramos otro mejor, usaremos este.
            except:
                continue

        if not target_ws:
            print("ERROR: No se encontró hoja de Historial válida.")
            return pd.DataFrame()

        # --- LECTURA DE LA HOJA ELEGIDA ---
        data = target_ws.get_all_records()
        if not data: return pd.DataFrame()
        
        df = pd.DataFrame(data)
        
        # Validar de nuevo por si acaso
        if 'CoolDown_Alta' in df.columns or 'Alerta_Alta' in df.columns:
            return pd.DataFrame() # Retorno vacío de seguridad

        # Normalizar columnas
        df.columns = [str(c).strip().replace(" ", "_") for c in df.columns]
        
        # Renombrar columna Resultado
        col_map = {}
        for c in df.columns:
            cu = c.upper()
            if "RESULTADO" in cu and "NETO" in cu: col_map[c] = 'Resultado_Neto'
            elif "GANANCIA" in cu and "REALIZADA" in cu: col_map[c] = 'Resultado_Neto'
            elif cu == "P&L": col_map[c] = 'Resultado_Neto'
        
        if col_map: df.rename(columns=col_map, inplace=True)
        
        # Conversión Numérica
        cols_num = ['Resultado_Neto', 'Precio_Compra', 'Precio_Venta', 'Cantidad']
        for c in cols_num:
            if c in df.columns:
                df[c] = df[c].apply(_clean_number_str)
                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)
                
        return df

    except Exception as e:
        print(f"Error leyendo historial: {e}")
        return pd.DataFrame()

# Funciones dummy para manager
def get_tickers_en_cartera():
    df = get_portafolio_df()
    return df['Ticker'].unique().tolist() if not df.empty else []

def get_favoritos(): return []
def add_transaction(d): return True, "Ok"
def registrar_venta(*a, **k): return False, "Mantenimiento"