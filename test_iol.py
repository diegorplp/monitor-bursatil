import requests
import json
from datetime import datetime, timedelta
try:
    from config import IOL_USER, IOL_PASSWORD
except:
    print("No se encontró config.py")
    exit()

IOL_BASE = "https://api.invertironline.com"

def get_token():
    print("Obteniendo Token...")
    try:
        data = {"username": IOL_USER, "password": IOL_PASSWORD, "grant_type": "password"}
        r = requests.post(f"{IOL_BASE}/token", data=data)
        r.raise_for_status()
        return r.json()['access_token']
    except Exception as e:
        print(f"Error Token: {e}")
        return None

def test_endpoint_doc(token):
    print("\n--- Probando Endpoint SEGÚN CAPTURA DE PANTALLA ---")
    
    # Parámetros
    mercado = "bCBA"
    simbolo = "GGAL"
    # Fechas en formato YYYY-MM-DD
    f_hasta = datetime.now().strftime('%Y-%m-%d')
    f_desde = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')
    ajustada = "ajustada" # Opciones suelen ser 'ajustada' o 'sinAjustar'

    # CONSTRUCCIÓN DE LA URL SEGÚN TU IMAGEN:
    # /api/v2/{mercado}/Titulos/{simbolo}/Cotizacion/seriehistorica/{fechaDesde}/{fechaHasta}/{ajustada}
    endpoint = f"api/v2/{mercado}/Titulos/{simbolo}/Cotizacion/seriehistorica/{f_desde}/{f_hasta}/{ajustada}"
    
    url = f"{IOL_BASE}/{endpoint}"
    
    headers = {"Authorization": f"Bearer {token}"}
    
    print(f"URL Generada: {url}")
    
    try:
        r = requests.get(url, headers=headers, timeout=15)
        print(f"Status Code: {r.status_code}")
        
        if r.status_code == 200:
            data = r.json()
            if data:
                print("¡ÉXITO ROTUNDO! Se recibieron datos.")
                print(f"Ejemplo del primer dato: {data[0]}")
                return True
            else:
                print("Respuesta 200 pero lista vacía.")
        else:
            print(f"Error: {r.text[:200]}")
            
    except Exception as e:
        print(f"Excepción: {e}")

# Ejecutar
token = get_token()
if token:
    test_endpoint_doc(token)