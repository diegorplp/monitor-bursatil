import gspread
import pandas as pd
import time
import streamlit as st
import re
from gspread.exceptions import APIError, WorksheetNotFound
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
    else:
        tasa = COMISIONES.get(broker, 0.006)
        return monto_bruto * tasa

def _clean_number_str(val):
    """Limpieza agresiva de números."""
    if pd.isna(val) or val == "": return 0.0
    if isinstance(val, (int, float)): return float(val)
    
    s = str(val).strip()
    
    # Soporte para negativos contables entre paréntesis: (100) -> -100
    is_negative = False
    if s.startswith('(') and s.endswith(')'):
        is_negative = True
    
    # Eliminar todo excepto dígitos, puntos, comas y guiones
    s = re.sub(r'[^\d,.-]', '', s)
    
    if not s: return 0.0

    # Lógica de detección de formato decimal (Latam vs USA)
    if '.' in s and ',' in s:
        if s.rfind('.') < s.rfind(','): 
            s = s.replace('.', '').replace(',', '.') # Latam: 1.000,50 -> 1000.50
        else: 
            s = s.replace(',', '') # USA: 1,000.50 -> 1000.50
    elif ',' in s: 
        s = s.replace(',', '.') # Asumimos coma decimal si solo hay coma
    
    try: 
        num = float(s)
        return -num if is_negative else num
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

# --- CONEXIÓN INTELIGENTE ---
def _get_worksheet(name=None):
    try:
        if USE_CLOUD_AUTH:
            gc = gspread.service_account_from_dict(GOOGLE_CREDENTIALS_DICT)
        else:
            gc = gspread.service_account(filename=CREDENTIALS_FILE)
            
        sh = gc.open(SHEET_NAME)
        
        # Si no piden nombre, devolvemos la primera (Portafolio/Transacciones)
        if not name:
            return sh.get_worksheet(0)

        # Búsqueda Robusta
        target = name.strip().lower()
        lista_hojas = sh.worksheets()
        titulos = [ws.title for ws in lista_hojas]
        
        # 1. Búsqueda Exacta
        for ws in lista_hojas:
            if ws.title.strip().lower() == target:
                return ws
        
        # 2. Búsqueda Parcial ("Historial" encuentra "Historial de Ventas")
        for ws in lista_hojas:
            if target in ws.title.strip().lower():
                print(f"⚠️ AVISO: Usando hoja '{ws.title}' para búsqueda '{name}'")
                return ws
                
        print(f"ERROR CRÍTICO: No se encontró la pestaña '{name}'. Disponibles: {titulos}")
        raise WorksheetNotFound(f"Pestaña '{name}' no existe.")

    except Exception as e:
        print(f"ERROR CONEXIÓN: {e}")
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
        ws = _get_worksheet() # Default (Hoja 0)
        data = ws.get_all_records()
        if not data: return pd.DataFrame()

        df = pd.DataFrame(data)
        df.columns = [str(c).strip() for c in df.columns]
        
        # Validación mínima para asegurar que es la hoja correcta
        if 'Ticker' not in df.columns:
            return pd.DataFrame()

        def fix_ticker(t):
            t = str(t).strip().upper()
            if not t.endswith('.BA') and len(t) < 9 and len(t) > 0: return f"{t}.BA"
            return t
        df['Ticker'] = df['Ticker'].apply(fix_ticker)

        cols_defs = {'Broker': 'DEFAULT', 'Alerta_Alta': 0.0, 'Alerta_Baja': 0.0}
        for c, default in cols_defs.items():
            if c not in df.columns: df[c] = default

        for c in ['Cantidad', 'Precio_Compra', 'Alerta_Alta', 'Alerta_Baja']:
            if c in df.columns:
                df[c] = df[c].apply(_clean_number_str)
        
        if 'Cantidad' in df.columns:
            df = df[df['Cantidad'] > 0]
            
        df['Fecha_Compra'] = pd.to_datetime(df['Fecha_Compra'], errors='coerce')
        return df
    except Exception as e:
        print(f"Error Portafolio: {e}")
        return pd.DataFrame()

# --- LECTURA HISTORIAL ---
@st.cache_data(ttl=60, show_spinner=False)
@retry_api_call
def get_historial_df():
    try:
        # Busca explícitamente "Historial"
        ws = _get_worksheet("Historial")
        data = ws.get_all_records()
        if not data: return pd.DataFrame()
        
        df = pd.DataFrame(data)
        
        # Normalización de columnas: espacios a guiones bajos
        df.columns = [re.sub(r'\s+', '_', str(c).strip()) for c in df.columns]
        
        # Intento de corrección si no encuentra 'Resultado_Neto'
        if 'Resultado_Neto' not in df.columns:
            # Busca columnas candidatas
            candidatos = [c for c in df.columns if 'RESULTADO' in c.upper()]
            if candidatos:
                df.rename(columns={candidatos[0]: 'Resultado_Neto'}, inplace=True)
            else:
                print(f"ERROR: Hoja Historial leída ({ws.title}) pero SIN columna de resultado. Cols: {df.columns.tolist()}")
                # Retornamos vacío para evitar errores posteriores, o el DF crudo para debug
                return df 

        cols_num = ['Resultado_Neto', 'Precio_Compra', 'Precio_Venta', 'Cantidad']
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

# --- ESCRITURA (Mantenemos igual para no romper lógica) ---
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
            if r_tick == ticker: # Simplificado match fecha
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

        from config import TICKERS_CONFIG
        es_bono = ticker in TICKERS_CONFIG.get('Bonos', [])
        divisor = 100 if es_bono else 1

        monto_compra_bruto = (precio_compra * cant_vender) / divisor
        monto_venta_bruto = (precio_vta * cant_vender) / divisor
        
        costo_entrada = _calcular_costo_operacion(monto_compra_bruto, broker)
        costo_salida = _calcular_costo_operacion(monto_venta_bruto, broker)
        
        costo_total_origen = monto_compra_bruto + costo_entrada
        ingreso_neto_venta = monto_venta_bruto - costo_salida
        resultado = ingreso_neto_venta - costo_total_origen

        # Columnas Historial Estándar
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
        return False, "No encontrado."
    except Exception as e: return False, f"Error: {e}"