import streamlit as st
import config
import database
import manager 
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# --- CONFIGURACIÓN ---
AUTO_REFRESH_DISPONIBLE = True

st.set_page_config(page_title="Monitor Bursátil", layout="wide", initial_sidebar_state="expanded")

# Inicializar Estado
manager.init_session_state()

# --- AUTO-REFRESH ---
if AUTO_REFRESH_DISPONIBLE:
    st_autorefresh(interval=60 * 1000, key="market_refresh")

# --- LÓGICA DE CARGA INICIAL/AUTO-REFRESH ---
# La carga inicial ahora solo pide Portafolio + MEP
if not st.session_state.init_done or (st.session_state.last_update and (datetime.now() - st.session_state.last_update).total_seconds() > 65):
    manager.actualizar_todo(silent=True)
    st.session_state.init_done = True
    st.rerun()

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
        
manager.mostrar_boton_actualizar()

st.divider()

# --- Lógica de Estilo (Copiada para evitar dependencia) ---
def get_styled_screener(df):
    if df.empty: return df
    def highlight_buy(row):
        return ['background-color: rgba(33, 195, 84, 0.2)'] * len(row) if row.get('Senal') == 'COMPRAR' else [''] * len(row)
    return df.style.apply(highlight_buy, axis=1).format({'Precio': '{:,.2f}', 'RSI': '{:.2f}', 'Caida_30d': '{:.2%}', 'Caida_5d': '{:.2%}', 'Suma_Caidas': '{:.2%}'})

# --- PANELES ---

# A. PANEL CARTERA (Siempre visible)
mis_tickers = database.get_tickers_en_cartera()
with st.expander("📂 Transacciones Recientes / En Cartera", expanded=True):
    if st.button("Refrescar Cartera"):
        manager.actualizar_todo(silent=False)
        st.rerun()
    
    df_cartera = st.session_state.oportunidades[st.session_state.oportunidades.index.isin(mis_tickers)]
    if not df_cartera.empty:
        st.dataframe(get_styled_screener(df_cartera), use_container_width=True)
    elif len(mis_tickers) > 0: st.caption("Esperando datos de mercado...")
    else: st.caption("Tu portafolio está vacío.")


# C. RESTO PANELES
paneles = ['Lider', 'Cedears', 'General', 'Bonos']
iconos = {'Lider': '🏆', 'Cedears': '🌎', 'General': '📊', 'Bonos': 'b'}

for p in paneles:
    if p in config.TICKERS_CONFIG:
        # Se elimina el control de estado y el key para máxima estabilidad
        with st.expander(f"{iconos.get(p, '')} {p}", expanded=False):
            
            # El botón de carga ahora es la ÚNICA forma de cargar ese panel
            if st.button(f"Cargar {p}", key=f"btn_{p}"):
                # Llama a la función que descarga ese panel y vuelve
                manager.actualizar_panel_individual(p, config.TICKERS_CONFIG[p])
                st.rerun()
            
            # Renderizado Condicional
            df_show = st.session_state.oportunidades[st.session_state.oportunidades.index.isin(config.TICKERS_CONFIG[p])]
            if not df_show.empty:
                st.dataframe(get_styled_screener(df_show), use_container_width=True)
            else:
                 st.caption("Pulse Cargar para obtener datos.")