import streamlit as st
from datetime import datetime
import database
import config

st.set_page_config(page_title="Registrar Compra", page_icon="📝")

st.title("📝 Registrar Nueva Compra")
st.markdown("Ingresa los datos de la operación para sumarla a tu portafolio.")

with st.form("form_compra", clear_on_submit=False):
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        ticker_input = st.text_input("Ticker (Ej: GGAL)", placeholder="GGAL").strip().upper()
        # Visualmente le avisamos al usuario que se normalizará
        if ticker_input and "." not in ticker_input and len(ticker_input) < 10:
            st.caption(f"ℹ️ Se guardará automáticamente como: **{ticker_input}.BA**")

    with col2:
        lista_brokers = list(config.COMISIONES.keys())
        # Selección inteligente de broker default
        idx_def = 0
        if 'IOL' in lista_brokers: idx_def = lista_brokers.index('IOL')
        elif 'BULL' in lista_brokers: idx_def = lista_brokers.index('BULL')
        
        broker_sel = st.selectbox("Broker", lista_brokers, index=idx_def)

    st.markdown("---")

    c1, c2, c3 = st.columns(3)
    
    with c1:
        fecha_compra = st.date_input("Fecha de Compra", datetime.now())
    
    with c2:
        cantidad = st.number_input("Cantidad", min_value=1, step=1, format="%d")
        
    with c3:
        precio = st.number_input("Precio de Compra ($)", min_value=0.0, step=10.0, format="%.2f")

    st.markdown("---")
    st.markdown("##### 🔔 Alertas Iniciales (Opcional)")
    c4, c5 = st.columns(2)
    
    with c4:
        alerta_alta = st.number_input("Take Profit ($)", min_value=0.0, step=10.0, help="Precio objetivo de venta (0 para ignorar)")
    
    with c5:
        alerta_baja = st.number_input("Stop Loss ($)", min_value=0.0, step=10.0, help="Precio límite de pérdida (0 para ignorar)")

    st.markdown("<br>", unsafe_allow_html=True)
    
    submitted = st.form_submit_button("💾 Guardar Transacción", type="primary")

    if submitted:
        if not ticker_input:
            st.error("Por favor ingresa un Ticker.")
        elif cantidad <= 0 or precio <= 0:
            st.error("La cantidad y el precio deben ser mayores a 0.")
        else:
            datos = {
                'Ticker': ticker_input,
                'Fecha_Compra': fecha_compra.strftime('%Y-%m-%d'),
                'Cantidad': int(cantidad),
                'Precio_Compra': float(precio),
                'Broker': broker_sel,
                'Alerta_Alta': float(alerta_alta),
                'Alerta_Baja': float(alerta_baja)
            }
            
            with st.spinner("Guardando en Google Sheets..."):
                exito, msg = database.add_transaction(datos)
            
            if exito:
                st.success(f"✅ {msg}")
                st.info("Ve a la pestaña 'Portafolio' para ver tu nueva posición.")
            else:
                st.error(f"❌ Error: {msg}")