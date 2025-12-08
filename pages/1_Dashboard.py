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
col_resultado_usada = "Ninguna"

if not df_hist.empty:
    # Intentamos ubicar la columna correcta
    if 'Resultado_Neto' in df_hist.columns:
        col_resultado_usada = 'Resultado_Neto'
        ganancia_realizada = pd.to_numeric(df_hist['Resultado_Neto'], errors='coerce').fillna(0.0).sum()
    elif 'Resultado Neto' in df_hist.columns:
        col_resultado_usada = 'Resultado Neto'
        ganancia_realizada = pd.to_numeric(df_hist['Resultado Neto'], errors='coerce').fillna(0.0).sum()

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

# --- DIAGNÓSTICO DETALLADO (CRÍTICO) ---
with st.expander("🕵️ Diagnóstico de Historial (Abrir si Ganancia Realizada es 0)", expanded=False):
    st.markdown("#### Estado de Datos")
    if df_hist.empty:
        st.error("❌ El DataFrame de Historial está VACÍO. Revisa que la pestaña 'Historial' exista en Google Sheets.")
    else:
        st.success(f"✅ Se cargaron {len(df_hist)} filas del historial.")
        st.write(f"**Columnas Detectadas:** {list(df_hist.columns)}")
        st.write(f"**Columna usada para suma:** `{col_resultado_usada}`")
        st.write(f"**Valor Sumado:** $ {ganancia_realizada:,.2f}")
        
        st.markdown("#### Muestra de Datos Crudos")
        cols_preview = [c for c in ['Ticker', 'Resultado_Neto', 'Resultado Neto', 'Precio_Venta'] if c in df_hist.columns]
        if cols_preview:
            st.dataframe(df_hist[cols_preview].head(), use_container_width=True)
        else:
            st.warning("No se encuentran columnas de resultado en el Historial cargado. ¿Estás leyendo la hoja correcta?")
            st.dataframe(df_hist.head())

# Tabla final
if not df_hist.empty:
    st.subheader("📜 Últimas Ventas")
    cols_ver = [c for c in ['Ticker', 'Fecha_Venta', 'Precio_Venta', 'Resultado_Neto', 'Broker'] if c in df_hist.columns]
    st.dataframe(df_hist[cols_ver].tail(5), use_container_width=True, hide_index=True)