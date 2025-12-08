import streamlit as st
import os
import sys

# ----------------------------------------------------
# --- LÓGICA DE DETECCIÓN DE ENTORNO Y AUTENTICACIÓN SEGURA ---
# ----------------------------------------------------

# 1. Chequeo si los secretos de GCP existen (Esto sólo es verdad en la nube)
try:
    # ⚠️ INTENTAMOS CARGAR Secrets sin importar el entorno. Si existen, forzamos CLOUD.
    # Si esta línea falla (ej: falta "gcp_service_account"), vamos al bloque 'except'.
    GOOGLE_CREDENTIALS_DICT = dict(st.secrets["gcp_service_account"])
    print("DEBUG_CFG: 1. GOOGLE_CREDENTIALS_DICT cargado de st.secrets.")
    
    # Si la carga fue exitosa, forzamos el modo CLOUD
    
    # Aplicar el fix de salto de línea
    if "private_key" in GOOGLE_CREDENTIALS_DICT:
        pk = GOOGLE_CREDENTIALS_DICT["private_key"]
        GOOGLE_CREDENTIALS_DICT["private_key"] = pk.replace("\\n", "\n")
        
    IOL_USER = st.secrets["IOL_USER"]
    IOL_PASSWORD = st.secrets["IOL_PASSWORD"]
    SHEET_NAME = st.secrets["SHEET_NAME"]
    USE_CLOUD_AUTH = True
    CREDENTIALS_FILE = None 
    print("DEBUG_CFG: 2. FORZANDO MODO CLOUD (Secrets OK).")
    
except Exception as e:
    # ⚠️ Si la carga de secrets falla, asumimos MODO LOCAL (o fallo de secrets)
    print(f"DEBUG_CFG: 1. Falla al cargar secrets: {e}. Asumiendo MODO LOCAL.", file=sys.stderr)
    
    # MODO LOCAL (TU PC): 
    USE_CLOUD_AUTH = False
    GOOGLE_CREDENTIALS_DICT = None
    
    # --- DATOS LOCALES PARA PRUEBAS (DEBES EDITAR ESTOS VALORES) ---
    IOL_USER = ""
    IOL_PASSWORD = ""
    SHEET_NAME = "para_streamlit" 
    CREDENTIALS_FILE = "ruta_correcta_a_tu_archivo.json" 
    print(f"DEBUG_CFG: 2. MODO LOCAL. CREDENTIALS_FILE={CREDENTIALS_FILE}")


# --- CONFIGURACIÓN GENERAL (CONSTANTES) ---
DIAS_HISTORIAL = 200

# TASAS Y BONOS
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