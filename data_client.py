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

# --- [FUNCIONES DE TOKEN E IOL OMITIDAS POR SER IDÉNTICAS] ---
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

def _fetch_iol_price(ticker_yahoo, token):
    clean_symbol = ticker_yahoo.upper().replace('.BA', '')
    market = 'bCBA'
    url = f"{IOL_BASE_URL}/api/v2/{market}/Titulos/{clean_symbol}/Cotizacion"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.get(url, headers=headers, timeout=3) 
        r.raise_for_status()
        data = r.json()
        return ticker_yahoo, float(data['ultimoPrecio'])
    except Exception as e:
        return ticker_yahoo, None

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

# --- HISTÓRICO (YAHOO) - ESTRATEGIA DE DESCARGA SEGURA FINAL ---
def get_history_yahoo(tickers_list):
    """Descarga el histórico de cada ticker de forma individual y limpia los datos."""
    tickers_filtrados = [t for t in tickers_list if t not in BONOS_SKIP_YAHOO]
    if not tickers_filtrados: return pd.DataFrame()
    
    print(f"   [Yahoo] Iniciando descarga individual de {len(tickers_filtrados)} activos...")
    start_date = datetime.now() - timedelta(days=DIAS_HISTORIAL + 10) 
    
    df_close_list = []
    
    # Bucle secuencial seguro: Si falla uno, el resto continúa
    for t in tickers_filtrados:
        try:
            df = yf.download(tickers=t, start=start_date, group_by='ticker', auto_adjust=True, prepost=False, threads=False, progress=False, timeout=10) 
            
            if not df.empty:
                # 1. Limpieza: Forzamos la columna y manejo de error
                col = 'Close' if 'Close' in df.columns else 'Adj Close'
                if col in df.columns:
                    serie = df[col].rename(t)
                    
                    # CRÍTICO: Limpieza de la Serie antes de agregar
                    serie = pd.to_numeric(serie, errors='coerce')
                    
                    # 2. Reemplazamos 0 por NaN para que FFILL funcione y no arruine los cálculos
                    serie.replace(0, np.nan, inplace=True) 
                    
                    df_close_list.append(serie)
                
        except Exception as e:
            # Registramos el fallo para el ticker específico
            print(f"Error Yahoo en {t}: {e}")
            continue

    if not df_close_list: return pd.DataFrame()

    # 3. Concatenamos, eliminamos el timezone, y rellenamos
    df_final = pd.concat(df_close_list, axis=1)
    
    if not df_final.empty and df_final.index.tz is not None:
        df_final.index = df_final.index.tz_localize(None)
        
    return df_final.fillna(method='ffill')

# --- ORQUESTADOR PRINCIPAL (Mantenido) ---
def get_data(lista_tickers=None):
    """
    Combina datos históricos (Yahoo) con precios de hoy (IOL).
    """
    tickers_target = lista_tickers if lista_tickers else TICKERS
    if not tickers_target: return pd.DataFrame()

    today = pd.Timestamp.now().normalize()
    
    dict_precios_hoy = get_current_prices_iol(tickers_target)
    
    if not dict_precios_hoy:
        return pd.DataFrame()

    df_history = get_history_yahoo(tickers_target)

    # Si Yahoo falló, usamos solo los precios de IOL
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