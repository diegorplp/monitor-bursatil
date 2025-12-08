import streamlit as st
import os

# --- LÓGICA DE DETECCIÓN Y SEGURIDAD MÁXIMA ---

# Streamlit Cloud siempre setea esta variable de entorno
IS_STREAMLIT_CLOUD = "STREAMLIT_SERVER_VERSION" in os.environ

if IS_STREAMLIT_CLOUD:
    # MODO NUBE (SEGURO): La aplicación SOLO lee de st.secrets.
    try:
        # 1. Credenciales de IOL
        IOL_USER = st.secrets["IOL_USER"]
        IOL_PASSWORD = st.secrets["IOL_PASSWORD"]
        SHEET_NAME = st.secrets["SHEET_NAME"]
        
        # 2. Credenciales GCP (FIX CRÍTICO para gspread)
        # Importamos las credenciales como un diccionario
        GOOGLE_CREDENTIALS_DICT = dict(st.secrets["gcp_service_account"])
        if "private_key" in GOOGLE_CREDENTIALS_DICT:
            # Reemplazamos el token de salto de línea '\n' que Streamlit a veces introduce
            pk = GOOGLE_CREDENTIALS_DICT["private_key"]
            GOOGLE_CREDENTIALS_DICT["private_key"] = pk.replace("\\n", "\n")
        
        # Variables de control para database.py
        USE_CLOUD_AUTH = True
        CREDENTIALS_FILE = None # No se usa en la nube, pero debe estar definido.

    except Exception:
        # Si falla la lectura de secrets, la app debe fallar.
        raise Exception("ERROR FATAL DE SEGURIDAD: Faltan claves en Streamlit Secrets. No se puede iniciar la conexión con IOL/Google.")

else:
    # MODO LOCAL (TU PC): 
    # Definimos todas las variables necesarias.
    
    # Variables de control para database.py
    USE_CLOUD_AUTH = False
    GOOGLE_CREDENTIALS_DICT = None # No se usa en modo local.

    # --- DATOS LOCALES PARA PRUEBAS (ATENCIÓN: NO DEBEN SER CLAVES REALES EN GITHUB) ---
    # Para que funcione localmente, DEBES COMPLETAR ESTOS VALORES EN TU COPIA LOCAL
    # (La versión que tienes en tu disco duro, NO la que subiste a GitHub).
    IOL_USER = "" # <<-- Usuario real para el modo LOCAL
    IOL_PASSWORD = "" # <<-- Password real para el modo LOCAL
    SHEET_NAME = "para_streamlit" # <<-- Nombre de tu hoja (puede ser constante)
    
    # RUTA AL ARCHIVO JSON en tu PC:
    CREDENTIALS_FILE = "carbon-broker-479906-a2-157f549dc6b7.json" # <<-- RUTA DE TU ARCHIVO LOCAL

# --- CONFIGURACIÓN GENERAL (A PARTIR DE AQUÍ SON SOLO TASAS Y LISTAS) ---
DIAS_HISTORIAL = 200

# TASAS Y BONOS (Se mantienen igual)
IVA = 1.21
DERECHOS_MERCADO = 0.0008
VETA_MINIMO = 50
COMISIONES = {
    'IOL': 0.006, 'BULL': 0.006, 'COCOS': 0.006, 'VETA': 0.002, 'DEFAULT': 0.006
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