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
    # AÑADIMOS EL FORMATO CORRECTO PARA LA TABLA DE CARTERA
    format_dict = {
        'Precio_Compra': '{:,.2f}', 'Precio_Actual': '{:,.2f}', 'Cantidad': '{:,.2f}',
        'RSI': '{:.2f}', 'Caida_30d': '{:.2%}', 'Caida_5d': '{:.2%}', 'Suma_Caidas': '{:.2%}'
    }
    return df.style.apply(highlight_buy, axis=1).format(format_dict, na_rep="--")

# --- PANELES ---

# A. PANEL CARTERA (RESTAURACIÓN COMPLETA)
mis_tickers = database.get_tickers_en_cartera()
# 1. Cargamos el DataFrame de tenencia cruda
df_port_raw = database.get_portafolio_df()

with st.expander("📂 Transacciones Recientes / En Cartera", expanded=True):
    if st.button("Refrescar Cartera"):
        manager.actualizar_todo(silent=False)
        st.rerun()
    
    if df_port_raw.empty:
         st.caption("Tu portafolio está vacío.")
    else:
        # 2. Filtramos el DataFrame de Oportunidades (Screener)
        df_screener = st.session_state.oportunidades.loc[st.session_state.oportunidades.index.isin(mis_tickers)]
        df_screener = df_screener[df_screener['Precio'] > 0]
        
        if df_screener.empty:
            st.caption("Esperando datos de mercado...")
        else:
            # 3. Unimos el Portafolio CRUDO con las métricas de Screener (RSI, Señal)
            df_merged = df_port_raw.merge(
                df_screener[['RSI', 'Caida_30d', 'Caida_5d', 'Suma_Caidas', 'Senal']],
                left_on='Ticker', right_index=True, how='left'
            )
            
            # 4. Unimos el precio actual de la sesión (solo para ver la tenencia)
            df_merged = df_merged.merge(
                st.session_state.precios_actuales.to_frame('Precio_Actual'),
                left_on='Ticker', right_index=True, how='left'
            )
            
            # Renombrar Columnas (Asumiendo que quieres el orden Ticker, Precio_Actual, RSI, Senal...)
            df_merged = df_merged.rename(columns={'Precio_Actual': 'Precio'})
            
            # Columnas a mostrar (Restauradas a tu orden original de tenencia)
            cols_to_show = ['Ticker', 'Precio', 'RSI', 'Caida_30d', 'Caida_5d', 'Suma_Caidas', 'Senal', 
                            'Cantidad', 'Precio_Compra', 'Broker']
            
            cols_valid = [c for c in cols_to_show if c in df_merged.columns]

            st.dataframe(get_styled_screener(df_merged[cols_valid]), use_container_width=True)


# C. RESTO PANELES
paneles = ['Lider', 'Cedears', 'General', 'Bonos']
iconos = {'Lider': '🏆', 'Cedears': '🌎', 'General': '📊', 'Bonos': 'b'}

for p in paneles:
    if p in config.TICKERS_CONFIG:
        with st.expander(f"{iconos.get(p, '')} {p}", expanded=False):
            
            if st.button(f"Cargar {p}", key=f"btn_{p}"):
                manager.actualizar_panel_individual(p, config.TICKERS_CONFIG[p])
                st.rerun()
            
            # Renderizado Condicional: Aquí SÍ mostramos el screener puro
            df_show = st.session_state.oportunidades.loc[st.session_state.oportunidades.index.isin(config.TICKERS_CONFIG[p])]
            df_show = df_show[df_show['Precio'] > 0]
            
            if not df_show.empty:
                # Usamos el estilo original de screener para estos paneles
                st.dataframe(get_styled_screener(df_show), use_container_width=True) 
            else:
                 st.caption("Pulse Cargar para obtener datos.")