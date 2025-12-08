import gspread
import pandas as pd
from datetime import datetime
try:
    from config import SHEET_NAME, CREDENTIALS_FILE, COMISIONES, IVA, DERECHOS_MERCADO, VETA_MINIMO
except ImportError:
    SHEET_NAME = ""
    CREDENTIALS_FILE = ""
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
        try:
            from config import USE_CLOUD_AUTH, GOOGLE_CREDENTIALS_DICT
            if USE_CLOUD_AUTH:
                gc = gspread.service_account_from_dict(GOOGLE_CREDENTIALS_DICT)
            else:
                gc = gspread.service_account(filename=CREDENTIALS_FILE)
        except ImportError:
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
        ws = _get_worksheet()
        data = ws.get_all_records()
        if not data: return pd.DataFrame()

        df = pd.DataFrame(data)
        df.columns = [c.strip() for c in df.columns]
        
        expected = ['Ticker', 'Fecha_Compra', 'Cantidad', 'Precio_Compra']
        if not all(c in df.columns for c in expected): return pd.DataFrame()

        def fix_ticker(t):
            t = str(t).strip().upper()
            if not t.endswith('.BA') and len(t) < 9 and len(t) > 0: return f"{t}.BA"
            return t
        df['Ticker'] = df['Ticker'].apply(fix_ticker)

        if 'Broker' not in df.columns: df['Broker'] = 'DEFAULT'
        if 'Alerta_Alta' not in df.columns: df['Alerta_Alta'] = 0.0
        if 'Alerta_Baja' not in df.columns: df['Alerta_Baja'] = 0.0
        if 'CoolDown_Alta' not in df.columns: df['CoolDown_Alta'] = 0
        if 'CoolDown_Baja' not in df.columns: df['CoolDown_Baja'] = 0

        df['Cantidad'] = pd.to_numeric(df['Cantidad'], errors='coerce').fillna(0).astype(float)
        df['Precio_Compra'] = pd.to_numeric(df['Precio_Compra'], errors='coerce').fillna(0).astype(float)
        df['Alerta_Alta'] = pd.to_numeric(df['Alerta_Alta'], errors='coerce').fillna(0.0).astype(float)
        df['Alerta_Baja'] = pd.to_numeric(df['Alerta_Baja'], errors='coerce').fillna(0.0).astype(float)
        df = df[df['Ticker'] != '']
        df = df[df['Cantidad'] > 0]
        df['Fecha_Compra'] = pd.to_datetime(df['Fecha_Compra'], errors='coerce')

        return df
    except Exception as e:
        print(f"ERROR LEYENDO DB: {e}")
        return pd.DataFrame()

def get_historial_df():
    try:
        ws = _get_worksheet("Historial")
        data = ws.get_all_records()
        if not data: return pd.DataFrame()
        df = pd.DataFrame(data)
        cols_num = ['Resultado_Neto', 'Precio_Compra', 'Precio_Venta', 'Cantidad']
        for c in cols_num:
            if c in df.columns:
                df[c] = df[c].astype(str).str.replace(',', '.')
                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)
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
            if not r_tick.endswith('.BA') and len(r_tick) < 9: r_tick += '.BA'
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

def registrar_venta(ticker, fecha_compra_str, cantidad_a_vender, precio_venta, fecha_venta_str, precio_compra_id=None):
    """
    Registra la venta. Usa precio_compra_id para diferenciar lotes del mismo día.
    """
    try:
        ws_port = _get_worksheet()
        try: ws_hist = _get_worksheet("Historial")
        except: return False, "Falta pestaña 'Historial'."

        records = ws_port.get_all_records()
        fila_encontrada = None
        idx_fila = -1 
        
        for i, row in enumerate(records):
            r_tick = str(row['Ticker']).strip().upper()
            if not r_tick.endswith('.BA') and len(r_tick) < 9: r_tick += '.BA'
            r_fecha = str(row['Fecha_Compra']).split(" ")[0]
            t_fecha = str(fecha_compra_str).split(" ")[0]
            
            # Coincidencia básica
            if r_tick == ticker and r_fecha == t_fecha:
                # CORRECCIÓN DE BUG DE DUPLICADOS:
                # Si nos pasan el precio ID, verificamos que coincida
                if precio_compra_id is not None:
                    p_row = float(str(row['Precio_Compra']).replace(',','.'))
                    p_target = float(precio_compra_id)
                    # Tolerancia de centavos por redondeo
                    if abs(p_row - p_target) > 0.05:
                        continue # No es el lote correcto, saltar
                
                fila_encontrada = row
                idx_fila = i + 2 
                break
        
        if not fila_encontrada: return False, "Lote no encontrado (Check precio/fecha)."

        cant_tenencia = int(fila_encontrada['Cantidad'])
        cant_vender = int(cantidad_a_vender)
        precio_compra = float(str(fila_encontrada['Precio_Compra']).replace(',','.'))
        precio_vta = float(precio_venta)
        broker = str(fila_encontrada.get('Broker', 'DEFAULT'))
        a_alta = float(fila_encontrada.get('Alerta_Alta', 0))
        a_baja = float(fila_encontrada.get('Alerta_Baja', 0))
        
        if cant_vender > cant_tenencia: return False, f"Insuficiente: tienes {cant_tenencia}, pides {cant_vender}."

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
    except Exception as e: return False, f"Error: {e}"

def remove_favorito(ticker):
    try:
        ws = _get_worksheet("Favoritos")
        cell = ws.find(ticker)
        if cell:
            ws.delete_rows(cell.row)
            return True, "Eliminado."
        cell = ws.find(ticker.replace('.BA', ''))
        if cell:
            ws.delete_rows(cell.row)
            return True, "Eliminado."
        return False, "No encontrado."
    except Exception as e: return False, f"Error: {e}"