import streamlit as st
import pandas as pd
from datetime import datetime
import data_client
import market_logic
import database
import config
import time # Importamos time
from typing import List

# --- INICIALIZACIÓN DE ESTADO ---
def init_session_state():
    if 'oportunidades' not in st.session_state: st.session_state.oportunidades = pd.DataFrame()
    if 'precios_actuales' not in st.session_state: st.session_state.precios_actuales = pd.Series(dtype=float)
    if 'paneles_expandidos' not in st.session_state: st.session_state.paneles_expandidos = ['Cartera']
    if 'mep_valor' not in st.session_state: st.session_state.mep_valor = None
    if 'mep_var' not in st.session_state: st.session_state.mep_var = None
    if 'last_update' not in st.session_state: st.session_state.last_update = None
    if 'init_done' not in st.session_state: st.session_state.init_done = False

# --- LÓGICA DE DETECCIÓN DE TICKERS ---
def get_tickers_a_cargar() -> List[str]:
    tickers_a_cargar = set()
    tickers_a_cargar.update(database.get_tickers_en_cartera())
    if 'Favoritos' in st.session_state.paneles_expandidos or not st.session_state.init_done:
        tickers_a_cargar.update(database.get_favoritos())

    for panel in st.session_state.paneles_expandidos:
        if panel in config.TICKERS_CONFIG:
            tickers_a_cargar.update(config.TICKERS_CONFIG[panel])
            
    tickers_a_cargar.update(['AL30.BA', 'AL30D.BA', 'GD30.BA', 'GD30D.BA'])
    
    return list(tickers_a_cargar)

# --- LÓGICA DE ACTUALIZACIÓN ---
def update_data(lista_tickers, nombre_panel, silent=False):
    if not lista_tickers: return

    # CRÍTICO: Usamos un bloque para manejar el estado del spinner
    status_placeholder = st.empty()
    contexto = status_placeholder.spinner(f"Cargando {nombre_panel}...") if not silent else st.empty()
    
    start_time = time.time() # Medir tiempo de descarga

    with contexto:
        # 1. Descarga de datos
        df_nuevo_raw = data_client.get_data(lista_tickers)
        
        # 2. Control de Timeout/Falla
        if time.time() - start_time > 30 and df_nuevo_raw.empty:
             if not silent: status_placeholder.error(f"❌ Error de Conexión: La descarga tardó mucho o falló para {nombre_panel}. Intenta en 1 minuto.")
             return

        if df_nuevo_raw.empty:
            if not silent: status_placeholder.warning(f"⚠️ No se encontraron datos para {nombre_panel}. Puede ser un problema de conexión a la API.")
            return

        # 3. MEP
        mep, var = market_logic.calcular_mep(df_nuevo_raw)
        if mep:
            st.session_state.mep_valor = mep
            st.session_state.mep_var = var

        # 4. Indicadores
        try:
            df_nuevo_screener = market_logic.calcular_indicadores(df_nuevo_raw)
        except Exception as e:
            if not silent: status_placeholder.error(f"❌ Error interno de cálculo: {e}")
            return

        if df_nuevo_screener.empty: return

        # 5. Fusión (Mantiene todos los paneles, actualizando solo los nuevos)
        if 'Precio' in df_nuevo_screener.columns:
            nuevos = df_nuevo_screener['Precio']
            st.session_state.precios_actuales.update(nuevos)
            st.session_state.precios_actuales = st.session_state.precios_actuales.combine_first(nuevos)
        
        if not st.session_state.oportunidades.empty:
            df_total = pd.concat([st.session_state.oportunidades.drop(df_nuevo_screener.index, errors='ignore'), df_nuevo_screener])
            df_total = df_total[~df_total.index.duplicated(keep='last')]
        else:
            df_total = df_nuevo_screener

        if not df_total.empty:
            cols_sort = ['Senal', 'Suma_Caidas']
            if all(c in df_total.columns for c in cols_sort):
                df_total.sort_values(by=cols_sort, ascending=[True, False], inplace=True)

        st.session_state.oportunidades = df_total
            
        st.session_state.last_update = datetime.now()
        
        if not silent: status_placeholder.success(f"✅ Datos actualizados en {time.time() - start_time:.2f}s.")
        else: status_placeholder.empty() # Limpiar el placeholder si fue silencioso


def actualizar_todo(silent=False):
    init_session_state()
    
    t_a_cargar = get_tickers_a_cargar()
    
    if not t_a_cargar:
        if not silent: st.warning("No hay tickers para cargar.")
        return

    # Llamamos a la lógica principal de descarga
    update_data(t_a_cargar, "Mercado Global", silent=silent)


# --- WIDGET DE SIDEBAR ---
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