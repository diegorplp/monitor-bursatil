import streamlit as st
import pandas as pd
from datetime import datetime
import data_client
import market_logic
import database
import config
import time
from typing import List
import numpy as np # Necesario para el np.nan

# --- INICIALIZACIÓN DE ESTADO (Mantenido) ---
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
    
# --- LÓGICA DE ACTUALIZACIÓN BASE ---
def update_data(lista_tickers, nombre_panel, silent=False):
    if not lista_tickers: return

    if not silent:
        with st.spinner(f"Cargando {nombre_panel}..."):
            # CRÍTICO: Si es SOLOS IOL (Dashboard), no llama a Yahoo
            if nombre_panel == "SOLO IOL (Dashboard)":
                dict_precios_hoy = data_client.get_current_prices_iol(lista_tickers)
                if not dict_precios_hoy:
                    st.warning(f"⚠️ No se encontraron precios en tiempo real.")
                    return
                
                # Actualizar precios
                st.session_state.precios_actuales.update(dict_precios_hoy)
                st.session_state.precios_actuales = st.session_state.precios_actuales.combine_first(pd.Series(dict_precios_hoy))
                
                # Recalcular MEP
                df_raw = pd.DataFrame([dict_precios_hoy])
                mep, var = market_logic.calcular_mep(df_raw)
                if mep:
                    st.session_state.mep_valor = mep
                    st.session_state.mep_var = var
                
                st.session_state.last_update = datetime.now()
                st.success(f"✅ Precios IOL actualizados.")
                return

            # --- Lógica de Descarga COMPLETA (Home) ---
            df_nuevo_raw = data_client.get_data(lista_tickers)
            # ... [Bloque de procesamiento restante idéntico] ...
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
            
    else: # Si silent=True, procesa sin spinner
        # Lógica de carga silenciosa (Auto-Refresh)
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


def actualizar_solo_iol():
    """NUEVA FUNCIÓN: Actualiza solo IOL (precios de Portafolio + MEP) para DASHBOARD."""
    init_session_state()
    
    t_cartera = database.get_tickers_en_cartera()
    t_mep = ['AL30.BA', 'AL30D.BA', 'GD30.BA', 'GD30D.BA']
    t_a_cargar = list(set(t_cartera + t_mep))
    
    if not t_a_cargar:
        st.warning("No hay activos para actualizar.")
        return

    # Llama al update_data con un nombre especial para activar la lógica de SOLO IOL
    update_data(t_a_cargar, "SOLO IOL (Dashboard)", silent=False)


def actualizar_todo(silent=False):
    """Función para HOME y DASHBOARD (Carga SOLO MEP al inicio)."""
    init_session_state()

    if not st.session_state.init_done:
        t_a_cargar = get_tickers_a_cargar()
        update_data(t_a_cargar, "MEP Base", silent=silent)
    else:
        # Aquí es donde fallamos, si init_done=True, intentamos actualizar la cartera completa.
        actualizar_solo_cartera(silent=silent)


# ... [Bloque de funciones restantes idéntico omitido] ...
def get_tickers_a_cargar() -> List[str]:
    tickers_a_cargar = set()
    tickers_a_cargar.update(['AL30.BA', 'AL30D.BA', 'GD30.BA', 'GD30D.BA'])
    return list(tickers_a_cargar)

def actualizar_solo_cartera(silent=False):
    init_session_state()
    
    t_cartera = database.get_tickers_en_cartera()
    t_mep = ['AL30.BA', 'AL30D.BA', 'GD30.BA', 'GD30D.BA']
    t_a_cargar = list(set(t_cartera + t_mep))
    
    if not t_a_cargar:
        t_a_cargar = get_tickers_a_cargar()
        
    update_data(t_a_cargar, "Portafolio en Tenencia", silent=silent)

def actualizar_panel_individual(nombre_panel, lista_tickers):
    init_session_state()
    
    t_mep = ['AL30.BA', 'AL30D.BA', 'GD30.BA', 'GD30D.BA']
    t_cartera = database.get_tickers_en_cartera()
    
    t_a_cargar = list(set(lista_tickers + t_mep + t_cartera))
    
    update_data(t_a_cargar, nombre_panel, silent=False)

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