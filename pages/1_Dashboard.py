import streamlit as st
import pandas as pd
import altair as alt
import database
import market_logic
import manager

st.set_page_config(page_title="Dashboard", page_icon="📊", layout="wide")
st.title("📊 Rendimiento del Portafolio")

manager.mostrar_boton_actualizar()

# --- CARGA DATOS ---
if 'precios_actuales' not in st.session_state or st.session_state.precios_actuales.empty:
    st.warning("⚠️ Sin precios. Actualiza.")
    st.stop()

try:
    df_port = database.get_portafolio_df()
    df_hist = database.get_historial_df()
except Exception as e:
    st.error(f"Error conectando a BD: {e}")
    st.stop()

# --- CÁLCULOS ---
ganancia_latente = 0.0
valor_cartera = 0.0
ganancia_realizada = 0.0

# 1. Tenencia (Portafolio)
df_validos = pd.DataFrame()
if not df_port.empty:
    df_analizado = market_logic.analizar_portafolio(df_port, st.session_state.precios_actuales)
    # Filtro básico para evitar errores
    if 'Valor_Actual' in df_analizado.columns:
        df_validos = df_analizado[df_analizado['Valor_Actual'] > 0].copy()
        ganancia_latente = df_validos['Ganancia_Neta_Monto'].sum()
        valor_cartera = df_validos['Valor_Salida_Neto'].sum()

# 2. Historial (Ventas Cerradas)
if not df_hist.empty and 'Resultado_Neto' in df_hist.columns:
    ganancia_realizada = df_hist['Resultado_Neto'].sum()

resultado_global = ganancia_latente + ganancia_realizada

# --- UI MÉTRICAS ---
c1, c2, c3, c4 = st.columns(4)
c1.metric("Valor Cartera", f"${valor_cartera:,.0f}")
c2.metric("Ganancia Latente", f"${ganancia_latente:,.0f}")
c3.metric("Ganancia Realizada", f"${ganancia_realizada:,.0f}")
c4.metric("Total", f"${resultado_global:,.0f}")

st.divider()

# --- DIAGNÓSTICO (Simplificado y funcional) ---
with st.expander("🕵️ Diagnóstico de Datos"):
    if st.button("🔄 Borrar Caché y Recargar"):
        st.cache_data.clear()
        st.rerun()

    st.write("### Datos de Historial Detectados:")
    if df_hist.empty:
        st.warning("El historial está vacío o no se encontró la hoja 'Historial'.")
    else:
        st.write(f"Filas: {len(df_hist)} | Columnas: {list(df_hist.columns)}")
        st.dataframe(df_hist.head())
        
        if 'Resultado_Neto' not in df_hist.columns:
            st.error("⚠️ ALERTA: No veo la columna 'Resultado_Neto'. Revisa si el nombre en el Excel es correcto.")

# --- GRÁFICOS ---
if not df_validos.empty:
    g1, g2 = st.columns(2)
    with g1:
        base = alt.Chart(df_validos).encode(theta=alt.Theta("Valor_Actual", stack=True), color="Ticker")
        st.altair_chart(base.mark_arc(outerRadius=120), use_container_width=True)
    with g2:
        chart = alt.Chart(df_validos).mark_bar().encode(
            x=alt.X('Ticker', sort='-y'), 
            y='Ganancia_Neta_Monto',
            color=alt.condition(alt.datum.Ganancia_Neta_Monto > 0, alt.value("green"), alt.value("red"))
        )
        st.altair_chart(chart, use_container_width=True)