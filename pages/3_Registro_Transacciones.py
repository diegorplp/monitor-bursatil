import streamlit as st
from datetime import datetime
import database
import config

# CORRECCIÓN AQUÍ: page_icon
st.set_page_config(page_title="Registrar Compra", page_icon="📝")

st.title("📝 Registrar Nueva Compra")
st.markdown("Ingresa los datos de la operación para sumarla a tu portafolio.")

with st.form("form_compra", clear_on_submit=False):
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        ticker_input = st.text_input("Ticker (Ej: GGAL)", placeholder="GGAL").strip().upper()
        if ticker_input and not ticker_input.endswith(".BA") and len(ticker_input) < 10:
            st.caption(f"Se guardará como: **{ticker_input}.BA**")

    with col2:
        lista_brokers = list(config.COMISIONES.keys())
        idx_def = lista_brokers.index('IOL') if 'IOL' in lista_brokers else 0
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
                st.session_state.cartera_intentada = False 
                st.info("Pestaña 'Portafolio' mostrará el nuevo activo tras actualizar datos.")
            else:
                st.error(f"❌ Error: {msg}")
