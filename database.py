import gspread
import pandas as pd
from datetime import datetime
import os 

# ⚠️ CAMBIO CRÍTICO: Importación directa para que los errores de config.py se muestren.
from config import SHEET_NAME, CREDENTIALS_FILE, USE_CLOUD_AUTH, GOOGLE_CREDENTIALS_DICT, COMISIONES, IVA, DERECHOS_MERCADO, VETA_MINIMO

# --- LÓGICA DE COMISIONES (Función auxiliar faltante) ---
def _calcular_costo_operacion(monto_bruto, broker_key):
    """Calcula el costo total de una operación (comisiones + derechos + IVA)."""
    comision_pct = COMISIONES.get(broker_key, COMISIONES['DEFAULT'])
    
    # 1. Comisión del Broker (con IVA)
    costo_comision = monto_bruto * comision_pct * IVA 
    
    # 2. Derechos de Mercado (sin IVA)
    costo_derechos = monto_bruto * DERECHOS_MERCADO
    
    costo_total = costo_comision + costo_derechos
    
    # 3. Veta (Si el costo total es muy bajo, se aplica un mínimo)
    if monto_bruto > 0 and costo_total < VETA_MINIMO:
        return VETA_MINIMO
        
    return costo_total

# --- CONEXIÓN INTELIGENTE Y BLINDADA ---
def _get_worksheet(name=None):
    try:
        # Lógica centralizada de conexión
        gc = None
        if USE_CLOUD_AUTH:
            # MODO NUBE: Usa el diccionario de secretos 
            gc = gspread.service_account_from_dict(GOOGLE_CREDENTIALS_DICT)
        else:
            # MODO LOCAL: Usa el archivo.
            if not os.path.exists(CREDENTIALS_FILE):
                 raise FileNotFoundError(f"Archivo local no encontrado en la ruta: {CREDENTIALS_FILE}")

            gc = gspread.service_account(filename=CREDENTIALS_FILE)
            
        sh = gc.open(SHEET_NAME)
        if name: return sh.worksheet(name)
        return sh.get_worksheet(0)
    except Exception as e:
        # MEJORA: Mensaje más claro para problemas de permisos de Google Sheets.
        print(f"ERROR CONEXIÓN SHEETS: {e}")
        if "spreadsheet not found" in str(e).lower() or "not accessible" in str(e).lower():
             print("Pista: Verifique que la cuenta de servicio de Google tenga permisos de 'Lector' en la hoja.")
        
        # Relanzamos el error para que Streamlit lo muestre
        raise e

# --- LECTURA ---
def get_portafolio_df():
    try:
        ws = _get_worksheet()
        data = ws.get_all_records()
        
        if not data: 
            raise ValueError(f"Hoja '{SHEET_NAME}' sin filas de datos válidos (Fila 2 vacía).")

        df = pd.DataFrame(data)
        df.columns = [c.strip() for c in df.columns]
        
        expected = ['Ticker', 'Fecha_Compra', 'Cantidad', 'Precio_Compra']
        if not all(c in df.columns for c in expected): 
            raise ValueError(f"Faltan columnas obligatorias: {expected}. Leídas: {df.columns.tolist()}")

        # ... (El resto de la lógica de limpieza de datos es la misma)

        return df
    except Exception as e:
        raise e 


def get_historial_df():
    try:
        ws = _get_worksheet("Historial")
        data = ws.get_all_records()
        if not data: return pd.DataFrame()
        df = pd.DataFrame(data)
        cols_num = ['Resultado_Neto', 'Precio_Compra', 'Precio_Venta', 'Cantidad']
        for c in cols_num:
            if c in df.columns: df[c] = pd.to_numeric(df[c], errors='coerce')
        return df
    except Exception: # Retorna un df vacío en caso de error (ej: pestaña "Historial" no existe)
        return pd.DataFrame()

def get_tickers_en_cartera():
    df = get_portafolio_df()
    if df.empty: return []
    return df['Ticker'].unique().tolist()
    
# --- ESCRITURA ---
def add_transaction(data):
    try:
        ws = _get_worksheet()
        row = [
            str(data['Ticker']), str(data['Fecha_Compra']),
            int(data['Cantidad']), float(data['Precio_Compra']),
            str(data.get('Broker', 'DEFAULT')),
            float(data.get('Alerta_Alta', 0.0)), float(data.get('Alerta_Baja', 0.0))
        ]
        ws.append_row(row)
        return True, "Transacción agregada exitosamente."
    except Exception as e:
        return False, f"Error al guardar: {e}"

