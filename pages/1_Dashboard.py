import streamlit as st
import pandas as pd
import altair as alt
import database
import market_logic
import manager

st.set_page_config(page_title="Dashboard", page_icon="📊", layout="wide")
st.title("📊 Rendimiento del Portafolio")

# --- CRÍTICO: BOTÓN DE ACTUALIZACIÓN LOCAL ---
if st.button("🔄 Actualizar Datos de Mercado"):
    manager.actualizar_todo(silent=False) 
    st.rerun()

if 'precios_actuales' not in st.session_state or st.session_state.precios_actuales.empty:
    st.warning("⚠️ Sin precios. Actualiza.")
    st.stop()

# --- CARGA DATOS ---
try:
    df_port = database.get_portafolio_df()
    df_hist = database.get_historial_df()
except Exception as e:
    st.error(f"Error BD: {e}")
    st.stop()

# --- CÁLCULOS ---
ganancia_latente = 0.0
valor_cartera = 0.0
ganancia_realizada = 0.0

# 1. Tenencia
df_validos = pd.DataFrame()
if not df_port.empty:
    df_analizado = market_logic.analizar_portafolio(df_port, st.session_state.precios_actuales)
    if 'Valor_Actual' in df_analizado.columns:
        df_validos = df_analizado[df_analizado['Valor_Actual'] > 0].copy()
        ganancia_latente = df_validos['Ganancia_Neta_Monto'].sum()
        valor_cartera = df_validos['Valor_Salida_Neto'].sum()

# 2. Historial
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

# --- DIAGNÓSTICO RÁPIDO (Opcional, útil para forzar recargas) ---
with st.expander("⚙️ Opciones de Datos", expanded=False):
    c_op1, c_op2 = st.columns([1, 5])
    
    with c_op1:
        if st.button("🔄 Recargar DB"):
            st.cache_data.clear()
            st.rerun()
            
    with c_op2:
        if df_hist.empty:
            st.warning("El historial parece vacío.")
        else:
            st.caption(f"Historial cargado: {len(df_hist)} operaciones procesadas.")
            st.caption("Usa 'Recargar DB' si editaste Google Sheet manualmente.")

# --- GRÁFICOS ---
if not df_validos.empty:
    g1, g2 = st.columns(2)
    with g1:
        base = alt.Chart(df_validos).encode(theta=alt.Theta("Valor_Actual", stack=True), color="Ticker", tooltip=["Ticker", "Valor_Actual"])
        st.altair_chart(base.mark_arc(outerRadius=120), use_container_width=True) # Mantenido: Los gráficos de Altair a veces usan esto
    with g2:
        chart = alt.Chart(df_validos).mark_bar().encode(
            x=alt.X('Ticker', sort='-y'), 
            y='Ganancia_Neta_Monto',
            color=alt.condition(alt.datum.Ganancia_Neta_Monto > 0, alt.value("green"), alt.value("red")),
            tooltip=["Ticker", "Ganancia_Neta_Monto"]
        )
        st.altair_chart(chart, use_container_width=True) # Mantenido: Los gráficos de Altair a veces usan esto