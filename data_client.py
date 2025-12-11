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

# --- HISTÓRICO (YAHOO) - OPTIMIZADO PARA NO BLOQUEAR IP ---
def get_history_yahoo(tickers_list):
    tickers_filtrados = [t for t in tickers_list if t not in BONOS_SKIP_YAHOO]
    if not tickers_filtrados: return pd.DataFrame()
    
    print(f"   [Yahoo] Descargando {len(tickers_filtrados)} activos (Modo Seguro)...")
    start_date = datetime.now() - timedelta(days=DIAS_HISTORIAL + 10) 
    
    df_close_list = []
    
    for t_app in tickers_filtrados:
        # ESTRATEGIA DE UN SOLO TIRO: Usamos siempre .BA (Ganador del diagnóstico)
        # Esto reduce las peticiones a la mitad o tercio.
        t_yahoo = t_app.upper()
        if not t_yahoo.endswith(".BA"):
            t_yahoo += ".BA"

        try:
            # Sin reintentos agresivos
            df = yf.download(tickers=t_yahoo, start=start_date, group_by='ticker', auto_adjust=True, prepost=False, threads=False, progress=False, timeout=10) 
            
            if not df.empty:
                col = 'Close' if 'Close' in df.columns else 'Adj Close'
                if col in df.columns:
                    serie = df[col].rename(t_app) 
                    serie = pd.to_numeric(serie, errors='coerce')
                    # Convertir 0 a NaN para que ffill funcione
                    serie.replace(0, np.nan, inplace=True) 
                    df_close_list.append(serie)
                
        except Exception:
            # Si falla, simplemente pasamos al siguiente para no detener el flujo
            continue

    if not df_close_list: return pd.DataFrame()

    df_final = pd.concat(df_close_list, axis=1)
    if not df_final.empty and df_final.index.tz is not None:
        df_final.index = df_final.index.tz_localize(None)
        
    return df_final.fillna(method='ffill')

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