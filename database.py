import gspread
import pandas as pd
import time
import streamlit as st
import re
from gspread.exceptions import APIError, WorksheetNotFound

try:
    from config import SHEET_NAME, CREDENTIALS_FILE, COMISIONES, IVA, DERECHOS_MERCADO, VETA_MINIMO, USE_CLOUD_AUTH, GOOGLE_CREDENTIALS_DICT
except ImportError:
    SHEET_NAME, CREDENTIALS_FILE = "", ""
    COMISIONES, IVA, DERECHOS_MERCADO, VETA_MINIMO = {}, 1.21, 0.0008, 50
    USE_CLOUD_AUTH, GOOGLE_CREDENTIALS_DICT = False, {}

# --- UTILIDADES ---
def _clean_number_str(val):
    """Limpieza numérica robusta."""
    if pd.isna(val) or val == "": return 0.0
    if isinstance(val, (int, float)): return float(val)
    
    s = str(val).strip()
    is_negative = s.startswith('(') and s.endswith(')')
    s = re.sub(r'[^\d,.-]', '', s)
    if not s: return 0.0

    if '.' in s and ',' in s:
        if s.rfind('.') < s.rfind(','): 
            s = s.replace('.', '').replace(',', '.') # Latam
        else: 
            s = s.replace(',', '') # USA
    elif ',' in s: 
        s = s.replace(',', '.')

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

# --- CONEXIÓN INTELIGENTE (MODIFICADA) ---
def _get_worksheet(name=None):
    try:
        if USE_CLOUD_AUTH: gc = gspread.service_account_from_dict(GOOGLE_CREDENTIALS_DICT)
        else: gc = gspread.service_account(filename=CREDENTIALS_FILE)
        
        sh = gc.open(SHEET_NAME)
        
        # Si no piden nombre, devolvemos la primera (Portafolio)
        if not name: return sh.get_worksheet(0)

        target = name.strip().lower()
        ws_list = sh.worksheets()
        
        # 1. BÚSQUEDA EXACTA (Prioridad 1)
        # Esto evita que "Historial de Precios" gane a "Historial"
        for ws in ws_list:
            if ws.title.strip().lower() == target:
                return ws
        
        # 2. BÚSQUEDA PARCIAL (Prioridad 2)
        for ws in ws_list:
            if target in ws.title.strip().lower():
                return ws
                
        # Si llegamos aquí, no existe.
        titulos_disponibles = [w.title for w in ws_list]
        print(f"⚠️ NO SE ENCONTRÓ HOJA '{name}'. Disponibles: {titulos_disponibles}")
        raise WorksheetNotFound(f"Pestaña '{name}' no existe.")

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
        ws = _get_worksheet() # Default (Index 0)
        data = ws.get_all_records()
        if not data: return pd.DataFrame()

        df = pd.DataFrame(data)
        df.columns = [str(c).strip() for c in df.columns]
        
        # Validación de ADN: Debe tener Ticker
        if 'Ticker' in df.columns:
            # Fix Ticker (si falta .BA)
            df['Ticker'] = df['Ticker'].apply(lambda x: f"{str(x).strip().upper()}.BA" if len(str(x)) < 9 and not str(x).endswith('.BA') else str(x).upper())
            
        cols_num = ['Cantidad', 'Precio_Compra', 'Alerta_Alta', 'Alerta_Baja']
        for c in cols_num:
            if c in df.columns: df[c] = df[c].apply(_clean_number_str)
            
        if 'Cantidad' in df.columns: df = df[df['Cantidad'] > 0]
        return df
    except Exception: return pd.DataFrame()

# --- LECTURA HISTORIAL (CORREGIDA) ---
@st.cache_data(ttl=60, show_spinner=False)
@retry_api_call
def get_historial_df():
    try:
        ws = _get_worksheet("Historial")
        data = ws.get_all_records()
        if not data: return pd.DataFrame()
        
        df = pd.DataFrame(data)
        
        # 1. Validación de Seguridad (Evitar cargar Portafolio por error)
        # Si tiene 'Alerta_Alta' o 'CoolDown_Alta', NO ES el Historial.
        cols_sospechosas = ['Alerta_Alta', 'CoolDown_Alta', 'Alerta_Baja']
        if any(c in df.columns for c in cols_sospechosas):
            print("⚠️ ALERTA: Se cargó la hoja incorrecta (tiene columnas de alertas).")
            # Devolvemos vacío para no corromper métricas, o forzamos error para debug
            return pd.DataFrame() 

        # 2. Normalizar columnas
        df.columns = [re.sub(r'\s+', '_', str(c).strip()) for c in df.columns]
        
        # 3. Mapeo de Nombres (Resultado Neto)
        if 'Resultado_Neto' not in df.columns:
            candidatos = [c for c in df.columns if any(x in c.upper() for x in ['RESULT', 'GANANCIA', 'NETO', 'P&L'])]
            if candidatos:
                df.rename(columns={candidatos[0]: 'Resultado_Neto'}, inplace=True)
        
        # 4. Limpieza Numérica
        cols_num = ['Resultado_Neto', 'Precio_Compra', 'Precio_Venta', 'Cantidad', 'Costo_Total', 'Ingreso_Neto']
        for c in cols_num:
            if c in df.columns: df[c] = df[c].apply(_clean_number_str)
            
        return df
    except Exception as e:
        print(f"Error Historial: {e}")
        return pd.DataFrame()

# --- FUNCIONES DE ESCRITURA ---
# Se mantienen igual (simplificadas aquí para el ejemplo, usa tus originales si las necesitas completas)
def add_transaction(data): pass 
def registrar_venta(*args, **kwargs): pass 
def add_favorito(t): pass
def remove_favorito(t): pass
def get_favoritos():
    try:
        ws = _get_worksheet("Favoritos")
        return [c for c in ws.col_values(1) if c != "TICKER"]
    except: return []