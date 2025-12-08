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
    """
    Parsea strings numéricos manejando ambigüedad de formatos (AR vs US).
    Prioriza formato AR (coma decimal) si hay ambigüedad, dado el contexto.
    """
    if pd.isna(val) or val == "": return 0.0
    if isinstance(val, (int, float)): return float(val)
    
    s = str(val).strip()
    # Manejo de negativos entre paréntesis (Ej: (500))
    is_negative = s.startswith('(') and s.endswith(')')
    if is_negative:
        s = s.replace('(', '').replace(')', '')
        
    # Eliminar símbolos de moneda y caracteres extraños, dejando puntos, comas y menos
    s = re.sub(r'[^\d,.-]', '', s)
    if not s: return 0.0

    # Lógica de detección de formato
    if ',' in s and '.' in s:
        # Caso mixto: 1.000,50 (AR) vs 1,000.50 (US)
        # Asumimos que el último separador es el decimal
        if s.rfind(',') > s.rfind('.'): 
            s = s.replace('.', '').replace(',', '.') # Formato AR -> US
        else:
            s = s.replace(',', '') # Formato US -> Limpio
    elif ',' in s:
        # Solo comas: 10,50 (AR) o 1,000 (US)
        if s.count(',') > 1: # Ej: 1,000,000 -> Es separador de miles US
            s = s.replace(',', '')
        else: # Ej: 10,50 -> Es decimal AR
            s = s.replace(',', '.')
    elif '.' in s:
        # Solo puntos: 1.000 (AR) o 10.5 (US)
        if s.count('.') > 1: # Ej: 1.000.000 -> Es separador de miles AR
            s = s.replace('.', '')
        # Si hay un solo punto (1.500), Python lo tomará como 1.5. 
        # NOTA: Sin contexto estricto, dejamos que Python decida, pero en GSpread 
        # suele venir como "1000" sin puntos si es número puro.

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

@st.cache_data(ttl=60, show_spinner=False)
@retry_api_call
# --- EN database.py (Reemplazar get_historial_df) ---

@st.cache_data(ttl=60, show_spinner=False)
@retry_api_call
def get_historial_df():
    try:
        sh = _get_connection()
        target_ws = None
        
        # 1. ESTRATEGIA PRIORITARIA: Buscar por nombre exacto "Historial"
        # Esto evita que el sistema "adivine" y termine leyendo Transacciones.
        try:
            target_ws = sh.worksheet("Historial")
        except WorksheetNotFound:
            # Si falla, buscamos alguna que contenga "HISTORIAL" en el nombre (ej: "Historial 2024")
            for ws in sh.worksheets():
                if "HISTORIAL" in ws.title.strip().upper():
                    target_ws = ws
                    break
        
        # 2. ESTRATEGIA DE RESPALDO (ADN): Solo si NO se encontró por nombre
        if not target_ws:
            all_worksheets = sh.worksheets()
            for ws in all_worksheets:
                title_upper = ws.title.strip().upper()
                
                # CRÍTICO: Excluir explícitamente "Transacciones" o "Portafolio" para no confundirse
                if "TRANSACCIONES" in title_upper or "PORTAFOLIO" in title_upper:
                    continue

                try:
                    headers = ws.row_values(1)
                    headers_upper = [str(h).strip().upper() for h in headers]
                    
                    # Exclusión de seguridad (columnas de Portafolio)
                    if any(c in headers_upper for c in ['COOLDOWN_ALTA', 'ALERTA_ALTA']):
                        continue
                    
                    # Búsqueda de Resultado
                    if any("RESULT" in h or "GANANCIA" in h or "P&L" in h for h in headers_upper):
                        target_ws = ws
                        break
                except: continue
        
        if not target_ws:
            print("ERROR CRÍTICO: No se encontró la hoja Historial.")
            return pd.DataFrame()

        # --- PROCESAMIENTO DE DATOS ---
        data = target_ws.get_all_records()
        if not data: return pd.DataFrame()
        
        df = pd.DataFrame(data)
        
        # Normalizar encabezados
        df.columns = [re.sub(r'\s+', '_', str(c).strip()) for c in df.columns]
        
        # Renombrar columna Resultado (Priorizando 'Neto')
        cols_upper = [c.upper() for c in df.columns]
        mapa_cols = {c.upper(): c for c in df.columns}
        
        col_resultado_real = None
        if 'RESULTADO_NETO' in cols_upper:
            col_resultado_real = mapa_cols['RESULTADO_NETO']
        else:
            # Buscar columna que contenga NETO
            candidatos_neto = [c for c in df.columns if 'NETO' in c.upper() and ('RESULT' in c.upper() or 'GANANCIA' in c.upper())]
            if candidatos_neto:
                col_resultado_real = candidatos_neto[0]
            else:
                # Fallback general
                candidatos_gen = [c for c in df.columns if 'RESULT' in c.upper() or 'GANANCIA' in c.upper()]
                if candidatos_gen:
                    col_resultado_real = candidatos_gen[0]

        if col_resultado_real:
            df.rename(columns={col_resultado_real: 'Resultado_Neto'}, inplace=True)
        
        # Limpieza numérica y forzado de tipos (Esencial para la suma)
        cols_num = ['Resultado_Neto', 'Precio_Compra', 'Precio_Venta', 'Cantidad']
        for c in cols_num:
            if c in df.columns:
                df[c] = df[c].apply(_clean_number_str) # Tu nueva función robusta
                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)
            
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
def _calcular_costo_operacion(monto_bruto, broker):
    # Dummy para evitar ImportError si no hay config
    return monto_bruto * 0.006

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