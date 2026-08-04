"""
database.py — Conexión y consultas MySQL/MariaDB
GRUPO ESMA — Plataforma de Telemetría
Estructura tipo Procore: Inicio · Reportes 360 · Documentos · Equipos · etc.
"""
import mysql.connector
from datetime import datetime, timedelta

DB_CONFIG = {
    "host":       "localhost",
    "port":       3306,
    "database":   "esma_telemetria",
    "user":       "root",
    "password":   "",
    "charset":    "utf8mb4",
    "autocommit": True,
}


def get_conn():
    return mysql.connector.connect(**DB_CONFIG)

def query(sql, params=None, one=False):
    c = get_conn()
    cur = c.cursor(dictionary=True, buffered=True)
    try:
        cur.execute(sql, params or ())
        return cur.fetchone() if one else cur.fetchall()
    finally:
        cur.close(); c.close()

def execute(sql, params=None):
    c = get_conn()
    cur = c.cursor(buffered=True)
    try:
        cur.execute(sql, params or ())
        c.commit()
        return cur.lastrowid
    finally:
        cur.close(); c.close()

def execute_ddl(sql):
    """Para CREATE TABLE, ALTER TABLE, etc. Consume resultados pendientes."""
    c = get_conn()
    cur = c.cursor(buffered=True)
    try:
        cur.execute(sql)
        # Consumir cualquier resultado pendiente (DDL puede generarlos)
        try:
            cur.fetchall()
        except Exception:
            pass
        c.commit()
    finally:
        cur.close(); c.close()

# ══════════════════════════════════════════════════════════════════
#  LÓGICA DE AUDITORÍA DE COMBUSTIBLE (semáforo de fraude)
#  Compara litros CARGADOS (reporte manual) vs CONSUMIDOS (telemetría)
# ══════════════════════════════════════════════════════════════════
def calcular_semaforo(litros_cargados, litros_telemetria):
    """Devuelve (faltantes, desviacion_pct, semaforo).
    faltantes = cargados - telemetria  (positivo => sobran/faltan litros sin justificar)
    Umbrales sobre |desviacion| respecto a lo cargado."""
    lc = float(litros_cargados or 0)
    lt = float(litros_telemetria or 0)
    faltantes = round(lc - lt, 2)
    base = lc if lc > 0 else lt
    desv = round((faltantes / base) * 100, 2) if base > 0 else 0.0
    a = abs(desv)
    if a <= 5:    semaforo = "OK"
    elif a <= 12: semaforo = "Revisar"
    elif a <= 20: semaforo = "Alerta"
    else:         semaforo = "Fraude Probable"
    return faltantes, desv, semaforo

# ══════════════════════════════════════════════════════════════════
#  CÁLCULO DE NÚMERO DE SEMANA (ciclo anual de 52 semanas)
#  Semana 1 inicia el lunes 29 de diciembre de 2025.
#  Cada 52 semanas (364 días) se reinicia a semana 1.
# ══════════════════════════════════════════════════════════════════
_LUNES_SEMANA1 = datetime(2025, 12, 29)

