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
    if 'oportunidades' not in st.session_state: st.session_state.oportunidades = pd.DataFrame()
    if 'precios_actuales' not in st.session_state: st.session_state.precios_actuales = pd.Series(dtype=float)
    if 'mep_valor' not in st.session_state: st.session_state.mep_valor = None
    if 'mep_var' not in st.session_state: st.session_state.mep_var = None
    if 'last_update' not in st.session_state: st.session_state.last_update = None
    if 'init_done' not in st.session_state: st.session_state.init_done = False
    
    # Inicialización de estados de los expanders (para lazy loading en Home)
    paneles_a_revisar = ['Favoritos', 'Lider', 'Cedears', 'General', 'Bonos']
    for panel in paneles_a_revisar:
        if f'expanded_{panel}' not in st.session_state:
            st.session_state[f'expanded_{panel}'] = False

# --- LÓGICA DE DETECCIÓN DE TICKERS ---
def get_tickers_a_cargar() -> List[str]:
    """Combina tickers de Portafolio + Favoritos + Paneles Abiertos (USADO POR HOME)."""
    tickers_a_cargar = set()
    
    # 1. Cartera (SIEMPRE se cargan sus precios)
    tickers_a_cargar.update(database.get_tickers_en_cartera())
    
    # 2. Favoritos y Paneles Expandidos
    paneles_a_revisar = ['Favoritos', 'Lider', 'Cedears', 'General', 'Bonos']

    for panel in paneles_a_revisar:
        is_expanded = st.session_state.get(f'expanded_{panel}', False)
        
        if is_expanded or not st.session_state.init_done:
            if panel == 'Favoritos':
                tickers_a_cargar.update(database.get_favoritos())
            elif panel in config.TICKERS_CONFIG:
                tickers_a_cargar.update(config.TICKERS_CONFIG[panel])
            
    # 3. MEP
    tickers_a_cargar.update(['AL30.BA', 'AL30D.BA', 'GD30.BA', 'GD30D.BA'])
    
    return list(tickers_a_cargar)

# --- LÓGICA DE ACTUALIZACIÓN BASE ---
def update_data(lista_tickers, nombre_panel, silent=False):
    if not lista_tickers: return

    # Implementación del spinner simplificada para evitar errores
    if not silent:
        with st.spinner(f"Cargando {nombre_panel}..."):
            df_nuevo_raw = data_client.get_data(lista_tickers)
            
            if df_nuevo_raw.empty:
                st.warning(f"⚠️ No se encontraron datos para {nombre_panel}.")
                return
            
            # Continuar procesamiento
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
            
            # Fusión
            if 'Precio' in df_nuevo_screener.columns:
                nuevos = df_nuevo_screener['Precio']
                st.session_state.precios_actuales.update(nuevos)
                st.session_state.precios_actuales = st.session_state.precios_actuales.combine_first(nuevos)
            
            # Solo actualiza los datos existentes sin recargar todo el df oportunidades
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

# --- FUNCIONES DE ORQUESTACIÓN ---
def actualizar_solo_cartera(silent=False):
    """NUEVA FUNCIÓN: Actualiza solo Portafolio y MEP (para Portafolio_y_Ventas)."""
    init_session_state()
    
    t_cartera = database.get_tickers_en_cartera()
    t_mep = ['AL30.BA', 'AL30D.BA', 'GD30.BA', 'GD30D.BA']
    
    t_a_cargar = list(set(t_cartera + t_mep))
    
    if not t_a_cargar:
        if not silent: st.warning("No hay activos en cartera para actualizar.")
        return

    update_data(t_a_cargar, "Portafolio en Tenencia", silent=silent)


def actualizar_todo(silent=False):
    """Función para HOME (Actualiza todo lo visible)."""
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