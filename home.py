import streamlit as st
import pandas as pd
from datetime import datetime
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
        # 1. Descarga
        df_nuevo_raw = data_client.get_data(lista_tickers)
        
        # INICIALIZACIÓN SEGURA DE VARIABLES
        df_nuevo_screener = pd.DataFrame() 

        # 2. MEP
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

        if df_nuevo_raw.empty:
            if not silent: st.warning(f"Sin datos para {nombre_panel}.")
            return

        # 3. Indicadores
        try:
            df_nuevo_screener = market_logic.calcular_indicadores(df_nuevo_raw)
        except: pass
        
        if df_nuevo_screener.empty: return

        # 4. Fusión
        if not st.session_state.oportunidades.empty:
            df_total = pd.concat([st.session_state.oportunidades, df_nuevo_screener])
            df_total = df_total[~df_total.index.duplicated(keep='last')]
        else:
            df_total = df_nuevo_screener

        if not df_total.empty:
            df_total.sort_values(by=['Senal', 'Suma_Caidas'], ascending=[True, False], inplace=True)

        st.session_state.oportunidades = df_total
        
        if 'Precio' in df_nuevo_screener.columns:
            nuevos = df_nuevo_screener['Precio']
            st.session_state.precios_actuales = st.session_state.precios_actuales.combine_first(nuevos)
            st.session_state.precios_actuales.update(nuevos)
        
        if nombre_panel not in st.session_state.paneles_cargados:
            st.session_state.paneles_cargados.append(nombre_panel)
            
        st.session_state.last_update = datetime.now()
        if not silent: st.success(f"{nombre_panel} actualizado.")

def get_styled_screener(df):
    if df.empty: return df
    def highlight_buy(row):
        return ['background-color: rgba(33, 195, 84, 0.2)'] * len(row) if row.get('Senal') == 'COMPRAR' else [''] * len(row)
    return df.style.apply(highlight_buy, axis=1).format({'Precio': '{:,.2f}', 'RSI': '{:.2f}', 'Caida_30d': '{:.2%}', 'Caida_5d': '{:.2%}', 'Suma_Caidas': '{:.2%}'})

# --- AUTO UPDATE ---
now = datetime.now()
if st.session_state.last_update:
    delta = now - st.session_state.last_update
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

# PANELES
with st.expander("📂 Transacciones Recientes / En Cartera", expanded=True):
    col_a, col_b = st.columns([1, 4])
    if col_a.button("Actualizar Recientes"):
        tickers = database.get_tickers_en_cartera()
        if tickers: update_data(tickers, "Cartera")
        else: st.info("Cartera vacía.")

    if not st.session_state.oportunidades.empty:
        mis_tickers = database.get_tickers_en_cartera()
        mis_t_norm = [str(t).strip().upper() for t in mis_tickers]
        idx_norm = st.session_state.oportunidades.index.astype(str).str.strip().str.upper()
        mask = idx_norm.isin(mis_t_norm)
        df_show = st.session_state.oportunidades[mask]
        if not df_show.empty:
            st.dataframe(get_styled_screener(df_show), use_container_width=True)
        else:
             if len(mis_tickers) > 0: st.info("Cargando precios...")
    else: st.caption("Esperando datos...")

paneles = ['Favoritos', 'Lider', 'Cedears', 'General', 'Bonos']
iconos = {'Favoritos': '⭐', 'Lider': '🏆', 'Cedears': '🌎', 'General': '📊', 'Bonos': 'b'}

for p in paneles:
    if p in config.TICKERS_CONFIG:
        with st.expander(f"{iconos.get(p, '')} {p}", expanded=False):
            if st.button(f"Cargar {p}", key=f"btn_{p}"):
                update_data(config.TICKERS_CONFIG[p], p)
            
            if p in st.session_state.paneles_cargados:
                mask = st.session_state.oportunidades.index.isin(config.TICKERS_CONFIG[p])
                df_show = st.session_state.oportunidades[mask]
                st.dataframe(get_styled_screener(df_show), use_container_width=True)