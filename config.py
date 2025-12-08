import streamlit as st
import os

# --- LÓGICA DE DETECCIÓN Y SEGURIDAD MÁXIMA ---

IS_STREAMLIT_CLOUD = "STREAMLIT_SERVER_VERSION" in os.environ

if IS_STREAMLIT_CLOUD:
    # MODO NUBE (SEGURO):
    # La aplicación SOLO PUEDE leer de st.secrets.
    try:
        # Credenciales de IOL
        IOL_USER = st.secrets["IOL_USER"]
        IOL_PASSWORD = st.secrets["IOL_PASSWORD"]
        SHEET_NAME = st.secrets["SHEET_NAME"]
        
        # Credenciales GCP (FIX CRÍTICO)
        GOOGLE_CREDENTIALS_DICT = dict(st.secrets["gcp_service_account"])
        if "private_key" in GOOGLE_CREDENTIALS_DICT:
            pk = GOOGLE_CREDENTIALS_DICT["private_key"]
            GOOGLE_CREDENTIALS_DICT["private_key"] = pk.replace("\\n", "\n")
        
        USE_CLOUD_AUTH = True
        CREDENTIALS_FILE = None # Aseguramos que esta variable no se use en la nube

    except Exception:
        # SI FALLA LA LECTURA DE SECRETS, LA APP DEBE FALLAR. NO HAY PLAN B EN LA NUBE.
        raise Exception("ERROR FATAL DE SEGURIDAD: Faltan claves en Streamlit Secrets. No se puede iniciar la conexión con IOL/Google.")

else:
    # MODO LOCAL (TU PC):
    # El código lee las credenciales directamente, ya que el archivo config.py NO SUBE A GITHUB
    # (El usuario debe mantener sus credenciales aquí localmente).
    USE_CLOUD_AUTH = False
    GOOGLE_CREDENTIALS_DICT = None
    
    # --- ESPACIO PARA TUS CLAVES LOCALES ---
    # Nota: Tu archivo config.py local debe contener estos valores sin st.secrets
    IOL_USER = "diego_rp_94@live.com"
    IOL_PASSWORD = "*iI213322"
    SHEET_NAME = "para_streamlit"
    CREDENTIALS_FILE = "carbon-broker-479906-a2-157f549dc6b7.json"

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