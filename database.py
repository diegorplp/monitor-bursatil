import gspread
import pandas as pd
from datetime import datetime

# Importamos todo lo necesario de config, incluyendo los flags de la nube
try:
    from config import SHEET_NAME, CREDENTIALS_FILE, USE_CLOUD_AUTH, GOOGLE_CREDENTIALS_DICT, COMISIONES, IVA, DERECHOS_MERCADO, VETA_MINIMO
except ImportError:
    # Valores dummy para evitar crash si config falla
    SHEET_NAME = ""
    CREDENTIALS_FILE = ""
    USE_CLOUD_AUTH = False
    GOOGLE_CREDENTIALS_DICT = {}
    COMISIONES = {}
    IVA = 1.21
    DERECHOS_MERCADO = 0.0008
    VETA_MINIMO = 50

# --- LÓGICA DE COMISIONES (Privada) ---
def _calcular_costo_operacion(monto_bruto, broker):
    broker = str(broker).upper().strip()
    if broker == 'VETA':
        TASA = 0.0015
        comision_base = max(VETA_MINIMO, monto_bruto * TASA)
        gastos = (comision_base * IVA) + (monto_bruto * DERECHOS_MERCADO)
        return gastos
    elif broker == 'COCOS':
        return monto_bruto * DERECHOS_MERCADO
    else:
        tasa = COMISIONES.get(broker, 0.006)
        return monto_bruto * tasa

# --- CONEXIÓN ---
def _get_worksheet(name=None):
    try:
        if USE_CLOUD_AUTH:
            # MODO NUBE: Usamos el diccionario de secretos
            gc = gspread.service_account_from_dict(GOOGLE_CREDENTIALS_DICT)
        else:
            # MODO LOCAL: Usamos el archivo físico
            gc = gspread.service_account(filename=CREDENTIALS_FILE)
            
        sh = gc.open(SHEET_NAME)
        if name: return sh.worksheet(name)
        return sh.get_worksheet(0)
    except Exception as e:
        print(f"ERROR CONEXIÓN SHEETS: {e}")
        raise e

# --- LECTURA ---
def get_portafolio_df():
    try:
        ws = _get_worksheet() # Conecta OK
        
        # DEBUG: Intentamos leer crudo sin formato
        raw_values = ws.get_all_values()
        
        if not raw_values:
            raise ValueError(f"La hoja '{ws.title}' está TOTALMENTE vacía (0 celdas con datos).")
            
        # Si hay datos, veamos qué son
        header = raw_values[0]
        row_count = len(raw_values)
        
        # Validamos si gspread lo lee como dict
        data = ws.get_all_records()
        
        if not data:
            # Aquí está el problema. Hay datos visuales pero el record devuelve vacío.
            # Probablemente el header está mal o hay filas vacías interactivas.
            raise ValueError(
                f"Error Lógico Gspread: Hay {row_count} filas crudas, pero get_all_records devolvió 0.\n"
                f"Encabezados leídos: {header}\n"
                f"Ejemplo Fila 2: {raw_values[1] if row_count > 1 else 'N/A'}"
            )

        df = pd.DataFrame(data)
        # ... (Resto del código de limpieza igual) ...
        df.columns = [c.strip() for c in df.columns]
        
        def fix_ticker(t):
            t = str(t).strip().upper()
            if not t.endswith('.BA') and len(t) < 9: return f"{t}.BA"
            return t
        df['Ticker'] = df['Ticker'].apply(fix_ticker)

        # Tipos
        df['Cantidad'] = pd.to_numeric(df['Cantidad'], errors='coerce')
        df['Precio_Compra'] = pd.to_numeric(df['Precio_Compra'], errors='coerce')
        
        df.dropna(subset=['Ticker', 'Cantidad', 'Precio_Compra'], inplace=True)
        
        if df.empty:
            raise ValueError(f"Leí datos pero al limpiar quedó vacío. Chequea tipos de datos.\nData cruda: {data[:1]}")

        return df

    except Exception as e:
        # Propagamos el error para verlo en el cartel rojo del Home
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
    except: return pd.DataFrame()

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