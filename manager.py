import streamlit as st
import pandas as pd
from datetime import datetime
import data_client
import market_logic
import database
import config
import time
from typing import List
import requests
import yfinance as yf
import numpy as np
from datetime import timedelta # Importamos timedelta

IOL_BASE_URL = "https://api.invertironline.com"

# --- INICIALIZACIÓN DE ESTADO ---
# ... (Bloque init_session_state idéntico omitido) ...
def init_session_state():
    screener_cols = ['Precio', 'RSI', 'Caida_30d', 'Caida_5d', 'Var_Ayer', 'Suma_Caidas', 'Senal']

    if 'oportunidades' not in st.session_state:
        df_base = pd.DataFrame(index=config.TICKERS)
        for col in screener_cols:
             df_base[col] = 0.0 if col != 'Senal' else 'PENDIENTE'
        df_base['Senal'] = df_base['Senal'].fillna('PENDIENTE')
        st.session_state.oportunidades = df_base
        
    if 'precios_actuales' not in st.session_state: st.session_state.precios_actuales = pd.Series(dtype=float)
    if 'mep_valor' not in st.session_state: st.session_state.mep_valor = None
    if 'mep_var' not in st.session_state: st.session_state.mep_var = None
    if 'last_update' not in st.session_state: st.session_state.last_update = None
    if 'init_done' not in st.session_state: st.session_state.init_done = False


# --- LÓGICA DE DETECCIÓN DE TICKERS y UPDATE_DATA (idéntico omitido) ---
def get_tickers_a_cargar() -> List[str]:
    tickers_a_cargar = set()
    tickers_a_cargar.update(['AL30.BA', 'AL30D.BA', 'GD30.BA', 'GD30D.BA'])
    return list(tickers_a_cargar)

def update_data(lista_tickers, nombre_panel, silent=False):
    # ... (Bloque update_data idéntico omitido) ...
    if not lista_tickers: return

    if not silent:
        with st.spinner(f"Cargando {nombre_panel}..."):
            df_nuevo_raw = data_client.get_data(lista_tickers)
            
            if df_nuevo_raw.empty:
                st.warning(f"⚠️ No se encontraron datos para {nombre_panel}.")
                return
            
            mep, var = market_logic.calcular_mep(df_nuevo_raw)
            if mep:
                st.session_state.mep_valor = mep
                st.session_state.mep_var = var

            try:
                df_nuevo_screener = market_logic.calcular_indicadores(df_nuevo_raw)
            except Exception as e:
                st.error(f"❌ Error interno de cálculo: {e}")
                return
            
            if df_nuevo_screener.empty: return
            
            if 'Precio' in df_nuevo_screener.columns:
                nuevos = df_nuevo_screener['Precio']
                st.session_state.precios_actuales.update(nuevos)
                st.session_state.precios_actuales = st.session_state.precios_actuales.combine_first(nuevos)
            
            # Fusión
            df_total = st.session_state.oportunidades.copy()
            
            df_nuevo_screener['Suma_Caidas'] = pd.to_numeric(df_nuevo_screener['Suma_Caidas'], errors='coerce')
            
            for idx in df_nuevo_screener.index:
                 if idx in df_total.index:
                     df_total.loc[idx] = df_nuevo_screener.loc[idx]
            
            if not df_total.empty:
                cols_sort = ['Senal', 'Suma_Caidas']
                if 'Suma_Caidas' in df_total.columns:
                     df_total['Suma_Caidas'] = pd.to_numeric(df_total['Suma_Caidas'], errors='coerce')
                df_total.sort_values(by=cols_sort, ascending=[True, False], na_position='last', inplace=True)

            st.session_state.oportunidades = df_total
            st.session_state.last_update = datetime.now()
            st.success(f"✅ Datos actualizados.")
            
    else: # Si silent=True, procesa sin spinner (auto-refresh)
        df_nuevo_raw = data_client.get_data(lista_tickers)
        if df_nuevo_raw.empty: return

        mep, var = market_logic.calcular_mep(df_nuevo_raw)
        if mep:
            st.session_state.mep_valor = mep
            st.session_state.mep_var = var

        try:
            df_nuevo_screener = market_logic.calcular_indicadores(df_nuevo_raw)
        except: return

        if df_nuevo_screener.empty: return

        if 'Precio' in df_nuevo_screener.columns:
            nuevos = df_nuevo_screener['Precio']
            st.session_state.precios_actuales.update(nuevos)
            st.session_state.precios_actuales = st.session_state.precios_actuales.combine_first(nuevos)
        
        # Fusión silenciosa
        df_total = st.session_state.oportunidades.copy()
        
        df_nuevo_screener['Suma_Caidas'] = pd.to_numeric(df_nuevo_screener['Suma_Caidas'], errors='coerce')
        
        for idx in df_nuevo_screener.index:
             if idx in df_total.index:
                 df_total.loc[idx] = df_nuevo_screener.loc[idx]
        
        if not df_total.empty:
            cols_sort = ['Senal', 'Suma_Caidas']
            if 'Suma_Caidas' in df_total.columns:
                 df_total['Suma_Caidas'] = pd.to_numeric(df_total['Suma_Caidas'], errors='coerce')
            df_total.sort_values(by=cols_sort, ascending=[True, False], na_position='last', inplace=True)

        st.session_state.oportunidades = df_total
        st.session_state.last_update = datetime.now()


