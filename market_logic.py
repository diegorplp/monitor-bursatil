import pandas as pd
import pandas_ta as ta
import numpy as np
import config

# --- CÁLCULO DE COMISIONES CENTRALIZADO ---
def calcular_comision_real(monto_bruto, broker):
    """
    Calcula la comisión exacta según las reglas del broker y config.
    """
    broker = str(broker).upper().strip()
    
    # Traemos constantes de config
    iva = config.IVA
    derechos = config.DERECHOS_MERCADO
    veta_min = config.VETA_MINIMO
    
    if broker == 'VETA':
        # 0.15% + IVA + Derechos. Mínimo fijo.
        TASA_VETA = 0.0015
        
        # El mínimo de VETA aplica a la comisión pura del broker
        comision_base = max(veta_min, monto_bruto * TASA_VETA)
        
        # El IVA aplica sobre esa comisión base
        gastos = (comision_base * iva) + (monto_bruto * derechos)
        return gastos

    elif broker == 'COCOS':
        # 0% Comisión, solo derechos.
        return monto_bruto * derechos

    else:
        # Default (IOL/BULL): Tasa all-in del config (ej: 0.6%)
        # Si el broker no está en la lista, usa DEFAULT
        tasa = config.COMISIONES.get(broker, config.COMISIONES['DEFAULT'])
        return monto_bruto * tasa

# --- INDICADORES (Screener) ---
def calcular_indicadores(df_historico_raw):
    if df_historico_raw.empty:
        return pd.DataFrame()

    lista_resultados = []
    
    for ticker in df_historico_raw.columns:
        try:
            serie_precios = df_historico_raw[ticker].dropna()
            if serie_precios.empty: continue

            precio_actual = serie_precios.iloc[-1]
            
            # Init vars
            rsi_actual = 0
            var_max_30d = 0
            var_max_5d = 0
            var_ayer = 0
            
            if len(serie_precios) > 14:
                rsi = ta.rsi(serie_precios, length=14)
                if rsi is not None and not rsi.empty:
                    rsi_actual = rsi.iloc[-1]
                
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

        except Exception as e:
            continue

    df_resumen = pd.DataFrame(lista_resultados)
    
    if df_resumen.empty: 
        return pd.DataFrame()

    df_resumen.set_index('Ticker', inplace=True)
    df_resumen['Suma_Caidas'] = df_resumen['Caida_30d'].abs() + df_resumen['Caida_5d'].abs()

    conditions = [
        (df_resumen['RSI'] >= 60) & (df_resumen['Suma_Caidas'] > 0.10),
        (df_resumen['RSI'] >= 40) & (df_resumen['RSI'] < 60) & (df_resumen['Suma_Caidas'] > 0.12),
        (df_resumen['RSI'] < 40) & (df_resumen['Suma_Caidas'] > 0.15) & (df_resumen['RSI'] > 0)
    ]
    choices = ['COMPRAR', 'COMPRAR', 'COMPRAR']
    df_resumen['Senal'] = np.select(conditions, choices, default='NEUTRO')
    
    return df_resumen

# --- ANÁLISIS DE PORTAFOLIO (Rentabilidad) ---
def analizar_portafolio(df_portafolio, series_precios_actuales):
    if df_portafolio.empty: return pd.DataFrame()

    df = df_portafolio.copy()
    df_precios = series_precios_actuales.to_frame(name='Precio_Actual')
    df = df.merge(df_precios, left_on='Ticker', right_index=True, how='left')

    def calc_fila(row):
        # Si no hay precio actual, devolvemos 0s
        if pd.isna(row['Precio_Actual']): return pd.Series([0,0,0,0,0,0,0])
        
        p_compra = row['Precio_Compra']
        p_actual = row['Precio_Actual']
        cant = row['Cantidad']
        broker = row.get('Broker', 'DEFAULT')

        # 1. Valor Bruto Actual (Mercado)
        valor_bruto_actual = p_actual * cant
        
        # 2. Inversión Total (Costo Origen Estimado con comisiones de compra)
        monto_compra_puro = p_compra * cant
        # Asumimos que pagaste comisiones al entrar. Usamos la regla del broker.
        comis_compra = calcular_comision_real(monto_compra_puro, broker)
        inversion_total = monto_compra_puro + comis_compra

        # 3. Valor Salida Neto (Si vendieras hoy)
        comis_venta_estimada = calcular_comision_real(valor_bruto_actual, broker)
        valor_neto_salida = valor_bruto_actual - comis_venta_estimada

        # 4. Ganancias
        gan_bruta_monto = valor_bruto_actual - monto_compra_puro
        gan_neta_monto = valor_neto_salida - inversion_total
        
        pct_bruta = (valor_bruto_actual / monto_compra_puro) - 1 if monto_compra_puro else 0
        pct_neta = (gan_neta_monto / inversion_total) if inversion_total else 0

        return pd.Series([inversion_total, valor_bruto_actual, valor_neto_salida, 
                          gan_bruta_monto, gan_neta_monto, pct_bruta, pct_neta])

    # Aplicamos cálculo
    cols_calc = ['Inversion_Total', 'Valor_Actual', 'Valor_Salida_Neto', 
                 'Ganancia_Bruta_Monto', 'Ganancia_Neta_Monto', 
                 '%_Ganancia_Bruta', '%_Ganancia_Neto']
    
    df[cols_calc] = df.apply(calc_fila, axis=1)

    # Limpieza
    df['%_Ganancia_Bruta'] = df['%_Ganancia_Bruta'].replace([np.inf, -np.inf], np.nan)
    df['%_Ganancia_Neto'] = df['%_Ganancia_Neto'].replace([np.inf, -np.inf], np.nan)

    # Señales (Prioridad Alertas Manuales)
    cond_stop_loss = (df['Alerta_Baja'] > 0) & (df['Precio_Actual'] <= df['Alerta_Baja'])
    cond_take_profit = (df['Alerta_Alta'] > 0) & (df['Precio_Actual'] >= df['Alerta_Alta'])
    cond_tecnica = (df['%_Ganancia_Neto'] >= 0.02)

    conditions = [cond_stop_loss, cond_take_profit, cond_tecnica]
    choices = ['STOP LOSS', 'TAKE PROFIT', 'VENDER (Obj)']
    df['Senal_Venta'] = np.select(conditions, choices, default='NEUTRO')
    df.loc[df['Precio_Actual'].isna(), 'Senal_Venta'] = 'PRECIO FALTANTE'

    return df

# --- DÓLAR MEP ---
def calcular_mep(df_raw):
    if df_raw.empty: return None, None
    
    # Pares ordenados por prioridad de liquidez
    pares = [('AL30.BA', 'AL30D.BA'), ('GD30.BA', 'GD30D.BA')]
    
    for peso_ticker, dolar_ticker in pares:
        if peso_ticker in df_raw.columns and dolar_ticker in df_raw.columns:
            try:
                serie_peso = df_raw[peso_ticker].dropna()
                serie_dolar = df_raw[dolar_ticker].dropna()
                
                df_pair = pd.concat([serie_peso, serie_dolar], axis=1, join='inner')
                df_pair.columns = ['peso', 'dolar']
                
                if df_pair.empty: continue
                
                mep_series = df_pair['peso'] / df_pair['dolar']
                ultimo_mep = mep_series.iloc[-1]
                
                variacion = 0.0
                if len(mep_series) >= 2:
                    mep_ayer = mep_series.iloc[-2]
                    variacion = (ultimo_mep / mep_ayer) - 1
                
                return ultimo_mep, variacion
            except: continue
                
    return None, None