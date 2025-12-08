import streamlit as st
import pandas as pd
import altair as alt
import database
import market_logic
import manager

st.set_page_config(page_title="Dashboard", page_icon="📊", layout="wide")
st.title("📊 Rendimiento del Portafolio")

manager.mostrar_boton_actualizar()

# --- CARGA ---
if 'precios_actuales' not in st.session_state or st.session_state.precios_actuales.empty:
    st.warning("⚠️ Sin precios. Actualiza.")
    st.stop()

# Forzamos recarga cada vez que entramos aquí para debug
# st.cache_data.clear() 

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

if not df_port.empty:
    df_analizado = market_logic.analizar_portafolio(df_port, st.session_state.precios_actuales)
    df_validos = df_analizado[df_analizado['Valor_Actual'] > 0].copy()
    if 'Ganancia_Neta_Monto' in df_validos.columns:
        ganancia_latente = df_validos['Ganancia_Neta_Monto'].sum()
    if 'Valor_Salida_Neto' in df_validos.columns:
        valor_cartera = df_validos['Valor_Salida_Neto'].sum()

# Lógica Historial
col_res = None
if not df_hist.empty:
    if 'Resultado_Neto' in df_hist.columns:
        ganancia_realizada = df_hist['Resultado_Neto'].sum()
        col_res = 'Resultado_Neto'
    else:
        # Intento de suma ciega solo si no hay columnas prohibidas
        if 'CoolDown_Alta' not in df_hist.columns:
             pass 

resultado_global = ganancia_latente + ganancia_realizada

# --- UI ---
c1, c2, c3, c4 = st.columns(4)
c1.metric("Valor Cartera", f"${valor_cartera:,.0f}")
c2.metric("Ganancia Latente", f"${ganancia_latente:,.0f}")
c3.metric("Ganancia Realizada", f"${ganancia_realizada:,.0f}")
c4.metric("Total", f"${resultado_global:,.0f}")

st.divider()

# --- DIAGNÓSTICO (ESTRICTO) ---
with st.expander("🕵️ Diagnóstico de Conexión", expanded=(ganancia_realizada == 0)):
    if st.button("🧹 BORRAR CACHÉ Y RECARGAR AHORA"):
        st.cache_data.clear()
        st.rerun()

    st.write("---")
    st.markdown("### 1. Estado del Historial")
    if df_hist.empty:
        st.error("❌ El DataFrame está VACÍO. El sistema no encontró ninguna hoja que cumpla los criterios (tener 'Resultado' y NO tener 'CoolDown').")
    else:
        st.success(f"✅ Se cargó una hoja con {len(df_hist)} filas.")
        
        # Verificación de ADN
        cols = list(df_hist.columns)
        st.write(f"**Columnas detectadas:** {cols}")
        
        if 'CoolDown_Alta' in cols:
            st.error("🚨 ¡ALERTA CRÍTICA! Se sigue cargando la hoja de Portafolio. Esto no debería pasar con el nuevo código.")
        elif 'Resultado_Neto' in cols:
            st.success("✅ ADN CORRECTO: Se detectó columna 'Resultado_Neto'.")
            st.dataframe(df_hist.head())
        else:
            st.warning("⚠️ Se cargó una hoja limpia pero no se encontró la columna exacta de resultado.")

# --- GRÁFICOS ---
if not df_port.empty and not df_validos.empty:
    g1, g2 = st.columns(2)
    with g1:
        base = alt.Chart(df_validos).encode(theta=alt.Theta("Valor_Actual", stack=True), color="Ticker")
        st.altair_chart(base.mark_arc(outerRadius=120), use_container_width=True)
    with g2:
        chart = alt.Chart(df_validos).mark_bar().encode(x=alt.X('Ticker', sort='-y'), y='Ganancia_Neta_Monto', color=alt.value("green"))
        st.altair_chart(chart, use_container_width=True)