import streamlit as st
import os
import sys

# ----------------------------------------------------
# --- LÓGICA DE DETECCIÓN DE ENTORNO Y AUTENTICACIÓN SEGURA ---
# ----------------------------------------------------

# 1. Chequeo inicial de detección de entorno
IS_STREAMLIT_CLOUD = "STREAMLIT_SERVER_VERSION" in os.environ
print(f"DEBUG_CFG: 1. IS_STREAMLIT_CLOUD detectado como: {IS_STREAMLIT_CLOUD}")

if IS_STREAMLIT_CLOUD:
    print("DEBUG_CFG: 2. Entrando en bloque IF (Modo CLOUD)")
    
    # MODO NUBE (SEGURO):
    try:
        # 3. Intentando cargar secrets
        print("DEBUG_CFG: 3. Intentando leer secrets...")
        
        # Credenciales de IOL
        IOL_USER = st.secrets["IOL_USER"]
        IOL_PASSWORD = st.secrets["IOL_PASSWORD"]
        SHEET_NAME = st.secrets["SHEET_NAME"]
        print("DEBUG_CFG: 3a. IOL_USER y SHEET_NAME cargados.")

        # Credenciales GCP
        GOOGLE_CREDENTIALS_DICT = dict(st.secrets["gcp_service_account"])
        if "private_key" in GOOGLE_CREDENTIALS_DICT:
            pk = GOOGLE_CREDENTIALS_DICT["private_key"]
            GOOGLE_CREDENTIALS_DICT["private_key"] = pk.replace("\\n", "\n")
        print(f"DEBUG_CFG: 3b. GCP dict cargado. Keys en dict: {len(GOOGLE_CREDENTIALS_DICT.keys())}")
        
        USE_CLOUD_AUTH = True
        CREDENTIALS_FILE = None 
        
        print(f"DEBUG_CFG: 4. CLOUD exitoso. USE_CLOUD_AUTH={USE_CLOUD_AUTH}. CREDENTIALS_FILE={CREDENTIALS_FILE}")

    except Exception as e:
        print(f"DEBUG_CFG: 5. ERROR FATAL al cargar secrets: {e}", file=sys.stderr)
        
        # Si falla la lectura de secrets, la app debe fallar.
        raise Exception(f"ERROR FATAL DE SEGURIDAD EN CLOUD: Faltan claves en Streamlit Secrets. Detalle: {e}")

else:
    print("DEBUG_CFG: 2. Entrando en bloque ELSE (Modo LOCAL)")
    
    # MODO LOCAL (TU PC): 
    USE_CLOUD_AUTH = False
    GOOGLE_CREDENTIALS_DICT = None
    
    # --- DATOS LOCALES PARA PRUEBAS (DEBES EDITAR ESTOS VALORES) ---
    IOL_USER = ""
    IOL_PASSWORD = ""
    SHEET_NAME = "para_streamlit" 
    CREDENTIALS_FILE = "ruta_correcta_a_tu_archivo.json" 
    
    print(f"DEBUG_CFG: 4. LOCAL exitoso. USE_CLOUD_AUTH={USE_CLOUD_AUTH}. CREDENTIALS_FILE={CREDENTIALS_FILE}")


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