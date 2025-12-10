import streamlit as st
import pandas as pd
from datetime import datetime
import database
import market_logic
import config
import manager 

st.set_page_config(page_title="Portafolio", layout="wide")
st.title("💰 Tu Portafolio y Señales de Venta")

# --- NUEVO BLOQUE DE MANTENIMIENTO CONSOLIDADO ---
with st.expander("⚙️ Opciones de Sincronización", expanded=False):
    c_db, c_mkt, c_msg = st.columns([1, 1, 4])
    
    with c_db:
        # Botón para Forzar la Recarga del Caché de DB
        if st.button("🔄 Actualizar DB (Excel)"):
            st.cache_data.clear()
            st.rerun()
    
    with c_mkt:
        # Botón para Forzar la Actualización de Precios
        if st.button("⬇️ Actualizar Precios"):
            manager.actualizar_solo_cartera(silent=False)
            st.rerun()
            
    with c_msg:
        st.caption("Usa 'Actualizar DB' si editaste Google Sheet manualmente. 'Actualizar Precios' solo trae cotizaciones de tus activos en tenencia.")

# --- ESTILOS ---
def get_styled_portafolio(df):
    if df.empty: return df
    
    def highlight_row(row):
        senal = row.get('Senal')
        if senal == 'STOP LOSS': return ['background-color: rgba(255, 75, 75, 0.25)'] * len(row) 
        elif senal == 'TAKE PROFIT': return ['background-color: rgba(33, 195, 84, 0.25)'] * len(row) 
        elif senal == 'VENDER (Obj)': return ['background-color: rgba(255, 255, 0, 0.15)'] * len(row) 
        return [''] * len(row)

    def color_profit(val):
        if not isinstance(val, (int, float)): return ''
        if pd.isna(val): return ''
        color = '#21c354' if val >= 0 else '#ff4b4b'
        return f'color: {color}'

    df_styled = df.style.apply(highlight_row, axis=1)
    
    cols_profit = ['GB', '%GB', 'GN', '%GN']
    cols_existentes = [c for c in cols_profit if c in df.columns]
    
    df_styled = df_styled.map(color_profit, subset=cols_existentes)

    format_dict = {
        'P.Compra': '{:,.2f}', 'P.Actual': '{:,.2f}',
        'Inv.Total': '{:,.2f}', 'GB': '{:,.2f}', 'GN': '{:,.2f}',
        '%GB': '{:.2%}', '%GN': '{:.2%}',
        'A.Alta': '{:,.2f}', 'A.Baja': '{:,.2f}'
    }
    # CORREGIDO: Reemplazar use_container_width
    return df_styled.format(format_dict, na_rep="--")

# --- HELPER ALERTAS ---
def render_alert_input(label, current_val, base_price, key_prefix):
    st.markdown(f"**{label}**")
    c1, c2 = st.columns([1, 2])
    with c1:
        modo = st.radio("Tipo", ["$", "%"], key=f"{key_prefix}_mode", horizontal=True, label_visibility="collapsed")
    val_retorno = 0.0
    with c2:
        if modo == "$":
            val_input = st.number_input(f"Precio {label}", value=float(current_val), min_value=0.0, step=10.0, key=f"{key_prefix}_p")
            val_retorno = val_input
        else:
            pct_def = ((current_val / base_price) - 1) * 100 if current_val > 0 else 0.0
            pct_input = st.number_input(f"% {label}", value=float(pct_def), step=1.0, key=f"{key_prefix}_pct")
            val_retorno = base_price * (1 + (pct_input / 100))
    return val_retorno

# --- LOGICA ---
if 'precios_actuales' not in st.session_state or st.session_state.precios_actuales.empty:
    st.warning("⚠️ No hay precios cargados. Ve al Inicio y presiona 'Actualizar Datos'.")
    st.stop() 

