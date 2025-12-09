import streamlit as st
import config
import database
import manager 
from datetime import datetime
from streamlit_autorefresh import st_autorefresh # Asumo que sigue disponible

# --- CONFIGURACIÓN ---
AUTO_REFRESH_DISPONIBLE = True # Asumo que la librería está instalada

st.set_page_config(page_title="Monitor Bursátil", layout="wide", initial_sidebar_state="expanded")

# Inicializar Estado
manager.init_session_state()

# --- AUTO-REFRESH ---
# Disparador en 60s
if AUTO_REFRESH_DISPONIBLE:
    st_autorefresh(interval=60 * 1000, key="market_refresh")

# --- LÓGICA DE CARGA INICIAL/AUTO-REFRESH ---
if not st.session_state.init_done or (st.session_state.last_update and (datetime.now() - st.session_state.last_update).total_seconds() > 65):
    # Si es la primera vez o ha pasado más de 65s (por el auto-refresh)
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
            st.progress(100)

# --- BOTÓN GLOBAL EN SIDEBAR ---
manager.mostrar_boton_actualizar()

st.divider()

# --- HELPER: REGISTRO DE PANELES ---
def render_panel(panel_name, tickers, icono):
    # Esta función se llama al abrir el expander
    is_expanded = st.session_state.paneles_expandidos.count(panel_name) > 0

    with st.expander(f"{icono} {panel_name}", expanded=is_expanded):
        # Lógica de guardado de estado al interactuar con el expander (si se usa directamente)
        # Para Streamlit 1.x, es mejor usar callbacks, pero para ser quirúrgico, lo mantenemos simple:

        # 1. Botón para cargar (Ahora solo detona la recarga de TODOS los paneles abiertos)
        if st.button(f"Cargar/Refrescar {panel_name}"):
            # Forzamos una actualización de todo lo visible y lo forzamos a abrir
            if panel_name not in st.session_state.paneles_expandidos:
                 st.session_state.paneles_expandidos.append(panel_name)
            manager.actualizar_todo(silent=False) # Llama a la lógica de manager que solo carga lo visible

        # 2. Renderizado Condicional
        df_show = st.session_state.oportunidades[st.session_state.oportunidades.index.isin(tickers)]

        if df_show.empty:
            st.caption("Esperando datos...")
        else:
            st.dataframe(get_styled_screener(df_show), use_container_width=True)

        # 3. Lógica para manejar la apertura (CRÍTICO)
        # Si el expander se abre, lo agregamos a la lista para el próximo refresh
        if not is_expanded and st.session_state.paneles_expandidos.count(panel_name) > 0:
            # Esto es un hack. El estado del expander se actualiza en el próximo ciclo
            pass
        elif is_expanded and st.session_state.paneles_expandidos.count(panel_name) == 0:
            # Si estaba cerrado y en el próximo ciclo estaba abierto
            pass
        
        # Una solución limpia implicaría el uso de callbacks on_change
        # Pero nos enfocaremos en que la carga forzada haga el trabajo.

# --- Lógica de Estilo (Copiada para evitar dependencia) ---
def get_styled_screener(df):
    if df.empty: return df
    def highlight_buy(row):
        return ['background-color: rgba(33, 195, 84, 0.2)'] * len(row) if row.get('Senal') == 'COMPRAR' else [''] * len(row)
    return df.style.apply(highlight_buy, axis=1).format({'Precio': '{:,.2f}', 'RSI': '{:.2f}', 'Caida_30d': '{:.2%}', 'Caida_5d': '{:.2%}', 'Suma_Caidas': '{:.2%}'})

# --- PANELES ---

# A. PANEL CARTERA (Siempre visible, siempre se cargan sus precios)
mis_tickers = database.get_tickers_en_cartera()
with st.expander("📂 Transacciones Recientes / En Cartera", expanded=True):
    # La lógica de cargar tickers en cartera ya está en actualizar_todo()
    if st.button("Refrescar Cartera"):
        manager.actualizar_todo(silent=False)

    df_cartera = st.session_state.oportunidades[st.session_state.oportunidades.index.isin(mis_tickers)]
    if not df_cartera.empty:
        st.dataframe(get_styled_screener(df_cartera), use_container_width=True)
    elif len(mis_tickers) > 0: st.info("Cargando precios...")
    else: st.caption("Esperando datos...")


# B. FAVORITOS
favs = database.get_favoritos()
is_fav_expanded = 'Favoritos' in st.session_state.paneles_expandidos
# Guardar estado del expander
with st.expander("⭐ Favoritos", expanded=is_fav_expanded):
    # ... Lógica de gestionar lista (se mantiene igual) ...
    c_btn, c_gest = st.columns([1, 4])
    if c_btn.button("Cargar Favoritos"):
         if 'Favoritos' not in st.session_state.paneles_expandidos: st.session_state.paneles_expandidos.append('Favoritos')
         manager.actualizar_todo(silent=False)
        
    with c_gest.popover("Gestionar Lista"):
        # Lógica de gestión de Favoritos (queda como estaba)
        new = st.text_input("Ticker").upper()
        c_add, c_del = st.columns(2)
        if c_add.button("Agregar"): 
            if new: database.add_favorito(new); st.rerun()
        if favs:
            del_fav = st.selectbox("Eliminar", favs)
            if c_del.button("Eliminar"):
                database.remove_favorito(del_fav); st.rerun()

    # Renderizado Condicional
    df_favs = st.session_state.oportunidades[st.session_state.oportunidades.index.isin(favs)]
    if not df_favs.empty:
         st.dataframe(get_styled_screener(df_favs), use_container_width=True)
    # CRÍTICO: Al renderizar, registramos en el estado si está abierto/cerrado
    if st.session_state._panel_fav_expanded != is_fav_expanded:
        st.session_state._panel_fav_expanded = is_fav_expanded
        if is_fav_expanded: st.session_state.paneles_expandidos.append('Favoritos')
        else: st.session_state.paneles_expandidos.remove('Favoritos')
        st.rerun()


# C. RESTO PANELES
paneles = ['Lider', 'Cedears', 'General', 'Bonos']
iconos = {'Lider': '🏆', 'Cedears': '🌎', 'General': '📊', 'Bonos': 'b'}

for p in paneles:
    if p in config.TICKERS_CONFIG:
        is_expanded = p in st.session_state.paneles_expandidos
        with st.expander(f"{iconos.get(p, '')} {p}", expanded=is_expanded, key=f"exp_{p}"):
            
            if st.button(f"Cargar {p}", key=f"btn_{p}"):
                if p not in st.session_state.paneles_expandidos: st.session_state.paneles_expandidos.append(p)
                manager.actualizar_todo(silent=False)
            
            # Renderizado Condicional
            df_show = st.session_state.oportunidades[st.session_state.oportunidades.index.isin(config.TICKERS_CONFIG[p])]
            if not df_show.empty:
                st.dataframe(get_styled_screener(df_show), use_container_width=True)
            else:
                 if is_expanded: st.caption("Pulse Cargar para obtener datos.")

            # CRÍTICO: Lógica de actualización de estado
            if st.session_state[f"exp_{p}"] != is_expanded:
                 if st.session_state[f"exp_{p}"]: # Se acaba de abrir
                     if p not in st.session_state.paneles_expandidos: st.session_state.paneles_expandidos.append(p)
                 else: # Se acaba de cerrar
                     if p in st.session_state.paneles_expandidos: st.session_state.paneles_expandidos.remove(p)
                 st.rerun()