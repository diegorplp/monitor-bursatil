import streamlit as st
import config
import database
import manager 
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# --- CONFIGURACIÓN ---
AUTO_REFRESH_DISPONIBLE = True

st.set_page_config(page_title="Monitor Bursátil", layout="wide", initial_sidebar_state="expanded")

# Inicializar Estado (manager.py ahora inicializa los expanded_panel)
manager.init_session_state()

# --- AUTO-REFRESH ---
if AUTO_REFRESH_DISPONIBLE:
    st_autorefresh(interval=60 * 1000, key="market_refresh")

# --- LÓGICA DE CARGA INICIAL/AUTO-REFRESH ---
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
        
# --- BOTÓN GLOBAL EN SIDEBAR ---
manager.mostrar_boton_actualizar()

st.divider()

# --- Lógica de Estilo ---
def get_styled_screener(df):
    if df.empty: return df
    def highlight_buy(row):
        return ['background-color: rgba(33, 195, 84, 0.2)'] * len(row) if row.get('Senal') == 'COMPRAR' else [''] * len(row)
    return df.style.apply(highlight_buy, axis=1).format({'Precio': '{:,.2f}', 'RSI': '{:.2f}', 'Caida_30d': '{:.2%}', 'Caida_5d': '{:.2%}', 'Suma_Caidas': '{:.2%}'})


# --- PANELES ---

# A. PANEL CARTERA (Siempre visible)
mis_tickers = database.get_tickers_en_cartera()
# El expander de Cartera ya no tiene lógica de estado, siempre está abierto.
with st.expander("📂 Transacciones Recientes / En Cartera", expanded=True):
    # CRÍTICO: Botón que llama a manager para actualizar todo
    if st.button("Refrescar Cartera"):
        manager.actualizar_todo(silent=False)
        st.rerun()
    
    df_cartera = st.session_state.oportunidades[st.session_state.oportunidades.index.isin(mis_tickers)]
    if not df_cartera.empty:
        st.dataframe(get_styled_screener(df_cartera), use_container_width=True)
    elif len(mis_tickers) > 0: st.caption("Esperando datos de mercado...")
    else: st.caption("Tu portafolio está vacío.")


# B. FAVORITOS
favs = database.get_favoritos()
panel_name = 'Favoritos'

def update_panel_state(key):
    """Callback para guardar si un panel se abre o se cierra."""
    st.session_state[f'expanded_{key}'] = st.session_state[f'exp_{key}']
    manager.actualizar_todo(silent=True) # Actualizar para cargar datos del panel


# CRÍTICO: Usamos el estado de session_state para expandido
with st.expander(f"⭐ {panel_name}", 
                 expanded=st.session_state.get(f'expanded_{panel_name}', False), 
                 key=f"exp_{panel_name}", 
                 on_change=update_panel_state, 
                 args=(panel_name,)):
    
    # 1. Botón de Carga
    c_btn, c_gest = st.columns([1, 4])
    if c_btn.button(f"Cargar {panel_name}"):
         st.session_state[f'expanded_{panel_name}'] = True # Marcar para mantener abierto
         manager.actualizar_todo(silent=False)
         st.rerun()
        
    # 2. Gestión
    with c_gest.popover("Gestionar Lista"):
        new = st.text_input("Ticker").upper()
        c_add, c_del = st.columns(2)
        if c_add.button("Agregar"): 
            if new: database.add_favorito(new); st.rerun()
        if favs:
            del_fav = st.selectbox("Eliminar", favs)
            if c_del.button("Eliminar"):
                database.remove_favorito(del_fav); st.rerun()

    # 3. Renderizado
    df_favs = st.session_state.oportunidades[st.session_state.oportunidades.index.isin(favs)]
    if not df_favs.empty:
         st.dataframe(get_styled_screener(df_favs), use_container_width=True)


# C. RESTO PANELES
paneles = ['Lider', 'Cedears', 'General', 'Bonos']
iconos = {'Lider': '🏆', 'Cedears': '🌎', 'General': '📊', 'Bonos': 'b'}

for p in paneles:
    if p in config.TICKERS_CONFIG:
        with st.expander(f"{iconos.get(p, '')} {p}", 
                         expanded=st.session_state.get(f'expanded_{p}', False), 
                         key=f"exp_{p}",
                         on_change=update_panel_state,
                         args=(p,)):
            
            # 1. Botón de Carga
            if st.button(f"Cargar {p}", key=f"btn_{p}"):
                st.session_state[f'expanded_{p}'] = True # Marcar para mantener abierto
                manager.actualizar_todo(silent=False)
                st.rerun()
            
            # 2. Renderizado Condicional
            df_show = st.session_state.oportunidades[st.session_state.oportunidades.index.isin(config.TICKERS_CONFIG[p])]
            if not df_show.empty:
                st.dataframe(get_styled_screener(df_show), use_container_width=True)
            else:
                 # Mensaje de carga
                 if st.session_state.get(f'expanded_{p}', False): st.caption("Pulse Cargar para obtener datos.")