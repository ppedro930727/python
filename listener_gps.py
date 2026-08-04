"""
listener_gps.py — Listener TCP para dispositivos Teltonika FMC650
GRUPO ESMA — Plataforma de Telemetría (esma_telemetria)

Corre como servicio systemd APARTE de Gunicorn (ej. esma-gps-listener.service),
porque mantiene sockets TCP abiertos indefinidamente.

Requiere:
  - Columna maquinas.imei (migración abajo)
"""
import socket
import struct
import threading
import time
from datetime import datetime, date, timezone

import database  # tu módulo existente: query(), execute(), execute_ddl()


# ══════════════════════════════════════════════════════════════════
#  IDs de IO elements — AJUSTAR según tu Configurator
#  (Configurator > tu dispositivo > "I/O elements" o "CAN adapter":
#   ahí ves el ID numérico exacto de cada parámetro que habilitaste)
# ══════════════════════════════════════════════════════════════════
IO_ID_IGNITION = 239          # Digital Input 1 / Ignition — este SÍ es estándar en FMC650
IO_ID_ENGINE_HOURS = None     # TODO: ID del horómetro/engine hours de tu perfil CAN (Volvo/Komatsu vía J1939)
IO_ID_FUEL_LEVEL = None       # TODO: ID del nivel de combustible (CAN) de tu perfil
IO_ID_TOTAL_ODOMETER = None   # TODO: opcional, si lo necesitas


# ══════════════════════════════════════════════════════════════════
#  MIGRACIONES (correr una sola vez antes de arrancar el listener)
# ══════════════════════════════════════════════════════════════════
def migrar_esquema():
    try:
        database.execute_ddl("ALTER TABLE maquinas ADD COLUMN imei VARCHAR(20) DEFAULT NULL")
    except Exception:
        pass
    try:
        database.execute_ddl("ALTER TABLE maquinas ADD UNIQUE KEY uq_maquinas_imei (imei)")
    except Exception:
        pass
    # Nota: estado es histórico (multi-fila por codigo_eco), NO llevar UNIQUE KEY aquí.
    # app.py ya consulta el más reciente vía MAX(fecha_ultima_actualizacion) GROUP BY codigo_eco.
    try:
        database.execute_ddl("ALTER TABLE estado ADD INDEX idx_estado_eco_fecha (codigo_eco, fecha_ultima_actualizacion)")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════
#  MAPEO IMEI -> codigo_eco  (cache en memoria, refresco cada 60s)
# ══════════════════════════════════════════════════════════════════
_cache_lock = threading.Lock()
_imei_to_eco = {}
_cache_ts = 0

def imei_a_eco(imei: str) -> str | None:
    global _cache_ts
    with _cache_lock:
        if time.time() - _cache_ts > 60:
            filas = database.query("SELECT imei, eco FROM maquinas WHERE imei IS NOT NULL")
            _imei_to_eco.clear()
            _imei_to_eco.update({f["imei"]: f["eco"] for f in filas})
            _cache_ts = time.time()
        return _imei_to_eco.get(imei)


# ══════════════════════════════════════════════════════════════════
#  BASELINE DIARIO (horometro/litros al inicio del día, por eco)
#  En memoria; si el proceso se reinicia a medio día se recalcula
#  leyendo el último valor guardado en estado/horas_diarias.
# ══════════════════════════════════════════════════════════════════
_baseline_lock = threading.Lock()
_baseline = {}  # eco -> dict

def _obtener_baseline(eco: str, hoy: date, horometro_actual, litros_actual):
    with _baseline_lock:
        b = _baseline.get(eco)
        if b is None or b["fecha"] != hoy:
            # Nuevo día (o primer ping de este eco): buscar si ya hay fila de hoy
            # (por si el listener se reinició), si no, usar el valor actual como punto de partida.
            fila_horas = database.query(
                "SELECT horas_trabajadas, horas_ralenti FROM horas_diarias WHERE codigo_eco=%s AND fecha=%s",
                (eco, hoy), one=True)
            fila_util = database.query(
                "SELECT litros_consumidos FROM utilizacion WHERE codigo_eco=%s AND fecha=%s",
                (eco, hoy), one=True)
            b = {
                "fecha": hoy,
                "horometro_inicio": (horometro_actual or 0) - float(fila_horas["horas_trabajadas"]) if fila_horas and fila_horas.get("horas_trabajadas") else horometro_actual,
                "litros_inicio_dia": litros_actual,
                "ultimo_horometro": horometro_actual,
                "ultimo_litros": litros_actual,
                "ultimo_ts": None,
                "horas_ralenti_acum": float(fila_horas["horas_ralenti"]) if fila_horas and fila_horas.get("horas_ralenti") else 0.0,
                "litros_consumidos_acum": float(fila_util["litros_consumidos"]) if fila_util and fila_util.get("litros_consumidos") else 0.0,
            }
            _baseline[eco] = b
        return b


