"""
simulador.py — Simula datos del FMC650 para probar en localhost
GRUPO ESMA — Sistema de Telemetría

Uso:
    py simulador.py

Envía datos de prueba al endpoint /api/telemetria cada 10 segundos
para que puedas ver el dashboard funcionando sin tener el dispositivo físico.
"""
import requests
import random
import time
from datetime import datetime, date

URL = "http://localhost:5000/api/telemetria"

# Equipos de prueba basados en tu BD real
EQUIPOS = [
    {"eco": "EXC-001", "serie": "VCEC350DC00271259", "nombre_equipo": "EXCAVADORA",       "marca": "VOLVO",   "modelo": "EC350DL", "capacidad_litros": 500},
    {"eco": "EXC-008", "serie": "VCEC350DC00271424", "nombre_equipo": "EXCAVADORA",       "marca": "VOLVO",   "modelo": "EC350DL", "capacidad_litros": 500},
    {"eco": "EXC-009", "serie": "VCEC350DP00281740", "nombre_equipo": "EXCAVADORA",       "marca": "VOLVO",   "modelo": "EC350DL", "capacidad_litros": 500},
    {"eco": "CGD-001", "serie": "VGEL110FAJ0071129", "nombre_equipo": "CARGADOR FRONTAL", "marca": "VOLVO",   "modelo": "L110F",   "capacidad_litros": 310},
    {"eco": "TOR-005", "serie": "100197",            "nombre_equipo": "TRACTOR",          "marca": "KOMATSU", "modelo": "D155AX-8","capacidad_litros": 400},
    {"eco": "MTN-001", "serie": "60270",             "nombre_equipo": "MOTOCONFORMADORA", "marca": "KOMATSU", "modelo": "GD655-6", "capacidad_litros": 350},
]

# Coordenadas base de obras reales (lat, lon)
OBRAS = {
    "EXC-001": (20.1234, -99.4567),   # SAN FELIPE
    "EXC-008": (19.8765, -98.9012),   # PALMILLAS
    "EXC-009": (19.8770, -98.9020),   # PALMILLAS
    "CGD-001": (19.3456, -98.7890),   # TEXCOCO-ECATEPEC
    "TOR-005": (20.1111, -99.3333),   # PALMILLAS
    "MTN-001": (19.2222, -98.6666),   # CHALCO
}

# Estado acumulado por equipo (simula avance real)
estado = {
    eq["eco"]: {
        "horometro":         random.uniform(1000, 9000),
        "nivel_combustible": random.uniform(40, 90),
        "litros_consumidos": 0,
        "horas_trabajadas":  0,
        "horas_ralenti":     0,
    }
    for eq in EQUIPOS
}

def simular_envio(equipo):
    eco = equipo["eco"]
    st  = estado[eco]
    lat_base, lon_base = OBRAS.get(eco, (19.4, -99.1))

    # Simular movimiento pequeño
    lat = lat_base + random.uniform(-0.001, 0.001)
    lon = lon_base + random.uniform(-0.001, 0.001)

    # Simular consumo gradual
    consumo_incremental  = random.uniform(8, 25)    # litros/hora
    horas_inc            = random.uniform(0.1, 0.3) # fracción de hora
    ralenti_inc          = random.uniform(0.01, 0.1)

    st["horometro"]         += horas_inc
    st["nivel_combustible"] -= random.uniform(0.5, 2.0)
    st["nivel_combustible"]  = max(5, st["nivel_combustible"])  # mínimo 5%
    st["litros_consumidos"] += consumo_incremental * horas_inc
    st["horas_trabajadas"]  += horas_inc
    st["horas_ralenti"]     += ralenti_inc

    horas_motor   = st["horas_trabajadas"]
    litros_hora   = round(consumo_incremental, 2)
    ralenti_pct   = round((st["horas_ralenti"] / max(horas_motor, 0.01)) * 100, 1)

    payload = {
        # Identificación
        "eco":               eco,
        "serie":             equipo["serie"],
        "nombre_equipo":     equipo["nombre_equipo"],
        "marca":             equipo["marca"],
        "modelo":            equipo["modelo"],
        "capacidad_litros":  equipo["capacidad_litros"],

        # Estado actual (tabla estado)
        "fecha":                      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "latitud":                    round(lat, 7),
        "longitud":                   round(lon, 7),
        "horas_totales_horometro":    round(st["horometro"], 2),
        "nivel_combustible":          round(st["nivel_combustible"], 2),

        # Acumulados del día (tablas horas_diarias y utilizacion)
        "fecha_dia":             date.today().strftime("%Y-%m-%d"),
        "horas_trabajadas":      round(st["horas_trabajadas"], 2),
        "horas_motor_conectado": round(st["horas_trabajadas"] + st["horas_ralenti"], 2),
        "horas_ralenti":         round(st["horas_ralenti"], 2),
        "motor_desconectado":    round(max(0, 8 - horas_motor), 2),
        "litros_consumidos":     round(st["litros_consumidos"], 2),
        "litros_hora":           litros_hora,
        "horas_maquina":         round(horas_motor, 2),
        "ralenti_porcentaje":    ralenti_pct,
    }

    try:
        r = requests.post(URL, json=payload, timeout=5)
        print(f"  [{eco}] Nivel: {payload['nivel_combustible']:.1f}% | "
              f"Horómetro: {payload['horas_totales_horometro']:.1f}h | "
              f"Lts/hr: {litros_hora} | Status: {r.status_code}")
    except Exception as e:
        print(f"  [{eco}] ERROR: {e}")

# ── Loop principal ────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 55)
    print("  SIMULADOR FMC650 — GRUPO ESMA")
    print(f"  Enviando datos a: {URL}")
    print(f"  Equipos: {len(EQUIPOS)}")
    print("  Ctrl+C para detener")
    print("=" * 55)

    ciclo = 0
    while True:
        ciclo += 1
        print(f"\n── Ciclo {ciclo} — {datetime.now().strftime('%H:%M:%S')} ──")
        for equipo in EQUIPOS:
            simular_envio(equipo)
            time.sleep(0.5)  # pequeña pausa entre equipos
        print(f"  Esperando 10 segundos...")
        time.sleep(10)