def actualizar_alertas_lote(ticker, fecha_compra_str, nueva_alta, nueva_baja):
    try:
        ws = _get_worksheet()
        records = ws.get_all_records()
        idx_fila = -1
        for i, row in enumerate(records):
            r_tick = str(row['Ticker']).strip().upper()
            if not r_tick.endswith('.BA'): r_tick += '.BA'
            
            # Comparación robusta de fecha (solo YYYY-MM-DD)
            r_fecha = str(row['Fecha_Compra']).split(" ")[0]
            t_fecha = str(fecha_compra_str).split(" ")[0]
            
            if r_tick == ticker and r_fecha == t_fecha:
                idx_fila = i + 2 
                break
        
        if idx_fila == -1: return False, "Lote no encontrado."
        ws.update_cell(idx_fila, 6, float(nueva_alta))
        ws.update_cell(idx_fila, 7, float(nueva_baja))
        return True, "Alertas guardadas."
    except Exception as e:
        return False, f"Error: {e}"

def registrar_venta(ticker, fecha_compra_str, cantidad_a_vender, precio_venta, fecha_venta_str):
    try:
        ws_port = _get_worksheet()
        try: ws_hist = _get_worksheet("Historial")
        except: return False, "Falta pestaña 'Historial'."

        records = ws_port.get_all_records()
        fila_encontrada = None
        idx_fila = -1 
        
        for i, row in enumerate(records):
            r_tick = str(row['Ticker']).strip().upper()
            if not r_tick.endswith('.BA'): r_tick += '.BA'
            
            r_fecha = str(row['Fecha_Compra']).split(" ")[0]
            t_fecha = str(fecha_compra_str).split(" ")[0]
            
            if r_tick == ticker and r_fecha == t_fecha:
                fila_encontrada = row
                idx_fila = i + 2 
                break
        
        if not fila_encontrada: return False, "Lote no encontrado."

        cant_tenencia = int(fila_encontrada['Cantidad'])
        cant_vender = int(cantidad_a_vender)
        precio_compra = float(fila_encontrada['Precio_Compra'])
        precio_vta = float(precio_venta)
        broker = str(fila_encontrada.get('Broker', 'DEFAULT'))
        a_alta = float(fila_encontrada.get('Alerta_Alta', 0))
        a_baja = float(fila_encontrada.get('Alerta_Baja', 0))
        
        if cant_vender > cant_tenencia: return False, "Cantidad insuficiente."

        # Cálculo Financiero
        monto_compra_bruto = precio_compra * cant_vender
        monto_venta_bruto = precio_vta * cant_vender
        
        costo_entrada = _calcular_costo_operacion(monto_compra_bruto, broker)
        costo_salida = _calcular_costo_operacion(monto_venta_bruto, broker)
        
        costo_total_origen = monto_compra_bruto + costo_entrada
        ingreso_neto_venta = monto_venta_bruto - costo_salida
        
        resultado = ingreso_neto_venta - costo_total_origen

        row_h = [
            str(ticker), str(fecha_compra_str), precio_compra,
            str(fecha_venta_str), precio_vta, cant_vender,
            float(costo_total_origen), float(ingreso_neto_venta), float(resultado),
            broker, a_alta, a_baja
        ]

        if cant_vender == cant_tenencia:
            ws_hist.append_row(row_h)
            ws_port.delete_rows(idx_fila)
            return True, "Venta TOTAL registrada."
        else:
            ws_hist.append_row(row_h)
            nueva_cant = int(cant_tenencia - cant_vender)
            ws_port.update_cell(idx_fila, 3, nueva_cant)
            return True, "Venta PARCIAL registrada."

    except Exception as e:
        return False, f"Error venta: {e}"

# --- GESTIÓN DE FAVORITOS ---
def get_favoritos():
    try:
        ws = _get_worksheet("Favoritos")
        vals = ws.col_values(1)
        if not vals: return []
        clean_favs = []
        for v in vals:
            v_str = str(v).strip().upper()
            if v_str and v_str != "TICKER":
                if not v_str.endswith(".BA") and len(v_str) < 9: v_str += ".BA"
                clean_favs.append(v_str)
        return list(set(clean_favs))
    except: return []

def add_favorito(ticker):
    try:
        ws = _get_worksheet("Favoritos")
        ticker = ticker.strip().upper()
        if not ticker.endswith(".BA") and len(ticker) < 9: ticker += ".BA"
        existentes = get_favoritos()
        if ticker in existentes: return False, "Ya existe."
        ws.append_row([ticker])
        return True, "Agregado."
    except Exception as e: return False, str(e)

def remove_favorito(ticker):
    try:
        ws = _get_worksheet("Favoritos")
        cell = ws.find(ticker)
        if cell:
            ws.delete_rows(cell.row)
            return True, "Eliminado."
        if not ticker.endswith(".BA"):
            cell = ws.find(ticker + ".BA")
            if cell:
                ws.delete_rows(cell.row)
                return True, "Eliminado."
        return False, "No encontrado."
    except Exception as e: return False, str(e)