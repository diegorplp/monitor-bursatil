import requests
import config
from datetime import datetime, timedelta

IOL_BASE = "https://api.invertironline.com"

def get_token():
    try:
        data = {"username": config.IOL_USER, "password": config.IOL_PASSWORD, "grant_type": "password"}
        r = requests.post(f"{IOL_BASE}/token", data=data)
        return r.json()['access_token']
    except: return None

token = get_token()
if token:
    print("--- PRUEBA SIN AJUSTE ---")
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')
    
    # URL terminada en 'sinAjustar' en lugar de 'ajustada'
    url = f"{IOL_BASE}/api/v2/bCBA/Titulos/AAPL/Cotizacion/seriehistorica/{start}/{end}/sinAjustar"
    
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(url, headers=headers)
    
    print(f"URL: {url}")
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        print(f"Datos: {r.json()}")