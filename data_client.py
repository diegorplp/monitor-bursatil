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
CACHE_FILE = "data_cache/historical_data_v3.json" # V3 para asegurar limpieza
CACHE_DIR = "data_cache"

# --- TOKEN E IOL ---
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

# --- HISTÓRICO (YAHOO) - ESTRATEGIA CHUNKING (ANTI-RATE LIMIT) ---
def get_history_yahoo(tickers_list):
    tickers_filtrados = [t for t in tickers_list if t not in BONOS_SKIP_YAHOO]
    if not tickers_filtrados: return pd.DataFrame()
    
    start_date = datetime.now() - timedelta(days=DIAS_HISTORIAL + 10) 
    
    # 1. Preparar mapa de nombres
    map_yahoo_app = {}
    all_yahoo_tickers = []
    for t_app in tickers_filtrados:
        t_yahoo = t_app.upper()
        if not t_yahoo.endswith(".BA"): t_yahoo += ".BA"
        all_yahoo_tickers.append(t_yahoo)
        map_yahoo_app[t_yahoo] = t_app 

    # 2. Dividir en Chunks (Lotes) de 10 para no saturar
    CHUNK_SIZE = 10
    chunks = [all_yahoo_tickers[i:i + CHUNK_SIZE] for i in range(0, len(all_yahoo_tickers), CHUNK_SIZE)]
    
    st.toast(f"📡 Descargando {len(all_yahoo_tickers)} activos en {len(chunks)} lotes...", icon="⏳")
    
    full_dfs_list = []
    
    for i, chunk in enumerate(chunks):
        try:
            # Pausa táctica entre lotes
            if i > 0: time.sleep(1.5)
            
            df_chunk = yf.download(
                tickers=" ".join(chunk), 
                start=start_date, 
                group_by='ticker', 
                auto_adjust=True, 
                prepost=False, 
                threads=False, 
                progress=False, 
                timeout=20
            )
            
            if df_chunk.empty: continue

            # Procesar este lote
            chunk_series = []
            
            # Caso 1 ticker en el chunk
            if len(chunk) == 1:
                t_yahoo = chunk[0]
                col_name = 'Close' if 'Close' in df_chunk.columns else 'Adj Close'
                if col_name in df_chunk.columns:
                    serie = df_chunk[col_name].copy()
                    serie.name = map_yahoo_app[t_yahoo]
                    chunk_series.append(serie)
            # Caso N tickers
            else:
                for t_yahoo in chunk:
                    if t_yahoo in df_chunk.columns:
                        df_sub = df_chunk[t_yahoo]
                        col_name = 'Close' if 'Close' in df_sub.columns else 'Adj Close'
                        if col_name in df_sub.columns:
                            serie = df_sub[col_name].copy()
                            serie.name = map_yahoo_app[t_yahoo]
                            chunk_series.append(serie)
            
            if chunk_series:
                full_dfs_list.extend(chunk_series)
                
        except Exception as e:
            print(f"Error en chunk {i}: {e}")
            continue

    if not full_dfs_list:
        st.toast("⚠️ No se pudieron obtener datos históricos.", icon="⚠️")
        return pd.DataFrame()

    # 3. Unir todo
    df_final = pd.concat(full_dfs_list, axis=1)
    df_final = df_final.apply(pd.to_numeric, errors='coerce')
    df_final.replace(0, np.nan, inplace=True)
    
    if not df_final.empty and df_final.index.tz is not None:
        df_final.index = df_final.index.tz_localize(None)
    
    # CORRECCIÓN WARNING: Usar ffill() en lugar de fillna(method='ffill')
    return df_final.ffill()

# --- ORQUESTADOR PRINCIPAL ---
def get_data(lista_tickers=None):
    tickers_target = lista_tickers if lista_tickers else TICKERS
    if not tickers_target: return pd.DataFrame()
    today = pd.Timestamp.now().normalize()
    
    # 1. LEER CACHÉ
    usar_cache = False
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                cache_data = json.load(f)
                cache_date = datetime.strptime(cache_data['date'], '%Y-%m-%d').date()
                if cache_date == today.date():
                    df_check = pd.read_json(io.StringIO(cache_data['data']))
                    if not df_check.empty and len(df_check) > 10:
                        df_history = df_check
                        usar_cache = True
                        st.toast("📂 Datos cargados de caché", icon="✅")
        except: pass

    # 2. DESCARGA REAL (Si no hay caché)
    if not usar_cache:
        df_history = get_history_yahoo(tickers_target)
        
        # Guardar caché solo si tenemos datos útiles
        if not df_history.empty and len(df_history) > 10:
            try:
                if not os.path.exists(CACHE_DIR): os.makedirs(CACHE_DIR)
                cache_to_save = {'date': today.strftime('%Y-%m-%d'), 'data': df_history.to_json()}
                with open(CACHE_FILE, 'w') as f: json.dump(cache_to_save, f)
            except: pass

    # 3. MERGE CON IOL
    dict_precios_hoy = get_current_prices_iol(tickers_target)
    
    if df_history.empty:
        if not dict_precios_hoy: return pd.DataFrame()
        df_final = pd.DataFrame([dict_precios_hoy], index=[today])
    else:
        if df_history.index[-1].normalize() == today: 
            df_history = df_history.iloc[:-1]
            
        if dict_precios_hoy:
            row_today = pd.DataFrame([dict_precios_hoy], index=[today])
            df_final = pd.concat([df_history, row_today])
        else:
            df_final = df_history
    
    if df_final.empty: return pd.DataFrame()

    df_final.sort_index(inplace=True)
    df_final.ffill(inplace=True) # CORRECCIÓN WARNING
    
    cutoff = datetime.now() - timedelta(days=DIAS_HISTORIAL)
    df_final = df_final[df_final.index >= cutoff]

    return df_final