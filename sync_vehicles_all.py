import requests
import json
from zoneinfo import ZoneInfo
import mysql.connector
from datetime import datetime
import sys

API_URL = "https://app.xirius.ai/api/v1/public/vehicles/stats"
API_KEY = "xir_397e8269a38fb8fa56f68fec756ea0417bec1a2"

DB_CONFIG = {
    "host": "localhost",
    "port": 3306,
    "database": "esma_telemetria",
    "user": "esma_app",
    "password": "Rammstein1",
    "charset": "utf8mb4",
    "autocommit": True,
}

def get_connection():
    return mysql.connector.connect(**DB_CONFIG)

def fetch_vehicles():
    headers = {"X-API-Key": API_KEY}
    response = requests.get(API_URL, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()

def to_mexico_naive(iso_time):
    dt_utc = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
    return dt_utc.astimezone(ZoneInfo("America/Mexico_City")).replace(tzinfo=None)

# ---------------------------------------------------------------
# ESTADO — inserta la lectura cruda tal cual llega (sin cambios de lógica)
# ---------------------------------------------------------------
def insert_estado(conn, vehicle, fecha_mx_dt):
    cursor = conn.cursor()
    fecha_mx = fecha_mx_dt.strftime("%Y-%m-%d %H:%M:%S")

    query = """
        INSERT INTO estado
            (codigo_eco, serie, nombre_equipo, marca, modelo,
             fecha_ultima_actualizacion, latitud, longitud,
             horas_totales_horometro, nivel_combustible, capacidad_litros)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    params = (
        vehicle.get("code"),
        vehicle.get("vin"),
        vehicle.get("name"),
        vehicle.get("brand"),
        vehicle.get("model"),
        fecha_mx,
        vehicle.get("latitude"),
        vehicle.get("longitude"),
        vehicle.get("engineHours"),
        vehicle.get("fuelLevelPct"),
        vehicle.get("tankCapacityLiters")
    )
    cursor.execute(query, params)
    cursor.close()

# ---------------------------------------------------------------
# Obtiene la lectura anterior de 'estado' para calcular el delta
# (la penúltima, ya que la más reciente es la que acabamos de insertar)
# ---------------------------------------------------------------
def get_previous_reading(conn, codigo_eco, current_time_str):
    cursor = conn.cursor(dictionary=True)
    query = """
        SELECT fecha_ultima_actualizacion, horas_totales_horometro, nivel_combustible, capacidad_litros
        FROM estado
        WHERE codigo_eco = %s AND fecha_ultima_actualizacion < %s
        ORDER BY fecha_ultima_actualizacion DESC
        LIMIT 1
    """
    cursor.execute(query, (codigo_eco, current_time_str))
    row = cursor.fetchone()
    cursor.close()
    return row

# ---------------------------------------------------------------
# UTILIZACION — acumula litros consumidos y horas de máquina del día
# ---------------------------------------------------------------
def upsert_utilizacion(conn, vehicle, fecha_str, delta_horas_maquina, delta_litros_consumidos):
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT id, litros_consumidos, horas_maquina, horas_ralenti FROM utilizacion WHERE codigo_eco = %s AND fecha = %s",
        (vehicle.get("code"), fecha_str)
    )
    existing = cursor.fetchone()

    if existing:
        nuevo_litros_consumidos = float(existing["litros_consumidos"] or 0) + delta_litros_consumidos
        nuevo_horas_maquina = float(existing["horas_maquina"] or 0) + delta_horas_maquina
        horas_ralenti = float(existing["horas_ralenti"] or 0)
        litros_hora = round(nuevo_litros_consumidos / nuevo_horas_maquina, 4) if nuevo_horas_maquina > 0 else None
        ralenti_pct = round((horas_ralenti / nuevo_horas_maquina) * 100, 2) if nuevo_horas_maquina > 0 else None

        query = """
            UPDATE utilizacion
            SET serie=%s, nombre_equipo=%s, marca=%s, modelo=%s,
                litros_hora=%s, litros_consumidos=%s, horas_maquina=%s,
                ralenti_porcentaje=%s
            WHERE id=%s
        """
        params = (
            vehicle.get("vin"), vehicle.get("name"), vehicle.get("brand"), vehicle.get("model"),
            litros_hora, nuevo_litros_consumidos, nuevo_horas_maquina, ralenti_pct,
            existing["id"]
        )
    else:
        litros_hora = round(delta_litros_consumidos / delta_horas_maquina, 4) if delta_horas_maquina > 0 else None
        query = """
            INSERT INTO utilizacion
                (codigo_eco, serie, nombre_equipo, marca, modelo, fecha,
                 litros_hora, litros_consumidos, horas_maquina, horas_ralenti, ralenti_porcentaje)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            vehicle.get("code"), vehicle.get("vin"), vehicle.get("name"),
            vehicle.get("brand"), vehicle.get("model"), fecha_str,
            litros_hora, delta_litros_consumidos, delta_horas_maquina, 0, None
        )

    cursor.execute(query, params)
    cursor.close()

