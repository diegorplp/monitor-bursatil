import pandas as pd
import pandas_ta as ta
import numpy as np
import config

# --- [DETECCIÓN DE BONOS Y COMISIONES] (No Modificado) ---
def _es_bono(ticker):
    if not ticker: return False
    t = str(ticker).strip().upper()
    bonos_letras = ['DICP', 'PARP', 'CUAP', 'DICY', 'PARY', 'TO26', 'PR13', 'CER']
    if any(b in t for b in bonos_letras): return True
    prefijos = ['AL', 'GD', 'TX', 'TO', 'BA', 'BP', 'TV', 'AE', 'SX', 'MR', 'CL', 'NO']
    if any(t.startswith(p) for p in prefijos):
        if any(char.isdigit() for char in t): return True
    return False

def calcular_comision_real(monto_bruto, broker, es_bono=False):
    broker = str(broker).upper().strip()
    iva = config.IVA
    derechos_acciones = config.DERECHOS_ACCIONES
    derechos_bonos = config.DERECHOS_BONOS
    veta_min = config.VETA_MINIMO

    if es_bono:
        tasa_derechos = derechos_bonos
        multiplicador_iva = 1.0
    else:
        tasa_derechos = derechos_acciones
        multiplicador_iva = iva
        
    if broker == 'VETA':
        tasa_veta = config.COMISIONES.get('VETA', 0.0015)
        comision_base = max(veta_min, monto_bruto * tasa_veta)
        costo_total = (comision_base * multiplicador_iva) + (monto_bruto * tasa_derechos)
        return costo_total
    
    tasa = config.COMISIONES.get(broker, config.COMISIONES.get('DEFAULT', 0.0045))
    comision_base = monto_bruto * tasa
    costo_derechos = monto_bruto * tasa_derechos
    
    if es_bono:
        costo_total = comision_base + costo_derechos
    else:
        costo_total = (comision_base + costo_derechos) * multiplicador_iva
        
    return costo_total

# --- INDICADORES (No Modificado el general) ---
def calcular_indicadores(df_historico_raw):
    if df_historico_raw.empty: return pd.DataFrame()
    
    lista_resultados = []
    
    for ticker in df_historico_raw.columns:
        try:
            serie_precios = df_historico_raw[ticker].dropna()
            cant_datos = len(serie_precios)
            
            if cant_datos < 15:
                # Datos insuficientes, saltamos
                continue

            precio_actual = serie_precios.iloc[-1]
            rsi_actual = 0
            var_max_30d = 0
            var_max_5d = 0
            var_ayer = 0
            
            # RSI
            rsi = ta.rsi(serie_precios, length=14)
            if rsi is not None and not rsi.empty:
                rsi_actual = rsi.iloc[-1]
            
            # Caídas
            max_30d = serie_precios.tail(30).max()
            if max_30d > 0: var_max_30d = (precio_actual / max_30d) - 1
            
            max_5d = serie_precios.tail(5).max()
            if max_5d > 0: var_max_5d = (precio_actual / max_5d) - 1
            
            if len(serie_precios) >= 2:
                cierre_ayer = serie_precios.iloc[-2]
                if cierre_ayer > 0: var_ayer = (precio_actual / cierre_ayer) - 1

            lista_resultados.append({
                'Ticker': ticker,
                'Precio': precio_actual,
                'RSI': rsi_actual,
                'Caida_30d': var_max_30d,
                'Caida_5d': var_max_5d,
                'Var_Ayer': var_ayer
            })
            
        except Exception: continue

    df_resumen = pd.DataFrame(lista_resultados)
    if df_resumen.empty: return pd.DataFrame()

    df_resumen.set_index('Ticker', inplace=True)
    
    df_resumen['Caida_30d'] = pd.to_numeric(df_resumen['Caida_30d'], errors='coerce').fillna(0)
    df_resumen['Caida_5d'] = pd.to_numeric(df_resumen['Caida_5d'], errors='coerce').fillna(0)
    df_resumen['Suma_Caidas'] = df_resumen['Caida_30d'].abs() + df_resumen['Caida_5d'].abs()
    
    conditions = [
        (df_resumen['RSI'] >= 60) & (df_resumen['Suma_Caidas'] > 0.10),
        (df_resumen['RSI'] >= 40) & (df_resumen['RSI'] < 60) & (df_resumen['Suma_Caidas'] > 0.12),
        (df_resumen['RSI'] < 40) & (df_resumen['Suma_Caidas'] > 0.15) & (df_resumen['RSI'] > 0)
    ]
    df_resumen['Senal'] = np.select(conditions, ['COMPRAR']*3, default='NEUTRO')
    df_resumen.loc[df_resumen['RSI'].isna(), 'Senal'] = 'PENDIENTE'
    
    return df_resumen

