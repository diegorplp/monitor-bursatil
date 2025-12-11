import pandas as pd
import yfinance as yf
import requests
import concurrent.futures
from datetime import datetime, timedelta
import numpy as np
import os
import json 
import streamlit as st 
import time 
import io

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

# --- TOKEN E IOL (Idénticos) ---
def _get_iol_token():
    if not IOL_USER or not IOL_PASSWORD: return None
    try:
        data = {"username": IOL_USER, "password": IOL_PASSWORD, "grant_type": "password"}
        r = requests.post(IOL_TOKEN_URL, data=data, timeout=5)
        r.raise_for_status()
        return r.json().get('access_token')
    except: return None

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
    except: return ticker_app, None

def get_current_prices_iol(tickers_list):
    token = _get_iol_token()
    if not token: return {}
    
    precios_iol = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor: 
        futures = {executor.submit(_fetch_iol_price, t, token): t for t in tickers_list}
        for future in concurrent.futures.as_completed(futures, timeout=15): 
            try:
                t, price = future.result()
                if price is not None: precios_iol[t] = price
            except: continue
    return precios_iol

# --- HISTÓRICO (YAHOO) - MODO DEBUG & ROBUSTO ---
def get_history_yahoo(tickers_list):
    tickers_filtrados = [t for t in tickers_list if t not in BONOS_SKIP_YAHOO]
    if not tickers_filtrados: return pd.DataFrame()
    
    print(f"--- INICIO DEBUG YAHOO ---")
    print(f"1. Tickers solicitados ({len(tickers_filtrados)}): {tickers_filtrados}")

    start_date = datetime.now() - timedelta(days=DIAS_HISTORIAL + 10) 
    
    # 1. Preparar lista y mapa
    map_yahoo_app = {}
    batch_tickers = []
    
    for t_app in tickers_filtrados:
        t_yahoo = t_app.upper()
        if not t_yahoo.endswith(".BA"):
            t_yahoo += ".BA"
        batch_tickers.append(t_yahoo)
        map_yahoo_app[t_yahoo] = t_app 

    # 2. Sesión
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    })

    try:
        # 3. Descarga (Forzamos group_by='ticker' que es más predecible para depurar)
        print(f"2. Ejecutando yf.download para: {batch_tickers}")
        df_all = yf.download(
            tickers=" ".join(batch_tickers), 
            start=start_date, 
            group_by='ticker',  # CAMBIO: Usar 'ticker' agrupa mejor para iterar si falla la estructura
            auto_adjust=True, 
            prepost=False, 
            threads=True, 
            progress=False, 
            timeout=20,
            session=session
        )
        
        print(f"3. Shape recibido: {df_all.shape}")
        
        if df_all.empty: 
            print("!!! ERROR: DataFrame vacío devuelto por Yahoo.")
            return pd.DataFrame()

        # 4. Extracción Robusta
        df_close_list = []
        
        # Caso A: Un solo ticker (DataFrame simple)
        if len(batch_tickers) == 1:
            ticker_y = batch_tickers[0]
            col_name = 'Close' if 'Close' in df_all.columns else 'Adj Close'
            if col_name in df_all.columns:
                serie = df_all[col_name].copy()
                serie.name = map_yahoo_app[ticker_y]
                df_close_list.append(serie)
            else:
                print(f"!!! Falta columna Close/Adj Close para único ticker. Cols: {df_all.columns}")

        # Caso B: Múltiples tickers (MultiIndex: Ticker -> Precio)
        else:
            # df_all columns levels: (Ticker, PriceType) debido a group_by='ticker'
            for t_yahoo in batch_tickers:
                try:
                    # Intentar acceder al ticker en el nivel 0
                    if t_yahoo in df_all.columns:
                        df_sub = df_all[t_yahoo]
                        col_name = 'Close' if 'Close' in df_sub.columns else 'Adj Close'
                        
                        if col_name in df_sub.columns:
                            serie = df_sub[col_name].copy()
                            serie.name = map_yahoo_app[t_yahoo]
                            df_close_list.append(serie)
                        else:
                            print(f"Warning: Sin precio de cierre para {t_yahoo}")
                    else:
                        print(f"Warning: Ticker {t_yahoo} no encontrado en columnas devueltas.")
                except Exception as e:
                    print(f"Error procesando {t_yahoo}: {e}")
                    continue

        if not df_close_list:
            print("!!! ERROR: No se pudo extraer ninguna serie de precios válida.")
            return pd.DataFrame()

        df_final = pd.concat(df_close_list, axis=1)
        
        # 5. Limpieza final
        df_final = df_final.apply(pd.to_numeric, errors='coerce')
        df_final.replace(0, np.nan, inplace=True)
        
        if not df_final.empty and df_final.index.tz is not None:
            df_final.index = df_final.index.tz_localize(None)
            
        print(f"--- FIN DEBUG YAHOO (Éxito parcial/total: {df_final.shape}) ---")
        return df_final.fillna(method='ffill')

    except Exception as e:
        print(f"!!! EXCEPTION CRITICA EN YAHOO: {e}")
        return pd.DataFrame()

# --- ORQUESTADOR PRINCIPAL (CACHEADO JSON) ---
def get_data(lista_tickers=None):
    tickers_target = lista_tickers if lista_tickers else TICKERS
    if not tickers_target: return pd.DataFrame()
    today = pd.Timestamp.now().normalize()
    
    # 1. LEER CACHÉ JSON
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                cache_data = json.load(f)
                cache_date = datetime.strptime(cache_data['date'], '%Y-%m-%d').date()
                if cache_date == today.date():
                    df_history = pd.read_json(io.StringIO(cache_data['data'])) 
                    print("   [Cache] Histórico cargado de JSON.")
                    
                    dict_precios_hoy = get_current_prices_iol(tickers_target)
                    if not dict_precios_hoy: return pd.DataFrame() 
                    
                    row_today = pd.DataFrame([dict_precios_hoy], index=[today])
                    df_final = pd.concat([df_history, row_today])
                    df_final.sort_index(inplace=True)
                    df_final.ffill(inplace=True) 
                    
                    cutoff = datetime.now() - timedelta(days=DIAS_HISTORIAL)
                    return df_final[df_final.index >= cutoff]
        except: pass

    # 2. DESCARGA REAL (Si no hay caché)
    dict_precios_hoy = get_current_prices_iol(tickers_target)
    if not dict_precios_hoy: return pd.DataFrame()

    df_history = get_history_yahoo(tickers_target)

    if df_history.empty:
        df_final = pd.DataFrame([dict_precios_hoy], index=[today])
    else:
        if df_history.index[-1].normalize() == today: df_history = df_history.iloc[:-1]
        row_today = pd.DataFrame([dict_precios_hoy], index=[today])
        df_final = pd.concat([df_history, row_today])
    
    df_final.sort_index(inplace=True)
    df_final.ffill(inplace=True) 
    
    cutoff = datetime.now() - timedelta(days=DIAS_HISTORIAL)
    df_final = df_final[df_final.index >= cutoff]

    # 3. GUARDAR CACHÉ
    try:
        if not os.path.exists(CACHE_DIR): os.makedirs(CACHE_DIR)
        cache_to_save = {'date': today.strftime('%Y-%m-%d'), 'data': df_history.to_json()}
        with open(CACHE_FILE, 'w') as f: json.dump(cache_to_save, f)
    except: pass

    return df_final