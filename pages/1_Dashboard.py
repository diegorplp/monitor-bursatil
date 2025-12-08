import streamlit as st
import pandas as pd
import altair as alt
import database
import market_logic

st.set_page_config(page_title="Dashboard", page_icon="📊", layout="wide")

st.title("📊 Rendimiento del Portafolio")

# --- VERIFICACIÓN DE DATOS ---
if 'precios_actuales' not in st.session_state or st.session_state.precios_actuales.empty:
    st.warning("⚠️ No hay precios cargados en memoria. Ve al Inicio y presiona 'Actualizar Recientes'.")
    # Mostramos qué hay en memoria para debug
    st.write(f"Contenido de memoria: {st.session_state.get('precios_actuales', 'Vacío')}")
    st.stop()

# --- CARGA DE DATOS ---
try:
    df_port = database.get_portafolio_df()
    df_hist = database.get_historial_df()
except Exception as e:
    st.error(f"Error leyendo base de datos: {e}")
    st.stop()

if df_port.empty:
    st.info("Tu portafolio está vacío.")
    st.stop()

# --- CÁLCULOS ---
df_analizado = market_logic.analizar_portafolio(df_port, st.session_state.precios_actuales)

# FILTRO DE ERRORES VISUAL
activos_sin_precio = df_analizado[ (df_analizado['Precio_Actual'].isna()) | (df_analizado['Precio_Actual'] == 0) ]

if not activos_sin_precio.empty:
    st.error(f"⚠️ Atención: Hay {len(activos_sin_precio)} lotes sin precio actualizado.")
    
    # --- HERRAMIENTA DE DIAGNÓSTICO (RAYOS X) ---
    with st.expander("🕵️ DIAGNÓSTICO TÉCNICO (Ábreme para ver el error)", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            st.warning("Lo que tienes en el EXCEL:")
            lista_excel = df_port['Ticker'].unique().tolist()
            st.write(lista_excel)
        
        with c2:
            st.success("Lo que tienes en MEMORIA (Descargado):")
            lista_memoria = st.session_state.precios_actuales.index.tolist()
            st.write(lista_memoria)
            
        st.markdown("---")
        st.info("💡 **Pista:** Busca diferencias sutiles. ¿Unos tienen `.BA` y los otros no? ¿Hay espacios en blanco?")

# Limpiamos para gráficos
df_validos = df_analizado.dropna(subset=['Valor_Actual'])
df_validos = df_validos[df_validos['Valor_Actual'] > 0]

ganancia_latente = df_validos['Ganancia_Neta_Monto'].sum()
valor_total_cartera = df_validos['Valor_Salida_Neto'].sum()
inversion_total_activa = df_validos['Inversion_Total'].sum()
ganancia_realizada = df_hist['Resultado_Neto'].sum() if not df_hist.empty and 'Resultado_Neto' in df_hist.columns else 0.0

resultado_global = ganancia_latente + ganancia_realizada
roi_global = (resultado_global / inversion_total_activa) if inversion_total_activa > 0 else 0.0

# --- UI: MÉTRICAS ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Valor de Cartera", f"$ {valor_total_cartera:,.0f}")
col2.metric("Ganancia Latente", f"$ {ganancia_latente:,.0f}")
col3.metric("Ganancia Realizada", f"$ {ganancia_realizada:,.0f}")
col4.metric("Resultado Global", f"$ {resultado_global:,.0f}", f"{roi_global:.2%}")

st.divider()

# --- GRÁFICOS ---
if not df_validos.empty:
    c_chart1, c_chart2 = st.columns(2)
    with c_chart1:
        st.subheader("Composición")
        df_pie = df_validos.groupby('Ticker')['Valor_Actual'].sum().reset_index()
        base = alt.Chart(df_pie).encode(theta=alt.Theta("Valor_Actual", stack=True), color=alt.Color("Ticker"), tooltip=["Ticker", "Valor_Actual"])
        pie = base.mark_arc(outerRadius=120)
        st.altair_chart(pie, use_container_width=True)

    with c_chart2:
        st.subheader("Rendimiento ($)")
        df_bar = df_validos.groupby('Ticker')['Ganancia_Neta_Monto'].sum().reset_index()
        chart = alt.Chart(df_bar).mark_bar().encode(
            x=alt.X('Ticker', sort='-y'), 
            y='Ganancia_Neta_Monto', 
            color=alt.condition(alt.datum.Ganancia_Neta_Monto > 0, alt.value("#21c354"), alt.value("#ff4b4b"))
        )
        st.altair_chart(chart, use_container_width=True)
