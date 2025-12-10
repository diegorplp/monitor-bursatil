import pandas as pd
import yfinance as yf
import requests
import concurrent.futures
from datetime import datetime, timedelta
import numpy as np 

pd.options.mode.chained_assignment = None 
IOL_BASE_URL = "https://api.invertironline.com"
IOL_TOKEN_URL = f"{IOL_BASE_URL}/token"
BONOS_SKIP_YAHOO = ['AL30.BA', 'AL30D.BA', 'GD30.BA', 'GD30D.BA', 'AE38.BA', 'AE38D.BA', 'AL29.BA', 'AL29D.BA', 'GD35.BA', 'GD35D.BA']

try:
    from config import TICKERS, DIAS_HISTORIAL, IOL_USER, IOL_PASSWORD
except ImportError:
    TICKERS = []
    DIAS_HISTORIAL = 200
    IOL_USER = ""
    IOL_PASSWORD = ""

# --- Funciones de Conversión de Nomenclatura Final ---
def _get_yahoo_symbol(ticker_with_suffix):
    """Retorna la simbología final para Yahoo (siempre .BA)."""
    return ticker_with_suffix.upper()

def _get_iol_symbol(ticker_with_suffix):
    """Retorna la simbología final para IOL (siempre sin sufijo)."""
    return ticker_with_suffix.upper().replace('.BA', '').replace('.C', '').replace('.L', '')

# --- [TOKEN E IOL OMITIDAS POR SER IDÉNTICAS] ---
def _get_iol_token():
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

def _fetch_iol_price(ticker_app, token):
    iol_symbol = _get_iol_symbol(ticker_app) 
    market = 'bCBA'
    url = f"{IOL_BASE_URL}/api/v2/{market}/Titulos/{iol_symbol}/Cotizacion"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.get(url, headers=headers, timeout=3) 
        r.raise_for_status()
        data = r.json()
        return ticker_app, float(data['ultimoPrecio'])
    except Exception as e:
        return ticker_app, None

def get_current_prices_iol(tickers_list):
    token = _get_iol_token()
    if not token: 
        print("Falla al obtener token IOL.")
        return {}
    
    print(f"   [IOL] Buscando precios en tiempo real para {len(tickers_list)} activos...")
    precios_iol = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor: 
        futures = {executor.submit(_fetch_iol_price, t, token): t for t in tickers_list}
        for future in concurrent.futures.as_completed(futures, timeout=15): 
            try:
                t, price = future.result()
                if price is not None:
                    precios_iol[t] = price
            except concurrent.futures.TimeoutError:
                print("TimeOut en descarga IOL.")
                break
            except Exception as e:
                continue
    return precios_iol

# --- HISTÓRICO (YAHOO) - ESTRATEGIA DE REINTENTO SIMPLE ---
def get_history_yahoo(tickers_list):
    """Descarga el histórico de cada ticker de forma individual y limpia los datos."""
    tickers_filtrados = [t for t in tickers_list if t not in BONOS_SKIP_YAHOO]
    if not tickers_filtrados: return pd.DataFrame()
    
    print(f"   [Yahoo] Iniciando descarga individual de {len(tickers_filtrados)} activos...")
    start_date = datetime.now() - timedelta(days=DIAS_HISTORIAL + 10) 
    df_close_list = []
    
    for t_app in tickers_filtrados:
        t_yahoo = _get_yahoo_symbol(t_app)
        serie = None
        
        # Lógica de Reintento
        for i in range(2): 
            try:
                df = yf.download(tickers=t_yahoo, start=start_date, group_by='ticker', auto_adjust=True, prepost=False, threads=False, progress=False, timeout=10) 
                
                if not df.empty:
                    col = 'Close' if 'Close' in df.columns else 'Adj Close'
                    if col in df.columns:
                        serie = df[col].rename(t_app) 
                        serie = pd.to_numeric(serie, errors='coerce')
                        serie.replace(0, np.nan, inplace=True) 
                        break # Si funciona, salimos del bucle de reintento
                    
            except Exception as e:
                print(f"Error Yahoo en {t_app} (Intento {i+1}): {e}")
                time.sleep(2) # Espera 2 segundos antes de reintentar
                
        if serie is not None:
            df_close_list.append(serie)

    if not df_close_list: return pd.DataFrame()

    df_final = pd.concat(df_close_list, axis=1)
    
    if not df_final.empty and df_final.index.tz is not None:
        df_final.index = df_final.index.tz_localize(None)
        
    return df_final.fillna(method='ffill')

# --- ORQUESTADOR PRINCIPAL (Mantenido) ---
def get_data(lista_tickers=None):
    tickers_target = lista_tickers if lista_tickers else TICKERS
    if not tickers_target: return pd.DataFrame()

    today = pd.Timestamp.now().normalize()
    
    dict_precios_hoy = get_current_prices_iol(tickers_target)
    
    if not dict_precios_hoy:
        return pd.DataFrame()

    df_history = get_history_yahoo(tickers_target)

    if df_history.empty:
        return pd.DataFrame([dict_precios_hoy], index=[today])

    if not df_history.empty and df_history.index[-1].normalize() == today:
        df_history = df_history.iloc[:-1]

    row_today = pd.DataFrame([dict_precios_hoy], index=[today])
    df_final = pd.concat([df_history, row_today])
    df_final.sort_index(inplace=True)
    df_final.ffill(inplace=True) 
    
    cutoff = datetime.now() - timedelta(days=DIAS_HISTORIAL)
    df_final = df_final[df_final.index >= cutoff]

    return df_final