import streamlit as st
import config
import database
import manager 
from datetime import datetime
from streamlit_autorefresh import st_autorefresh
import numpy as np 
import pandas as pd
# import data_client (Ya no es necesario)

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

# A. PANEL CARTERA (Funciones de Soporte)
df_port_raw = database.get_portafolio_df()
mis_tickers = df_port_raw['Ticker'].unique().tolist() if not df_port_raw.empty else []


# --- Lógica de Estilo (APLICACIÓN DE FORMATO FINAL Y CORRECTO) ---
def get_styled_screener(df, is_cartera_panel=False):
    if df.empty: return df
    
    df_temp = df.copy() 
    
    def highlight_buy(row):
        senal = row.get('Senal')
        ticker = row.name
        
        if senal == 'COMPRAR' and not is_cartera_panel and ticker not in mis_tickers: 
            return ['background-color: rgba(33, 195, 84, 0.2)'] * len(row)
        elif is_cartera_panel and (senal == 'STOP LOSS' or senal == 'TAKE PROFIT'):
             return ['background-color: rgba(255, 75, 75, 0.25)'] * len(row)
             
        return [''] * len(row)

    # 1. Formato para las columnas porcentuales/decimales (RSI, Caídas)
    format_dict = {
        'RSI': '{:.2f}', 
        'Caida_30d': '{:.2%}', 
        'Caida_5d': '{:.2%}', 
        'Suma_Caidas': '{:.2%}',
        'Var_Ayer': '{:.2%}'
    }

    # Aplicar el estilo de color
    df_styled = df_temp.style.apply(highlight_buy, axis=1)
    
    # Aplicar el formato numérico
    df_styled = df_styled.format(format_dict, na_rep="--")
    
    # 2. Conversión a string para Precio y Cantidad (Esto debe ir después)
    for col in ['Precio', 'Cantidad_Total']:
        if col in df_temp.columns:
            df_temp[col] = df_temp[col].fillna(0.0)
            df_temp[col] = df_temp[col].apply(lambda x: f"{x:,.2f}" if x != 0 else '--')
            df_styled.data[col] = df_temp[col]
            
    return df_styled

# --- PANELES ---

# DEFINICIÓN ÚNICA DE COLUMNAS DE SCREENER
COLS_SCREENER_FULL = ['Precio', 'RSI', 'Caida_30d', 'Caida_5d', 'Var_Ayer', 'Suma_Caidas', 'Senal']

# A. PANEL CARTERA (AGRUPACIÓN POR TICKER)
with st.expander("📂 Transacciones Recientes / En Cartera", expanded=True):
    if st.button("Refrescar Cartera"):
        manager.actualizar_todo(silent=False)
        st.rerun()
    
    if df_port_raw.empty:
         st.caption("Tu portafolio está vacío.")
    else:
        # 1. Agrupamos Lotes por Ticker
        df_agrupado = df_port_raw.groupby('Ticker').agg(
            Cantidad_Total=('Cantidad', 'sum'),
            Broker_Principal=('Broker', lambda x: x.iloc[0]),
        ).reset_index().set_index('Ticker')

        # 2. Filtramos y unimos el Portafolio Agrupado con las métricas de Screener
        df_screener = st.session_state.oportunidades.loc[st.session_state.oportunidades.index.isin(mis_tickers)]
        
        if df_screener.empty:
            st.caption("Esperando datos de mercado...")
        else:
            df_merged = df_agrupado.merge(
                df_screener,
                left_index=True, right_index=True, how='left'
            )
            
            # 3. Ordenamiento
            df_merged['Precio'] = pd.to_numeric(df_merged['Precio'], errors='coerce').fillna(0.0) 
            df_merged['Sort_Key'] = df_merged['Precio'].apply(lambda x: 1 if np.isnan(x) or x == 0 else 0)
            df_merged.sort_values(by=['Sort_Key', 'Senal', 'RSI'], ascending=[True, True, False], na_position='last', inplace=True)
            df_merged.drop(columns=['Sort_Key'], inplace=True)
            
            # 4. Columna de Precio Faltante
            df_merged.loc[df_merged['Precio'].isna() | (df_merged['Precio'] == 0), 'Senal'] = 'PRECIO FALTANTE'

            # 5. Columnas a mostrar
            cols_to_show = ['Precio', 'Cantidad_Total'] + COLS_SCREENER_FULL[1:] + ['Broker_Principal']
            if 'Var_Ayer' in cols_to_show: cols_to_show.remove('Var_Ayer') 

            st.dataframe(get_styled_screener(df_merged[cols_to_show], is_cartera_panel=True), use_container_width=True)


# C. RESTO PANELES
paneles = ['Lider', 'Cedears', 'General', 'Bonos']
iconos = {'Lider': '🏆', 'Cedears': '🌎', 'General': '📊', 'Bonos': 'b'}

for p in paneles:
    if p in config.TICKERS_CONFIG:
        all_tickers_in_panel = config.TICKERS_CONFIG[p]
        
        with st.expander(f"{iconos.get(p, '')} {p}", expanded=False):
            
            if st.button(f"Cargar {p}", key=f"btn_{p}"):
                manager.actualizar_panel_individual(p, all_tickers_in_panel)
                st.rerun()
            
            # Renderizado Condicional: Muestra TODOS los que tienen Precio
            df_show = st.session_state.oportunidades.loc[st.session_state.oportunidades.index.isin(all_tickers_in_panel)]
            
            if not df_show.empty:
                df_show.sort_values(by=['Senal', 'Suma_Caidas'], ascending=[True, False], na_position='last', inplace=True)
                
                COLS_SCREENER_FINAL = [c for c in COLS_SCREENER_FULL if c in df_show.columns]
                st.dataframe(get_styled_screener(df_show[COLS_SCREENER_FINAL], is_cartera_panel=False), use_container_width=True) 
            else:
                 st.caption("Pulse Cargar para obtener datos.")
