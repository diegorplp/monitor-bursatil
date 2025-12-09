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
    # Inicialización de df_oportunidades con TODOS los tickers posibles, pero sin datos.
    if 'oportunidades' not in st.session_state:
        # Crea un DataFrame vacío con todos los Tickers como índice
        df_base = pd.DataFrame(index=config.TICKERS)
        # Añade las columnas necesarias para evitar errores de cálculo
        df_base['Precio'] = 0.0
        df_base['RSI'] = 0.0
        df_base['Senal'] = 'PENDIENTE'
        st.session_state.oportunidades = df_base
        
    if 'precios_actuales' not in st.session_state: st.session_state.precios_actuales = pd.Series(dtype=float)
    if 'mep_valor' not in st.session_state: st.session_state.mep_valor = None
    if 'mep_var' not in st.session_state: st.session_state.mep_var = None
    if 'last_update' not in st.session_state: st.session_state.last_update = None
    if 'init_done' not in st.session_state: st.session_state.init_done = False
    
# --- LÓGICA DE DETECCIÓN DE TICKERS ---
def get_tickers_a_cargar() -> List[str]:
    """Solo carga Portafolio y MEP (USADO PARA LA CARGA INICIAL/AUTO-REFRESH)."""
    tickers_a_cargar = set()
    tickers_a_cargar.update(database.get_tickers_en_cartera())
    tickers_a_cargar.update(['AL30.BA', 'AL30D.BA', 'GD30.BA', 'GD30D.BA'])
    return list(tickers_a_cargar)

# --- LÓGICA DE ACTUALIZACIÓN BASE ---
def update_data(lista_tickers, nombre_panel, silent=False):
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
            
            # Fusión
            if 'Precio' in df_nuevo_screener.columns:
                nuevos = df_nuevo_screener['Precio']
                st.session_state.precios_actuales.update(nuevos)
                st.session_state.precios_actuales = st.session_state.precios_actuales.combine_first(nuevos)
            
            # CRÍTICO: El merge ahora se hace contra el df de oportunidades, el cual contiene TODOS los tickers
            df_total = st.session_state.oportunidades.copy()
            
            # 1. Actualizar las filas del screener
            for idx in df_nuevo_screener.index:
                if idx in df_total.index:
                    df_total.loc[idx] = df_nuevo_screener.loc[idx]
                
            # 2. Ordenar
            if not df_total.empty:
                cols_sort = ['Senal', 'Suma_Caidas']
                # Se necesita manejar la posibilidad de que Suma_Caidas sea NaN (si el ticker no se cargó)
                if all(c in df_total.columns for c in cols_sort):
                    # Sortear poniendo los NaN al final
                    df_total.sort_values(by=cols_sort, ascending=[True, False], na_position='last', inplace=True)

            st.session_state.oportunidades = df_total
            st.session_state.last_update = datetime.now()
            st.success(f"✅ Datos actualizados.")
            
    else: # Si silent=True, procesa sin spinner
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
        for idx in df_nuevo_screener.index:
             if idx in df_total.index:
                 df_total.loc[idx] = df_nuevo_screener.loc[idx]
        
        if not df_total.empty:
            cols_sort = ['Senal', 'Suma_Caidas']
            if all(c in df_total.columns for c in cols_sort):
                df_total.sort_values(by=cols_sort, ascending=[True, False], na_position='last', inplace=True)

        st.session_state.oportunidades = df_total
        st.session_state.last_update = datetime.now()

# --- FUNCIONES DE ORQUESTACIÓN ---
def actualizar_panel_individual(nombre_panel, lista_tickers):
    """Actualiza un solo panel (Lider, Bonos, etc.)"""
    init_session_state()
    
    t_mep = ['AL30.BA', 'AL30D.BA', 'GD30.BA', 'GD30D.BA']
    t_cartera = database.get_tickers_en_cartera()
    
    # La descarga incluye el panel solicitado + cartera + MEP
    t_a_cargar = list(set(lista_tickers + t_mep + t_cartera))
    
    update_data(t_a_cargar, nombre_panel, silent=False)

# ... [resto de manager.py idéntico] ...


def actualizar_solo_cartera(silent=False):
    """Actualiza solo Portafolio y MEP (para Portafolio_y_Ventas)."""
    init_session_state()
    
    t_cartera = database.get_tickers_en_cartera()
    t_mep = ['AL30.BA', 'AL30D.BA', 'GD30.BA', 'GD30D.BA']
    t_a_cargar = list(set(t_cartera + t_mep))
    
    if not t_a_cargar:
        if not silent: st.warning("No hay activos en cartera para actualizar.")
        return

    update_data(t_a_cargar, "Portafolio en Tenencia", silent=silent)


def actualizar_todo(silent=False):
    """Función para HOME y DASHBOARD (Actualiza solo Portafolio y MEP)."""
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