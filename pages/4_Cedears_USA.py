import streamlit as st
import database
import market_logic
import pandas as pd
import numpy as np

st.set_page_config(page_title="Cedears USA (RSI Multi)", layout="wide")

st.title("🌎 Monitor CEDEARs (Estrategia Multi-RSI)")
st.caption("Consenso de Sobreventa: Porcentaje de indicadores RSI (1 a 8 periodos) que están por debajo de 30.")

# 1. Cargar Datos
with st.spinner("Cargando historial y calculando matrices..."):
    df_history = database.get_historical_prices_df(nombre_hoja="Historial_Cedears_Ext")

if df_history.empty:
    st.error("No se pudieron cargar los datos de 'Historial_Cedears_Ext'.")
else:
    # 2. Calcular usando la NUEVA función Multi-length
    df_screen = market_logic.calcular_screen_cedears(df_history)
    
    if df_screen.empty:
        st.warning("Datos insuficientes.")
    else:
        # 3. Estilos de la Tabla
        # Resaltamos RSI 14 estándar como referencia
        def style_rsi_std(val):
            if val < 30: return 'color: red; font-weight: bold;'
            return ''

        # Ordenar: Primero los que tengan MAYOR CONSENSO de sobreventa
        df_screen.sort_values(by=['Consenso_RSI', 'RSI_14'], ascending=[False, True], inplace=True)
        
        # Formato columnas
        column_config = {
            "Precio": st.column_config.NumberColumn(format="$%.2f"),
            "RSI_14": st.column_config.NumberColumn(format="%.1f", label="RSI (14)"),
            
            # NUEVA COLUMNA VISUAL
            "Consenso_RSI": st.column_config.ProgressColumn(
                label="Consenso RSI < 30 (1-8d)",
                help="Muestra qué porcentaje de los RSI de corto plazo (1 a 8 días) están en zona de compra.",
                format="%.0f%%",
                min_value=0,
                max_value=1,
            ),
            
            "Caida_30d": st.column_config.NumberColumn(format="%.2%", label="Caída 30d"),
        }
        
        cols_show = ['Precio', 'Consenso_RSI', 'RSI_14', 'Caida_30d', 'Caida_5d']

        # Mostrar Tabla
        st.dataframe(
            df_screen[cols_show].style.map(style_rsi_std, subset=['RSI_14']),
            use_container_width=True,
            column_config=column_config,
            height=700
        )

        # --- SIMULADOR SIMPLE (Adaptado) ---
        st.sidebar.header("🧪 Simulador")
        lista_tickers = sorted(df_history.columns.tolist())
        ticker_sim = st.sidebar.selectbox("Simular Activo", lista_tickers)
        precio_ref = df_history[ticker_sim].iloc[-1]
        
        precio_input = st.sidebar.number_input("Precio Hipotético", value=float(precio_ref), format="%.2f")
        
        if st.sidebar.button("Calcular Impacto"):
            # Usamos la función simple para RSI 14 solo como referencia rápida
            rsi_sim = market_logic.calcular_rsi_simulado(df_history, ticker_sim, precio_input)
            st.sidebar.metric("RSI (14) Simulado", f"{rsi_sim:.2f}" if rsi_sim else "--")
            
            diff = (precio_input / precio_ref) - 1
            st.sidebar.caption(f"Variación: {diff:+.2%}")