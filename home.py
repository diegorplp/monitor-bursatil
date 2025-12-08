import streamlit as st
import pandas as pd
from datetime import datetime
import pytz # Importamos librería de zonas horarias
import data_client
import market_logic
import database
import config

try:
    from streamlit_autorefresh import st_autorefresh
    AUTO_REFRESH_DISPONIBLE = True
except ImportError:
    AUTO_REFRESH_DISPONIBLE = False

st.set_page_config(page_title="Monitor Bursátil", layout="wide", initial_sidebar_state="expanded")

if AUTO_REFRESH_DISPONIBLE:
    st_autorefresh(interval=60 * 1000, key="market_refresh")

# --- FUNCIÓN DE HORA LOCAL ---
def get_now_arg():
    """Devuelve la hora actual en Argentina."""
    return datetime.now(pytz.timezone('America/Argentina/Buenos_Aires'))

# --- ESTADO ---
if 'oportunidades' not in st.session_state: st.session_state.oportunidades = pd.DataFrame()
if 'precios_actuales' not in st.session_state: st.session_state.precios_actuales = pd.Series(dtype=float)
if 'paneles_cargados' not in st.session_state: st.session_state.paneles_cargados = []
if 'mep_data' not in st.session_state: st.session_state.mep_data = {}
if 'last_update' not in st.session_state: st.session_state.last_update = None
if 'init_done' not in st.session_state: st.session_state.init_done = False

# --- UPDATE ---
def update_data(lista_tickers, nombre_panel, silent=False):
    if not lista_tickers: return

    contexto = st.spinner(f"Cargando {nombre_panel}...") if not silent else st.empty()
    
    with contexto:
        # Descarga
        df_nuevo_raw = data_client.get_data(lista_tickers)
        
        # Validación de descarga fallida
        if df_nuevo_raw.empty:
            if not silent: st.warning(f"No se pudieron descargar datos para {nombre_panel}.")
            return

        # MEP
        if 'Bonos' in nombre_panel or not st.session_state.mep_data:
             mep_info = data_client.get_mep_detailed()
             if mep_info and 'AL30' in mep_info and 'AL30D' in mep_info:
                 al30 = mep_info['AL30']
                 al30d = mep_info['AL30D']
                 if al30d['bid'] > 0:
                     mc = al30['ask'] / al30d['bid']
                     mv = al30['bid'] / al30d['ask'] if al30d['ask'] > 0 else mc
                     spr = (mc / mv) - 1 if mv > 0 else 0
                 else:
                     mc = al30['last'] / al30d['last'] if al30d['last'] else 0
                     spr = 0.0
                 st.session_state.mep_data = {'compra': mc, 'spread': spr}

        # Indicadores
        df_screener = market_logic.calcular_indicadores(df_nuevo_raw)
        if df_screener.empty: return

        # Fusión
        if not st.session_state.oportunidades.empty:
            df_total = pd.concat([st.session_state.oportunidades, df_screener])
            df_total = df_total[~df_total.index.duplicated(keep='last')]
        else:
            df_total = df_screener

        if not df_total.empty:
            df_total.sort_values(by=['Senal', 'Suma_Caidas'], ascending=[True, False], inplace=True)

        st.session_state.oportunidades = df_total
        
        if 'Precio' in df_screener.columns:
            nuevos = df_screener['Precio']
            st.session_state.precios_actuales = st.session_state.precios_actuales.combine_first(nuevos)
            st.session_state.precios_actuales.update(nuevos)
        
        if nombre_panel not in st.session_state.paneles_cargados:
            st.session_state.paneles_cargados.append(nombre_panel)
            
        # Usamos hora Argentina
        st.session_state.last_update = get_now_arg()
        
        if not silent: st.success(f"{nombre_panel} actualizado.")

def get_styled_screener(df):
    if df.empty: return df
    def highlight_buy(row):
        return ['background-color: rgba(33, 195, 84, 0.2)'] * len(row) if row.get('Senal') == 'COMPRAR' else [''] * len(row)
    return df.style.apply(highlight_buy, axis=1).format({'Precio': '{:,.2f}', 'RSI': '{:.2f}', 'Caida_30d': '{:.2%}', 'Caida_5d': '{:.2%}', 'Suma_Caidas': '{:.2%}'})

