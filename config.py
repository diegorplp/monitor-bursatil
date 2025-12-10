import streamlit as st
import os
import sys

# ----------------------------------------------------
# --- LÓGICA DE DETECCIÓN DE ENTORNO ---
# ----------------------------------------------------
try:
    GOOGLE_CREDENTIALS_DICT = dict(st.secrets["gcp_service_account"])
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
    IOL_USER = ""
    IOL_PASSWORD = ""
    SHEET_NAME = "para_streamlit" 
    CREDENTIALS_FILE = "ruta_correcta_a_tu_archivo.json" 

# --- CONFIGURACIÓN GENERAL ---
DIAS_HISTORIAL = 200

# TASAS E IMPUESTOS
IVA = 1.21
VETA_MINIMO = 50

# DERECHOS DE MERCADO DIFERENCIADOS
DERECHOS_ACCIONES = 0.0005  # 0.05% (Factura GGAL)
DERECHOS_BONOS = 0.0001     # 0.01% (Factura AL30)

# COMISIONES (Base sin IVA)
COMISIONES = {
    'IOL': 0.0045, 
    'BULL': 0.0045, 
    'COCOS': 0.0045, 
    'VETA': 0.0015, 
    'DEFAULT': 0.0045
}

# TICKERS Y CATEGORÍAS
TICKERS_CONFIG = {
    'Favoritos': ['GGAL.BA', 'YPFD.BA', 'AL30.BA', 'GD30.BA'],
    
    # Lider: 20 Merval + BHIP + BPAT
    'Lider': [
        'ALUA.BA', 'BBAR.BA', 'BMA.BA', 'BYMA.BA', 'CEPU.BA', 'COME.BA', 
        'CRES.BA', 'EDN.BA', 'GGAL.BA', 'LOMA.BA', 'MIRG.BA', 'PAMP.BA', 
        'SUPV.BA', 'TECO2.BA', 'TGNO4.BA', 'TGSU2.BA', 'TRAN.BA', 'TXAR.BA', 
        'VALO.BA', 'YPFD.BA',
        # Agregados por solicitud
        'BHIP.BA', 'BPAT.BA'
    ],
    
    # General: Stocks restantes que no son Merval
    'General': [
        'BOLT.BA', 'LEDE.BA', 'MOLI.BA', 'SEMI.BA', 
        # Si quieres agregar más acciones conocidas del panel general:
        'DGCU2.BA', 'GARO.BA', 'CADO.BA' 
    ],
    
    # Cedears: Selección de los más líquidos y representativos
    'Cedears': [
        # Tech & Growth (Lideres)
        'AAPL.BA', 'MSFT.BA', 'GOOGL.BA', 'AMZN.BA', 'NVDA.BA', 'AMD.BA', 
        'TSLA.BA', 'META.BA', 'MELI.BA', 'ADBE.BA',
        # Consumo / Retail
        'BABA.BA', 'DIS.BA', 'KO.BA', 'WMT.BA', 'MCD.BA', 'PFE.BA',
        # Financieras / Industriales
        'V.BA', 'JPM.BA', 'QCOM.BA', 'BBD.BA', 'X.BA', 
        # ETFs y Energía
        'SPY.BA', 'QQQ.BA', 'DIA.BA', 'VIST.BA', 'ARKK.BA'
    ],
    
    # Bonos: Lista completa de AL/GD + Ley Local/Extranjera + Letras
    'Bonos': [
        'AL29.BA', 'AL29D.BA', 'AL30.BA', 'AL30D.BA', 'AL35.BA', 'AL35D.BA',
        'AE38.BA', 'AE38D.BA', 'AL41.BA', 'AL41D.BA',
        'GD29.BA', 'GD29D.BA', 'GD30.BA', 'GD30D.BA', 'GD35.BA', 'GD35D.BA',
        'GD38.BA', 'GD38D.BA', 'GD41.BA', 'GD41D.BA', 'GD46.BA', 'GD46D.BA',
    ]
}

# La lógica para generar la lista única de tickers (TICKERS) sigue siendo perfecta
TICKERS = list(set([t for sublist in TICKERS_CONFIG.values() for t in sublist]))