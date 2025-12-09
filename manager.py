import streamlit as st
import pandas as pd
from datetime import datetime
import data_client
import market_logic
import database
import config
from typing import List

# --- INICIALIZACIÓN DE ESTADO ---
def init_session_state():
    if 'oportunidades' not in st.session_state: st.session_state.oportunidades = pd.DataFrame()
    if 'precios_actuales' not in st.session_state: st.session_state.precios_actuales = pd.Series(dtype=float)
    if 'paneles_cargados' not in st.session_state: st.session_state.paneles_cargados = []
    if 'mep_valor' not in st.session_state: st.session_state.mep_valor = None
    if 'mep_var' not in st.session_state: st.session_state.mep_var = None
    if 'last_update' not in st.session_state: st.session_state.last_update = None
    if 'init_done' not in st.session_state: st.session_state.init_done = False
    # CRÍTICO: Registramos qué paneles están expandidos para lazy loading
    if 'paneles_expandidos' not in st.session_state: st.session_state.paneles_expandidos = ['Cartera'] # Cartera siempre está abierta

# --- LÓGICA DE DETECCIÓN DE TICKERS ---
def get_tickers_a_cargar() -> List[str]:
    """
    Combina tickers de todos los paneles que están expandidos (o son Cartera/Favoritos).
    """
    tickers_a_cargar = set()
    
    # 1. Cartera (SIEMPRE se cargan sus precios)
    tickers_a_cargar.update(database.get_tickers_en_cartera())
    
    # 2. Favoritos (Sólo si están en la lista de expandidos o si es la carga inicial)
    if 'Favoritos' in st.session_state.paneles_expandidos or not st.session_state.init_done:
        tickers_a_cargar.update(database.get_favoritos())

    # 3. Paneles Expandidos (Lazy Loading)
    for panel in st.session_state.paneles_expandidos:
        if panel in config.TICKERS_CONFIG:
            tickers_a_cargar.update(config.TICKERS_CONFIG[panel])
            
    # Siempre incluir los tickers necesarios para MEP
    tickers_a_cargar.update(['AL30.BA', 'AL30D.BA', 'GD30.BA', 'GD30D.BA'])
    
    return list(tickers_a_cargar)

# --- LÓGICA DE ACTUALIZACIÓN ---
def update_data(lista_tickers, nombre_panel, silent=False):
    # Ya no necesita el nombre del panel, solo los tickers
    if not lista_tickers: return

    contexto = st.spinner(f"Cargando {nombre_panel}...") if not silent else st.empty()
    
    with contexto:
        # 2. Descarga
        df_nuevo_raw = data_client.get_data(lista_tickers)
        
        if df_nuevo_raw.empty:
            if not silent: st.warning(f"No se encontraron datos.")
            return

        # 3. MEP
        mep, var = market_logic.calcular_mep(df_nuevo_raw)
        if mep:
            st.session_state.mep_valor = mep
            st.session_state.mep_var = var

        # 4. Indicadores
        try:
            df_nuevo_screener = market_logic.calcular_indicadores(df_nuevo_raw)
        except: return

        if df_nuevo_screener.empty: return

        # 5. Fusión (Mantiene todos los paneles, actualizando solo los nuevos)
        # CRÍTICO: En lugar de fusionar, vamos a actualizar los precios y re-analizar.
        
        # A. Actualizar precios actuales
        if 'Precio' in df_nuevo_screener.columns:
            nuevos = df_nuevo_screener['Precio']
            # Reemplazar valores existentes con los nuevos
            st.session_state.precios_actuales.update(nuevos)
            # Agregar tickers nuevos si no existían
            st.session_state.precios_actuales = st.session_state.precios_actuales.combine_first(nuevos)
        
        # B. Fusionar dataframes de screener, manteniendo el orden de carga (keep='last')
        if not st.session_state.oportunidades.empty:
            df_total = pd.concat([st.session_state.oportunidades.drop(df_nuevo_screener.index, errors='ignore'), df_nuevo_screener])
            df_total = df_total[~df_total.index.duplicated(keep='last')]
        else:
            df_total = df_nuevo_screener

        # 6. Orden (Ordenar solo si es la lista completa)
        if not df_total.empty:
            cols_sort = ['Senal', 'Suma_Caidas']
            if all(c in df_total.columns for c in cols_sort):
                df_total.sort_values(by=cols_sort, ascending=[True, False], inplace=True)

        st.session_state.oportunidades = df_total
        
        # El registro de paneles cargados es ahora irrelevante, el control es por 'paneles_expandidos'
            
        st.session_state.last_update = datetime.now()
        
        if not silent: st.success(f"Datos de {nombre_panel} actualizados.")


def actualizar_todo(silent=False):
    """
    Función de carga inicial/manual: Determina qué cargar, lo carga y detona el rerun.
    """
    init_session_state()
    
    # Esta función ahora solo detecta qué cargar y llama a la función principal de carga
    t_a_cargar = get_tickers_a_cargar()
    
    if not t_a_cargar:
        if not silent: st.warning("No hay tickers en Portafolio ni en el panel abierto.")
        return

    # Usamos update_data como la única fuente de la verdad para la carga
    update_data(t_a_cargar, "Mercado Global", silent=silent)


# --- WIDGET DE SIDEBAR ---
def mostrar_boton_actualizar():
    init_session_state()

    st.sidebar.markdown("---")
    st.sidebar.subheader("📡 Datos de Mercado")
    
    # CRÍTICO: El botón ahora SÓLO hace el RERUN. La lógica de carga la toma Home.py
    if st.sidebar.button("🔄 Actualizar Todo", use_container_width=True):
        st.session_state.init_done = False # Forzar re-lectura
        st.rerun() # Dispara la carga completa

    if st.session_state.last_update:
        st.sidebar.caption(f"Última act: {st.session_state.last_update.strftime('%H:%M:%S')}")
        
    if st.session_state.mep_valor:
        st.sidebar.metric("MEP", f"${st.session_state.mep_valor:,.0f}")