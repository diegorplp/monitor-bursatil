import streamlit as st
import pandas as pd
from datetime import datetime
import data_client
import market_logic
import database
import config

# --- INICIALIZACIÓN DE ESTADO ---
def init_session_state():
    """Inicializa todas las variables de sesión si no existen."""
    if 'oportunidades' not in st.session_state: st.session_state.oportunidades = pd.DataFrame()
    if 'precios_actuales' not in st.session_state: st.session_state.precios_actuales = pd.Series(dtype=float)
    if 'paneles_cargados' not in st.session_state: st.session_state.paneles_cargados = []
    if 'mep_valor' not in st.session_state: st.session_state.mep_valor = None
    if 'mep_var' not in st.session_state: st.session_state.mep_var = None
    if 'mep_intentado' not in st.session_state: st.session_state.mep_intentado = False
    if 'last_update' not in st.session_state: st.session_state.last_update = None
    if 'init_done' not in st.session_state: st.session_state.init_done = False
    if 'cartera_intentada' not in st.session_state: st.session_state.cartera_intentada = False

# --- LÓGICA DE ACTUALIZACIÓN ---
def update_data(lista_tickers, nombre_panel, silent=False):
    """Descarga, calcula y fusiona datos nuevos."""
    
    # 1. BLINDAJE DE SEGURIDAD (FIX ERROR ATTRIBUTE)
    # Aseguramos que la variable exista antes de usarla
    if 'oportunidades' not in st.session_state:
        st.session_state.oportunidades = pd.DataFrame()
    if 'precios_actuales' not in st.session_state:
        st.session_state.precios_actuales = pd.Series(dtype=float)
        
    if not lista_tickers: return

    contexto = st.spinner(f"Cargando {nombre_panel}...") if not silent else st.empty()
    
    with contexto:
        # 2. Descarga
        df_nuevo_raw = data_client.get_data(lista_tickers)
        
        if df_nuevo_raw.empty:
            if not silent: st.warning(f"No se encontraron datos para {nombre_panel}.")
            return

        # 3. MEP
        if 'AL30.BA' in df_nuevo_raw.columns:
            mep, var = market_logic.calcular_mep(df_nuevo_raw)
            if mep:
                st.session_state.mep_valor = mep
                st.session_state.mep_var = var

        # 4. Indicadores
        try:
            df_nuevo_screener = market_logic.calcular_indicadores(df_nuevo_raw)
        except: 
            return

        if df_nuevo_screener.empty: return

        # 5. Fusión
        if not st.session_state.oportunidades.empty:
            df_total = pd.concat([st.session_state.oportunidades, df_nuevo_screener])
            df_total = df_total[~df_total.index.duplicated(keep='last')]
        else:
            df_total = df_nuevo_screener

        # 6. Orden
        if not df_total.empty:
            cols_sort = ['Senal', 'Suma_Caidas']
            if all(c in df_total.columns for c in cols_sort):
                df_total.sort_values(by=cols_sort, ascending=[True, False], inplace=True)

        st.session_state.oportunidades = df_total
        
        if 'Precio' in df_nuevo_screener.columns:
            nuevos = df_nuevo_screener['Precio']
            st.session_state.precios_actuales = st.session_state.precios_actuales.combine_first(nuevos)
            st.session_state.precios_actuales.update(nuevos)
        
        if nombre_panel not in st.session_state.paneles_cargados:
            st.session_state.paneles_cargados.append(nombre_panel)
            
        st.session_state.last_update = datetime.now()
        
        if not silent: st.success(f"{nombre_panel} actualizado.")

def actualizar_todo(silent=False):
    """Actualiza Bonos, Cartera y Favoritos de una sola vez."""
    # Asegurar inicialización antes de actualizar
    init_session_state()
    
    # 1. Bonos (MEP)
    t_bonos = config.TICKERS_CONFIG.get('Bonos', [])
    if t_bonos: update_data(t_bonos, "Bonos", silent=silent)
    
    # 2. Cartera
    t_cart = database.get_tickers_en_cartera()
    if t_cart: update_data(t_cart, "Cartera", silent=silent)
    
    # 3. Favoritos
    t_fav = database.get_favoritos()
    if t_fav: update_data(t_fav, "Favoritos", silent=True)

# --- WIDGET DE SIDEBAR ---
def mostrar_boton_actualizar():
    """Muestra el estado y botón en la barra lateral."""
    
    # BLINDAJE DE INICIO: Si entramos directo aquí, inicializar todo.
    if 'last_update' not in st.session_state:
        init_session_state()

    st.sidebar.markdown("---")
    st.sidebar.subheader("📡 Datos de Mercado")
    
    if st.sidebar.button("🔄 Actualizar Todo", use_container_width=True):
        actualizar_todo(silent=False)
        st.rerun()
        
    if st.session_state.last_update:
        st.sidebar.caption(f"Última act: {st.session_state.last_update.strftime('%H:%M:%S')}")
        
    if st.session_state.mep_valor:
        st.sidebar.metric("MEP", f"${st.session_state.mep_valor:,.0f}")