# --- NUEVA FUNCIÓN: SIMULADOR DE RSI ---
def calcular_rsi_simulado(df_historico, ticker, precio_nuevo):
    if ticker not in df_historico.columns: return None
    
    # Tomamos la serie y agregamos el precio nuevo al final
    serie = df_historico[ticker].dropna().copy()
    
    # Agregar el precio simulado como si fuera el cierre de hoy (o mañana)
    # Pandas Series append está deprecado en versiones nuevas, usamos concat
    nueva_fila = pd.Series([precio_nuevo], index=[serie.index[-1] + pd.Timedelta(days=1)])
    serie_simulada = pd.concat([serie, nueva_fila])
    
    try:
        rsi_series = ta.rsi(serie_simulada, length=14)
        if rsi_series is not None and not rsi_series.empty:
            return rsi_series.iloc[-1]
    except: pass
    
    return None

# ... [Resto de funciones omitidas sin cambios: analizar_portafolio, calcular_mep] ...
def analizar_portafolio(df_portafolio, series_precios_actuales):
    if df_portafolio.empty: return pd.DataFrame()

    df = df_portafolio.copy()
    df_precios = series_precios_actuales.to_frame(name='Precio_Actual')
    df = df.merge(df_precios, left_on='Ticker', right_index=True, how='left')

    def calc_fila(row):
        if pd.isna(row['Precio_Actual']) or row['Precio_Actual'] == 0.0: return pd.Series([0,0,0,0,0,0,0])
        
        p_compra = float(row['Precio_Compra'])
        p_actual = float(row['Precio_Actual'])
        cant = float(row['Cantidad'])
        broker = row.get('Broker', 'DEFAULT')
        ticker = row['Ticker']

        es_bono = _es_bono(ticker)
        divisor = 100 if es_bono else 1
        
        monto_compra_puro = (p_compra * cant) / divisor
        valor_bruto_actual = (p_actual * cant) / divisor
        
        comis_compra = calcular_comision_real(monto_compra_puro, broker, es_bono)
        inversion_total = monto_compra_puro + comis_compra

        comis_venta_estimada = calcular_comision_real(valor_bruto_actual, broker, es_bono)
        valor_neto_salida = valor_bruto_actual - comis_venta_estimada

        gan_bruta_monto = valor_bruto_actual - monto_compra_puro
        gan_neta_monto = valor_neto_salida - inversion_total
        
        pct_bruta = (valor_bruto_actual / monto_compra_puro) - 1 if monto_compra_puro else 0
        pct_neta = (gan_neta_monto / inversion_total) if inversion_total else 0

        return pd.Series([inversion_total, valor_bruto_actual, valor_neto_salida, 
                          gan_bruta_monto, gan_neta_monto, pct_bruta, pct_neta])

    cols_calc = ['Inversion_Total', 'Valor_Actual', 'Valor_Salida_Neto', 
                 'Ganancia_Bruta_Monto', 'Ganancia_Neta_Monto', 
                 '%_Ganancia_Bruta', '%_Ganancia_Neto']
    
    df[cols_calc] = df.apply(calc_fila, axis=1)

    df['%_Ganancia_Bruta'] = df['%_Ganancia_Bruta'].replace([np.inf, -np.inf], np.nan)
    df['%_Ganancia_Neto'] = df['%_Ganancia_Neto'].replace([np.inf, -np.inf], np.nan)

    cond_stop_loss = (df['Alerta_Baja'] > 0) & (df['Precio_Actual'] <= df['Alerta_Baja'])
    cond_take_profit = (df['Alerta_Alta'] > 0) & (df['Precio_Actual'] >= df['Alerta_Alta'])
    
    conditions = [cond_stop_loss, cond_take_profit]
    df['Senal_Venta'] = np.select(conditions, ['STOP LOSS', 'TAKE PROFIT'], default='NEUTRO')
    df.loc[df['Precio_Actual'].isna(), 'Senal_Venta'] = 'PRECIO FALTANTE'

    return df

def calcular_mep(df_raw):
    if df_raw.empty: return None, None
    pares = [('AL30.BA', 'AL30D.BA'), ('GD30.BA', 'GD30D.BA')]
    for peso_ticker, dolar_ticker in pares:
        if peso_ticker in df_raw.columns and dolar_ticker in df_raw.columns:
            try:
                serie_peso = df_raw[peso_ticker].dropna()
                serie_dolar = df_raw[dolar_ticker].dropna()
                if serie_peso.empty or serie_dolar.empty: continue
                df_pair = pd.concat([serie_peso, serie_dolar], axis=1, join='inner')
                if df_pair.empty: continue
                mep_series = df_pair.iloc[:,0] / df_pair.iloc[:,1]
                ultimo_mep = mep_series.iloc[-1]
                variacion = 0.0
                if len(mep_series) >= 2:
                    variacion = (ultimo_mep / mep_series.iloc[-2]) - 1
                return ultimo_mep, variacion
            except Exception: continue
    return None, None