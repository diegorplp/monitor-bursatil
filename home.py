import streamlit as st
import config
import database
import manager # Importamos el nuevo cerebro

# --- CONFIGURACIÓN ---
try:
    from streamlit_autorefresh import st_autorefresh
    AUTO_REFRESH_DISPONIBLE = True
except ImportError:
    AUTO_REFRESH_DISPONIBLE = False

st.set_page_config(page_title="Monitor Bursátil", layout="wide", initial_sidebar_state="expanded")

# Inicializar Estado
manager.init_session_state()

# --- AUTO-REFRESH ---
if AUTO_REFRESH_DISPONIBLE:
    st_autorefresh(interval=60 * 1000, key="market_refresh")

# --- UI PRINCIPAL ---
c1, c2 = st.columns([3, 2])
c1.title("Monitor Bursátil")
with c2:
    cm, ct = st.columns(2)
    with cm:
        if st.session_state.mep_valor:
            st.metric("Dólar MEP", f"${st.session_state.mep_valor:,.2f}", f"{st.session_state.mep_var:.2%}")
        else: st.info("Cargando MEP...")
    with ct:
        if st.session_state.last_update:
            st.caption(f"Actualizado: {st.session_state.last_update.strftime('%H:%M:%S')}")
            st.progress(100)

# --- BOTÓN GLOBAL EN SIDEBAR ---
manager.mostrar_boton_actualizar()

# --- AUTO START ---
if not st.session_state.init_done:
    st.session_state.init_done = True
    manager.actualizar_todo(silent=True)
    st.rerun()

# --- AUTO REFRESH CHECK ---
now = datetime.now()
if st.session_state.last_update:
    delta = now - st.session_state.last_update
    if delta.total_seconds() > 65:
        manager.actualizar_todo(silent=True)

st.divider()

# --- PANELES ---

# Estilos locales (copia breve)
def get_styled_screener(df):
    if df.empty: return df
    def highlight_buy(row):
        return ['background-color: rgba(33, 195, 84, 0.2)'] * len(row) if row.get('Senal') == 'COMPRAR' else [''] * len(row)
    return df.style.apply(highlight_buy, axis=1).format({'Precio': '{:,.2f}', 'RSI': '{:.2f}', 'Caida_30d': '{:.2%}', 'Caida_5d': '{:.2%}', 'Suma_Caidas': '{:.2%}'})

# A. PANEL RECIENTES
with st.expander("📂 Transacciones Recientes / En Cartera", expanded=True):
    # Ya no hace falta botón acá, está en el sidebar, pero lo dejamos por comodidad
    if st.button("Actualizar Recientes"):
        t = database.get_tickers_en_cartera()
        if t: manager.update_data(t, "Cartera")

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

# B. FAVORITOS
with st.expander("⭐ Favoritos", expanded=False):
    favs = database.get_favoritos()
    c_btn, c_gest = st.columns([1, 4])
    if c_btn.button("Cargar Favoritos"):
        if favs: manager.update_data(favs, "Favoritos")
        
    with c_gest.popover("Gestionar Lista"):
        new = st.text_input("Ticker").upper()
        c_add, c_del = st.columns(2)
        if c_add.button("Agregar"): 
            if new: database.add_favorito(new); st.rerun()
        if favs:
            del_fav = st.selectbox("Eliminar", favs)
            if c_del.button("Eliminar"):
                database.remove_favorito(del_fav); st.rerun()

    if 'Favoritos' in st.session_state.paneles_cargados:
        mask = st.session_state.oportunidades.index.isin(favs)
        df_show = st.session_state.oportunidades[mask]
        st.dataframe(get_styled_screener(df_show), use_container_width=True)

# C. RESTO PANELES
paneles = ['Lider', 'Cedears', 'General', 'Bonos']
iconos = {'Lider': '🏆', 'Cedears': '🌎', 'General': '📊', 'Bonos': 'b'}

for p in paneles:
    if p in config.TICKERS_CONFIG:
        with st.expander(f"{iconos.get(p, '')} {p}", expanded=False):
            if st.button(f"Cargar {p}", key=f"btn_{p}"):
                manager.update_data(config.TICKERS_CONFIG[p], p)
            
            if p in st.session_state.paneles_cargados:
                mask = st.session_state.oportunidades.index.isin(config.TICKERS_CONFIG[p])
                df_show = st.session_state.oportunidades[mask]
                st.dataframe(get_styled_screener(df_show), use_container_width=True)