# --- LÓGICA DE DIAGNÓSTICO (MOVILIZADA DESDE data_client.py) ---
def run_diagnostic_test(tickers_to_test):
    """Ejecuta pruebas de conexión y nomenclatura para un grupo de tickers."""
    
    iol_token = data_client._get_iol_token()
    
    results = []
    
    if not iol_token:
        results.append("❌ ERROR CRÍTICO: No se pudo obtener el token de IOL. Verifica usuario/contraseña en st.secrets.")
        return results

    
    for base_ticker in tickers_to_test:
        test_variants = {
            f"{base_ticker}.BA": "Bolsa Argentina (.BA)",
            f"{base_ticker}": "Sin sufijo (RAW)",
            f"{base_ticker}.L": "Cedear (.L - Yahoo)"
        }
        
        results.append(f"\n--- Probando Ticker Base: {base_ticker} ---")
        
        for ticker_test, desc in test_variants.items():
            # 1. Test IOL (Precio Actual)
            iol_symbol = ticker_test.upper().replace('.BA', '').replace('.C', '').replace('.L', '')
            url_iol = f"{IOL_BASE_URL}/api/v2/bCBA/Titulos/{iol_symbol}/Cotizacion"
            headers = {"Authorization": f"Bearer {iol_token}"}
            
            iol_price = "❌ FALLA"
            try:
                r = requests.get(url_iol, headers=headers, timeout=3)
                if r.status_code == 200:
                    iol_price = r.json().get('ultimoPrecio', 'NO PRICE')
                elif r.status_code == 404:
                    iol_price = "❌ 404 (No Encontrado)"
            except: pass
            
            # 2. Test Yahoo (Histórico)
            df_yahoo = yf.download(tickers=ticker_test, start=datetime.now() - timedelta(days=50), interval='1d', auto_adjust=True, progress=False, threads=False, timeout=5)
            yahoo_ok = not df_yahoo.empty
            
            results.append(f"  > {desc} ({ticker_test}): IOL Price: {iol_price}, Yahoo Histórico: {'✅ OK' if yahoo_ok else '❌ FALLA'}")

    return results


# --- FUNCIONES DE ORQUESTACIÓN y WIDGET DE SIDEBAR (idéntico omitido) ---
def actualizar_panel_individual(nombre_panel, lista_tickers):
    init_session_state()
    
    t_mep = ['AL30.BA', 'AL30D.BA', 'GD30.BA', 'GD30D.BA']
    t_cartera = database.get_tickers_en_cartera()
    
    t_a_cargar = list(set(lista_tickers + t_mep + t_cartera))
    
    update_data(t_a_cargar, nombre_panel, silent=False)


def actualizar_solo_cartera(silent=False):
    init_session_state()
    
    t_cartera = database.get_tickers_en_cartera()
    t_mep = ['AL30.BA', 'AL30D.BA', 'GD30.BA', 'GD30D.BA']
    t_a_cargar = list(set(t_cartera + t_mep))
    
    if not t_a_cargar:
        t_a_cargar = get_tickers_a_cargar()
        
    update_data(t_a_cargar, "Portafolio en Tenencia", silent=silent)


def actualizar_todo(silent=False):
    init_session_state()

    if not st.session_state.init_done:
        t_a_cargar = get_tickers_a_cargar()
        update_data(t_a_cargar, "MEP Base", silent=silent)
    else:
        actualizar_solo_cartera(silent=silent)


def mostrar_boton_actualizar():
    init_session_state()
    st.sidebar.markdown("---")
    st.sidebar.subheader("📡 Datos de Mercado")
    
    if st.sidebar.button("🔄 Actualizar Todo", use_container_width=True):
        st.session_state.init_done = False
        st.rerun()
        
    if st.session_state.last_update:
        st.sidebar.caption(f"Última act: {st.session_state.last_update.strftime('%H:%M:%S')}")
        
    if st.session_state.mep_valor:
        st.sidebar.metric("MEP", f"${st.session_state.mep_valor:,.0f}")

# Lista de tickers para la prueba.
TEST_TICKERS_DIAG = [
    'A3',      # Acción Local
    'NFLX',    # Cedear
    'MSFT',    # Cedear
    'AL30'     # Bono
]

# --- PANEL DE DIAGNÓSTICO DE CONECTIVIDAD (NUEVO) ---
with st.expander("🛠️ Diagnóstico de Conexión y Simbología", expanded=False):
    st.caption("Usa este panel para verificar qué nomenclatura funciona para IOL y Yahoo Finance.")
    
    if st.button("▶️ Ejecutar Test de Conexión (Lento)"):
        with st.spinner("Ejecutando test en IOL y Yahoo Finance..."):
            # CRÍTICO: La llamada al manager se hace directamente.
            test_results = manager.run_diagnostic_test(TEST_TICKERS_DIAG)
            st.session_state['test_results_diag'] = test_results
            
    if 'test_results_diag' in st.session_state:
        st.code('\n'.join(st.session_state['test_results_diag']), language='text')