# ---------------------------------------------------------------
# HORAS_DIARIAS — acumula horas trabajadas / ralentí / motor apagado del día
# Clasifica el intervalo desde la lectura anterior según el estado actual:
#   ignition=True  y movement=True   -> horas_trabajadas
#   ignition=True  y movement=False  -> horas_ralenti
#   ignition=False                   -> motor_desconectado
# ---------------------------------------------------------------
def upsert_horas_diarias(conn, vehicle, fecha_str, delta_horas, estado_motor):
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT id, horas_trabajadas, horas_ralenti, motor_desconectado, horas_motor_conectado FROM horas_diarias WHERE codigo_eco = %s AND fecha = %s",
        (vehicle.get("code"), fecha_str)
    )
    existing = cursor.fetchone()

    horas_trabajadas_add = delta_horas if estado_motor == "trabajando" else 0
    horas_ralenti_add = delta_horas if estado_motor == "ralenti" else 0
    motor_desconectado_add = delta_horas if estado_motor == "apagado" else 0

    if existing:
        nueva_trabajadas = float(existing["horas_trabajadas"] or 0) + horas_trabajadas_add
        nueva_ralenti = float(existing["horas_ralenti"] or 0) + horas_ralenti_add
        nueva_desconectado = float(existing["motor_desconectado"] or 0) + motor_desconectado_add
        nueva_conectado = nueva_trabajadas + nueva_ralenti

        query = """
            UPDATE horas_diarias
            SET serie=%s, nombre_equipo=%s, marca=%s, modelo=%s,
                horas_trabajadas=%s, horas_motor_conectado=%s,
                horas_ralenti=%s, motor_desconectado=%s
            WHERE id=%s
        """
        params = (
            vehicle.get("vin"), vehicle.get("name"), vehicle.get("brand"), vehicle.get("model"),
            nueva_trabajadas, nueva_conectado, nueva_ralenti, nueva_desconectado,
            existing["id"]
        )
    else:
        horas_conectado = horas_trabajadas_add + horas_ralenti_add
        query = """
            INSERT INTO horas_diarias
                (codigo_eco, serie, nombre_equipo, marca, modelo, fecha,
                 horas_trabajadas, horas_motor_conectado, horas_ralenti, motor_desconectado)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            vehicle.get("code"), vehicle.get("vin"), vehicle.get("name"),
            vehicle.get("brand"), vehicle.get("model"), fecha_str,
            horas_trabajadas_add, horas_conectado, horas_ralenti_add, motor_desconectado_add
        )

    cursor.execute(query, params)
    cursor.close()

def get_last_update_time(conn, codigo_eco):
    cursor = conn.cursor()
    query = "SELECT MAX(fecha_ultima_actualizacion) FROM estado WHERE codigo_eco = %s"
    cursor.execute(query, (codigo_eco,))
    result = cursor.fetchone()
    cursor.close()
    return result[0] if result and result[0] else None

def sync_cycle(debug=False):
    conn = None
    new_records = 0
    skipped = 0

    try:
        data = fetch_vehicles()
        print(f"API returned {data.get('count', 0)} vehicles")

        if not data.get("data"):
            print("No vehicles found in API response")
            return

        conn = get_connection()

        for i, vehicle in enumerate(data["data"]):
            if not vehicle.get("code") or not vehicle.get("time"):
                continue

            if debug and i == 0:
                print("\n--- JSON CRUDO ---")
                print(json.dumps(vehicle, indent=2, ensure_ascii=False))
                print("--- FIN ---\n")

            codigo_eco = vehicle["code"]
            last_update = get_last_update_time(conn, codigo_eco)
            api_time = to_mexico_naive(vehicle["time"])

            if last_update is not None and api_time <= last_update:
                skipped += 1
                continue

            # Lectura anterior (antes de insertar la nueva) para calcular el delta
            api_time_str = api_time.strftime("%Y-%m-%d %H:%M:%S")
            prev = get_previous_reading(conn, codigo_eco, api_time_str)

            insert_estado(conn, vehicle, api_time)
            new_records += 1
            print(f"  Inserted (estado): {codigo_eco} - {vehicle.get('name', 'Unknown')}")

            fecha_str = api_time.strftime("%Y-%m-%d")

            if prev is not None:
                delta_horas = (api_time - prev["fecha_ultima_actualizacion"]).total_seconds() / 3600

                # Solo acumula si el intervalo es razonable (evita huecos de días sin datos)
                if 0 < delta_horas <= 2:
                    # --- Horas de máquina y litros consumidos (utilizacion) ---
                    delta_horas_maquina = 0
                    if vehicle.get("engineHours") is not None and prev["horas_totales_horometro"] is not None:
                        d = float(vehicle["engineHours"]) - float(prev["horas_totales_horometro"])
                        if d >= 0:
                            delta_horas_maquina = d

                    delta_litros_consumidos = 0
                    if vehicle.get("fuelLevelPct") is not None and prev["nivel_combustible"] is not None and vehicle.get("tankCapacityLiters"):
                        pct_diff = float(prev["nivel_combustible"]) - float(vehicle["fuelLevelPct"])
                        if pct_diff > 0:  # bajó el nivel -> consumo; si subió, fue recarga (no se cuenta aquí)
                            delta_litros_consumidos = round((pct_diff / 100) * float(vehicle["tankCapacityLiters"]), 2)

                    if delta_horas_maquina > 0 or delta_litros_consumidos > 0:
                        upsert_utilizacion(conn, vehicle, fecha_str, delta_horas_maquina, delta_litros_consumidos)

                    # --- Horas trabajadas / ralentí / motor apagado (horas_diarias) ---
                    ignition = vehicle.get("ignition")
                    movement = vehicle.get("movement")
                    if ignition is True and movement is True:
                        estado_motor = "trabajando"
                    elif ignition is True and movement is False:
                        estado_motor = "ralenti"
                    else:
                        estado_motor = "apagado"

                    upsert_horas_diarias(conn, vehicle, fecha_str, delta_horas, estado_motor)

        if conn:
            conn.commit()

        print(f"\nSummary: {new_records} new records (estado), {skipped} skipped (no updates)")

    except requests.HTTPError as e:
        print(f"API Error: {e}")
        if e.response:
            print(f"Response: {e.response.text}")
    except mysql.connector.Error as e:
        print(f"Database error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")
    finally:
        if conn:
            conn.close()

def main():
    print(f"Starting vehicle sync at {datetime.now()}")
    print(f"API URL: {API_URL}")
    print(f"Database: {DB_CONFIG['database']}@{DB_CONFIG['host']}")
    print("-" * 50)

    sync_cycle(debug=False)

    print("-" * 50)
    print(f"Sync completed at {datetime.now()}")

if __name__ == "__main__":
    main()