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
import random 

# CRÍTICO: Importamos database para leer la nueva fuente de datos histórica
import database 

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

# --- CONFIGURACIÓN DE CACHÉ (Mantenido solo por si es usado en otro lado, pero no para historial) ---
CACHE_FILE = "data_cache/historical_data_v4.json" 
CACHE_DIR = "data_cache"

# --- TOKEN E IOL (No Modificado) ---
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

# --- HISTÓRICO (YAHOO) - ELIMINADO/DEPRECADO (Devuelve vacío) ---
def get_history_yahoo(tickers_list):
    # La aplicación ya no debe llamar a Yahoo, lo hacemos en la VM y leemos de Sheets.
    return pd.DataFrame()

# --- ORQUESTADOR PRINCIPAL (MODIFICADO) ---
def get_data(lista_tickers=None):
    tickers_target = lista_tickers if lista_tickers else TICKERS
    if not tickers_target: return pd.DataFrame()
    today = pd.Timestamp.now().normalize()
    
    # 1. LEER HISTORIAL DESDE GOOGLE SHEETS
    df_history = database.get_historical_prices_df()
    
    if df_history.empty:
        pass
    else:
        st.toast("📂 Historial cargado de Google Sheets.", icon="✅")

    # 2. MERGE IOL (TIEMPO REAL)
    dict_precios_hoy = get_current_prices_iol(tickers_target)
    
    # Lógica de unión: IOL (hoy) + Sheets (histórico)
    if df_history.empty:
        if not dict_precios_hoy: return pd.DataFrame()
        df_final = pd.DataFrame([dict_precios_hoy], index=[today])
    else:
        # Aseguramos que el histórico de Sheets no tenga el precio de hoy (si el bot lo incluyó)
        if df_history.index[-1].normalize() == today: 
            df_history = df_history.iloc[:-1]
            
        if dict_precios_hoy:
            row_today = pd.DataFrame([dict_precios_hoy], index=[today])
            df_final = pd.concat([df_history, row_today])
        else:
            df_final = df_history
    
    if df_final.empty: return pd.DataFrame()

    df_final.sort_index(inplace=True)
    df_final.ffill(inplace=True) 
    
    cutoff = datetime.now() - timedelta(days=DIAS_HISTORIAL)
    df_final = df_final[df_final.index >= cutoff]

    return df_final