# --- AUTO UPDATE CHECK ---
now_arg = get_now_arg()
if st.session_state.last_update:
    delta = now_arg - st.session_state.last_update
    if delta.total_seconds() > 65:
        t_bonos = config.TICKERS_CONFIG.get('Bonos', [])
        if t_bonos: update_data(t_bonos, "Bonos (Auto)", silent=True)
        t_cart = database.get_tickers_en_cartera()
        if t_cart: update_data(t_cart, "Cartera (Auto)", silent=True)

# --- UI ---
c1, c2 = st.columns([3, 2])
c1.title("Monitor Bursátil")
with c2:
    cm, ct = st.columns(2)
    with cm:
        mep = st.session_state.mep_data
        if mep:
            val = mep.get('compra', 0)
            spr = mep.get('spread', 0)
            st.metric("Dólar MEP", f"${val:,.2f}", f"Spread: {spr:.2%}")
        else: st.info("Cargando MEP...")
    with ct:
        if st.session_state.last_update:
            st.caption(f"Actualizado: {st.session_state.last_update.strftime('%H:%M:%S')}")
            st.progress(100)

if not st.session_state.init_done:
    st.session_state.init_done = True
    t_bonos = config.TICKERS_CONFIG.get('Bonos', [])
    if t_bonos: update_data(t_bonos, "Bonos", silent=True)
    t_cart = database.get_tickers_en_cartera()
    if t_cart: update_data(t_cart, "Cartera", silent=True)
    st.rerun()

st.divider()

# A. PANEL RECIENTES (CON DIAGNÓSTICO)
with st.expander("📂 Transacciones Recientes / En Cartera", expanded=True):
    col_a, col_b = st.columns([1, 4])
    
    # --- DIAGNÓSTICO DE CONEXIÓN ---
    if col_a.button("Actualizar Recientes"):
        try:
            tickers = database.get_tickers_en_cartera()
            if tickers:
                st.success(f"Conexión Exitosa. Tickers encontrados: {len(tickers)}")
                update_data(tickers, "Cartera")
            else:
                st.warning("La base de datos conectó pero devolvió lista vacía.")
        except Exception as e:
            st.error(f"❌ ERROR CRÍTICO DE BASE DE DATOS: {str(e)}")
            # Intentamos ver si es la credencial
            if config.USE_CLOUD_AUTH:
                st.write("Modo: NUBE (Secrets)")
            else:
                st.write("Modo: LOCAL (Archivo)")

# RESTO PANELES
paneles_orden = ['Favoritos', 'Lider', 'Cedears', 'General', 'Bonos']
iconos = {'Favoritos': '⭐', 'Lider': '🏆', 'Cedears': '🌎', 'General': '📊', 'Bonos': 'b'}

for p in paneles_orden:
    if p in config.TICKERS_CONFIG:
        # Lógica especial para Favoritos: leer de DB
        lista_tickers = []
        if p == 'Favoritos':
            lista_tickers = database.get_favoritos()
        else:
            lista_tickers = config.TICKERS_CONFIG[p]

        with st.expander(f"{iconos.get(p, '')} {p}", expanded=False):
            if st.button(f"Cargar {p}", key=f"btn_{p}"):
                if lista_tickers: update_data(lista_tickers, p)
                else: st.warning("Lista vacía.")
            
            # Gestión de Favoritos UI
            if p == 'Favoritos':
                with st.popover("Gestionar Favoritos"):
                    new = st.text_input("Ticker").upper()
                    c_add, c_del = st.columns(2)
                    if c_add.button("Agregar"): 
                        if new: database.add_favorito(new); st.rerun()
                    if lista_tickers:
                        d_sel = st.selectbox("Borrar", lista_tickers)
                        if c_del.button("Eliminar"):
                            database.remove_favorito(d_sel); st.rerun()

            if p in st.session_state.paneles_cargados:
                mask = st.session_state.oportunidades.index.isin(lista_tickers)
                df_show = st.session_state.oportunidades[mask]
                st.dataframe(get_styled_screener(df_show), use_container_width=True)