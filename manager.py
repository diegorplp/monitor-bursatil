import streamlit as st
import pandas as pd
from datetime import datetime
import data_client
import market_logic
import database
import config
import time
from typing import List

# --- INICIALIZACIÓN DE ESTADO ---
def init_session_state():
    # Inicialización estándar
    if 'oportunidades' not in st.session_state: st.session_state.oportunidades = pd.DataFrame()
    if 'precios_actuales' not in st.session_state: st.session_state.precios_actuales = pd.Series(dtype=float)
    if 'mep_valor' not in st.session_state: st.session_state.mep_valor = None
    if 'mep_var' not in st.session_state: st.session_state.mep_var = None
    if 'last_update' not in st.session_state: st.session_state.last_update = None
    if 'init_done' not in st.session_state: st.session_state.init_done = False
    
    # CRÍTICO: Inicialización de estados de los expanders (para Lazy Loading)
    paneles_a_revisar = ['Favoritos', 'Lider', 'Cedears', 'General', 'Bonos']
    for panel in paneles_a_revisar:
        if f'expanded_{panel}' not in st.session_state:
            st.session_state[f'expanded_{panel}'] = False # Por defecto, cerrados

# --- LÓGICA DE DETECCIÓN DE TICKERS ---
def get_tickers_a_cargar() -> List[str]:
    """Combina tickers de Portafolio + Favoritos + Paneles Abiertos."""
    tickers_a_cargar = set()
    
    # 1. Cartera (SIEMPRE se cargan sus precios)
    tickers_a_cargar.update(database.get_tickers_en_cartera())
    
    # 2. Favoritos y Paneles Expandidos
    paneles_a_revisar = ['Favoritos', 'Lider', 'Cedears', 'General', 'Bonos']

    for panel in paneles_a_revisar:
        # Si el panel está marcado como expandido O es la carga inicial
        is_expanded = st.session_state.get(f'expanded_{panel}', False)
        
        if is_expanded or not st.session_state.init_done:
            if panel == 'Favoritos':
                tickers_a_cargar.update(database.get_favoritos())
            elif panel in config.TICKERS_CONFIG:
                tickers_a_cargar.update(config.TICKERS_CONFIG[panel])
            
    # 3. MEP
    tickers_a_cargar.update(['AL30.BA', 'AL30D.BA', 'GD30.BA', 'GD30D.BA'])
    
    return list(tickers_a_cargar)

# --- LÓGICA DE ACTUALIZACIÓN ---
def update_data(lista_tickers, nombre_panel, silent=False):
    if not lista_tickers: return

    status_placeholder = st.empty()
    contexto = status_placeholder.spinner(f"Cargando {nombre_panel}...") if not silent else st.empty()
    
    start_time = time.time()

    with contexto:
        df_nuevo_raw = data_client.get_data(lista_tickers)
        
        if time.time() - start_time > 30 and df_nuevo_raw.empty:
             if not silent: status_placeholder.error(f"❌ Error de Conexión: Descarga falló.")
             return

        if df_nuevo_raw.empty:
            if not silent: status_placeholder.warning(f"⚠️ No se encontraron datos.")
            return

        # MEP
        mep, var = market_logic.calcular_mep(df_nuevo_raw)
        if mep:
            st.session_state.mep_valor = mep
            st.session_state.mep_var = var

        # Indicadores
        try:
            df_nuevo_screener = market_logic.calcular_indicadores(df_nuevo_raw)
        except Exception as e:
            if not silent: status_placeholder.error(f"❌ Error interno de cálculo: {e}")
            return

        if df_nuevo_screener.empty: return

        # Fusión
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
        else: status_placeholder.empty()


def actualizar_todo(silent=False):
    init_session_state()
    
    t_a_cargar = get_tickers_a_cargar()
    
    if not t_a_cargar:
        if not silent: st.warning("No hay tickers para cargar.")
        return

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