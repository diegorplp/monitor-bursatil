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
    is_negative = s.startswith('(') and s.endswith(')') or s.startswith('-') # Soporte explícito para negativos
    if is_negative: s = s.replace('(', '').replace(')', '').replace('-', '')
    
    s = re.sub(r'[^\d,.-]', '', s) 
    if not s: return 0.0
    
    # Detección de formato
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

# --- LECTURA HISTORIAL (CORREGIDO PARA TU SHEET) ---
# Sin caché para debug instantáneo
@retry_api_call
def get_historial_df():
    logs = [f"--- DEBUG {time.strftime('%H:%M:%S')} ---"]
    
    try:
        sh = _get_connection()
        worksheets = sh.worksheets()
        target_ws = None
        
        # 1. BÚSQUEDA POR NOMBRE (PRIORIDAD ABSOLUTA)
        # Si se llama "Historial", ignoramos qué columnas tiene. ¡Es la correcta!
        for ws in worksheets:
            title = ws.title.strip().upper()
            if "HISTORIAL" in title:
                target_ws = ws
                logs.append(f"✅ Hoja '{ws.title}' seleccionada por nombre (Inmunidad a filtros).")
                break
        
        # 2. BÚSQUEDA POR CONTENIDO (SOLO SI FALLÓ LA ANTERIOR)
        if not target_ws:
            logs.append("⚠️ No encontré hoja llamada 'Historial'. Buscando por contenido...")
            for ws in worksheets:
                try:
                    headers = [str(h).upper() for h in ws.row_values(1)]
                    # Aquí sí filtramos si tiene CoolDown PERO NO Alertas (porque tu historial tiene alertas)
                    if "COOLDOWN_ALTA" in headers: 
                        continue 
                    if any(k in h for h in headers for k in ["RESULT", "GANANCIA", "P&L"]):
                        target_ws = ws
                        break
                except: continue

        if not target_ws:
            logs.append("❌ FATAL: No se encontró la hoja.")
            st.session_state['db_logs'] = logs
            return pd.DataFrame()

        # LECTURA DE DATOS
        data = target_ws.get_all_records()
        if not data:
            logs.append("⚠️ Hoja vacía.")
            st.session_state['db_logs'] = logs
            return pd.DataFrame()
        
        df = pd.DataFrame(data)
        logs.append(f"Filas: {len(df)}")

        # Normalización de Nombres de Columnas
        df.columns = [str(c).strip().replace(" ", "_") for c in df.columns]
        
        # Mapeo Inteligente (Tu hoja usa 'Resultado_Neto', esto debería detectarlo directo)
        col_map = {}
        for c in df.columns:
            cu = c.upper()
            if "RESULTADO" in cu and "NETO" in cu: col_map[c] = 'Resultado_Neto'
            elif "GANANCIA" in cu and "REALIZADA" in cu: col_map[c] = 'Resultado_Neto'
        
        if col_map: 
            df.rename(columns=col_map, inplace=True)
            logs.append(f"Renombrado: {col_map}")
        
        if 'Resultado_Neto' not in df.columns:
             logs.append(f"⚠️ NO VEO 'Resultado_Neto'. Columnas actuales: {list(df.columns)}")

        # Limpieza Numérica (IMPORTANTE: Limpiar Alertas también para que no explote Arrow)
        cols_num = ['Resultado_Neto', 'Precio_Compra', 'Precio_Venta', 'Cantidad', 'Alerta_Alta', 'Alerta_Baja', 'Costo_Total_Origen', 'Ingreso_Total_Venta']
        for c in cols_num:
            if c in df.columns:
                df[c] = df[c].apply(_clean_number_str)
                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)

        if 'Resultado_Neto' in df.columns:
            logs.append(f"SUMA FINAL RESULTADO: {df['Resultado_Neto'].sum()}")

        st.session_state['db_logs'] = logs
        return df

    except Exception as e:
        logs.append(f"🔥 Error Global: {e}")
        st.session_state['db_logs'] = logs
        return pd.DataFrame()

def get_tickers_en_cartera():
    df = get_portafolio_df()
    return df['Ticker'].unique().tolist() if not df.empty else []
def get_favoritos(): return []
def add_transaction(d): return True, "Ok"
def registrar_venta(*a, **k): return False, "Mantenimiento"