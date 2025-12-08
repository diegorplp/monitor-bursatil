import yfinance as yf
import pandas_ta as ta
import pandas as pd

# Definir el ticker (GGAL.BA es Grupo Galicia en el MERVAL)
ticker = "GGAL.BA"

print(f"--- Descargando datos para {ticker} ---")

try:
    # Descargar datos del último día con intervalo de 1 minuto si es posible, o diario
    data = yf.download(ticker, period="1d", interval="1m", progress=False)
    
    # Si el mercado está cerrado y no hay datos de 1m, bajamos datos diarios
    if data.empty:
        print("Mercado cerrado o sin datos intradiarios. Bajando datos diarios...")
        data = yf.download(ticker, period="5d", progress=False)

    if not data.empty:
        # Obtener el último precio de cierre
        ultimo_precio = data['Close'].iloc[-1]
        
        # yfinance a veces devuelve el dato como una Serie o un escalar, aseguramos el formato
        if isinstance(ultimo_precio, pd.Series):
             ultimo_precio = ultimo_precio.item()

        print(f"✅ ÉXITO: Conexión establecida.")
        print(f"📈 El precio actual/último de {ticker} es: ${ultimo_precio:.2f}")
    else:
        print("❌ Error: No se encontraron datos para el ticker especificado.")

except Exception as e:
    print(f"❌ Ocurrió un error: {e}")