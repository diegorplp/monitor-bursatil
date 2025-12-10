import pandas as pd
import yfinance as yf
import requests
import concurrent.futures
from datetime import datetime, timedelta
import numpy as np
import os
import json 
import streamlit as st 
import time # Para el sleep

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

# --- CONFIGURACIÓN DE CACHÉ ---
CACHE_FILE = "data_cache/historical_data.json"
CACHE_DIR = "data_cache"

# --- Funciones de TOKEN e IOL omitidas por ser idénticas ---
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
    iol_symbol = ticker_app.upper().replace('.BA', '').replace('.C', '').replace('.L', '')
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

def _get_yahoo_symbol(ticker_with_suffix):
    return ticker_with_suffix.upper()

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
        
        for i in range(2): 
            try:
                df = yf.download(tickers=t_yahoo, start=start_date, group_by='ticker', auto_adjust=True, prepost=False, threads=False, progress=False, timeout=10) 
                
                if not df.empty:
                    col = 'Close' if 'Close' in df.columns else 'Adj Close'
                    if col in df.columns:
                        serie = df[col].rename(t_app) 
                        serie = pd.to_numeric(serie, errors='coerce')
                        serie.replace(0, np.nan, inplace=True) 
                        break
                    
            except Exception as e:
                time.sleep(2)
                
        if serie is not None:
            df_close_list.append(serie)

    if not df_close_list: return pd.DataFrame()

    df_final = pd.concat(df_close_list, axis=1)
    
    if not df_final.empty and df_final.index.tz is not None:
        df_final.index = df_final.index.tz_localize(None)
        
    return df_final.fillna(method='ffill')

# --- ORQUESTADOR PRINCIPAL (CACHEADO) ---
# Quitamos el @st.cache_data de la función principal
def get_data(lista_tickers=None):
    tickers_target = lista_tickers if lista_tickers else TICKERS
    if not tickers_target: return pd.DataFrame()

    today = pd.Timestamp.now().normalize()
    
    # 1. INTENTO DE LECTURA DEL CACHÉ JSON (Persistencia de 1 día)
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                cache_data = json.load(f)
                cache_date = datetime.strptime(cache_data['date'], '%Y-%m-%d').date()
                
                # Si el archivo es de hoy, cargamos histórico (Cache de Supervivencia)
                if cache_date == today.date():
                    df_history = pd.read_json(cache_data['data'])
                    print("   [Cache] Histórico cargado de archivo JSON de hoy.")
                    
                    # 2. Obtener Precios de Hoy (Siempre Real Time)
                    dict_precios_hoy = get_current_prices_iol(tickers_target)
                    
                    if not dict_precios_hoy: return pd.DataFrame() # No hay precio hoy, no podemos calcular
                    
                    # Fusionar con la fila de hoy
                    row_today = pd.DataFrame([dict_precios_hoy], index=[today])
                    df_final = pd.concat([df_history, row_today])
                    
                    # Finalizar y retornar
                    df_final.sort_index(inplace=True)
                    df_final.ffill(inplace=True) 
                    
                    cutoff = datetime.now() - timedelta(days=DIAS_HISTORIAL)
                    df_final = df_final[df_final.index >= cutoff]
                    
                    return df_final
        except Exception as e:
            print(f"Error leyendo caché: {e}")

    # 2. SI EL CACHÉ FALLA/NO ES DE HOY: DESCARGA COMPLETA
    print("   [Descarga] Iniciando descarga completa de APIs...")
    dict_precios_hoy = get_current_prices_iol(tickers_target)
    
    if not dict_precios_hoy:
        return pd.DataFrame()

    df_history = get_history_yahoo(tickers_target)

    # 3. FUSIÓN Y ESCRITURA
    if df_history.empty:
        df_final = pd.DataFrame([dict_precios_hoy], index=[today])
    else:
        if df_history.index[-1].normalize() == today:
            df_history = df_history.iloc[:-1]
        row_today = pd.DataFrame([dict_precios_hoy], index=[today])
        df_final = pd.concat([df_history, row_today])
    
    df_final.sort_index(inplace=True)
    df_final.ffill(inplace=True) 
    
    cutoff = datetime.now() - timedelta(days=DIAS_HISTORIAL)
    df_final = df_final[df_final.index >= cutoff]

    # 4. ESCRIBIR EL CACHÉ JSON (Cache de Supervivencia)
    try:
        if not os.path.exists(CACHE_DIR): os.makedirs(CACHE_DIR)
        
        # Solo guardamos el histórico (Yahoo)
        cache_to_save = {
            'date': today.strftime('%Y-%m-%d'),
            'data': df_history.to_json() 
        }
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache_to_save, f)
            print("   [Cache] Archivo JSON de histórico escrito correctamente.")
    except Exception as e:
        print(f"Error escribiendo caché: {e}")


    return df_final