try:
    df_port_raw = database.get_portafolio_df()
    
    if df_port_raw.empty:
        st.info("Tu portafolio está vacío.")
    else:
        df_analyzed = market_logic.analizar_portafolio(df_port_raw, st.session_state.precios_actuales)
        
        if 'Fecha_Compra' in df_analyzed.columns:
            df_analyzed['Fecha_fmt'] = pd.to_datetime(df_analyzed['Fecha_Compra']).dt.strftime('%Y-%m-%d')

        df_display = df_analyzed.rename(columns={
            'Fecha_fmt': 'Fecha',
            'Precio_Compra': 'P.Compra', 'Precio_Actual': 'P.Actual',
            'Inversion_Total': 'Inv.Total', 'Ganancia_Bruta_Monto': 'GB',
            '%_Ganancia_Bruta': '%GB', 'Ganancia_Neta_Monto': 'GN',
            '%_Ganancia_Neto': '%GN', 'Senal_Venta': 'Senal',
            'Alerta_Alta': 'A.Alta', 'Alerta_Baja': 'A.Baja'
        })
        
        cols_finales = ['Ticker', 'Broker', 'Fecha', 'Cantidad', 'P.Compra', 'P.Actual', 'Inv.Total', 'GB', '%GB', 'GN', '%GN', 'A.Alta', 'A.Baja', 'Senal']
        cols_validas = [c for c in cols_finales if c in df_display.columns]
        
        st.dataframe(get_styled_portafolio(df_display[cols_validas]), width='stretch', height=400, hide_index=True) # CORREGIDO

        st.divider()
        tab_venta, tab_alertas = st.tabs(["📉 Registrar Venta", "🔔 Configurar Alertas"])

        # --- PESTAÑA VENTA ---
        with tab_venta:
            tickers_disponibles = df_port_raw['Ticker'].unique().tolist()
            col_sel, _ = st.columns([1, 2])
            with col_sel:
                ticker_sel = st.selectbox("1. Seleccionar Activo", tickers_disponibles, key="sel_vta")

            if ticker_sel:
                lotes = df_port_raw[df_port_raw['Ticker'] == ticker_sel]
                opciones_lotes = {}
                for idx, row in lotes.iterrows():
                    fecha_str = pd.to_datetime(row['Fecha_Compra']).strftime('%Y-%m-%d')
                    brk = row.get('Broker', 'DEFAULT')
                    label = f"{fecha_str} ({brk}) | Cant: {row['Cantidad']} | P.Compra: ${row['Precio_Compra']:,.2f}"
                    opciones_lotes[idx] = label
                
                lote_idx = st.selectbox("2. Seleccionar Lote", options=opciones_lotes.keys(), format_func=lambda x: opciones_lotes[x], key="lote_vta")
                
                lote_data = lotes.loc[lote_idx]
                cantidad_max = int(lote_data['Cantidad'])
                fecha_compra_orig = pd.to_datetime(lote_data['Fecha_Compra']).strftime('%Y-%m-%d')
                broker_origen = lote_data.get('Broker', 'DEFAULT')
                precio_compra_orig = float(lote_data['Precio_Compra']) # ID para el backend

                tasa_info = config.COMISIONES.get(broker_origen, "Estándar")
                
                precio_sugerido = 0.0
                if ticker_sel in st.session_state.precios_actuales:
                    precio_sugerido = float(st.session_state.precios_actuales[ticker_sel])

                with st.form("form_venta"):
                    st.markdown("### 3. Detalles de la Operación")
                    st.info(f"🔒 **Custodia:** {broker_origen}")
                    
                    c1, c2, c3 = st.columns(3)
                    with c1: f_venta = st.date_input("Fecha Venta", datetime.now())
                    with c2: p_venta = st.number_input("Precio Venta", min_value=0.0, value=precio_sugerido, step=10.0)
                    with c3: q_venta = st.number_input("Cantidad", min_value=1, max_value=cantidad_max, value=cantidad_max)

                    submitted_venta = st.form_submit_button("Confirmar Venta", type="primary")
                    
                    if submitted_venta:
                        res, msg = database.registrar_venta(
                            ticker=ticker_sel,
                            fecha_compra_str=fecha_compra_orig,
                            cantidad_a_vender=q_venta,
                            precio_venta=p_venta,
                            fecha_venta_str=f_venta.strftime('%Y-%m-%d'),
                            precio_compra_id=precio_compra_orig 
                        )
                        if res:
                            st.success(msg)
                            st.session_state.pop('oportunidades', None)
                            st.rerun()
                        else:
                            st.error(msg)

        # --- PESTAÑA ALERTAS ---
        with tab_alertas:
            col_al_1, _ = st.columns([1, 2])
            with col_al_1:
                ticker_alerta = st.selectbox("1. Seleccionar Activo", tickers_disponibles, key="sel_alerta")
            
            if ticker_alerta:
                lotes_al = df_port_raw[df_port_raw['Ticker'] == ticker_alerta]
                opciones_al = {}
                for idx, row in lotes_al.iterrows():
                    f_str = pd.to_datetime(row['Fecha_Compra']).strftime('%Y-%m-%d')
                    aa = row.get('Alerta_Alta', 0)
                    ab = row.get('Alerta_Baja', 0)
                    est = "🟢" if (aa>0 or ab>0) else "⚪"
                    opciones_al[idx] = f"{est} {f_str} | Compra: ${row['Precio_Compra']:,.0f}"
                
                lote_idx_al = st.selectbox("2. Seleccionar Lote", options=opciones_al.keys(), format_func=lambda x: opciones_al[x], key="lote_al")
                row_al = lotes_al.loc[lote_idx_al]
                p_base = float(row_al['Precio_Compra'])
                v_alta = float(row_al.get('Alerta_Alta', 0.0))
                v_baja = float(row_al.get('Alerta_Baja', 0.0))
                fecha_orig_al = pd.to_datetime(row_al['Fecha_Compra']).strftime('%Y-%m-%d')

                with st.form("form_alertas"):
                    st.markdown("### 3. Configurar Objetivos")
                    st.caption(f"Base de Compra: ${p_base:,.2f}")
                    
                    c_alta, c_baja = st.columns(2)
                    with c_alta: n_alta = render_alert_input("Alta (Take Profit)", v_alta, p_base, "tp")
                    with c_baja: n_baja = render_alert_input("Baja (Stop Loss)", v_baja, p_base, "sl")
                    
                    st.markdown("---")
                    cols_btns = st.columns([1, 1])
                    guardar = cols_btns[0].form_submit_button("💾 Guardar Cambios")
                    
                    if guardar:
                        res, msg = database.actualizar_alertas_lote(ticker_alerta, fecha_orig_al, n_alta, n_baja)
                        if res:
                            st.success("Alertas actualizadas.")
                            st.rerun()
                        else:
                            st.error(msg)
                
                if st.button("🗑️ Borrar Alertas (Reset a 0)", key="del_al"):
                     database.actualizar_alertas_lote(ticker_alerta, fecha_orig_al, 0.0, 0.0)
                     st.rerun()

except Exception as e:
    st.error(f"Error cargando módulo: {e}")