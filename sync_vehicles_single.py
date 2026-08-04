import requests
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

def insert_estado(conn, vehicle):
    cursor = conn.cursor()

    # Convertir timestamp UTC de la API a hora de México (sin tzinfo, para comparar/guardar limpio)
    fecha_mx = None
    if vehicle.get("time"):
        dt_utc = datetime.fromisoformat(vehicle["time"].replace("Z", "+00:00"))
        dt_mx = dt_utc.astimezone(ZoneInfo("America/Mexico_City")).replace(tzinfo=None)
        fecha_mx = dt_mx.strftime("%Y-%m-%d %H:%M:%S")

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

def get_last_update_time(conn, codigo_eco):
    cursor = conn.cursor()
    query = """
        SELECT MAX(fecha_ultima_actualizacion)
        FROM estado
        WHERE codigo_eco = %s
    """
    cursor.execute(query, (codigo_eco,))
    result = cursor.fetchone()
    cursor.close()
    return result[0] if result and result[0] else None

def sync_cycle():
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

        for vehicle in data["data"]:
            if not vehicle.get("code") or not vehicle.get("time"):
                continue

            last_update = get_last_update_time(conn, vehicle["code"])

            if vehicle["time"]:
                # Convertir timestamp de la API (UTC) a hora de México SIN tzinfo,
                # para poder compararlo contra lo que ya está guardado en la BD (naive)
                api_time_utc = datetime.fromisoformat(vehicle["time"].replace("Z", "+00:00"))
                api_time = api_time_utc.astimezone(ZoneInfo("America/Mexico_City")).replace(tzinfo=None)

                if last_update is None or api_time > last_update:
                    insert_estado(conn, vehicle)
                    new_records += 1
                    print(f"  Inserted: {vehicle['code']} - {vehicle.get('name', 'Unknown')}")
                else:
                    skipped += 1

        if conn:
            conn.commit()

        print(f"\nSummary: {new_records} new records, {skipped} skipped (no updates)")

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

    sync_cycle()

    print("-" * 50)
    print(f"Sync completed at {datetime.now()}")

if __name__ == "__main__":
    main()