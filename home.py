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
    # Solo Portafolio y MEP se cargan en la inicialización
    manager.actualizar_solo_cartera(silent=True) 
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

# --- Lógica de Estilo (Añadimos formato al Ticker) ---
def get_styled_screener(df):
    if df.empty: return df
    def highlight_buy(row):
        return ['background-color: rgba(33, 195, 84, 0.2)'] * len(row) if row.get('Senal') == 'COMPRAR' else [''] * len(row)
    
    # Formato para las columnas que suelen ser numéricas
    format_dict = {
        'Precio': '{:,.2f}', 'RSI': '{:.2f}', 'Caida_30d': '{:.2%}', 'Caida_5d': '{:.2%}', 'Suma_Caidas': '{:.2%}',
        'Cantidad_Total': '{:,.2f}' # Nuevo campo total
    }

    # Aplicar el estilo
    df_styled = df.style.apply(highlight_buy, axis=1)
    
    # Aplicar el formato solo a las columnas existentes
    for col, fmt in format_dict.items():
        if col in df_styled.columns:
            df_styled = df_styled.format({col: fmt}, na_rep="--")
            
    return df_styled

# --- PANELES ---

# A. PANEL CARTERA (AGRUPACIÓN POR TICKER)
df_port_raw = database.get_portafolio_df()
mis_tickers = df_port_raw['Ticker'].unique().tolist() if not df_port_raw.empty else []

with st.expander("📂 Transacciones Recientes / En Cartera", expanded=True):
    if st.button("Refrescar Cartera"):
        manager.actualizar_todo(silent=False) # Llama a la carga global para el Home
        st.rerun()
    
    if df_port_raw.empty:
         st.caption("Tu portafolio está vacío.")
    else:
        # 1. Agrupamos Lotes por Ticker y sumamos Cantidad
        df_agrupado = df_port_raw.groupby('Ticker').agg(
            Cantidad_Total=('Cantidad', 'sum'),
            Broker_Principal=('Broker', lambda x: x.iloc[0]), # Mantenemos el broker del primer lote
        ).reset_index()

        # 2. Filtramos el DataFrame de Oportunidades (Screener)
        df_screener = st.session_state.oportunidades.loc[st.session_state.oportunidades.index.isin(mis_tickers)]
        df_screener = df_screener[df_screener['Precio'] > 0]
        
        if df_screener.empty:
            st.caption("Esperando datos de mercado...")
        else:
            # 3. Unimos Agrupación con las métricas de Screener (RSI, Señal)
            df_merged = df_agrupado.merge(
                df_screener.drop(columns=['Precio'], errors='ignore'), # Precio se vuelve a traer
                left_on='Ticker', right_index=True, how='left'
            )
            
            # 4. Unimos el precio actual
            df_merged = df_merged.merge(
                st.session_state.precios_actuales.to_frame('Precio'),
                left_on='Ticker', right_index=True, how='left'
            )
            
            # 5. Columnas a mostrar
            cols_to_show = ['Ticker', 'Precio', 'Cantidad_Total', 'RSI', 'Suma_Caidas', 'Senal', 'Broker_Principal']
            
            # Reemplazar NaN en Screener con Neutro/--
            df_merged['Senal'] = df_merged['Senal'].fillna('PENDIENTE')

            st.dataframe(get_styled_screener(df_merged[cols_to_show]), use_container_width=True)


# B. RESTO PANELES
paneles = ['Lider', 'Cedears', 'General', 'Bonos']
iconos = {'Lider': '🏆', 'Cedears': '🌎', 'General': '📊', 'Bonos': 'b'}

for p in paneles:
    if p in config.TICKERS_CONFIG:
        # Aquí no queremos el filtro de la cartera!
        with st.expander(f"{iconos.get(p, '')} {p}", expanded=False):
            
            if st.button(f"Cargar {p}", key=f"btn_{p}"):
                # Llama a la función que descarga ese panel y vuelve
                manager.actualizar_panel_individual(p, config.TICKERS_CONFIG[p])
                st.rerun()
            
            # Renderizado Condicional: Aquí SÍ mostramos el screener puro (TODOS)
            df_show = st.session_state.oportunidades.loc[st.session_state.oportunidades.index.isin(config.TICKERS_CONFIG[p])]
            df_show = df_show[df_show['Precio'] > 0]
            
            if not df_show.empty:
                # Usamos el estilo original de screener para estos paneles
                st.dataframe(get_styled_screener(df_show), use_container_width=True) 
            else:
                 st.caption("Pulse Cargar para obtener datos.")