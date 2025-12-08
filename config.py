import streamlit as st
import os
import sys

# ----------------------------------------------------
# --- LÓGICA DE DETECCIÓN DE ENTORNO ---
# ----------------------------------------------------
try:
    GOOGLE_CREDENTIALS_DICT = dict(st.secrets["gcp_service_account"])
    # Fix saltos de línea en clave privada
    if "private_key" in GOOGLE_CREDENTIALS_DICT:
        pk = GOOGLE_CREDENTIALS_DICT["private_key"]
        GOOGLE_CREDENTIALS_DICT["private_key"] = pk.replace("\\n", "\n")
        
    IOL_USER = st.secrets["IOL_USER"]
    IOL_PASSWORD = st.secrets["IOL_PASSWORD"]
    SHEET_NAME = st.secrets["SHEET_NAME"]
    USE_CLOUD_AUTH = True
    CREDENTIALS_FILE = None 
except Exception as e:
    USE_CLOUD_AUTH = False
    GOOGLE_CREDENTIALS_DICT = None
    # DATOS LOCALES
    IOL_USER = ""
    IOL_PASSWORD = ""
    SHEET_NAME = "para_streamlit" 
    CREDENTIALS_FILE = "ruta_correcta_a_tu_archivo.json" 

# --- CONFIGURACIÓN GENERAL ---
DIAS_HISTORIAL = 200

# TASAS
IVA = 1.21
DERECHOS_MERCADO = 0.0008
VETA_MINIMO = 50
COMISIONES = {
    'IOL': 0.006, 'BULL': 0.006, 'COCOS': 0.006, 'VETA': 0.002, 'DEFAULT': 0.006
}

# TICKERS Y CATEGORÍAS
# IMPORTANTE: Agregados AL35, AL29, GD35, GD38, GD41, GD46, TX, etc.
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
    'Bonos': [
        'AL29.BA', 'AL29D.BA', 'AL30.BA', 'AL30D.BA', 'AL35.BA', 'AL35D.BA',
        'AE38.BA', 'AE38D.BA', 'AL41.BA', 'AL41D.BA',
        'GD29.BA', 'GD29D.BA', 'GD30.BA', 'GD30D.BA', 'GD35.BA', 'GD35D.BA',
        'GD38.BA', 'GD38D.BA', 'GD41.BA', 'GD41D.BA', 'GD46.BA', 'GD46D.BA',
        'TX24.BA', 'TX26.BA', 'TX28.BA', 'TO26.BA'
    ]
}
# Lista plana única
TICKERS = list(set([t for sublist in TICKERS_CONFIG.values() for t in sublist]))