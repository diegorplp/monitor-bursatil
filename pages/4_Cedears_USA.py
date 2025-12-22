import streamlit as st
import database
import market_logic
import pandas as pd
import numpy as np

st.set_page_config(page_title="Cedears USA (RSI)", layout="wide")

st.title("🌎 Monitor CEDEARs (Mercado USA)")
st.caption("Análisis técnico puro sobre precio en Dólares (Subyacente). Elimina ruido del CCL.")

# 1. Cargar Datos Históricos de la nueva Hoja
with st.spinner("Cargando historial completo de CEDEARs..."):
    # Llamamos a la hoja específica
    df_history = database.get_historical_prices_df(nombre_hoja="Historial_Cedears_Ext")

if df_history.empty:
    st.error("No se pudieron cargar los datos de 'Historial_Cedears_Ext'. Verifica que la hoja exista en Google Sheets y tenga datos.")
else:
    # 2. Calcular Indicadores (RSI, etc)
    # market_logic.calcular_indicadores funciona agnóstico a si es .BA o USA,
    # siempre que el DF tenga tickers en columnas.
    df_screen = market_logic.calcular_indicadores(df_history)
    
    if df_screen.empty:
        st.warning("No hay suficientes datos históricos para calcular indicadores.")
    else:
        # 3. Estilos de la Tabla (RSI Colores)
        def style_rsi(val):
            if pd.isna(val): return ''
            if val < 30:
                return 'background-color: rgba(255, 0, 0, 0.3); color: white; font-weight: bold;' # Rojo fuerte
            elif 30 <= val <= 35:
                return 'background-color: rgba(255, 165, 0, 0.3); color: white;' # Naranja
            return ''

        # Ordenar por RSI ascendente (Oportunidades primero)
        df_screen.sort_values(by='RSI', ascending=True, inplace=True, na_position='last')
        
        # Formato columnas
        column_config = {
            "Precio": st.column_config.NumberColumn(format="$%.2f"), # Dólares
            "RSI": st.column_config.NumberColumn(format="%.2f"),
            "Caida_30d": st.column_config.NumberColumn(format="%.2%", label="Caída 30d"),
            "Caida_5d": st.column_config.NumberColumn(format="%.2%", label="Caída 5d"),
        }
        
        cols_show = ['Precio', 'RSI', 'Caida_30d', 'Caida_5d']

        # Mostrar Tabla
        st.dataframe(
            df_screen[cols_show].style.map(style_rsi, subset=['RSI']),
            use_container_width=True,
            column_config=column_config,
            height=600
        )

        # --- 4. SIMULADOR EN SIDEBAR ---
        st.sidebar.header("🧪 Simulador de Precio")
        st.sidebar.info("Modifica el precio de un activo para ver cómo cambiaría su RSI instantáneamente.")
        
        # Selector de Ticker (ordenado alfabéticamente para facilitar búsqueda)
        lista_tickers = sorted(df_history.columns.tolist())
        ticker_sim = st.sidebar.selectbox("Seleccionar Activo", lista_tickers)
        
        # Obtener precio actual (último cierre)
        precio_actual_ref = df_history[ticker_sim].iloc[-1]
        
        # Input de Precio Nuevo
        precio_input = st.sidebar.number_input(
            f"Precio Simulado para {ticker_sim}", 
            value=float(precio_actual_ref), 
            format="%.2f"
        )
        
        if st.sidebar.button("Calcular RSI Simulado"):
            # Calcular
            rsi_sim = market_logic.calcular_rsi_simulado(df_history, ticker_sim, precio_input)
            
            # Obtener RSI actual (real)
            rsi_real = df_screen.loc[ticker_sim, 'RSI'] if ticker_sim in df_screen.index else None
            
            st.sidebar.divider()
            
            # Mostrar Comparación
            c1, c2 = st.sidebar.columns(2)
            c1.metric("RSI Actual", f"{rsi_real:.2f}" if rsi_real else "--")
            c2.metric("RSI Simulado", f"{rsi_sim:.2f}" if rsi_sim else "--")
            
            # Interpretación
            if rsi_sim:
                if rsi_sim < 30:
                    st.sidebar.error("⚠️ SOBREVENTA (Oportunidad)")
                elif rsi_sim > 70:
                    st.sidebar.warning("🔥 SOBRECOMPRA (Riesgo)")
                else:
                    st.sidebar.success("✅ Zona Neutra")
            
            # Diferencia porcentual de precio
            diff_precio = (precio_input / precio_actual_ref) - 1
            st.sidebar.caption(f"Cambio de precio simulado: {diff_precio:+.2%}")