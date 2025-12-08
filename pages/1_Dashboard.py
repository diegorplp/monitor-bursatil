import streamlit as st
import pandas as pd
import altair as alt
import database
import market_logic
import manager

st.set_page_config(page_title="Dashboard", page_icon="📊", layout="wide")

st.title("📊 Rendimiento del Portafolio")

# --- BOTÓN SIDEBAR ---
manager.mostrar_boton_actualizar()

# --- VERIFICACIÓN DE DATOS ---
if 'precios_actuales' not in st.session_state or st.session_state.precios_actuales.empty:
    st.warning("⚠️ No hay precios cargados. Presiona 'Actualizar Todo' en la barra lateral.")
    st.stop()

# --- CARGA DE DATOS ---
try:
    df_port = database.get_portafolio_df()
    df_hist = database.get_historial_df()
except Exception as e:
    st.error(f"Error crítico leyendo base de datos: {e}")
    st.stop()

# --- CÁLCULOS: PORTAFOLIO (LATENTE) ---
ganancia_latente = 0.0
valor_total_cartera = 0.0
inversion_total_activa = 0.0
df_validos = pd.DataFrame()

if not df_port.empty:
    df_analizado = market_logic.analizar_portafolio(df_port, st.session_state.precios_actuales)
    
    # Filtrar válidos para métricas
    df_validos = df_analizado.dropna(subset=['Valor_Actual'])
    df_validos = df_validos[df_validos['Valor_Actual'] > 0]

    if 'Ganancia_Neta_Monto' in df_validos.columns:
        ganancia_latente = df_validos['Ganancia_Neta_Monto'].sum()
    
    if 'Valor_Salida_Neto' in df_validos.columns:
        valor_total_cartera = df_validos['Valor_Salida_Neto'].sum()
    
    if 'Inversion_Total' in df_validos.columns:
        inversion_total_activa = df_validos['Inversion_Total'].sum()

# --- CÁLCULOS: HISTORIAL (REALIZADO) ---
ganancia_realizada = 0.0
if not df_hist.empty and 'Resultado_Neto' in df_hist.columns:
    # Como database.py ya limpió y normalizó, confiamos en la columna 'Resultado_Neto'.
    # Nos aseguramos de que sea float por si acaso, llenando NaNs con 0.
    ganancia_realizada = pd.to_numeric(df_hist['Resultado_Neto'], errors='coerce').fillna(0.0).sum()

# --- RESULTADO TOTAL ---
resultado_global = ganancia_latente + ganancia_realizada
roi_global = 0.0
if inversion_total_activa > 0:
    roi_global = (resultado_global / inversion_total_activa)

# --- UI: MÉTRICAS ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Valor de Cartera", f"$ {valor_total_cartera:,.0f}")
col2.metric("Ganancia Latente", f"$ {ganancia_latente:,.0f}")
col3.metric("Ganancia Realizada", f"$ {ganancia_realizada:,.0f}")
col4.metric("Resultado Global", f"$ {resultado_global:,.0f}", f"{roi_global:.2%}")

st.divider()

# --- GRÁFICOS ---
if not df_validos.empty:
    g1, g2 = st.columns(2)
    with g1:
        st.subheader("Composición")
        df_pie = df_validos.groupby('Ticker')['Valor_Actual'].sum().reset_index()
        base = alt.Chart(df_pie).encode(
            theta=alt.Theta("Valor_Actual", stack=True), 
            color=alt.Color("Ticker"), 
            tooltip=["Ticker", alt.Tooltip("Valor_Actual", format="$,.0f")]
        )
        pie = base.mark_arc(outerRadius=120)
        st.altair_chart(pie, use_container_width=True)

    with g2:
        st.subheader("Rendimiento ($)")
        df_bar = df_validos.groupby('Ticker')['Ganancia_Neta_Monto'].sum().reset_index()
        chart = alt.Chart(df_bar).mark_bar().encode(
            x=alt.X('Ticker', sort='-y'), 
            y='Ganancia_Neta_Monto', 
            color=alt.condition(
                alt.datum.Ganancia_Neta_Monto > 0, 
                alt.value("#21c354"), 
                alt.value("#ff4b4b")
            ),
            tooltip=["Ticker", alt.Tooltip("Ganancia_Neta_Monto", format="$,.0f")]
        )
        st.altair_chart(chart, use_container_width=True)

# --- DIAGNÓSTICO (DEBUGGER) ---
with st.expander("🕵️ Diagnóstico de Historial", expanded=False):
    if df_hist.empty:
        st.info("Historial vacío o no se pudo leer.")
    else:
        st.write(f"Filas leídas: {len(df_hist)}")
        if 'Resultado_Neto' in df_hist.columns:
            st.write(f"Suma calculada: {ganancia_realizada:,.2f}")
            # Muestra una muestra de datos crudos para ver si hay errores de parseo
            st.dataframe(df_hist[['Ticker', 'Resultado_Neto']].head(), use_container_width=True)
        else:
            st.error("Columna 'Resultado_Neto' no encontrada tras normalización.")
            st.write("Columnas disponibles:", df_hist.columns.tolist())

# Tabla final
if not df_hist.empty:
    st.subheader("📜 Últimas Ventas")
    cols_ver = [c for c in ['Ticker', 'Fecha_Venta', 'Precio_Venta', 'Resultado_Neto', 'Broker'] if c in df_hist.columns]
    st.dataframe(df_hist[cols_ver].tail(5), use_container_width=True, hide_index=True)