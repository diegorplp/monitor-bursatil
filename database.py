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
    if pd.isna(val) or val == "": return 0.0
    if isinstance(val, (int, float)): return float(val)
    s = str(val).strip()
    is_negative = s.startswith('(') and s.endswith(')')
    if is_negative: s = s.replace('(', '').replace(')', '')
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

# --- LECTURA PORTAFOLIO (Con Caché y protección Arrow) ---
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
    except Exception as e:
        return pd.DataFrame()

# --- LECTURA HISTORIAL (SIN CACHÉ PARA DEBUGGING) ---
# IMPORTANTE: He quitado el decorador de caché para forzar la ejecución y ver los logs.
@retry_api_call
def get_historial_df():
    logs = [f"--- DEBUG RUN {time.strftime('%H:%M:%S')} ---"]
    
    try:
        sh = _get_connection()
        worksheets = sh.worksheets()
        logs.append(f"Hojas disponibles: {[w.title for w in worksheets]}")
        
        target_ws = None
        
        # BÚSQUEDA EXPLICITA
        for i, ws in enumerate(worksheets):
            title = ws.title.strip()
            logs.append(f"Analizando: '{title}'")
            
            try:
                headers = ws.row_values(1)
                headers_upper = [str(h).strip().upper() for h in headers]
            except: 
                logs.append(" -> Error leyendo headers")
                continue

            # RECHAZO
            if any(p in headers_upper for p in ['COOLDOWN_ALTA', 'ALERTA_ALTA']):
                logs.append(" -> RECHAZADA (Portafolio)")
                continue

            # ACEPTACIÓN
            # 1. Por Nombre exacto
            if "HISTORIAL" in title.upper():
                logs.append(" -> ✅ SELECCIONADA (Por Nombre)")
                target_ws = ws
                break
            
            # 2. Por Contenido (Plan B)
            if any(k in h for h in headers_upper for k in ["RESULT", "GANANCIA", "P&L", "NETO"]):
                logs.append(" -> ✅ SELECCIONADA (Por Contenido)")
                target_ws = ws
                break

        if not target_ws:
            logs.append("❌ FATAL: No se eligió ninguna hoja.")
            st.session_state['db_logs'] = logs
            return pd.DataFrame()

        # LECTURA
        data = target_ws.get_all_records()
        if not data:
            logs.append("⚠️ La hoja seleccionada está VACÍA.")
            st.session_state['db_logs'] = logs
            return pd.DataFrame()
        
        df = pd.DataFrame(data)
        logs.append(f"Filas crudas: {len(df)}")
        logs.append(f"Columnas crudas: {list(df.columns)}")

        # Renombrado de columnas
        df.columns = [str(c).strip().replace(" ", "_") for c in df.columns]
        
        col_map = {}
        for c in df.columns:
            cu = c.upper()
            if "RESULTADO" in cu and "NETO" in cu: col_map[c] = 'Resultado_Neto'
            elif "GANANCIA" in cu and "REALIZADA" in cu: col_map[c] = 'Resultado_Neto'
            elif cu == "P&L": col_map[c] = 'Resultado_Neto'
        
        if col_map: 
            df.rename(columns=col_map, inplace=True)
            logs.append(f"Mapeo aplicado: {col_map}")
        else:
            logs.append("⚠️ ALERTA: No se encontró columna para 'Resultado_Neto'.")

        # Limpieza Numérica (CRÍTICO)
        cols_num = ['Resultado_Neto', 'Precio_Compra', 'Precio_Venta', 'Cantidad']
        for c in cols_num:
            if c in df.columns:
                df[c] = df[c].apply(_clean_number_str)
                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)
                if c == 'Resultado_Neto':
                    logs.append(f"Suma de Resultado_Neto tras limpieza: {df[c].sum()}")

        st.session_state['db_logs'] = logs # Guardar logs
        return df

    except Exception as e:
        logs.append(f"🔥 EXCEPCIÓN: {e}")
        st.session_state['db_logs'] = logs
        return pd.DataFrame()

def get_tickers_en_cartera():
    df = get_portafolio_df()
    return df['Ticker'].unique().tolist() if not df.empty else []
def get_favoritos(): return []
def add_transaction(d): return True, "Ok"
def registrar_venta(*a, **k): return False, "Mantenimiento"