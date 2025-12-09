import pandas as pd
import yfinance as yf
import requests
import concurrent.futures
from datetime import datetime, timedelta

pd.options.mode.chained_assignment = None 
IOL_BASE_URL = "https://api.invertironline.com"
IOL_TOKEN_URL = f"{IOL_BASE_URL}/token"
BONOS_SKIP_YAHOO = ['AL30.BA', 'AL30D.BA', 'GD30.BA', 'GD30D.BA', 'AE38.BA', 'AE38D.BA', 'AL29.BA', 'AL29D.BA', 'GD35.BA', 'GD35D.BA']

# Carga segura de variables (mejor que un bloque try/except)
try:
    from config import TICKERS, DIAS_HISTORIAL, IOL_USER, IOL_PASSWORD
except ImportError:
    TICKERS = []
    DIAS_HISTORIAL = 200
    IOL_USER = ""
    IOL_PASSWORD = ""

# --- TOKEN ---
def _get_iol_token():
    """Obtiene el token IOL con manejo de errores explícito."""
    if not IOL_USER or not IOL_PASSWORD: return None
    try:
        data = {"username": IOL_USER, "password": IOL_PASSWORD, "grant_type": "password"}
        r = requests.post(IOL_TOKEN_URL, data=data, timeout=5)
        r.raise_for_status()
        return r.json().get('access_token')
    except requests.exceptions.RequestException as e:
        print(f"Error IOL Token (API/Conexión): {e}")
        return None
    except Exception as e:
        print(f"Error IOL Token (JSON/Otro): {e}")
        return None

# --- PRECIOS EN TIEMPO REAL (IOL) ---
def _fetch_iol_price(ticker_yahoo, token):
    """Obtiene precio de un solo ticker desde IOL."""
    clean_symbol = ticker_yahoo.upper().replace('.BA', '')
    market = 'bCBA'
    url = f"{IOL_BASE_URL}/api/v2/{market}/Titulos/{clean_symbol}/Cotizacion"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        # TimeOut más agresivo para no congelar
        r = requests.get(url, headers=headers, timeout=3) 
        r.raise_for_status() # Lanza excepción si el status no es 2xx
        data = r.json()
        return ticker_yahoo, float(data['ultimoPrecio'])
    except Exception as e:
        # print(f"Error IOL {ticker_yahoo}: {e}")
        return ticker_yahoo, None

def get_current_prices_iol(tickers_list):
    """Descarga concurrente de precios IOL."""
    token = _get_iol_token()
    if not token: 
        print("Falla al obtener token IOL.")
        return {}
    
    print(f"   [IOL] Buscando precios en tiempo real para {len(tickers_list)} activos...")
    precios_iol = {}
    # Aumentamos los workers por si es problema de concurrencia
    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as executor: 
        futures = {executor.submit(_fetch_iol_price, t, token): t for t in tickers_list}
        for future in concurrent.futures.as_completed(futures, timeout=10): # TimeOut global
            try:
                t, price = future.result()
                if price is not None:
                    precios_iol[t] = price
            except concurrent.futures.TimeoutError:
                print("TimeOut en descarga IOL.")
                break # Detenemos si hay TimeOut
            except Exception as e:
                # print(f"Error en hilo IOL: {e}")
                continue
    return precios_iol

# --- HISTÓRICO (YAHOO) ---
def get_history_yahoo(tickers_list):
    """Descarga histórico de Yahoo con filtro de tickers y días."""
    tickers_filtrados = [t for t in tickers_list if t not in BONOS_SKIP_YAHOO]
    if not tickers_filtrados: return pd.DataFrame()
    
    print(f"   [Yahoo] Descargando histórico para {len(tickers_filtrados)} activos...")
    # Reducimos los días para no saturar a Yahoo (era DIAS_HISTORIAL + 30)
    start_date = datetime.now() - timedelta(days=DIAS_HISTORIAL + 10) 
    
    try:
        # Usamos download_yahoo_data (función alternativa más robusta si la principal falla)
        df = yf.download(tickers=tickers_filtrados, start=start_date, group_by='ticker', auto_adjust=True, prepost=False, threads=True, progress=False, timeout=15)
        
        # Lógica de limpieza de Yahoo (Mantenida)
        df_close = pd.DataFrame()
        if len(tickers_filtrados) == 1:
            t = tickers_filtrados[0]
            col = 'Close' if 'Close' in df.columns else 'Adj Close'
            if col in df.columns: df_close[t] = df[col]
        else:
            for t in tickers_filtrados:
                try:
                    if t in df.columns.levels[0]: df_close[t] = df[t]['Close']
                except: pass
        
        if not df_close.empty and df_close.index.tz is not None:
            df_close.index = df_close.index.tz_localize(None)
        return df_close
    except Exception as e:
        print(f"Error Yahoo: {e}")
        return pd.DataFrame()

# --- ORQUESTADOR PRINCIPAL ---
def get_data(lista_tickers=None):
    """Combina datos históricos (Yahoo) con precios de hoy (IOL)."""
    tickers_target = lista_tickers if lista_tickers else TICKERS
    if not tickers_target: return pd.DataFrame()

    # Descarga concurrente
    df_history = get_history_yahoo(tickers_target)
    dict_precios_hoy = get_current_prices_iol(tickers_target)
    
    today = pd.Timestamp.now().normalize()

    # Caso 1: No hay histórico (solo precios de hoy)
    if df_history.empty:
        if dict_precios_hoy:
            return pd.DataFrame([dict_precios_hoy], index=[today])
        return pd.DataFrame()

    # Caso 2: Hay histórico y hay que añadir precios de hoy
    # Eliminar la última fila si ya corresponde a 'hoy' (para no duplicar)
    if not df_history.empty and df_history.index[-1].normalize() == today:
        df_history = df_history.iloc[:-1]

    # Fusionar
    row_today = pd.DataFrame([dict_precios_hoy], index=[today])
    df_final = pd.concat([df_history, row_today])
    df_final.sort_index(inplace=True)
    df_final.ffill(inplace=True) 
    
    # Filtro de días
    cutoff = datetime.now() - timedelta(days=DIAS_HISTORIAL)
    df_final = df_final[df_final.index >= cutoff]

    return df_final