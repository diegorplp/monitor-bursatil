import gspread
import pandas as pd
import time
import streamlit as st
import re
from gspread.exceptions import APIError, WorksheetNotFound

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

# --- CONEXIÓN INTELIGENTE (VERSIÓN SABUESO) ---
def _get_worksheet(target_name_hint=None):
    try:
        if USE_CLOUD_AUTH: gc = gspread.service_account_from_dict(GOOGLE_CREDENTIALS_DICT)
        else: gc = gspread.service_account(filename=CREDENTIALS_FILE)
        
        sh = gc.open(SHEET_NAME)
        
        # Si no piden nombre, asumimos Portafolio (Hoja 0 o llamada Transacciones)
        if not target_name_hint:
            return sh.get_worksheet(0)

        # ESTRATEGIA DE BÚSQUEDA AGRESIVA
        keyword = target_name_hint.strip().upper() # EJ: "HISTORIAL"
        
        all_sheets = sh.worksheets()
        print(f"DEBUG: Hojas encontradas en Excel: {[s.title for s in all_sheets]}")

        # Intento 1: Coincidencia exacta ignorando espacios extra
        for ws in all_sheets:
            titulo_limpio = ws.title.strip().upper()
            if titulo_limpio == keyword:
                return ws
        
        # Intento 2: Contiene la palabra clave (Ej: "Historial de Ventas")
        for ws in all_sheets:
            if keyword in ws.title.upper():
                return ws
                
        # Si llegamos acá, falló.
        raise WorksheetNotFound(f"No se encontró hoja similar a '{target_name_hint}'")

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
        # Pedimos explícitamente "Transacciones" para evitar ambigüedad, si falla, usa índice 0
        try: ws = _get_worksheet("Transacciones")
        except: ws = _get_worksheet(None)
            
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

# --- LECTURA HISTORIAL (VERSIÓN BLINDADA) ---
@st.cache_data(ttl=60, show_spinner=False)
@retry_api_call
def get_historial_df():
    try:
        # 1. Buscar la hoja
        ws = _get_worksheet("Historial")
        data = ws.get_all_records()
        if not data: return pd.DataFrame()
        
        df = pd.DataFrame(data)
        
        # 2. VALIDACIÓN DE ADN (CRÍTICA)
        # Si la hoja que trajimos tiene columnas de alertas/cooldown, NO ES LA DE HISTORIAL.
        # Es probable que 'Transacciones' contenga la palabra 'Historial' o el buscador falló.
        columnas_prohibidas = ['CoolDown_Alta', 'CoolDown_Baja', 'Alerta_Alta']
        
        # Normalizamos nombres de columnas actuales para el chequeo
        cols_actuales_upper = [str(c).upper().strip() for c in df.columns]
        
        for prohibida in columnas_prohibidas:
            if prohibida.upper() in cols_actuales_upper:
                print(f"ERROR: Se cargó la hoja incorrecta ({ws.title}). Tiene columna {prohibida}.")
                # Si pasa esto, el código está leyendo Transacciones. Devolvemos vacío.
                return pd.DataFrame() 

        # 3. Normalizar columnas legítimas
        df.columns = [re.sub(r'\s+', '_', str(c).strip()) for c in df.columns]
        
        # 4. Mapeo de Resultado
        if 'Resultado_Neto' not in df.columns:
            # Tu Excel tiene "Resultado_Neto", así que debería entrar directo.
            # Pero si falla, buscamos variantes.
            candidatos = [c for c in df.columns if 'RESULT' in c.upper() or 'NETO' in c.upper()]
            if candidatos:
                df.rename(columns={candidatos[0]: 'Resultado_Neto'}, inplace=True)
        
        cols_num = ['Resultado_Neto', 'Precio_Compra', 'Precio_Venta', 'Cantidad', 'Costo_Total_Origen', 'Ingreso_Neto_Venta']
        for c in cols_num:
            if c in df.columns: df[c] = df[c].apply(_clean_number_str)
            
        return df
    except Exception as e:
        print(f"Error Historial: {e}")
        return pd.DataFrame()

def get_tickers_en_cartera():
    df = get_portafolio_df()
    if df.empty: return []
    return df['Ticker'].unique().tolist()

# --- ESCRITURA ---
@retry_api_call
def add_transaction(data):
    try:
        ws = _get_worksheet("Transacciones") # Explicitly ask for Transacciones
        row = [str(data['Ticker']), str(data['Fecha_Compra']), int(data['Cantidad']), float(data['Precio_Compra']), str(data.get('Broker', 'DEFAULT')), float(data.get('Alerta_Alta', 0.0)), float(data.get('Alerta_Baja', 0.0))]
        ws.append_row(row)
        clear_db_cache()
        return True, "Transacción agregada."
    except Exception as e: return False, f"Error: {e}"

@retry_api_call
def actualizar_alertas_lote(ticker, fecha_compra_str, nueva_alta, nueva_baja):
    try:
        ws = _get_worksheet("Transacciones")
        records = ws.get_all_records()
        idx_fila = -1
        for i, row in enumerate(records):
            if str(row['Ticker']).strip().upper() == str(ticker).strip().upper(): # Match simple
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
        ws_port = _get_worksheet("Transacciones")
        ws_hist = _get_worksheet("Historial")

        records = ws_port.get_all_records()
        fila_encontrada = None
        idx_fila = -1 
        
        for i, row in enumerate(records):
            r_tick = str(row['Ticker']).strip().upper()
            if not r_tick.endswith('.BA') and len(r_tick) < 9: r_tick += '.BA'
            if r_tick == ticker: # Match simple ticker
                fila_encontrada = row
                idx_fila = i + 2 
                break # Tomamos el primer lote FIFO por simplicidad si hay confusión de fechas
        
        if not fila_encontrada: return False, "Lote no encontrado."

        cant_tenencia = int(_clean_number_str(fila_encontrada['Cantidad']))
        precio_compra = _clean_number_str(fila_encontrada['Precio_Compra'])
        cant_vender = int(cantidad_a_vender)
        precio_vta = float(precio_venta)
        broker = str(fila_encontrada.get('Broker', 'DEFAULT'))
        
        if cant_vender > cant_tenencia: return False, "Cantidad insuficiente."

        es_bono = ticker in TICKERS_CONFIG.get('Bonos', [])
        divisor = 100 if es_bono else 1

        monto_compra_bruto = (precio_compra * cant_vender) / divisor
        monto_venta_bruto = (precio_vta * cant_vender) / divisor
        
        costo_entrada = _calcular_costo_operacion(monto_compra_bruto, broker)
        costo_salida = _calcular_costo_operacion(monto_venta_bruto, broker)
        
        costo_total_origen = monto_compra_bruto + costo_entrada
        ingreso_neto_venta = monto_venta_bruto - costo_salida
        resultado = ingreso_neto_venta - costo_total_origen

        row_h = [str(ticker), str(fecha_compra_str), precio_compra, str(fecha_venta_str), precio_vta, cant_vender, float(costo_total_origen), float(ingreso_neto_venta), float(resultado), broker, 0, 0]

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
        return list(set([str(v).strip().upper() for v in vals if v and str(v).upper() != "TICKER"]))
    except: return []

def add_favorito(t): return _generic_fav(t, "ADD") # Simplificado
def remove_favorito(t): return _generic_fav(t, "DEL") # Simplificado
def _generic_fav(ticker, action): # Placeholder para evitar errores de importación
    pass