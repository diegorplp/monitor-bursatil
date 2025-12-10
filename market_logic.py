import pandas as pd
import pandas_ta as ta
import numpy as np
import config

# --- DETECCIÓN DE BONOS ---
def _es_bono(ticker):
    if not ticker: return False
    t = str(ticker).strip().upper()
    bonos_letras = ['DICP', 'PARP', 'CUAP', 'DICY', 'PARY', 'TO26', 'PR13', 'CER']
    if any(b in t for b in bonos_letras): return True
    prefijos = ['AL', 'GD', 'TX', 'TO', 'BA', 'BP', 'TV', 'AE', 'SX', 'MR', 'CL', 'NO']
    if any(t.startswith(p) for p in prefijos):
        if any(char.isdigit() for char in t): return True
    return False

# --- CÁLCULO DE COMISIONES ---
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
        gastos = (comision_base * multiplicador_iva) + (monto_bruto * tasa_derechos)
        return gastos
    
    tasa = config.COMISIONES.get(broker, config.COMISIONES.get('DEFAULT', 0.0045))
    comision_base = monto_bruto * tasa
    costo_derechos = monto_bruto * tasa_derechos
    
    if es_bono:
        costo_total = comision_base + costo_derechos
    else:
        costo_total = (comision_base + costo_derechos) * multiplicador_iva
        
    return costo_total

# --- INDICADORES (Manejo de Error y Fallback) ---
def calcular_indicadores(df_historico_raw):
    if df_historico_raw.empty: return pd.DataFrame()

    lista_resultados = []
    
    for ticker in df_historico_raw.columns:
        # CRÍTICO: El bloque try/except ahora envuelve el cálculo de INDICADORES
        try:
            serie_precios = df_historico_raw[ticker].dropna()
            
            # Si solo tiene el precio de hoy (viene de IOL/la última fila) no podemos calcular RSI
            if len(serie_precios) < 15:
                # Si no hay suficiente histórico, devuelve 0 o None para los indicadores
                precio_actual = serie_precios.iloc[-1] if not serie_precios.empty else None
                lista_resultados.append({
                    'Ticker': ticker,
                    'Precio': precio_actual,
                    'RSI': None,
                    'Caida_30d': None,
                    'Caida_5d': None,
                    'Var_Ayer': None
                })
                continue # Continúa con el siguiente ticker

            precio_actual = serie_precios.iloc[-1]
            rsi_actual = 0
            var_max_30d = 0
            var_max_5d = 0
            var_ayer = 0
            
            # CÁLCULOS ESTÁNDAR
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
            # Fallback si el código de cálculo rompe por alguna razón inesperada
            print(f"FALLBACK ACTIVO en {ticker}: {e}")
            precio_actual = df_historico_raw[ticker].iloc[-1] if not df_historico_raw[ticker].empty else None
            lista_resultados.append({
                'Ticker': ticker,
                'Precio': precio_actual,
                'RSI': None,
                'Caida_30d': None,
                'Caida_5d': None,
                'Var_Ayer': None
            })
            continue

    df_resumen = pd.DataFrame(lista_resultados)
    if df_resumen.empty: return pd.DataFrame()

    df_resumen.set_index('Ticker', inplace=True)
    
    # Aseguramos que las columnas de suma existan y sean numéricas antes de operar
    df_resumen['Caida_30d'] = pd.to_numeric(df_resumen['Caida_30d'], errors='coerce').fillna(0)
    df_resumen['Caida_5d'] = pd.to_numeric(df_resumen['Caida_5d'], errors='coerce').fillna(0)
    
    df_resumen['Suma_Caidas'] = df_resumen['Caida_30d'].abs() + df_resumen['Caida_5d'].abs()
    
    # Lógica de señales (solo si hay RSI)
    conditions = [
        (df_resumen['RSI'] >= 60) & (df_resumen['Suma_Caidas'] > 0.10),
        (df_resumen['RSI'] >= 40) & (df_resumen['RSI'] < 60) & (df_resumen['Suma_Caidas'] > 0.12),
        (df_resumen['RSI'] < 40) & (df_resumen['Suma_Caidas'] > 0.15) & (df_resumen['RSI'] > 0)
    ]
    df_resumen['Senal'] = np.select(conditions, ['COMPRAR']*3, default='NEUTRO')
    df_resumen.loc[df_resumen['RSI'].isna(), 'Senal'] = 'PENDIENTE' # Si no hay RSI, queda Pendiente
    
    return df_resumen

# --- ANÁLISIS DE PORTAFOLIO (Rentabilidad) y DÓLAR MEP omitidos por ser idénticos

# --- DÓLAR MEP (Manejo de Error) ---
def calcular_mep(df_raw):
    if df_raw.empty: return None, None
    pares = [('AL30.BA', 'AL30D.BA'), ('GD30.BA', 'GD30D.BA')]
    
    for peso_ticker, dolar_ticker in pares:
        # CRÍTICO: Comprobar si las columnas existen antes de intentar usarlas
        if peso_ticker in df_raw.columns and dolar_ticker in df_raw.columns:
            try:
                # Ahora usamos el valor de cierre/último precio (última fila)
                serie_peso = df_raw[peso_ticker].dropna()
                serie_dolar = df_raw[dolar_ticker].dropna()
                
                # CRÍTICO: Si no hay datos, pasa al siguiente par
                if serie_peso.empty or serie_dolar.empty: continue
                
                # Buscamos la última fila que tenga valor en ambas
                df_pair = pd.concat([serie_peso, serie_dolar], axis=1, join='inner')
                if df_pair.empty: continue
                
                mep_series = df_pair.iloc[:,0] / df_pair.iloc[:,1]
                
                # Si el último valor es NaN, intentamos el anterior
                ultimo_mep = mep_series.iloc[-1]
                
                variacion = 0.0
                if len(mep_series) >= 2:
                    variacion = (ultimo_mep / mep_series.iloc[-2]) - 1
                
                return ultimo_mep, variacion
                
            except Exception as e:
                 # Si rompe por algún cálculo, intenta el siguiente par
                 print(f"Error calculando MEP para {peso_ticker}: {e}")
                 continue
                 
    return None, None