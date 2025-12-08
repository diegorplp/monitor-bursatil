import pandas as pd
import yfinance as yf
import requests
import concurrent.futures
from datetime import datetime, timedelta

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

# --- TOKEN ---
def _get_iol_token():
    try:
        data = {"username": IOL_USER, "password": IOL_PASSWORD, "grant_type": "password"}
        r = requests.post(IOL_TOKEN_URL, data=data, timeout=5)
        r.raise_for_status()
        return r.json().get('access_token')
    except: return None

# --- MEP DETALLADO (PUNTAS) ---
def get_mep_detailed():
    """
    Descarga puntas de compra/venta para AL30 y AL30D para calcular spread.
    Retorna un diccionario con los valores.
    """
    token = _get_iol_token()
    if not token: return None

    assets = ['AL30', 'AL30D']
    resultados = {}
    
    for symbol in assets:
        url = f"{IOL_BASE_URL}/api/v2/bCBA/Titulos/{symbol}/Cotizacion"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            r = requests.get(url, headers=headers, timeout=5)
            if r.status_code == 200:
                data = r.json()
                # Guardamos Ultimo, y las Puntas
                puntas = data.get('puntas', {})
                resultados[symbol] = {
                    'last': float(data.get('ultimoPrecio', 0)),
                    'bid': float(puntas.get('compraPrecio', 0)) if puntas else 0,
                    'ask': float(puntas.get('ventaPrecio', 0)) if puntas else 0
                }
        except: pass
    
    return resultados

# --- PROCESO NORMAL (DF) ---
def _fetch_iol_price(ticker_yahoo, token):
    clean_symbol = ticker_yahoo.upper().replace('.BA', '')
    market = 'bCBA'
    url = f"{IOL_BASE_URL}/api/v2/{market}/Titulos/{clean_symbol}/Cotizacion"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            data = r.json()
            return ticker_yahoo, float(data['ultimoPrecio'])
    except: pass
    return ticker_yahoo, None

def get_current_prices_iol(tickers_list):
    token = _get_iol_token()
    if not token: return {}
    print(f"   [IOL] Buscando precios en tiempo real para {len(tickers_list)} activos...")
    precios_iol = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(_fetch_iol_price, t, token): t for t in tickers_list}
        for future in concurrent.futures.as_completed(futures):
            t, price = future.result()
            if price is not None:
                precios_iol[t] = price
    return precios_iol

def get_history_yahoo(tickers_list):
    tickers_filtrados = [t for t in tickers_list if t not in BONOS_SKIP_YAHOO]
    if not tickers_filtrados: return pd.DataFrame()
    print(f"   [Yahoo] Descargando histórico para {len(tickers_filtrados)} activos...")
    start_date = datetime.now() - timedelta(days=DIAS_HISTORIAL + 30)
    try:
        df = yf.download(tickers=tickers_filtrados, start=start_date, group_by='ticker', auto_adjust=True, prepost=False, threads=True, progress=False)
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

def get_data(lista_tickers=None):
    tickers_target = lista_tickers if lista_tickers else TICKERS
    if not tickers_target: return pd.DataFrame()

    df_history = get_history_yahoo(tickers_target)
    dict_precios_hoy = get_current_prices_iol(tickers_target)
    today = pd.Timestamp.now().normalize()

    if df_history.empty:
        if dict_precios_hoy:
            return pd.DataFrame([dict_precios_hoy], index=[today])
        return pd.DataFrame()

    if not df_history.empty and df_history.index[-1].normalize() == today:
        df_history = df_history.iloc[:-1]

    row_today = pd.DataFrame([dict_precios_hoy], index=[today])
    df_final = pd.concat([df_history, row_today])
    df_final.sort_index(inplace=True)
    df_final.ffill(inplace=True) 
    
    cutoff = datetime.now() - timedelta(days=DIAS_HISTORIAL)
    df_final = df_final[df_final.index >= cutoff]

    return df_final