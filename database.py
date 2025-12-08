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

def get_all_sheet_names():
    try:
        sh = _get_connection()
        return [ws.title for ws in sh.worksheets()]
    except: return []

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
        cols_num = ['Cantidad', 'Precio_Compra', 'Alerta_Alta', 'Alerta_Baja']
        for c in cols_num:
            if c in df.columns: df[c] = df[c].apply(_clean_number_str)
        if 'Cantidad' in df.columns: df = df[df['Cantidad'] > 0]
        return df
    except: return pd.DataFrame()

# --- LECTURA HISTORIAL (MODO DEBUG EXTREMO) ---
@st.cache_data(ttl=60, show_spinner=False)
@retry_api_call
def get_historial_df():
    logs = [] # Aquí acumularemos la evidencia forense
    logs.append("--- INICIO DE DEBUGGING ---")
    
    try:
        sh = _get_connection()
        worksheets = sh.worksheets()
        logs.append(f"Hojas encontradas: {[w.title for w in worksheets]}")
        
        target_ws = None
        
        # Iteramos hoja por hoja
        for i, ws in enumerate(worksheets):
            title = ws.title.strip()
            logs.append(f"\n[Analizando Hoja {i}: '{title}']")
            
            # Leemos headers
            try:
                headers = ws.row_values(1)
                logs.append(f"Headers Crudos: {headers}")
                headers_upper = [str(h).strip().upper() for h in headers]
            except Exception as e:
                logs.append(f"Error leyendo headers: {e}")
                continue

            # CRITERIO 1: Rechazo inmediato por columnas de Portafolio
            columnas_prohibidas = ['COOLDOWN_ALTA', 'ALERTA_ALTA', 'ALERTA_BAJA']
            encontro_prohibida = any(p in headers_upper for p in columnas_prohibidas)
            
            if encontro_prohibida:
                logs.append("❌ RECHAZADA: Detectadas columnas de Portafolio/Alertas.")
                continue

            # CRITERIO 2: Aceptación por Nombre
            if title.upper() == "HISTORIAL":
                logs.append("✅ SELECCIONADA: Coincidencia exacta de nombre 'Historial'.")
                target_ws = ws
                break
            
            # CRITERIO 3: Aceptación por Contenido (si el nombre falló)
            keywords = ["RESULT", "GANANCIA", "P&L", "NETO"]
            matches = [k for k in keywords if any(k in h for h in headers_upper)]
            
            if matches:
                logs.append(f"✅ SELECCIONADA: Encontradas palabras clave {matches}")
                target_ws = ws
                break
            else:
                logs.append("ℹ️ IGNORADA: No parece ser relevante.")

        if not target_ws:
            logs.append("\n❌ FATAL: Ninguna hoja pasó los filtros.")
            df_vacio = pd.DataFrame()
            df_vacio.attrs['debug_logs'] = logs
            return df_vacio

        # --- LECTURA ---
        logs.append(f"\n[Leyendo datos de: '{target_ws.title}']")
        data = target_ws.get_all_records()
        
        if not data: 
            logs.append("La hoja estaba vacía.")
            df = pd.DataFrame()
        else:
            df = pd.DataFrame(data)
            logs.append(f"Filas cargadas: {len(df)}")
            logs.append(f"Columnas iniciales: {list(df.columns)}")

            # Validación final de seguridad
            if 'CoolDown_Alta' in df.columns:
                logs.append("🚨 ERROR CRÍTICO: Gspread devolvió datos de Portafolio aunque seleccionamos Historial. Esto indica un problema grave de caché o índices.")
                # NO retornamos estos datos corruptos
                df = pd.DataFrame()
            else:
                # Normalización
                df.columns = [str(c).strip().replace(" ", "_") for c in df.columns]
                
                col_map = {}
                for c in df.columns:
                    cu = c.upper()
                    if "RESULTADO" in cu and "NETO" in cu: col_map[c] = 'Resultado_Neto'
                    elif "GANANCIA" in cu and "REALIZADA" in cu: col_map[c] = 'Resultado_Neto'
                    elif cu == "P&L": col_map[c] = 'Resultado_Neto'
                
                if col_map: 
                    df.rename(columns=col_map, inplace=True)
                    logs.append(f"Renombrado de columnas: {col_map}")

                # Limpieza numérica
                cols_num = ['Resultado_Neto', 'Precio_Compra', 'Precio_Venta', 'Cantidad']
                for c in cols_num:
                    if c in df.columns:
                        df[c] = df[c].apply(_clean_number_str)
                        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)

        # Adjuntar logs al dataframe (Truco para pasarlos al frontend)
        df.attrs['debug_logs'] = logs
        return df

    except Exception as e:
        logs.append(f"Excepción Global: {e}")
        df = pd.DataFrame()
        df.attrs['debug_logs'] = logs
        return df

# Funciones dummy
def get_tickers_en_cartera():
    df = get_portafolio_df()
    return df['Ticker'].unique().tolist() if not df.empty else []
def get_favoritos(): return []
def add_transaction(d): return True, "Ok"
def registrar_venta(*a, **k): return False, "Mantenimiento"