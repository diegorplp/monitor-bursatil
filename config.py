import streamlit as st
import os

# --- LÓGICA HÍBRIDA DE SECRETOS ---
try:
    # 1. Intentamos leer desde la Nube
    IOL_USER = st.secrets["IOL_USER"]
    IOL_PASSWORD = st.secrets["IOL_PASSWORD"]
    SHEET_NAME = st.secrets["SHEET_NAME"]
    
    # 2. Reconstruimos el diccionario de credenciales
    GOOGLE_CREDENTIALS_DICT = dict(st.secrets["gcp_service_account"])

    # --- FIX CRÍTICO PARA NUBE ---
    # Reemplazamos los caracteres '\\n' literales por saltos de línea reales '\n'
    # Sin esto, gspread rechaza la llave privada en Linux/Cloud.
    if "private_key" in GOOGLE_CREDENTIALS_DICT:
        private_key = GOOGLE_CREDENTIALS_DICT["private_key"]
        GOOGLE_CREDENTIALS_DICT["private_key"] = private_key.replace("\\n", "\n")
    
    USE_CLOUD_AUTH = True 

except (FileNotFoundError, KeyError):
    # --- MODO LOCAL (TU PC) ---
    USE_CLOUD_AUTH = False
    GOOGLE_CREDENTIALS_DICT = None
    
    # TUS DATOS REALES (MANTENLOS ACÁ PARA TU PC)
    IOL_USER = "diego_rp_94@live.com"
    IOL_PASSWORD = "*iI213322"
    SHEET_NAME = "para_streamlit"
    CREDENTIALS_FILE = "carbon-broker-479906-a2-157f549dc6b7.json"

# --- CONFIGURACIÓN GENERAL ---
DIAS_HISTORIAL = 200

# COSTOS
IVA = 1.21
DERECHOS_MERCADO = 0.0008
VETA_MINIMO = 50

COMISIONES = {
    'IOL': 0.006,
    'BULL': 0.006,
    'COCOS': 0.006,
    'VETA': 0.002, 
    'DEFAULT': 0.006
}

TICKERS_CONFIG = {
    'Favoritos': ['GGAL.BA', 'YPFD.BA', 'AL30.BA', 'GD30.BA'],
    'Lider': [
        'ALUA.BA', 'BBAR.BA', 'BMA.BA', 'BYMA.BA', 'CEPU.BA', 'COME.BA', 
        'CRES.BA', 'EDN.BA', 'GGAL.BA', 'LOMA.BA', 'MIRG.BA', 'PAMP.BA', 
        'SUPV.BA', 'TECO2.BA', 'TGNO4.BA', 'TGSU2.BA', 'TRAN.BA', 'TXAR.BA', 
        'VALO.BA', 'YPFD.BA'
    ],
    'General': ['BHIP.BA', 'BPAT.BA', 'BOLT.BA', 'LEDE.BA', 'MOLI.BA', 'SEMI.BA'],
    'Cedears': [
        'AAPL.BA', 'AMD.BA', 'AMZN.BA', 'BABA.BA', 'DIS.BA', 'GOOGL.BA', 
        'KO.BA', 'MELI.BA', 'MSFT.BA', 'NVDA.BA', 'QCOM.BA', 'SPY.BA', 
        'TSLA.BA', 'VIST.BA', 'X.BA'
    ],
    'Bonos': ['AL30.BA', 'AL30D.BA', 'GD30.BA', 'GD30D.BA', 'AE38.BA', 'AE38D.BA']
}

TICKERS = list(set([t for sublist in TICKERS_CONFIG.values() for t in sublist]))