# ══════════════════════════════════════════════════════════════════
#  PROCESAMIENTO DE CADA AVL RECORD
# ══════════════════════════════════════════════════════════════════
def procesar_registro(eco: str, maquina: dict, r: dict):
    """
    r: dict ya decodificado por parse_codec8e con llaves esperadas:
       timestamp (datetime), lat, lon, speed, ignition (bool),
       horometro (horas motor acumuladas, IO 239 tipicamente),
       nivel_combustible_pct (0-100), io_all (dict crudo)
    """
    ts = r["timestamp"]
    hoy = ts.date()
    capacidad = float(maquina.get("capacidad_litros") or 0)
    litros_abs = (float(r["nivel_combustible_pct"]) / 100.0 * capacidad) if r.get("nivel_combustible_pct") is not None and capacidad else None

    # 1) Insert en estado — histórico (una fila por ping, NO se sobreescribe).
    #    app.py ya saca el más reciente vía MAX(fecha_ultima_actualizacion) GROUP BY codigo_eco.
    database.execute("""
        INSERT INTO estado
        (codigo_eco, serie, nombre_equipo, marca, modelo,
         fecha_ultima_actualizacion, latitud, longitud,
         horas_totales_horometro, nivel_combustible, capacidad_litros)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (eco, maquina.get("serie"), maquina.get("nombre_equipo"), maquina.get("marca"), maquina.get("modelo"),
          ts, r.get("lat"), r.get("lon"), r.get("horometro"), r.get("nivel_combustible_pct"), capacidad))

    # 2) Baseline diario para horas_diarias / utilizacion
    b = _obtener_baseline(eco, hoy, r.get("horometro"), litros_abs)

    horas_trabajadas = None
    if r.get("horometro") is not None and b["horometro_inicio"] is not None:
        horas_trabajadas = round(float(r["horometro"]) - float(b["horometro_inicio"]), 2)

    # Ralentí: tiempo transcurrido desde el ping anterior, contado como ralentí
    # solo si ignition=on y velocidad=0 (aproximación por diferencia de tiempo entre pings)
    if b["ultimo_ts"] is not None and r.get("ignition") and (r.get("speed") or 0) == 0:
        delta_h = (ts - b["ultimo_ts"]).total_seconds() / 3600.0
        b["horas_ralenti_acum"] += delta_h

    # Litros: solo contar caídas de nivel como consumo (subidas = carga, se ignoran aquí)
    if litros_abs is not None and b["ultimo_litros"] is not None:
        delta_l = b["ultimo_litros"] - litros_abs
        if delta_l > 0:
            b["litros_consumidos_acum"] += delta_l

    b["ultimo_horometro"] = r.get("horometro")
    b["ultimo_litros"] = litros_abs
    b["ultimo_ts"] = ts

    horas_ralenti = round(b["horas_ralenti_acum"], 2)
    horas_maquina = round((horas_trabajadas or 0) - horas_ralenti, 2) if horas_trabajadas is not None else None
    litros_consumidos = round(b["litros_consumidos_acum"], 2)
    litros_hora = round(litros_consumidos / horas_trabajadas, 2) if horas_trabajadas and horas_trabajadas > 0 else None

    # 3) Upsert horas_diarias
    database.execute("""
        INSERT INTO horas_diarias
        (codigo_eco, serie, nombre_equipo, marca, modelo, fecha,
         horas_trabajadas, horas_motor_conectado, horas_ralenti, motor_desconectado)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            horas_trabajadas=VALUES(horas_trabajadas),
            horas_motor_conectado=VALUES(horas_motor_conectado),
            horas_ralenti=VALUES(horas_ralenti)
    """, (eco, maquina.get("serie"), maquina.get("nombre_equipo"), maquina.get("marca"), maquina.get("modelo"),
          hoy, horas_trabajadas, horas_maquina, horas_ralenti, None))

    # 4) Upsert utilizacion
    database.execute("""
        INSERT INTO utilizacion
        (codigo_eco, serie, nombre_equipo, marca, modelo, fecha,
         litros_hora, litros_consumidos, horas_maquina, horas_ralenti, ralenti_porcentaje)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            litros_hora=VALUES(litros_hora),
            litros_consumidos=VALUES(litros_consumidos),
            horas_maquina=VALUES(horas_maquina),
            horas_ralenti=VALUES(horas_ralenti),
            ralenti_porcentaje=VALUES(ralenti_porcentaje)
    """, (eco, maquina.get("serie"), maquina.get("nombre_equipo"), maquina.get("marca"), maquina.get("modelo"),
          hoy, litros_hora, litros_consumidos, horas_maquina, horas_ralenti,
          round(horas_ralenti / horas_trabajadas * 100, 2) if horas_trabajadas else None))


# ══════════════════════════════════════════════════════════════════
#  DECODER — Codec 8 Extended (protocolo público de Teltonika)
# ══════════════════════════════════════════════════════════════════
def _crc16_ibm(data: bytes) -> int:
    """CRC-16/IBM (polinomio 0xA001), el que usa Teltonika para validar el frame."""
    crc = 0x0000
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def parse_codec8e(data: bytes) -> list[dict]:
    """
    Decodifica un frame TCP completo de Codec 8 Extended.
    Estructura: Preamble(4) + DataFieldLength(4) + [CodecID(1) + NumData1(1) +
                AVL records... + NumData2(1)] + CRC(4)
    Lanza ValueError si el frame está corrupto, truncado, o el CRC no coincide.
    """
    if len(data) < 12:
        raise ValueError("Frame demasiado corto")

    preamble = struct.unpack(">I", data[0:4])[0]
    if preamble != 0:
        raise ValueError(f"Preamble invalido: {preamble}")

    data_field_length = struct.unpack(">I", data[4:8])[0]
    payload = data[8:8 + data_field_length]
    if len(payload) < data_field_length:
        raise ValueError("Frame incompleto (payload truncado, esperar mas bytes)")

    crc_recibido = struct.unpack(">I", data[8 + data_field_length:8 + data_field_length + 4])[0]
    crc_calculado = _crc16_ibm(payload)
    if crc_calculado != crc_recibido:
        raise ValueError(f"CRC no coincide: calculado={crc_calculado} recibido={crc_recibido}")

    pos = 0
    codec_id = payload[pos]; pos += 1
    if codec_id != 0x8E:
        raise ValueError(f"Codec no soportado: 0x{codec_id:02X} (se esperaba 0x8E, Codec 8 Extended)")

    num_data_1 = payload[pos]; pos += 1

    registros = []
    for _ in range(num_data_1):
        registro, pos = _parse_avl_record(payload, pos)
        registros.append(registro)

    num_data_2 = payload[pos]; pos += 1
    if num_data_2 != num_data_1:
        raise ValueError(f"Number of Data inconsistente: {num_data_1} vs {num_data_2}")

    return registros


def _parse_avl_record(buf: bytes, pos: int):
    """Decodifica un AVL record (timestamp + GPS + IO elements) a partir de pos."""
    timestamp_ms = struct.unpack(">Q", buf[pos:pos + 8])[0]; pos += 8
    priority = buf[pos]; pos += 1

    longitude = struct.unpack(">i", buf[pos:pos + 4])[0] / 10_000_000.0; pos += 4
    latitude = struct.unpack(">i", buf[pos:pos + 4])[0] / 10_000_000.0; pos += 4
    altitude = struct.unpack(">h", buf[pos:pos + 2])[0]; pos += 2
    angle = struct.unpack(">H", buf[pos:pos + 2])[0]; pos += 2
    satellites = buf[pos]; pos += 1
    speed = struct.unpack(">H", buf[pos:pos + 2])[0]; pos += 2

    _event_io_id = struct.unpack(">H", buf[pos:pos + 2])[0]; pos += 2
    _total_io_count = struct.unpack(">H", buf[pos:pos + 2])[0]; pos += 2

    io_all = {}

    # Propiedades de 1 byte
    n1 = struct.unpack(">H", buf[pos:pos + 2])[0]; pos += 2
    for _ in range(n1):
        io_id = struct.unpack(">H", buf[pos:pos + 2])[0]; pos += 2
        io_all[io_id] = buf[pos]; pos += 1

    # Propiedades de 2 bytes
    n2 = struct.unpack(">H", buf[pos:pos + 2])[0]; pos += 2
    for _ in range(n2):
        io_id = struct.unpack(">H", buf[pos:pos + 2])[0]; pos += 2
        io_all[io_id] = struct.unpack(">H", buf[pos:pos + 2])[0]; pos += 2

    # Propiedades de 4 bytes
    n4 = struct.unpack(">H", buf[pos:pos + 2])[0]; pos += 2
    for _ in range(n4):
        io_id = struct.unpack(">H", buf[pos:pos + 2])[0]; pos += 2
        io_all[io_id] = struct.unpack(">I", buf[pos:pos + 4])[0]; pos += 4

    # Propiedades de 8 bytes
    n8 = struct.unpack(">H", buf[pos:pos + 2])[0]; pos += 2
    for _ in range(n8):
        io_id = struct.unpack(">H", buf[pos:pos + 2])[0]; pos += 2
        io_all[io_id] = struct.unpack(">Q", buf[pos:pos + 8])[0]; pos += 8

    # Propiedades de longitud variable (NX) — solo existe en Codec 8 Extended
    nx = struct.unpack(">H", buf[pos:pos + 2])[0]; pos += 2
    for _ in range(nx):
        io_id = struct.unpack(">H", buf[pos:pos + 2])[0]; pos += 2
        length = struct.unpack(">H", buf[pos:pos + 2])[0]; pos += 2
        io_all[io_id] = buf[pos:pos + length]; pos += length

    ignition = bool(io_all.get(IO_ID_IGNITION, 0))

    horometro = None
    if IO_ID_ENGINE_HOURS is not None and IO_ID_ENGINE_HOURS in io_all:
        horometro = io_all[IO_ID_ENGINE_HOURS] / 3600.0  # ajustar divisor segun unidad real (seg->horas)

    nivel_combustible_pct = None
    if IO_ID_FUEL_LEVEL is not None and IO_ID_FUEL_LEVEL in io_all:
        nivel_combustible_pct = io_all[IO_ID_FUEL_LEVEL]  # ajustar si viene en otra escala

    registro = {
        "timestamp": datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc).replace(tzinfo=None),
        "priority": priority,
        "lat": latitude,
        "lon": longitude,
        "altitude": altitude,
        "angle": angle,
        "satellites": satellites,
        "speed": speed,
        "ignition": ignition,
        "horometro": horometro,
        "nivel_combustible_pct": nivel_combustible_pct,
        "io_all": io_all,
    }
    return registro, pos


# ══════════════════════════════════════════════════════════════════
#  SERVIDOR TCP
# ══════════════════════════════════════════════════════════════════
def handle_device(conn, addr):
    imei = None
    buffer = b""
    try:
        while True:
            data = conn.recv(4096)
            if not data:
                break

            if imei is None:
                imei = data[2:].decode(errors="ignore")
                conn.sendall(b'\x01')  # ACK del handshake IMEI
                continue

            buffer += data

            # Un frame completo necesita: preamble(4) + data_field_length(4) + payload + crc(4)
            while len(buffer) >= 8:
                data_field_length = struct.unpack(">I", buffer[4:8])[0]
                frame_total_len = 8 + data_field_length + 4
                if len(buffer) < frame_total_len:
                    break  # falta que llegue el resto del frame, esperar siguiente recv()

                frame = buffer[:frame_total_len]
                buffer = buffer[frame_total_len:]

                eco = imei_a_eco(imei)
                if not eco:
                    print(f"[WARN] IMEI {imei} sin mapear en maquinas.imei — frame descartado")
                    conn.sendall((0).to_bytes(4, 'big'))
                    continue

                try:
                    registros = parse_codec8e(frame)
                except ValueError as e:
                    print(f"[ERROR] Frame invalido de {imei}: {e}")
                    conn.sendall((0).to_bytes(4, 'big'))
                    continue

                maquina = database.query("SELECT * FROM maquinas WHERE eco=%s", (eco,), one=True) or {}
                for r in registros:
                    procesar_registro(eco, maquina, r)

                conn.sendall(len(registros).to_bytes(4, 'big'))
    except Exception as e:
        print(f"[ERROR] {addr}: {e}")
    finally:
        conn.close()


def main():
    migrar_esquema()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('0.0.0.0', 5027))
    srv.listen(20)
    print("Listener FMC650 escuchando en puerto 5027...")
    while True:
        conn, addr = srv.accept()
        threading.Thread(target=handle_device, args=(conn, addr), daemon=True).start()


if __name__ == '__main__':
    main()
