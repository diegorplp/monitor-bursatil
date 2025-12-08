import gspread
import pandas as pd
from datetime import datetime
try:
    # IMPORTAMOS LAS VARIABLES CLAVE DE LA NUBE
    from config import SHEET_NAME, CREDENTIALS_FILE, USE_CLOUD_AUTH, GOOGLE_CREDENTIALS_DICT, COMISIONES, IVA, DERECHOS_MERCADO, VETA_MINIMO
except ImportError:
    # Fallback por si ejecutas esto suelto
    SHEET_NAME = ""
    CREDENTIALS_FILE = ""
    USE_CLOUD_AUTH = False
    GOOGLE_CREDENTIALS_DICT = {}
    COMISIONES = {}
    IVA = 1.21
    DERECHOS_MERCADO = 0.0008
    VETA_MINIMO = 50

# --- LÓGICA DE COMISIONES (Privada) ---
def _calcular_costo_operacion(monto_bruto, broker):
    broker = str(broker).upper().strip()
    if broker == 'VETA':
        TASA = 0.0015
        comision_base = max(VETA_MINIMO, monto_bruto * TASA)
        gastos = (comision_base * IVA) + (monto_bruto * DERECHOS_MERCADO)
        return gastos
    elif broker == 'COCOS':
        return monto_bruto * DERECHOS_MERCADO
    else:
        tasa = COMISIONES.get(broker, 0.006)
        return monto_bruto * tasa

# --- CONEXIÓN INTELIGENTE (CLOUD vs LOCAL) ---
def _get_worksheet(name=None):
    try:
        if USE_CLOUD_AUTH:
            # ESTAMOS EN LA NUBE: Usamos el diccionario de secretos
            # Nota: service_account_from_dict es el método correcto
            gc = gspread.service_account_from_dict(GOOGLE_CREDENTIALS_DICT)
        else:
            # ESTAMOS EN CASA: Usamos el archivo físico
            gc = gspread.service_account(filename=CREDENTIALS_FILE)
            
        sh = gc.open(SHEET_NAME)
        if name: return sh.worksheet(name)
        return sh.get_worksheet(0)
    except Exception as e:
        # En producción conviene propagar el error para verlo en el log
        print(f"ERROR CONEXIÓN SHEETS: {e}")
        raise e

# --- LECTURA ---
def get_portafolio_df():
    # Volvemos al try-except normal para producción, pero si falla, 
    # _get_worksheet lanzará la excepción arriba.
    try:
        ws = _get_worksheet()
        data = ws.get_all_records()
        
        if not data: return pd.DataFrame()

        df = pd.DataFrame(data)
        df.columns = [c.strip() for c in df.columns]
        
        expected = ['Ticker', 'Fecha_Compra', 'Cantidad', 'Precio_Compra']
        if not all(c in df.columns for c in expected): return pd.DataFrame()

        def fix_ticker(t):
            t = str(t).strip().upper()
            if not t.endswith('.BA') and len(t) < 9: return f"{t}.BA"
            return t
        df['Ticker'] = df['Ticker'].apply(fix_ticker)

        if 'Broker' not in df.columns: df['Broker'] = 'DEFAULT'
        if 'Alerta_Alta' not in df.columns: df['Alerta_Alta'] = 0.0
        if 'Alerta_Baja' not in df.columns: df['Alerta_Baja'] = 0.0

        df['Cantidad'] = pd.to_numeric(df['Cantidad'], errors='coerce')
        df['Precio_Compra'] = pd.to_numeric(df['Precio_Compra'], errors='coerce')
        df['Alerta_Alta'] = pd.to_numeric(df['Alerta_Alta'], errors='coerce').fillna(0.0)
        df['Alerta_Baja'] = pd.to_numeric(df['Alerta_Baja'], errors='coerce').fillna(0.0)
        
        df.dropna(subset=['Ticker', 'Cantidad', 'Precio_Compra'], inplace=True)
        df['Fecha_Compra'] = pd.to_datetime(df['Fecha_Compra'], errors='coerce')

        return df
    except Exception as e:
        print(f"ERROR LEYENDO DB: {e}")
        # Si es error de conexión, dejamos que suba para verlo en la app
        if "FileNotFound" in str(e) or "gspread" in str(e): raise e
        return pd.DataFrame()

def get_historial_df():
    try:
        ws = _get_worksheet("Historial")
        data = ws.get_all_records()
        if not data: return pd.DataFrame()
        df = pd.DataFrame(data)
        cols_num = ['Resultado_Neto', 'Precio_Compra', 'Precio_Venta', 'Cantidad']
        for c in cols_num:
            if c in df.columns: df[c] = pd.to_numeric(df[c], errors='coerce')
        return df
    except: return pd.DataFrame() 

def get_tickers_en_cartera():
    df = get_portafolio_df()
    if df.empty: return []
    return df['Ticker'].unique().tolist()

# --- ESCRITURA ---
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
        return True, "Transacción agregada exitosamente."
    except Exception as e:
        return False, f"Error al guardar: {e}"

def actualizar_alertas_lote(ticker, fecha_compra_str, nueva_alta, nueva_baja):
    try:
        ws = _get_worksheet()
        records = ws.get_all_records()
        idx_fila = -1
        
        for i, row in enumerate(records):
            r_tick = str(