def calcular_semana_combustible(fecha):
    """Calcula el número de semana (1-52) a partir de una fecha.
    Semana 1 = lunes 29/dic/2025. Se reinicia cada 52 semanas."""
    try:
        if fecha is None:
            return None
        if isinstance(fecha, str):
            # Soporta formatos comunes
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
                try:
                    fecha = datetime.strptime(fecha, fmt)
                    break
                except ValueError:
                    continue
            else:
                return None
        if not isinstance(fecha, datetime):
            # Si es date sin hora, convertir
            fecha = datetime(fecha.year, fecha.month, fecha.day)
        # Obtener el lunes de la semana de la fecha
        dias_desde_lunes = fecha.weekday()
        lunes_de_fecha = (fecha - timedelta(days=dias_desde_lunes)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        # Diferencia en semanas desde el lunes base
        diferencia_dias = (lunes_de_fecha - _LUNES_SEMANA1).days
        semana_absoluta = diferencia_dias // 7 + 1
        # Reiniciar cada 52 semanas (ciclo anual)
        semana = ((semana_absoluta - 1) % 52) + 1
        return semana
    except Exception:
        return None

# ── USUARIOS ─────────────────────────────────────────────────────
def _init_columna_foto_maquina():
    """Migración: agrega maquinas.foto y maquinas.capacidad_litros si no existen."""
    try:
        execute_ddl("ALTER TABLE maquinas ADD COLUMN foto VARCHAR(255) DEFAULT NULL")
    except Exception:
        pass
    try:
        execute_ddl("ALTER TABLE maquinas ADD COLUMN capacidad_litros DECIMAL(8,2) DEFAULT NULL")
    except Exception:
        pass

def _init_columnas_obra_asignada():
    """Migración: agrega usuarios.id_obra_asignada, obras.archivada y obras.link_drive si no existen."""
    try:
        execute_ddl("ALTER TABLE usuarios ADD COLUMN id_obra_asignada INT DEFAULT NULL")
    except Exception:
        pass
    try:
        execute_ddl("ALTER TABLE obras ADD COLUMN archivada TINYINT(1) NOT NULL DEFAULT 0")
    except Exception:
        pass
    try:
        execute_ddl("ALTER TABLE obras ADD COLUMN link_drive VARCHAR(500) DEFAULT NULL")
    except Exception:
        pass

def _init_columna_foto_escaneo():
    """Migración: agrega escaneos_qr.foto_evidencia si no existe."""
    try:
        execute_ddl("ALTER TABLE escaneos_qr ADD COLUMN foto_evidencia VARCHAR(255) DEFAULT NULL")
    except Exception:
        pass

def _init_columna_tipo_combustible():
    """Migración: agrega reportes_combustible.tipo_combustible y campos extendidos si no existen."""
    columnas = [
        ("tipo_combustible", "VARCHAR(20) NOT NULL DEFAULT 'diesel'"),
        ("costo_total", "DECIMAL(12,2) DEFAULT NULL"),
        ("horometro_inicial", "DECIMAL(10,2) DEFAULT NULL"),
        ("horometro_final", "DECIMAL(10,2) DEFAULT NULL"),
        ("costo_por_litro", "DECIMAL(10,2) DEFAULT NULL"),
        ("lt_por_hr", "DECIMAL(10,2) DEFAULT NULL"),
        ("costo_por_hr", "DECIMAL(10,2) DEFAULT NULL"),
        ("frente_trabajo", "VARCHAR(120) DEFAULT NULL"),
        ("actividad", "VARCHAR(120) DEFAULT NULL"),
        ("origen_carga", "VARCHAR(120) DEFAULT NULL"),
        ("responsable", "VARCHAR(120) DEFAULT NULL"),
        ("folio_ticket", "VARCHAR(60) DEFAULT NULL"),
        ("odometro_inicial", "DECIMAL(10,2) DEFAULT NULL"),
        ("odometro_final", "DECIMAL(10,2) DEFAULT NULL"),
        ("km_recorridos", "DECIMAL(10,2) DEFAULT NULL"),
        ("km_por_litro", "DECIMAL(10,3) DEFAULT NULL"),
        ("costo_por_km", "DECIMAL(10,2) DEFAULT NULL"),
        ("destino", "VARCHAR(120) DEFAULT NULL"),
    ]
    for col, tipo in columnas:
        try:
            execute_ddl(f"ALTER TABLE reportes_combustible ADD COLUMN {col} {tipo}")
        except Exception:
            pass


def _init_columnas_remisiones_extra():
    """Migración: agrega campos extra a planta_remisiones si no existen."""
    columnas_rem = [
        ("peso_bruto_envio", "DECIMAL(8,2) DEFAULT NULL"),
        ("tara_envio", "DECIMAL(8,2) DEFAULT NULL"),
        ("precio_tonelada", "DECIMAL(12,2) DEFAULT NULL"),
    ]
    for col, tipo in columnas_rem:
        try:
            execute_ddl(f"ALTER TABLE planta_remisiones ADD COLUMN {col} {tipo}")
        except Exception:
            pass

def get_usuario_by_email(email):
    return query("""SELECT u.*, ob.nombre AS obra_asignada_nombre
                     FROM usuarios u LEFT JOIN obras ob ON ob.id=u.id_obra_asignada
                     WHERE u.email=%s AND u.activo=1""", (email,), one=True)

def get_usuario_by_id(uid):
    return query("""SELECT u.*, ob.nombre AS obra_asignada_nombre
                     FROM usuarios u LEFT JOIN obras ob ON ob.id=u.id_obra_asignada
                     WHERE u.id=%s""", (uid,), one=True)

def get_usuarios():
    return query("""SELECT u.id,u.nombre,u.email,u.rol,u.activo,u.creado_en,
                            u.id_obra_asignada, ob.nombre AS obra_asignada_nombre
                     FROM usuarios u LEFT JOIN obras ob ON ob.id=u.id_obra_asignada
                     ORDER BY u.nombre""")

def crear_usuario(nombre, email, password_hash, rol, id_obra_asignada=None):
    return execute("""INSERT INTO usuarios (nombre,email,password,rol,id_obra_asignada)
                       VALUES (%s,%s,%s,%s,%s)""",
                   (nombre, email, password_hash, rol, id_obra_asignada))

def actualizar_usuario(uid, nombre, email, rol, activo, id_obra_asignada=None):
    execute("""UPDATE usuarios SET nombre=%s,email=%s,rol=%s,activo=%s,id_obra_asignada=%s
               WHERE id=%s""",
            (nombre, email, rol, activo, id_obra_asignada, uid))

def cambiar_password(uid, password_hash):
    execute("UPDATE usuarios SET password=%s WHERE id=%s", (password_hash, uid))

# ── DASHBOARD KPIs ────────────────────────────────────────────────
# ── DASHBOARD KPIs ────────────────────────────────────────────────
def get_kpis():
    return query("""
        SELECT
            (SELECT COUNT(*) FROM maquinas)                              AS total_flota,
            (SELECT COUNT(DISTINCT codigo_eco) FROM estado)              AS con_telemetria,
            (SELECT COUNT(*) FROM horas_diarias WHERE fecha=CURDATE())   AS activos_hoy,
            (SELECT COUNT(*) FROM obras WHERE estado='activa')           AS obras_activas,
            COALESCE((SELECT SUM(litros_consumidos) FROM utilizacion
                      WHERE fecha=CURDATE()),0)                          AS litros_hoy,
            COALESCE((SELECT SUM(horas_trabajadas) FROM horas_diarias
                      WHERE fecha=CURDATE()),0)                          AS horas_hoy,
            (SELECT COUNT(*) FROM reportes_combustible
              WHERE semaforo IN ('Alerta','Fraude Probable') AND justificado=0
                AND fecha >= CURDATE() - INTERVAL 7 DAY)                 AS alertas_combustible,
            (SELECT COUNT(*) FROM incidentes WHERE estado<>'cerrado')    AS incidentes_abiertos
    """, one=True)

# ── TELEMETRÍA ────────────────────────────────────────────────────
def get_estado_equipos():
    """Estado actual de cada equipo = el registro más reciente en `estado`."""
    return query("""
        SELECT e.*, m.clasificacion, m.anio, m.id_obra,
               h.horas_trabajadas, h.horas_motor_conectado, h.horas_ralenti,
               u.litros_consumidos, u.litros_hora, u.ralenti_porcentaje,
               ob.nombre AS obra_nombre
        FROM estado e
        INNER JOIN (
            SELECT codigo_eco, MAX(fecha_ultima_actualizacion) AS ultima
            FROM estado GROUP BY codigo_eco
        ) ult ON ult.codigo_eco = e.codigo_eco
              AND ult.ultima    = e.fecha_ultima_actualizacion
        LEFT JOIN maquinas m  ON m.eco = e.codigo_eco
        LEFT JOIN horas_diarias h ON h.codigo_eco = e.codigo_eco AND h.fecha = CURDATE()
        LEFT JOIN utilizacion u   ON u.codigo_eco = e.codigo_eco AND u.fecha = CURDATE()
        LEFT JOIN obras ob ON ob.id = m.id_obra
        ORDER BY e.codigo_eco
    """)

def get_maquinas_mapa():
    """Última posición GPS de cada equipo para el mapa."""
    return query("""
        SELECT e.codigo_eco, e.serie, e.nombre_equipo, e.marca, e.modelo,
               e.latitud, e.longitud, e.nivel_combustible,
               e.horas_totales_horometro, e.fecha_ultima_actualizacion,
               m.clasificacion, m.eco AS maquina_eco, ob.nombre AS obra_nombre
        FROM estado e
        INNER JOIN (
            SELECT codigo_eco, MAX(fecha_ultima_actualizacion) AS ultima
            FROM estado GROUP BY codigo_eco
        ) ult ON ult.codigo_eco = e.codigo_eco
              AND ult.ultima    = e.fecha_ultima_actualizacion
        LEFT JOIN maquinas m ON m.eco = e.codigo_eco
        LEFT JOIN obras ob   ON ob.id = m.id_obra
        ORDER BY e.codigo_eco
    """)

def get_consumo_semana():
    return query("""
        SELECT fecha, ROUND(SUM(litros_consumidos),2) AS litros_consumidos,
               ROUND(SUM(horas_maquina),2) AS horas_maquina
        FROM utilizacion WHERE fecha >= CURDATE() - INTERVAL 7 DAY
        GROUP BY fecha ORDER BY fecha
    """)

def get_horas_semana():
    return query("""
        SELECT fecha, ROUND(SUM(horas_trabajadas),2) AS horas_trabajadas,
               ROUND(SUM(horas_ralenti),2) AS horas_ralenti
        FROM horas_diarias WHERE fecha >= CURDATE() - INTERVAL 7 DAY
        GROUP BY fecha ORDER BY fecha
    """)

def get_top_consumo(limit=10):
    return query("""
        SELECT u.codigo_eco, m.nombre_equipo, m.marca, m.clasificacion,
               ROUND(SUM(u.litros_consumidos),1) AS total_litros,
               ROUND(AVG(u.litros_hora),2) AS promedio_lts_hora,
               ROUND(SUM(u.horas_maquina),1) AS total_horas
        FROM utilizacion u
        LEFT JOIN maquinas m ON m.eco=u.codigo_eco
        WHERE u.fecha >= CURDATE() - INTERVAL 7 DAY
        GROUP BY u.codigo_eco, m.nombre_equipo, m.marca, m.clasificacion
        ORDER BY total_litros DESC LIMIT %s
    """, (limit,))

def insertar_estado(d):
    """Inserta una nueva lectura de telemetría en estado.
    Cada llamada crea una fila nueva — el historial completo queda en esta tabla.
    Si capacidad_litros no viene en d, la toma automáticamente de la tabla maquinas."""
    if not d.get("capacidad_litros"):
        maq = query("SELECT capacidad_litros FROM maquinas WHERE eco=%s", (d.get("eco"),), one=True)
        if maq and maq.get("capacidad_litros"):
            d["capacidad_litros"] = maq["capacidad_litros"]
    execute("""
        INSERT INTO estado
            (codigo_eco, serie, nombre_equipo, marca, modelo,
             fecha_ultima_actualizacion, latitud, longitud,
             horas_totales_horometro, nivel_combustible, capacidad_litros)
        VALUES (%(eco)s, %(serie)s, %(nombre_equipo)s, %(marca)s, %(modelo)s,
                %(fecha)s, %(lat)s, %(lon)s, %(horometro)s,
                %(nivel_combustible)s, %(capacidad_litros)s)
    """, d)

# Alias para no romper código viejo que llame a upsert_estado
upsert_estado = insertar_estado

def upsert_horas(d):
    execute("""
        INSERT INTO horas_diarias
            (codigo_eco,serie,nombre_equipo,marca,modelo,fecha,
             horas_trabajadas,horas_motor_conectado,horas_ralenti,motor_desconectado)
        VALUES (%(eco)s,%(serie)s,%(nombre_equipo)s,%(marca)s,%(modelo)s,%(fecha)s,
                %(horas_trabajadas)s,%(horas_motor_conectado)s,%(horas_ralenti)s,%(motor_desconectado)s)
        ON DUPLICATE KEY UPDATE
            horas_trabajadas=VALUES(horas_trabajadas),
            horas_motor_conectado=VALUES(horas_motor_conectado),
            horas_ralenti=VALUES(horas_ralenti),
            motor_desconectado=VALUES(motor_desconectado)
    """, d)

def upsert_utilizacion(d):
    d.setdefault("ralenti_porcentaje", None)
    execute("""
        INSERT INTO utilizacion
            (codigo_eco,serie,nombre_equipo,marca,modelo,fecha,
             litros_hora,litros_consumidos,horas_maquina,horas_ralenti,ralenti_porcentaje)
        VALUES (%(eco)s,%(serie)s,%(nombre_equipo)s,%(marca)s,%(modelo)s,%(fecha)s,
                %(litros_hora)s,%(litros_consumidos)s,%(horas_maquina)s,%(horas_ralenti)s,%(ralenti_porcentaje)s)
        ON DUPLICATE KEY UPDATE
            litros_hora=VALUES(litros_hora),
            litros_consumidos=VALUES(litros_consumidos),
            horas_maquina=VALUES(horas_maquina),
            horas_ralenti=VALUES(horas_ralenti),
            ralenti_porcentaje=VALUES(ralenti_porcentaje)
    """, d)

# ── MAQUINAS ──────────────────────────────────────────────────────


def get_clasificaciones():
    rows = query("SELECT DISTINCT clasificacion FROM maquinas WHERE clasificacion<>'' ORDER BY clasificacion")
    return [r["clasificacion"] for r in rows]

def maquina_existe(eco=None, serie=None, id_obra=None, excluir_eco=None):
    """Verifica si ya existe una máquina con el mismo ECO, serie o combinación ECO+obra.
    excluir_eco: ECO actual al editar (para no comparar consigo misma).
    Retorna dict con las claves duplicadas encontradas o None si no hay conflicto."""
    conflictos = []
    if eco:
        sql = "SELECT eco FROM maquinas WHERE eco=%s"
        params = [eco]
        if excluir_eco:
            sql += " AND eco<>%s"; params.append(excluir_eco)
        if query(sql, params):
            conflictos.append(f"El código ECO '{eco}' ya existe")
    if serie:
        sql = "SELECT eco FROM maquinas WHERE serie=%s AND serie<>''"
        params = [serie]
        if excluir_eco:
            sql += " AND eco<>%s"; params.append(excluir_eco)
        if query(sql, params):
            conflictos.append(f"El número de serie '{serie}' ya existe")
    return conflictos if conflictos else None

def get_maquinas(search=None, clasificacion=None):
    sql = """
        SELECT m.*, e.latitud, e.longitud, e.nivel_combustible,
               e.horas_totales_horometro, e.fecha_ultima_actualizacion,
               ob.nombre AS obra_nombre
        FROM maquinas m
        LEFT JOIN (
            SELECT e1.*
            FROM estado e1
            INNER JOIN (
                SELECT codigo_eco, MAX(fecha_ultima_actualizacion) AS ultima
                FROM estado GROUP BY codigo_eco
            ) ult ON ult.codigo_eco = e1.codigo_eco
                  AND ult.ultima    = e1.fecha_ultima_actualizacion
        ) e ON e.codigo_eco = m.eco
        LEFT JOIN obras ob ON ob.id=m.id_obra
        WHERE 1=1
    """
    params = []
    if search:
        sql += " AND (m.eco LIKE %s OR m.nombre_equipo LIKE %s OR m.marca LIKE %s OR m.serie LIKE %s)"
        params += [f"%{search}%"]*4
    if clasificacion:
        sql += " AND m.clasificacion=%s"; params.append(clasificacion)
    sql += " ORDER BY m.eco"
    return query(sql, params)

def get_maquina(eco):
    return query("""
        SELECT m.*, e.latitud, e.longitud, e.nivel_combustible,
               e.horas_totales_horometro, e.fecha_ultima_actualizacion,
               e.capacidad_litros AS cap_estado, ob.nombre AS obra_nombre
        FROM maquinas m
        LEFT JOIN (
            SELECT e1.*
            FROM estado e1
            INNER JOIN (
                SELECT codigo_eco, MAX(fecha_ultima_actualizacion) AS ultima
                FROM estado GROUP BY codigo_eco
            ) ult ON ult.codigo_eco = e1.codigo_eco
                  AND ult.ultima    = e1.fecha_ultima_actualizacion
        ) e ON e.codigo_eco = m.eco
        LEFT JOIN obras ob ON ob.id=m.id_obra
        WHERE m.eco=%s
    """, (eco,), one=True)

def crear_maquina(d):
    return execute("""
        INSERT INTO maquinas
            (eco,proveedor,nombre_equipo,marca,modelo,serie,
             anio,clasificacion,cantidad,id_obra,ubicacion,link_ubicacion,foto,capacidad_litros)
        VALUES (%(eco)s,%(proveedor)s,%(nombre_equipo)s,%(marca)s,%(modelo)s,
                %(serie)s,%(anio)s,%(clasificacion)s,%(cantidad)s,
                %(id_obra)s,%(ubicacion)s,%(link_ubicacion)s,%(foto)s,%(capacidad_litros)s)
    """, d)

def actualizar_maquina(d):
    execute("""
        UPDATE maquinas SET proveedor=%(proveedor)s, nombre_equipo=%(nombre_equipo)s,
               marca=%(marca)s, modelo=%(modelo)s, serie=%(serie)s,
               anio=%(anio)s, clasificacion=%(clasificacion)s, cantidad=%(cantidad)s,
               id_obra=%(id_obra)s, ubicacion=%(ubicacion)s, link_ubicacion=%(link_ubicacion)s,
               foto=%(foto)s, capacidad_litros=%(capacidad_litros)s
        WHERE eco=%(eco)s
    """, d)

def get_horas_maquina(eco, dias=30):
    return query("""
        SELECT fecha, horas_trabajadas, horas_motor_conectado, horas_ralenti, motor_desconectado
        FROM horas_diarias WHERE codigo_eco=%s AND fecha >= CURDATE() - INTERVAL %s DAY
        ORDER BY fecha
    """, (eco, dias))

def get_horas_maquina_rango(eco, fi, ff):
    return query("""
        SELECT fecha, horas_trabajadas, horas_motor_conectado, horas_ralenti, motor_desconectado
        FROM horas_diarias WHERE codigo_eco=%s AND fecha BETWEEN %s AND %s
        ORDER BY fecha
    """, (eco, fi, ff))

def get_consumo_maquina(eco, dias=30):
    return query("""
        SELECT fecha, litros_consumidos, litros_hora, horas_maquina, horas_ralenti
        FROM utilizacion WHERE codigo_eco=%s AND fecha >= CURDATE() - INTERVAL %s DAY
        ORDER BY fecha
    """, (eco, dias))

def get_consumo_maquina_rango(eco, fi, ff):
    return query("""
        SELECT fecha, litros_consumidos, litros_hora, horas_maquina, horas_ralenti
        FROM utilizacion WHERE codigo_eco=%s AND fecha BETWEEN %s AND %s
        ORDER BY fecha
    """, (eco, fi, ff))

def get_reportes_maquina(eco, dias=30):
    return query("""
        SELECT fecha, litros_cargados, litros_telemetria, litros_faltantes,
               desviacion_pct, semaforo
        FROM reportes_combustible
        WHERE codigo_eco=%s AND fecha >= CURDATE() - INTERVAL %s DAY
        ORDER BY fecha
    """, (eco, dias))

def get_reportes_maquina_rango(eco, fi, ff):
    return query("""
        SELECT fecha, litros_cargados, litros_telemetria, litros_faltantes,
               desviacion_pct, semaforo
        FROM reportes_combustible
        WHERE codigo_eco=%s AND fecha BETWEEN %s AND %s
        ORDER BY fecha
    """, (eco, fi, ff))

def get_cargas_detectadas(eco, fi=None, ff=None):
    """Detecta cargas de combustible desde la tabla estado:
    cuando nivel_combustible sube entre dos lecturas consecutivas.
    Usa LAG() para comparar con la lectura anterior del mismo equipo."""
    if fi and ff:
        sql = """
            SELECT fecha, ROUND(SUM(litros_carga), 1) AS litros_cargados
            FROM (
                SELECT DATE(e.fecha_ultima_actualizacion) AS fecha,
                       (e.nivel_combustible - LAG(e.nivel_combustible) 
                        OVER (ORDER BY e.fecha_ultima_actualizacion))
                         / 100 * e.capacidad_litros AS litros_carga
                FROM estado e
                WHERE e.codigo_eco = %s
                  AND e.fecha_ultima_actualizacion BETWEEN %s AND %s
                  AND e.capacidad_litros > 0
                  AND e.nivel_combustible IS NOT NULL
            ) sub
            WHERE sub.litros_carga >= 5
            GROUP BY sub.fecha
            ORDER BY sub.fecha
        """
        return query(sql, (eco, fi, ff))
    else:
        sql = """
            SELECT fecha, ROUND(SUM(litros_carga), 1) AS litros_cargados
            FROM (
                SELECT DATE(e.fecha_ultima_actualizacion) AS fecha,
                       (e.nivel_combustible - LAG(e.nivel_combustible) 
                        OVER (ORDER BY e.fecha_ultima_actualizacion))
                         / 100 * e.capacidad_litros AS litros_carga
                FROM estado e
                WHERE e.codigo_eco = %s
                  AND e.fecha_ultima_actualizacion >= CURDATE() - INTERVAL 30 DAY
                  AND e.capacidad_litros > 0
                  AND e.nivel_combustible IS NOT NULL
            ) sub
            WHERE sub.litros_carga >= 5
            GROUP BY sub.fecha
            ORDER BY sub.fecha
        """
        return query(sql, (eco,))

# ── OBRAS ─────────────────────────────────────────────────────────
def get_obras(archivada=0):
    """archivada=0 -> obras vigentes (en ejecución); archivada=1 -> archivo histórico;
    archivada=None -> todas."""
    sql = """
        SELECT ob.*, COUNT(m.id) AS total_equipos
        FROM obras ob LEFT JOIN maquinas m ON m.id_obra=ob.id
    """
    p = []
    if archivada is not None:
        sql += " WHERE ob.archivada=%s"
        p.append(1 if archivada else 0)
    sql += " GROUP BY ob.id ORDER BY ob.estado, ob.nombre"
    return query(sql, p)

def get_obra(oid):
    return query("SELECT * FROM obras WHERE id=%s", (oid,), one=True)

def archivar_obra(oid):
    execute("UPDATE obras SET archivada=1 WHERE id=%s", (oid,))

def desarchivar_obra(oid):
    execute("UPDATE obras SET archivada=0 WHERE id=%s", (oid,))

def crear_obra(d):
    return execute("""
        INSERT INTO obras (nombre,cliente,ubicacion,fecha_inicio,fecha_fin,estado)
        VALUES (%(nombre)s,%(cliente)s,%(ubicacion)s,%(fecha_inicio)s,%(fecha_fin)s,%(estado)s)
    """, d)

def actualizar_obra(d):
    execute("""
        UPDATE obras SET nombre=%(nombre)s, cliente=%(cliente)s, ubicacion=%(ubicacion)s,
               fecha_inicio=%(fecha_inicio)s, fecha_fin=%(fecha_fin)s, estado=%(estado)s,
               link_drive=%(link_drive)s
        WHERE id=%(id)s
    """, d)

def get_equipos_obra(oid):
    return query("""
        SELECT m.eco, m.nombre_equipo, m.marca, m.modelo,
               e.nivel_combustible, e.horas_totales_horometro, h.horas_trabajadas
        FROM maquinas m
        LEFT JOIN (
            SELECT e1.*
            FROM estado e1
            INNER JOIN (
                SELECT codigo_eco, MAX(fecha_ultima_actualizacion) AS ultima
                FROM estado GROUP BY codigo_eco
            ) ult ON ult.codigo_eco = e1.codigo_eco
                  AND ult.ultima    = e1.fecha_ultima_actualizacion
        ) e ON e.codigo_eco = m.eco
        LEFT JOIN horas_diarias h ON h.codigo_eco=m.eco AND h.fecha=CURDATE()
        WHERE m.id_obra=%s ORDER BY m.eco
    """, (oid,))



def get_maquinas_para_asignar(id_obra_actual):
    """Obtiene las máquinas que están libres o en otra obra distinta a la actual."""
    return query("""
        SELECT eco, nombre_equipo, serie, marca 
        FROM maquinas 
        WHERE id_obra IS NULL OR id_obra != %s 
        ORDER BY eco
    """, (id_obra_actual,))


def actualizar_obra_maquina(eco, id_obra):
    """Actualiza a qué obra pertenece una máquina (id_obra puede ser None para liberarla).
    Registra automáticamente en el historial de obras del equipo."""
    # Obtener obra anterior para cerrar el registro en historial
    maq = query("SELECT id_obra FROM maquinas WHERE eco=%s", (eco,), one=True)
    obra_anterior = maq["id_obra"] if maq else None

    # Si la obra anterior es diferente, cerrar registro anterior y abrir uno nuevo
    if obra_anterior != id_obra:
        # Cerrar el registro abierto (fecha_salida = hoy)
        if obra_anterior:
            execute("""UPDATE historial_obras_equipo SET fecha_salida=CURDATE()
                       WHERE eco=%s AND id_obra=%s AND fecha_salida IS NULL""",
                    (eco, obra_anterior))
        # Abrir nuevo registro si se asigna a una obra (no si se libera)
        if id_obra:
            execute("""INSERT INTO historial_obras_equipo (eco, id_obra, fecha_entrada)
                       VALUES (%s, %s, CURDATE())""", (eco, id_obra))

    execute("UPDATE maquinas SET id_obra=%s WHERE eco=%s", (id_obra, eco))


# ══════════════════════════════════════════════════════════════════
#  HISTORIAL DE OBRAS POR EQUIPO
# ══════════════════════════════════════════════════════════════════

def _init_tabla_historial_obras():
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS historial_obras_equipo (
            id            INT AUTO_INCREMENT PRIMARY KEY,
            eco           VARCHAR(30) NOT NULL,
            id_obra       INT NOT NULL,
            fecha_entrada DATE NOT NULL,
            fecha_salida  DATE DEFAULT NULL,
            creado_en     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_eco (eco),
            INDEX idx_obra (id_obra)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

def get_historial_obras_equipo(eco):
    """Devuelve el historial de obras de un equipo, más reciente primero."""
    return query("""
        SELECT h.*, ob.nombre AS obra_nombre
        FROM historial_obras_equipo h
        LEFT JOIN obras ob ON ob.id = h.id_obra
        WHERE h.eco=%s
        ORDER BY h.fecha_entrada DESC
    """, (eco,))


# ══════════════════════════════════════════════════════════════════
#  EQUIPO DEL PROYECTO (directorio de personas asignadas a la obra)
# ══════════════════════════════════════════════════════════════════

ROLES_EQUIPO_PROYECTO = [
    "Operación de Proyectos",
    "Superintendente de Obra",
    "Residente de Obra",
    "Administrador de Obra",
    "Auxiliar",
    "Residente Técnico",
    "Residente de Seguridad",
    "Área de Auditoría",
    "Área de Tesorería",
    "Área de Licitaciones",
    "Área de Compras",
    "Control Interno",
    "Otro",
]

def _init_tabla_equipo_proyecto():
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS equipo_proyecto (
            id         INT AUTO_INCREMENT PRIMARY KEY,
            id_obra    INT NOT NULL,
            rol        VARCHAR(80) NOT NULL,
            nombre     VARCHAR(200) NOT NULL,
            correo     VARCHAR(120) DEFAULT NULL,
            oficina    VARCHAR(40) DEFAULT NULL,
            movil      VARCHAR(40) DEFAULT NULL,
            creado_en  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_obra (id_obra)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

def get_equipo_proyecto(id_obra):
    return query("SELECT * FROM equipo_proyecto WHERE id_obra=%s ORDER BY rol, nombre", (id_obra,))

def crear_miembro_equipo(id_obra, rol, nombre, correo, oficina, movil):
    return execute("""
        INSERT INTO equipo_proyecto (id_obra, rol, nombre, correo, oficina, movil)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (id_obra, rol, nombre, correo or None, oficina or None, movil or None))

def eliminar_miembro_equipo(mid):
    execute("DELETE FROM equipo_proyecto WHERE id=%s", (mid,))



# ══════════════════════════════════════════════════════════════════
#  REPORTES 360 · COMBUSTIBLE  (auditoría cargado vs telemetría)
# ══════════════════════════════════════════════════════════════════
def get_reportes_combustible(fi=None, ff=None, semaforo=None, obra=None, eco=None):
    """Trae reportes de combustible. litros_telemetria se recalcula desde tabla estado
    comparando nivel del día vs día anterior para detectar la carga."""
    sql = """
        SELECT r.*, ob.nombre AS obra_nombre
        FROM reportes_combustible r
        LEFT JOIN obras ob ON ob.id=r.id_obra
        WHERE 1=1
    """
    p = []
    if fi: sql += " AND r.fecha >= %s"; p.append(fi)
    if ff: sql += " AND r.fecha <= %s"; p.append(ff)
    if semaforo: sql += " AND r.semaforo=%s"; p.append(semaforo)
    if obra: sql += " AND r.id_obra=%s"; p.append(obra)
    if eco: sql += " AND r.codigo_eco=%s"; p.append(eco)
    sql += " ORDER BY r.fecha DESC, FIELD(r.semaforo,'Fraude Probable','Alerta','Revisar','OK'), r.codigo_eco"
    filas = query(sql, p)

    # Recalcular telemetría: buscar subida de nivel en estado
    for fila in filas:
        eco_r = fila.get("codigo_eco")
        fecha_r = str(fila.get("fecha"))
        # Buscar nivel máximo del día (después de carga) y nivel del registro anterior
        niveles_dia = query("""
            SELECT nivel_combustible, capacidad_litros, fecha_ultima_actualizacion
            FROM estado
            WHERE codigo_eco=%s AND DATE(fecha_ultima_actualizacion)=%s
              AND nivel_combustible IS NOT NULL
            ORDER BY fecha_ultima_actualizacion ASC
        """, (eco_r, fecha_r))

        if niveles_dia and len(niveles_dia) >= 2:
            # Múltiples registros: buscar la subida más grande (= la carga)
            max_subida = 0
            cap = None
            for i in range(1, len(niveles_dia)):
                subida = float(niveles_dia[i]["nivel_combustible"]) - float(niveles_dia[i-1]["nivel_combustible"])
                if subida > max_subida:
                    max_subida = subida
                    cap = float(niveles_dia[i]["capacidad_litros"]) if niveles_dia[i].get("capacidad_litros") else None
            if max_subida > 0:
                if cap and cap > 10:
                    fila["litros_telemetria"] = round(max_subida / 100 * cap, 1)
                else:
                    fila["litros_telemetria"] = round(max_subida, 1)
        elif niveles_dia and len(niveles_dia) == 1:
            # Solo 1 registro del día: comparar con el último registro anterior (cualquier fecha)
            nivel_hoy = float(niveles_dia[0]["nivel_combustible"])
            cap = float(niveles_dia[0]["capacidad_litros"]) if niveles_dia[0].get("capacidad_litros") and float(niveles_dia[0].get("capacidad_litros") or 0) > 10 else None
            anterior = query("""
                SELECT nivel_combustible
                FROM estado
                WHERE codigo_eco=%s AND fecha_ultima_actualizacion < %s
                  AND nivel_combustible IS NOT NULL
                ORDER BY fecha_ultima_actualizacion DESC LIMIT 1
            """, (eco_r, niveles_dia[0]["fecha_ultima_actualizacion"]), one=True)
            if anterior:
                nivel_ant = float(anterior["nivel_combustible"])
                subida = nivel_hoy - nivel_ant
                if subida > 0:
                    if cap:
                        fila["litros_telemetria"] = round(subida / 100 * cap, 1)
                    else:
                        fila["litros_telemetria"] = round(subida, 1)
            else:
                # No hay registro anterior: usar nivel actual como referencia
                if cap:
                    fila["litros_telemetria"] = round(nivel_hoy / 100 * cap, 1)
                else:
                    fila["litros_telemetria"] = round(nivel_hoy, 1)

        # Recalcular faltantes y desviación
        litros_tel = float(fila.get("litros_telemetria") or 0)
        cargados = float(fila.get("litros_cargados") or 0)
        if litros_tel > 0:
            fila["litros_faltantes"] = round(cargados - litros_tel, 1)
            fila["desviacion_pct"] = round((cargados - litros_tel) / cargados * 100, 1) if cargados > 0 else 0

    return filas

def get_combustible_kpis(fi, ff):
    """KPIs de combustible. total_telemetria se calcula desde tabla estado
    (nivel_combustible/100*capacidad_litros) para reflejar dato real del sensor."""
    base = query("""
        SELECT
            COUNT(*) AS total_reportes,
            COALESCE(SUM(litros_cargados),0)   AS total_cargados,
            SUM(semaforo='OK')               AS n_ok,
            SUM(semaforo='Revisar')          AS n_revisar,
            SUM(semaforo='Alerta')           AS n_alerta,
            SUM(semaforo='Fraude Probable')  AS n_fraude
        FROM reportes_combustible
        WHERE fecha BETWEEN %s AND %s
    """, (fi, ff), one=True)
    # Telemetría desde estado: suma del último nivel de cada equipo por día
    tel = query("""
        SELECT COALESCE(ROUND(SUM(litros_tel), 1), 0) AS total_telemetria
        FROM (
            SELECT ult.codigo_eco, ult.dia,
                   CASE
                     WHEN e.capacidad_litros IS NOT NULL AND e.capacidad_litros > 0
                       THEN e.nivel_combustible / 100 * e.capacidad_litros
                     ELSE e.nivel_combustible
                   END AS litros_tel
            FROM (
                SELECT codigo_eco, DATE(fecha_ultima_actualizacion) AS dia, MAX(id) AS max_id
                FROM estado
                WHERE fecha_ultima_actualizacion BETWEEN %s AND %s
                  AND nivel_combustible IS NOT NULL
                GROUP BY codigo_eco, DATE(fecha_ultima_actualizacion)
            ) ult
            INNER JOIN estado e ON e.id = ult.max_id
        ) calc
    """, (fi, ff + " 23:59:59" if len(ff) == 10 else ff), one=True)
    total_tel = float((tel or {}).get("total_telemetria") or 0)
    total_carg = float(base.get("total_cargados") or 0)
    base["total_telemetria"] = total_tel
    base["total_faltantes"] = round(total_carg - total_tel, 1) if total_tel > 0 else total_carg
    return base

def get_combustible_por_obra(fi, ff):
    return query("""
        SELECT ob.nombre AS obra, COUNT(*) AS reportes,
               ROUND(SUM(r.litros_cargados),1)   AS cargados,
               ROUND(SUM(r.litros_telemetria),1) AS telemetria,
               ROUND(SUM(r.litros_faltantes),1)  AS faltantes,
               SUM(r.semaforo IN ('Alerta','Fraude Probable')) AS criticos
        FROM reportes_combustible r
        LEFT JOIN obras ob ON ob.id=r.id_obra
        WHERE r.fecha BETWEEN %s AND %s
        GROUP BY r.id_obra, ob.nombre
        ORDER BY faltantes DESC
    """, (fi, ff))

# ── RESUMEN COMBUSTIBLE POR OBRA (réplica de la hoja "Resumen" del Excel) ──
def get_resumen_combustible_obra(fi, ff):
    """
    Réplica de la hoja 'Resumen' del reporte de Excel:
      Tabla 1 (cargas):  Reporte Telemetría vs Reporte Obra por obra,
                          con Diferencia (telemetría - obra) y # de Equipos.
      Tabla 2 (consumo):  Consumo Telemetría vs Cargas Telemetría por obra,
                          con Diferencia (cargas - consumo).
    """
    cargas = query("""
        SELECT COALESCE(NULLIF(TRIM(ob.nombre),''), 'SIN OBRA') AS obra,
               ROUND(SUM(r.litros_telemetria),0) AS reporte_telemetria,
               ROUND(SUM(r.litros_cargados),0)   AS reporte_obra,
               COUNT(DISTINCT r.codigo_eco)       AS equipos
        FROM reportes_combustible r
        LEFT JOIN obras ob ON ob.id = r.id_obra
        WHERE r.fecha BETWEEN %s AND %s
        GROUP BY r.id_obra, ob.nombre
    """, (fi, ff))

    consumos = query("""
        SELECT COALESCE(NULLIF(TRIM(ob.nombre),''), 'SIN OBRA') AS obra,
               ROUND(SUM(u.litros_consumidos),0) AS consumo_telemetria
        FROM utilizacion u
        LEFT JOIN maquinas m ON m.eco = u.codigo_eco
        LEFT JOIN obras   ob ON ob.id = m.id_obra
        WHERE u.fecha BETWEEN %s AND %s
        GROUP BY m.id_obra, ob.nombre
    """, (fi, ff))

    mapa_consumo = {c["obra"]: float(c["consumo_telemetria"] or 0) for c in consumos}

    filas = []
    for c in cargas:
        obra       = c["obra"]
        tele       = float(c["reporte_telemetria"] or 0)
        obra_total = float(c["reporte_obra"] or 0)
        consumo    = mapa_consumo.pop(obra, 0.0)
        filas.append({
            "obra":                obra,
            "reporte_telemetria":  tele,
            "reporte_obra":        obra_total,
            "diferencia_carga":    round(tele - obra_total, 0),
            "equipos":             int(c["equipos"] or 0),
            "consumo_telemetria":  consumo,
            "cargas_telemetria":   tele,
            "diferencia_consumo":  round(tele - consumo, 0),
        })

    # Obras que solo tienen consumo registrado (sin reportes_combustible en el rango)
    for obra, consumo in mapa_consumo.items():
        filas.append({
            "obra":                obra,
            "reporte_telemetria":  0.0,
            "reporte_obra":        0.0,
            "diferencia_carga":    0.0,
            "equipos":             0,
            "consumo_telemetria":  consumo,
            "cargas_telemetria":   0.0,
            "diferencia_consumo":  round(0.0 - consumo, 0),
        })

    filas.sort(key=lambda f: f["reporte_telemetria"], reverse=True)
    return filas

# ── CARGAS DE TELEMETRÍA DETECTADAS (histórico real, semanal) ─────
def get_cargas_semanal_telemetria(semanas=8, id_obra=None):
    """
    Detecta cargas reales de combustible a partir del histórico de telemetría.
    Si id_obra se pasa, filtra solo los equipos de esa obra.
    """
    join_obra = "INNER JOIN maquinas m ON m.eco = e.codigo_eco" if id_obra else ""
    filtro_obra = "AND m.id_obra = %s" if id_obra else ""
    params = [semanas, id_obra] if id_obra else [semanas]
    return query(f"""
        WITH lecturas AS (
            SELECT e.codigo_eco, e.fecha_ultima_actualizacion AS fecha_hora,
                   e.nivel_combustible, e.capacidad_litros,
                   LAG(e.nivel_combustible) OVER (
                       PARTITION BY e.codigo_eco ORDER BY e.fecha_ultima_actualizacion
                   ) AS nivel_anterior
            FROM estado e
            {join_obra}
            WHERE e.fecha_ultima_actualizacion >= CURDATE() - INTERVAL %s WEEK
            {filtro_obra}
        ),
        cargas AS (
            SELECT fecha_hora,
                   (nivel_combustible - nivel_anterior) / 100 * capacidad_litros AS litros_carga
            FROM lecturas
            WHERE nivel_anterior IS NOT NULL
              AND (nivel_combustible - nivel_anterior) >= 3
        )
        SELECT YEARWEEK(fecha_hora, 3) AS semana_key,
               MIN(DATE(fecha_hora))   AS semana_inicio,
               ROUND(SUM(litros_carga), 0) AS litros_telemetria
        FROM cargas
        GROUP BY semana_key
        ORDER BY semana_key
    """, params)

def get_reporte_semanal(semanas=8, id_obra=None):
    """Suma de litros cargados (reporte manual/obra) agrupados por semana."""
    if id_obra:
        return query("""
            SELECT YEARWEEK(fecha, 3) AS semana_key,
                   MIN(fecha)         AS semana_inicio,
                   ROUND(SUM(litros_cargados), 0) AS litros_reporte
            FROM reportes_combustible
            WHERE fecha >= CURDATE() - INTERVAL %s WEEK AND id_obra=%s
            GROUP BY semana_key
            ORDER BY semana_key
        """, (semanas, id_obra))
    return query("""
        SELECT YEARWEEK(fecha, 3) AS semana_key,
               MIN(fecha)         AS semana_inicio,
               ROUND(SUM(litros_cargados), 0) AS litros_reporte
        FROM reportes_combustible
        WHERE fecha >= CURDATE() - INTERVAL %s WEEK
        GROUP BY semana_key
        ORDER BY semana_key
    """, (semanas,))

def get_cargas_vs_reporte_semanal(semanas=8, id_obra=None):
    """
    Combina, semana por semana:
      - litros_telemetria: cargas detectadas por subida de nivel en 'estado'
      - litros_reporte:    litros_cargados capturados manualmente (obra)
    """
    tele = get_cargas_semanal_telemetria(semanas, id_obra)
    rep  = get_reporte_semanal(semanas, id_obra)

    mapa_tele = {r["semana_key"]: r for r in tele}
    mapa_rep  = {r["semana_key"]: r for r in rep}
    claves = sorted(set(mapa_tele) | set(mapa_rep))

    filas = []
    for k in claves:
        base = mapa_tele.get(k) or mapa_rep.get(k)
        inicio = base["semana_inicio"]
        filas.append({
            "semana_key":         k,
            "semana_inicio":      inicio.strftime("%Y-%m-%d") if inicio else None,
            "semana_label":       ("Sem " + inicio.strftime("%d/%m")) if inicio else str(k),
            "litros_telemetria":  float(mapa_tele.get(k, {}).get("litros_telemetria") or 0),
            "litros_reporte":     float(mapa_rep.get(k, {}).get("litros_reporte") or 0),
        })
    return filas

def get_combustible_tendencia(fi, ff, obra=None, eco=None):
    """Tendencia diaria: Cargado desde reportes_combustible,
    Telemetría calculada desde tabla estado (nivel_combustible/100*capacidad_litros)."""
    # Cargado por día
    sql_carg = """
        SELECT fecha, ROUND(SUM(litros_cargados),1) AS cargados
        FROM reportes_combustible
        WHERE fecha BETWEEN %s AND %s
    """
    p_carg = [fi, ff]
    if obra:
        sql_carg += " AND id_obra=%s"
        p_carg.append(obra)
    if eco:
        sql_carg += " AND codigo_eco=%s"
        p_carg.append(eco)
    sql_carg += " GROUP BY fecha ORDER BY fecha"
    cargados = query(sql_carg, p_carg)

    # Telemetría por día: último nivel de cada equipo por día desde estado
    sql_tel = """
        SELECT DATE(e.fecha_ultima_actualizacion) AS fecha,
               ROUND(SUM(
                 CASE
                   WHEN e.capacidad_litros IS NOT NULL AND e.capacidad_litros > 0
                     THEN e.nivel_combustible / 100 * e.capacidad_litros
                   ELSE e.nivel_combustible
                 END
               ), 1) AS telemetria
        FROM (
            SELECT codigo_eco, DATE(fecha_ultima_actualizacion) AS dia,
                   MAX(id) AS max_id
            FROM estado
            WHERE fecha_ultima_actualizacion BETWEEN %s AND %s
              AND nivel_combustible IS NOT NULL
    """
    p_tel = [fi, ff + " 23:59:59" if len(ff) == 10 else ff]
    if eco:
        sql_tel += " AND codigo_eco=%s"
        p_tel.append(eco)
    if obra:
        sql_tel += " AND codigo_eco IN (SELECT eco FROM maquinas WHERE id_obra=%s)"
        p_tel.append(obra)
    sql_tel += """
            GROUP BY codigo_eco, DATE(fecha_ultima_actualizacion)
        ) ult
        INNER JOIN estado e ON e.id = ult.max_id
        GROUP BY DATE(e.fecha_ultima_actualizacion)
        ORDER BY fecha
    """
    telemetria_dia = query(sql_tel, p_tel)

    # Combinar en un solo resultado
    tel_map = {str(t["fecha"]): float(t["telemetria"] or 0) for t in telemetria_dia}
    resultado = []
    for row in cargados:
        fecha = str(row["fecha"])
        carg = float(row["cargados"] or 0)
        tel = tel_map.get(fecha, 0)
        falt = round(carg - tel, 1) if tel > 0 else 0
        resultado.append({
            "fecha": fecha,
            "cargados": carg,
            "telemetria": tel,
            "faltantes": falt
        })
    return resultado

def crear_reporte_combustible(d):
    """Inserta un reporte de combustible con todos los campos extendidos."""
    faltantes, desv, sem = calcular_semaforo(d.get("litros_cargados"), d.get("litros_telemetria"))
    d = dict(d)
    d["litros_faltantes"] = faltantes
    d["desviacion_pct"]   = desv
    d["semaforo"]         = sem
    d.setdefault("tipo_combustible", "diesel")
    # Campos opcionales con default None
    for campo in ("costo_total", "horometro_inicial", "horometro_final", "costo_por_litro",
                  "lt_por_hr", "costo_por_hr", "frente_trabajo", "actividad", "origen_carga",
                  "responsable", "folio_ticket", "odometro_inicial", "odometro_final",
                  "km_recorridos", "km_por_litro", "costo_por_km", "destino"):
        d.setdefault(campo, None)
    return execute("""
        INSERT INTO reportes_combustible
            (codigo_eco, nombre_equipo, marca, id_obra, fecha, semana, operador,
             litros_cargados, litros_telemetria, litros_faltantes, desviacion_pct,
             semaforo, horas_maquina, observaciones, registrado_por, tipo_combustible,
             costo_total, horometro_inicial, horometro_final, costo_por_litro,
             lt_por_hr, costo_por_hr, frente_trabajo, actividad, origen_carga,
             responsable, folio_ticket, odometro_inicial, odometro_final,
             km_recorridos, km_por_litro, costo_por_km, destino)
        VALUES (%(eco)s, %(nombre_equipo)s, %(marca)s, %(id_obra)s, %(fecha)s, %(semana)s, %(operador)s,
                %(litros_cargados)s, %(litros_telemetria)s, %(litros_faltantes)s, %(desviacion_pct)s,
                %(semaforo)s, %(horas_maquina)s, %(observaciones)s, %(registrado_por)s, %(tipo_combustible)s,
                %(costo_total)s, %(horometro_inicial)s, %(horometro_final)s, %(costo_por_litro)s,
                %(lt_por_hr)s, %(costo_por_hr)s, %(frente_trabajo)s, %(actividad)s, %(origen_carga)s,
                %(responsable)s, %(folio_ticket)s, %(odometro_inicial)s, %(odometro_final)s,
                %(km_recorridos)s, %(km_por_litro)s, %(costo_por_km)s, %(destino)s)
        ON DUPLICATE KEY UPDATE
            litros_cargados=VALUES(litros_cargados),
            litros_telemetria=VALUES(litros_telemetria),
            litros_faltantes=VALUES(litros_faltantes),
            desviacion_pct=VALUES(desviacion_pct),
            semaforo=VALUES(semaforo),
            horas_maquina=VALUES(horas_maquina),
            observaciones=VALUES(observaciones),
            operador=VALUES(operador),
            tipo_combustible=VALUES(tipo_combustible),
            costo_total=VALUES(costo_total),
            costo_por_litro=VALUES(costo_por_litro),
            folio_ticket=VALUES(folio_ticket)
    """, d)

def marcar_reporte_justificado(rid, justificado, observaciones=None):
    if observaciones is not None:
        execute("UPDATE reportes_combustible SET justificado=%s, observaciones=%s WHERE id=%s",
                (justificado, observaciones, rid))
    else:
        execute("UPDATE reportes_combustible SET justificado=%s WHERE id=%s", (justificado, rid))

def telemetria_consumo_dia(eco, fecha):
    """Obtiene el nivel de combustible del equipo en la fecha dada desde la tabla estado.
    Calcula litros: nivel_combustible/100 * capacidad_litros.
    Si no tiene capacidad_litros, usa el porcentaje directamente como valor."""
    # Buscar el último registro del día en estado
    r = query("""
        SELECT nivel_combustible, capacidad_litros
        FROM estado
        WHERE codigo_eco=%s AND DATE(fecha_ultima_actualizacion)=%s
              AND nivel_combustible IS NOT NULL
        ORDER BY fecha_ultima_actualizacion DESC LIMIT 1
    """, (eco, fecha), one=True)
    if not r or r.get("nivel_combustible") is None:
        # Fallback: intentar con utilizacion (compatibilidad)
        r2 = query("SELECT litros_consumidos, horas_maquina FROM utilizacion WHERE codigo_eco=%s AND fecha=%s",
                   (eco, fecha), one=True)
        return r2 or {}
    nivel = float(r["nivel_combustible"])
    cap = float(r["capacidad_litros"]) if r.get("capacidad_litros") else None
    if cap and cap > 0:
        litros = round(nivel / 100 * cap, 2)
    else:
        litros = round(nivel, 2)  # Sin capacidad, usar porcentaje como valor
    # También traer horas_maquina de utilizacion si existe
    r_hrs = query("SELECT horas_maquina FROM utilizacion WHERE codigo_eco=%s AND fecha=%s",
                  (eco, fecha), one=True)
    return {"litros_consumidos": litros, "horas_maquina": (r_hrs or {}).get("horas_maquina")}

# ══════════════════════════════════════════════════════════════════
#  DOCUMENTOS
# ══════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════
#  CARPETAS DE DOCUMENTOS
# ══════════════════════════════════════════════════════════════════
def get_carpetas(id_obra=None):
    """Devuelve carpetas, opcionalmente filtradas por obra."""
    if id_obra:
        return query("SELECT * FROM doc_carpetas WHERE id_obra=%s ORDER BY padre_id ASC, nombre ASC", (id_obra,))
    return query("SELECT * FROM doc_carpetas ORDER BY padre_id ASC, nombre ASC")

def crear_carpeta(nombre, padre_id=None, id_obra=None):
    return execute(
        "INSERT INTO doc_carpetas (nombre, padre_id, id_obra) VALUES (%s, %s, %s)",
        (nombre, padre_id or None, id_obra or None))

def eliminar_carpeta(cid):
    # Mueve documentos huérfanos a sin-carpeta
    execute("UPDATE documentos SET id_carpeta=NULL WHERE id_carpeta=%s", (cid,))
    # Remueve subcarpetas recursivamente (nivel 2 máximo por ahora)
    subcarpetas = query("SELECT id FROM doc_carpetas WHERE padre_id=%s", (cid,))
    for sc in subcarpetas:
        execute("UPDATE documentos SET id_carpeta=NULL WHERE id_carpeta=%s", (sc["id"],))
        execute("DELETE FROM doc_carpetas WHERE id=%s", (sc["id"],))
    execute("DELETE FROM doc_carpetas WHERE id=%s", (cid,))

def get_documentos(id_maquina=None, id_obra=None, tipo=None, search=None, id_carpeta="__none__"):
    sql = """SELECT d.*, u.nombre AS subido_por_nombre, m.eco AS maquina_eco,
                    ob.nombre AS obra_nombre
             FROM documentos d
             LEFT JOIN usuarios u ON u.id=d.subido_por
             LEFT JOIN maquinas m ON m.id=d.id_maquina
             LEFT JOIN obras ob   ON ob.id=d.id_obra
             WHERE 1=1"""
    p = []
    if id_maquina: sql += " AND d.id_maquina=%s"; p.append(id_maquina)
    if id_obra:    sql += " AND d.id_obra=%s"; p.append(id_obra)
    if tipo:       sql += " AND d.tipo=%s"; p.append(tipo)
    if search:     sql += " AND d.nombre LIKE %s"; p.append(f"%{search}%")
    if id_carpeta not in ("__none__", "__all__"):
        if id_carpeta is None:
            sql += " AND d.id_carpeta IS NULL"
        else:
            sql += " AND d.id_carpeta=%s"; p.append(id_carpeta)
    elif id_carpeta == "__none__":
        sql += " AND d.id_carpeta IS NULL"
    # __all__ → sin filtro de carpeta
    sql += " ORDER BY d.subido_en DESC"
    return query(sql, p)

def crear_documento(tipo, nombre, archivo, id_maquina, id_obra, subido_por, id_carpeta=None):
    return execute(
        "INSERT INTO documentos (tipo,nombre,archivo,id_maquina,id_obra,subido_por,id_carpeta) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (tipo, nombre, archivo, id_maquina or None, id_obra or None, subido_por, id_carpeta or None))

def eliminar_documento(did):
    doc = query("SELECT * FROM documentos WHERE id=%s", (did,), one=True)
    execute("DELETE FROM documentos WHERE id=%s", (did,))
    return doc

# ══════════════════════════════════════════════════════════════════
#  INSPECCIONES
# ══════════════════════════════════════════════════════════════════
def get_inspecciones(fi=None, ff=None, resultado=None):
    sql = """SELECT i.*, ob.nombre AS obra_nombre
             FROM inspecciones i LEFT JOIN obras ob ON ob.id=i.id_obra WHERE 1=1"""
    p = []
    if fi: sql += " AND i.fecha >= %s"; p.append(fi)
    if ff: sql += " AND i.fecha <= %s"; p.append(ff)
    if resultado: sql += " AND i.resultado=%s"; p.append(resultado)
    sql += " ORDER BY i.fecha DESC, i.id DESC"
    return query(sql, p)

def crear_inspeccion(d):
    folio = "INS-" + str(int(__import__("time").time()))[-6:]
    d = dict(d); d["folio"] = folio
    execute("""
        INSERT INTO inspecciones
            (folio,codigo_eco,id_obra,fecha,inspector,tipo,resultado,severidad,hallazgos,registrado_por)
        VALUES (%(folio)s,%(codigo_eco)s,%(id_obra)s,%(fecha)s,%(inspector)s,%(tipo)s,
                %(resultado)s,%(severidad)s,%(hallazgos)s,%(registrado_por)s)
    """, d)
    return folio

# ══════════════════════════════════════════════════════════════════
#  INCIDENTES
# ══════════════════════════════════════════════════════════════════
def get_incidentes(estado=None, severidad=None):
    sql = """SELECT i.*, ob.nombre AS obra_nombre
             FROM incidentes i LEFT JOIN obras ob ON ob.id=i.id_obra WHERE 1=1"""
    p = []
    if estado: sql += " AND i.estado=%s"; p.append(estado)
    if severidad: sql += " AND i.severidad=%s"; p.append(severidad)
    sql += " ORDER BY FIELD(i.estado,'abierto','en_proceso','cerrado'), FIELD(i.severidad,'critico','alto','medio','bajo'), i.fecha DESC"
    return query(sql, p)

def crear_incidente(d):
    folio = "INC-" + str(int(__import__("time").time()))[-6:]
    d = dict(d); d["folio"] = folio
    execute("""
        INSERT INTO incidentes
            (folio,codigo_eco,id_obra,fecha,tipo,descripcion,severidad,estado,responsable,reportado_por)
        VALUES (%(folio)s,%(codigo_eco)s,%(id_obra)s,%(fecha)s,%(tipo)s,%(descripcion)s,
                %(severidad)s,%(estado)s,%(responsable)s,%(reportado_por)s)
    """, d)
    return folio

def actualizar_estado_incidente(iid, estado):
    execute("UPDATE incidentes SET estado=%s WHERE id=%s", (estado, iid))

# ══════════════════════════════════════════════════════════════════
#  REGISTRO DIARIO
# ══════════════════════════════════════════════════════════════════
def get_registros(fi=None, ff=None, obra=None):
    sql = """SELECT r.*, ob.nombre AS obra_nombre
             FROM registro_diario r LEFT JOIN obras ob ON ob.id=r.id_obra WHERE 1=1"""
    p = []
    if fi: sql += " AND r.fecha >= %s"; p.append(fi)
    if ff: sql += " AND r.fecha <= %s"; p.append(ff)
    if obra: sql += " AND r.id_obra=%s"; p.append(obra)
    sql += " ORDER BY r.fecha DESC, r.id DESC"
    return query(sql, p)

def crear_registro(d):
    return execute("""
        INSERT INTO registro_diario
            (fecha,id_obra,autor,clima,equipos_activos,notas,registrado_por)
        VALUES (%(fecha)s,%(id_obra)s,%(autor)s,%(clima)s,%(equipos_activos)s,%(notas)s,%(registrado_por)s)
    """, d)

# ══════════════════════════════════════════════════════════════════
#  EXPORTAR  — todas las funciones aceptan lista=[] (vacío = todos)
# ══════════════════════════════════════════════════════════════════


def _filtro_eco(campo, lista):
    """Devuelve (fragmento_sql, params_extra) para filtrar por lista de ECOs.
    Aplica TRIM para evitar problemas con espacios ocultos en la base de datos."""
    if not lista:
        return "", []
    placeholders = ",".join(["%s"] * len(lista))
    # Usamos TRIM() para limpiar los espacios de la columna en la base de datos
    return f" AND TRIM({campo}) IN ({placeholders})", [e.strip() for e in lista]


def get_estado_export(fi, ff, lista=None):
    """Exporta el historial de lecturas de estado filtrado por fechas y equipos.
    lista: lista de codigo_eco a incluir; None o [] = todos."""
    lista = lista or []
    extra, extra_params = _filtro_eco("codigo_eco", lista)
    sql = f"""
        SELECT id, codigo_eco, serie, nombre_equipo, marca, modelo, fecha_ultima_actualizacion,
               latitud, longitud, horas_totales_horometro, nivel_combustible, capacidad_litros
        FROM estado
        WHERE DATE(fecha_ultima_actualizacion) BETWEEN %s AND %s{extra}
        ORDER BY codigo_eco, fecha_ultima_actualizacion
    """
    return query(sql, [fi, ff] + extra_params)


def get_horas_export(fi, ff, lista=None):
    """Exporta horas diarias entre fi y ff.
    lista: lista de codigo_eco a incluir; None o [] = todos."""
    lista = lista or []
    extra, extra_params = _filtro_eco("codigo_eco", lista)
    sql = f"""
        SELECT codigo_eco, nombre_equipo, marca, modelo, fecha,
               horas_trabajadas, horas_motor_conectado, horas_ralenti, motor_desconectado
        FROM horas_diarias
        WHERE fecha BETWEEN %s AND %s{extra}
        ORDER BY codigo_eco, fecha
    """
    return query(sql, [fi, ff] + extra_params)


def get_utilizacion_export(fi, ff, lista=None):
    """Exporta utilización y consumo entre fi y ff.
    lista: lista de codigo_eco a incluir; None o [] = todos."""
    lista = lista or []
    extra, extra_params = _filtro_eco("codigo_eco", lista)
    sql = f"""
        SELECT codigo_eco, nombre_equipo, marca, modelo, fecha,
               litros_hora, litros_consumidos, horas_maquina, horas_ralenti
        FROM utilizacion
        WHERE fecha BETWEEN %s AND %s{extra}
        ORDER BY codigo_eco, fecha
    """
    return query(sql, [fi, ff] + extra_params)


def get_combustible_export(fi, ff, lista=None):
    """Exporta reportes 360 de combustible entre fi y ff.
    lista: lista de codigo_eco a incluir; None o [] = todos."""
    lista = lista or []
    extra, extra_params = _filtro_eco("r.codigo_eco", lista)
    sql = f"""
        SELECT r.codigo_eco, r.nombre_equipo, r.marca, ob.nombre AS obra, r.fecha,
               r.operador, r.litros_cargados, r.litros_telemetria, r.litros_faltantes,
               r.desviacion_pct, r.semaforo, r.justificado, r.observaciones
        FROM reportes_combustible r
        LEFT JOIN obras ob ON ob.id = r.id_obra
        WHERE r.fecha BETWEEN %s AND %s{extra}
        ORDER BY r.fecha, r.codigo_eco
    """
    return query(sql, [fi, ff] + extra_params)

# ══════════════════════════════════════════════════════════════════
#  PERMISOS CRUD POR ROL
# ══════════════════════════════════════════════════════════════════

MODULOS_PERMISOS = [
    ("dashboard_completo", "Dashboard KPIs / Alertas / Telemetría"),
    ("equipos",        "Equipos y Maquinaria"),
    ("obras",          "Obras"),
    ("documentos",     "Documentos"),
    ("inspecciones",   "Inspecciones"),
    ("incidentes",     "Incidentes"),
    ("registro",       "Registro Diario"),
    ("combustible",    "Combustible / Reportes 360"),
    ("telemetria",     "Ver Telemetría (gráficas/datos)"),
    ("mapa",           "Mapa GPS"),
    ("exportar",       "Exportar Excel"),
    ("planta",         "Planta de Asfalto"),
    ("acarreo",        "Acarreo de Materiales"),
    ("reportes_obra",  "Reportes de Obra Acarreos"),
    ("rrhh",           "Recursos Humanos"),
    ("requisiciones",  "Requisiciones Semanales"),
    ("ordenes_compra", "Órdenes de Compra"),
    ("proveedores",    "Proveedores"),
    ("presupuesto",    "Presupuesto y Códigos de Costo"),
    ("analisis_compra", "Análisis de Compra (Cotizaciones)"),
    ("caja_chica",     "Caja Chica / Reembolsos / Viáticos"),
    ("cancelaciones_cfdi", "Solicitudes de Cancelación CFDI"),
    ("contratos",      "Contratos"),
    ("usuarios",       "Usuarios"),
]

ROLES_PERMISOS_BASE = ["admin", "supervisor", "operador", "reportes", "cliente"]

# Nombres visibles de cada rol (el código interno admin/supervisor/operador/
# reportes/cliente NO cambia — se sigue usando en sesión, permisos_rol, la
# tabla usuarios y las URLs de /permisos — solo cambia lo que se muestra).
ROLES_LABELS_BASE = {
    "admin":      "Admin",
    "supervisor": "Superintendente de Obra",
    "operador":   "Administrador de Obra",
    "reportes":   "Control Interno y Auditoría",
    "cliente":    "Operación de Proyectos",
}

# Roles que administran obra por obra: solo pueden modificar la obra
# que tienen asignada en usuarios.id_obra_asignada
ROLES_RESTRINGIDOS_A_OBRA = ("supervisor", "operador")

ACCIONES = ["crear", "leer", "editar", "eliminar"]


def _init_tabla_roles_custom():
    """Crea la tabla roles_custom si no existe y amplía columnas rol en otras tablas."""
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS roles_custom (
            id         INT AUTO_INCREMENT PRIMARY KEY,
            codigo     VARCHAR(30) NOT NULL UNIQUE,
            nombre     VARCHAR(80) NOT NULL,
            creado_en  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # Migración: ampliar columna rol en usuarios y permisos_rol para soportar roles custom
    try:
        execute_ddl("ALTER TABLE usuarios MODIFY COLUMN rol VARCHAR(30) NOT NULL DEFAULT 'cliente'")
    except Exception:
        pass
    try:
        execute_ddl("ALTER TABLE permisos_rol MODIFY COLUMN rol VARCHAR(30) NOT NULL")
    except Exception:
        pass


def get_roles_custom():
    """Devuelve lista de roles personalizados [{codigo, nombre}]."""
    return query("SELECT codigo, nombre FROM roles_custom ORDER BY nombre")


def crear_rol_custom(codigo, nombre):
    """Crea un rol personalizado. Retorna el ID o None si ya existe."""
    try:
        rid = execute("INSERT INTO roles_custom (codigo, nombre) VALUES (%s, %s)", (codigo, nombre))
        # Insertar permisos vacíos para todos los módulos
        for modulo, _ in MODULOS_PERMISOS:
            execute("""INSERT IGNORE INTO permisos_rol (rol, modulo, crear, leer, editar, eliminar)
                       VALUES (%s, %s, 0, 0, 0, 0)""", (codigo, modulo))
        return rid
    except Exception:
        return None


def eliminar_rol_custom(codigo):
    """Elimina un rol personalizado y sus permisos. No permite borrar roles base."""
    if codigo in ROLES_PERMISOS_BASE:
        return False
    execute("DELETE FROM permisos_rol WHERE rol=%s", (codigo,))
    execute("DELETE FROM roles_custom WHERE codigo=%s", (codigo,))
    return True


def get_roles_permisos():
    """Devuelve la lista completa de roles (base + custom) para usar en la app."""
    customs = get_roles_custom()
    return ROLES_PERMISOS_BASE + [c["codigo"] for c in customs]


def get_roles_labels():
    """Devuelve dict {codigo: nombre_visible} para todos los roles."""
    labels = dict(ROLES_LABELS_BASE)
    customs = get_roles_custom()
    for c in customs:
        labels[c["codigo"]] = c["nombre"]
    return labels


# Compatibilidad — estas variables se recalculan al importar pero las funciones
# dinámicas son las que se deben usar en runtime.
ROLES_PERMISOS = ROLES_PERMISOS_BASE[:]
ROLES_LABELS = dict(ROLES_LABELS_BASE)

def _init_tabla_permisos():
    """Crea la tabla permisos_rol si no existe."""
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS permisos_rol (
            id       INT AUTO_INCREMENT PRIMARY KEY,
            rol      VARCHAR(20) NOT NULL,
            modulo   VARCHAR(40) NOT NULL,
            crear    TINYINT(1) NOT NULL DEFAULT 0,
            leer     TINYINT(1) NOT NULL DEFAULT 0,
            editar   TINYINT(1) NOT NULL DEFAULT 0,
            eliminar TINYINT(1) NOT NULL DEFAULT 0,
            UNIQUE KEY uq_rol_modulo (rol, modulo)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

def _defaults_permisos():
    """Devuelve los permisos por defecto para cada rol."""
    # (crear, leer, editar, eliminar)
    defaults = {
        "admin":      {m: (1,1,1,1) for m,_ in MODULOS_PERMISOS},
        "supervisor": {
            "dashboard_completo": (0,0,0,0),
            "equipos":     (0,1,1,0), "obras":       (0,1,1,0),
            "documentos":  (1,1,1,1), "inspecciones":(1,1,1,0),
            "incidentes":  (1,1,1,0), "registro":    (1,1,1,0),
            "combustible": (1,1,1,0), "telemetria":  (0,1,0,0),
            "mapa":        (0,1,0,0),
            "exportar":    (0,1,0,0), "planta":      (1,1,1,0),
            "acarreo":     (1,1,1,0), "usuarios":    (0,0,0,0),
        },
        "operador": {
            "dashboard_completo": (0,0,0,0),
            "equipos":     (0,1,0,0), "obras":       (0,1,0,0),
            "documentos":  (0,1,0,0), "inspecciones":(1,1,0,0),
            "incidentes":  (1,1,0,0), "registro":    (1,1,1,0),
            "combustible": (0,1,0,0), "telemetria":  (0,0,0,0),
            "mapa":        (0,1,0,0),
            "exportar":    (0,0,0,0), "planta":      (1,1,1,0),
            "acarreo":     (0,1,0,0), "usuarios":    (0,0,0,0),
        },
        "reportes": {
            "dashboard_completo": (0,0,0,0),
            "equipos":     (0,1,0,0), "obras":       (0,1,0,0),
            "documentos":  (0,1,0,0), "inspecciones":(0,1,0,0),
            "incidentes":  (0,1,0,0), "registro":    (0,1,0,0),
            "combustible": (1,1,1,0), "telemetria":  (0,0,0,0),
            "mapa":        (0,1,0,0),
            "exportar":    (0,1,0,0), "planta":      (0,0,0,0),
            "acarreo":     (0,1,0,0), "usuarios":    (0,0,0,0),
        },
        "cliente": {
            "dashboard_completo": (0,0,0,0),
            "equipos":     (0,1,0,0), "obras":       (0,1,0,0),
            "documentos":  (0,1,0,0), "inspecciones":(0,1,0,0),
            "incidentes":  (0,0,0,0), "registro":    (0,1,0,0),
            "combustible": (0,0,0,0), "telemetria":  (0,0,0,0),
            "mapa":        (0,1,0,0),
            "exportar":    (0,0,0,0), "planta":      (0,0,0,0),
            "acarreo":     (0,0,0,0), "usuarios":    (0,0,0,0),
            "ordenes_compra": (0,0,0,0),
        },
    }
    # Agregar ordenes_compra a roles que no lo tienen aún
    for rol in ("admin", "supervisor", "operador", "reportes"):
        if rol not in defaults:
            defaults[rol] = {}
        if "ordenes_compra" not in defaults[rol]:
            defaults[rol]["ordenes_compra"] = {
                "admin":      (1,1,1,1),
                "supervisor": (1,1,1,0),
                "operador":   (1,1,0,0),
                "reportes":   (0,1,0,0),
            }[rol]
    # Agregar proveedores y presupuesto a roles que no los tienen aún
    for rol in ("admin", "supervisor", "operador", "reportes", "cliente"):
        if rol not in defaults:
            defaults[rol] = {}
        if "proveedores" not in defaults[rol]:
            defaults[rol]["proveedores"] = {
                "admin":      (1,1,1,1),
                "supervisor": (1,1,1,0),
                "operador":   (0,1,0,0),
                "reportes":   (1,1,0,0),
                "cliente":    (0,0,0,0),
            }[rol]
        if "presupuesto" not in defaults[rol]:
            defaults[rol]["presupuesto"] = {
                "admin":      (1,1,1,1),
                "supervisor": (0,1,0,0),
                "operador":   (0,0,0,0),
                "reportes":   (1,1,0,0),
                "cliente":    (0,0,0,0),
            }[rol]
        if "analisis_compra" not in defaults[rol]:
            defaults[rol]["analisis_compra"] = {
                "admin":      (1,1,1,1),
                "supervisor": (1,1,1,0),
                "operador":   (1,1,0,0),
                "reportes":   (0,1,0,0),
                "cliente":    (0,0,0,0),
            }[rol]
        if "caja_chica" not in defaults[rol]:
            defaults[rol]["caja_chica"] = {
                "admin":      (1,1,1,1),
                "supervisor": (1,1,1,0),
                "operador":   (1,1,0,0),
                "reportes":   (1,1,0,0),
                "cliente":    (0,0,0,0),
            }[rol]
        if "cancelaciones_cfdi" not in defaults[rol]:
            defaults[rol]["cancelaciones_cfdi"] = {
                "admin":      (1,1,1,1),
                "supervisor": (1,1,0,0),
                "operador":   (0,0,0,0),
                "reportes":   (1,1,1,0),
                "cliente":    (0,0,0,0),
            }[rol]
        if "contratos" not in defaults[rol]:
            defaults[rol]["contratos"] = {
                "admin":      (1,1,1,1),
                "supervisor": (1,1,1,0),
                "operador":   (0,1,0,0),
                "reportes":   (0,1,0,0),
                "cliente":    (0,0,0,0),
            }[rol]
    return defaults

def get_permisos_rol(rol):
    """Devuelve dict {modulo: {crear,leer,editar,eliminar}} para un rol."""
    filas = query("SELECT * FROM permisos_rol WHERE rol=%s", (rol,))
    resultado = {}
    for f in filas:
        resultado[f["modulo"]] = {
            "crear": bool(f["crear"]), "leer": bool(f["leer"]),
            "editar": bool(f["editar"]), "eliminar": bool(f["eliminar"])
        }
    return resultado

def get_todos_permisos():
    """Devuelve {rol: {modulo: {accion: bool}}} para todos los roles."""
    filas = query("SELECT * FROM permisos_rol ORDER BY rol, modulo")
    result = {}
    for f in filas:
        r = f["rol"]
        if r not in result: result[r] = {}
        result[r][f["modulo"]] = {
            "crear": bool(f["crear"]), "leer": bool(f["leer"]),
            "editar": bool(f["editar"]), "eliminar": bool(f["eliminar"])
        }
    return result

def guardar_permisos_rol(rol, permisos_dict):
    """permisos_dict = {modulo: {crear,leer,editar,eliminar}}"""
    for modulo, acc in permisos_dict.items():
        execute("""
            INSERT INTO permisos_rol (rol, modulo, crear, leer, editar, eliminar)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                crear=%s, leer=%s, editar=%s, eliminar=%s
        """, (rol, modulo,
              int(acc.get("crear",0)), int(acc.get("leer",0)),
              int(acc.get("editar",0)), int(acc.get("eliminar",0)),
              int(acc.get("crear",0)), int(acc.get("leer",0)),
              int(acc.get("editar",0)), int(acc.get("eliminar",0))))

def init_permisos_si_vacios():
    """Pobla permisos por defecto si la tabla está vacía.
    También inserta módulos nuevos que no existían antes (migración incremental)."""
    _init_tabla_permisos()
    count = query("SELECT COUNT(*) AS n FROM permisos_rol", one=True)
    defaults = _defaults_permisos()
    if count and count["n"] == 0:
        # Tabla vacía: insertar todos los defaults
        for rol, mods in defaults.items():
            for modulo, (c, r, e, d) in mods.items():
                execute("""
                    INSERT IGNORE INTO permisos_rol (rol,modulo,crear,leer,editar,eliminar)
                    VALUES (%s,%s,%s,%s,%s,%s)
                """, (rol, modulo, c, r, e, d))
    else:
        # Tabla ya tiene datos: insertar solo módulos que falten (nuevos)
        _migrar_modulos_nuevos(defaults)


def _migrar_modulos_nuevos(defaults=None):
    """Inserta en permisos_rol los módulos nuevos que aún no existen,
    usando los valores por defecto. NO sobreescribe configuraciones existentes."""
    if defaults is None:
        defaults = _defaults_permisos()
    modulos_definidos = [m for m, _ in MODULOS_PERMISOS]
    todos_roles = get_roles_permisos()
    for rol in todos_roles:
        existentes = query("SELECT modulo FROM permisos_rol WHERE rol=%s", (rol,))
        modulos_existentes = {r["modulo"] for r in existentes}
        mods_rol = defaults.get(rol, {})
        for modulo in modulos_definidos:
            if modulo not in modulos_existentes:
                c, r, e, d = mods_rol.get(modulo, (0, 0, 0, 0))
                execute("""
                    INSERT IGNORE INTO permisos_rol (rol,modulo,crear,leer,editar,eliminar)
                    VALUES (%s,%s,%s,%s,%s,%s)
                """, (rol, modulo, c, r, e, d))


# ══════════════════════════════════════════════════════════════════
#  MANTENIMIENTOS
# ══════════════════════════════════════════════════════════════════

INTERVALO_MANTENIMIENTO_HORAS = 250

def _init_tabla_mantenimientos():
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS mantenimientos (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            codigo_eco      VARCHAR(30) NOT NULL,
            fecha           DATE NOT NULL,
            hora            TIME NOT NULL,
            horometro       DECIMAL(10,2) NOT NULL,
            descripcion     TEXT DEFAULT NULL,
            registrado_por  INT DEFAULT NULL,
            creado_en       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_eco (codigo_eco)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # Migración: si la tabla ya existía con descripcion VARCHAR(255), ampliarla a TEXT
    try:
        execute_ddl("ALTER TABLE mantenimientos MODIFY COLUMN descripcion TEXT DEFAULT NULL")
    except Exception:
        pass

def get_ultimo_mantenimiento(eco):
    """Último mantenimiento registrado para un ECO (por horómetro más alto)."""
    return query("""
        SELECT * FROM mantenimientos
        WHERE codigo_eco=%s
        ORDER BY horometro DESC, fecha DESC, hora DESC
        LIMIT 1
    """, (eco,), one=True)

def get_mantenimientos_maquina(eco):
    return query("""
        SELECT m.*, u.nombre AS registrado_por_nombre
        FROM mantenimientos m
        LEFT JOIN usuarios u ON u.id = m.registrado_por
        WHERE m.codigo_eco=%s
        ORDER BY m.horometro DESC
    """, (eco,))

def crear_mantenimiento(eco, fecha, hora, horometro, descripcion, registrado_por):
    return execute("""
        INSERT INTO mantenimientos (codigo_eco, fecha, hora, horometro, descripcion, registrado_por)
        VALUES (%s,%s,%s,%s,%s,%s)
    """, (eco, fecha, hora, horometro, descripcion, registrado_por))

def get_mantenimiento(mid):
    return query("SELECT * FROM mantenimientos WHERE id=%s", (mid,), one=True)

def actualizar_mantenimiento(mid, fecha, hora, horometro, descripcion):
    execute("""UPDATE mantenimientos SET fecha=%s, hora=%s, horometro=%s, descripcion=%s
               WHERE id=%s""", (fecha, hora, horometro, descripcion, mid))

def eliminar_mantenimiento(mid):
    execute("DELETE FROM mantenimientos WHERE id=%s", (mid,))

def get_ultimos_mantenimientos_todos():
    """Devuelve {codigo_eco: {horometro, fecha, hora}} con el último mantenimiento de cada equipo."""
    filas = query("""
        SELECT m1.codigo_eco, m1.horometro, m1.fecha, m1.hora
        FROM mantenimientos m1
        INNER JOIN (
            SELECT codigo_eco, MAX(horometro) AS maxh
            FROM mantenimientos GROUP BY codigo_eco
        ) m2 ON m2.codigo_eco = m1.codigo_eco AND m2.maxh = m1.horometro
    """)
    return {f["codigo_eco"]: f for f in filas}

def calcular_semaforo_mantenimiento(horometro_actual, horometro_ultimo_mant):
    """
    Devuelve dict con: horas_desde_ultimo, horas_restantes, pct, nivel, sin_dato
    Basado en intervalo fijo de 250 horas, dividido en 3 tercios (~83.3 h c/u):
      - ok        : 0    a 83.3 h desde el último mantenimiento   -> verde
      - atencion  : 83.3 a 166.6 h                                -> amarillo
      - proximo   : 166.6 a 250 h                                 -> naranja
      - vencido   : > 250 h                                       -> rojo
    """
    if horometro_actual is None:
        return {"sin_dato": True}
    horometro_actual = float(horometro_actual)
    if horometro_ultimo_mant is None:
        # Sin mantenimiento registrado: se asume desde 0
        horometro_ultimo_mant = 0.0
    else:
        horometro_ultimo_mant = float(horometro_ultimo_mant)

    horas_desde_ultimo = horometro_actual - horometro_ultimo_mant
    horas_restantes = INTERVALO_MANTENIMIENTO_HORAS - horas_desde_ultimo
    pct = max(0, min(100, (horas_desde_ultimo / INTERVALO_MANTENIMIENTO_HORAS) * 100))

    tercio = INTERVALO_MANTENIMIENTO_HORAS / 3  # 83.33...

    if horas_desde_ultimo > INTERVALO_MANTENIMIENTO_HORAS:
        nivel = "vencido"
    elif horas_desde_ultimo > tercio * 2:
        nivel = "proximo"
    elif horas_desde_ultimo > tercio:
        nivel = "atencion"
    else:
        nivel = "ok"

    return {
        "sin_dato": False,
        "horas_desde_ultimo": round(horas_desde_ultimo, 1),
        "horas_restantes": round(horas_restantes, 1),
        "pct": round(pct, 1),
        "nivel": nivel,
    }

# ══════════════════════════════════════════════════════════════════
#  ACARREO DE MATERIALES (Reportes 360 · pestaña Acarreo)
#  Bitácora de viajes por material + comparación Acarreado vs Pagado
# ══════════════════════════════════════════════════════════════════

MATERIALES_ACARREO = ["Arena", "Sello 3/8", "Grava 3/4", "Grava 1/2",
                       "Carpeta", "Fresado", "Otro"]

def _init_tabla_acarreo():
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS acarreo_viajes (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            obra_id         INT DEFAULT NULL,
            semana          VARCHAR(20) NOT NULL,
            fecha           DATE NOT NULL,
            material        VARCHAR(50) NOT NULL,
            placa           VARCHAR(20) DEFAULT NULL,
            origen          VARCHAR(120) DEFAULT NULL,
            destino         VARCHAR(120) DEFAULT NULL,
            volumen         DECIMAL(10,2) NOT NULL DEFAULT 0,
            folio_esma      VARCHAR(30) DEFAULT NULL,
            registrado_por  INT DEFAULT NULL,
            creado_en       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_obra_semana (obra_id, semana),
            INDEX idx_material (material)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS acarreo_pagado (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            obra_id         INT DEFAULT NULL,
            semana          VARCHAR(20) NOT NULL,
            material        VARCHAR(50) NOT NULL,
            m3_pagados      DECIMAL(10,2) NOT NULL DEFAULT 0,
            actualizado_por INT DEFAULT NULL,
            actualizado_en  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_obra_semana_material (obra_id, semana, material)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

def insertar_viaje_acarreo(obra_id, semana, fecha, material, placa, origen,
                            destino, volumen, folio_esma, registrado_por):
    return execute("""
        INSERT INTO acarreo_viajes
          (obra_id, semana, fecha, material, placa, origen, destino,
           volumen, folio_esma, registrado_por)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (obra_id, semana, fecha, material, placa, origen, destino,
          volumen, folio_esma, registrado_por))

def get_viajes_acarreo(obra_id=None, semana=None, material=None, limit=200):
    sql = """SELECT v.*, o.nombre AS obra_nombre
             FROM acarreo_viajes v LEFT JOIN obras o ON o.id=v.obra_id
             WHERE 1=1"""
    params = []
    if obra_id:
        sql += " AND v.obra_id=%s"; params.append(obra_id)
    if semana:
        sql += " AND v.semana=%s"; params.append(semana)
    if material:
        sql += " AND v.material=%s"; params.append(material)
    sql += " ORDER BY v.fecha DESC, v.id DESC LIMIT %s"; params.append(limit)
    return query(sql, params)

def get_resumen_acarreo(obra_id=None, semana=None):
    """Totales de viajes y volumen acarreado, agrupado por material."""
    sql = """SELECT material, COUNT(*) AS viajes, COALESCE(SUM(volumen),0) AS m3_acarreados
             FROM acarreo_viajes WHERE 1=1"""
    params = []
    if obra_id:
        sql += " AND obra_id=%s"; params.append(obra_id)
    if semana:
        sql += " AND semana=%s"; params.append(semana)
    sql += " GROUP BY material ORDER BY m3_acarreados DESC"
    return query(sql, params)

def get_kpis_acarreo(obra_id=None, semana=None):
    sql = """SELECT COUNT(*) AS total_viajes,
                    COALESCE(SUM(volumen),0) AS total_m3,
                    COUNT(DISTINCT material) AS materiales,
                    COUNT(DISTINCT placa) AS camiones
             FROM acarreo_viajes WHERE 1=1"""
    params = []
    if obra_id:
        sql += " AND obra_id=%s"; params.append(obra_id)
    if semana:
        sql += " AND semana=%s"; params.append(semana)
    return query(sql, params, one=True)

def set_pagado_acarreo(obra_id, semana, material, m3_pagados, actualizado_por):
    execute("""
        INSERT INTO acarreo_pagado (obra_id, semana, material, m3_pagados, actualizado_por)
        VALUES (%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE m3_pagados=VALUES(m3_pagados),
                                 actualizado_por=VALUES(actualizado_por)
    """, (obra_id, semana, material, m3_pagados, actualizado_por))

def get_pagado_acarreo(obra_id=None, semana=None):
    """Devuelve dict {material: m3_pagados} para la obra/semana dadas."""
    sql = "SELECT material, m3_pagados FROM acarreo_pagado WHERE 1=1"
    params = []
    if obra_id:
        sql += " AND obra_id=%s"; params.append(obra_id)
    if semana:
        sql += " AND semana=%s"; params.append(semana)
    rows = query(sql, params)
    return {r["material"]: float(r["m3_pagados"]) for r in rows}

def get_semanas_acarreo():
    """Lista de semanas ya capturadas (para el filtro), más reciente primero."""
    rows = query("SELECT DISTINCT semana FROM acarreo_viajes ORDER BY semana DESC")
    return [r["semana"] for r in rows]

# ══════════════════════════════════════════════════════════════════
#  PLANTA DE ASFALTO — CONTROL DE PRODUCCIÓN
#  Réplica funcional del Excel "Control de Producción — Planta de
#  Asfalto": kardex de insumos, avance físico, remisiones y alertas.
#  Todo se recalcula en cada consulta a partir de planta_config
#  (nunca se guardan valores fijos de rendimiento/umbral/semáforo).
# ══════════════════════════════════════════════════════════════════

PLANTA_CONFIG_DEFAULTS = {
    "densidad_asfalto": 0.94, "capacidad_camion_m3": 14.0,
    "umbral_asfalto_lt": 15000, "rend_ref_asfalto": 80.0, "rend_max_asfalto": 100.0,
    "umbral_alterno_lt": 10000,
    "umbral_emulsion_lt": 5000, "rend_ref_emulsion": 0.7, "rend_max_emulsion": 1.2,
    "factor_grava": 0.6, "factor_arena": 0.4,
    "umbral_grava_m3": 200, "umbral_arena_m3": 150,
    "tolerancia_remision_tn": 0.3, "tramo": "",
}

def _init_tabla_planta():
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS planta_config (
            id                   INT AUTO_INCREMENT PRIMARY KEY,
            id_obra              INT NOT NULL UNIQUE,
            densidad_asfalto     DECIMAL(6,3)  NOT NULL DEFAULT 0.94,
            capacidad_camion_m3  DECIMAL(6,2)  NOT NULL DEFAULT 14,
            umbral_asfalto_lt    INT           NOT NULL DEFAULT 15000,
            rend_ref_asfalto     DECIMAL(6,2)  NOT NULL DEFAULT 80,
            rend_max_asfalto     DECIMAL(6,2)  NOT NULL DEFAULT 100,
            umbral_alterno_lt    INT           NOT NULL DEFAULT 10000,
            umbral_emulsion_lt   INT           NOT NULL DEFAULT 5000,
            rend_ref_emulsion    DECIMAL(6,3)  NOT NULL DEFAULT 0.7,
            rend_max_emulsion    DECIMAL(6,3)  NOT NULL DEFAULT 1.2,
            factor_grava         DECIMAL(5,3)  NOT NULL DEFAULT 0.6,
            factor_arena         DECIMAL(5,3)  NOT NULL DEFAULT 0.4,
            umbral_grava_m3      INT           NOT NULL DEFAULT 200,
            umbral_arena_m3      INT           NOT NULL DEFAULT 150,
            tolerancia_remision_tn DECIMAL(5,2) NOT NULL DEFAULT 0.3,
            tramo                VARCHAR(150) DEFAULT NULL,
            actualizado_en       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                                  ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS planta_produccion (
            id           INT AUTO_INCREMENT PRIMARY KEY,
            id_obra      INT NOT NULL,
            fecha        DATE NOT NULL,
            material     VARCHAR(30) DEFAULT NULL,
            num_camiones INT DEFAULT NULL,
            vol_m3       DECIMAL(10,2) DEFAULT NULL,
            asf_ini      DECIMAL(10,2) DEFAULT NULL,
            asf_desc     DECIMAL(10,2) DEFAULT NULL,
            asf_final    DECIMAL(10,2) DEFAULT NULL,
            alt_ini      DECIMAL(10,2) DEFAULT NULL,
            alt_desc     DECIMAL(10,2) DEFAULT NULL,
            alt_final    DECIMAL(10,2) DEFAULT NULL,
            emu_ini      DECIMAL(10,2) DEFAULT NULL,
            emu_desc     DECIMAL(10,2) DEFAULT NULL,
            emu_final    DECIMAL(10,2) DEFAULT NULL,
            grava_ini    DECIMAL(10,2) DEFAULT NULL,
            grava_recib  DECIMAL(10,2) DEFAULT NULL,
            arena_ini    DECIMAL(10,2) DEFAULT NULL,
            arena_recib  DECIMAL(10,2) DEFAULT NULL,
            validado     TINYINT(1) NOT NULL DEFAULT 0,
            creado_por   INT DEFAULT NULL,
            creado_en    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_obra_fecha (id_obra, fecha)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS planta_avance_fisico (
            id         INT AUTO_INCREMENT PRIMARY KEY,
            id_obra    INT NOT NULL,
            fecha      DATE NOT NULL,
            carril     VARCHAR(30) DEFAULT NULL,
            inicio     DECIMAL(10,2) DEFAULT NULL,
            termino    DECIMAL(10,2) DEFAULT NULL,
            ancho      DECIMAL(6,2) DEFAULT NULL,
            espesor    DECIMAL(6,3) DEFAULT NULL,
            creado_por INT DEFAULT NULL,
            creado_en  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_obra_fecha (id_obra, fecha)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS planta_remisiones (
            id                 INT AUTO_INCREMENT PRIMARY KEY,
            id_obra            INT NOT NULL,
            producto           ENUM('asfalto','emulsion') NOT NULL DEFAULT 'asfalto',
            proveedor          VARCHAR(80) DEFAULT NULL,
            fecha_llegada      DATE DEFAULT NULL,
            fecha_salida       DATE DEFAULT NULL,
            remision           VARCHAR(40) DEFAULT NULL,
            certificado        VARCHAR(40) DEFAULT NULL,
            placas_tracto      VARCHAR(20) DEFAULT NULL,
            placas_tanque      VARCHAR(20) DEFAULT NULL,
            peso_bruto_envio   DECIMAL(8,2) DEFAULT NULL,
            tara_envio         DECIMAL(8,2) DEFAULT NULL,
            peso_neto_envio    DECIMAL(8,2) DEFAULT NULL,
            peso_bruto_recibo  DECIMAL(8,2) DEFAULT NULL,
            tara_recibo        DECIMAL(8,2) DEFAULT NULL,
            precio_tonelada    DECIMAL(12,2) DEFAULT NULL,
            creado_por         INT DEFAULT NULL,
            creado_en          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_obra_producto (id_obra, producto)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

# ── CONFIG (parámetros por obra, editables — todo lo demás recalcula) ──
def get_planta_config(id_obra):
    row = query("SELECT * FROM planta_config WHERE id_obra=%s", (id_obra,), one=True)
    if not row:
        execute("""INSERT INTO planta_config (id_obra) VALUES (%s)""", (id_obra,))
        row = query("SELECT * FROM planta_config WHERE id_obra=%s", (id_obra,), one=True)
    return row

def guardar_planta_config(id_obra, datos):
    get_planta_config(id_obra)  # asegura que exista la fila
    campos = list(PLANTA_CONFIG_DEFAULTS.keys())
    sets = ", ".join(f"{c}=%s" for c in campos)
    valores = [datos.get(c) for c in campos]
    execute(f"UPDATE planta_config SET {sets} WHERE id_obra=%s", valores + [id_obra])

# ── KARDEX: el "final" del registro anterior alimenta el "inicial" del nuevo ──
def _kardex_anterior(id_obra, fecha):
    return query("""
        SELECT asf_final, alt_final, emu_final, grava_ini, grava_recib,
               arena_ini, arena_recib, vol_m3
        FROM planta_produccion
        WHERE id_obra=%s AND fecha<=%s
        ORDER BY fecha DESC, id DESC LIMIT 1
    """, (id_obra, fecha), one=True)

def crear_planta_produccion(datos):
    cfg = get_planta_config(datos["id_obra"])
    prev = _kardex_anterior(datos["id_obra"], datos["fecha"])
    if prev:
        prev_grava_final = float(prev["grava_ini"] or 0) + float(prev["grava_recib"] or 0) \
                            - float(prev["vol_m3"] or 0) * float(cfg["factor_grava"])
        prev_arena_final = float(prev["arena_ini"] or 0) + float(prev["arena_recib"] or 0) \
                            - float(prev["vol_m3"] or 0) * float(cfg["factor_arena"])
    def _auto(val, campo_prev, default_prev=0.0):
        if val not in (None, ""):
            return val
        return float(prev[campo_prev]) if prev and prev.get(campo_prev) is not None else default_prev
    asf_ini   = _auto(datos.get("asf_ini"), "asf_final")
    alt_ini   = _auto(datos.get("alt_ini"), "alt_final")
    emu_ini   = _auto(datos.get("emu_ini"), "emu_final")
    grava_ini = datos.get("grava_ini") if datos.get("grava_ini") not in (None, "") \
                else (round(prev_grava_final, 2) if prev else 0.0)
    arena_ini = datos.get("arena_ini") if datos.get("arena_ini") not in (None, "") \
                else (round(prev_arena_final, 2) if prev else 0.0)
    return execute("""
        INSERT INTO planta_produccion
        (id_obra, fecha, material, num_camiones, vol_m3,
         asf_ini, asf_desc, asf_final, alt_ini, alt_desc, alt_final,
         emu_ini, emu_desc, emu_final, grava_ini, grava_recib, arena_ini, arena_recib,
         creado_por)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (datos["id_obra"], datos["fecha"], datos.get("material"),
          datos.get("num_camiones"), datos.get("vol_m3"),
          asf_ini, datos.get("asf_desc"), datos.get("asf_final"),
          alt_ini, datos.get("alt_desc"), datos.get("alt_final"),
          emu_ini, datos.get("emu_desc"), datos.get("emu_final"),
          grava_ini, datos.get("grava_recib"), arena_ini, datos.get("arena_recib"),
          datos.get("creado_por")))

def validar_planta_produccion(pid):
    execute("UPDATE planta_produccion SET validado=1 WHERE id=%s", (pid,))

def _avance_del_dia(id_obra, fecha):
    return query("""
        SELECT COALESCE(SUM((termino-inicio)*ancho),0) AS area,
               COALESCE(SUM((termino-inicio)*ancho*espesor),0) AS vol_compacto
        FROM planta_avance_fisico WHERE id_obra=%s AND fecha=%s
    """, (id_obra, fecha), one=True)

def _calc_fila_produccion(f, cfg):
    """Añade a la fila los campos calculados (equivalentes a las fórmulas del Excel)."""
    def cons(ini, desc, fin):
        if fin is None or ini is None: return None
        return round(float(ini) + float(desc or 0) - float(fin), 2)
    f["asf_cons"] = cons(f["asf_ini"], f["asf_desc"], f["asf_final"])
    f["alt_cons"] = cons(f["alt_ini"], f["alt_desc"], f["alt_final"])
    f["emu_cons"] = cons(f["emu_ini"], f["emu_desc"], f["emu_final"])
    vol = float(f["vol_m3"] or 0)
    f["asf_kg"]  = round(f["asf_cons"] * float(cfg["densidad_asfalto"]), 1) if f["asf_cons"] is not None else None
    f["asf_rend"] = round(f["asf_cons"] / vol, 2) if f["asf_cons"] is not None and vol > 0 else None
    f["grava_cons"]  = round(vol * float(cfg["factor_grava"]), 2)
    f["arena_cons"]  = round(vol * float(cfg["factor_arena"]), 2)
    f["grava_final"] = round(float(f["grava_ini"] or 0) + float(f["grava_recib"] or 0) - f["grava_cons"], 2)
    f["arena_final"] = round(float(f["arena_ini"] or 0) + float(f["arena_recib"] or 0) - f["arena_cons"], 2)
    av = _avance_del_dia(f["id_obra"], f["fecha"])
    f["vol_avance_dia"]  = float(av["vol_compacto"] or 0)
    f["area_avance_dia"] = float(av["area"] or 0)
    f["abundamiento"] = round(vol / f["vol_avance_dia"], 3) if f["vol_avance_dia"] > 0 else None
    f["emu_rend"] = round(f["emu_cons"] / f["area_avance_dia"], 3) \
                    if f["emu_cons"] is not None and f["area_avance_dia"] > 0 else None
    return f

def get_planta_producciones(id_obra, fi=None, ff=None):
    cfg = get_planta_config(id_obra)
    sql = "SELECT * FROM planta_produccion WHERE id_obra=%s"
    p = [id_obra]
    if fi: sql += " AND fecha>=%s"; p.append(fi)
    if ff: sql += " AND fecha<=%s"; p.append(ff)
    sql += " ORDER BY fecha DESC, id DESC"
    return [_calc_fila_produccion(f, cfg) for f in query(sql, p)]

def get_planta_stock_actual(id_obra):
    """Últimos valores conocidos — equivalente al RESUMEN EJECUTIVO del Excel.
    8 indicadores: Asfalto recibido, Consumo acumulado (kg), Asfalto restante,
    Volumen producido, Rendimiento prom., Días con stock, Grava restante, Arena restante."""
    cfg = get_planta_config(id_obra)
    ultimo = query("""SELECT * FROM planta_produccion WHERE id_obra=%s
                       ORDER BY fecha DESC, id DESC LIMIT 1""", (id_obra,), one=True)
    if not ultimo:
        return {"asf_final": 0, "alt_final": 0, "emu_final": 0, "grava_final": 0, "arena_final": 0,
                "asf_rend_prom": None, "dias_stock_asf": None, "fecha": None,
                "asf_recibido": 0, "asf_consumo_acum_kg": 0, "vol_producido": 0}
    ultimo = _calc_fila_produccion(ultimo, cfg)

    # Asfalto recibido total (suma de todas las descargas)
    asf_recibido = query("""SELECT COALESCE(SUM(asf_desc), 0) AS total
                             FROM planta_produccion WHERE id_obra=%s""", (id_obra,), one=True)

    # Consumo acumulado en litros y kg
    asf_consumo_acum = query("""SELECT COALESCE(SUM(asf_ini + COALESCE(asf_desc,0) - asf_final), 0) AS total
                                 FROM planta_produccion
                                 WHERE id_obra=%s AND asf_final IS NOT NULL""", (id_obra,), one=True)
    consumo_lt = float(asf_consumo_acum["total"]) if asf_consumo_acum else 0
    consumo_kg = round(consumo_lt * float(cfg["densidad_asfalto"]), 0)

    # Volumen producido acumulado
    vol_producido = query("""SELECT COALESCE(SUM(vol_m3), 0) AS total
                              FROM planta_produccion WHERE id_obra=%s""", (id_obra,), one=True)

    # Rendimiento promedio (últimos 7 días)
    rend_prom = query("""SELECT AVG(asf_cons_por_m3) AS r FROM (
                            SELECT (asf_ini+COALESCE(asf_desc,0)-asf_final)/vol_m3 AS asf_cons_por_m3
                            FROM planta_produccion
                            WHERE id_obra=%s AND vol_m3>0 AND asf_final IS NOT NULL
                              AND fecha >= CURDATE()-INTERVAL 7 DAY) t""", (id_obra,), one=True)

    # Consumo diario promedio para estimar días de stock
    consumo_diario_prom = query("""SELECT AVG(asf_ini+COALESCE(asf_desc,0)-asf_final) AS c
                                    FROM planta_produccion
                                    WHERE id_obra=%s AND asf_final IS NOT NULL
                                      AND fecha >= CURDATE()-INTERVAL 7 DAY""", (id_obra,), one=True)
    cdiario = float(consumo_diario_prom["c"]) if consumo_diario_prom and consumo_diario_prom["c"] else 0

    return {
        "fecha": ultimo["fecha"],
        "asf_recibido": float(asf_recibido["total"]) if asf_recibido else 0,
        "asf_consumo_acum_kg": consumo_kg,
        "asf_final": float(ultimo["asf_final"] or 0),
        "vol_producido": float(vol_producido["total"]) if vol_producido else 0,
        "asf_rend_prom": round(float(rend_prom["r"]), 1) if rend_prom and rend_prom["r"] else None,
        "dias_stock_asf": round(float(ultimo["asf_final"] or 0) / cdiario, 1) if cdiario > 0 else None,
        "grava_final": ultimo["grava_final"],
        "arena_final": ultimo["arena_final"],
        "alt_final": float(ultimo["alt_final"] or 0),
        "emu_final": float(ultimo["emu_final"] or 0),
    }

# ── AVANCE FÍSICO ──
def crear_planta_avance(datos):
    return execute("""INSERT INTO planta_avance_fisico
        (id_obra, fecha, carril, inicio, termino, ancho, espesor, creado_por)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (datos["id_obra"], datos["fecha"], datos.get("carril"), datos.get("inicio"),
         datos.get("termino"), datos.get("ancho"), datos.get("espesor"), datos.get("creado_por")))

def get_planta_avance(id_obra, fi=None, ff=None):
    sql = """SELECT *, (termino-inicio) AS distancia, (termino-inicio)*ancho AS area,
                    (termino-inicio)*ancho*espesor AS vol_compacto
             FROM planta_avance_fisico WHERE id_obra=%s"""
    p = [id_obra]
    if fi: sql += " AND fecha>=%s"; p.append(fi)
    if ff: sql += " AND fecha<=%s"; p.append(ff)
    sql += " ORDER BY fecha DESC, id DESC"
    filas = query(sql, p)
    acum = 0.0
    for f in reversed(filas):
        acum += float(f["vol_compacto"] or 0)
        f["acumulado"] = round(acum, 2)
    return filas

# ── REMISIONES (base real de pago de asfalto/emulsión) ──
def crear_planta_remision(datos):
    return execute("""INSERT INTO planta_remisiones
        (id_obra, producto, proveedor, fecha_llegada, fecha_salida, remision, certificado,
         placas_tracto, placas_tanque, peso_bruto_envio, tara_envio, peso_neto_envio,
         peso_bruto_recibo, tara_recibo, precio_tonelada, creado_por)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (datos["id_obra"], datos.get("producto","asfalto"), datos.get("proveedor"),
         datos.get("fecha_llegada"), datos.get("fecha_salida"), datos.get("remision"),
         datos.get("certificado"), datos.get("placas_tracto"), datos.get("placas_tanque"),
         datos.get("peso_bruto_envio"), datos.get("tara_envio"), datos.get("peso_neto_envio"),
         datos.get("peso_bruto_recibo"), datos.get("tara_recibo"),
         datos.get("precio_tonelada"), datos.get("creado_por")))

def get_planta_remisiones(id_obra, producto=None, fi=None, ff=None):
    cfg = get_planta_config(id_obra)
    tol = float(cfg["tolerancia_remision_tn"])
    sql = "SELECT * FROM planta_remisiones WHERE id_obra=%s"
    p = [id_obra]
    if producto: sql += " AND producto=%s"; p.append(producto)
    if fi: sql += " AND fecha_llegada>=%s"; p.append(fi)
    if ff: sql += " AND fecha_llegada<=%s"; p.append(ff)
    sql += " ORDER BY fecha_llegada DESC, id DESC"
    filas = query(sql, p)
    acum = 0.0
    monto_acum = 0.0
    out = []
    for f in reversed(filas):
        neto_recibo = round(float(f["peso_bruto_recibo"] or 0) - float(f["tara_recibo"] or 0), 2)
        neto_envio = float(f["peso_neto_envio"] or 0)
        if not neto_envio and f.get("peso_bruto_envio") and f.get("tara_envio"):
            neto_envio = round(float(f["peso_bruto_envio"]) - float(f["tara_envio"]), 2)
        diferencia = round(neto_recibo - neto_envio, 2)
        acum += neto_recibo
        precio_tn = float(f["precio_tonelada"] or 0)
        monto = round(neto_recibo * precio_tn, 2) if precio_tn > 0 else None
        if monto:
            monto_acum += monto
        f["peso_neto_envio_calc"] = neto_envio
        f["peso_neto_recibo"] = neto_recibo
        f["diferencia"] = diferencia
        f["merma"] = abs(diferencia) > tol
        f["tn_acumuladas"] = round(acum, 2)
        f["monto"] = monto
        f["monto_acumulado"] = round(monto_acum, 2)
        out.insert(0, f)
    return out

# ── ALERTAS (equivalente a la hoja "Alertas Semana") ──
def get_planta_alertas(id_obra):
    cfg = get_planta_config(id_obra)
    stock = get_planta_stock_actual(id_obra)
    pendientes = query("""SELECT COUNT(*) AS n FROM planta_produccion
                           WHERE id_obra=%s AND validado=0""", (id_obra,), one=True)["n"]
    def nivel(valor, umbral, invertido=False):
        if valor is None: return "ok"
        if invertido:  # rendimiento: alerta si excede el máximo
            return "danger" if valor > umbral else "ok"
        if valor < umbral: return "danger"
        if valor < umbral * 1.3: return "warn"
        return "ok"
    alertas = []
    alertas.append({"indicador": "Asfalto restante", "valor": f"{stock['asf_final']:,.0f} lt"
                     + (f" — {stock['dias_stock_asf']} días de stock" if stock['dias_stock_asf'] else ""),
                     "accion": "Solicitar descarga si <5 días de stock",
                     "nivel": nivel(stock["asf_final"], float(cfg["umbral_asfalto_lt"]))})
    if stock["asf_rend_prom"]:
        rn = "danger" if stock["asf_rend_prom"] > float(cfg["rend_max_asfalto"]) \
             else ("warn" if stock["asf_rend_prom"] > float(cfg["rend_ref_asfalto"]) else "ok")
        alertas.append({"indicador": "Rendimiento asfalto (lts/m³)",
                         "valor": f"{stock['asf_rend_prom']} lts/m³ (ref: {cfg['rend_ref_asfalto']})",
                         "accion": "Revisar dosificación si excede la referencia", "nivel": rn})
    alertas.append({"indicador": "Combustible alterno restante", "valor": f"{stock['alt_final']:,.0f} lt",
                     "accion": "Solicitar suministro si bajo el umbral",
                     "nivel": nivel(stock["alt_final"], float(cfg["umbral_alterno_lt"]))})
    alertas.append({"indicador": "Emulsión restante", "valor": f"{stock['emu_final']:,.0f} lt",
                     "accion": "Revisar vs. programa de riego semanal",
                     "nivel": nivel(stock["emu_final"], float(cfg["umbral_emulsion_lt"]))})
    if stock["grava_final"] is not None:
        alertas.append({"indicador": "Grava restante", "valor": f"{stock['grava_final']:,.0f} m³",
                         "accion": "Solicitar acarreo de grava si bajo el umbral",
                         "nivel": nivel(stock["grava_final"], float(cfg["umbral_grava_m3"]))})
    if stock["arena_final"] is not None:
        alertas.append({"indicador": "Arena restante", "valor": f"{stock['arena_final']:,.0f} m³",
                         "accion": "Solicitar acarreo de arena si bajo el umbral",
                         "nivel": nivel(stock["arena_final"], float(cfg["umbral_arena_m3"]))})
    alertas.append({"indicador": "Registros sin validar", "valor": f"{pendientes} pendientes",
                     "accion": "Validar antes del viernes 12:00 pm",
                     "nivel": "warn" if pendientes > 0 else "ok"})
    remis_merma = query("""SELECT COUNT(*) AS n FROM planta_remisiones
                            WHERE id_obra=%s AND ABS(COALESCE(peso_bruto_recibo,0)-COALESCE(tara_recibo,0)
                                  -COALESCE(peso_neto_envio,0)) > %s""",
                         (id_obra, float(cfg["tolerancia_remision_tn"])), one=True)["n"]
    alertas.append({"indicador": "Remisiones con merma/exceso", "valor": f"{remis_merma} remisiones",
                     "accion": "Conciliar peso de envío vs. recibo antes de pagar",
                     "nivel": "danger" if remis_merma > 0 else "ok"})
    return alertas

def get_planta_alertas_todas(limite_por_obra=3):
    """Para el widget del dashboard global: alertas no-OK de todas las obras con planta activa."""
    obras_con_planta = query("""SELECT DISTINCT id_obra FROM planta_config""")
    out = []
    for row in obras_con_planta:
        oid = row["id_obra"]
        obra = get_obra(oid)
        if not obra: continue
        for a in get_planta_alertas(oid):
            if a["nivel"] != "ok":
                out.append({**a, "obra": obra["nombre"], "id_obra": oid})
    orden = {"danger": 0, "warn": 1}
    out.sort(key=lambda a: orden.get(a["nivel"], 2))
    return out


# ══════════════════════════════════════════════════════════════════
#  REPORTES DE OBRA (Excel subido por personal de obra)
#  Módulo de control: quién subió, cuándo, qué obra, semáforo faltantes
# ══════════════════════════════════════════════════════════════════

def _init_tabla_reportes_obra():
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS reportes_obra_excel (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            id_obra         INT NOT NULL,
            subido_por      INT NOT NULL,
            fecha_subida    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            semana          VARCHAR(20) DEFAULT NULL,
            nombre_archivo  VARCHAR(255) NOT NULL,
            archivo_disco   VARCHAR(255) NOT NULL,
            notas           TEXT DEFAULT NULL,
            INDEX idx_obra (id_obra),
            INDEX idx_fecha (fecha_subida)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)


def crear_reporte_obra_excel(id_obra, subido_por, semana, nombre_archivo, archivo_disco, notas=None):
    return execute("""
        INSERT INTO reportes_obra_excel (id_obra, subido_por, semana, nombre_archivo, archivo_disco, notas)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (id_obra, subido_por, semana, nombre_archivo, archivo_disco, notas))


def get_reportes_obra_excel(id_obra=None, limit=50):
    sql = """
        SELECT r.*, u.nombre AS subido_por_nombre, ob.nombre AS obra_nombre
        FROM reportes_obra_excel r
        LEFT JOIN usuarios u ON u.id = r.subido_por
        LEFT JOIN obras ob ON ob.id = r.id_obra
        WHERE 1=1
    """
    p = []
    if id_obra:
        sql += " AND r.id_obra=%s"; p.append(id_obra)
    sql += " ORDER BY r.fecha_subida DESC LIMIT %s"; p.append(limit)
    return query(sql, p)


def get_reporte_obra_excel_by_id(rid):
    return query("""
        SELECT r.*, u.nombre AS subido_por_nombre, ob.nombre AS obra_nombre
        FROM reportes_obra_excel r
        LEFT JOIN usuarios u ON u.id = r.subido_por
        LEFT JOIN obras ob ON ob.id = r.id_obra
        WHERE r.id=%s
    """, (rid,), one=True)


def get_obras_con_reporte_reciente(dias=10):
    """Devuelve set de id_obra que tienen al menos 1 reporte en los últimos N días."""
    rows = query("""
        SELECT DISTINCT id_obra FROM reportes_obra_excel
        WHERE fecha_subida >= NOW() - INTERVAL %s DAY
    """, (dias,))
    return {r["id_obra"] for r in rows}


def get_ultimo_reporte_por_obra():
    """Devuelve {id_obra: {fecha_subida, subido_por_nombre, nombre_archivo}}."""
    rows = query("""
        SELECT r.id_obra, r.fecha_subida, u.nombre AS subido_por_nombre, r.nombre_archivo
        FROM reportes_obra_excel r
        INNER JOIN (
            SELECT id_obra, MAX(fecha_subida) AS ultima
            FROM reportes_obra_excel GROUP BY id_obra
        ) ult ON ult.id_obra = r.id_obra AND ult.ultima = r.fecha_subida
        LEFT JOIN usuarios u ON u.id = r.subido_por
    """)
    return {r["id_obra"]: r for r in rows}


# ══════════════════════════════════════════════════════════════════
#  PERMISOS POR USUARIO POR OBRA — SOLO MÓDULO reportes_obra
#  Controla qué usuario puede hacer qué en cada obra específica.
#  Admin siempre tiene acceso total.
# ══════════════════════════════════════════════════════════════════

MODULOS_POR_OBRA = [
    ("reportes_obra", "Reportes de Obra (Excel)"),
    ("combustible", "Combustible / Reportes 360"),
    ("planta", "Planta de Asfalto"),
    ("documentos", "Documentos"),
    ("inspecciones", "Inspecciones"),
    ("incidentes", "Incidentes"),
    ("registro", "Registro Diario"),
    ("equipos", "Equipos y Maquinaria"),
    ("obras", "Obras"),
    ("mapa", "Mapa GPS"),
    ("exportar", "Exportar Excel"),
    ("acarreo", "Acarreo de Materiales"),
    ("rrhh", "Recursos Humanos"),
    ("requisiciones", "Requisiciones Semanales"),
    ("ordenes_compra", "Órdenes de Compra"),
]


def _init_tabla_permisos_usuario_obra():
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS permisos_usuario_obra (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            id_usuario  INT NOT NULL,
            id_obra     INT NOT NULL,
            modulo      VARCHAR(40) NOT NULL,
            crear       TINYINT(1) NOT NULL DEFAULT 0,
            leer        TINYINT(1) NOT NULL DEFAULT 0,
            editar      TINYINT(1) NOT NULL DEFAULT 0,
            eliminar    TINYINT(1) NOT NULL DEFAULT 0,
            UNIQUE KEY uq_usuario_obra_modulo (id_usuario, id_obra, modulo),
            INDEX idx_usuario (id_usuario),
            INDEX idx_obra (id_obra),
            INDEX idx_modulo (modulo)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)


def get_obras_permitidas(id_usuario, modulo, accion="leer"):
    rows = query(f"""
        SELECT p.id_obra, ob.nombre AS obra_nombre
        FROM permisos_usuario_obra p
        LEFT JOIN obras ob ON ob.id = p.id_obra
        WHERE p.id_usuario = %s AND p.modulo = %s AND p.{accion} = 1
        ORDER BY ob.nombre
    """, (id_usuario, modulo))
    return rows


def get_todos_permisos_usuario_obra(modulo=None):
    sql = """
        SELECT p.*, u.nombre AS usuario_nombre, u.email AS usuario_email,
               ob.nombre AS obra_nombre
        FROM permisos_usuario_obra p
        LEFT JOIN usuarios u ON u.id = p.id_usuario
        LEFT JOIN obras ob ON ob.id = p.id_obra
        WHERE 1=1
    """
    params = []
    if modulo:
        sql += " AND p.modulo = %s"
        params.append(modulo)
    sql += " ORDER BY u.nombre, p.modulo, ob.nombre"
    rows = query(sql, params)
    resultado = {}
    for r in rows:
        uid = r["id_usuario"]
        if uid not in resultado:
            resultado[uid] = {"nombre": r["usuario_nombre"], "email": r["usuario_email"], "permisos": []}
        resultado[uid]["permisos"].append(r)
    return resultado


def guardar_permiso_usuario_obra(id_usuario, id_obra, modulo, crear, leer, editar, eliminar):
    execute("""
        INSERT INTO permisos_usuario_obra (id_usuario, id_obra, modulo, crear, leer, editar, eliminar)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE crear=%s, leer=%s, editar=%s, eliminar=%s
    """, (id_usuario, id_obra, modulo, crear, leer, editar, eliminar,
          crear, leer, editar, eliminar))


def eliminar_permiso_usuario_obra(id_usuario, id_obra, modulo):
    execute("DELETE FROM permisos_usuario_obra WHERE id_usuario=%s AND id_obra=%s AND modulo=%s",
            (id_usuario, id_obra, modulo))


def usuario_puede(id_usuario, id_obra, modulo, accion="leer"):
    row = query(f"""
        SELECT {accion} AS permitido FROM permisos_usuario_obra
        WHERE id_usuario=%s AND id_obra=%s AND modulo=%s
    """, (id_usuario, id_obra, modulo), one=True)
    return bool(row and row["permitido"])


def get_permisos_usuario_obra(id_usuario, modulo=None):
    sql = """
        SELECT p.*, ob.nombre AS obra_nombre
        FROM permisos_usuario_obra p
        LEFT JOIN obras ob ON ob.id = p.id_obra
        WHERE p.id_usuario = %s
    """
    params = [id_usuario]
    if modulo:
        sql += " AND p.modulo = %s"
        params.append(modulo)
    sql += " ORDER BY p.modulo, ob.nombre"
    return query(sql, params)



    execute_ddl("""
        CREATE TABLE IF NOT EXISTS permisos_reportes_obra (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            id_usuario  INT NOT NULL,
            id_obra     INT NOT NULL,
            crear       TINYINT(1) NOT NULL DEFAULT 0,
            leer        TINYINT(1) NOT NULL DEFAULT 0,
            editar      TINYINT(1) NOT NULL DEFAULT 0,
            eliminar    TINYINT(1) NOT NULL DEFAULT 0,
            UNIQUE KEY uq_usuario_obra (id_usuario, id_obra),
            INDEX idx_usuario (id_usuario),
            INDEX idx_obra (id_obra)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)


def get_permisos_reportes_obra_usuario(id_usuario):
    """Devuelve {id_obra: {crear, leer, editar, eliminar}} para un usuario."""
    rows = query("""
        SELECT p.*, ob.nombre AS obra_nombre
        FROM permisos_reportes_obra p
        LEFT JOIN obras ob ON ob.id = p.id_obra
        WHERE p.id_usuario = %s
    """, (id_usuario,))
    return {r["id_obra"]: r for r in rows}


def get_obras_permitidas_reportes(id_usuario, accion="leer"):
    """Devuelve lista de id_obra donde el usuario tiene la acción habilitada."""
    rows = query(f"""
        SELECT p.id_obra, ob.nombre AS obra_nombre
        FROM permisos_reportes_obra p
        LEFT JOIN obras ob ON ob.id = p.id_obra
        WHERE p.id_usuario = %s AND p.{accion} = 1
        ORDER BY ob.nombre
    """, (id_usuario,))
    return rows


def get_todos_permisos_reportes_obra():
    """Para panel admin: todos los permisos asignados, agrupados por usuario."""
    rows = query("""
        SELECT p.*, u.nombre AS usuario_nombre, u.email AS usuario_email,
               ob.nombre AS obra_nombre
        FROM permisos_reportes_obra p
        LEFT JOIN usuarios u ON u.id = p.id_usuario
        LEFT JOIN obras ob ON ob.id = p.id_obra
        ORDER BY u.nombre, ob.nombre
    """)
    resultado = {}
    for r in rows:
        uid = r["id_usuario"]
        if uid not in resultado:
            resultado[uid] = {"nombre": r["usuario_nombre"], "email": r["usuario_email"], "obras": []}
        resultado[uid]["obras"].append(r)
    return resultado


def guardar_permiso_reportes_obra(id_usuario, id_obra, crear, leer, editar, eliminar):
    """Inserta o actualiza el permiso de un usuario para una obra."""
    execute("""
        INSERT INTO permisos_reportes_obra (id_usuario, id_obra, crear, leer, editar, eliminar)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE crear=%s, leer=%s, editar=%s, eliminar=%s
    """, (id_usuario, id_obra, crear, leer, editar, eliminar,
          crear, leer, editar, eliminar))


def eliminar_permiso_reportes_obra(id_usuario, id_obra):
    """Quita el acceso de un usuario a una obra."""
    execute("DELETE FROM permisos_reportes_obra WHERE id_usuario=%s AND id_obra=%s",
            (id_usuario, id_obra))


def usuario_puede_reportes_obra(id_usuario, id_obra, accion="leer"):
    """Verifica si un usuario puede realizar una acción en una obra específica."""
    row = query(f"""
        SELECT {accion} AS permitido FROM permisos_reportes_obra
        WHERE id_usuario=%s AND id_obra=%s
    """, (id_usuario, id_obra), one=True)
    return bool(row and row["permitido"])


def get_historial_gps(eco, fi=None, ff=None):
    """Historial de ubicaciones GPS desde la tabla estado."""
    if fi and ff:
        return query("""
            SELECT DATE(fecha_ultima_actualizacion) AS fecha,
                   latitud, longitud, nivel_combustible, horas_totales_horometro,
                   fecha_ultima_actualizacion
            FROM estado
            WHERE codigo_eco=%s AND latitud IS NOT NULL AND longitud IS NOT NULL
              AND fecha_ultima_actualizacion BETWEEN %s AND CONCAT(%s, ' 23:59:59')
            ORDER BY fecha_ultima_actualizacion
        """, (eco, fi, ff))
    else:
        return query("""
            SELECT DATE(fecha_ultima_actualizacion) AS fecha,
                   latitud, longitud, nivel_combustible, horas_totales_horometro,
                   fecha_ultima_actualizacion
            FROM estado
            WHERE codigo_eco=%s AND latitud IS NOT NULL AND longitud IS NOT NULL
              AND fecha_ultima_actualizacion >= CURDATE() - INTERVAL 30 DAY
            ORDER BY fecha_ultima_actualizacion
        """, (eco,))


def get_historial_nivel_combustible(eco, fi=None, ff=None):
    """Historial detallado de nivel de combustible (%) desde tabla estado.
    Retorna todos los registros hora por hora para visualizar cargas y consumo."""
    if fi and ff:
        return query("""
            SELECT fecha_ultima_actualizacion, nivel_combustible, capacidad_litros
            FROM estado
            WHERE codigo_eco=%s AND nivel_combustible IS NOT NULL
              AND fecha_ultima_actualizacion BETWEEN %s AND CONCAT(%s, ' 23:59:59')
            ORDER BY fecha_ultima_actualizacion
        """, (eco, fi, ff))
    else:
        return query("""
            SELECT fecha_ultima_actualizacion, nivel_combustible, capacidad_litros
            FROM estado
            WHERE codigo_eco=%s AND nivel_combustible IS NOT NULL
              AND fecha_ultima_actualizacion >= CURDATE() - INTERVAL 30 DAY
            ORDER BY fecha_ultima_actualizacion
        """, (eco,))


# ══════════════════════════════════════════════════════════════════
#  RECURSOS HUMANOS — DIRECTORIO DE EMPLEADOS, ASISTENCIA Y NÓMINA
# ══════════════════════════════════════════════════════════════════

DEPARTAMENTOS_RRHH = [
    "Operación", "Administración", "Maquinaria", "Topografía",
    "Laboratorio", "Seguridad", "Almacén", "Taller", "Oficina Central", "Otro"
]

TIPOS_CONTRATO = ["Planta", "Eventual", "Obra determinada", "Honorarios"]

def _init_tabla_rrhh():
    """Crea las tablas del módulo de Recursos Humanos."""
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS empleados (
            id                INT AUTO_INCREMENT PRIMARY KEY,
            numero_empleado   VARCHAR(20) DEFAULT NULL,
            nombre            VARCHAR(150) NOT NULL,
            apellido_paterno  VARCHAR(80) NOT NULL,
            apellido_materno  VARCHAR(80) DEFAULT NULL,
            curp              VARCHAR(18) DEFAULT NULL,
            rfc               VARCHAR(13) DEFAULT NULL,
            nss               VARCHAR(15) DEFAULT NULL COMMENT 'Número de Seguro Social',
            fecha_nacimiento  DATE DEFAULT NULL,
            telefono          VARCHAR(20) DEFAULT NULL,
            email             VARCHAR(120) DEFAULT NULL,
            direccion         TEXT DEFAULT NULL,
            puesto            VARCHAR(100) DEFAULT NULL,
            departamento      VARCHAR(60) DEFAULT NULL,
            id_obra           INT DEFAULT NULL COMMENT 'Obra asignada actualmente',
            tipo_contrato     VARCHAR(30) DEFAULT 'Planta',
            fecha_ingreso     DATE DEFAULT NULL,
            fecha_baja        DATE DEFAULT NULL,
            salario_diario    DECIMAL(10,2) DEFAULT NULL,
            salario_semanal   DECIMAL(10,2) DEFAULT NULL,
            banco             VARCHAR(60) DEFAULT NULL,
            cuenta_banco      VARCHAR(20) DEFAULT NULL,
            clabe             VARCHAR(18) DEFAULT NULL,
            contacto_emergencia VARCHAR(200) DEFAULT NULL,
            foto              VARCHAR(255) DEFAULT NULL,
            activo            TINYINT(1) NOT NULL DEFAULT 1,
            creado_por        INT DEFAULT NULL,
            creado_en         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_obra (id_obra),
            INDEX idx_departamento (departamento),
            INDEX idx_activo (activo)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS asistencia (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            id_empleado     INT NOT NULL,
            fecha           DATE NOT NULL,
            id_obra         INT DEFAULT NULL,
            entrada         TIME DEFAULT NULL,
            salida          TIME DEFAULT NULL,
            horas_normales  DECIMAL(4,2) DEFAULT NULL,
            horas_extra     DECIMAL(4,2) DEFAULT 0,
            tipo            ENUM('asistencia','falta','permiso','incapacidad','vacaciones','descanso') NOT NULL DEFAULT 'asistencia',
            observaciones   VARCHAR(255) DEFAULT NULL,
            registrado_por  INT DEFAULT NULL,
            creado_en       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_empleado_fecha (id_empleado, fecha),
            INDEX idx_fecha (fecha),
            INDEX idx_obra (id_obra),
            INDEX idx_tipo (tipo)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS escaneos_qr (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            id_empleado     INT NOT NULL,
            fecha           DATE NOT NULL,
            hora            TIME NOT NULL,
            tipo            ENUM('entrada','salida') NOT NULL,
            id_obra         INT DEFAULT NULL,
            foto_evidencia  VARCHAR(255) DEFAULT NULL,
            creado_en       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_empleado_fecha (id_empleado, fecha),
            INDEX idx_fecha (fecha)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS nomina (
            id                INT AUTO_INCREMENT PRIMARY KEY,
            id_empleado       INT NOT NULL,
            semana            VARCHAR(20) NOT NULL COMMENT 'Ej: 2026-W28',
            fecha_inicio      DATE NOT NULL,
            fecha_fin         DATE NOT NULL,
            dias_trabajados   INT NOT NULL DEFAULT 0,
            horas_normales    DECIMAL(6,2) DEFAULT 0,
            horas_extra       DECIMAL(6,2) DEFAULT 0,
            salario_base      DECIMAL(10,2) DEFAULT 0 COMMENT 'salario_diario * dias_trabajados',
            pago_horas_extra  DECIMAL(10,2) DEFAULT 0,
            bonos             DECIMAL(10,2) DEFAULT 0,
            deducciones       DECIMAL(10,2) DEFAULT 0,
            total_pagar       DECIMAL(10,2) DEFAULT 0,
            observaciones     TEXT DEFAULT NULL,
            estatus           ENUM('borrador','aprobada','pagada') NOT NULL DEFAULT 'borrador',
            generado_por      INT DEFAULT NULL,
            creado_en         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_empleado_semana (id_empleado, semana),
            INDEX idx_semana (semana),
            INDEX idx_estatus (estatus)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)


# ── EMPLEADOS ─────────────────────────────────────────────────────

def get_empleados(search=None, obra=None, departamento=None, activo=1):
    sql = """
        SELECT e.*, ob.nombre AS obra_nombre
        FROM empleados e
        LEFT JOIN obras ob ON ob.id = e.id_obra
        WHERE 1=1
    """
    p = []
    if activo is not None:
        sql += " AND e.activo=%s"; p.append(activo)
    if search:
        sql += " AND (e.nombre LIKE %s OR e.apellido_paterno LIKE %s OR e.numero_empleado LIKE %s OR e.curp LIKE %s)"
        p += [f"%{search}%"] * 4
    if obra:
        sql += " AND e.id_obra=%s"; p.append(obra)
    if departamento:
        sql += " AND e.departamento=%s"; p.append(departamento)
    sql += " ORDER BY e.apellido_paterno, e.nombre"
    return query(sql, p)


def get_empleado(eid):
    return query("""
        SELECT e.*, ob.nombre AS obra_nombre
        FROM empleados e LEFT JOIN obras ob ON ob.id = e.id_obra
        WHERE e.id=%s
    """, (eid,), one=True)


def crear_empleado(d):
    return execute("""
        INSERT INTO empleados
            (numero_empleado, nombre, apellido_paterno, apellido_materno,
             curp, rfc, nss, fecha_nacimiento, telefono, email, direccion,
             puesto, departamento, id_obra, tipo_contrato, fecha_ingreso,
             salario_diario, salario_semanal, tasa_hora_extra, banco, cuenta_banco, clabe,
             contacto_emergencia, foto, creado_por)
        VALUES (%(numero_empleado)s, %(nombre)s, %(apellido_paterno)s, %(apellido_materno)s,
                %(curp)s, %(rfc)s, %(nss)s, %(fecha_nacimiento)s, %(telefono)s, %(email)s, %(direccion)s,
                %(puesto)s, %(departamento)s, %(id_obra)s, %(tipo_contrato)s, %(fecha_ingreso)s,
                %(salario_diario)s, %(salario_semanal)s, %(tasa_hora_extra)s, %(banco)s, %(cuenta_banco)s, %(clabe)s,
                %(contacto_emergencia)s, %(foto)s, %(creado_por)s)
    """, d)


def actualizar_empleado(eid, d):
    d["id"] = eid
    execute("""
        UPDATE empleados SET
            numero_empleado=%(numero_empleado)s, nombre=%(nombre)s,
            apellido_paterno=%(apellido_paterno)s, apellido_materno=%(apellido_materno)s,
            curp=%(curp)s, rfc=%(rfc)s, nss=%(nss)s, fecha_nacimiento=%(fecha_nacimiento)s,
            telefono=%(telefono)s, email=%(email)s, direccion=%(direccion)s,
            puesto=%(puesto)s, departamento=%(departamento)s, id_obra=%(id_obra)s,
            tipo_contrato=%(tipo_contrato)s, fecha_ingreso=%(fecha_ingreso)s,
            salario_diario=%(salario_diario)s, salario_semanal=%(salario_semanal)s,
            tasa_hora_extra=%(tasa_hora_extra)s,
            banco=%(banco)s, cuenta_banco=%(cuenta_banco)s, clabe=%(clabe)s,
            contacto_emergencia=%(contacto_emergencia)s, foto=%(foto)s
        WHERE id=%(id)s
    """, d)


def baja_empleado(eid, fecha_baja):
    execute("UPDATE empleados SET activo=0, fecha_baja=%s WHERE id=%s", (fecha_baja, eid))


def reactivar_empleado(eid):
    execute("UPDATE empleados SET activo=1, fecha_baja=NULL WHERE id=%s", (eid,))


def get_kpis_rrhh():
    return query("""
        SELECT
            (SELECT COUNT(*) FROM empleados WHERE activo=1) AS total_activos,
            (SELECT COUNT(DISTINCT id_obra) FROM empleados WHERE activo=1 AND id_obra IS NOT NULL) AS obras_con_personal,
            (SELECT COUNT(*) FROM empleados WHERE activo=1 AND tipo_contrato='Planta') AS planta,
            (SELECT COUNT(*) FROM empleados WHERE activo=1 AND tipo_contrato='Eventual') AS eventuales,
            (SELECT COUNT(*) FROM asistencia WHERE fecha=CURDATE() AND tipo='asistencia') AS asistencias_hoy,
            (SELECT COUNT(*) FROM asistencia WHERE fecha=CURDATE() AND tipo='falta') AS faltas_hoy
    """, one=True)


# ── ASISTENCIA ────────────────────────────────────────────────────

def registrar_asistencia(id_empleado, fecha, id_obra, entrada, salida,
                          horas_normales, horas_extra, tipo, observaciones, registrado_por):
    return execute("""
        INSERT INTO asistencia
            (id_empleado, fecha, id_obra, entrada, salida, horas_normales,
             horas_extra, tipo, observaciones, registrado_por)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            id_obra=VALUES(id_obra), entrada=VALUES(entrada), salida=VALUES(salida),
            horas_normales=VALUES(horas_normales), horas_extra=VALUES(horas_extra),
            tipo=VALUES(tipo), observaciones=VALUES(observaciones),
            registrado_por=VALUES(registrado_por)
    """, (id_empleado, fecha, id_obra, entrada or None, salida or None,
          horas_normales, horas_extra, tipo, observaciones or None, registrado_por))


def get_empleado_por_numero(numero_empleado):
    """Busca un empleado activo por su numero_empleado."""
    emp = query("""
        SELECT e.*, ob.nombre AS obra_nombre
        FROM empleados e LEFT JOIN obras ob ON ob.id = e.id_obra
        WHERE e.numero_empleado=%s AND e.activo=1
    """, (str(numero_empleado).strip(),), one=True)
    if not emp:
        try:
            emp = query("""
                SELECT e.*, ob.nombre AS obra_nombre
                FROM empleados e LEFT JOIN obras ob ON ob.id = e.id_obra
                WHERE e.id=%s AND e.activo=1
            """, (int(numero_empleado),), one=True)
        except (ValueError, TypeError):
            pass
    return emp


def get_escaneos_hoy(id_empleado, fecha):
    """Obtiene todos los escaneos QR de un empleado en una fecha."""
    return query("""
        SELECT * FROM escaneos_qr
        WHERE id_empleado=%s AND fecha=%s
        ORDER BY hora ASC
    """, (id_empleado, fecha))


def registrar_escaneo_qr(id_empleado, fecha, hora, tipo, id_obra=None, foto_evidencia=None):
    """Registra un escaneo QR (entrada o salida)."""
    execute("""
        INSERT INTO escaneos_qr (id_empleado, fecha, hora, tipo, id_obra, foto_evidencia)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (id_empleado, fecha, hora, tipo, id_obra, foto_evidencia))
    # Actualizar tabla de asistencia con la primera entrada y última salida del día
    _actualizar_asistencia_desde_escaneos(id_empleado, fecha, id_obra)


def _actualizar_asistencia_desde_escaneos(id_empleado, fecha, id_obra=None):
    """Sincroniza la tabla asistencia con los escaneos QR del día."""
    escaneos = get_escaneos_hoy(id_empleado, fecha)
    if not escaneos:
        return
    primera_entrada = None
    ultima_salida = None
    for e in escaneos:
        if e["tipo"] == "entrada" and not primera_entrada:
            primera_entrada = e["hora"]
        if e["tipo"] == "salida":
            ultima_salida = e["hora"]

    # Calcular horas trabajadas totales (sumar pares entrada-salida)
    horas_total = 0.0
    entrada_actual = None
    for e in escaneos:
        if e["tipo"] == "entrada":
            entrada_actual = e["hora"]
        elif e["tipo"] == "salida" and entrada_actual:
            # Calcular diferencia en horas
            if hasattr(entrada_actual, 'total_seconds'):
                seg_entrada = entrada_actual.total_seconds()
            else:
                seg_entrada = 0
            if hasattr(e["hora"], 'total_seconds'):
                seg_salida = e["hora"].total_seconds()
            else:
                seg_salida = 0
            diff = (seg_salida - seg_entrada) / 3600.0
            if diff > 0:
                horas_total += diff
            entrada_actual = None

    n_entradas = sum(1 for e in escaneos if e["tipo"] == "entrada")
    n_salidas = sum(1 for e in escaneos if e["tipo"] == "salida")
    obs = f"QR: {n_entradas} entrada(s), {n_salidas} salida(s)"

    execute("""
        INSERT INTO asistencia (id_empleado, fecha, id_obra, entrada, salida,
                                horas_normales, horas_extra, tipo, observaciones)
        VALUES (%s, %s, %s, %s, %s, %s, 0, 'asistencia', %s)
        ON DUPLICATE KEY UPDATE
            entrada=VALUES(entrada), salida=VALUES(salida),
            horas_normales=VALUES(horas_normales), tipo='asistencia',
            observaciones=VALUES(observaciones)
    """, (id_empleado, fecha, id_obra, primera_entrada, ultima_salida,
          round(horas_total, 1), obs))


def get_asistencia_semana(fecha_inicio, fecha_fin, id_obra=None):
    """Devuelve asistencia de todos los empleados activos en un rango de fechas."""
    sql = """
        SELECT a.*, e.nombre, e.apellido_paterno, e.apellido_materno,
               e.numero_empleado, e.puesto, ob.nombre AS obra_nombre
        FROM asistencia a
        INNER JOIN empleados e ON e.id = a.id_empleado
        LEFT JOIN obras ob ON ob.id = a.id_obra
        WHERE a.fecha BETWEEN %s AND %s
    """
    p = [fecha_inicio, fecha_fin]
    if id_obra:
        sql += " AND a.id_obra=%s"; p.append(id_obra)
    sql += " ORDER BY e.apellido_paterno, e.nombre, a.fecha"
    return query(sql, p)


def get_asistencia_empleado(id_empleado, fecha_inicio, fecha_fin):
    return query("""
        SELECT * FROM asistencia
        WHERE id_empleado=%s AND fecha BETWEEN %s AND %s
        ORDER BY fecha
    """, (id_empleado, fecha_inicio, fecha_fin))


def get_resumen_asistencia_semana(fecha_inicio, fecha_fin, id_obra=None):
    """Resumen por empleado: días trabajados, faltas, horas extras en una semana."""
    sql = """
        SELECT e.id, e.numero_empleado, e.nombre, e.apellido_paterno, e.puesto,
               e.salario_diario, ob.nombre AS obra_nombre,
               SUM(CASE WHEN a.tipo='asistencia' THEN 1 ELSE 0 END) AS dias_trabajados,
               SUM(CASE WHEN a.tipo='falta' THEN 1 ELSE 0 END) AS faltas,
               SUM(CASE WHEN a.tipo='permiso' THEN 1 ELSE 0 END) AS permisos,
               SUM(CASE WHEN a.tipo='incapacidad' THEN 1 ELSE 0 END) AS incapacidades,
               COALESCE(SUM(a.horas_normales), 0) AS total_horas_normales,
               COALESCE(SUM(a.horas_extra), 0) AS total_horas_extra,
               GROUP_CONCAT(DISTINCT a.observaciones ORDER BY a.fecha SEPARATOR '; ') AS observaciones,
               (SELECT COUNT(*) FROM escaneos_qr eq
                WHERE eq.id_empleado=e.id AND eq.fecha BETWEEN %s AND %s
                AND eq.foto_evidencia IS NOT NULL) AS tiene_fotos
        FROM empleados e
        LEFT JOIN asistencia a ON a.id_empleado = e.id AND a.fecha BETWEEN %s AND %s
        LEFT JOIN obras ob ON ob.id = e.id_obra
        WHERE e.activo=1
    """
    p = [fecha_inicio, fecha_fin, fecha_inicio, fecha_fin]
    if id_obra:
        sql += " AND e.id_obra=%s"; p.append(id_obra)
    sql += " GROUP BY e.id ORDER BY e.apellido_paterno, e.nombre"
    return query(sql, p)


# ── NÓMINA ────────────────────────────────────────────────────────

def generar_nomina_semanal(semana, fecha_inicio, fecha_fin, generado_por, id_obra=None):
    """Genera registros de nómina para todos los empleados activos
    basándose en su asistencia de la semana."""
    empleados_activos = get_empleados(obra=id_obra, activo=1)
    count = 0
    for emp in empleados_activos:
        salario_diario = float(emp.get("salario_diario") or 0)
        if salario_diario <= 0:
            continue  # Sin salario configurado, no genera nómina

        # Obtener asistencia de la semana
        asist = get_asistencia_empleado(emp["id"], fecha_inicio, fecha_fin)
        dias_trab = sum(1 for a in asist if a["tipo"] == "asistencia")
        hrs_normales = sum(float(a.get("horas_normales") or 0) for a in asist)
        hrs_extra = sum(float(a.get("horas_extra") or 0) for a in asist)

        salario_base = round(salario_diario * dias_trab, 2)
        # Tasa de hora extra: configurable por empleado, default = (salario_diario / 8) * 2
        tasa_hora_extra = float(emp.get("tasa_hora_extra") or 0)
        if tasa_hora_extra <= 0:
            tasa_hora_extra = round((salario_diario / 8) * 2, 2)
        pago_extras = round(hrs_extra * tasa_hora_extra, 2)
        total = round(salario_base + pago_extras, 2)

        execute("""
            INSERT INTO nomina
                (id_empleado, semana, fecha_inicio, fecha_fin, dias_trabajados,
                 horas_normales, horas_extra, salario_base, pago_horas_extra,
                 total_pagar, generado_por)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
                dias_trabajados=VALUES(dias_trabajados),
                horas_normales=VALUES(horas_normales),
                horas_extra=VALUES(horas_extra),
                salario_base=VALUES(salario_base),
                pago_horas_extra=VALUES(pago_horas_extra),
                total_pagar=VALUES(total_pagar)
        """, (emp["id"], semana, fecha_inicio, fecha_fin, dias_trab,
              hrs_normales, hrs_extra, salario_base, pago_extras, total, generado_por))
        count += 1
    return count


def get_nomina_semanal(semana, id_obra=None):
    sql = """
        SELECT n.*, e.nombre, e.apellido_paterno, e.apellido_materno,
               e.numero_empleado, e.puesto, e.departamento, e.banco, e.cuenta_banco,
               ob.nombre AS obra_nombre
        FROM nomina n
        INNER JOIN empleados e ON e.id = n.id_empleado
        LEFT JOIN obras ob ON ob.id = e.id_obra
        WHERE n.semana=%s
    """
    p = [semana]
    if id_obra:
        sql += " AND e.id_obra=%s"; p.append(id_obra)
    sql += " ORDER BY e.apellido_paterno, e.nombre"
    return query(sql, p)


def get_nomina_empleado(id_empleado, limit=12):
    return query("""
        SELECT * FROM nomina WHERE id_empleado=%s
        ORDER BY fecha_inicio DESC LIMIT %s
    """, (id_empleado, limit))


def aprobar_nomina(semana):
    execute("UPDATE nomina SET estatus='aprobada' WHERE semana=%s AND estatus='borrador'", (semana,))


def marcar_nomina_pagada(semana):
    execute("UPDATE nomina SET estatus='pagada' WHERE semana=%s AND estatus='aprobada'", (semana,))


def get_kpis_nomina(semana):
    return query("""
        SELECT
            COUNT(*) AS total_empleados,
            SUM(dias_trabajados) AS total_dias,
            SUM(horas_extra) AS total_horas_extra,
            ROUND(SUM(salario_base), 2) AS total_salario_base,
            ROUND(SUM(pago_horas_extra), 2) AS total_extras,
            ROUND(SUM(total_pagar), 2) AS gran_total,
            SUM(estatus='borrador') AS borradores,
            SUM(estatus='aprobada') AS aprobadas,
            SUM(estatus='pagada') AS pagadas
        FROM nomina WHERE semana=%s
    """, (semana,), one=True)


def get_semanas_nomina():
    """Lista de semanas con nómina generada, más reciente primero."""
    rows = query("SELECT DISTINCT semana, MIN(fecha_inicio) AS inicio FROM nomina GROUP BY semana ORDER BY inicio DESC")
    return rows


# ══════════════════════════════════════════════════════════════════
#  REQUISICIONES SEMANALES — Control de Requerimientos por Obra
#  Formato ESMA-GREMIAL: partidas de gasto + nómina IMSS/sin IMSS + finiquitos
# ══════════════════════════════════════════════════════════════════

CATEGORIAS_REQUISICION = [
    "Administración", "Maquinaria", "Materiales", "Servicios", "Otros", "Comisiones", "Finiquitos"
]

CATEGORIAS_PERSONAL_IMSS = [
    "Personal Administrativo", "Personal Banobras/Capufe/SCT", "Laboratorio de Calidad",
    "Personal de Obra Civil - Cabos", "Personal de Obra Civil - Oficiales",
    "Personal de Obra Civil - Ayudantes", "Operadores Maquinaria",
    "Brigada de Topografía", "Seguridad Diurna", "Seguridad Nocturna", "Planta de Asfalto"
]

EMPRESAS_REQ = ["ESMA", "GREMIAL"]


def _init_tabla_requisiciones():
    """Crea las tablas del módulo de Requisiciones Semanales."""
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS requisiciones (
            id                INT AUTO_INCREMENT PRIMARY KEY,
            id_obra           INT DEFAULT NULL,
            empresa           VARCHAR(20) NOT NULL DEFAULT 'ESMA',
            semana            VARCHAR(20) DEFAULT NULL COMMENT 'Ej: 2026-W09',
            semana_num        INT DEFAULT NULL,
            fecha_inicio      DATE DEFAULT NULL,
            fecha_fin         DATE DEFAULT NULL,
            residente         VARCHAR(150) DEFAULT NULL,
            total_solicitado  DECIMAL(12,2) DEFAULT 0,
            total_autorizado  DECIMAL(12,2) DEFAULT 0,
            estatus           ENUM('borrador','enviado','aprobado','rechazado') NOT NULL DEFAULT 'borrador',
            observaciones     TEXT DEFAULT NULL,
            creado_por        INT DEFAULT NULL,
            aprobado_por      INT DEFAULT NULL,
            fecha_aprobacion  DATETIME DEFAULT NULL,
            creado_en         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_obra (id_obra),
            INDEX idx_semana (semana),
            INDEX idx_estatus (estatus),
            INDEX idx_empresa (empresa)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS requisicion_partidas (
            id                INT AUTO_INCREMENT PRIMARY KEY,
            id_requisicion    INT NOT NULL,
            categoria         VARCHAR(50) NOT NULL DEFAULT 'Otros',
            proveedor         VARCHAR(200) DEFAULT NULL,
            contacto_proveedor VARCHAR(200) DEFAULT NULL,
            concepto          TEXT DEFAULT NULL,
            periodo           VARCHAR(120) DEFAULT NULL,
            monto_solicitado  DECIMAL(12,2) DEFAULT 0,
            monto_autorizado  DECIMAL(12,2) DEFAULT 0,
            observaciones     VARCHAR(255) DEFAULT NULL,
            INDEX idx_req (id_requisicion),
            INDEX idx_cat (categoria)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS nomina_imss (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            id_requisicion      INT NOT NULL,
            id_empleado         INT DEFAULT NULL,
            nombre_empleado     VARCHAR(200) DEFAULT NULL,
            puesto              VARCHAR(100) DEFAULT NULL,
            categoria_personal  VARCHAR(80) DEFAULT NULL,
            fecha_ingreso       DATE DEFAULT NULL,
            dias                INT DEFAULT 0,
            salario_diario      DECIMAL(10,2) DEFAULT 0,
            salario_proporcional DECIMAL(10,2) DEFAULT 0,
            salario_semanal     DECIMAL(10,2) DEFAULT 0,
            horas_extra         DECIMAL(6,2) DEFAULT 0,
            costo_horas_extra   DECIMAL(10,2) DEFAULT 0,
            descanso_pagado     DECIMAL(10,2) DEFAULT 0,
            compensacion        DECIMAL(10,2) DEFAULT 0,
            pago_tiempo_extra   DECIMAL(10,2) DEFAULT 0,
            comidas             DECIMAL(10,2) DEFAULT 0,
            total_real          DECIMAL(10,2) DEFAULT 0,
            observaciones       VARCHAR(255) DEFAULT NULL,
            INDEX idx_req (id_requisicion),
            INDEX idx_emp (id_empleado)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS nomina_sin_imss (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            id_requisicion      INT NOT NULL,
            id_empleado         INT DEFAULT NULL,
            nombre_empleado     VARCHAR(200) DEFAULT NULL,
            puesto              VARCHAR(100) DEFAULT NULL,
            dias                INT DEFAULT 0,
            salario_diario      DECIMAL(10,2) DEFAULT 0,
            salario_proporcional DECIMAL(10,2) DEFAULT 0,
            salario_semanal     DECIMAL(10,2) DEFAULT 0,
            horas_extra         DECIMAL(6,2) DEFAULT 0,
            costo_horas_extra   DECIMAL(10,2) DEFAULT 0,
            compensacion        DECIMAL(10,2) DEFAULT 0,
            pago_tiempo_extra   DECIMAL(10,2) DEFAULT 0,
            comidas             DECIMAL(10,2) DEFAULT 0,
            total_real          DECIMAL(10,2) DEFAULT 0,
            observaciones       VARCHAR(255) DEFAULT NULL,
            INDEX idx_req (id_requisicion),
            INDEX idx_emp (id_empleado)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS finiquitos (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            id_requisicion  INT NOT NULL,
            id_obra         INT DEFAULT NULL,
            id_empleado     INT DEFAULT NULL,
            nombre_empleado VARCHAR(200) DEFAULT NULL,
            costo_empresa   DECIMAL(12,2) DEFAULT 0,
            INDEX idx_req (id_requisicion)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)


# ── REQUISICIONES CRUD ────────────────────────────────────────────

def crear_requisicion(d):
    d = dict(d)
    d.setdefault("id_codigo_costo", None)
    return execute("""
        INSERT INTO requisiciones
            (id_obra, empresa, semana, semana_num, fecha_inicio, fecha_fin,
             residente, total_solicitado, total_autorizado, estatus, observaciones,
             id_codigo_costo, creado_por)
        VALUES (%(id_obra)s, %(empresa)s, %(semana)s, %(semana_num)s, %(fecha_inicio)s, %(fecha_fin)s,
                %(residente)s, %(total_solicitado)s, %(total_autorizado)s, %(estatus)s,
                %(observaciones)s, %(id_codigo_costo)s, %(creado_por)s)
    """, d)


def get_requisiciones(id_obra=None, empresa=None, estatus=None, semana=None, limit=50):
    sql = """
        SELECT r.*, ob.nombre AS obra_nombre, u.nombre AS creado_por_nombre
        FROM requisiciones r
        LEFT JOIN obras ob ON ob.id = r.id_obra
        LEFT JOIN usuarios u ON u.id = r.creado_por
        WHERE 1=1
    """
    p = []
    if id_obra: sql += " AND r.id_obra=%s"; p.append(id_obra)
    if empresa: sql += " AND r.empresa=%s"; p.append(empresa)
    if estatus: sql += " AND r.estatus=%s"; p.append(estatus)
    if semana: sql += " AND r.semana=%s"; p.append(semana)
    sql += " ORDER BY r.creado_en DESC LIMIT %s"; p.append(limit)
    return query(sql, p)


def get_requisicion(rid):
    return query("""
        SELECT r.*, ob.nombre AS obra_nombre, u.nombre AS creado_por_nombre,
               ua.nombre AS aprobado_por_nombre
        FROM requisiciones r
        LEFT JOIN obras ob ON ob.id = r.id_obra
        LEFT JOIN usuarios u ON u.id = r.creado_por
        LEFT JOIN usuarios ua ON ua.id = r.aprobado_por
        WHERE r.id=%s
    """, (rid,), one=True)


def get_partidas_requisicion(id_requisicion):
    return query("SELECT * FROM requisicion_partidas WHERE id_requisicion=%s ORDER BY categoria, id",
                 (id_requisicion,))


def crear_partida_requisicion(d):
    return execute("""
        INSERT INTO requisicion_partidas
            (id_requisicion, categoria, proveedor, contacto_proveedor, concepto,
             periodo, monto_solicitado, monto_autorizado, observaciones)
        VALUES (%(id_requisicion)s, %(categoria)s, %(proveedor)s, %(contacto_proveedor)s,
                %(concepto)s, %(periodo)s, %(monto_solicitado)s, %(monto_autorizado)s, %(observaciones)s)
    """, d)


def get_nomina_imss_requisicion(id_requisicion):
    return query("SELECT * FROM nomina_imss WHERE id_requisicion=%s ORDER BY categoria_personal, id",
                 (id_requisicion,))


def crear_nomina_imss(d):
    return execute("""
        INSERT INTO nomina_imss
            (id_requisicion, id_empleado, nombre_empleado, puesto, categoria_personal,
             fecha_ingreso, dias, salario_diario, salario_proporcional, salario_semanal,
             horas_extra, costo_horas_extra, descanso_pagado, compensacion,
             pago_tiempo_extra, comidas, total_real, observaciones)
        VALUES (%(id_requisicion)s, %(id_empleado)s, %(nombre_empleado)s, %(puesto)s,
                %(categoria_personal)s, %(fecha_ingreso)s, %(dias)s, %(salario_diario)s,
                %(salario_proporcional)s, %(salario_semanal)s, %(horas_extra)s,
                %(costo_horas_extra)s, %(descanso_pagado)s, %(compensacion)s,
                %(pago_tiempo_extra)s, %(comidas)s, %(total_real)s, %(observaciones)s)
    """, d)


def get_nomina_sin_imss_requisicion(id_requisicion):
    return query("SELECT * FROM nomina_sin_imss WHERE id_requisicion=%s ORDER BY id",
                 (id_requisicion,))


def crear_nomina_sin_imss(d):
    return execute("""
        INSERT INTO nomina_sin_imss
            (id_requisicion, id_empleado, nombre_empleado, puesto,
             dias, salario_diario, salario_proporcional, salario_semanal,
             horas_extra, costo_horas_extra, compensacion,
             pago_tiempo_extra, comidas, total_real, observaciones)
        VALUES (%(id_requisicion)s, %(id_empleado)s, %(nombre_empleado)s, %(puesto)s,
                %(dias)s, %(salario_diario)s, %(salario_proporcional)s, %(salario_semanal)s,
                %(horas_extra)s, %(costo_horas_extra)s, %(compensacion)s,
                %(pago_tiempo_extra)s, %(comidas)s, %(total_real)s, %(observaciones)s)
    """, d)


def get_finiquitos_requisicion(id_requisicion):
    return query("SELECT * FROM finiquitos WHERE id_requisicion=%s ORDER BY id",
                 (id_requisicion,))


def crear_finiquito(d):
    return execute("""
        INSERT INTO finiquitos (id_requisicion, id_obra, id_empleado, nombre_empleado, costo_empresa)
        VALUES (%(id_requisicion)s, %(id_obra)s, %(id_empleado)s, %(nombre_empleado)s, %(costo_empresa)s)
    """, d)


def aprobar_requisicion(rid, aprobado_por, montos_autorizados=None):
    """Aprueba una requisición. Opcionalmente actualiza montos autorizados de partidas."""
    execute("""UPDATE requisiciones SET estatus='aprobado', aprobado_por=%s,
               fecha_aprobacion=NOW() WHERE id=%s""", (aprobado_por, rid))
    if montos_autorizados:
        for pid, monto in montos_autorizados.items():
            execute("UPDATE requisicion_partidas SET monto_autorizado=%s WHERE id=%s", (monto, pid))
    # Recalcular totales
    _recalcular_totales_requisicion(rid)
    # Enlazar a presupuesto si la requisición tiene código de costo asignado
    req = query("SELECT id_obra, id_codigo_costo, total_autorizado FROM requisiciones WHERE id=%s",
               (rid,), one=True)
    if req and req.get("id_codigo_costo") and req.get("id_obra"):
        monto = float(req["total_autorizado"] or 0)
        if monto > 0:
            execute("""UPDATE presupuesto_obra SET costos_reales = costos_reales + %s
                       WHERE id_obra=%s AND id_codigo_costo=%s""",
                    (monto, req["id_obra"], req["id_codigo_costo"]))


def rechazar_requisicion(rid, aprobado_por, observaciones=None):
    execute("""UPDATE requisiciones SET estatus='rechazado', aprobado_por=%s,
               fecha_aprobacion=NOW(), observaciones=%s WHERE id=%s""",
            (aprobado_por, observaciones, rid))


def enviar_requisicion(rid):
    execute("UPDATE requisiciones SET estatus='enviado' WHERE id=%s AND estatus='borrador'", (rid,))


def _recalcular_totales_requisicion(rid):
    """Recalcula total_solicitado y total_autorizado sumando partidas + nóminas + finiquitos."""
    partidas = query("""SELECT COALESCE(SUM(monto_solicitado),0) AS sol,
                               COALESCE(SUM(monto_autorizado),0) AS aut
                        FROM requisicion_partidas WHERE id_requisicion=%s""", (rid,), one=True)
    nom_imss = query("SELECT COALESCE(SUM(total_real),0) AS total FROM nomina_imss WHERE id_requisicion=%s",
                     (rid,), one=True)
    nom_sin = query("SELECT COALESCE(SUM(total_real),0) AS total FROM nomina_sin_imss WHERE id_requisicion=%s",
                    (rid,), one=True)
    finiq = query("SELECT COALESCE(SUM(costo_empresa),0) AS total FROM finiquitos WHERE id_requisicion=%s",
                  (rid,), one=True)
    total_sol = float(partidas["sol"]) + float(nom_imss["total"]) + float(nom_sin["total"]) + float(finiq["total"])
    total_aut = float(partidas["aut"]) + float(nom_imss["total"]) + float(nom_sin["total"]) + float(finiq["total"])
    execute("UPDATE requisiciones SET total_solicitado=%s, total_autorizado=%s WHERE id=%s",
            (round(total_sol, 2), round(total_aut, 2), rid))


def get_kpis_requisiciones(id_obra=None):
    sql_base = " WHERE 1=1"
    p = []
    if id_obra: sql_base += " AND id_obra=%s"; p.append(id_obra)
    return query(f"""
        SELECT
            COUNT(*) AS total,
            SUM(estatus='borrador') AS borradores,
            SUM(estatus='enviado') AS enviados,
            SUM(estatus='aprobado') AS aprobados,
            SUM(estatus='rechazado') AS rechazados,
            COALESCE(SUM(total_solicitado), 0) AS suma_solicitado,
            COALESCE(SUM(total_autorizado), 0) AS suma_autorizado
        FROM requisiciones{sql_base}
    """, p, one=True)


# ── DESCANSOS ─────────────────────────────────────────────────────

def _init_tabla_descansos():
    """Crea tabla de control de descansos (hojas DESCAN ESMA/GREMIAL)."""
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS requisicion_descansos (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            id_requisicion  INT NOT NULL,
            nombre          VARCHAR(200) DEFAULT NULL,
            puesto          VARCHAR(100) DEFAULT NULL,
            origen          VARCHAR(100) DEFAULT NULL,
            fecha_alta      DATE DEFAULT NULL,
            sueldo          DECIMAL(10,2) DEFAULT 0,
            descanso_1      DATE DEFAULT NULL,
            descanso_2      DATE DEFAULT NULL,
            descanso_3      DATE DEFAULT NULL,
            descanso_4      DATE DEFAULT NULL,
            descanso_5      DATE DEFAULT NULL,
            INDEX idx_req (id_requisicion)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)


def _init_columnas_firmas_requisicion():
    """Migración: agrega campos de firmas a requisiciones."""
    cols = [
        ("solicito_nombre", "VARCHAR(150) DEFAULT NULL"),
        ("solicito_puesto", "VARCHAR(100) DEFAULT NULL"),
        ("reviso_nombre", "VARCHAR(150) DEFAULT NULL"),
        ("reviso_puesto", "VARCHAR(100) DEFAULT NULL"),
        ("autorizo_nombre", "VARCHAR(150) DEFAULT NULL"),
        ("autorizo_puesto", "VARCHAR(100) DEFAULT NULL"),
    ]
    for col, tipo in cols:
        try:
            execute_ddl(f"ALTER TABLE requisiciones ADD COLUMN {col} {tipo}")
        except Exception:
            pass


def get_descansos_requisicion(id_requisicion):
    return query("SELECT * FROM requisicion_descansos WHERE id_requisicion=%s ORDER BY id",
                 (id_requisicion,))


def crear_descanso(d):
    return execute("""
        INSERT INTO requisicion_descansos
            (id_requisicion, nombre, puesto, origen, fecha_alta, sueldo,
             descanso_1, descanso_2, descanso_3, descanso_4, descanso_5)
        VALUES (%(id_requisicion)s, %(nombre)s, %(puesto)s, %(origen)s, %(fecha_alta)s,
                %(sueldo)s, %(descanso_1)s, %(descanso_2)s, %(descanso_3)s,
                %(descanso_4)s, %(descanso_5)s)
    """, d)


def actualizar_firmas_requisicion(rid, solicito_nombre=None, solicito_puesto=None,
                                   reviso_nombre=None, reviso_puesto=None,
                                   autorizo_nombre=None, autorizo_puesto=None):
    execute("""UPDATE requisiciones SET solicito_nombre=%s, solicito_puesto=%s,
               reviso_nombre=%s, reviso_puesto=%s, autorizo_nombre=%s, autorizo_puesto=%s
               WHERE id=%s""",
            (solicito_nombre, solicito_puesto, reviso_nombre, reviso_puesto,
             autorizo_nombre, autorizo_puesto, rid))


# ══════════════════════════════════════════════════════════════════
#  ÓRDENES DE COMPRA
#  Replicar el formato del Excel "Orden de Compra ESMA.xlsx":
#  cabecera (proveedor, obra, fechas, condiciones, moneda) +
#  tabla de partidas (pos, descripción, cantidad, unidad, P.U., importe)
#  + estados: borrador → enviado → autorizado → cancelado
# ══════════════════════════════════════════════════════════════════

TIPOS_PEDIDO_OC = ["Materiales", "Servicios"]
CONDICIONES_PAGO_OC = [
    "100% ANTICIPADO", "CRÉDITO", "10% ANTICIPO, 90% CONTRA ENTREGA",
    "20% ANTICIPO, 80% CONTRA ENTREGA", "30% ANTICIPO, 70% CONTRA ENTREGA",
    "50% ANTICIPO, 50% CONTRA ENTREGA", "70% ANTICIPO, 30% CONTRA ENTREGA",
]
MONEDAS_OC = ["MXN", "USD"]
FORMAS_PAGO_OC = ["003 - Transferencia electronica de fondos", "001 - Efectivo", "002 - Cheque nominativo"]
METODOS_PAGO_OC = ["PUE – Pago en una sola exhibición", "PPD – Pago en parcialidades o diferido"]
USOS_CFDI_OC = ["G03 Gastos Generales", "G01 Adquisición de mercancias", "I01 Construcciones", "I04 Equipo de cómputo y accesorios"]
ESTATUS_OC = ["borrador", "enviado", "autorizado", "rechazado", "cancelado"]


def _init_tabla_ordenes_compra():
    """Crea las tablas del módulo de Órdenes de Compra."""
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS ordenes_compra (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            numero_pedido       INT DEFAULT NULL COMMENT 'Consecutivo por proveedor/tipo',
            folio               VARCHAR(30) DEFAULT NULL COMMENT 'Folio único ej: OC-BAVISPE-001',
            fecha               DATE DEFAULT NULL,
            tipo_pedido         VARCHAR(30) DEFAULT 'Materiales',
            id_obra             INT DEFAULT NULL,
            descripcion_obra    TEXT DEFAULT NULL COMMENT 'Descripción larga del proyecto',
            proveedor           VARCHAR(200) DEFAULT NULL,
            rfc_proveedor       VARCHAR(15) DEFAULT NULL,
            contacto_pago       VARCHAR(150) DEFAULT NULL,
            telefono_proveedor  VARCHAR(40) DEFAULT NULL,
            email_proveedor     VARCHAR(120) DEFAULT NULL,
            condiciones_pago    VARCHAR(80) DEFAULT NULL,
            forma_pago          VARCHAR(80) DEFAULT NULL,
            metodo_pago         VARCHAR(80) DEFAULT NULL,
            uso_cfdi            VARCHAR(60) DEFAULT NULL,
            moneda              VARCHAR(5) DEFAULT 'MXN',
            tiempo_entrega      VARCHAR(60) DEFAULT NULL,
            subtotal            DECIMAL(14,2) DEFAULT 0,
            iva                 DECIMAL(14,2) DEFAULT 0,
            total               DECIMAL(14,2) DEFAULT 0,
            flete_logistica     DECIMAL(14,2) DEFAULT NULL,
            retencion           DECIMAL(14,2) DEFAULT NULL,
            importe_letra       TEXT DEFAULT NULL,
            responsable         VARCHAR(150) DEFAULT 'Elena de la Rocha Calderon',
            estatus             ENUM('borrador','enviado','autorizado','rechazado','cancelado') NOT NULL DEFAULT 'borrador',
            observaciones       TEXT DEFAULT NULL,
            creado_por          INT DEFAULT NULL,
            autorizado_por      INT DEFAULT NULL,
            fecha_autorizacion  DATETIME DEFAULT NULL,
            creado_en           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_obra (id_obra),
            INDEX idx_proveedor (proveedor(50)),
            INDEX idx_fecha (fecha),
            INDEX idx_estatus (estatus)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # Agregar columna id_codigo_costo si no existe (requerida por crear_orden_compra)
    try:
        execute_ddl("ALTER TABLE ordenes_compra ADD COLUMN id_codigo_costo INT DEFAULT NULL")
    except Exception:
        pass
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS ordenes_compra_partidas (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            id_orden        INT NOT NULL,
            pos             INT DEFAULT NULL,
            descripcion     TEXT DEFAULT NULL,
            cantidad        DECIMAL(12,3) DEFAULT NULL,
            unidad          VARCHAR(30) DEFAULT NULL,
            precio_unitario DECIMAL(14,2) DEFAULT NULL,
            importe         DECIMAL(14,2) DEFAULT NULL,
            INDEX idx_orden (id_orden)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)


# ── CRUD ÓRDENES DE COMPRA ─────────────────────────────────────────

def crear_orden_compra(d):
    """Crea la cabecera de la orden. Devuelve el id insertado."""
    d = dict(d)
    d.setdefault("id_codigo_costo", None)
    return execute("""
        INSERT INTO ordenes_compra
            (numero_pedido, folio, fecha, tipo_pedido, id_obra, descripcion_obra,
             proveedor, rfc_proveedor, contacto_pago, telefono_proveedor, email_proveedor,
             condiciones_pago, forma_pago, metodo_pago, uso_cfdi, moneda, tiempo_entrega,
             subtotal, iva, total, flete_logistica, retencion, importe_letra,
             responsable, estatus, observaciones, id_codigo_costo, creado_por)
        VALUES
            (%(numero_pedido)s, %(folio)s, %(fecha)s, %(tipo_pedido)s, %(id_obra)s,
             %(descripcion_obra)s, %(proveedor)s, %(rfc_proveedor)s, %(contacto_pago)s,
             %(telefono_proveedor)s, %(email_proveedor)s, %(condiciones_pago)s,
             %(forma_pago)s, %(metodo_pago)s, %(uso_cfdi)s, %(moneda)s, %(tiempo_entrega)s,
             %(subtotal)s, %(iva)s, %(total)s, %(flete_logistica)s, %(retencion)s,
             %(importe_letra)s, %(responsable)s, %(estatus)s, %(observaciones)s,
             %(id_codigo_costo)s, %(creado_por)s)
    """, d)


def get_ordenes_compra(id_obra=None, proveedor=None, estatus=None, fi=None, ff=None,
                       tipo_pedido=None, limit=100):
    sql = """
        SELECT oc.*, ob.nombre AS obra_nombre, u.nombre AS creado_por_nombre
        FROM ordenes_compra oc
        LEFT JOIN obras ob ON ob.id = oc.id_obra
        LEFT JOIN usuarios u ON u.id = oc.creado_por
        WHERE 1=1
    """
    p = []
    if id_obra:       sql += " AND oc.id_obra=%s";     p.append(id_obra)
    if proveedor:     sql += " AND oc.proveedor LIKE %s"; p.append(f"%{proveedor}%")
    if estatus:       sql += " AND oc.estatus=%s";     p.append(estatus)
    if fi:            sql += " AND oc.fecha>=%s";      p.append(fi)
    if ff:            sql += " AND oc.fecha<=%s";      p.append(ff)
    if tipo_pedido:   sql += " AND oc.tipo_pedido=%s"; p.append(tipo_pedido)
    sql += " ORDER BY oc.fecha DESC, oc.id DESC LIMIT %s"; p.append(limit)
    return query(sql, p)


def get_orden_compra(oid):
    return query("""
        SELECT oc.*, ob.nombre AS obra_nombre, ob.cliente AS obra_cliente,
               u.nombre AS creado_por_nombre, ua.nombre AS autorizado_por_nombre
        FROM ordenes_compra oc
        LEFT JOIN obras ob ON ob.id = oc.id_obra
        LEFT JOIN usuarios u ON u.id = oc.creado_por
        LEFT JOIN usuarios ua ON ua.id = oc.autorizado_por
        WHERE oc.id=%s
    """, (oid,), one=True)


def get_partidas_orden(id_orden):
    return query("""
        SELECT * FROM ordenes_compra_partidas
        WHERE id_orden=%s ORDER BY pos, id
    """, (id_orden,))


def crear_partida_orden(id_orden, pos, descripcion, cantidad, unidad, precio_unitario, importe):
    return execute("""
        INSERT INTO ordenes_compra_partidas
            (id_orden, pos, descripcion, cantidad, unidad, precio_unitario, importe)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
    """, (id_orden, pos, descripcion, cantidad, unidad, precio_unitario, importe))


def eliminar_partidas_orden(id_orden):
    execute("DELETE FROM ordenes_compra_partidas WHERE id_orden=%s", (id_orden,))


def recalcular_totales_oc(id_orden):
    """Recalcula subtotal, IVA y total a partir de las partidas."""
    res = query("""SELECT COALESCE(SUM(importe),0) AS subtotal
                   FROM ordenes_compra_partidas WHERE id_orden=%s""", (id_orden,), one=True)
    sub = round(float(res["subtotal"]), 2)
    iva = round(sub * 0.16, 2)
    total = round(sub + iva, 2)
    execute("UPDATE ordenes_compra SET subtotal=%s, iva=%s, total=%s WHERE id=%s",
            (sub, iva, total, id_orden))
    return sub, iva, total


def actualizar_orden_compra(oid, d):
    d = dict(d)
    d.setdefault("id_codigo_costo", None)
    execute("""
        UPDATE ordenes_compra SET
            fecha=%(fecha)s, tipo_pedido=%(tipo_pedido)s, id_obra=%(id_obra)s,
            descripcion_obra=%(descripcion_obra)s, proveedor=%(proveedor)s,
            rfc_proveedor=%(rfc_proveedor)s, contacto_pago=%(contacto_pago)s,
            telefono_proveedor=%(telefono_proveedor)s, email_proveedor=%(email_proveedor)s,
            condiciones_pago=%(condiciones_pago)s, forma_pago=%(forma_pago)s,
            metodo_pago=%(metodo_pago)s, uso_cfdi=%(uso_cfdi)s, moneda=%(moneda)s,
            tiempo_entrega=%(tiempo_entrega)s, flete_logistica=%(flete_logistica)s,
            retencion=%(retencion)s, importe_letra=%(importe_letra)s,
            responsable=%(responsable)s, observaciones=%(observaciones)s,
            id_codigo_costo=%(id_codigo_costo)s
        WHERE id=%(id)s
    """, d)


def autorizar_orden_compra(oid, autorizado_por):
    execute("""UPDATE ordenes_compra SET estatus='autorizado', autorizado_por=%s,
               fecha_autorizacion=NOW() WHERE id=%s""", (autorizado_por, oid))
    _aplicar_impacto_presupuesto_oc(oid, sumar=True)


def rechazar_orden_compra(oid, autorizado_por, obs=None):
    previo = query("SELECT estatus FROM ordenes_compra WHERE id=%s", (oid,), one=True)
    execute("""UPDATE ordenes_compra SET estatus='rechazado', autorizado_por=%s,
               fecha_autorizacion=NOW(), observaciones=%s WHERE id=%s""",
            (autorizado_por, obs, oid))
    if previo and previo["estatus"] == "autorizado":
        _aplicar_impacto_presupuesto_oc(oid, sumar=False)


def cancelar_orden_compra(oid, obs=None):
    previo = query("SELECT estatus FROM ordenes_compra WHERE id=%s", (oid,), one=True)
    execute("""UPDATE ordenes_compra SET estatus='cancelado', observaciones=%s WHERE id=%s""",
            (obs, oid))
    if previo and previo["estatus"] == "autorizado":
        _aplicar_impacto_presupuesto_oc(oid, sumar=False)


def enviar_orden_compra(oid):
    execute("""UPDATE ordenes_compra SET estatus='enviado' WHERE id=%s AND estatus='borrador'""",
            (oid,))


def get_siguiente_numero_oc(id_obra=None, proveedor=None):
    """Devuelve el siguiente número de pedido consecutivo (por obra o global)."""
    if id_obra:
        res = query("SELECT MAX(numero_pedido) AS mx FROM ordenes_compra WHERE id_obra=%s",
                    (id_obra,), one=True)
    else:
        res = query("SELECT MAX(numero_pedido) AS mx FROM ordenes_compra", one=True)
    return (int(res["mx"]) + 1) if res and res["mx"] else 1


def get_kpis_oc(id_obra=None, fi=None, ff=None):
    sql = "SELECT COUNT(*) AS total, SUM(estatus='borrador') AS borradores, SUM(estatus='enviado') AS enviados, SUM(estatus='autorizado') AS autorizados, SUM(estatus='rechazado') AS rechazados, SUM(estatus='cancelado') AS cancelados, COALESCE(SUM(total),0) AS suma_total, COALESCE(SUM(CASE WHEN estatus='autorizado' THEN total ELSE 0 END),0) AS suma_autorizado FROM ordenes_compra WHERE 1=1"
    p = []
    if id_obra: sql += " AND id_obra=%s"; p.append(id_obra)
    if fi:      sql += " AND fecha>=%s"; p.append(fi)
    if ff:      sql += " AND fecha<=%s"; p.append(ff)
    return query(sql, p, one=True)


def get_proveedores_oc():
    """Lista de proveedores para autocompletar en OC/Requisiciones: prioriza el
    catálogo maestro (proveedores) y complementa con los usados históricamente
    en OC que aún no estén dados de alta."""
    catalogo = query("SELECT razon_social AS proveedor FROM proveedores WHERE activo=1 ORDER BY razon_social")
    nombres = {r["proveedor"] for r in catalogo}
    historicos = query("SELECT DISTINCT proveedor FROM ordenes_compra WHERE proveedor IS NOT NULL ORDER BY proveedor")
    extra = [r["proveedor"] for r in historicos if r["proveedor"] not in nombres]
    return [r["proveedor"] for r in catalogo] + extra


def get_proveedores_autofill():
    """Datos del catálogo de proveedores para autocompletar RFC/contacto/condiciones
    de pago en el formulario de Orden de Compra vía JavaScript (keyed por razón social)."""
    filas = query("""
        SELECT razon_social, rfc, contacto, telefono, email, condiciones_pago_habitual
        FROM proveedores WHERE activo=1
    """)
    return {f["razon_social"]: {
        "rfc": f["rfc"] or "", "contacto": f["contacto"] or "",
        "telefono": f["telefono"] or "", "email": f["email"] or "",
        "condiciones": f["condiciones_pago_habitual"] or "",
    } for f in filas}


# ══════════════════════════════════════════════════════════════════
#  PROVEEDORES (catálogo maestro)
#  Formatos de referencia: "ALTAS PROVEEDORES", "Formato de evaluación
#  de proveedores ESMA-GREMIAL". Alimenta los combos de proveedor que
#  hoy son texto libre en Requisiciones y Órdenes de Compra.
# ══════════════════════════════════════════════════════════════════

TIPOS_PROVEEDOR = [
    "Obra y construcción", "Materiales", "Servicios",
    "Equipos, materiales y bienes en general", "Renta de maquinaria", "Otro",
]


def _init_tabla_proveedores():
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS proveedores (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            razon_social        VARCHAR(200) NOT NULL,
            tipo_persona        ENUM('fisica','moral') NOT NULL DEFAULT 'moral',
            rfc                 VARCHAR(15) DEFAULT NULL,
            tipo_proveedor      VARCHAR(60) DEFAULT NULL,
            direccion           VARCHAR(255) DEFAULT NULL,
            ciudad              VARCHAR(100) DEFAULT NULL,
            estado              VARCHAR(100) DEFAULT NULL,
            cp                  VARCHAR(10) DEFAULT NULL,
            pais                VARCHAR(60) DEFAULT 'México',
            telefono            VARCHAR(40) DEFAULT NULL,
            email               VARCHAR(120) DEFAULT NULL,
            contacto            VARCHAR(150) DEFAULT NULL,
            banco               VARCHAR(80) DEFAULT NULL,
            cuenta_clabe        VARCHAR(20) DEFAULT NULL,
            condiciones_pago_habitual VARCHAR(80) DEFAULT NULL,
            activo              TINYINT(1) NOT NULL DEFAULT 1,
            observaciones       TEXT DEFAULT NULL,
            creado_por          INT DEFAULT NULL,
            creado_en           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_rfc (rfc),
            INDEX idx_activo (activo),
            INDEX idx_razon (razon_social(50))
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS proveedor_evaluaciones (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            id_proveedor    INT NOT NULL,
            id_obra         INT DEFAULT NULL,
            evaluador       VARCHAR(150) DEFAULT NULL,
            fecha           DATE DEFAULT NULL,
            calidad         TINYINT DEFAULT NULL COMMENT '1-5',
            tiempo_entrega  TINYINT DEFAULT NULL COMMENT '1-5',
            precio          TINYINT DEFAULT NULL COMMENT '1-5',
            servicio        TINYINT DEFAULT NULL COMMENT '1-5',
            promedio        DECIMAL(4,2) DEFAULT NULL,
            comentarios     TEXT DEFAULT NULL,
            creado_en       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_prov (id_proveedor)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)


# ── CRUD Proveedores ────────────────────────────────────────────────

def get_proveedores(search=None, tipo=None, activo=1):
    sql = "SELECT * FROM proveedores WHERE 1=1"
    p = []
    if activo is not None:
        sql += " AND activo=%s"; p.append(activo)
    if tipo:
        sql += " AND tipo_proveedor=%s"; p.append(tipo)
    if search:
        sql += " AND (razon_social LIKE %s OR rfc LIKE %s)"
        p += [f"%{search}%", f"%{search}%"]
    sql += " ORDER BY razon_social"
    return query(sql, p)


def get_proveedor(pid):
    return query("SELECT * FROM proveedores WHERE id=%s", (pid,), one=True)


def crear_proveedor(d):
    return execute("""
        INSERT INTO proveedores
            (razon_social, tipo_persona, rfc, tipo_proveedor, direccion, ciudad, estado, cp,
             pais, telefono, email, contacto, banco, cuenta_clabe,
             condiciones_pago_habitual, observaciones, creado_por)
        VALUES
            (%(razon_social)s, %(tipo_persona)s, %(rfc)s, %(tipo_proveedor)s, %(direccion)s,
             %(ciudad)s, %(estado)s, %(cp)s, %(pais)s, %(telefono)s, %(email)s, %(contacto)s,
             %(banco)s, %(cuenta_clabe)s, %(condiciones_pago_habitual)s, %(observaciones)s,
             %(creado_por)s)
    """, d)


def actualizar_proveedor(pid, d):
    d = dict(d, id=pid)
    execute("""
        UPDATE proveedores SET
            razon_social=%(razon_social)s, tipo_persona=%(tipo_persona)s, rfc=%(rfc)s,
            tipo_proveedor=%(tipo_proveedor)s, direccion=%(direccion)s, ciudad=%(ciudad)s,
            estado=%(estado)s, cp=%(cp)s, pais=%(pais)s, telefono=%(telefono)s,
            email=%(email)s, contacto=%(contacto)s, banco=%(banco)s,
            cuenta_clabe=%(cuenta_clabe)s, condiciones_pago_habitual=%(condiciones_pago_habitual)s,
            observaciones=%(observaciones)s
        WHERE id=%(id)s
    """, d)


def cambiar_estado_proveedor(pid, activo):
    execute("UPDATE proveedores SET activo=%s WHERE id=%s", (activo, pid))


# ── EVALUACIÓN DE PROVEEDORES (sub-criterios ponderados) ─────────
# Formato de referencia: "Formato de evaluación de proveedores ESMA-GREMIAL.xlsx"
# Dos tipos: SERVICIO y MATERIALES, cada uno con rubros y sub-criterios distintos.
# Escala: 0-10 por sub-criterio. Resultado final: 0-100.
# 0-59 = NO CONFIABLE (Veto) | 60-79 = EN DESARROLLO | 80-100 = CONFIABLE

CRITERIOS_EVALUACION_SERVICIO = {
    "calidad": {
        "peso": 0.50,
        "nombre": "Calidad",
        "criterios": [
            ("serv_cal_cumplimiento", "Cumplimiento del trabajo o servicio realizado en su totalidad"),
            ("serv_cal_normas", "Cumplimiento de normas de seguridad, ambientales y prevención de riesgos"),
            ("serv_cal_infraestructura", "Infraestructura, equipos y herramientas adecuados"),
            ("serv_cal_materiales", "Calidad de materiales y suministros"),
            ("serv_cal_capacidad", "Capacidad técnica del personal"),
            ("serv_cal_comunicacion", "Comunicación clara ante eventualidades"),
            ("serv_cal_supervision", "Supervisión de los trabajos"),
        ],
    },
    "plazos": {
        "peso": 0.30,
        "nombre": "Plazos",
        "criterios": [
            ("serv_plz_programa", "Ejecución y cumplimiento del Programa de Obra"),
        ],
    },
    "ejecucion": {
        "peso": 0.20,
        "nombre": "Ejecución de Contrato y/o Pedido",
        "criterios": [
            ("serv_eje_estimaciones", "Adecuada elaboración de Estimaciones de Obra"),
            ("serv_eje_bitacora", "Desarrollo de bitácora de obra y actas de entrega"),
            ("serv_eje_especificaciones", "Apego a las especificaciones técnicas entregadas"),
            ("serv_eje_reuniones", "Asistencia a las reuniones y/o visitas técnicas"),
            ("serv_eje_almacenamiento", "Almacenamiento, resguardo y/o preservación de los recursos"),
        ],
    },
}

CRITERIOS_EVALUACION_MATERIALES = {
    "calidad": {
        "peso": 0.30,
        "nombre": "Calidad",
        "criterios": [
            ("mat_cal_materiales", "Calidad de materiales y suministros"),
            ("mat_cal_personal", "El personal técnico es idóneo para la actividad a realizar"),
            ("mat_cal_especificaciones", "Se cubrieron las especificaciones técnicas, seguridad y medio ambiente"),
            ("mat_cal_comunicacion", "Comunicación clara ante eventualidades"),
        ],
    },
    "administrativos": {
        "peso": 0.20,
        "nombre": "Aspectos Administrativos",
        "criterios": [
            ("mat_adm_documentos", "Entrega de certificados, seguridad, cartas garantía, cotizaciones, facturas y remisiones"),
        ],
    },
    "plazos": {
        "peso": 0.25,
        "nombre": "Plazos",
        "criterios": [
            ("mat_plz_entrega", "Entrega oportuna y puntual"),
            ("mat_plz_devoluciones", "Respuesta ante devoluciones y/o cambios"),
        ],
    },
    "logistica": {
        "peso": 0.25,
        "nombre": "Logística de Contrato y/o Pedido",
        "criterios": [
            ("mat_log_informes", "Informes de avance"),
            ("mat_log_reclamos", "Atención de reclamos"),
        ],
    },
}

RANGOS_EVALUACION = [
    (80, 100, "CONFIABLE", "badge-ok"),
    (60, 79.99, "EN DESARROLLO", "badge-wn"),
    (0, 59.99, "NO CONFIABLE (Veto)", "badge-dg"),
]


def clasificar_evaluacion(puntaje):
    """Devuelve (etiqueta, badge_class) según el puntaje 0-100."""
    for minimo, maximo, etiqueta, badge in RANGOS_EVALUACION:
        if minimo <= puntaje <= maximo:
            return etiqueta, badge
    return "NO CONFIABLE (Veto)", "badge-dg"


def _init_tabla_evaluacion_criterios():
    """Crea tabla para almacenar los sub-criterios de cada evaluación."""
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS proveedor_evaluacion_criterios (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            id_evaluacion   INT NOT NULL,
            codigo          VARCHAR(40) NOT NULL,
            puntaje         DECIMAL(4,1) NOT NULL DEFAULT 0 COMMENT '0-10',
            INDEX idx_eval (id_evaluacion),
            FOREIGN KEY (id_evaluacion) REFERENCES proveedor_evaluaciones(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # Migración: agregar columnas tipo_evaluacion y puntaje_final a proveedor_evaluaciones
    try:
        execute_ddl("ALTER TABLE proveedor_evaluaciones ADD COLUMN tipo_evaluacion ENUM('servicio','materiales') DEFAULT 'servicio' AFTER id_obra")
    except Exception:
        pass
    try:
        execute_ddl("ALTER TABLE proveedor_evaluaciones ADD COLUMN puntaje_final DECIMAL(5,2) DEFAULT NULL COMMENT '0-100' AFTER promedio")
    except Exception:
        pass
    try:
        execute_ddl("ALTER TABLE proveedor_evaluaciones ADD COLUMN clasificacion VARCHAR(30) DEFAULT NULL AFTER puntaje_final")
    except Exception:
        pass
    try:
        execute_ddl("ALTER TABLE proveedor_evaluaciones ADD COLUMN objeto_contrato TEXT DEFAULT NULL AFTER id_obra")
    except Exception:
        pass
    try:
        execute_ddl("ALTER TABLE proveedor_evaluaciones ADD COLUMN num_contrato VARCHAR(80) DEFAULT NULL AFTER objeto_contrato")
    except Exception:
        pass
    try:
        execute_ddl("ALTER TABLE proveedor_evaluaciones ADD COLUMN fecha_inicio DATE DEFAULT NULL AFTER fecha")
    except Exception:
        pass
    try:
        execute_ddl("ALTER TABLE proveedor_evaluaciones ADD COLUMN fecha_fin DATE DEFAULT NULL AFTER fecha_inicio")
    except Exception:
        pass


def get_evaluaciones_proveedor(id_proveedor):
    return query("""
        SELECT e.*, ob.nombre AS obra_nombre
        FROM proveedor_evaluaciones e
        LEFT JOIN obras ob ON ob.id = e.id_obra
        WHERE e.id_proveedor=%s ORDER BY e.fecha DESC
    """, (id_proveedor,))


def get_evaluacion_detalle(id_evaluacion):
    """Obtiene una evaluación con todos sus sub-criterios."""
    evaluacion = query("""
        SELECT e.*, ob.nombre AS obra_nombre, p.razon_social AS proveedor_nombre
        FROM proveedor_evaluaciones e
        LEFT JOIN obras ob ON ob.id = e.id_obra
        LEFT JOIN proveedores p ON p.id = e.id_proveedor
        WHERE e.id=%s
    """, (id_evaluacion,), one=True)
    if evaluacion:
        criterios = query("SELECT * FROM proveedor_evaluacion_criterios WHERE id_evaluacion=%s",
                          (id_evaluacion,))
        evaluacion["criterios_detalle"] = {c["codigo"]: float(c["puntaje"]) for c in criterios}
    return evaluacion


def calcular_puntaje_ponderado(tipo_evaluacion, criterios_dict):
    """Calcula el puntaje final (0-100) a partir de los sub-criterios.
    criterios_dict = {codigo: puntaje_0_10}
    Retorna (puntaje_final_0_100, detalle_por_rubro)."""
    config = CRITERIOS_EVALUACION_SERVICIO if tipo_evaluacion == "servicio" else CRITERIOS_EVALUACION_MATERIALES
    detalle_rubros = {}
    puntaje_total = 0.0

    for rubro_key, rubro in config.items():
        peso = rubro["peso"]
        codigos_rubro = [c[0] for c in rubro["criterios"]]
        puntajes_rubro = [float(criterios_dict.get(cod, 0)) for cod in codigos_rubro]
        promedio_rubro = sum(puntajes_rubro) / len(puntajes_rubro) if puntajes_rubro else 0
        # Normalizar a escala 0-100 (puntaje es 0-10, multiplicar por 10)
        promedio_rubro_100 = promedio_rubro * 10
        contribucion = promedio_rubro_100 * peso
        puntaje_total += contribucion
        detalle_rubros[rubro_key] = {
            "nombre": rubro["nombre"],
            "peso": peso,
            "promedio": round(promedio_rubro, 2),
            "promedio_100": round(promedio_rubro_100, 1),
            "contribucion": round(contribucion, 1),
        }

    return round(puntaje_total, 2), detalle_rubros


def crear_evaluacion_proveedor(d):
    """Crea una evaluación. Soporta tanto el formato viejo (4 campos simples)
    como el nuevo (sub-criterios desglosados).
    Si d contiene 'tipo_evaluacion' y 'criterios', usa el sistema nuevo."""
    tipo_eval = d.get("tipo_evaluacion", "servicio")
    criterios_dict = d.get("criterios", {})

    if criterios_dict:
        # Sistema nuevo: sub-criterios ponderados
        puntaje_final, _ = calcular_puntaje_ponderado(tipo_eval, criterios_dict)
        clasificacion_texto, _ = clasificar_evaluacion(puntaje_final)
        # Para compatibilidad, calcular promedio simple en escala 1-5
        promedio_5 = round(puntaje_final / 20, 2)  # 0-100 → 0-5

        d_insert = dict(d)
        d_insert["promedio"] = promedio_5
        d_insert["puntaje_final"] = puntaje_final
        d_insert["clasificacion"] = clasificacion_texto
        d_insert["tipo_evaluacion"] = tipo_eval
        d_insert.setdefault("calidad", 0)
        d_insert.setdefault("tiempo_entrega", 0)
        d_insert.setdefault("precio", 0)
        d_insert.setdefault("servicio", 0)
        d_insert.setdefault("objeto_contrato", None)
        d_insert.setdefault("num_contrato", None)
        d_insert.setdefault("fecha_inicio", None)
        d_insert.setdefault("fecha_fin", None)

        eid = execute("""
            INSERT INTO proveedor_evaluaciones
                (id_proveedor, id_obra, tipo_evaluacion, objeto_contrato, num_contrato,
                 evaluador, fecha, fecha_inicio, fecha_fin,
                 calidad, tiempo_entrega, precio, servicio, promedio,
                 puntaje_final, clasificacion, comentarios)
            VALUES
                (%(id_proveedor)s, %(id_obra)s, %(tipo_evaluacion)s, %(objeto_contrato)s,
                 %(num_contrato)s, %(evaluador)s, %(fecha)s, %(fecha_inicio)s, %(fecha_fin)s,
                 %(calidad)s, %(tiempo_entrega)s, %(precio)s, %(servicio)s, %(promedio)s,
                 %(puntaje_final)s, %(clasificacion)s, %(comentarios)s)
        """, d_insert)

        # Insertar sub-criterios
        for codigo, puntaje in criterios_dict.items():
            execute("""INSERT INTO proveedor_evaluacion_criterios (id_evaluacion, codigo, puntaje)
                       VALUES (%s, %s, %s)""", (eid, codigo, float(puntaje)))
        return eid
    else:
        # Sistema viejo: 4 campos simples (compatibilidad)
        promedio = round(sum([d["calidad"], d["tiempo_entrega"], d["precio"], d["servicio"]]) / 4, 2)
        d = dict(d, promedio=promedio)
        return execute("""
            INSERT INTO proveedor_evaluaciones
                (id_proveedor, id_obra, evaluador, fecha, calidad, tiempo_entrega, precio,
                 servicio, promedio, comentarios)
            VALUES
                (%(id_proveedor)s, %(id_obra)s, %(evaluador)s, %(fecha)s, %(calidad)s,
                 %(tiempo_entrega)s, %(precio)s, %(servicio)s, %(promedio)s, %(comentarios)s)
        """, d)


def get_calificacion_promedio_proveedor(id_proveedor):
    r = query("""SELECT AVG(promedio) AS prom, COUNT(*) AS n,
                        AVG(puntaje_final) AS prom_100
                 FROM proveedor_evaluaciones WHERE id_proveedor=%s""",
              (id_proveedor,), one=True)
    return r


# ══════════════════════════════════════════════════════════════════
#  CÓDIGOS DE COSTO Y PRESUPUESTO POR OBRA
#  Formatos de referencia: "Códigos de costo_Import_template GENERAL",
#  budget_details.csv, direct_costs.csv, Contratos.csv (exportaciones
#  tipo Procore). Conecta el gasto real de la obra (combustible, rentas,
#  requisiciones, OC) contra lo presupuestado por código de costo.
# ══════════════════════════════════════════════════════════════════

def _init_tabla_presupuesto():
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS codigos_costo (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            codigo      VARCHAR(30) NOT NULL COMMENT 'Ej: 1-02-020',
            nivel1      VARCHAR(10) DEFAULT NULL,
            nivel2      VARCHAR(10) DEFAULT NULL,
            nivel3      VARCHAR(10) DEFAULT NULL,
            nivel4      VARCHAR(10) DEFAULT NULL,
            nivel5      VARCHAR(10) DEFAULT NULL,
            descripcion VARCHAR(200) NOT NULL,
            tipo_costo  VARCHAR(60) DEFAULT NULL COMMENT 'Ej: MAQ - Maquinaria, CMB - Combustibles',
            activo      TINYINT(1) NOT NULL DEFAULT 1,
            UNIQUE KEY uq_codigo (codigo)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS presupuesto_obra (
            id                      INT AUTO_INCREMENT PRIMARY KEY,
            id_obra                 INT NOT NULL,
            id_codigo_costo         INT NOT NULL,
            monto_original          DECIMAL(14,2) DEFAULT 0,
            cambios_aprobados       DECIMAL(14,2) DEFAULT 0,
            monto_revisado          DECIMAL(14,2) DEFAULT 0,
            oc_aprobadas            DECIMAL(14,2) DEFAULT 0 COMMENT 'Comprometido en OC autorizadas',
            oc_pendientes           DECIMAL(14,2) DEFAULT 0,
            costos_reales           DECIMAL(14,2) DEFAULT 0 COMMENT 'Ejercido a la fecha',
            unidad_medida           VARCHAR(30) DEFAULT NULL,
            cantidad                DECIMAL(12,3) DEFAULT NULL,
            precio_unitario         DECIMAL(14,2) DEFAULT NULL,
            actualizado_en          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_obra_codigo (id_obra, id_codigo_costo),
            INDEX idx_obra (id_obra)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS presupuesto_costos_directos (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            id_obra             INT DEFAULT NULL,
            id_codigo_costo     INT DEFAULT NULL,
            fecha               DATE DEFAULT NULL,
            proveedor           VARCHAR(200) DEFAULT NULL,
            tipo                VARCHAR(60) DEFAULT NULL,
            factura_folio       VARCHAR(120) DEFAULT NULL,
            monto               DECIMAL(14,2) DEFAULT 0,
            fecha_recepcion     DATE DEFAULT NULL,
            fecha_pago          DATE DEFAULT NULL,
            creado_en           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_obra (id_obra),
            INDEX idx_codigo (id_codigo_costo)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)


# ── Catálogo de códigos de costo ───────────────────────────────────

def get_codigos_costo(search=None, activo=1):
    sql = "SELECT * FROM codigos_costo WHERE 1=1"
    p = []
    if activo is not None:
        sql += " AND activo=%s"; p.append(activo)
    if search:
        sql += " AND (codigo LIKE %s OR descripcion LIKE %s)"
        p += [f"%{search}%", f"%{search}%"]
    sql += " ORDER BY nivel1, nivel2, nivel3, nivel4, nivel5"
    return query(sql, p)


def get_codigo_costo(cid):
    return query("SELECT * FROM codigos_costo WHERE id=%s", (cid,), one=True)


def upsert_codigo_costo(codigo, descripcion, nivel1=None, nivel2=None, nivel3=None,
                         nivel4=None, nivel5=None, tipo_costo=None):
    """Crea el código de costo si no existe; si existe, actualiza la descripción."""
    existente = query("SELECT id FROM codigos_costo WHERE codigo=%s", (codigo,), one=True)
    if existente:
        execute("UPDATE codigos_costo SET descripcion=%s, tipo_costo=COALESCE(%s, tipo_costo) WHERE id=%s",
                (descripcion, tipo_costo, existente["id"]))
        return existente["id"]
    return execute("""
        INSERT INTO codigos_costo (codigo, nivel1, nivel2, nivel3, nivel4, nivel5, descripcion, tipo_costo)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (codigo, nivel1, nivel2, nivel3, nivel4, nivel5, descripcion, tipo_costo))


def importar_codigos_costo_excel(wb):
    """Parsea el formato 'Códigos de costo_Import_template GENERAL.xlsx':
    columnas Cost Code Level 1..5 + Descripción. Devuelve (creados, actualizados).
    Infiere tipo_costo del nivel 1 automáticamente."""
    TIPOS_POR_NIVEL1 = {
        "1": "MAQ - Maquinaria",
        "2": "CMB - Combustibles",
        "3": "MAT - Materiales",
        "4": "SUB - Subcontratos",
        "5": "ACR - Acarreos",
        "6": "NOM - Nómina",
        "7": "IND - Indirectos",
    }
    ws = wb.worksheets[0]
    creados = 0
    actualizados = 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or len(row) < 6:
            continue
        n1, n2, n3, n4, n5, desc = row[0], row[1], row[2], row[3], row[4], row[5]
        if not desc:
            continue
        niveles = [str(n).strip() for n in (n1, n2, n3, n4, n5) if n is not None and str(n).strip()]
        if not niveles:
            continue
        codigo = "-".join(niveles)
        # Inferir tipo de costo del nivel 1
        tipo_costo = TIPOS_POR_NIVEL1.get(str(n1).strip() if n1 else "", None)
        existente = query("SELECT id FROM codigos_costo WHERE codigo=%s", (codigo,), one=True)
        upsert_codigo_costo(
            codigo, str(desc).strip(),
            nivel1=str(n1).strip() if n1 else None, nivel2=str(n2).strip() if n2 else None,
            nivel3=str(n3).strip() if n3 else None, nivel4=str(n4).strip() if n4 else None,
            nivel5=str(n5).strip() if n5 else None, tipo_costo=tipo_costo,
        )
        if existente:
            actualizados += 1
        else:
            creados += 1
    return creados, actualizados


# ── Presupuesto por obra ───────────────────────────────────────────

def get_presupuesto_obra(id_obra):
    return query("""
        SELECT p.*, c.codigo, c.descripcion, c.tipo_costo
        FROM presupuesto_obra p
        JOIN codigos_costo c ON c.id = p.id_codigo_costo
        WHERE p.id_obra=%s
        ORDER BY c.nivel1, c.nivel2, c.nivel3, c.nivel4, c.nivel5
    """, (id_obra,))


def upsert_presupuesto_obra(id_obra, id_codigo_costo, d):
    existente = query("SELECT id FROM presupuesto_obra WHERE id_obra=%s AND id_codigo_costo=%s",
                      (id_obra, id_codigo_costo), one=True)
    d = dict(d, id_obra=id_obra, id_codigo_costo=id_codigo_costo)
    if existente:
        execute("""
            UPDATE presupuesto_obra SET
                monto_original=%(monto_original)s, cambios_aprobados=%(cambios_aprobados)s,
                monto_revisado=%(monto_revisado)s, oc_aprobadas=%(oc_aprobadas)s,
                oc_pendientes=%(oc_pendientes)s, costos_reales=%(costos_reales)s,
                unidad_medida=%(unidad_medida)s, cantidad=%(cantidad)s,
                precio_unitario=%(precio_unitario)s
            WHERE id_obra=%(id_obra)s AND id_codigo_costo=%(id_codigo_costo)s
        """, d)
        return existente["id"]
    return execute("""
        INSERT INTO presupuesto_obra
            (id_obra, id_codigo_costo, monto_original, cambios_aprobados, monto_revisado,
             oc_aprobadas, oc_pendientes, costos_reales, unidad_medida, cantidad, precio_unitario)
        VALUES
            (%(id_obra)s, %(id_codigo_costo)s, %(monto_original)s, %(cambios_aprobados)s,
             %(monto_revisado)s, %(oc_aprobadas)s, %(oc_pendientes)s, %(costos_reales)s,
             %(unidad_medida)s, %(cantidad)s, %(precio_unitario)s)
    """, d)


def importar_presupuesto_csv(id_obra, filas):
    """Recibe una lista de dicts (csv.DictReader) del formato budget_details.csv de
    Procore y hace upsert en presupuesto_obra. Devuelve el número de renglones procesados."""
    def _f(v):
        try:
            return float(str(v).replace(",", "").replace("$", "").strip() or 0)
        except (ValueError, TypeError):
            return 0.0

    procesados = 0
    for fila in filas:
        codigo = (fila.get("Código de presupuesto") or "").strip()
        desc = (fila.get("Descripción del código de presupuesto") or "").strip()
        if not codigo or not desc:
            continue
        n1 = (fila.get("Código de costo Nivel 1") or "").split(" - ")[0].strip() or None
        n2 = (fila.get("Código de costo Nivel 2") or "").split(" - ")[0].strip() or None
        n3 = (fila.get("Código de costo Nivel 3") or "").split(" - ")[0].strip() or None
        tipo_costo = (fila.get("Tipo de costo") or "").strip() or None
        id_codigo = upsert_codigo_costo(codigo, desc, nivel1=n1, nivel2=n2, nivel3=n3, tipo_costo=tipo_costo)
        upsert_presupuesto_obra(id_obra, id_codigo, {
            "monto_original": _f(fila.get("Monto del presupuesto original (MXN)")),
            "cambios_aprobados": _f(fila.get("Cambios de presupuesto aprobados (MXN)")),
            "monto_revisado": _f(fila.get("Presupuesto revisado (MXN)")),
            "oc_aprobadas": _f(fila.get("OC aprobadas (MXN)")),
            "oc_pendientes": _f(fila.get("OC pendientes (MXN)")),
            "costos_reales": _f(fila.get("Costos de trabajo a la fecha (MXN)")),
            "unidad_medida": (fila.get("Unidad de medida del presupuesto") or "").strip() or None,
            "cantidad": _f(fila.get("Cantidad por unidad del presupuesto")) or None,
            "precio_unitario": _f(fila.get("Precio unitario del presupuesto (MXN)")) or None,
        })
        procesados += 1
    return procesados


def importar_costos_directos_csv(id_obra, filas):
    """Importa direct_costs.csv (Fecha, Proveedor, Tipo, Factura n.º, Monto,
    Fecha de recepción, Fecha de pago) a presupuesto_costos_directos."""
    def _fecha(s):
        s = (s or "").strip()
        if not s:
            return None
        for fmt in ("%d/%m/%y", "%d/%m/%Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return None

    def _f(v):
        try:
            return float(str(v).replace(",", "").replace("$", "").strip() or 0)
        except (ValueError, TypeError):
            return 0.0

    procesados = 0
    for fila in filas:
        execute("""
            INSERT INTO presupuesto_costos_directos
                (id_obra, fecha, proveedor, tipo, factura_folio, monto, fecha_recepcion, fecha_pago)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            id_obra, _fecha(fila.get("Fecha")), (fila.get("Proveedor") or "").strip() or None,
            (fila.get("Tipo") or "").strip() or None, (fila.get("Factura n.º") or "").strip() or None,
            _f(fila.get("Monto")), _fecha(fila.get("Fecha de recepción")), _fecha(fila.get("Fecha de pago")),
        ))
        procesados += 1
    return procesados


def get_kpis_presupuesto(id_obra):
    r = query("""
        SELECT
            COALESCE(SUM(monto_revisado), 0) AS presupuestado,
            COALESCE(SUM(oc_aprobadas), 0)    AS comprometido,
            COALESCE(SUM(costos_reales), 0)   AS ejercido
        FROM presupuesto_obra WHERE id_obra=%s
    """, (id_obra,), one=True)
    presupuestado = float(r["presupuestado"] or 0)
    ejercido = float(r["ejercido"] or 0)
    r["pct_ejercido"] = round((ejercido / presupuestado * 100), 1) if presupuestado else 0
    return r


# ══════════════════════════════════════════════════════════════════
#  ENLACE DE PRESUPUESTO CON OC / REQUISICIONES
#  Agrega ordenes_compra.id_codigo_costo y requisiciones.id_codigo_costo.
#  Al autorizar/cancelar/rechazar una OC, o al aprobar una Requisición,
#  se actualiza presupuesto_obra automáticamente (si el código de costo
#  ya tiene una línea de presupuesto para esa obra).
# ══════════════════════════════════════════════════════════════════

def _init_columna_codigo_costo():
    """Migración: agrega id_codigo_costo a ordenes_compra y requisiciones."""
    try:
        execute_ddl("ALTER TABLE ordenes_compra ADD COLUMN id_codigo_costo INT DEFAULT NULL")
    except Exception:
        pass
    try:
        execute_ddl("ALTER TABLE requisiciones ADD COLUMN id_codigo_costo INT DEFAULT NULL")
    except Exception:
        pass


def _aplicar_impacto_presupuesto_oc(oid, sumar=True):
    """Suma o resta el total de una OC a presupuesto_obra.oc_aprobadas, si la OC
    tiene código de costo asignado y ya existe línea de presupuesto para esa obra."""
    oc = query("SELECT id_obra, id_codigo_costo, total FROM ordenes_compra WHERE id=%s", (oid,), one=True)
    if not oc or not oc["id_codigo_costo"] or not oc["id_obra"]:
        return
    monto = float(oc["total"] or 0)
    if monto <= 0:
        return
    if sumar:
        execute("""UPDATE presupuesto_obra SET oc_aprobadas = oc_aprobadas + %s
                   WHERE id_obra=%s AND id_codigo_costo=%s""",
                (monto, oc["id_obra"], oc["id_codigo_costo"]))
    else:
        execute("""UPDATE presupuesto_obra SET oc_aprobadas = GREATEST(oc_aprobadas - %s, 0)
                   WHERE id_obra=%s AND id_codigo_costo=%s""",
                (monto, oc["id_obra"], oc["id_codigo_costo"]))


def get_kpis_presupuesto_obra_codigo(id_obra, id_codigo_costo):
    """Consulta rápida usada por las pantallas de OC/Requisición para mostrar
    cuánto queda disponible de un código de costo antes de guardar."""
    return query("""
        SELECT monto_revisado, oc_aprobadas, costos_reales
        FROM presupuesto_obra WHERE id_obra=%s AND id_codigo_costo=%s
    """, (id_obra, id_codigo_costo), one=True)


# ══════════════════════════════════════════════════════════════════
#  ANÁLISIS DE COMPRA (comparación de cotizaciones)
#  Formato de referencia: "Formato de Análisis de Compra.xlsx" y las
#  cotizaciones reales en paralelo por proveedor (ej. "COTIZACIONES
#  REFUERZO ESTRUCTURAL..."). Al elegir la cotización ganadora, genera
#  directamente el borrador de la Orden de Compra correspondiente.
# ══════════════════════════════════════════════════════════════════

def _init_tabla_analisis_compra():
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS analisis_compra (
            id                      INT AUTO_INCREMENT PRIMARY KEY,
            id_obra                 INT DEFAULT NULL,
            descripcion             VARCHAR(255) NOT NULL,
            requisitante            VARCHAR(150) DEFAULT NULL,
            fecha                   DATE DEFAULT NULL,
            estatus                 ENUM('abierto','cerrado') NOT NULL DEFAULT 'abierto',
            id_cotizacion_ganadora  INT DEFAULT NULL,
            id_orden_generada       INT DEFAULT NULL,
            observaciones           TEXT DEFAULT NULL,
            creado_por              INT DEFAULT NULL,
            creado_en               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_obra (id_obra),
            INDEX idx_estatus (estatus)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS analisis_compra_cotizaciones (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            id_analisis         INT NOT NULL,
            proveedor           VARCHAR(200) NOT NULL,
            numero_cotizacion   VARCHAR(80) DEFAULT NULL,
            fecha_visita        DATE DEFAULT NULL,
            total               DECIMAL(14,2) DEFAULT 0,
            observaciones       TEXT DEFAULT NULL,
            INDEX idx_analisis (id_analisis)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS analisis_compra_items (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            id_cotizacion       INT NOT NULL,
            descripcion         TEXT DEFAULT NULL,
            cantidad            DECIMAL(12,3) DEFAULT NULL,
            unidad              VARCHAR(30) DEFAULT NULL,
            precio_unitario     DECIMAL(14,2) DEFAULT NULL,
            costo               DECIMAL(14,2) DEFAULT NULL,
            INDEX idx_cotizacion (id_cotizacion)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)


def get_analisis_compra(id_obra=None, estatus=None):
    sql = """
        SELECT a.*, ob.nombre AS obra_nombre,
               (SELECT COUNT(*) FROM analisis_compra_cotizaciones c WHERE c.id_analisis=a.id) AS num_cotizaciones
        FROM analisis_compra a
        LEFT JOIN obras ob ON ob.id = a.id_obra
        WHERE 1=1
    """
    p = []
    if id_obra: sql += " AND a.id_obra=%s"; p.append(id_obra)
    if estatus: sql += " AND a.estatus=%s"; p.append(estatus)
    sql += " ORDER BY a.creado_en DESC"
    return query(sql, p)


def get_analisis(aid):
    return query("""
        SELECT a.*, ob.nombre AS obra_nombre
        FROM analisis_compra a LEFT JOIN obras ob ON ob.id = a.id_obra
        WHERE a.id=%s
    """, (aid,), one=True)


def crear_analisis_compra(d):
    return execute("""
        INSERT INTO analisis_compra (id_obra, descripcion, requisitante, fecha, observaciones, creado_por)
        VALUES (%(id_obra)s, %(descripcion)s, %(requisitante)s, %(fecha)s, %(observaciones)s, %(creado_por)s)
    """, d)


def get_cotizaciones_analisis(id_analisis):
    cotizaciones = query("""
        SELECT * FROM analisis_compra_cotizaciones WHERE id_analisis=%s ORDER BY total
    """, (id_analisis,))
    for c in cotizaciones:
        c["items"] = query("SELECT * FROM analisis_compra_items WHERE id_cotizacion=%s ORDER BY id", (c["id"],))
    return cotizaciones


def crear_cotizacion_analisis(id_analisis, proveedor, numero_cotizacion, fecha_visita, observaciones, items):
    """items: lista de dicts {descripcion, cantidad, unidad, precio_unitario}."""
    cid = execute("""
        INSERT INTO analisis_compra_cotizaciones
            (id_analisis, proveedor, numero_cotizacion, fecha_visita, total, observaciones)
        VALUES (%s, %s, %s, %s, 0, %s)
    """, (id_analisis, proveedor, numero_cotizacion, fecha_visita, observaciones))
    total = 0
    for it in items:
        costo = round(float(it.get("cantidad") or 0) * float(it.get("precio_unitario") or 0), 2)
        total += costo
        execute("""
            INSERT INTO analisis_compra_items (id_cotizacion, descripcion, cantidad, unidad, precio_unitario, costo)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (cid, it.get("descripcion"), it.get("cantidad") or 0, it.get("unidad"),
              it.get("precio_unitario") or 0, costo))
    execute("UPDATE analisis_compra_cotizaciones SET total=%s WHERE id=%s", (round(total, 2), cid))
    return cid


def eliminar_cotizacion_analisis(id_cotizacion):
    execute("DELETE FROM analisis_compra_items WHERE id_cotizacion=%s", (id_cotizacion,))
    execute("DELETE FROM analisis_compra_cotizaciones WHERE id=%s", (id_cotizacion,))


def marcar_cotizacion_ganadora(id_analisis, id_cotizacion):
    execute("""UPDATE analisis_compra SET id_cotizacion_ganadora=%s, estatus='cerrado'
               WHERE id=%s""", (id_cotizacion, id_analisis))


def marcar_orden_generada(id_analisis, id_orden):
    execute("UPDATE analisis_compra SET id_orden_generada=%s WHERE id=%s", (id_orden, id_analisis))


def get_cotizacion(id_cotizacion):
    c = query("SELECT * FROM analisis_compra_cotizaciones WHERE id=%s", (id_cotizacion,), one=True)
    if c:
        c["items"] = query("SELECT * FROM analisis_compra_items WHERE id_cotizacion=%s ORDER BY id", (id_cotizacion,))
    return c


# ══════════════════════════════════════════════════════════════════
#  CAJA CHICA / REEMBOLSOS / VIÁTICOS  (Modelo Maestro-Detalle)
#  Formatos de referencia: "CAJA CHICA SEM 30-AMECAMECA", "Formato de
#  Cajas Chicas-Comprobaciones ESMA-GREMIAL" (hojas REEMBOLSO DE
#  GASTOS / VIATICOS / CAJA CHICA).
#  Estructura: Comprobación semanal (encabezado) → N Partidas (facturas)
# ══════════════════════════════════════════════════════════════════

TIPOS_CAJA_CHICA = [
    ("reembolso", "Reembolso de gastos"),
    ("viaticos", "Viáticos"),
    ("caja_chica", "Caja chica"),
]


def _init_tabla_caja_chica():
    """Crea las tablas del modelo maestro-detalle de caja chica."""
    # Tabla ENCABEZADO: comprobación semanal
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS caja_chica_comprobaciones (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            id_obra             INT DEFAULT NULL,
            empresa             VARCHAR(20) NOT NULL DEFAULT 'ESMA',
            tipo                ENUM('reembolso','viaticos','caja_chica') NOT NULL DEFAULT 'caja_chica',
            elaboro             VARCHAR(150) DEFAULT NULL,
            num_semana          INT DEFAULT NULL,
            semana_inicio       DATE DEFAULT NULL,
            semana_fin          DATE DEFAULT NULL,
            fecha_elaboracion   DATE DEFAULT NULL,
            fecha_deposito      DATE DEFAULT NULL,
            monto_deposito      DECIMAL(14,2) DEFAULT 0,
            observaciones       TEXT DEFAULT NULL,
            estatus             ENUM('borrador','enviado','aprobado','rechazado') NOT NULL DEFAULT 'borrador',
            creado_por          INT DEFAULT NULL,
            aprobado_por        INT DEFAULT NULL,
            fecha_aprobacion    DATETIME DEFAULT NULL,
            creado_en           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_obra (id_obra),
            INDEX idx_tipo (tipo),
            INDEX idx_estatus (estatus),
            INDEX idx_semana (num_semana)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # Tabla DETALLE: partidas (facturas/gastos)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS caja_chica_partidas (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            id_comprobacion     INT NOT NULL,
            es_deducible        TINYINT(1) NOT NULL DEFAULT 1,
            fecha               DATE DEFAULT NULL,
            proveedor           VARCHAR(200) DEFAULT NULL,
            concepto            VARCHAR(500) DEFAULT NULL,
            folio_fiscal        VARCHAR(80) DEFAULT NULL,
            rfc                 VARCHAR(15) DEFAULT NULL,
            subtotal            DECIMAL(14,2) DEFAULT 0,
            iva_pct             DECIMAL(5,2) DEFAULT 16.00,
            iva                 DECIMAL(14,2) DEFAULT 0,
            otras               DECIMAL(14,2) DEFAULT 0,
            ish                 DECIMAL(14,2) DEFAULT 0,
            ish_pct             DECIMAL(5,2) DEFAULT 0,
            retencion_isr       DECIMAL(14,2) DEFAULT 0,
            retencion_isr_pct   DECIMAL(5,2) DEFAULT 0,
            retencion_iva       DECIMAL(14,2) DEFAULT 0,
            retencion_iva_pct   DECIMAL(5,2) DEFAULT 0,
            total               DECIMAL(14,2) DEFAULT 0,
            nota_folio          VARCHAR(120) DEFAULT NULL,
            archivo_cfdi        VARCHAR(255) DEFAULT NULL COMMENT 'Nombre del archivo PDF del CFDI',
            estatus_pago        ENUM('no_pagado','pagado') NOT NULL DEFAULT 'no_pagado',
            INDEX idx_comp (id_comprobacion),
            INDEX idx_estatus_pago (estatus_pago)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # ALTER TABLE para bases existentes (agrega columnas si no existen)
    try:
        execute_ddl("ALTER TABLE caja_chica_partidas ADD COLUMN archivo_cfdi VARCHAR(255) DEFAULT NULL COMMENT 'Nombre del archivo PDF del CFDI'")
    except Exception:
        pass
    try:
        execute_ddl("ALTER TABLE caja_chica_partidas ADD COLUMN estatus_pago ENUM('no_pagado','pagado') NOT NULL DEFAULT 'no_pagado'")
    except Exception:
        pass
    # Mantener compatibilidad: tabla vieja puede existir, no la borramos


# ── CRUD Comprobaciones (encabezado) ─────────────────────────────

def get_caja_chica(id_obra=None, tipo=None, estatus=None, limit=100):
    """Listado de comprobaciones semanales."""
    sql = """
        SELECT c.*, ob.nombre AS obra_nombre, u.nombre AS creado_por_nombre,
               (SELECT COALESCE(SUM(p.total),0) FROM caja_chica_partidas p
                WHERE p.id_comprobacion=c.id AND p.es_deducible=1) AS total_deducible,
               (SELECT COALESCE(SUM(p.total),0) FROM caja_chica_partidas p
                WHERE p.id_comprobacion=c.id AND p.es_deducible=0) AS total_no_deducible,
               (SELECT COUNT(*) FROM caja_chica_partidas p
                WHERE p.id_comprobacion=c.id) AS num_partidas
        FROM caja_chica_comprobaciones c
        LEFT JOIN obras ob ON ob.id = c.id_obra
        LEFT JOIN usuarios u ON u.id = c.creado_por
        WHERE 1=1
    """
    p = []
    if id_obra: sql += " AND c.id_obra=%s"; p.append(id_obra)
    if tipo: sql += " AND c.tipo=%s"; p.append(tipo)
    if estatus: sql += " AND c.estatus=%s"; p.append(estatus)
    sql += " ORDER BY c.num_semana DESC, c.id DESC LIMIT %s"; p.append(limit)
    return query(sql, p)


def get_comprobacion_caja_chica(cid):
    """Detalle del encabezado de una comprobación."""
    return query("""
        SELECT c.*, ob.nombre AS obra_nombre,
               u.nombre AS creado_por_nombre
        FROM caja_chica_comprobaciones c
        LEFT JOIN obras ob ON ob.id = c.id_obra
        LEFT JOIN usuarios u ON u.id = c.creado_por
        WHERE c.id=%s
    """, (cid,), one=True)


def crear_comprobacion_caja_chica(d):
    return execute("""
        INSERT INTO caja_chica_comprobaciones
            (id_obra, empresa, tipo, elaboro, num_semana, semana_inicio, semana_fin,
             fecha_elaboracion, fecha_deposito, monto_deposito, observaciones, estatus, creado_por)
        VALUES
            (%(id_obra)s, %(empresa)s, %(tipo)s, %(elaboro)s, %(num_semana)s,
             %(semana_inicio)s, %(semana_fin)s, %(fecha_elaboracion)s,
             %(fecha_deposito)s, %(monto_deposito)s, %(observaciones)s, %(estatus)s, %(creado_por)s)
    """, d)


def actualizar_comprobacion_caja_chica(cid, d):
    execute("""
        UPDATE caja_chica_comprobaciones SET
            id_obra=%(id_obra)s, empresa=%(empresa)s, tipo=%(tipo)s, elaboro=%(elaboro)s,
            num_semana=%(num_semana)s, semana_inicio=%(semana_inicio)s, semana_fin=%(semana_fin)s,
            fecha_elaboracion=%(fecha_elaboracion)s, fecha_deposito=%(fecha_deposito)s,
            monto_deposito=%(monto_deposito)s, observaciones=%(observaciones)s
        WHERE id=%(id)s
    """, {**d, "id": cid})


def enviar_comprobacion_caja_chica(cid):
    execute("UPDATE caja_chica_comprobaciones SET estatus='enviado' WHERE id=%s AND estatus='borrador'", (cid,))


def aprobar_comprobacion_caja_chica(cid, aprobado_por):
    execute("""UPDATE caja_chica_comprobaciones SET estatus='aprobado', aprobado_por=%s,
               fecha_aprobacion=NOW() WHERE id=%s""", (aprobado_por, cid))


def rechazar_comprobacion_caja_chica(cid, aprobado_por, obs=None):
    execute("""UPDATE caja_chica_comprobaciones SET estatus='rechazado', aprobado_por=%s,
               fecha_aprobacion=NOW(), observaciones=%s WHERE id=%s""", (aprobado_por, obs, cid))


# ── CRUD Partidas (detalle de facturas) ──────────────────────────

def get_partidas_caja_chica(id_comprobacion, solo_deducibles=None):
    """Obtiene las partidas de una comprobación."""
    sql = "SELECT * FROM caja_chica_partidas WHERE id_comprobacion=%s"
    p = [id_comprobacion]
    if solo_deducibles is True:
        sql += " AND es_deducible=1"
    elif solo_deducibles is False:
        sql += " AND es_deducible=0"
    sql += " ORDER BY fecha, id"
    return query(sql, p)


def get_partida_caja_chica(pid):
    return query("SELECT * FROM caja_chica_partidas WHERE id=%s", (pid,), one=True)


def crear_partida_caja_chica(d):
    return execute("""
        INSERT INTO caja_chica_partidas
            (id_comprobacion, es_deducible, fecha, proveedor, concepto, folio_fiscal, rfc,
             subtotal, iva_pct, iva, otras, ish, ish_pct,
             retencion_isr, retencion_isr_pct, retencion_iva, retencion_iva_pct,
             total, nota_folio, archivo_cfdi, estatus_pago)
        VALUES
            (%(id_comprobacion)s, %(es_deducible)s, %(fecha)s, %(proveedor)s, %(concepto)s,
             %(folio_fiscal)s, %(rfc)s, %(subtotal)s, %(iva_pct)s, %(iva)s, %(otras)s,
             %(ish)s, %(ish_pct)s, %(retencion_isr)s, %(retencion_isr_pct)s,
             %(retencion_iva)s, %(retencion_iva_pct)s, %(total)s, %(nota_folio)s,
             %(archivo_cfdi)s, %(estatus_pago)s)
    """, d)


def actualizar_partida_caja_chica(pid, d):
    execute("""
        UPDATE caja_chica_partidas SET
            es_deducible=%(es_deducible)s, fecha=%(fecha)s, proveedor=%(proveedor)s,
            concepto=%(concepto)s, folio_fiscal=%(folio_fiscal)s, rfc=%(rfc)s,
            subtotal=%(subtotal)s, iva_pct=%(iva_pct)s, iva=%(iva)s, otras=%(otras)s,
            ish=%(ish)s, ish_pct=%(ish_pct)s, retencion_isr=%(retencion_isr)s,
            retencion_isr_pct=%(retencion_isr_pct)s, retencion_iva=%(retencion_iva)s,
            retencion_iva_pct=%(retencion_iva_pct)s, total=%(total)s, nota_folio=%(nota_folio)s,
            estatus_pago=%(estatus_pago)s
        WHERE id=%(id)s
    """, {**d, "id": pid})


def actualizar_cfdi_partida(pid, archivo_cfdi):
    """Actualiza solo el archivo CFDI de una partida."""
    execute("UPDATE caja_chica_partidas SET archivo_cfdi=%s WHERE id=%s", (archivo_cfdi, pid))


def actualizar_estatus_pago_partida(pid, estatus_pago):
    """Cambia el estatus de pago de una partida (pagado/no_pagado)."""
    execute("UPDATE caja_chica_partidas SET estatus_pago=%s WHERE id=%s", (estatus_pago, pid))


def eliminar_partida_caja_chica(pid):
    execute("DELETE FROM caja_chica_partidas WHERE id=%s", (pid,))


# ── Resúmenes fiscales ───────────────────────────────────────────

def get_resumen_caja_chica(id_comprobacion):
    """Calcula totales fiscales de una comprobación (como el Excel)."""
    return query("""
        SELECT
            COALESCE(SUM(CASE WHEN es_deducible=1 THEN total ELSE 0 END), 0) AS total_deducible,
            COALESCE(SUM(CASE WHEN es_deducible=0 THEN total ELSE 0 END), 0) AS total_no_deducible,
            COALESCE(SUM(CASE WHEN es_deducible=1 THEN subtotal ELSE 0 END), 0) AS base_iva,
            COALESCE(SUM(CASE WHEN es_deducible=1 THEN iva ELSE 0 END), 0) AS total_iva,
            COALESCE(SUM(CASE WHEN es_deducible=1 THEN retencion_iva ELSE 0 END), 0) AS total_retencion_iva,
            COALESCE(SUM(CASE WHEN es_deducible=1 THEN retencion_isr ELSE 0 END), 0) AS total_retencion_isr,
            COALESCE(SUM(CASE WHEN es_deducible=1 THEN ish ELSE 0 END), 0) AS total_ish,
            COALESCE(SUM(CASE WHEN es_deducible=1 THEN otras ELSE 0 END), 0) AS total_otras,
            COUNT(*) AS num_partidas
        FROM caja_chica_partidas WHERE id_comprobacion=%s
    """, (id_comprobacion,), one=True)


# ── KPIs generales ───────────────────────────────────────────────

def get_kpis_caja_chica(id_obra=None, tipo=None):
    sql = " WHERE 1=1"
    p = []
    if id_obra: sql += " AND c.id_obra=%s"; p.append(id_obra)
    if tipo: sql += " AND c.tipo=%s"; p.append(tipo)
    return query(f"""
        SELECT COUNT(*) AS total,
               SUM(c.estatus='enviado') AS pendientes,
               SUM(c.estatus='aprobado') AS aprobados,
               COALESCE((SELECT SUM(p.total) FROM caja_chica_partidas p
                         JOIN caja_chica_comprobaciones c2 ON c2.id=p.id_comprobacion
                         WHERE 1=1 {' AND c2.id_obra='+str(int(id_obra)) if id_obra else ''}
                         {' AND c2.tipo="'+tipo+'"' if tipo else ''}), 0) AS suma_total
        FROM caja_chica_comprobaciones c{sql}
    """, p, one=True)


# ── Compatibilidad con tabla vieja (migración suave) ─────────────
# Las funciones viejas se mantienen por si hay datos en caja_chica_movimientos

def get_movimiento_caja_chica(mid):
    return query("""
        SELECT cc.*, ob.nombre AS obra_nombre
        FROM caja_chica_movimientos cc LEFT JOIN obras ob ON ob.id = cc.id_obra
        WHERE cc.id=%s
    """, (mid,), one=True)


def crear_movimiento_caja_chica(d):
    return execute("""
        INSERT INTO caja_chica_movimientos
            (id_obra, empresa, tipo, fecha, concepto, proveedor, monto, iva,
             comprobado, responsable, observaciones, estatus, creado_por)
        VALUES
            (%(id_obra)s, %(empresa)s, %(tipo)s, %(fecha)s, %(concepto)s, %(proveedor)s,
             %(monto)s, %(iva)s, %(comprobado)s, %(responsable)s, %(observaciones)s,
             %(estatus)s, %(creado_por)s)
    """, d)


def enviar_movimiento_caja_chica(mid):
    execute("UPDATE caja_chica_movimientos SET estatus='enviado' WHERE id=%s AND estatus='borrador'", (mid,))


def aprobar_movimiento_caja_chica(mid, aprobado_por):
    execute("""UPDATE caja_chica_movimientos SET estatus='aprobado', aprobado_por=%s,
               fecha_aprobacion=NOW() WHERE id=%s""", (aprobado_por, mid))


def rechazar_movimiento_caja_chica(mid, aprobado_por, obs=None):
    execute("""UPDATE caja_chica_movimientos SET estatus='rechazado', aprobado_por=%s,
               fecha_aprobacion=NOW(), observaciones=%s WHERE id=%s""", (aprobado_por, obs, mid))


# ══════════════════════════════════════════════════════════════════
#  SOLICITUD DE CANCELACIÓN DE CFDI
#  Formato de referencia: "Formato de Solicitud de Cancelación.xlsx"
# ══════════════════════════════════════════════════════════════════

def _init_tabla_cancelaciones_cfdi():
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS solicitudes_cancelacion (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            id_obra             INT DEFAULT NULL,
            empresa             VARCHAR(20) NOT NULL DEFAULT 'ESMA',
            folio_fiscal        VARCHAR(80) DEFAULT NULL,
            razon_social        VARCHAR(200) DEFAULT NULL,
            rfc                 VARCHAR(15) DEFAULT NULL,
            clave_cancelacion   VARCHAR(80) DEFAULT NULL,
            monto               DECIMAL(14,2) DEFAULT 0,
            justificacion       TEXT DEFAULT NULL,
            cfdi_reemplaza      VARCHAR(80) DEFAULT NULL,
            fecha_solicitud     DATE DEFAULT NULL,
            estatus             ENUM('pendiente','aplicada','rechazada') NOT NULL DEFAULT 'pendiente',
            solicitado_por      INT DEFAULT NULL,
            creado_en           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_obra (id_obra),
            INDEX idx_estatus (estatus),
            INDEX idx_empresa (empresa)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # Migración: agregar campo empresa si la tabla ya existía sin él
    try:
        execute_ddl("ALTER TABLE solicitudes_cancelacion ADD COLUMN empresa VARCHAR(20) NOT NULL DEFAULT 'ESMA' AFTER id_obra")
    except Exception:
        pass
    # Migración: ampliar clave_cancelacion de VARCHAR(10) a VARCHAR(80)
    try:
        execute_ddl("ALTER TABLE solicitudes_cancelacion MODIFY COLUMN clave_cancelacion VARCHAR(80) DEFAULT NULL")
    except Exception:
        pass


CLAVES_CANCELACION_SAT = [
    "01 - Comprobante emitido con errores con relación",
    "02 - Comprobante emitido con errores sin relación",
    "03 - No se llevó a cabo la operación",
    "04 - Operación nominativa relacionada en factura global",
]

EMPRESAS_CANCELACION = ["ESMA", "GREMIAL"]


def get_solicitudes_cancelacion(id_obra=None, estatus=None, empresa=None):
    sql = """
        SELECT s.*, ob.nombre AS obra_nombre
        FROM solicitudes_cancelacion s LEFT JOIN obras ob ON ob.id = s.id_obra
        WHERE 1=1
    """
    p = []
    if id_obra: sql += " AND s.id_obra=%s"; p.append(id_obra)
    if estatus: sql += " AND s.estatus=%s"; p.append(estatus)
    if empresa: sql += " AND s.empresa=%s"; p.append(empresa)
    sql += " ORDER BY s.fecha_solicitud DESC, s.id DESC"
    return query(sql, p)


def crear_solicitud_cancelacion(d):
    d = dict(d)
    d.setdefault("empresa", "ESMA")
    return execute("""
        INSERT INTO solicitudes_cancelacion
            (id_obra, empresa, folio_fiscal, razon_social, rfc, clave_cancelacion, monto,
             justificacion, cfdi_reemplaza, fecha_solicitud, solicitado_por)
        VALUES
            (%(id_obra)s, %(empresa)s, %(folio_fiscal)s, %(razon_social)s, %(rfc)s,
             %(clave_cancelacion)s, %(monto)s, %(justificacion)s, %(cfdi_reemplaza)s,
             %(fecha_solicitud)s, %(solicitado_por)s)
    """, d)


def cambiar_estatus_cancelacion(sid, estatus):
    execute("UPDATE solicitudes_cancelacion SET estatus=%s WHERE id=%s", (estatus, sid))


# ══════════════════════════════════════════════════════════════════
#  CONTRATOS (importación desde Excel/CSV tipo Procore)
# ══════════════════════════════════════════════════════════════════

def _init_tabla_contratos():
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS contratos (
            id                      INT AUTO_INCREMENT PRIMARY KEY,
            numero                  VARCHAR(60) NOT NULL,
            compania_contratista    VARCHAR(200) DEFAULT NULL,
            tipo_contrato           VARCHAR(60) DEFAULT NULL,
            titulo                  VARCHAR(255) DEFAULT NULL,
            estatus                 VARCHAR(40) DEFAULT 'Aprobado',
            ejecutado               VARCHAR(10) DEFAULT 'No',
            monto_original          DECIMAL(18,2) DEFAULT 0,
            ordenes_cambio_aprobadas DECIMAL(18,2) DEFAULT 0,
            monto_revisado          DECIMAL(18,2) DEFAULT 0,
            facturado               DECIMAL(18,2) DEFAULT 0,
            pagos_emitidos          DECIMAL(18,2) DEFAULT 0,
            pct_pagado              DECIMAL(8,4) DEFAULT 0,
            saldo_restante          DECIMAL(18,2) DEFAULT 0,
            proveedor               VARCHAR(200) DEFAULT NULL,
            telefono_proveedor      VARCHAR(40) DEFAULT NULL,
            email_proveedor         VARCHAR(120) DEFAULT NULL,
            id_obra                 INT DEFAULT NULL,
            creado_por              INT DEFAULT NULL,
            creado_en               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_numero (numero),
            INDEX idx_obra (id_obra),
            INDEX idx_estatus (estatus)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)


def get_contratos(id_obra=None, tipo=None, estatus=None, search=None):
    sql = "SELECT * FROM contratos WHERE 1=1"
    p = []
    if id_obra:
        sql += " AND id_obra=%s"; p.append(id_obra)
    if tipo:
        sql += " AND tipo_contrato=%s"; p.append(tipo)
    if estatus:
        sql += " AND estatus=%s"; p.append(estatus)
    if search:
        sql += " AND (numero LIKE %s OR compania_contratista LIKE %s OR titulo LIKE %s)"
        p += [f"%{search}%", f"%{search}%", f"%{search}%"]
    sql += " ORDER BY creado_en DESC"
    return query(sql, p)


def get_contrato(cid):
    return query("SELECT * FROM contratos WHERE id=%s", (cid,), one=True)


def crear_contrato(d):
    return execute("""
        INSERT INTO contratos
            (numero, compania_contratista, tipo_contrato, titulo, estatus, ejecutado,
             monto_original, ordenes_cambio_aprobadas, monto_revisado,
             facturado, pagos_emitidos, pct_pagado, saldo_restante,
             proveedor, telefono_proveedor, email_proveedor, id_obra, creado_por)
        VALUES
            (%(numero)s, %(compania_contratista)s, %(tipo_contrato)s, %(titulo)s,
             %(estatus)s, %(ejecutado)s, %(monto_original)s, %(ordenes_cambio_aprobadas)s,
             %(monto_revisado)s, %(facturado)s, %(pagos_emitidos)s, %(pct_pagado)s,
             %(saldo_restante)s, %(proveedor)s, %(telefono_proveedor)s,
             %(email_proveedor)s, %(id_obra)s, %(creado_por)s)
    """, d)


def importar_contratos_excel(filas, id_obra=None, creado_por=None):
    """Importa filas de Excel/CSV de contratos (formato Procore).
    Hace upsert por numero + id_obra. Retorna cantidad procesada."""
    count = 0

    def _dec(v):
        try:
            return float(str(v).replace(",", "").strip()) if v else 0
        except (ValueError, TypeError):
            return 0

    def _str(v):
        return str(v).strip() if v else None

    for fila in filas:
        numero = _str(fila.get("Número") or fila.get("Numero") or fila.get("numero"))
        if not numero:
            continue

        datos = {
            "numero": numero,
            "compania_contratista": _str(fila.get("Compañía contratista") or fila.get("Compania contratista")),
            "tipo_contrato": _str(fila.get("Tipo de contrato") or fila.get("Tipo")),
            "titulo": _str(fila.get("Título") or fila.get("Titulo")),
            "estatus": _str(fila.get("Estatus")) or "Aprobado",
            "ejecutado": _str(fila.get("Ejecutado")) or "No",
            "monto_original": _dec(fila.get("Monto del contrato original") or fila.get("Monto original")),
            "ordenes_cambio_aprobadas": _dec(fila.get("Órdenes de cambio aprobadas") or fila.get("Ordenes de cambio aprobadas")),
            "monto_revisado": _dec(fila.get("Monto del contrato revisado") or fila.get("Monto revisado")),
            "facturado": _dec(fila.get("Facturado")),
            "pagos_emitidos": _dec(fila.get("Pagos emitidos")),
            "pct_pagado": _dec(fila.get("% pagado") or fila.get("% Pagado")),
            "saldo_restante": _dec(fila.get("Saldo restante pendiente") or fila.get("Saldo restante")),
            "proveedor": _str(fila.get("Proveedor")),
            "telefono_proveedor": _str(fila.get("Teléfono del proveedor") or fila.get("Telefono del proveedor")),
            "email_proveedor": _str(fila.get("Dirección de correo electrónico") or fila.get("Email")),
            "id_obra": id_obra,
            "creado_por": creado_por,
        }

        # Upsert por numero + id_obra
        existente = query(
            "SELECT id FROM contratos WHERE numero=%s AND (id_obra=%s OR (id_obra IS NULL AND %s IS NULL))",
            (numero, id_obra, id_obra), one=True)

        if existente:
            sets = ", ".join(f"{k}=%({k})s" for k in datos if k not in ("numero", "id_obra", "creado_por"))
            datos["_id"] = existente["id"]
            execute(f"UPDATE contratos SET {sets} WHERE id=%(_id)s", datos)
        else:
            crear_contrato(datos)
        count += 1
    return count


def get_contratos_resumen(id_obra=None):
    """Resumen: total, monto total, facturado, pagado."""
    sql = """SELECT COUNT(*) as total, COALESCE(SUM(monto_revisado),0) as monto_total,
             COALESCE(SUM(facturado),0) as facturado_total,
             COALESCE(SUM(pagos_emitidos),0) as pagado_total FROM contratos WHERE 1=1"""
    p = []
    if id_obra:
        sql += " AND id_obra=%s"; p.append(id_obra)
    return query(sql, p, one=True)
