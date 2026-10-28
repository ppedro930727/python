"""
database.py — Conexión y consultas MySQL/MariaDB
GRUPO ESMA — Plataforma de Telemetría
Estructura tipo Procore: Inicio · Reportes 360 · Documentos · Equipos · etc.
"""
import mysql.connector
from datetime import datetime, timedelta, date

DB_CONFIG = {
    "host":       "localhost",
    "port":       3306,
    "database":   "esma_telemetria",
    "user":       "esma_app",
    "password":   "",
    "charset":    "utf8mb4",
    "collation":  "utf8mb4_unicode_ci",   # evita mezcla de collations
    "autocommit": True,
    "connect_timeout": 10,
    "connection_timeout": 10,
}


def get_conn():
    c = mysql.connector.connect(**DB_CONFIG)
    # Timeout de queries: 30 segundos máximo por consulta
    cur = c.cursor(buffered=True)
    try:
        cur.execute("SET SESSION max_execution_time=30000")  # 30 seg en milisegundos
    except Exception:
        pass  # Versiones viejas de MySQL no soportan esto
    finally:
        cur.close()
    return c

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
    faltantes = cargados - telemetria  (positivo => faltan litros; negativo => telemetría detectó más)
    Umbrales sobre |desviacion| respecto a lo cargado."""
    lc = float(litros_cargados or 0)
    lt = float(litros_telemetria or 0)
    faltantes = round(lc - lt, 2)
    if lc > 0:
        base = lc
    elif lt > 0:
        base = lt
    else:
        base = 0
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


def _init_drop_uk_eco_fecha():
    """Migración: elimina la clave única (codigo_eco, fecha) de reportes_combustible.
    Antes esa restricción impedía tener más de una carga del MISMO equipo en la
    MISMA fecha (la segunda sobrescribía a la primera vía ON DUPLICATE KEY).
    Ahora se permiten múltiples cargas por equipo/día."""
    try:
        execute_ddl("ALTER TABLE reportes_combustible DROP INDEX uk_eco_fecha")
    except Exception:
        # Ya fue eliminada o no existe; sin problema.
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

def _init_columna_movil_usuarios():
    """Migración: agrega usuarios.movil si no existe."""
    try:
        execute_ddl("ALTER TABLE usuarios ADD COLUMN movil VARCHAR(40) DEFAULT NULL COMMENT 'Teléfono móvil' AFTER email")
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
    return query("""SELECT u.id,u.nombre,u.email,u.movil,u.rol,u.activo,u.creado_en,
                            u.id_obra_asignada, ob.nombre AS obra_asignada_nombre
                     FROM usuarios u LEFT JOIN obras ob ON ob.id=u.id_obra_asignada
                     ORDER BY u.nombre""")

def crear_usuario(nombre, email, password_hash, rol, id_obra_asignada=None, movil=None):
    return execute("""INSERT INTO usuarios (nombre,email,password,rol,id_obra_asignada,movil)
                       VALUES (%s,%s,%s,%s,%s,%s)""",
                   (nombre, email, password_hash, rol, id_obra_asignada, movil or None))

def actualizar_usuario(uid, nombre, email, rol, activo, id_obra_asignada=None, movil=None):
    execute("""UPDATE usuarios SET nombre=%s,email=%s,rol=%s,activo=%s,id_obra_asignada=%s,movil=%s
               WHERE id=%s""",
            (nombre, email, rol, activo, id_obra_asignada, movil or None, uid))

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
               m.capacidad_litros AS capacidad_litros,
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
    Cada llamada crea una fila nueva — el historial completo queda en esta tabla."""
    execute("""
        INSERT INTO estado
            (codigo_eco, serie, nombre_equipo, marca, modelo,
             fecha_ultima_actualizacion, latitud, longitud,
             horas_totales_horometro, nivel_combustible)
        VALUES (%(eco)s, %(serie)s, %(nombre_equipo)s, %(marca)s, %(modelo)s,
                %(fecha)s, %(lat)s, %(lon)s, %(horometro)s,
                %(nivel_combustible)s)
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

def get_maquinas(search=None, clasificacion=None, obra=None):
    sql = """
        SELECT m.*, e.latitud, e.longitud, e.nivel_combustible,
               COALESCE(e.horas_totales_horometro, rc_last.horometro_final) AS horas_totales_horometro,
               e.fecha_ultima_actualizacion,
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
        LEFT JOIN (
            SELECT codigo_eco, MAX(horometro_final) AS horometro_final
            FROM reportes_combustible
            WHERE horometro_final IS NOT NULL AND horometro_final > 0
            GROUP BY codigo_eco
        ) rc_last ON rc_last.codigo_eco = m.eco
        LEFT JOIN obras ob ON ob.id=m.id_obra
        WHERE 1=1
    """
    params = []
    if search:
        sql += " AND (m.eco LIKE %s OR m.nombre_equipo LIKE %s OR m.marca LIKE %s OR m.serie LIKE %s)"
        params += [f"%{search}%"]*4
    if clasificacion:
        sql += " AND m.clasificacion=%s"; params.append(clasificacion)
    if obra:
        sql += " AND m.id_obra=%s"; params.append(obra)
    sql += " ORDER BY m.eco"
    return query(sql, params)

def get_maquina(eco):
    return query("""
        SELECT m.*, e.latitud, e.longitud, e.nivel_combustible,
               COALESCE(e.horas_totales_horometro, rc_last.horometro_final) AS horas_totales_horometro,
               e.fecha_ultima_actualizacion,
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
        LEFT JOIN (
            SELECT codigo_eco, MAX(horometro_final) AS horometro_final
            FROM reportes_combustible
            WHERE horometro_final IS NOT NULL AND horometro_final > 0
            GROUP BY codigo_eco
        ) rc_last ON rc_last.codigo_eco = m.eco
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
    """
    Compatibilidad con llamadas antiguas.
    Obtiene reportes de los últimos 'dias' días.
    """

    reportes = query("""
        SELECT
            MIN(fecha) AS fecha_ini,
            MAX(fecha) AS fecha_fin
        FROM reportes_combustible
        WHERE codigo_eco = %s
          AND fecha >= CURDATE() - INTERVAL %s DAY
    """, (eco, dias))

    if not reportes or not reportes[0].get("fecha_ini"):
        return []

    fi = reportes[0]["fecha_ini"]
    ff = reportes[0]["fecha_fin"]

    return get_reportes_maquina_rango(
        eco,
        fi,
        ff
    )











def get_reportes_maquina_rango(eco, fi=None, ff=None):
    """
    Obtiene los reportes 360 de una máquina dentro
    del rango seleccionado.

    La telemetría utiliza EXACTAMENTE la misma función
    get_cargas_detectadas() que utiliza la gráfica.
    """

    # =========================================================
    # 1. REPORTES MANUALES
    # =========================================================

    sql = """
        SELECT
            fecha,
            litros_cargados,
            justificado
        FROM reportes_combustible
        WHERE codigo_eco = %s
    """

    params = [eco]

    if fi:
        sql += " AND fecha >= %s"
        params.append(fi)

    if ff:
        sql += " AND fecha <= %s"
        params.append(ff)

    sql += " ORDER BY fecha"

    reportes = query(sql, tuple(params))

    if not reportes:
        return []

    # =========================================================
    # 2. TELEMETRÍA
    #
    # IMPORTANTE:
    # Pasamos también fi y ff para que utilice exactamente
    # el mismo rango seleccionado por el usuario.
    # =========================================================

    cargas_telemetria = get_cargas_detectadas(
        eco,
        fi,
        ff
    )

    # =========================================================
    # 3. INDEXAR TELEMETRÍA POR FECHA
    # =========================================================

    telemetria_por_fecha = {}

    for carga in cargas_telemetria:

        fecha = str(carga.get("fecha"))[:10]

        litros = float(
            carga.get("litros_cargados") or 0
        )

        telemetria_por_fecha[fecha] = litros

    # =========================================================
    # 4. COMBINAR REPORTES + TELEMETRÍA
    # =========================================================

    resultado = []

    for r in reportes:

        fecha = str(r.get("fecha"))[:10]

        # -----------------------------------------------------
        # Litros registrados manualmente
        # -----------------------------------------------------

        litros_cargados = float(
            r.get("litros_cargados") or 0
        )

        # -----------------------------------------------------
        # Litros detectados por telemetría
        # -----------------------------------------------------

        litros_telemetria = telemetria_por_fecha.get(
            fecha,
            0
        )

        # -----------------------------------------------------
        # Diferencia
        # -----------------------------------------------------

        litros_faltantes = round(
            litros_cargados - litros_telemetria,
            1
        )

        # -----------------------------------------------------
        # Desviación %
        # -----------------------------------------------------

        if litros_cargados > 0:

            desviacion_pct = round(
                (
                    litros_cargados - litros_telemetria
                )
                / litros_cargados
                * 100,
                1
            )

        elif litros_telemetria > 0:

            # cargados=0 pero hay telemetría → diferencia negativa completa
            desviacion_pct = round(
                (0 - litros_telemetria) / litros_telemetria * 100,
                1
            )

        else:

            desviacion_pct = 0

        # -----------------------------------------------------
        # SEMÁFORO
        # -----------------------------------------------------

        if litros_telemetria >= litros_cargados:

            semaforo = "OK"

        elif desviacion_pct >= -5.0:

            semaforo = "OK"

        elif desviacion_pct >= -15.0:

            semaforo = "Revisar"

        else:

            semaforo = "Fraude Probable"

        # -----------------------------------------------------
        # RESULTADO
        # -----------------------------------------------------

        resultado.append({
            "fecha": r.get("fecha"),

            # Valor original del reporte
            "litros_cargados": litros_cargados,

            # Valor EXACTO de get_cargas_detectadas()
            "litros_telemetria": round(
                litros_telemetria,
                1
            ),

            "litros_faltantes": litros_faltantes,

            "desviacion_pct": desviacion_pct,

            "semaforo": semaforo,

            "justificado": r.get(
                "justificado",
                False
            )
        })

    return resultado











def get_cargas_detectadas(eco, fi=None, ff=None):
    """
    Detecta cargas de combustible desde la tabla estado.

    Una carga se detecta cuando el nivel de combustible
    aumenta entre dos lecturas consecutivas.

    Usa LAG() para comparar con la lectura anterior.
    """

    if fi and ff:

        sql = """
            SELECT
                fecha,
                ROUND(SUM(litros_carga), 1) AS litros_cargados
            FROM (
                SELECT
                    DATE(e.fecha_ultima_actualizacion) AS fecha,

                    (
                        e.nivel_combustible
                        - LAG(e.nivel_combustible)
                          OVER (
                              ORDER BY e.fecha_ultima_actualizacion
                          )
                    ) / 100 * m.capacidad_litros AS litros_carga

                FROM estado e

                LEFT JOIN maquinas m
                    ON m.eco = e.codigo_eco

                WHERE e.codigo_eco = %s

                  AND e.fecha_ultima_actualizacion >= %s
                  AND e.fecha_ultima_actualizacion
                      < DATE_ADD(%s, INTERVAL 1 DAY)

                  AND m.capacidad_litros > 0

                  AND e.nivel_combustible IS NOT NULL

            ) sub

            WHERE sub.litros_carga >= 5

            GROUP BY sub.fecha

            ORDER BY sub.fecha
        """

        return query(sql, (eco, fi, ff))

    else:

        sql = """
            SELECT
                fecha,
                ROUND(SUM(litros_carga), 1) AS litros_cargados
            FROM (
                SELECT
                    DATE(e.fecha_ultima_actualizacion) AS fecha,

                    (
                        e.nivel_combustible
                        - LAG(e.nivel_combustible)
                          OVER (
                              ORDER BY e.fecha_ultima_actualizacion
                          )
                    ) / 100 * m.capacidad_litros AS litros_carga

                FROM estado e

                LEFT JOIN maquinas m
                    ON m.eco = e.codigo_eco

                WHERE e.codigo_eco = %s

                  AND e.fecha_ultima_actualizacion
                      >= CURDATE() - INTERVAL 30 DAY

                  AND m.capacidad_litros > 0

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
        INSERT INTO obras (nombre,numero_contrato,descripcion,cliente,ubicacion,fecha_inicio,fecha_fin,estado,link_drive)
        VALUES (%(nombre)s,%(numero_contrato)s,%(descripcion)s,%(cliente)s,%(ubicacion)s,%(fecha_inicio)s,%(fecha_fin)s,%(estado)s,%(link_drive)s)
    """, d)

def actualizar_obra(d):
    execute("""
        UPDATE obras SET nombre=%(nombre)s, numero_contrato=%(numero_contrato)s,
               descripcion=%(descripcion)s, cliente=%(cliente)s, ubicacion=%(ubicacion)s,
               fecha_inicio=%(fecha_inicio)s, fecha_fin=%(fecha_fin)s, estado=%(estado)s,
               link_drive=%(link_drive)s
        WHERE id=%(id)s
    """, d)

def get_equipos_obra(oid):
    return query("""
        SELECT m.eco, m.nombre_equipo, m.marca, m.modelo, m.serie, m.marca,
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
#  DIRECTORIO / EQUIPO DEL PROYECTO  →  usa tabla usuarios
# ══════════════════════════════════════════════════════════════════

def get_directorio_equipo_proyecto():
    """Devuelve todos los usuarios activos del sistema como directorio.
    Se usa en órdenes de compra (Contacto de pagos, Responsable)
    y en la sección Equipo del Proyecto de cada obra."""
    return query("""
        SELECT u.id, u.nombre, u.email AS correo, u.movil, u.rol,
               ob.nombre AS obra_asignada_nombre
        FROM usuarios u
        LEFT JOIN obras ob ON ob.id = u.id_obra_asignada
        WHERE u.activo = 1
        ORDER BY u.nombre
    """)



# ══════════════════════════════════════════════════════════════════
#  REPORTES 360 · COMBUSTIBLE  (auditoría cargado vs telemetría)
# ══════════════════════════════════════════════════════════════════
def get_reportes_combustible(fi=None, ff=None, semaforo=None, obra=None, eco=None):
    """
    Trae reportes de combustible.

    IMPORTANTE:
    - litros_cargados viene directamente de reportes_combustible.
    - litros_telemetria se obtiene EXCLUSIVAMENTE mediante
      get_cargas_detectadas().
    - De esta manera /combustible y /maquinas/<eco> utilizan
      exactamente la misma lógica de detección.
    """

    # =========================================================
    # 1. OBTENER LOS REPORTES
    # =========================================================

    sql = """
        SELECT
            r.*,
            ob.nombre AS obra_nombre
        FROM reportes_combustible r
        LEFT JOIN obras ob
            ON ob.id = r.id_obra
        WHERE 1=1
    """

    p = []

    if fi:
        sql += " AND r.fecha >= %s"
        p.append(fi)

    if ff:
        sql += " AND r.fecha <= %s"
        p.append(ff)

    if semaforo:
        sql += " AND r.semaforo=%s"
        p.append(semaforo)

    if obra:
        sql += " AND r.id_obra=%s"
        p.append(obra)

    if eco:
        sql += " AND r.codigo_eco=%s"
        p.append(eco)

    sql += """
        ORDER BY
            r.fecha DESC,
            FIELD(
                r.semaforo,
                'Fraude Probable',
                'Alerta',
                'Revisar',
                'OK'
            ),
            r.codigo_eco
    """

    filas = query(sql, p)
    filas = filas or []

    # =========================================================
    # 2. OBTENER ECOs A CONSULTAR PARA TELEMETRÍA
    #
    # Fuente 1: ECOs que ya tienen reporte manual (siempre)
    # Fuente 2: ECOs con telemetría en el período sin reporte
    #           → maquinas filtradas por obra, o el eco específico,
    #             o todas las máquinas con capacidad_litros > 0
    # =========================================================

    ecos = set()

    # ECOs con reporte manual
    for fila in filas:
        if fila.get("codigo_eco"):
            ecos.add(fila["codigo_eco"])

    # ECOs adicionales según el filtro activo
    if eco:
        # ECO específico — aunque no tenga reporte
        ecos.add(eco)
    elif obra:
        # Máquinas de esa obra
        maquinas_obra = query(
            "SELECT eco FROM maquinas WHERE eco IS NOT NULL AND id_obra=%s AND capacidad_litros > 0",
            (obra,)
        ) or []
        for m in maquinas_obra:
            if m.get("eco"):
                ecos.add(m["eco"])
    else:
        # Sin filtro — todas las máquinas con sensor de combustible
        todas = query(
            "SELECT eco FROM maquinas WHERE eco IS NOT NULL AND capacidad_litros > 0"
        ) or []
        for m in todas:
            if m.get("eco"):
                ecos.add(m["eco"])


    telemetria = {}

    for eco_r in ecos:

        try:
            cargas = get_cargas_detectadas(
                eco_r,
                fi,
                ff
            )
        except Exception:
            cargas = []

        for carga in cargas:

            fecha = str(
                carga.get("fecha")
            )[:10]

            litros = float(
                carga.get("litros_cargados") or 0
            )

            telemetria[
                (eco_r, fecha)
            ] = litros


    # =========================================================
    # 3. ACTUALIZAR CADA REPORTE
    # =========================================================

    for fila in filas:

        eco_r = fila.get("codigo_eco")

        fecha_r = str(
            fila.get("fecha")
        )[:10]


        # -----------------------------------------------------
        # LITROS DEL REPORTE
        #
        # NO SE TOCAN
        # -----------------------------------------------------

        cargados = float(
            fila.get("litros_cargados") or 0
        )


        # -----------------------------------------------------
        # TELEMETRÍA
        #
        # MISMA FUENTE QUE LA PANTALLA DE LA MÁQUINA
        # -----------------------------------------------------

        litros_tel = telemetria.get(
            (eco_r, fecha_r),
            0
        )


        fila["litros_telemetria"] = round(
            litros_tel,
            1
        )


        # -----------------------------------------------------
        # FALTANTE
        # -----------------------------------------------------

        fila["litros_faltantes"] = round(
            cargados - litros_tel,
            1
        )


        # -----------------------------------------------------
        # DESVIACIÓN
        # -----------------------------------------------------

        if cargados > 0:

            fila["desviacion_pct"] = round(
                (
                    cargados - litros_tel
                )
                / cargados
                * 100,
                1
            )

        elif litros_tel > 0:

            # cargados=0 pero hay telemetría → diferencia negativa completa
            fila["desviacion_pct"] = round(
                (0 - litros_tel) / litros_tel * 100,
                1
            )

        else:

            fila["desviacion_pct"] = 0


        # -----------------------------------------------------
        # SEMÁFORO
        # -----------------------------------------------------

        if litros_tel >= cargados:

            fila["semaforo"] = "OK"

        elif fila["desviacion_pct"] >= -5.0:

            fila["semaforo"] = "OK"

        elif fila["desviacion_pct"] >= -15.0:

            fila["semaforo"] = "Revisar"

        else:

            fila["semaforo"] = "Fraude Probable"

    # =========================================================
    # 4. AGREGAR FILAS PARA FECHAS DE TELEMETRÍA SIN REPORTE
    # =========================================================

    # Par (eco, fecha) que ya tienen reporte manual
    pares_con_reporte = {
        (str(f.get("codigo_eco")), str(f.get("fecha"))[:10])
        for f in filas
    }

    # Cache de info de máquinas para no repetir queries
    cache_maq = {}

    for (eco_t, fecha_t), litros_tel in telemetria.items():
        if (eco_t, fecha_t) in pares_con_reporte:
            continue  # ya cubierta por reporte manual
        if litros_tel <= 0:
            continue  # sin dato real

        if eco_t not in cache_maq:
            cache_maq[eco_t] = query(
                "SELECT nombre_equipo, marca, id_obra FROM maquinas WHERE eco=%s",
                (eco_t,), one=True
            ) or {}
        maq_info = cache_maq[eco_t]

        # Obtener obra de la máquina si no se filtró por obra
        obra_nombre_tel = None
        if maq_info.get("id_obra"):
            ob = query("SELECT nombre FROM obras WHERE id=%s",
                       (maq_info["id_obra"],), one=True)
            obra_nombre_tel = ob.get("nombre") if ob else None

        filas.append({
            "codigo_eco":        eco_t,
            "fecha":             fecha_t,
            "semana_num":        None,
            "nombre_equipo":     maq_info.get("nombre_equipo", ""),
            "marca":             maq_info.get("marca", ""),
            "obra_nombre":       obra_nombre_tel,
            "operador":          None,
            "litros_cargados":   0.0,
            "litros_telemetria": round(litros_tel, 1),
            "litros_faltantes":  round(0.0 - litros_tel, 1),
            "desviacion_pct":    0.0,
            "semaforo":          "OK",
            "justificado":       0,
            "tipo_combustible":  "diesel",
        })

    # Reordenar por fecha desc, luego por eco
    filas.sort(key=lambda r: (str(r.get("fecha") or ""), str(r.get("codigo_eco") or "")), reverse=True)

    return filas


def get_auditoria_combustible_maquina(eco, fi=None, ff=None):
    """
    Para /maquinas/<eco> — muestra TODAS las fechas donde haya dato
    en telemetría O en reporte manual, o en ambos.

    Casos posibles por fecha:
      - Solo reporte manual  (cargados > 0, telemetria = 0)
      - Solo telemetría      (cargados = 0, telemetria > 0)
      - Ambos                (cargados > 0, telemetria > 0)
    """

    # 1. Reportes manuales del ECO
    sql = """
        SELECT fecha, litros_cargados, justificado
        FROM reportes_combustible
        WHERE codigo_eco = %s
    """
    params = [eco]
    if fi:
        sql += " AND fecha >= %s"; params.append(fi)
    if ff:
        sql += " AND fecha <= %s"; params.append(ff)

    filas_reporte = query(sql, params) or []

    # Indexar por fecha
    reporte_map = {}
    for r in filas_reporte:
        fecha = str(r["fecha"])[:10]
        reporte_map[fecha] = {
            "litros_cargados": float(r.get("litros_cargados") or 0),
            "justificado":     r.get("justificado", 0),
        }

    # 2. Telemetría del ECO
    try:
        cargas_tel = get_cargas_detectadas(eco, fi, ff) or []
    except Exception:
        cargas_tel = []

    tel_map = {}
    for c in cargas_tel:
        fecha = str(c.get("fecha"))[:10]
        tel_map[fecha] = float(c.get("litros_cargados") or 0)

    # 3. Unión de fechas
    todas_fechas = sorted(set(list(reporte_map.keys()) + list(tel_map.keys())), reverse=True)

    if not todas_fechas:
        return []

    resultado = []
    for fecha in todas_fechas:
        cargados  = reporte_map.get(fecha, {}).get("litros_cargados", 0)
        telemetria = tel_map.get(fecha, 0)
        faltante   = round(cargados - telemetria, 1)

        if cargados > 0:
            desviacion = round((cargados - telemetria) / cargados * 100, 1)
        else:
            desviacion = 0.0

        resultado.append({
            "fecha":             fecha,
            "litros_cargados":   round(cargados, 1),
            "litros_telemetria": round(telemetria, 1),
            "litros_faltantes":  faltante,
            "desviacion_pct":    desviacion,
            "semaforo":          "OK" if faltante <= 0 else ("Revisar" if desviacion < 15 else "Fraude Probable"),
        })

    return resultado




    

def get_combustible_kpis(fi, ff, obra=None):
    """KPIs de combustible. total_telemetria se calcula con get_cargas_detectadas
    (misma lógica que la gráfica de tendencia) para garantizar que ambos números coincidan."""
    
    sql = """
        SELECT
            COUNT(*) AS total_reportes,
            COALESCE(SUM(litros_cargados),0)   AS total_cargados,
            COALESCE(SUM(costo_total),0)       AS total_costo,
            SUM(semaforo='OK')               AS n_ok,
            SUM(semaforo='Revisar')          AS n_revisar,
            SUM(semaforo='Alerta')           AS n_alerta,
            SUM(semaforo='Fraude Probable')  AS n_fraude
        FROM reportes_combustible
        WHERE fecha BETWEEN %s AND %s
    """
    params = [fi, ff]
    
    if obra:
        sql += " AND id_obra = %s"
        params.append(obra)
    
    base = query(sql, params, one=True)
    
    # Telemetría: sumar exactamente los mismos valores que muestra la gráfica
    tendencia = get_combustible_tendencia(fi, ff)
    total_tel = round(sum(float(row.get("telemetria") or 0) for row in (tendencia or [])), 1)
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
    filtro_obra = "AND m.id_obra = %s" if id_obra else ""
    params = [semanas, id_obra] if id_obra else [semanas]
    return query(f"""
        WITH lecturas AS (
            SELECT e.codigo_eco, e.fecha_ultima_actualizacion AS fecha_hora,
                   e.nivel_combustible, m.capacidad_litros,
                   LAG(e.nivel_combustible) OVER (
                       PARTITION BY e.codigo_eco ORDER BY e.fecha_ultima_actualizacion
                   ) AS nivel_anterior
            FROM estado e
            LEFT JOIN maquinas m ON m.eco = e.codigo_eco
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













def get_combustible_tendencia(fi, ff, obra=None, eco=None, tipo_combustible=None):
    """
    Tendencia diaria de combustible.

    Litros Cargados Reporte Obra:
        reportes_combustible.litros_cargados

    Litros Cargados Telemetría:
        get_cargas_detectadas()

    Diferencia:
        cargado - telemetría
    """

    # =========================================================
    # CARGADO
    # =========================================================

    sql_carg = """
        SELECT
            fecha,
            ROUND(SUM(litros_cargados), 1) AS cargados
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

    if tipo_combustible:
        sql_carg += " AND tipo_combustible=%s"
        p_carg.append(tipo_combustible)

    sql_carg += """
        GROUP BY fecha
        ORDER BY fecha
    """

    cargados = query(sql_carg, p_carg)

    # =========================================================
    # TELEMETRÍA
    # =========================================================

    tel_map = {}

    # La telemetría GPS solo aplica para diesel.
    # Para gasolina (vehículos ligeros) no hay sensor de nivel, tel_map queda vacío.
    if tipo_combustible == 'gasolina':
        pass  # sin telemetría

    elif eco:

        cargas = get_cargas_detectadas(
            eco,
            fi,
            ff
        )

        for carga in cargas:

            fecha = str(
                carga.get("fecha")
            )[:10]

            litros = float(
                carga.get("litros_cargados") or 0
            )

            tel_map[fecha] = round(
                tel_map.get(fecha, 0) + litros,
                1
            )

    else:

        sql_maquinas = """
            SELECT eco
            FROM maquinas
            WHERE eco IS NOT NULL
        """

        p_maquinas = []

        if obra:
            sql_maquinas += " AND id_obra=%s"
            p_maquinas.append(obra)

        maquinas = query(
            sql_maquinas,
            p_maquinas
        )

        for maquina in maquinas:

            eco_m = maquina.get("eco")

            if not eco_m:
                continue

            try:
                cargas = get_cargas_detectadas(
                    eco_m,
                    fi,
                    ff
                )
            except Exception:
                cargas = []

            for carga in cargas:

                fecha = str(
                    carga.get("fecha")
                )[:10]

                litros = float(
                    carga.get("litros_cargados") or 0
                )

                tel_map[fecha] = round(
                    tel_map.get(fecha, 0) + litros,
                    1
                )

    # =========================================================
    # RESULTADO
    # =========================================================

    carg_map = {}

    for row in cargados:

        fecha = str(row["fecha"])[:10]

        carg = float(
            row["cargados"] or 0
        )

        carg_map[fecha] = round(
            carg_map.get(fecha, 0) + carg,
            1
        )


    # =========================================================
    # UNIÓN DE FECHAS
    # =========================================================

    fechas = sorted(
        set(carg_map.keys()) |
        set(tel_map.keys())
    )


    # =========================================================
    # CONSTRUIR RESULTADO
    # =========================================================

    resultado = []

    for fecha in fechas:

        carg = round(
            carg_map.get(fecha, 0),
            1
        )

        tel = round(
            tel_map.get(fecha, 0),
            1
        )

        # Diferencia: positivo = obra reportó más de lo detectado (faltante)
        #             negativo = telemetría detectó más de lo reportado
        falt = round(
            carg - tel,
            1
        )

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
    # Clamp a los rangos de las columnas DECIMAL para evitar "Out of range value".
    def _clamp_dec(v, max_abs):
        if v is None:
            return None
        try:
            v = float(v)
        except (ValueError, TypeError):
            return None
        return max(-max_abs, min(max_abs, v))
    faltantes = _clamp_dec(faltantes, 999999.99)   # decimal(8,2)
    desv      = _clamp_dec(desv, 9999.99)           # decimal(6,2)
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
        SELECT e.nivel_combustible, m.capacidad_litros
        FROM estado e
        LEFT JOIN maquinas m ON m.eco = e.codigo_eco
        WHERE e.codigo_eco=%s AND DATE(e.fecha_ultima_actualizacion)=%s
              AND e.nivel_combustible IS NOT NULL
        ORDER BY e.fecha_ultima_actualizacion DESC LIMIT 1
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
        SELECT e.id, e.codigo_eco, e.serie, e.nombre_equipo, e.marca, e.modelo, e.fecha_ultima_actualizacion,
               e.latitud, e.longitud, e.horas_totales_horometro, e.nivel_combustible, m.capacidad_litros
        FROM estado e
        LEFT JOIN maquinas m ON m.eco = e.codigo_eco
        WHERE DATE(e.fecha_ultima_actualizacion) BETWEEN %s AND %s{extra}
        ORDER BY e.codigo_eco, e.fecha_ultima_actualizacion
    """
    return query(sql, [fi, ff] + extra_params)


def get_horas_export(fi, ff, lista=None):
    """Exporta horas diarias entre fi y ff.
    lista: lista de codigo_eco a incluir; None o [] = todos."""
    lista = lista or []
    extra, extra_params = _filtro_eco("codigo_eco", lista)
    sql = f"""
        SELECT codigo_eco, serie, nombre_equipo, marca, modelo, fecha,
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
        SELECT codigo_eco, serie, nombre_equipo, marca, modelo, fecha,
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


def get_combustible_export_completo(fi, ff):
    """Exporta TODOS los reportes 360 de combustible entre fi y ff,
    sin filtro de equipos. Incluye columna tipo_combustible de la misma
    tabla y ordena diesel primero, luego por ECO y fecha."""
    sql = """
        SELECT r.tipo_combustible AS tipo,
               r.codigo_eco, r.nombre_equipo, r.marca, ob.nombre AS obra, r.fecha,
               r.operador, r.litros_cargados, r.litros_telemetria, r.litros_faltantes,
               r.desviacion_pct, r.semaforo, r.justificado, r.observaciones
        FROM reportes_combustible r
        LEFT JOIN obras ob ON ob.id = r.id_obra
        WHERE r.fecha BETWEEN %s AND %s
        ORDER BY
            CASE WHEN r.tipo_combustible = 'diesel' THEN 0 ELSE 1 END,
            r.codigo_eco, r.fecha
    """
    return query(sql, [fi, ff])

# ══════════════════════════════════════════════════════════════════
#  PERMISOS CRUD POR ROL
# ══════════════════════════════════════════════════════════════════

MODULOS_PERMISOS = [
    ("dashboard_completo", "Dashboard KPIs / Alertas / Telemetría"),
    ("equipos",        "Equipos y Maquinaria"),
    ("obras",          "Obras"),
    ("documentos",     "Documentos"),
    ("combustible",    "Combustible / Reportes 360"),
    ("telemetria",     "Ver Telemetría (gráficas/datos)"),
    ("mapa",           "Mapa GPS"),
    ("exportar",       "Exportar Excel"),
    ("planta",         "Producción Avance Físico y Remisiones"),
    ("acarreo",        "Acarreo de Materiales"),
    ("reportes_obra",  "Reportes de Obra Acarreos"),
    ("rrhh",           "Recursos Humanos"),
    ("requisiciones",  "Requisiciones Semanales"),
    ("codigos_costo",  "Códigos de Costo (Admin)"),
    ("comisiones_config", "Comisiones (Admin)"),
    ("proyecciones",   "Proyecciones (Admin)"),
    ("ordenes_compra", "Órdenes de Compra"),
    ("proveedores",    "Proveedores"),
    
    ("analisis_compra", "Análisis de Compra (Cotizaciones)"),
    ("caja_chica",     "Caja Chica / Reembolsos / Viáticos"),
    ("cancelaciones_cfdi", "Solicitudes de Cancelación CFDI"),
    ("contratos",      "Contratos"),
    ("avance_fisico",  "Avance Físico y Financiero"),
    ("avance_captura", "Avance Físico (Captura)"),
    ("estimaciones",   "Estimaciones y Ajustes"),
    ("insumos_propuesta", "Insumos de la Propuesta"),
    ("programa_mano_obra", "Programa Mano de Obra"),
    ("analisis_financiero", "Análisis Financiero"),
    ("liquidacion_obra", "Liquidación de Obra"),
    ("control_ingresos", "Control de Ingresos"),
    ("usuarios",       "Usuarios"),
    ("camaras",        "Cámaras"),
    ("maquinas",       "Maquinaria (Alta/Edición/Baja)"),
    ("control_calidad","Control de Calidad (Órdenes)"),
    ("proveedores_pendientes", "Proveedores Pendientes (Aprobar/Rechazar)"),
    ("auditoria", "Auditoría / Historial de Actividades"),
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
            execute("""INSERT IGNORE INTO permisos_rol (rol, modulo, crear, leer, editar, eliminar, autorizar)
                       VALUES (%s, %s, 0, 0, 0, 0, 0)""", (codigo, modulo))
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
            autorizar TINYINT(1) NOT NULL DEFAULT 0,
            UNIQUE KEY uq_rol_modulo (rol, modulo)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # Migración: agregar columna autorizar si no existe (bases de datos existentes)
    try:
        execute_ddl("ALTER TABLE permisos_rol ADD COLUMN autorizar TINYINT(1) NOT NULL DEFAULT 0")
    except Exception:
        pass  # La columna ya existe

def _defaults_permisos():
    """Devuelve los permisos por defecto para cada rol."""
    # (crear, leer, editar, eliminar)
    defaults = {
        "admin":      {m: (1,1,1,1) for m,_ in MODULOS_PERMISOS},
        "supervisor": {
            "dashboard_completo": (0,0,0,0),
            "equipos":     (0,1,1,0), "obras":       (0,1,1,0),
            "documentos":  (1,1,1,1),
            "combustible": (1,1,1,0), "telemetria":  (0,1,0,0),
            "mapa":        (0,1,0,0),
            "exportar":    (0,1,0,0), "planta":      (1,1,1,0),
            "acarreo":     (1,1,1,0), "usuarios":    (0,0,0,0),
        },
        "operador": {
            "dashboard_completo": (0,0,0,0),
            "equipos":     (0,1,0,0), "obras":       (0,1,0,0),
            "documentos":  (0,1,0,0),
            "combustible": (0,1,0,0), "telemetria":  (0,0,0,0),
            "mapa":        (0,1,0,0),
            "exportar":    (0,0,0,0), "planta":      (1,1,1,0),
            "acarreo":     (0,1,0,0), "usuarios":    (0,0,0,0),
        },
        "reportes": {
            "dashboard_completo": (0,0,0,0),
            "equipos":     (0,1,0,0), "obras":       (0,1,0,0),
            "documentos":  (0,1,0,0),
            "combustible": (1,1,1,0), "telemetria":  (0,0,0,0),
            "mapa":        (0,1,0,0),
            "exportar":    (0,1,0,0), "planta":      (0,0,0,0),
            "acarreo":     (0,1,0,0), "usuarios":    (0,0,0,0),
        },
        "cliente": {
            "dashboard_completo": (0,0,0,0),
            "equipos":     (0,1,0,0), "obras":       (0,1,0,0),
            "documentos":  (0,1,0,0),
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
        if "avance_fisico" not in defaults[rol]:
            defaults[rol]["avance_fisico"] = {
                "admin":      (1,1,1,1),
                "supervisor": (1,1,1,0),
                "operador":   (0,1,0,0),
                "reportes":   (0,1,0,0),
                "cliente":    (0,0,0,0),
            }[rol]
        if "avance_captura" not in defaults[rol]:
            defaults[rol]["avance_captura"] = {
                "admin":      (1,1,1,1),
                "supervisor": (1,1,1,0),
                "operador":   (0,1,0,0),
                "reportes":   (0,0,0,0),
                "cliente":    (0,0,0,0),
            }[rol]
        if "estimaciones" not in defaults[rol]:
            defaults[rol]["estimaciones"] = {
                "admin":      (1,1,1,1),
                "supervisor": (1,1,1,0),
                "operador":   (0,1,0,0),
                "reportes":   (0,1,0,0),
                "cliente":    (0,0,0,0),
            }[rol]
        if "insumos_propuesta" not in defaults[rol]:
            defaults[rol]["insumos_propuesta"] = {
                "admin":      (1,1,1,1),
                "supervisor": (0,1,0,0),
                "operador":   (0,1,0,0),
                "reportes":   (0,1,0,0),
                "cliente":    (0,0,0,0),
            }[rol]
        if "programa_mano_obra" not in defaults[rol]:
            defaults[rol]["programa_mano_obra"] = {
                "admin":      (1,1,1,1),
                "supervisor": (1,1,1,0),
                "operador":   (0,1,0,0),
                "reportes":   (0,1,0,0),
                "cliente":    (0,0,0,0),
            }[rol]
        if "analisis_financiero" not in defaults[rol]:
            defaults[rol]["analisis_financiero"] = {
                "admin":      (1,1,1,1),
                "supervisor": (0,1,0,0),
                "operador":   (0,1,0,0),
                "reportes":   (1,1,0,0),
                "cliente":    (0,0,0,0),
            }[rol]
        if "liquidacion_obra" not in defaults[rol]:
            defaults[rol]["liquidacion_obra"] = {
                "admin":      (1,1,1,1),
                "supervisor": (0,1,0,0),
                "operador":   (0,0,0,0),
                "reportes":   (0,1,0,0),
                "cliente":    (0,0,0,0),
            }[rol]
        if "control_ingresos" not in defaults[rol]:
            defaults[rol]["control_ingresos"] = {
                "admin":      (1,1,1,1),
                "supervisor": (0,1,0,0),
                "operador":   (0,0,0,0),
                "reportes":   (1,1,0,0),
                "cliente":    (0,0,0,0),
            }[rol]
        if "codigos_costo" not in defaults[rol]:
            defaults[rol]["codigos_costo"] = {
                "admin":      (1,1,1,1),
                "supervisor": (0,0,0,0),
                "operador":   (0,0,0,0),
                "reportes":   (0,0,0,0),
                "cliente":    (0,0,0,0),
            }[rol]
        if "comisiones_config" not in defaults[rol]:
            defaults[rol]["comisiones_config"] = {
                "admin":      (1,1,1,1),
                "supervisor": (0,0,0,0),
                "operador":   (0,0,0,0),
                "reportes":   (0,0,0,0),
                "cliente":    (0,0,0,0),
            }[rol]
        if "proyecciones" not in defaults[rol]:
            defaults[rol]["proyecciones"] = {
                "admin":      (1,1,1,1),
                "supervisor": (0,0,0,0),
                "operador":   (0,0,0,0),
                "reportes":   (0,0,0,0),
                "cliente":    (0,0,0,0),
            }[rol]
        # ── Módulos nuevos ────────────────────────────────────────
        if "camaras" not in defaults[rol]:
            defaults[rol]["camaras"] = {
                "admin":      (1,1,1,1),
                "supervisor": (1,1,1,0),
                "operador":   (0,1,0,0),
                "reportes":   (0,1,0,0),
                "cliente":    (0,0,0,0),
            }[rol]
        if "maquinas" not in defaults[rol]:
            # Solo crear/editar/eliminar (leer lo controla "equipos")
            defaults[rol]["maquinas"] = {
                "admin":      (1,1,1,1),
                "supervisor": (1,0,1,0),
                "operador":   (0,0,0,0),
                "reportes":   (0,0,0,0),
                "cliente":    (0,0,0,0),
            }[rol]
        if "control_calidad" not in defaults[rol]:
            # Solo editar = Autorizar
            defaults[rol]["control_calidad"] = {
                "admin":      (1,1,1,1),
                "supervisor": (0,0,1,0),
                "operador":   (0,0,0,0),
                "reportes":   (0,0,0,0),
                "cliente":    (0,0,0,0),
            }[rol]
        if "proveedores_pendientes" not in defaults[rol]:
            # crear = Aprobar,  eliminar = Rechazar
            defaults[rol]["proveedores_pendientes"] = {
                "admin":      (1,1,1,1),
                "supervisor": (1,0,0,1),
                "operador":   (0,0,0,0),
                "reportes":   (0,0,0,0),
                "cliente":    (0,0,0,0),
            }[rol]
    return defaults

def get_permisos_rol(rol):
    """Devuelve dict {modulo: {crear,leer,editar,eliminar}} para un rol."""
    filas = query("SELECT * FROM permisos_rol WHERE rol=%s", (rol,))
    resultado = {}
    for f in filas:
        resultado[f["modulo"]] = {
            "crear":    bool(f["crear"]),
            "leer":     bool(f["leer"]),
            "editar":   bool(f["editar"]),
            "eliminar": bool(f["eliminar"]),
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
            "crear":    bool(f["crear"]),
            "leer":     bool(f["leer"]),
            "editar":   bool(f["editar"]),
            "eliminar": bool(f["eliminar"]),
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
                    INSERT IGNORE INTO permisos_rol (rol,modulo,crear,leer,editar,eliminar,autorizar)
                    VALUES (%s,%s,%s,%s,%s,%s,0)
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
                    INSERT IGNORE INTO permisos_rol (rol,modulo,crear,leer,editar,eliminar,autorizar)
                    VALUES (%s,%s,%s,%s,%s,%s,0)
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
            lts_m3       DECIMAL(8,2) DEFAULT NULL COMMENT 'Rendimiento lts/m3',
            -- ASFALTO
            asf_ini      DECIMAL(10,2) DEFAULT NULL,
            asf_desc     DECIMAL(10,2) DEFAULT NULL,
            asf_cons     DECIMAL(10,2) DEFAULT NULL,
            asf_final    DECIMAL(10,2) DEFAULT NULL,
            asf_kg       DECIMAL(10,2) DEFAULT NULL COMMENT 'Consumo en kg',
            -- COMBUSTIBLE ALTERNO
            alt_ini      DECIMAL(10,2) DEFAULT NULL,
            alt_desc     DECIMAL(10,2) DEFAULT NULL,
            alt_final    DECIMAL(10,2) DEFAULT NULL,
            alt_cons     DECIMAL(10,2) DEFAULT NULL,
            alt_lts_m3   DECIMAL(8,2) DEFAULT NULL,
            -- AVANCE / RENDIMIENTO
            vol_compacto DECIMAL(10,2) DEFAULT NULL COMMENT 'Volumen compactado m3',
            vol_acumulado DECIMAL(12,2) DEFAULT NULL COMMENT 'Volumen acumulado m3',
            abundamiento DECIMAL(6,3) DEFAULT NULL COMMENT 'Factor abundamiento',
            -- EMULSIÓN / LIGA
            emu_lts_m2   DECIMAL(8,3) DEFAULT NULL COMMENT 'Rendimiento lts/m2',
            emu_ini      DECIMAL(10,2) DEFAULT NULL,
            emu_desc     DECIMAL(10,2) DEFAULT NULL,
            emu_cons     DECIMAL(10,2) DEFAULT NULL,
            emu_final    DECIMAL(10,2) DEFAULT NULL,
            -- PÉTREO: GRAVA 3/4" CARPETA
            grava_carpeta_ini    DECIMAL(10,2) DEFAULT NULL,
            grava_carpeta_recib  DECIMAL(10,2) DEFAULT NULL,
            grava_carpeta_cons   DECIMAL(10,2) DEFAULT NULL,
            grava_carpeta_final  DECIMAL(10,2) DEFAULT NULL,
            -- PÉTREO: ARENA
            arena_ini    DECIMAL(10,2) DEFAULT NULL,
            arena_recib  DECIMAL(10,2) DEFAULT NULL,
            arena_cons   DECIMAL(10,2) DEFAULT NULL,
            arena_final  DECIMAL(10,2) DEFAULT NULL,
            -- PÉTREO: GRAVA 3/4" NORMAL
            grava_normal_ini    DECIMAL(10,2) DEFAULT NULL,
            grava_normal_recib  DECIMAL(10,2) DEFAULT NULL,
            grava_normal_cons   DECIMAL(10,2) DEFAULT NULL,
            grava_normal_final  DECIMAL(10,2) DEFAULT NULL,
            -- PÉTREO: GRAVA 3/8" (SELLO)
            grava_sello_ini     DECIMAL(10,2) DEFAULT NULL,
            grava_sello_recib   DECIMAL(10,2) DEFAULT NULL,
            grava_sello_cons    DECIMAL(10,2) DEFAULT NULL,
            grava_sello_final   DECIMAL(10,2) DEFAULT NULL,
            -- PÉTREO: GRAVA 1/2
            grava_medio_ini     DECIMAL(10,2) DEFAULT NULL,
            grava_medio_recib   DECIMAL(10,2) DEFAULT NULL,
            grava_medio_cons    DECIMAL(10,2) DEFAULT NULL,
            grava_medio_final   DECIMAL(10,2) DEFAULT NULL,
            -- CONTROL
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
        SELECT asf_final, alt_final, emu_final, grava_carpeta_ini AS grava_ini, grava_carpeta_recib AS grava_recib,
               arena_ini, arena_recib, vol_m3
        FROM planta_produccion
        WHERE id_obra=%s AND fecha<=%s
        ORDER BY fecha DESC, id DESC LIMIT 1
    """, (id_obra, fecha), one=True)

def crear_planta_produccion(datos):
    cfg = get_planta_config(datos["id_obra"])
    return execute("""
        INSERT INTO planta_produccion
        (id_obra, fecha, material, num_camiones, vol_m3, lts_m3,
         asf_ini, asf_desc, asf_cons, asf_final, asf_kg,
         alt_ini, alt_desc, alt_final, alt_cons, alt_lts_m3,
         vol_compacto, vol_acumulado, abundamiento,
         emu_lts_m2, emu_ini, emu_desc, emu_cons, emu_final,
         grava_carpeta_ini, grava_carpeta_recib, grava_carpeta_cons, grava_carpeta_final,
         arena_ini, arena_recib, arena_cons, arena_final,
         grava_normal_ini, grava_normal_recib, grava_normal_cons, grava_normal_final,
         grava_sello_ini, grava_sello_recib, grava_sello_cons, grava_sello_final,
         grava_medio_ini, grava_medio_recib, grava_medio_cons, grava_medio_final,
         creado_por)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (datos["id_obra"], datos["fecha"], datos.get("material"),
          datos.get("num_camiones"), datos.get("vol_m3"), datos.get("lts_m3"),
          datos.get("asf_ini"), datos.get("asf_desc"), datos.get("asf_cons"), datos.get("asf_final"), datos.get("asf_kg"),
          datos.get("alt_ini"), datos.get("alt_desc"), datos.get("alt_final"), datos.get("alt_cons"), datos.get("alt_lts_m3"),
          datos.get("vol_compacto"), datos.get("vol_acumulado"), datos.get("abundamiento"),
          datos.get("emu_lts_m2"), datos.get("emu_ini"), datos.get("emu_desc"), datos.get("emu_cons"), datos.get("emu_final"),
          datos.get("grava_carpeta_ini"), datos.get("grava_carpeta_recib"), datos.get("grava_carpeta_cons"), datos.get("grava_carpeta_final"),
          datos.get("arena_ini"), datos.get("arena_recib"), datos.get("arena_cons"), datos.get("arena_final"),
          datos.get("grava_normal_ini"), datos.get("grava_normal_recib"), datos.get("grava_normal_cons"), datos.get("grava_normal_final"),
          datos.get("grava_sello_ini"), datos.get("grava_sello_recib"), datos.get("grava_sello_cons"), datos.get("grava_sello_final"),
          datos.get("grava_medio_ini"), datos.get("grava_medio_recib"), datos.get("grava_medio_cons"), datos.get("grava_medio_final"),
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
    # Grava final: usar valor importado si existe, sino calcular desde carpeta
    if f.get("grava_carpeta_final") is not None:
        f["grava_final"] = round(float(f["grava_carpeta_final"]), 2)
    else:
        f["grava_final"] = round(float(f.get("grava_carpeta_ini") or 0) + float(f.get("grava_carpeta_recib") or 0) - f["grava_cons"], 2)
    # Arena final: usar valor importado si existe, sino calcular
    if f.get("arena_final") is not None:
        f["arena_final"] = round(float(f["arena_final"]), 2)
    else:
        f["arena_final"] = round(float(f.get("arena_ini") or 0) + float(f.get("arena_recib") or 0) - f["arena_cons"], 2)
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
    ("planta", "Producción Avance Físico y Remisiones"),
    ("documentos", "Documentos"),
    ("equipos", "Equipos y Maquinaria"),
    ("camaras", "Cámaras"),
    ("maquinas", "Maquinaria (Alta/Edición/Baja)"),
    ("obras", "Obras (Alta/Edición/Baja)"),
    ("mapa", "Mapa GPS"),
    ("exportar", "Exportar Excel"),
    ("acarreo", "Acarreo de Materiales"),
    ("rrhh", "Recursos Humanos"),
    ("requisiciones", "Requisiciones Semanales"),
    ("requisiciones_autorizar", "Autorizar Montos (Requisiciones)"),
   
    ("requisiciones_presupuesto", "Proyecciones (Requisiciones)"),
    ("codigos_costo", "Códigos de Costo"),
    ("comisiones_config", "Comisiones"),
    ("proyecciones", "Proyecciones"),
    ("ordenes_compra", "Órdenes de Compra"),
    ("proveedores", "Proveedores (Alta/Edición/Baja)"),
    ("control_calidad", "Control de Calidad (Órdenes)"),
    ("proveedores_pendientes", "Proveedores Pendientes (Aprobar/Rechazar)"),
]

# Acciones disponibles por módulo en permisos por obra.
# None = mostrar las 4 acciones estándar (crear/leer/editar/eliminar).
# Lista = mostrar solo esas acciones con sus etiquetas personalizadas.
ACCIONES_POR_MODULO = {
    # Módulos con CRUD completo (default — no necesitan entradas aquí)
    # Módulos con acciones restringidas:
    "maquinas":              [("crear","Crear"), ("editar","Editar"), ("eliminar","Eliminar")],
    "obras":                 [("crear","Crear"), ("editar","Editar"), ("eliminar","Eliminar")],
    "proveedores":           [("crear","Crear"), ("editar","Editar"), ("eliminar","Eliminar")],
    "ordenes_compra":        [("crear","Enviar"), ("leer","Ver"), ("editar","Autorizar"), ("eliminar","Rechazar")],
    "control_calidad":       [("editar","Autorizar")],
    "proveedores_pendientes":[("crear","Aprobar"), ("eliminar","Rechazar")],
}


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
            SELECT e.fecha_ultima_actualizacion, e.nivel_combustible, m.capacidad_litros
            FROM estado e
            LEFT JOIN maquinas m ON m.eco = e.codigo_eco
            WHERE e.codigo_eco=%s AND e.nivel_combustible IS NOT NULL
              AND e.fecha_ultima_actualizacion BETWEEN %s AND CONCAT(%s, ' 23:59:59')
            ORDER BY e.fecha_ultima_actualizacion
        """, (eco, fi, ff))
    else:
        return query("""
            SELECT e.fecha_ultima_actualizacion, e.nivel_combustible, m.capacidad_litros
            FROM estado e
            LEFT JOIN maquinas m ON m.eco = e.codigo_eco
            WHERE e.codigo_eco=%s AND e.nivel_combustible IS NOT NULL
              AND e.fecha_ultima_actualizacion >= CURDATE() - INTERVAL 30 DAY
            ORDER BY e.fecha_ultima_actualizacion
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
            horas_diarias     DECIMAL(4,2) DEFAULT 8 COMMENT 'Hrs jornada: 8 diurno, 7 nocturno, manual',
            turno             VARCHAR(20) DEFAULT 'Diurno' COMMENT 'Diurno/Nocturno/Mixto',
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
            frente          VARCHAR(100) DEFAULT NULL COMMENT 'Frente de obra donde se registra',
            entrada         TIME DEFAULT NULL,
            salida          TIME DEFAULT NULL,
            horas_normales  DECIMAL(4,2) DEFAULT NULL,
            horas_extra     DECIMAL(4,2) DEFAULT 0,
            autoriza_extras VARCHAR(150) DEFAULT NULL COMMENT 'Quien autoriza horas extras',
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
            lat             DECIMAL(10,7) DEFAULT NULL COMMENT 'Latitud GPS',
            lng             DECIMAL(10,7) DEFAULT NULL COMMENT 'Longitud GPS',
            accuracy        DECIMAL(8,2) DEFAULT NULL COMMENT 'Precision GPS en metros',
            creado_en       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_empleado_fecha (id_empleado, fecha),
            INDEX idx_fecha (fecha)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS empleado_documentos (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            id_empleado     INT NOT NULL,
            tipo_documento  VARCHAR(60) NOT NULL COMMENT 'CV, Acta, INE, Diploma, etc.',
            descripcion     VARCHAR(255) DEFAULT NULL,
            archivo         VARCHAR(255) NOT NULL COMMENT 'Nombre del archivo en disco',
            archivo_original VARCHAR(255) DEFAULT NULL COMMENT 'Nombre original del archivo subido',
            creado_por      INT DEFAULT NULL,
            creado_en       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_empleado (id_empleado)
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
            sueldo_semanal    DECIMAL(10,2) DEFAULT 0 COMMENT 'Sueldo semanal del empleado',
            pago_horas_extra  DECIMAL(10,2) DEFAULT 0,
            bonos             DECIMAL(10,2) DEFAULT 0,
            devengado         DECIMAL(10,2) DEFAULT 0 COMMENT 'Total bruto: base + extras + bonos',
            descuento_isr     DECIMAL(10,2) DEFAULT 0,
            descuento_imss    DECIMAL(10,2) DEFAULT 0,
            descuento_infonavit DECIMAL(10,2) DEFAULT 0,
            otros_descuentos  DECIMAL(10,2) DEFAULT 0,
            descripcion_otros_desc VARCHAR(255) DEFAULT NULL,
            total_descuentos  DECIMAL(10,2) DEFAULT 0 COMMENT 'Suma ISR+IMSS+Infonavit+otros',
            total_pagar       DECIMAL(10,2) DEFAULT 0 COMMENT 'Devengado - total_descuentos',
            monto_empresa     DECIMAL(10,2) DEFAULT 0 COMMENT 'Costo total empresa (incluye cuotas patronales)',
            validado_por      INT DEFAULT NULL COMMENT 'ID usuario que valida',
            nombre_validador  VARCHAR(150) DEFAULT NULL,
            fecha_validacion  DATETIME DEFAULT NULL,
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
             salario_diario, salario_semanal, horas_diarias, turno,
             tasa_hora_extra, banco, cuenta_banco, clabe,
             contacto_emergencia, foto, creado_por)
        VALUES (%(numero_empleado)s, %(nombre)s, %(apellido_paterno)s, %(apellido_materno)s,
                %(curp)s, %(rfc)s, %(nss)s, %(fecha_nacimiento)s, %(telefono)s, %(email)s, %(direccion)s,
                %(puesto)s, %(departamento)s, %(id_obra)s, %(tipo_contrato)s, %(fecha_ingreso)s,
                %(salario_diario)s, %(salario_semanal)s, %(horas_diarias)s, %(turno)s,
                %(tasa_hora_extra)s, %(banco)s, %(cuenta_banco)s, %(clabe)s,
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
            horas_diarias=%(horas_diarias)s, turno=%(turno)s,
            tasa_hora_extra=%(tasa_hora_extra)s,
            banco=%(banco)s, cuenta_banco=%(cuenta_banco)s, clabe=%(clabe)s,
            contacto_emergencia=%(contacto_emergencia)s, foto=%(foto)s
        WHERE id=%(id)s
    """, d)


def baja_empleado(eid, fecha_baja):
    execute("UPDATE empleados SET activo=0, fecha_baja=%s WHERE id=%s", (fecha_baja, eid))


def reactivar_empleado(eid):
    execute("UPDATE empleados SET activo=1, fecha_baja=NULL WHERE id=%s", (eid,))


# ── DOCUMENTOS DE EMPLEADO ────────────────────────────────────────

def get_documentos_empleado(id_empleado):
    return query("SELECT * FROM empleado_documentos WHERE id_empleado=%s ORDER BY creado_en DESC",
                 (id_empleado,))


def crear_documento_empleado(id_empleado, tipo_documento, archivo, archivo_original, descripcion=None, creado_por=None):
    return execute("""
        INSERT INTO empleado_documentos (id_empleado, tipo_documento, descripcion, archivo, archivo_original, creado_por)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (id_empleado, tipo_documento, descripcion, archivo, archivo_original, creado_por))


def eliminar_documento_empleado(doc_id):
    doc = query("SELECT archivo FROM empleado_documentos WHERE id=%s", (doc_id,), one=True)
    execute("DELETE FROM empleado_documentos WHERE id=%s", (doc_id,))
    return doc.get("archivo") if doc else None


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
                          horas_normales, horas_extra, tipo, observaciones, registrado_por,
                          frente=None, autoriza_extras=None):
    return execute("""
        INSERT INTO asistencia
            (id_empleado, fecha, id_obra, frente, entrada, salida, horas_normales,
             horas_extra, autoriza_extras, tipo, observaciones, registrado_por)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            id_obra=VALUES(id_obra), frente=VALUES(frente),
            entrada=VALUES(entrada), salida=VALUES(salida),
            horas_normales=VALUES(horas_normales), horas_extra=VALUES(horas_extra),
            autoriza_extras=VALUES(autoriza_extras),
            tipo=VALUES(tipo), observaciones=VALUES(observaciones),
            registrado_por=VALUES(registrado_por)
    """, (id_empleado, fecha, id_obra, frente or None, entrada or None, salida or None,
          horas_normales, horas_extra, autoriza_extras or None,
          tipo, observaciones or None, registrado_por))


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


def registrar_escaneo_qr(id_empleado, fecha, hora, tipo, id_obra=None, foto_evidencia=None,
                         lat=None, lng=None, accuracy=None):
    """Registra un escaneo QR (entrada o salida) con coordenadas GPS opcionales."""
    execute("""
        INSERT INTO escaneos_qr (id_empleado, fecha, hora, tipo, id_obra, foto_evidencia, lat, lng, accuracy)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (id_empleado, fecha, hora, tipo, id_obra, foto_evidencia, lat, lng, accuracy))
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

    # Obtener horas_diarias del empleado para separar normales de extras
    emp = get_empleado(id_empleado)
    jornada = float(emp.get("horas_diarias") or 8) if emp else 8.0
    horas_normales = min(horas_total, jornada)
    horas_extra = round(max(horas_total - jornada, 0), 2)

    execute("""
        INSERT INTO asistencia (id_empleado, fecha, id_obra, entrada, salida,
                                horas_normales, horas_extra, tipo, observaciones)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'asistencia', %s)
        ON DUPLICATE KEY UPDATE
            entrada=VALUES(entrada), salida=VALUES(salida),
            horas_normales=VALUES(horas_normales), horas_extra=VALUES(horas_extra),
            tipo='asistencia', observaciones=VALUES(observaciones)
    """, (id_empleado, fecha, id_obra, primera_entrada, ultima_salida,
          round(horas_normales, 1), round(horas_extra, 1), obs))


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
               GROUP_CONCAT(DISTINCT a.frente ORDER BY a.fecha SEPARATOR ', ') AS frentes,
               GROUP_CONCAT(DISTINCT a.autoriza_extras SEPARATOR ', ') AS autoriza_extras,
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
    basándose en su asistencia de la semana.
    Calcula: devengado, descuentos (ISR, IMSS, Infonavit), neto a pagar, monto empresa."""
    empleados_activos = get_empleados(obra=id_obra, activo=1)
    count = 0
    for emp in empleados_activos:
        salario_diario = float(emp.get("salario_diario") or 0)
        sueldo_semanal = float(emp.get("salario_semanal") or 0)
        if salario_diario <= 0 and sueldo_semanal <= 0:
            continue  # Sin salario configurado, no genera nómina

        # Si no tiene sueldo semanal pero sí diario, calcular
        if sueldo_semanal <= 0 and salario_diario > 0:
            horas_jornada = float(emp.get("horas_diarias") or 8)
            dias_jornada = 6 if horas_jornada >= 8 else 6  # 6 dias semana standard
            sueldo_semanal = round(salario_diario * dias_jornada, 2)
        # Si tiene semanal pero no diario, derivar diario
        if salario_diario <= 0 and sueldo_semanal > 0:
            salario_diario = round(sueldo_semanal / 6, 2)

        # Obtener asistencia de la semana
        asist = get_asistencia_empleado(emp["id"], fecha_inicio, fecha_fin)
        dias_trab = sum(1 for a in asist if a["tipo"] == "asistencia")
        hrs_normales = sum(float(a.get("horas_normales") or 0) for a in asist)
        hrs_extra = sum(float(a.get("horas_extra") or 0) for a in asist)

        salario_base = round(salario_diario * dias_trab, 2)
        # Tasa de hora extra: configurable por empleado, default = (salario_diario / horas_diarias) * 2
        horas_jornada = float(emp.get("horas_diarias") or 8)
        tasa_hora_extra = float(emp.get("tasa_hora_extra") or 0)
        if tasa_hora_extra <= 0:
            tasa_hora_extra = round((salario_diario / horas_jornada) * 2, 2)
        pago_extras = round(hrs_extra * tasa_hora_extra, 2)

        # Devengado = salario_base + horas_extra + bonos
        devengado = round(salario_base + pago_extras, 2)

        # Descuentos (proporcionales al devengado, tasas aproximadas Mexico)
        # ISR: ~10% para rango salarial obrero/campo (simplificado)
        # IMSS trabajador: ~2.775% sobre SBC
        # Infonavit: 0% trabajador (lo paga empresa), pero puede haber crédito
        descuento_isr = round(devengado * 0.02, 2)  # Tasa baja para este rango salarial
        descuento_imss = round(devengado * 0.02775, 2)
        descuento_infonavit = 0.0  # Se ajusta manualmente si tiene crédito
        total_descuentos = round(descuento_isr + descuento_imss + descuento_infonavit, 2)

        # Total neto a pagar
        total = round(devengado - total_descuentos, 2)

        # Monto empresa (cuotas patronales aprox: IMSS patrón ~20%, Infonavit 5%, etc.)
        monto_empresa = round(devengado * 1.30, 2)  # Factor patronal estimado

        execute("""
            INSERT INTO nomina
                (id_empleado, semana, fecha_inicio, fecha_fin, dias_trabajados,
                 horas_normales, horas_extra, salario_base, sueldo_semanal,
                 pago_horas_extra, devengado,
                 descuento_isr, descuento_imss, descuento_infonavit,
                 total_descuentos, total_pagar, monto_empresa, generado_por)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
                dias_trabajados=VALUES(dias_trabajados),
                horas_normales=VALUES(horas_normales),
                horas_extra=VALUES(horas_extra),
                salario_base=VALUES(salario_base),
                sueldo_semanal=VALUES(sueldo_semanal),
                pago_horas_extra=VALUES(pago_horas_extra),
                devengado=VALUES(devengado),
                descuento_isr=VALUES(descuento_isr),
                descuento_imss=VALUES(descuento_imss),
                descuento_infonavit=VALUES(descuento_infonavit),
                total_descuentos=VALUES(total_descuentos),
                total_pagar=VALUES(total_pagar),
                monto_empresa=VALUES(monto_empresa)
        """, (emp["id"], semana, fecha_inicio, fecha_fin, dias_trab,
              hrs_normales, hrs_extra, salario_base, sueldo_semanal,
              pago_extras, devengado,
              descuento_isr, descuento_imss, descuento_infonavit,
              total_descuentos, total, monto_empresa, generado_por))
        count += 1
    return count


def get_nomina_semanal(semana, id_obra=None):
    sql = """
        SELECT n.*, e.nombre, e.apellido_paterno, e.apellido_materno,
               e.numero_empleado, e.puesto, e.departamento, e.banco, e.cuenta_banco,
               e.salario_semanal AS emp_salario_semanal,
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
            ROUND(SUM(devengado), 2) AS total_devengado,
            ROUND(SUM(total_descuentos), 2) AS total_descuentos,
            ROUND(SUM(total_pagar), 2) AS gran_total,
            ROUND(SUM(monto_empresa), 2) AS total_monto_empresa,
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
    # Tabla de configuración de comisiones
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS config_comisiones (
            id INT AUTO_INCREMENT PRIMARY KEY,
            clave VARCHAR(50) NOT NULL UNIQUE,
            valor DECIMAL(6,2) NOT NULL,
            descripcion VARCHAR(200) DEFAULT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # Insertar valores por defecto si no existen
    try:
        execute("INSERT IGNORE INTO config_comisiones (clave, valor, descripcion) VALUES (%s, %s, %s)",
                ("comision_imss", 42.00, "Porcentaje de comisión para nómina con IMSS"))
        execute("INSERT IGNORE INTO config_comisiones (clave, valor, descripcion) VALUES (%s, %s, %s)",
                ("comision_sin_imss", 30.00, "Porcentaje de comisión para nómina sin IMSS"))
    except Exception:
        pass
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
            id_codigo_costo   INT DEFAULT NULL COMMENT 'Liga a catalogo codigos_costo',
            categoria         VARCHAR(50) NOT NULL DEFAULT 'Otros',
            proveedor         VARCHAR(200) DEFAULT NULL,
            contacto_proveedor VARCHAR(200) DEFAULT NULL,
            concepto          TEXT DEFAULT NULL,
            periodo           VARCHAR(120) DEFAULT NULL,
            monto_solicitado  DECIMAL(12,2) DEFAULT 0,
            monto_autorizado  DECIMAL(12,2) DEFAULT 0,
            observaciones     VARCHAR(255) DEFAULT NULL,
            INDEX idx_req (id_requisicion),
            INDEX idx_cat (categoria),
            INDEX idx_codigo_costo (id_codigo_costo)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS nomina_imss (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            id_requisicion      INT NOT NULL,
            id_obra             INT DEFAULT NULL,
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
            INDEX idx_obra (id_obra),
            INDEX idx_emp (id_empleado)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS nomina_sin_imss (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            id_requisicion      INT NOT NULL,
            id_obra             INT DEFAULT NULL,
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
            INDEX idx_obra (id_obra),
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
    # Migración: agregar id_obra a tablas existentes si no existe
    for tabla in ("nomina_imss", "nomina_sin_imss"):
        try:
            execute_ddl(f"ALTER TABLE {tabla} ADD COLUMN id_obra INT DEFAULT NULL")
        except Exception:
            pass  # columna ya existe
        try:
            execute_ddl(f"ALTER TABLE {tabla} ADD INDEX idx_obra (id_obra)")
        except Exception:
            pass  # índice ya existe


# ── CONFIGURACIÓN DE COMISIONES ───────────────────────────────────

def get_config_comision_imss():
    """Retorna el porcentaje de comisión IMSS (ej: 42.0)."""
    r = query("SELECT valor FROM config_comisiones WHERE clave='comision_imss'", one=True)
    return float(r["valor"]) if r else 42.0


def get_config_comision_sin_imss():
    """Retorna el porcentaje de comisión Sin IMSS (ej: 30.0)."""
    r = query("SELECT valor FROM config_comisiones WHERE clave='comision_sin_imss'", one=True)
    return float(r["valor"]) if r else 30.0


def set_config_comision(clave, valor):
    """Actualiza un porcentaje de comisión."""
    execute("UPDATE config_comisiones SET valor=%s WHERE clave=%s", (valor, clave))


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


# ── COMPROBANTES DE PAGO (adjuntos a requisiciones) ────────────────
def _crear_tabla_comprobantes_requisicion():
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS requisicion_comprobantes (
            id INT AUTO_INCREMENT PRIMARY KEY,
            id_requisicion INT NOT NULL,
            nombre_archivo VARCHAR(255) NOT NULL,
            nombre_original VARCHAR(255) NOT NULL,
            tipo_archivo VARCHAR(50),
            subido_por INT,
            creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX(id_requisicion)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

try:
    _crear_tabla_comprobantes_requisicion()
except Exception:
    pass


def guardar_comprobante_requisicion(id_requisicion, nombre_archivo, nombre_original, tipo_archivo, subido_por):
    return execute("""
        INSERT INTO requisicion_comprobantes (id_requisicion, nombre_archivo, nombre_original, tipo_archivo, subido_por)
        VALUES (%s, %s, %s, %s, %s)
    """, (id_requisicion, nombre_archivo, nombre_original, tipo_archivo, subido_por))


def get_comprobantes_requisicion(id_requisicion):
    return query("""
        SELECT rc.*, u.nombre AS subido_por_nombre
        FROM requisicion_comprobantes rc
        LEFT JOIN usuarios u ON u.id = rc.subido_por
        WHERE rc.id_requisicion = %s
        ORDER BY rc.creado_en DESC
    """, (id_requisicion,))


def get_comprobante_requisicion(comp_id):
    return query("SELECT * FROM requisicion_comprobantes WHERE id=%s", (comp_id,), one=True)


def eliminar_comprobante_requisicion(comp_id):
    comp = query("SELECT * FROM requisicion_comprobantes WHERE id=%s", (comp_id,), one=True)
    if comp:
        execute("DELETE FROM requisicion_comprobantes WHERE id=%s", (comp_id,))
    return comp


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
    return query("""
        SELECT p.*, cc.codigo AS codigo_costo_codigo, cc.descripcion AS codigo_costo_nombre
        FROM requisicion_partidas p
        LEFT JOIN codigos_costo cc ON cc.id = p.id_codigo_costo
        WHERE p.id_requisicion=%s ORDER BY p.categoria, p.id
    """, (id_requisicion,))


def crear_partida_requisicion(d):
    d = dict(d)
    d.setdefault("id_codigo_costo", None)
    d.setdefault("cantidad", None)
    d.setdefault("unidad", None)
    d.setdefault("estatus_pago", "pendiente")
    d.setdefault("id_partida_origen", None)
    d.setdefault("semana_origen", None)
    return execute("""
        INSERT INTO requisicion_partidas
            (id_requisicion, id_codigo_costo, categoria, proveedor, contacto_proveedor, concepto,
             periodo, monto_solicitado, monto_autorizado, observaciones, cantidad, unidad,
             estatus_pago, id_partida_origen, semana_origen)
        VALUES (%(id_requisicion)s, %(id_codigo_costo)s, %(categoria)s, %(proveedor)s, %(contacto_proveedor)s,
                %(concepto)s, %(periodo)s, %(monto_solicitado)s, %(monto_autorizado)s, %(observaciones)s,
                %(cantidad)s, %(unidad)s, %(estatus_pago)s, %(id_partida_origen)s, %(semana_origen)s)
    """, d)


def actualizar_pago_partida(pid, estatus_pago, fecha_pago=None, no_factura=None,
                             factura_nombre=None, factura_archivo=None):
    """Marca una partida como pagada/cancelada/pendiente y opcionalmente adjunta factura."""
    execute("""
        UPDATE requisicion_partidas
           SET estatus_pago=%s, fecha_pago=%s, no_factura=%s,
               factura_nombre=%s, factura_archivo=%s
         WHERE id=%s
    """, (estatus_pago, fecha_pago or None, no_factura or None,
          factura_nombre or None, factura_archivo or None, pid))


def get_partidas_pendientes_obra(id_obra, excluir_requisicion=None):
    """Devuelve partidas con estatus_pago='pendiente' de semanas anteriores de una obra.
    Se usa para proponer arrastre al crear una nueva requisición."""
    sql = """
        SELECT p.*,
               r.semana, r.semana_num, r.fecha_inicio, r.fecha_fin, r.empresa,
               cc.codigo AS codigo_costo_codigo, cc.descripcion AS codigo_costo_nombre
        FROM requisicion_partidas p
        JOIN requisiciones r ON r.id = p.id_requisicion
        LEFT JOIN codigos_costo cc ON cc.id = p.id_codigo_costo
        WHERE r.id_obra = %s
          AND p.estatus_pago = 'pendiente'
          AND r.estatus NOT IN ('cancelado')
    """
    params = [id_obra]
    if excluir_requisicion:
        sql += " AND r.id != %s"
        params.append(excluir_requisicion)
    sql += " ORDER BY r.semana_num DESC, p.categoria, p.id"
    return query(sql, params)


def get_egresos_pagados_obra(id_obra=None):
    """Devuelve totales de partidas PAGADAS agrupadas por obra para Control de Ingresos."""
    sql = """
        SELECT
            r.id_obra,
            o.nombre AS obra_nombre,
            r.semana,
            r.semana_num,
            p.categoria,
            COUNT(p.id)                        AS total_partidas,
            SUM(p.monto_autorizado)             AS total_autorizado,
            SUM(p.monto_solicitado)             AS total_solicitado,
            MAX(p.fecha_pago)                   AS ultima_fecha_pago
        FROM requisicion_partidas p
        JOIN requisiciones r ON r.id = p.id_requisicion
        LEFT JOIN obras o ON o.id = r.id_obra
        WHERE p.estatus_pago = 'pagado'
    """
    params = []
    if id_obra:
        sql += " AND r.id_obra = %s"
        params.append(id_obra)
    sql += " GROUP BY r.id_obra, o.nombre, r.semana, r.semana_num, p.categoria ORDER BY r.semana_num DESC, p.categoria"
    return query(sql, params)


def get_totales_egresos_pagados(id_obra=None):
    """Totales consolidados de egresos pagados para KPIs de Control de Ingresos."""
    sql = """
        SELECT
            COALESCE(SUM(p.monto_autorizado), 0) AS total_egresado,
            COALESCE(SUM(p.monto_solicitado), 0) AS total_solicitado,
            COUNT(p.id)                          AS total_partidas_pagadas
        FROM requisicion_partidas p
        JOIN requisiciones r ON r.id = p.id_requisicion
        WHERE p.estatus_pago = 'pagado'
    """
    params = []
    if id_obra:
        sql += " AND r.id_obra = %s"
        params.append(id_obra)
    return query(sql, params, one=True)


def get_nomina_imss_requisicion(id_requisicion):
    return query("SELECT * FROM nomina_imss WHERE id_requisicion=%s ORDER BY categoria_personal, id",
                 (id_requisicion,))


def get_nomina_imss_por_obra(id_obra=None):
    if id_obra:
        return query("""
            SELECT n.*, r.semana, r.empresa, COALESCE(n.id_obra, r.id_obra) AS id_obra_efectiva
            FROM nomina_imss n
            LEFT JOIN requisiciones r ON r.id = n.id_requisicion
            WHERE (n.id_obra=%s OR r.id_obra=%s)
            ORDER BY r.semana DESC, n.categoria_personal, n.id
        """, (id_obra, id_obra))
    return query("""
        SELECT n.*, r.semana, r.empresa, COALESCE(n.id_obra, r.id_obra) AS id_obra_efectiva
        FROM nomina_imss n
        LEFT JOIN requisiciones r ON r.id = n.id_requisicion
        ORDER BY r.semana DESC, n.categoria_personal, n.id
    """)


def get_nomina_sin_imss_por_obra(id_obra=None):
    if id_obra:
        return query("""
            SELECT n.*, r.semana, r.empresa, COALESCE(n.id_obra, r.id_obra) AS id_obra_efectiva
            FROM nomina_sin_imss n
            LEFT JOIN requisiciones r ON r.id = n.id_requisicion
            WHERE (n.id_obra=%s OR r.id_obra=%s)
            ORDER BY r.semana DESC, n.id
        """, (id_obra, id_obra))
    return query("""
        SELECT n.*, r.semana, r.empresa, COALESCE(n.id_obra, r.id_obra) AS id_obra_efectiva
        FROM nomina_sin_imss n
        LEFT JOIN requisiciones r ON r.id = n.id_requisicion
        ORDER BY r.semana DESC, n.id
    """)


def get_finiquitos_por_obra(id_obra=None):
    if id_obra:
        return query("""
            SELECT f.*, r.semana, r.empresa, COALESCE(f.id_obra, r.id_obra) AS id_obra_efectiva
            FROM finiquitos f
            LEFT JOIN requisiciones r ON r.id = f.id_requisicion
            WHERE (f.id_obra=%s OR r.id_obra=%s)
            ORDER BY r.semana DESC, f.id
        """, (id_obra, id_obra))
    return query("""
        SELECT f.*, r.semana, r.empresa, COALESCE(f.id_obra, r.id_obra) AS id_obra_efectiva
        FROM finiquitos f
        LEFT JOIN requisiciones r ON r.id = f.id_requisicion
        ORDER BY r.semana DESC, f.id
    """)


def get_descansos_por_obra(id_obra=None):
    if id_obra:
        return query("""
            SELECT d.*, r.semana, r.empresa, r.id_obra AS id_obra_efectiva
            FROM requisicion_descansos d
            LEFT JOIN requisiciones r ON r.id = d.id_requisicion
            WHERE r.id_obra=%s
            ORDER BY r.semana DESC, d.id
        """, (id_obra,))
    return query("""
        SELECT d.*, r.semana, r.empresa, r.id_obra AS id_obra_efectiva
        FROM requisicion_descansos d
        LEFT JOIN requisiciones r ON r.id = d.id_requisicion
        ORDER BY r.semana DESC, d.id
    """)


def get_partidas_por_obra(id_obra=None):
    if id_obra:
        return query("""
            SELECT p.*, r.semana, r.empresa, r.id_obra AS id_obra_efectiva,
                   cc.codigo AS codigo_costo_codigo, cc.descripcion AS codigo_costo_nombre
            FROM requisicion_partidas p
            LEFT JOIN requisiciones r ON r.id = p.id_requisicion
            LEFT JOIN codigos_costo cc ON cc.id = p.id_codigo_costo
            WHERE r.id_obra=%s
            ORDER BY r.semana DESC, p.categoria, p.id
        """, (id_obra,))
    return query("""
        SELECT p.*, r.semana, r.empresa, r.id_obra AS id_obra_efectiva,
               cc.codigo AS codigo_costo_codigo, cc.descripcion AS codigo_costo_nombre
        FROM requisicion_partidas p
        LEFT JOIN requisiciones r ON r.id = p.id_requisicion
        LEFT JOIN codigos_costo cc ON cc.id = p.id_codigo_costo
        ORDER BY r.semana DESC, p.categoria, p.id
    """)


def crear_nomina_imss(d):
    d = dict(d)
    d.setdefault("id_obra", None)
    return execute("""
        INSERT INTO nomina_imss
            (id_requisicion, id_obra, id_empleado, nombre_empleado, puesto, categoria_personal,
             fecha_ingreso, dias, salario_diario, salario_proporcional, salario_semanal,
             horas_extra, costo_horas_extra, descanso_pagado, compensacion,
             pago_tiempo_extra, comidas, total_real, observaciones)
        VALUES (%(id_requisicion)s, %(id_obra)s, %(id_empleado)s, %(nombre_empleado)s, %(puesto)s,
                %(categoria_personal)s, %(fecha_ingreso)s, %(dias)s, %(salario_diario)s,
                %(salario_proporcional)s, %(salario_semanal)s, %(horas_extra)s,
                %(costo_horas_extra)s, %(descanso_pagado)s, %(compensacion)s,
                %(pago_tiempo_extra)s, %(comidas)s, %(total_real)s, %(observaciones)s)
    """, d)


def get_nomina_sin_imss_requisicion(id_requisicion):
    return query("SELECT * FROM nomina_sin_imss WHERE id_requisicion=%s ORDER BY id",
                 (id_requisicion,))


def crear_nomina_sin_imss(d):
    d = dict(d)
    d.setdefault("id_obra", None)
    return execute("""
        INSERT INTO nomina_sin_imss
            (id_requisicion, id_obra, id_empleado, nombre_empleado, puesto,
             dias, salario_diario, salario_proporcional, salario_semanal,
             horas_extra, costo_horas_extra, compensacion,
             pago_tiempo_extra, comidas, total_real, observaciones)
        VALUES (%(id_requisicion)s, %(id_obra)s, %(id_empleado)s, %(nombre_empleado)s, %(puesto)s,
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


def sync_requisicion_a_nomina(rid):
    """Sincroniza los registros de nómina IMSS y sin IMSS de una requisición
    hacia la tabla de nómina de RRHH. Solo sincroniza registros que tengan id_empleado asignado.
    Retorna (sincronizados, omitidos_sin_empleado)."""
    req = query("SELECT * FROM requisiciones WHERE id=%s", (rid,), one=True)
    if not req:
        return 0, 0

    semana = req.get("semana") or f"REQ-{rid}"
    fecha_inicio = req.get("fecha_inicio")
    fecha_fin = req.get("fecha_fin")

    # Si no hay fechas, usar la fecha de creación
    if not fecha_inicio:
        from datetime import date as _date
        fecha_inicio = _date.today().isoformat()
        fecha_fin = fecha_inicio

    sincronizados = 0
    omitidos = 0

    # ── Procesar nomina_imss ──
    registros_imss = get_nomina_imss_requisicion(rid)
    for r in registros_imss:
        id_emp = r.get("id_empleado")
        if not id_emp:
            # Intentar buscar por nombre
            nombre = r.get("nombre_empleado", "").strip()
            if nombre:
                # Buscar empleado por nombre similar
                partes = nombre.split()
                if len(partes) >= 2:
                    emp = query("""SELECT id FROM empleados
                                   WHERE CONCAT(nombre,' ',apellido_paterno) LIKE %s
                                      OR CONCAT(apellido_paterno,' ',nombre) LIKE %s
                                   LIMIT 1""",
                                (f"%{nombre}%", f"%{nombre}%"), one=True)
                    if emp:
                        id_emp = emp["id"]
                        # Actualizar el registro de nomina_imss con el id_empleado encontrado
                        execute("UPDATE nomina_imss SET id_empleado=%s WHERE id=%s", (id_emp, r["id"]))

        if not id_emp:
            omitidos += 1
            continue

        # Insertar/actualizar en tabla nomina de RRHH
        salario_base = float(r.get("salario_semanal") or r.get("salario_proporcional") or 0)
        pago_extras = float(r.get("pago_tiempo_extra") or 0)
        comidas = float(r.get("comidas") or 0)
        total_real = float(r.get("total_real") or 0)
        devengado = total_real if total_real > 0 else salario_base + pago_extras + comidas
        dias = int(r.get("dias") or 0)
        hrs_extra = float(r.get("horas_extra") or 0)
        sueldo_semanal = float(r.get("salario_semanal") or 0)
        salario_diario = float(r.get("salario_diario") or 0)

        execute("""
            INSERT INTO nomina
                (id_empleado, semana, fecha_inicio, fecha_fin, dias_trabajados,
                 horas_normales, horas_extra, salario_base, sueldo_semanal,
                 pago_horas_extra, devengado,
                 descuento_isr, descuento_imss, descuento_infonavit,
                 total_descuentos, total_pagar, monto_empresa,
                 observaciones, generado_por)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,0,0,0,%s,%s,%s,NULL)
            ON DUPLICATE KEY UPDATE
                dias_trabajados=VALUES(dias_trabajados),
                horas_extra=VALUES(horas_extra),
                salario_base=VALUES(salario_base),
                sueldo_semanal=VALUES(sueldo_semanal),
                pago_horas_extra=VALUES(pago_horas_extra),
                devengado=VALUES(devengado),
                total_pagar=VALUES(total_pagar),
                monto_empresa=VALUES(monto_empresa),
                observaciones=VALUES(observaciones)
        """, (id_emp, semana, fecha_inicio, fecha_fin, dias,
              dias * 8, hrs_extra, salario_base, sueldo_semanal,
              pago_extras, devengado,
              total_real, round(total_real * 1.30, 2),
              f"Desde REQ #{rid} (IMSS)", None))
        sincronizados += 1

    # ── Procesar nomina_sin_imss ──
    registros_sin = get_nomina_sin_imss_requisicion(rid)
    for r in registros_sin:
        id_emp = r.get("id_empleado")
        if not id_emp:
            nombre = r.get("nombre_empleado", "").strip()
            if nombre:
                partes = nombre.split()
                if len(partes) >= 2:
                    emp = query("""SELECT id FROM empleados
                                   WHERE CONCAT(nombre,' ',apellido_paterno) LIKE %s
                                      OR CONCAT(apellido_paterno,' ',nombre) LIKE %s
                                   LIMIT 1""",
                                (f"%{nombre}%", f"%{nombre}%"), one=True)
                    if emp:
                        id_emp = emp["id"]
                        execute("UPDATE nomina_sin_imss SET id_empleado=%s WHERE id=%s", (id_emp, r["id"]))

        if not id_emp:
            omitidos += 1
            continue

        salario_base = float(r.get("salario_semanal") or r.get("salario_proporcional") or 0)
        pago_extras = float(r.get("pago_tiempo_extra") or 0)
        comidas = float(r.get("comidas") or 0)
        total_real = float(r.get("total_real") or 0)
        devengado = total_real if total_real > 0 else salario_base + pago_extras + comidas
        dias = int(r.get("dias") or 0)
        hrs_extra = float(r.get("horas_extra") or 0)
        sueldo_semanal = float(r.get("salario_semanal") or 0)

        execute("""
            INSERT INTO nomina
                (id_empleado, semana, fecha_inicio, fecha_fin, dias_trabajados,
                 horas_normales, horas_extra, salario_base, sueldo_semanal,
                 pago_horas_extra, devengado,
                 descuento_isr, descuento_imss, descuento_infonavit,
                 total_descuentos, total_pagar, monto_empresa,
                 observaciones, generado_por)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,0,0,0,%s,%s,%s,NULL)
            ON DUPLICATE KEY UPDATE
                dias_trabajados=VALUES(dias_trabajados),
                horas_extra=VALUES(horas_extra),
                salario_base=VALUES(salario_base),
                sueldo_semanal=VALUES(sueldo_semanal),
                pago_horas_extra=VALUES(pago_horas_extra),
                devengado=VALUES(devengado),
                total_pagar=VALUES(total_pagar),
                monto_empresa=VALUES(monto_empresa),
                observaciones=VALUES(observaciones)
        """, (id_emp, semana, fecha_inicio, fecha_fin, dias,
              dias * 8, hrs_extra, salario_base, sueldo_semanal,
              pago_extras, devengado,
              total_real, round(total_real * 1.0, 2),
              f"Desde REQ #{rid} (Sin IMSS)", None))
        sincronizados += 1

    return sincronizados, omitidos


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
    """Recalcula total_solicitado y total_autorizado sumando SOLO partidas.
    Las nóminas (IMSS/Sin IMSS) y finiquitos son desglose de las partidas,
    no se suman por separado para evitar duplicación."""
    partidas = query("""SELECT COALESCE(SUM(monto_solicitado),0) AS sol,
                               COALESCE(SUM(monto_autorizado),0) AS aut
                        FROM requisicion_partidas WHERE id_requisicion=%s""", (rid,), one=True)
    total_sol = float(partidas["sol"])
    total_aut = float(partidas["aut"])
    # Si no hay partidas pero sí hay nómina/finiquitos (creación manual sin partidas REQ),
    # entonces sí sumar nóminas y finiquitos como respaldo
    if total_sol == 0:
        nom_imss = query("SELECT COALESCE(SUM(total_real),0) AS total FROM nomina_imss WHERE id_requisicion=%s",
                         (rid,), one=True)
        nom_sin = query("SELECT COALESCE(SUM(total_real),0) AS total FROM nomina_sin_imss WHERE id_requisicion=%s",
                        (rid,), one=True)
        finiq = query("SELECT COALESCE(SUM(costo_empresa),0) AS total FROM finiquitos WHERE id_requisicion=%s",
                      (rid,), one=True)
        total_sol = float(nom_imss["total"]) + float(nom_sin["total"]) + float(finiq["total"])
        total_aut = total_sol
    execute("UPDATE requisiciones SET total_solicitado=%s, total_autorizado=%s WHERE id=%s",
            (round(total_sol, 2), round(total_aut, 2), rid))
    # Recalcular total de cantidades en unidades (m³, ton, etc.)
    cant_info = query("""SELECT COALESCE(SUM(cantidad),0) AS total_cant,
                                (SELECT unidad FROM requisicion_partidas
                                 WHERE id_requisicion=%s AND cantidad IS NOT NULL AND unidad IS NOT NULL
                                 LIMIT 1) AS unidad_cant
                         FROM requisicion_partidas
                         WHERE id_requisicion=%s AND cantidad IS NOT NULL""",
                      (rid, rid), one=True)
    total_cant = float(cant_info["total_cant"]) if cant_info else 0
    unidad_cant = cant_info.get("unidad_cant") or None if cant_info else None
    execute("UPDATE requisiciones SET total_cantidad=%s, unidad_cantidad=%s WHERE id=%s",
            (round(total_cant, 3) if total_cant else None, unidad_cant, rid))


def _recalcular_solo_solicitado(rid):
    """Recalcula total_solicitado y cantidades (m³/ton) SIN tocar total_autorizado.
    Se usa cuando el usuario fijó un total_autorizado_manual."""
    partidas = query("""SELECT COALESCE(SUM(monto_solicitado),0) AS sol
                        FROM requisicion_partidas WHERE id_requisicion=%s""", (rid,), one=True)
    total_sol = float(partidas["sol"])
    if total_sol == 0:
        nom_imss = query("SELECT COALESCE(SUM(total_real),0) AS total FROM nomina_imss WHERE id_requisicion=%s",
                         (rid,), one=True)
        nom_sin = query("SELECT COALESCE(SUM(total_real),0) AS total FROM nomina_sin_imss WHERE id_requisicion=%s",
                        (rid,), one=True)
        finiq = query("SELECT COALESCE(SUM(costo_empresa),0) AS total FROM finiquitos WHERE id_requisicion=%s",
                      (rid,), one=True)
        total_sol = float(nom_imss["total"]) + float(nom_sin["total"]) + float(finiq["total"])
    execute("UPDATE requisiciones SET total_solicitado=%s WHERE id=%s", (round(total_sol, 2), rid))
    # Recalcular cantidades en unidades (m³, ton, etc.) sin alterar total_autorizado
    cant_info = query("""SELECT COALESCE(SUM(cantidad),0) AS total_cant,
                                (SELECT unidad FROM requisicion_partidas
                                 WHERE id_requisicion=%s AND cantidad IS NOT NULL AND unidad IS NOT NULL
                                 LIMIT 1) AS unidad_cant
                         FROM requisicion_partidas
                         WHERE id_requisicion=%s AND cantidad IS NOT NULL""",
                      (rid, rid), one=True)
    total_cant = float(cant_info["total_cant"]) if cant_info else 0
    unidad_cant = cant_info.get("unidad_cant") or None if cant_info else None
    execute("UPDATE requisiciones SET total_cantidad=%s, unidad_cantidad=%s WHERE id=%s",
            (round(total_cant, 3) if total_cant else None, unidad_cant, rid))


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
            COALESCE(SUM(total_autorizado), 0) AS suma_autorizado,
            COALESCE(SUM(total_cantidad), 0) AS suma_cantidad,
            (SELECT unidad_cantidad FROM requisiciones WHERE unidad_cantidad IS NOT NULL ORDER BY id DESC LIMIT 1) AS unidad_predominante
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

# Migración: total_cantidad y unidad_cantidad en requisiciones
try:
    execute_ddl("ALTER TABLE requisiciones ADD COLUMN total_cantidad DECIMAL(14,3) DEFAULT NULL COMMENT 'Total en unidades (m³, ton, etc)'")
except Exception:
    pass
try:
    execute_ddl("ALTER TABLE requisiciones ADD COLUMN unidad_cantidad VARCHAR(20) DEFAULT NULL COMMENT 'Unidad de las partidas'")
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

TIPOS_PEDIDO_OC = ["1 - Servicios", "3 - Materiales"]
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
    # Agregar columna estatus_pago si no existe
    try:
        execute_ddl("ALTER TABLE ordenes_compra ADD COLUMN estatus_pago ENUM('no_pagado','pagado') NOT NULL DEFAULT 'no_pagado'")
    except Exception:
        pass
    # Agregar columna email_contacto_pago si no existe (email del contacto interno, separado del email del proveedor)
    try:
        execute_ddl("ALTER TABLE ordenes_compra ADD COLUMN email_contacto_pago VARCHAR(120) DEFAULT NULL COMMENT 'Email del contacto de pagos (equipo interno)'")
    except Exception:
        pass
    # Migrar datos existentes: mover email_proveedor → email_contacto_pago donde email_contacto_pago esté vacío
    # (las OC antiguas guardaban el email del contacto interno en email_proveedor por error)
    try:
        execute("""
            UPDATE ordenes_compra
            SET email_contacto_pago = email_proveedor,
                email_proveedor     = NULL
            WHERE email_contacto_pago IS NULL
              AND email_proveedor IS NOT NULL
              AND email_proveedor NOT IN (SELECT email FROM proveedores WHERE email IS NOT NULL)
        """)
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

def get_email_del_proveedor(razon_social):
    """Devuelve el email del catálogo de proveedores por razón social exacta o parcial."""
    if not razon_social:
        return None
    razon_social = razon_social.strip()
    res = query("SELECT email FROM proveedores WHERE razon_social=%s AND activo=1 LIMIT 1",
                (razon_social,), one=True)
    if res and res.get("email") and res["email"].strip():
        return res["email"].strip()
    res = query("SELECT email FROM proveedores WHERE razon_social LIKE %s AND activo=1 LIMIT 1",
                (f"%{razon_social[:20]}%",), one=True)
    if res and res.get("email") and res["email"].strip():
        return res["email"].strip()
    return None


def crear_orden_compra(d):
    """Crea la cabecera de la orden. Devuelve el id insertado."""
    d = dict(d)
    d.setdefault("id_codigo_costo", None)
    d.setdefault("email_contacto_pago", None)
    return execute("""
        INSERT INTO ordenes_compra
            (numero_pedido, folio, fecha, tipo_pedido, id_obra, descripcion_obra,
             proveedor, rfc_proveedor, contacto_pago, telefono_proveedor, email_proveedor,
             email_contacto_pago,
             condiciones_pago, forma_pago, metodo_pago, uso_cfdi, moneda, tiempo_entrega,
             subtotal, iva, total, flete_logistica, retencion, importe_letra,
             responsable, estatus, observaciones, id_codigo_costo, creado_por)
        VALUES
            (%(numero_pedido)s, %(folio)s, %(fecha)s, %(tipo_pedido)s, %(id_obra)s,
             %(descripcion_obra)s, %(proveedor)s, %(rfc_proveedor)s, %(contacto_pago)s,
             %(telefono_proveedor)s, %(email_proveedor)s, %(email_contacto_pago)s,
             %(condiciones_pago)s,
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


def recalcular_totales_oc(id_orden, porcentaje_iva=16.0):
    """Recalcula subtotal, IVA y total a partir de las partidas.
    porcentaje_iva: 4, 10.6667 o 16 (por defecto 16)."""
    res = query("""SELECT COALESCE(SUM(importe),0) AS subtotal
                   FROM ordenes_compra_partidas WHERE id_orden=%s""", (id_orden,), one=True)
    sub = round(float(res["subtotal"]), 2)
    iva = round(sub * (float(porcentaje_iva) / 100.0), 2)
    total = round(sub + iva, 2)
    execute("UPDATE ordenes_compra SET subtotal=%s, iva=%s, total=%s WHERE id=%s",
            (sub, iva, total, id_orden))
    return sub, iva, total


def actualizar_orden_compra(oid, d):
    d = dict(d)
    d.setdefault("id_codigo_costo", None)
    d.setdefault("email_contacto_pago", None)
    execute("""
        UPDATE ordenes_compra SET
            fecha=%(fecha)s, tipo_pedido=%(tipo_pedido)s, id_obra=%(id_obra)s,
            descripcion_obra=%(descripcion_obra)s, proveedor=%(proveedor)s,
            rfc_proveedor=%(rfc_proveedor)s, contacto_pago=%(contacto_pago)s,
            telefono_proveedor=%(telefono_proveedor)s, email_proveedor=%(email_proveedor)s,
            email_contacto_pago=%(email_contacto_pago)s,
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


def update_estatus_pago_orden(oid, estatus_pago):
    """Actualiza el estatus de pago de una orden de compra ('no_pagado' o 'pagado')."""
    if estatus_pago not in ("no_pagado", "pagado"):
        raise ValueError("estatus_pago inválido")
    execute("UPDATE ordenes_compra SET estatus_pago=%s WHERE id=%s", (estatus_pago, oid))


def enviar_orden_compra(oid):
    execute("""UPDATE ordenes_compra SET estatus='enviado' WHERE id=%s AND estatus='borrador'""",
            (oid,))


def get_siguiente_numero_oc(id_obra=None, proveedor=None, tipo_pedido=None):
    """Devuelve el siguiente número de pedido consecutivo clasificado por tipo.
    El prefijo es el primer dígito numérico del tipo de pedido:
      '1 - Servicios'  → 10001, 10002 ...
      '3 - Materiales' → 30001, 30002 ...
    Si el tipo no empieza con dígito usa base 10000."""
    import re
    prefijo = 1
    if tipo_pedido:
        m = re.match(r'(\d+)', str(tipo_pedido).strip())
        if m:
            prefijo = int(m.group(1))
    base = prefijo * 10000          # 1→10000, 3→30000, ...
    tope = base + 9999              # límite del rango de ese tipo

    res = query(
        "SELECT MAX(numero_pedido) AS mx FROM ordenes_compra "
        "WHERE numero_pedido BETWEEN %s AND %s",
        (base, tope), one=True)
    ultimo = int(res["mx"]) if res and res["mx"] else base
    return ultimo + 1


def generar_folio_oc(tipo_pedido, numero):
    """Devuelve el número de pedido como string simple (ej. '10001')."""
    return str(int(numero))


# ── Conversión de importe a letras (español, pesos mexicanos) ─────

def numero_a_letras(monto):
    """Convierte un importe numérico a su representación en letras (MXN).
    Ej.: 15230.50  →  'QUINCE MIL DOSCIENTOS TREINTA PESOS 50/100 M.N.'"""
    if monto is None:
        return ""
    try:
        monto = float(monto)
    except (ValueError, TypeError):
        return ""

    centavos = round((monto - int(monto)) * 100)
    entero = int(monto)

    UNIDADES = [
        "", "UN", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE",
        "DIEZ", "ONCE", "DOCE", "TRECE", "CATORCE", "QUINCE", "DIECISÉIS",
        "DIECISIETE", "DIECIOCHO", "DIECINUEVE", "VEINTE", "VEINTIÚN", "VEINTIDÓS",
        "VEINTITRÉS", "VEINTICUATRO", "VEINTICINCO", "VEINTISÉIS", "VEINTISIETE",
        "VEINTIOCHO", "VEINTINUEVE",
    ]
    DECENAS = [
        "", "DIEZ", "VEINTE", "TREINTA", "CUARENTA", "CINCUENTA",
        "SESENTA", "SETENTA", "OCHENTA", "NOVENTA",
    ]
    CENTENAS = [
        "", "CIEN", "DOSCIENTOS", "TRESCIENTOS", "CUATROCIENTOS", "QUINIENTOS",
        "SEISCIENTOS", "SETECIENTOS", "OCHOCIENTOS", "NOVECIENTOS",
    ]

    def _cientos(n):
        if n == 0:
            return ""
        if n == 100:
            return "CIEN"
        c = n // 100
        resto = n % 100
        txt = CENTENAS[c] if c else ""
        if resto:
            if txt:
                txt += " "
            if resto < 30:
                txt += UNIDADES[resto]
            else:
                d = resto // 10
                u = resto % 10
                txt += DECENAS[d]
                if u:
                    txt += " Y " + UNIDADES[u]
        return txt

    def _miles(n):
        if n == 0:
            return "CERO"
        millones = n // 1_000_000
        miles = (n % 1_000_000) // 1_000
        cientos = n % 1_000
        partes = []
        if millones:
            texto_mill = _cientos(millones)
            partes.append(texto_mill + (" MILLÓN" if millones == 1 else " MILLONES"))
        if miles:
            texto_mil = _cientos(miles)
            partes.append(("UN MIL" if miles == 1 else texto_mil + " MIL"))
        if cientos:
            partes.append(_cientos(cientos))
        return " ".join(partes)

    letras = _miles(entero)
    return f"{letras} PESOS {centavos:02d}/100 M.N."


def get_kpis_oc(id_obra=None, fi=None, ff=None):
    sql = "SELECT COUNT(*) AS total, SUM(estatus='borrador') AS borradores, SUM(estatus='enviado') AS enviados, SUM(estatus='autorizado') AS autorizados, SUM(estatus='rechazado') AS rechazados, SUM(estatus='cancelado') AS cancelados, COALESCE(SUM(total),0) AS suma_total, COALESCE(SUM(CASE WHEN estatus='autorizado' THEN total ELSE 0 END),0) AS suma_autorizado FROM ordenes_compra WHERE 1=1"
    p = []
    if id_obra: sql += " AND id_obra=%s"; p.append(id_obra)
    if fi:      sql += " AND fecha>=%s"; p.append(fi)
    if ff:      sql += " AND fecha<=%s"; p.append(ff)
    return query(sql, p, one=True)


def get_proveedores_catalogo():
    """Devuelve id, razon_social, rfc y email de todos los proveedores activos
    para usarlos en el select del formulario de Orden de Compra."""
    return query("""
        SELECT id, razon_social, rfc, email, contacto, telefono, condiciones_pago_habitual
        FROM proveedores WHERE activo=1 ORDER BY razon_social
    """)


def get_email_proveedor_oc(id_orden):
    """Devuelve el email del proveedor para una OC.
    Orden de búsqueda:
    1. email_proveedor guardado directamente en la OC
    2. email del catálogo buscando por razon_social exacta
    3. email del catálogo buscando por coincidencia parcial (LIKE)
    """
    oc = query(
        "SELECT email_proveedor,  proveedor FROM ordenes_compra WHERE id=%s",
        (id_orden,), one=True)
    if not oc:
        return None

    # 1. Email guardado en la OC
    if oc.get("email_proveedor") and oc["email_proveedor"].strip():
        return oc["email_proveedor"].strip()

    # 2 y 3. Buscar en catálogo
    if oc.get("proveedor"):
        nombre = oc["proveedor"].strip()
        # Exacto
        res = query("SELECT email FROM proveedores WHERE razon_social=%s AND activo=1 LIMIT 1",
                    (nombre,), one=True)
        if res and res.get("email") and res["email"].strip():
            return res["email"].strip()
        # Parcial (el nombre guardado puede ser una versión corta)
        res = query("SELECT email FROM proveedores WHERE razon_social LIKE %s AND activo=1 LIMIT 1",
                    (f"%{nombre[:20]}%",), one=True)
        if res and res.get("email") and res["email"].strip():
            return res["email"].strip()
    return None


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
    "Equipos, materiales y bienes en general", "Renta de maquinaria",
    "Control de Calidad", "Otro",
]


def _init_tabla_proveedores():
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS proveedores (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            razon_social        VARCHAR(200) NOT NULL,
            tipo_persona        ENUM('fisica','moral') NOT NULL DEFAULT 'moral',
            rfc                 VARCHAR(15) DEFAULT NULL,
            tipo_proveedor      VARCHAR(60) DEFAULT NULL,
            tipo_producto_servicio VARCHAR(255) DEFAULT NULL COMMENT 'Descripcion del producto o servicio que ofrece',
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
    # Agregar columna estado_registro si no existe (pendiente/aprobado/rechazado)
    try:
        execute("ALTER TABLE proveedores ADD COLUMN estado_registro VARCHAR(20) DEFAULT 'aprobado'")
    except Exception:
        pass  # Ya existe
    # Agregar columna actualizado_en si no existe
    try:
        execute("ALTER TABLE proveedores ADD COLUMN actualizado_en TIMESTAMP NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP")
    except Exception:
        pass  # Ya existe
    # Agregar columnas de plazo para subir soporte de Control de Calidad
    try:
        execute("ALTER TABLE proveedores ADD COLUMN plazo_cc_desde DATE DEFAULT NULL")
    except Exception:
        pass  # Ya existe
    try:
        execute("ALTER TABLE proveedores ADD COLUMN plazo_cc_hasta DATE DEFAULT NULL")
    except Exception:
        pass  # Ya existe
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

def get_proveedores(search=None, tipo=None, activo=1, estado_registro=None):
    sql = "SELECT * FROM proveedores WHERE 1=1"
    p = []
    if activo is not None:
        if activo == 1:
            # "Activos" muestra activo(1) + inactivo(2), excluye baja(0)
            sql += " AND activo > 0"
        else:
            sql += " AND activo=%s"; p.append(activo)
    if estado_registro:
        sql += " AND estado_registro=%s"; p.append(estado_registro)
    else:
        # Por defecto excluir pendientes de la vista normal
        sql += " AND (estado_registro IS NULL OR estado_registro != 'pendiente')"
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
            (razon_social, tipo_persona, rfc, tipo_proveedor, tipo_producto_servicio,
             direccion, ciudad, estado, cp,
             pais, telefono, email, contacto, banco, cuenta_clabe,
             condiciones_pago_habitual, observaciones, plazo_cc_desde, plazo_cc_hasta, creado_por)
        VALUES
            (%(razon_social)s, %(tipo_persona)s, %(rfc)s, %(tipo_proveedor)s,
             %(tipo_producto_servicio)s, %(direccion)s,
             %(ciudad)s, %(estado)s, %(cp)s, %(pais)s, %(telefono)s, %(email)s, %(contacto)s,
             %(banco)s, %(cuenta_clabe)s, %(condiciones_pago_habitual)s, %(observaciones)s,
             %(plazo_cc_desde)s, %(plazo_cc_hasta)s, %(creado_por)s)
    """, d)


def crear_proveedor_publico(d):
    """Crea un proveedor desde el registro público con estado_registro='pendiente'."""
    return execute("""
        INSERT INTO proveedores
            (razon_social, tipo_persona, rfc, tipo_proveedor, tipo_producto_servicio,
             direccion, ciudad, estado, cp,
             pais, telefono, email, contacto, banco, cuenta_clabe,
             condiciones_pago_habitual, observaciones, creado_por, estado_registro)
        VALUES
            (%(razon_social)s, %(tipo_persona)s, %(rfc)s, %(tipo_proveedor)s,
             %(tipo_producto_servicio)s, %(direccion)s,
             %(ciudad)s, %(estado)s, %(cp)s, %(pais)s, %(telefono)s, %(email)s, %(contacto)s,
             %(banco)s, %(cuenta_clabe)s, %(condiciones_pago_habitual)s, %(observaciones)s,
             %(creado_por)s, %(estado_registro)s)
    """, d)


def actualizar_proveedor(pid, d):
    d = dict(d, id=pid)
    # Si no se pasan los campos de plazo CC, mantener los valores existentes
    if "plazo_cc_desde" not in d:
        d.setdefault("plazo_cc_desde", None)
        d.setdefault("plazo_cc_hasta", None)
    try:
        execute("""
            UPDATE proveedores SET
                razon_social=%(razon_social)s, tipo_persona=%(tipo_persona)s, rfc=%(rfc)s,
                tipo_proveedor=%(tipo_proveedor)s, tipo_producto_servicio=%(tipo_producto_servicio)s,
                direccion=%(direccion)s, ciudad=%(ciudad)s,
                estado=%(estado)s, cp=%(cp)s, pais=%(pais)s, telefono=%(telefono)s,
                email=%(email)s, contacto=%(contacto)s, banco=%(banco)s,
                cuenta_clabe=%(cuenta_clabe)s, condiciones_pago_habitual=%(condiciones_pago_habitual)s,
                observaciones=%(observaciones)s,
                plazo_cc_desde=%(plazo_cc_desde)s, plazo_cc_hasta=%(plazo_cc_hasta)s,
                actualizado_en=NOW()
            WHERE id=%(id)s
        """, d)
    except Exception:
        # Fallback: si las columnas plazo_cc no existen aún, actualizar sin ellas
        execute("""
            UPDATE proveedores SET
                razon_social=%(razon_social)s, tipo_persona=%(tipo_persona)s, rfc=%(rfc)s,
                tipo_proveedor=%(tipo_proveedor)s, tipo_producto_servicio=%(tipo_producto_servicio)s,
                direccion=%(direccion)s, ciudad=%(ciudad)s,
                estado=%(estado)s, cp=%(cp)s, pais=%(pais)s, telefono=%(telefono)s,
                email=%(email)s, contacto=%(contacto)s, banco=%(banco)s,
                cuenta_clabe=%(cuenta_clabe)s, condiciones_pago_habitual=%(condiciones_pago_habitual)s,
                observaciones=%(observaciones)s,
                actualizado_en=NOW()
            WHERE id=%(id)s
        """, d)


def actualizar_plazo_cc_proveedor(pid, plazo_desde, plazo_hasta):
    """Actualiza SOLO el plazo de Control de Calidad de un proveedor.
    Función independiente que no depende del UPDATE principal."""
    try:
        execute("""
            UPDATE proveedores SET plazo_cc_desde=%s, plazo_cc_hasta=%s WHERE id=%s
        """, (plazo_desde, plazo_hasta, pid))
    except Exception:
        pass  # Columnas aún no existen — se crearán en el próximo reinicio


def cambiar_estado_proveedor(pid, activo):
    execute("UPDATE proveedores SET activo=%s WHERE id=%s", (activo, pid))


def aprobar_proveedor(pid):
    """Aprueba un proveedor pendiente."""
    execute("UPDATE proveedores SET estado_registro='aprobado' WHERE id=%s", (pid,))


def rechazar_proveedor(pid):
    """Rechaza un proveedor pendiente (solo marca, no elimina)."""
    execute("UPDATE proveedores SET estado_registro='rechazado', activo=0 WHERE id=%s", (pid,))


def rechazar_proveedor_completo(pid):
    """Rechaza y ELIMINA completamente un proveedor: documentos, obras, evaluaciones, órdenes CC y el registro."""
    # Eliminar órdenes de servicio CC
    execute("DELETE FROM control_calidad WHERE id_proveedor=%s", (pid,))
    # Eliminar documentos
    execute("DELETE FROM proveedor_documentos WHERE id_proveedor=%s", (pid,))
    # Eliminar asignaciones de obra
    execute("DELETE FROM proveedor_obras WHERE id_proveedor=%s", (pid,))
    # Eliminar evaluaciones
    execute("DELETE FROM proveedor_evaluaciones WHERE id_proveedor=%s", (pid,))
    # Eliminar el proveedor
    execute("DELETE FROM proveedores WHERE id=%s", (pid,))


def get_proveedores_pendientes():
    """Obtiene proveedores con registro pendiente de aprobación."""
    return query("SELECT * FROM proveedores WHERE estado_registro='pendiente' ORDER BY creado_en DESC")


# ── DOCUMENTOS DE PROVEEDORES ────────────────────────────────────
def _crear_tabla_proveedor_documentos():
    """Crea la tabla si no existe."""
    execute("""
        CREATE TABLE IF NOT EXISTS proveedor_documentos (
            id INT AUTO_INCREMENT PRIMARY KEY,
            id_proveedor INT NOT NULL,
            nombre_archivo VARCHAR(255) NOT NULL,
            nombre_original VARCHAR(255) NOT NULL,
            tipo_archivo VARCHAR(50),
            subido_por INT,
            creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX(id_proveedor)
        )
    """)

# Ejecutar al importar
try:
    _crear_tabla_proveedor_documentos()
except Exception:
    pass


# ── PROVEEDOR ↔ OBRAS (relación muchos-a-muchos) ────────────────
def _crear_tabla_proveedor_obras():
    """Crea la tabla de relación proveedor-obras si no existe."""
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS proveedor_obras (
            id INT AUTO_INCREMENT PRIMARY KEY,
            id_proveedor INT NOT NULL,
            id_obra INT NOT NULL,
            creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uk_prov_obra (id_proveedor, id_obra),
            INDEX idx_prov (id_proveedor),
            INDEX idx_obra (id_obra)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

try:
    _crear_tabla_proveedor_obras()
except Exception:
    pass

# Ejecutar init de proveedores para crear columnas plazo_cc si no existen
try:
    _init_tabla_proveedores()
except Exception:
    pass

# Migración: agregar columna actualizado_en a proveedores
try:
    execute("ALTER TABLE proveedores ADD COLUMN actualizado_en TIMESTAMP NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP")
except Exception:
    pass

# Migración: agregar columna estado_pago a proveedor_documentos
try:
    execute("ALTER TABLE proveedor_documentos ADD COLUMN estado_pago VARCHAR(20) DEFAULT 'no_pagado'")
except Exception:
    pass

# Migración: agregar columna nombre_empleado_pago a caja_chica_comprobaciones
try:
    execute("ALTER TABLE caja_chica_comprobaciones ADD COLUMN nombre_empleado_pago VARCHAR(200) DEFAULT NULL")
except Exception:
    pass


# ══════════════════════════════════════════════════════════════════
#  PRESUPUESTO POR OBRA — TOPE DE VOLUMEN POR CONCEPTO
#  Controla que las requisiciones no excedan la proyección
#  de volumen (m³, m², ton, etc.) por código de costo por obra.
# ══════════════════════════════════════════════════════════════════

def _crear_tabla_presupuesto_obra():
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS presupuesto_obra_concepto (
            id INT AUTO_INCREMENT PRIMARY KEY,
            id_obra INT NOT NULL,
            id_codigo_costo INT NOT NULL COMMENT 'Obligatorio: liga al catálogo de códigos de costo',
            concepto VARCHAR(300) NOT NULL,
            unidad VARCHAR(20) NOT NULL DEFAULT 'm³' COMMENT 'm³, m², ton, pza, lt, etc',
            cantidad_presupuestada DECIMAL(14,3) NOT NULL DEFAULT 0 COMMENT 'Tope máximo en unidades',
            precio_unitario DECIMAL(12,2) DEFAULT 0,
            importe_presupuestado DECIMAL(14,2) DEFAULT 0 COMMENT 'Referencia: cantidad * PU',
            activo TINYINT(1) NOT NULL DEFAULT 1,
            creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_obra (id_obra),
            INDEX idx_codigo (id_codigo_costo)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

try:
    _crear_tabla_presupuesto_obra()
except Exception:
    pass

# Migración: eliminar UNIQUE KEY si existe (permitir conceptos repetidos en misma obra+código)
for _idx in ("uk_obra_codigo_concepto", "uk_obra_codigo"):
    try:
        execute_ddl(f"ALTER TABLE presupuesto_obra_concepto DROP INDEX {_idx}")
    except Exception:
        pass

# Migración: hacer id_codigo_costo NOT NULL (si aún es nullable)
try:
    execute_ddl("ALTER TABLE presupuesto_obra_concepto MODIFY COLUMN id_codigo_costo INT NOT NULL COMMENT 'Obligatorio: liga al catálogo de códigos de costo'")
except Exception:
    pass

# Migración: agregar cantidad y unidad a requisicion_partidas
try:
    execute("ALTER TABLE requisicion_partidas ADD COLUMN cantidad DECIMAL(14,3) DEFAULT NULL COMMENT 'Cantidad solicitada en unidades'")
except Exception:
    pass
try:
    execute("ALTER TABLE requisicion_partidas ADD COLUMN unidad VARCHAR(20) DEFAULT NULL COMMENT 'm³, m², ton, etc'")
except Exception:
    pass

# Migración: agregar flag excede_presupuesto a requisicion_partidas
try:
    execute_ddl("ALTER TABLE requisicion_partidas ADD COLUMN excede_presupuesto TINYINT(1) NOT NULL DEFAULT 0 COMMENT '1=excede tope de volumen'")
except Exception:
    pass

# Migración: columnas de pago y arrastre en requisicion_partidas
for _col, _ddl in [
    ("estatus_pago",     "ALTER TABLE requisicion_partidas ADD COLUMN estatus_pago VARCHAR(20) NOT NULL DEFAULT 'pendiente' COMMENT 'pendiente|pagado|cancelado'"),
    ("fecha_pago",       "ALTER TABLE requisicion_partidas ADD COLUMN fecha_pago DATE DEFAULT NULL"),
    ("no_factura",       "ALTER TABLE requisicion_partidas ADD COLUMN no_factura VARCHAR(100) DEFAULT NULL"),
    ("factura_nombre",   "ALTER TABLE requisicion_partidas ADD COLUMN factura_nombre VARCHAR(255) DEFAULT NULL COMMENT 'nombre original del archivo'"),
    ("factura_archivo",  "ALTER TABLE requisicion_partidas ADD COLUMN factura_archivo VARCHAR(255) DEFAULT NULL COMMENT 'nombre en disco'"),
    ("id_partida_origen","ALTER TABLE requisicion_partidas ADD COLUMN id_partida_origen INT DEFAULT NULL COMMENT 'si es arrastre, id de la partida original'"),
    ("semana_origen",    "ALTER TABLE requisicion_partidas ADD COLUMN semana_origen VARCHAR(20) DEFAULT NULL COMMENT 'semana de la partida original p/arrastre'"),
]:
    try:
        execute_ddl(_ddl)
    except Exception:
        pass  # columna ya existe

# Migración: crear tabla alertas_presupuesto para notificaciones
try:
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS alertas_presupuesto (
            id INT AUTO_INCREMENT PRIMARY KEY,
            id_obra INT NOT NULL,
            id_codigo_costo INT NOT NULL,
            concepto VARCHAR(300) DEFAULT NULL,
            id_requisicion INT DEFAULT NULL,
            id_partida INT DEFAULT NULL,
            cantidad_solicitada DECIMAL(14,3) DEFAULT NULL,
            cantidad_disponible DECIMAL(14,3) DEFAULT NULL,
            cantidad_presupuestada DECIMAL(14,3) DEFAULT NULL,
            cantidad_acumulada DECIMAL(14,3) DEFAULT NULL,
            unidad VARCHAR(20) DEFAULT NULL,
            leida TINYINT(1) NOT NULL DEFAULT 0,
            creada_por INT DEFAULT NULL,
            creada_en DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_obra (id_obra),
            INDEX idx_leida (leida)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Alertas cuando una requisición excede el tope presupuestado'
    """)
except Exception:
    pass


# ── CRUD Presupuesto Obra ────────────────────────────────────────

def get_presupuesto_obra(id_obra):
    """Obtiene todos los conceptos presupuestados de una obra."""
    return query("""
        SELECT poc.*, cc.codigo AS codigo_costo_codigo, cc.descripcion AS codigo_costo_desc
        FROM presupuesto_obra_concepto poc
        LEFT JOIN codigos_costo cc ON cc.id = poc.id_codigo_costo
        WHERE poc.id_obra = %s AND poc.activo = 1
        ORDER BY poc.concepto
    """, (id_obra,))


def get_presupuesto_concepto(concepto_id):
    return query("SELECT * FROM presupuesto_obra_concepto WHERE id=%s", (concepto_id,), one=True)


def crear_presupuesto_concepto(d):
    return execute("""
        INSERT INTO presupuesto_obra_concepto
            (id_obra, id_codigo_costo, concepto, unidad, cantidad_presupuestada, precio_unitario, importe_presupuestado)
        VALUES (%(id_obra)s, %(id_codigo_costo)s, %(concepto)s, %(unidad)s,
                %(cantidad_presupuestada)s, %(precio_unitario)s, %(importe_presupuestado)s)
    """, d)


def actualizar_presupuesto_concepto(cid, d):
    d = dict(d, id=cid)
    execute("""
        UPDATE presupuesto_obra_concepto SET
            concepto=%(concepto)s, unidad=%(unidad)s, cantidad_presupuestada=%(cantidad_presupuestada)s,
            precio_unitario=%(precio_unitario)s, importe_presupuestado=%(importe_presupuestado)s,
            id_codigo_costo=%(id_codigo_costo)s
        WHERE id=%(id)s
    """, d)


def eliminar_presupuesto_concepto(cid):
    execute("UPDATE presupuesto_obra_concepto SET activo=0 WHERE id=%s", (cid,))


def get_cantidad_requisitada_acumulada(id_obra, id_codigo_costo):
    """Calcula cuánto se ha requisitado (en unidades) para un código de costo en una obra.
    Solo cuenta requisiciones que NO están rechazadas."""
    r = query("""
        SELECT COALESCE(SUM(rp.cantidad), 0) AS total_requisitado
        FROM requisicion_partidas rp
        JOIN requisiciones req ON req.id = rp.id_requisicion
        WHERE req.id_obra = %s
          AND rp.id_codigo_costo = %s
          AND req.estatus != 'rechazado'
          AND rp.cantidad IS NOT NULL
    """, (id_obra, id_codigo_costo), one=True)
    return float(r["total_requisitado"]) if r else 0


def get_cantidad_requisitada_por_concepto(id_obra, id_codigo_costo, concepto):
    """Calcula cuánto se ha requisitado para un concepto específico (obra + código + concepto).
    Solo cuenta requisiciones que NO están rechazadas.
    Busca por coincidencia parcial en el concepto de la partida."""
    if not concepto:
        return get_cantidad_requisitada_acumulada(id_obra, id_codigo_costo)
    r = query("""
        SELECT COALESCE(SUM(rp.cantidad), 0) AS total_requisitado
        FROM requisicion_partidas rp
        JOIN requisiciones req ON req.id = rp.id_requisicion
        WHERE req.id_obra = %s
          AND rp.id_codigo_costo = %s
          AND req.estatus != 'rechazado'
          AND rp.cantidad IS NOT NULL
    """, (id_obra, id_codigo_costo), one=True)
    return float(r["total_requisitado"]) if r else 0


def validar_tope_presupuesto(id_obra, id_codigo_costo, cantidad_nueva):
    """Valida si una nueva cantidad excede el presupuesto para un código de costo en una obra.
    Suma TODOS los topes definidos para ese código en esa obra (puede haber varios conceptos).
    Retorna dict: {permitido: bool, excede: bool, mensaje: str, disponible: float, presupuestado: float, acumulado: float}"""
    if not id_obra or not id_codigo_costo:
        return {"permitido": True, "excede": False, "mensaje": ""}
    if cantidad_nueva is None:
        cantidad_nueva = 0

    # Buscar TODOS los topes para este código en esta obra (puede haber varios conceptos)
    topes = query("""
        SELECT * FROM presupuesto_obra_concepto
        WHERE id_obra=%s AND id_codigo_costo=%s AND activo=1
    """, (id_obra, id_codigo_costo))

    if not topes:
        return {"permitido": True, "excede": False, "mensaje": "Sin tope definido para este código de costo."}

    # Sumar toda la cantidad presupuestada para este código en esta obra
    presupuestado = sum(float(t["cantidad_presupuestada"]) for t in topes)
    unidad = topes[0]["unidad"]
    conceptos_str = ", ".join(t["concepto"] for t in topes)
    precio_unitario = float(topes[0]["precio_unitario"]) if topes[0].get("precio_unitario") else 0

    acumulado = get_cantidad_requisitada_acumulada(id_obra, id_codigo_costo)
    disponible = presupuestado - acumulado
    nueva = float(cantidad_nueva)

    if nueva > disponible:
        return {
            "permitido": True,  # Opción A: se permite guardar pero se alerta
            "excede": True,
            "mensaje": f"⚠️ EXCEDE PROYECCIÓN: Se solicitan {nueva:.3f} {unidad} pero solo quedan {disponible:.3f} {unidad} disponibles. "
                       f"(Presupuestado: {presupuestado:.3f}, Ya requisitado: {acumulado:.3f}). "
                       f"Conceptos afectados: {conceptos_str}",
            "disponible": disponible,
            "presupuestado": presupuestado,
            "acumulado": acumulado,
            "unidad": unidad,
            "conceptos": conceptos_str,
            "precio_unitario": precio_unitario,
        }

    return {
        "permitido": True,
        "excede": False,
        "mensaje": f"OK: {disponible - nueva:.3f} {unidad} restantes después de esta requisición.",
        "disponible": disponible,
        "presupuestado": presupuestado,
        "acumulado": acumulado,
        "unidad": unidad,
        "precio_unitario": precio_unitario,
    }


def crear_alerta_presupuesto(id_obra, id_codigo_costo, concepto, id_requisicion,
                              id_partida, cantidad_solicitada, cantidad_disponible,
                              cantidad_presupuestada, cantidad_acumulada, unidad, creada_por):
    """Registra una alerta cuando una requisición excede el tope presupuestado."""
    return execute("""
        INSERT INTO alertas_presupuesto
            (id_obra, id_codigo_costo, concepto, id_requisicion, id_partida,
             cantidad_solicitada, cantidad_disponible, cantidad_presupuestada,
             cantidad_acumulada, unidad, creada_por)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (id_obra, id_codigo_costo, concepto, id_requisicion, id_partida,
          cantidad_solicitada, cantidad_disponible, cantidad_presupuestada,
          cantidad_acumulada, unidad, creada_por))


def get_alertas_presupuesto(solo_no_leidas=False, id_obra=None, limit=50):
    """Obtiene alertas de presupuesto para el dashboard/notificaciones."""
    sql = """
        SELECT ap.*, ob.nombre AS obra_nombre, cc.codigo AS codigo_costo_codigo,
               cc.descripcion AS codigo_costo_desc, req.semana, u.nombre AS creada_por_nombre
        FROM alertas_presupuesto ap
        LEFT JOIN obras ob ON ob.id = ap.id_obra
        LEFT JOIN codigos_costo cc ON cc.id = ap.id_codigo_costo
        LEFT JOIN requisiciones req ON req.id = ap.id_requisicion
        LEFT JOIN usuarios u ON u.id = ap.creada_por
        WHERE 1=1
    """
    params = []
    if solo_no_leidas:
        sql += " AND ap.leida = 0"
    if id_obra:
        sql += " AND ap.id_obra = %s"
        params.append(id_obra)
    sql += " ORDER BY ap.creada_en DESC LIMIT %s"
    params.append(limit)
    return query(sql, params)


def contar_alertas_presupuesto_no_leidas():
    """Cuenta alertas no leídas para mostrar badge en el menú."""
    r = query("SELECT COUNT(*) AS total FROM alertas_presupuesto WHERE leida=0", one=True)
    return int(r["total"]) if r else 0


def marcar_alertas_leidas(ids=None):
    """Marca alertas como leídas. Si ids es None, marca todas."""
    if ids:
        placeholders = ",".join(["%s"] * len(ids))
        execute(f"UPDATE alertas_presupuesto SET leida=1 WHERE id IN ({placeholders})", ids)
    else:
        execute("UPDATE alertas_presupuesto SET leida=1 WHERE leida=0")


def importar_presupuesto_obra_excel(wb, id_obra):
    """Importa presupuesto desde un workbook de openpyxl.
    Espera columnas: concepto, unidad, cantidad, precio_unitario (opcionalmente codigo_costo)."""
    ws = wb.active
    creados = 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not row[0]:
            continue
        concepto = str(row[0]).strip()
        unidad = str(row[1]).strip() if len(row) > 1 and row[1] else "m³"
        cantidad = float(row[2]) if len(row) > 2 and row[2] else 0
        pu = float(row[3]) if len(row) > 3 and row[3] else 0
        codigo_str = str(row[4]).strip() if len(row) > 4 and row[4] else None

        # Buscar código de costo si se proporcionó
        id_codigo = None
        if codigo_str:
            cc = query("SELECT id FROM codigos_costo WHERE codigo=%s", (codigo_str,), one=True)
            if cc:
                id_codigo = cc["id"]

        datos = {
            "id_obra": id_obra,
            "id_codigo_costo": id_codigo,
            "concepto": concepto,
            "unidad": unidad,
            "cantidad_presupuestada": cantidad,
            "precio_unitario": pu,
            "importe_presupuestado": round(cantidad * pu, 2),
        }
        try:
            crear_presupuesto_concepto(datos)
            creados += 1
        except Exception:
            # Si ya existe (UNIQUE), actualizar
            if id_codigo:
                existing = query("SELECT id FROM presupuesto_obra_concepto WHERE id_obra=%s AND id_codigo_costo=%s",
                                 (id_obra, id_codigo), one=True)
                if existing:
                    actualizar_presupuesto_concepto(existing["id"], datos)
                    creados += 1
    return creados


# ══════════════════════════════════════════════════════════════════
#  ÓRDENES DE SERVICIO — CONTROL DE CALIDAD
#  Flujo: COTIZADO → AUTORIZADO → PAGADO → FACTURADO → COMPLETO
# ══════════════════════════════════════════════════════════════════

ESTADOS_ORDEN_CC = ["cotizado", "autorizado", "pagado", "facturado", "completo"]

def _crear_tabla_ordenes_cc():
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS control_calidad (
            id INT AUTO_INCREMENT PRIMARY KEY,
            id_proveedor INT NOT NULL,
            id_obra INT NOT NULL,
            descripcion_servicio TEXT NOT NULL,
            monto_cotizado DECIMAL(12,2) DEFAULT NULL,
            moneda VARCHAR(5) DEFAULT 'MXN',
            estado VARCHAR(20) NOT NULL DEFAULT 'cotizado',
            archivo_cotizacion VARCHAR(255) DEFAULT NULL,
            nombre_cotizacion VARCHAR(255) DEFAULT NULL,
            archivo_factura VARCHAR(255) DEFAULT NULL,
            nombre_factura VARCHAR(255) DEFAULT NULL,
            archivo_resultados VARCHAR(255) DEFAULT NULL,
            nombre_resultados VARCHAR(255) DEFAULT NULL,
            fecha_cotizacion DATETIME DEFAULT CURRENT_TIMESTAMP,
            fecha_autorizacion DATETIME DEFAULT NULL,
            fecha_pago DATETIME DEFAULT NULL,
            fecha_factura DATETIME DEFAULT NULL,
            fecha_resultados DATETIME DEFAULT NULL,
            autorizado_por INT DEFAULT NULL,
            pagado_por INT DEFAULT NULL,
            observaciones TEXT DEFAULT NULL,
            creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_prov (id_proveedor),
            INDEX idx_obra (id_obra),
            INDEX idx_estado (estado)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

try:
    _crear_tabla_ordenes_cc()
except Exception:
    pass

# Migración: agregar columna monto_autorizado a control_calidad
try:
    execute("ALTER TABLE control_calidad ADD COLUMN monto_autorizado DECIMAL(12,2) DEFAULT NULL AFTER monto_cotizado")
except Exception:
    pass

# Migración: agregar columnas periodo_desde y periodo_hasta a control_calidad
try:
    execute("ALTER TABLE control_calidad ADD COLUMN periodo_desde DATE DEFAULT NULL AFTER observaciones")
except Exception:
    pass
try:
    execute("ALTER TABLE control_calidad ADD COLUMN periodo_hasta DATE DEFAULT NULL AFTER periodo_desde")
except Exception:
    pass

# Migración: agregar columnas archivo_cfdi y nombre_cfdi para CFDI separado
try:
    execute("ALTER TABLE control_calidad ADD COLUMN archivo_cfdi VARCHAR(500) DEFAULT NULL AFTER nombre_cotizacion")
except Exception:
    pass
try:
    execute("ALTER TABLE control_calidad ADD COLUMN nombre_cfdi VARCHAR(500) DEFAULT NULL AFTER archivo_cfdi")
except Exception:
    pass


def crear_orden_cc(datos):
    """Crea una nueva orden de servicio CC (estado inicial: cotizado)."""
    return execute("""
        INSERT INTO control_calidad
            (id_proveedor, id_obra, descripcion_servicio, monto_cotizado, moneda,
             archivo_cotizacion, nombre_cotizacion, archivo_cfdi, nombre_cfdi,
             observaciones, periodo_desde, periodo_hasta)
        VALUES
            (%(id_proveedor)s, %(id_obra)s, %(descripcion_servicio)s, %(monto_cotizado)s,
             %(moneda)s, %(archivo_cotizacion)s, %(nombre_cotizacion)s, %(archivo_cfdi)s, %(nombre_cfdi)s,
             %(observaciones)s, %(periodo_desde)s, %(periodo_hasta)s)
    """, datos)


def get_ordenes_cc(id_proveedor=None, id_obra=None, estado=None):
    """Lista órdenes de servicio CC con filtros opcionales."""
    sql = """
        SELECT occ.*, p.razon_social AS proveedor_nombre, p.rfc AS proveedor_rfc,
               ob.nombre AS obra_nombre, ob.ubicacion AS obra_ubicacion,
               u_auth.nombre AS autorizado_por_nombre,
               u_pag.nombre AS pagado_por_nombre
        FROM control_calidad occ
        JOIN proveedores p ON p.id = occ.id_proveedor
        JOIN obras ob ON ob.id = occ.id_obra
        LEFT JOIN usuarios u_auth ON u_auth.id = occ.autorizado_por
        LEFT JOIN usuarios u_pag ON u_pag.id = occ.pagado_por
        WHERE 1=1
    """
    params = []
    if id_proveedor:
        sql += " AND occ.id_proveedor = %s"
        params.append(id_proveedor)
    if id_obra:
        sql += " AND occ.id_obra = %s"
        params.append(id_obra)
    if estado:
        sql += " AND occ.estado = %s"
        params.append(estado)
    sql += " ORDER BY occ.creado_en DESC"
    return query(sql, params)


def get_orden_cc(orden_id):
    """Obtiene una orden CC por ID."""
    return query("""
        SELECT occ.*, p.razon_social AS proveedor_nombre, p.rfc AS proveedor_rfc,
               ob.nombre AS obra_nombre, ob.ubicacion AS obra_ubicacion
        FROM control_calidad occ
        JOIN proveedores p ON p.id = occ.id_proveedor
        JOIN obras ob ON ob.id = occ.id_obra
        WHERE occ.id = %s
    """, (orden_id,), one=True)


def autorizar_orden_cc(orden_id, usuario_id, monto_autorizado=None):
    """Marca una orden como autorizada con monto (puede diferir del cotizado)."""
    if monto_autorizado is not None:
        execute("""
            UPDATE control_calidad
            SET estado='autorizado', fecha_autorizacion=NOW(), autorizado_por=%s, monto_autorizado=%s
            WHERE id=%s AND estado='cotizado'
        """, (usuario_id, monto_autorizado, orden_id))
    else:
        execute("""
            UPDATE control_calidad
            SET estado='autorizado', fecha_autorizacion=NOW(), autorizado_por=%s
            WHERE id=%s AND estado='cotizado'
        """, (usuario_id, orden_id))


def rechazar_orden_cc(orden_id, usuario_id):
    """Rechaza una orden de servicio CC."""
    execute("""
        UPDATE control_calidad
        SET estado='rechazado', autorizado_por=%s, fecha_autorizacion=NOW()
        WHERE id=%s AND estado='cotizado'
    """, (usuario_id, orden_id))


def revertir_orden_cc(orden_id):
    """Revierte una orden autorizada o rechazada de vuelta a cotizado."""
    execute("""
        UPDATE control_calidad
        SET estado='cotizado', fecha_autorizacion=NULL, autorizado_por=NULL, monto_autorizado=NULL
        WHERE id=%s AND estado IN ('autorizado', 'rechazado')
    """, (orden_id,))


def pagar_orden_cc(orden_id, usuario_id):
    """Marca una orden como pagada."""
    execute("""
        UPDATE control_calidad
        SET estado='pagado', fecha_pago=NOW(), pagado_por=%s
        WHERE id=%s AND estado='autorizado'
    """, (usuario_id, orden_id))


def subir_factura_orden_cc(orden_id, archivo, nombre):
    """Sube factura del proveedor y cambia estado a facturado."""
    execute("""
        UPDATE control_calidad
        SET estado='facturado', archivo_factura=%s, nombre_factura=%s, fecha_factura=NOW()
        WHERE id=%s AND estado='pagado'
    """, (archivo, nombre, orden_id))


def subir_resultados_orden_cc(orden_id, archivo, nombre):
    """Sube resultados de laboratorio y cambia estado a completo."""
    execute("""
        UPDATE control_calidad
        SET estado='completo', archivo_resultados=%s, nombre_resultados=%s, fecha_resultados=NOW()
        WHERE id=%s AND estado='facturado'
    """, (archivo, nombre, orden_id))


def get_ordenes_pendientes_factura(id_proveedor=None):
    """Obtiene órdenes que están pagadas pero sin factura."""
    sql = """
        SELECT occ.*, p.razon_social AS proveedor_nombre, ob.nombre AS obra_nombre
        FROM control_calidad occ
        JOIN proveedores p ON p.id = occ.id_proveedor
        JOIN obras ob ON ob.id = occ.id_obra
        WHERE occ.estado = 'pagado'
    """
    params = []
    if id_proveedor:
        sql += " AND occ.id_proveedor = %s"
        params.append(id_proveedor)
    sql += " ORDER BY occ.fecha_pago ASC"
    return query(sql, params)


def contar_pendientes_nav_proveedores():
    """Cuenta pendientes para el badge del menú Proveedores.
    - prov: proveedores registrados (público) pendientes de aprobación.
    - cc:   órdenes de Control de Calidad en estado 'cotizado' (esperan autorización).
    """
    r1 = query("SELECT COUNT(*) AS n FROM proveedores WHERE estado_registro='pendiente'", one=True)
    r2 = query("SELECT COUNT(*) AS n FROM control_calidad WHERE estado='cotizado'", one=True)
    prov = int(r1["n"]) if r1 else 0
    cc = int(r2["n"]) if r2 else 0
    return {"prov": prov, "cc": cc, "total": prov + cc}


def contar_facturas_pendientes_proveedor(id_proveedor):
    """Cuenta cuántas órdenes tiene un proveedor en estado 'pagado' (sin factura)."""
    r = query("SELECT COUNT(*) AS n FROM control_calidad WHERE id_proveedor=%s AND estado='pagado'",
              (id_proveedor,), one=True)
    return r["n"] if r else 0


def get_ordenes_cc_proveedor_por_obra(id_proveedor):
    """Obtiene las órdenes agrupadas por obra para un proveedor."""
    return query("""
        SELECT occ.*, ob.nombre AS obra_nombre, ob.ubicacion AS obra_ubicacion
        FROM control_calidad occ
        JOIN obras ob ON ob.id = occ.id_obra
        WHERE occ.id_proveedor = %s
        ORDER BY ob.nombre, occ.creado_en DESC
    """, (id_proveedor,))


def asignar_obras_proveedor(id_proveedor, lista_ids_obra):
    """Asigna una lista de obras a un proveedor (reemplaza las anteriores)."""
    execute("DELETE FROM proveedor_obras WHERE id_proveedor=%s", (id_proveedor,))
    for id_obra in lista_ids_obra:
        if id_obra:
            try:
                execute("INSERT INTO proveedor_obras (id_proveedor, id_obra) VALUES (%s, %s)",
                        (id_proveedor, int(id_obra)))
            except Exception:
                pass  # Duplicado u otro error


def get_obras_proveedor(id_proveedor):
    """Obtiene las obras asignadas a un proveedor."""
    return query("""
        SELECT o.id, o.nombre, o.ubicacion, o.estado AS estado_obra
        FROM proveedor_obras po
        JOIN obras o ON o.id = po.id_obra
        WHERE po.id_proveedor = %s
        ORDER BY o.nombre
    """, (id_proveedor,))


def get_proveedores_control_calidad():
    """Obtiene proveedores de tipo Control de Calidad que están aprobados/activos."""
    return query("""
        SELECT p.*, GROUP_CONCAT(o.nombre SEPARATOR ', ') AS obras_asignadas
        FROM proveedores p
        LEFT JOIN proveedor_obras po ON po.id_proveedor = p.id
        LEFT JOIN obras o ON o.id = po.id_obra
        WHERE p.tipo_proveedor = 'Control de Calidad'
          AND p.activo > 0
          AND (p.estado_registro IS NULL OR p.estado_registro != 'pendiente')
        GROUP BY p.id
        ORDER BY p.razon_social
    """)


def get_proveedores_control_calidad_todos():
    """Obtiene TODOS los proveedores activos (cualquier tipo) para vista informativa en registro CC.
    Solo incluye proveedores aprobados (no pendientes ni rechazados)."""
    return query("""
        SELECT p.*, GROUP_CONCAT(o.nombre SEPARATOR ', ') AS obras_asignadas
        FROM proveedores p
        LEFT JOIN proveedor_obras po ON po.id_proveedor = p.id
        LEFT JOIN obras o ON o.id = po.id_obra
        WHERE p.activo > 0
          AND (p.estado_registro IS NULL OR p.estado_registro = 'aprobado')
        GROUP BY p.id
        ORDER BY p.razon_social
    """)


def guardar_documento_proveedor(id_proveedor, nombre_archivo, nombre_original, tipo_archivo, subido_por):
    return execute("""
        INSERT INTO proveedor_documentos (id_proveedor, nombre_archivo, nombre_original, tipo_archivo, subido_por)
        VALUES (%s, %s, %s, %s, %s)
    """, (id_proveedor, nombre_archivo, nombre_original, tipo_archivo, subido_por))


def get_documentos_proveedor(id_proveedor):
    return query("""
        SELECT pd.*, u.nombre AS subido_por_nombre
        FROM proveedor_documentos pd
        LEFT JOIN usuarios u ON u.id = pd.subido_por
        WHERE pd.id_proveedor = %s
        ORDER BY pd.creado_en DESC
    """, (id_proveedor,))


def eliminar_documento_proveedor(doc_id):
    doc = query("SELECT * FROM proveedor_documentos WHERE id=%s", (doc_id,), one=True)
    if doc:
        # No permitir eliminar documentos ININME que estén pagados
        if doc.get("estado_pago") == "pagado":
            return None
        execute("DELETE FROM proveedor_documentos WHERE id=%s", (doc_id,))
    return doc


def marcar_documento_pagado(doc_id):
    """Marca un documento ININME-FACTURA como pagado (irreversible)."""
    doc = query("SELECT * FROM proveedor_documentos WHERE id=%s", (doc_id,), one=True)
    if doc and doc.get("estado_pago") != "pagado":
        execute("UPDATE proveedor_documentos SET estado_pago='pagado' WHERE id=%s", (doc_id,))
        return doc
    return None


def get_documento_proveedor(doc_id):
    """Obtiene un documento por su ID."""
    return query("SELECT * FROM proveedor_documentos WHERE id=%s", (doc_id,), one=True)


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


def _asegurar_columnas_evaluaciones():
    """Agrega columnas nuevas si no existen en proveedor_evaluaciones."""
    columnas_nuevas = [
        ("puntaje_final", "DECIMAL(6,2) DEFAULT NULL"),
        ("clasificacion", "VARCHAR(50) DEFAULT NULL"),
        ("tipo_evaluacion", "VARCHAR(30) DEFAULT 'servicio'"),
        ("objeto_contrato", "VARCHAR(255) DEFAULT NULL"),
        ("num_contrato", "VARCHAR(100) DEFAULT NULL"),
        ("fecha_inicio", "DATE DEFAULT NULL"),
        ("fecha_fin", "DATE DEFAULT NULL"),
    ]
    for col, definicion in columnas_nuevas:
        try:
            execute(f"ALTER TABLE proveedor_evaluaciones ADD COLUMN {col} {definicion}")
        except Exception:
            pass  # Ya existe

# Ejecutar al importar para asegurar schema actualizado
try:
    _asegurar_columnas_evaluaciones()
except Exception:
    pass


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


# ── Presupuesto por obra (financiero / Procore) ────────────────────

def get_presupuesto_obra_financiero(id_obra):
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


def actualizar_cotizacion_analisis(id_cotizacion, proveedor, numero_cotizacion, fecha_visita, observaciones, items):
    """Actualiza encabezado y reemplaza los items de una cotización ya subida.
    items: lista de dicts {descripcion, cantidad, unidad, precio_unitario}."""
    execute("""
        UPDATE analisis_compra_cotizaciones
        SET proveedor=%s, numero_cotizacion=%s, fecha_visita=%s, observaciones=%s
        WHERE id=%s
    """, (proveedor, numero_cotizacion, fecha_visita, observaciones, id_cotizacion))
    execute("DELETE FROM analisis_compra_items WHERE id_cotizacion=%s", (id_cotizacion,))
    total = 0
    for it in items:
        costo = round(float(it.get("cantidad") or 0) * float(it.get("precio_unitario") or 0), 2)
        total += costo
        execute("""
            INSERT INTO analisis_compra_items (id_cotizacion, descripcion, cantidad, unidad, precio_unitario, costo)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (id_cotizacion, it.get("descripcion"), it.get("cantidad") or 0, it.get("unidad"),
              it.get("precio_unitario") or 0, costo))
    execute("UPDATE analisis_compra_cotizaciones SET total=%s WHERE id=%s", (round(total, 2), id_cotizacion))


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
             fecha_elaboracion, fecha_deposito, monto_deposito, observaciones, estatus, creado_por,
             nombre_empleado_pago)
        VALUES
            (%(id_obra)s, %(empresa)s, %(tipo)s, %(elaboro)s, %(num_semana)s,
             %(semana_inicio)s, %(semana_fin)s, %(fecha_elaboracion)s,
             %(fecha_deposito)s, %(monto_deposito)s, %(observaciones)s, %(estatus)s, %(creado_por)s,
             %(nombre_empleado_pago)s)
    """, d)


def actualizar_comprobacion_caja_chica(cid, d):
    execute("""
        UPDATE caja_chica_comprobaciones SET
            id_obra=%(id_obra)s, empresa=%(empresa)s, tipo=%(tipo)s, elaboro=%(elaboro)s,
            num_semana=%(num_semana)s, semana_inicio=%(semana_inicio)s, semana_fin=%(semana_fin)s,
            fecha_elaboracion=%(fecha_elaboracion)s, fecha_deposito=%(fecha_deposito)s,
            monto_deposito=%(monto_deposito)s, observaciones=%(observaciones)s,
            nombre_empleado_pago=%(nombre_empleado_pago)s
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
            id_codigo_costo         INT DEFAULT NULL,
            creado_por              INT DEFAULT NULL,
            creado_en               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_numero (numero),
            INDEX idx_obra (id_obra),
            INDEX idx_codigo_costo (id_codigo_costo),
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
    return query("""
        SELECT ct.*, cc.codigo AS cc_codigo, cc.descripcion AS cc_descripcion
        FROM contratos ct
        LEFT JOIN codigos_costo cc ON cc.id = ct.id_codigo_costo
        WHERE ct.id=%s
    """, (cid,), one=True)


def crear_contrato(d):
    return execute("""
        INSERT INTO contratos
            (numero, compania_contratista, empresa, titulo, estatus, ejecutado,
             monto_original, ordenes_cambio_aprobadas, monto_revisado,
             facturado, pagos_emitidos, pct_pagado, saldo_restante,
             proveedor, telefono_proveedor, email_proveedor, id_obra, id_codigo_costo, creado_por)
        VALUES
            (%(numero)s, %(compania_contratista)s, %(empresa)s, %(titulo)s,
             %(estatus)s, %(ejecutado)s, %(monto_original)s, %(ordenes_cambio_aprobadas)s,
             %(monto_revisado)s, %(facturado)s, %(pagos_emitidos)s, %(pct_pagado)s,
             %(saldo_restante)s, %(proveedor)s, %(telefono_proveedor)s,
             %(email_proveedor)s, %(id_obra)s, %(id_codigo_costo)s, %(creado_por)s)
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
            "empresa": _str(fila.get("empresa") or fila.get("Tipo")),
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


# ══════════════════════════════════════════════════════════════════
#  CONTROL DE AVANCE FÍSICO Y FINANCIERO
#  Seguimiento semanal programado vs real por concepto/tramo/obra
# ══════════════════════════════════════════════════════════════════

def _init_tabla_avance_fisico():
    """Crea las tablas del módulo de Control de Avance Físico y Financiero."""
    # Catálogo de conceptos contratados por obra
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS avance_catalogo (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            id_obra             INT NOT NULL,
            item_id             INT NOT NULL COMMENT 'Num consecutivo del concepto en el contrato',
            tramo               VARCHAR(200) NOT NULL COMMENT 'Tramo / Partida',
            codigo              VARCHAR(20) NOT NULL COMMENT 'Codigo del concepto (1-7)',
            concepto            VARCHAR(300) NOT NULL,
            unidad              VARCHAR(20) NOT NULL,
            cantidad_contratada DECIMAL(14,3) NOT NULL DEFAULT 0,
            precio_unitario     DECIMAL(14,2) NOT NULL DEFAULT 0,
            importe_contratado  DECIMAL(14,2) NOT NULL DEFAULT 0,
            cantidad_estimada   DECIMAL(14,3) DEFAULT 0 COMMENT 'Avance fisico estimado (proyeccion)',
            creado_en           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_obra (id_obra),
            UNIQUE KEY uq_obra_item (id_obra, item_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # Programa semanal (distribución programada por semana)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS avance_programa_semanal (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            id_catalogo         INT NOT NULL COMMENT 'FK avance_catalogo.id',
            id_obra             INT NOT NULL,
            semana              INT NOT NULL COMMENT 'Numero de semana (1-13+)',
            fecha_inicio        DATE DEFAULT NULL,
            fecha_fin           DATE DEFAULT NULL,
            cantidad_programada DECIMAL(14,3) DEFAULT 0,
            importe_programado  DECIMAL(14,2) DEFAULT 0,
            cantidad_acumulada  DECIMAL(14,3) DEFAULT 0,
            importe_acumulado   DECIMAL(14,2) DEFAULT 0,
            pct_avance_acumulado DECIMAL(6,2) DEFAULT 0,
            INDEX idx_catalogo (id_catalogo),
            INDEX idx_obra_semana (id_obra, semana),
            UNIQUE KEY uq_catalogo_semana (id_catalogo, semana)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # Avance real registrado
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS avance_real (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            id_catalogo         INT NOT NULL COMMENT 'FK avance_catalogo.id',
            id_obra             INT NOT NULL,
            semana              INT DEFAULT NULL,
            fecha               DATE DEFAULT NULL,
            cantidad_real       DECIMAL(14,3) DEFAULT 0,
            importe_real        DECIMAL(14,2) DEFAULT 0,
            observaciones       VARCHAR(255) DEFAULT NULL,
            registrado_por      INT DEFAULT NULL,
            creado_en           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_catalogo (id_catalogo),
            INDEX idx_obra (id_obra),
            INDEX idx_semana (id_obra, semana)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # Parámetros del contrato (fechas, duración)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS avance_parametros (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            id_obra         INT NOT NULL,
            fecha_inicio    DATE DEFAULT NULL,
            fecha_fin       DATE DEFAULT NULL,
            duracion_dias   INT DEFAULT NULL,
            contrato        VARCHAR(200) DEFAULT NULL,
            empresa         VARCHAR(100) DEFAULT NULL,
            importe_total   DECIMAL(14,2) DEFAULT 0,
            observaciones   TEXT DEFAULT NULL,
            UNIQUE KEY uq_obra (id_obra)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)


# ── CRUD Avance Físico ────────────────────────────────────────────

def _calcular_semana_actual_obra(id_obra):
    """Calcula en qué semana del programa se encuentra la obra hoy.
    Usa la fecha_inicio de avance_parametros. Si no hay parámetros o la obra
    no ha iniciado, retorna None. Si ya finalizó, retorna la última semana."""
    params = query("SELECT fecha_inicio, fecha_fin FROM avance_parametros WHERE id_obra=%s",
                   (id_obra,), one=True)
    if not params or not params.get("fecha_inicio"):
        # Sin parámetros: usar la última semana con fecha_fin <= hoy
        sem = query("""
            SELECT MAX(semana) AS sem FROM avance_programa_semanal
            WHERE id_obra=%s AND fecha_fin <= CURDATE()
        """, (id_obra,), one=True)
        if sem and sem["sem"]:
            return int(sem["sem"])
        # Si no hay semanas pasadas, retornar la max semana disponible
        sem_max = query("SELECT MAX(semana) AS sem FROM avance_programa_semanal WHERE id_obra=%s",
                        (id_obra,), one=True)
        return int(sem_max["sem"]) if sem_max and sem_max["sem"] else None

    fecha_inicio = params["fecha_inicio"]
    if isinstance(fecha_inicio, str):
        fecha_inicio = datetime.strptime(fecha_inicio, "%Y-%m-%d").date()
    hoy = date.today()

    if hoy < fecha_inicio:
        return 0  # Obra no ha iniciado

    # Buscar la semana cuyo rango contiene la fecha de hoy
    sem = query("""
        SELECT semana FROM avance_programa_semanal
        WHERE id_obra=%s AND fecha_inicio <= %s AND fecha_fin >= %s
        ORDER BY semana DESC LIMIT 1
    """, (id_obra, hoy, hoy), one=True)
    if sem:
        return int(sem["semana"])

    # Si hoy ya pasó todas las semanas del programa, retornar la última
    sem_max = query("""
        SELECT MAX(semana) AS sem FROM avance_programa_semanal
        WHERE id_obra=%s AND fecha_fin <= %s
    """, (id_obra, hoy), one=True)
    if sem_max and sem_max["sem"]:
        return int(sem_max["sem"])

    # Fallback: última semana del programa
    sem_max = query("SELECT MAX(semana) AS sem FROM avance_programa_semanal WHERE id_obra=%s",
                    (id_obra,), one=True)
    return int(sem_max["sem"]) if sem_max and sem_max["sem"] else None


def get_avance_catalogo(id_obra, semana_corte=None):
    """Obtiene todos los conceptos del catálogo con TODOS los campos calculados
    fielmente según las fórmulas del Excel de avance físico-financiero:

    DATOS FIJOS (del catálogo):
      cantidad_contratada, precio_unitario, importe_contratado, cantidad_estimada

    PROGRAMADO (viene del Selector Semanal = Cantidad Acumulada a la fecha):
      cantidad_programada_total = SUM(programa_semanal.cantidad_programada) hasta semana_corte
      pct_fisico_programado     = SI(cantidad_contratada=0, 0, cantidad_programada / cantidad_contratada)
      importe_programado_total  = cantidad_programada_total × precio_unitario
      pct_financiero_programado = SI(importe_contratado=0, 0, importe_programado / importe_contratado)

    REAL (viene de avance_real acumulado):
      cantidad_real_total       = SUM(avance_real.cantidad_real)
      pct_fisico_real           = SI(cantidad_contratada=0, 0, cantidad_real / cantidad_contratada)
      importe_real_total        = cantidad_real_total × precio_unitario
      pct_financiero_real       = SI(importe_contratado=0, 0, importe_real / importe_contratado)

    ESTIMADO (dato manual en avance_catalogo.cantidad_estimada):
      cantidad_estimada         = campo directo
      pct_fisico_estimado       = SI(cantidad_contratada=0, 0, cantidad_estimada / cantidad_contratada)
      importe_estimado          = cantidad_estimada × precio_unitario
      pct_financiero_estimado   = SI(importe_contratado=0, 0, importe_estimado / importe_contratado)

    DIFERENCIAS:
      diferencia_fisica_pct     = pct_fisico_real - pct_fisico_programado
      diferencia_financiera     = importe_real - importe_programado

    ESTATUS:
      SI(diferencia_fisica_pct >= 0, 'En tiempo/Adelanto', 'Atraso')
      (con excepción: si ambos son 0, 'Sin programar')
    """
    if semana_corte is None:
        semana_corte = _calcular_semana_actual_obra(id_obra)
    if semana_corte is None:
        semana_corte = 9999  # Sin programa: mostrar todo programado

    return query("""
        SELECT c.*,
            -- ═══ REAL ═══
            COALESCE((SELECT SUM(r.cantidad_real) FROM avance_real r WHERE r.id_catalogo=c.id), 0)
                AS cantidad_real_total,
            ROUND(COALESCE((SELECT SUM(r.cantidad_real) FROM avance_real r WHERE r.id_catalogo=c.id), 0)
                * c.precio_unitario, 2)
                AS importe_real_total,
            CASE WHEN c.cantidad_contratada > 0
                THEN ROUND(COALESCE((SELECT SUM(r.cantidad_real) FROM avance_real r
                      WHERE r.id_catalogo=c.id), 0) / c.cantidad_contratada * 100, 1)
                ELSE 0 END
                AS pct_fisico_real,
            CASE WHEN c.importe_contratado > 0
                THEN ROUND(COALESCE((SELECT SUM(r.cantidad_real) FROM avance_real r
                      WHERE r.id_catalogo=c.id), 0) * c.precio_unitario / c.importe_contratado * 100, 1)
                ELSE 0 END
                AS pct_financiero_real,

            -- ═══ PROGRAMADO (Selector Semanal: Cantidad Acumulada a la fecha) ═══
            COALESCE((SELECT SUM(p.cantidad_programada) FROM avance_programa_semanal p
                      WHERE p.id_catalogo=c.id AND p.semana <= %s), 0)
                AS cantidad_programada_total,
            ROUND(COALESCE((SELECT SUM(p.cantidad_programada) FROM avance_programa_semanal p
                      WHERE p.id_catalogo=c.id AND p.semana <= %s), 0)
                * c.precio_unitario, 2)
                AS importe_programado_total,
            CASE WHEN c.cantidad_contratada > 0
                THEN ROUND(COALESCE((SELECT SUM(p.cantidad_programada) FROM avance_programa_semanal p
                      WHERE p.id_catalogo=c.id AND p.semana <= %s), 0) / c.cantidad_contratada * 100, 1)
                ELSE 0 END
                AS pct_fisico_programado,
            CASE WHEN c.importe_contratado > 0
                THEN ROUND(COALESCE((SELECT SUM(p.cantidad_programada) FROM avance_programa_semanal p
                      WHERE p.id_catalogo=c.id AND p.semana <= %s), 0)
                      * c.precio_unitario / c.importe_contratado * 100, 1)
                ELSE 0 END
                AS pct_financiero_programado,

            -- ═══ ESTIMADO ═══
            ROUND(COALESCE(c.cantidad_estimada, 0) * c.precio_unitario, 2)
                AS importe_estimado,
            CASE WHEN c.cantidad_contratada > 0
                THEN ROUND(COALESCE(c.cantidad_estimada, 0) / c.cantidad_contratada * 100, 1)
                ELSE 0 END
                AS pct_fisico_estimado,
            CASE WHEN c.importe_contratado > 0
                THEN ROUND(COALESCE(c.cantidad_estimada, 0) * c.precio_unitario / c.importe_contratado * 100, 1)
                ELSE 0 END
                AS pct_financiero_estimado,

            -- ═══ DIFERENCIAS (Real - Programado) ═══
            ROUND(
                CASE WHEN c.cantidad_contratada > 0
                    THEN (COALESCE((SELECT SUM(r.cantidad_real) FROM avance_real r WHERE r.id_catalogo=c.id), 0)
                          - COALESCE((SELECT SUM(p.cantidad_programada) FROM avance_programa_semanal p
                                      WHERE p.id_catalogo=c.id AND p.semana <= %s), 0))
                         / c.cantidad_contratada * 100
                    ELSE 0 END, 2)
                AS diferencia_fisica_pct,
            ROUND(
                (COALESCE((SELECT SUM(r.cantidad_real) FROM avance_real r WHERE r.id_catalogo=c.id), 0)
                 - COALESCE((SELECT SUM(p.cantidad_programada) FROM avance_programa_semanal p
                             WHERE p.id_catalogo=c.id AND p.semana <= %s), 0))
                * c.precio_unitario, 2)
                AS diferencia_financiera,

            -- ═══ ESTATUS ═══
            CASE
                WHEN COALESCE((SELECT SUM(r.cantidad_real) FROM avance_real r WHERE r.id_catalogo=c.id), 0) = 0
                     AND COALESCE((SELECT SUM(p.cantidad_programada) FROM avance_programa_semanal p
                                   WHERE p.id_catalogo=c.id AND p.semana <= %s), 0) = 0
                    THEN 'Sin programar'
                WHEN (COALESCE((SELECT SUM(r.cantidad_real) FROM avance_real r WHERE r.id_catalogo=c.id), 0)
                      - COALESCE((SELECT SUM(p.cantidad_programada) FROM avance_programa_semanal p
                                  WHERE p.id_catalogo=c.id AND p.semana <= %s), 0)) >= 0
                    THEN 'En tiempo/Adelanto'
                ELSE 'Atraso'
            END AS estatus
        FROM avance_catalogo c
        WHERE c.id_obra=%s
        ORDER BY c.item_id
    """, (semana_corte, semana_corte, semana_corte, semana_corte,
          semana_corte, semana_corte, semana_corte, semana_corte, id_obra))


def get_avance_resumen_tramos(id_obra, semana_corte=None):
    """Resumen agrupado por tramo con subtotales (como los SUBTOTAL del Excel).
    Incluye: contratado, programado, real, estimado, % financieros, estatus."""
    if semana_corte is None:
        semana_corte = _calcular_semana_actual_obra(id_obra)
    if semana_corte is None:
        semana_corte = 9999

    return query("""
        SELECT c.tramo,
            COUNT(*) AS num_conceptos,
            -- Contratado
            SUM(c.importe_contratado) AS importe_contratado,
            -- Programado a la fecha
            SUM(COALESCE((SELECT SUM(p.cantidad_programada) FROM avance_programa_semanal p
                          WHERE p.id_catalogo=c.id AND p.semana <= %s), 0)
                * c.precio_unitario) AS importe_programado,
            CASE WHEN SUM(c.importe_contratado) > 0
                THEN ROUND(SUM(COALESCE((SELECT SUM(p.cantidad_programada) FROM avance_programa_semanal p
                          WHERE p.id_catalogo=c.id AND p.semana <= %s), 0)
                    * c.precio_unitario) / SUM(c.importe_contratado) * 100, 1)
                ELSE 0 END AS pct_financiero_programado,
            -- Real
            SUM(COALESCE((SELECT SUM(r.cantidad_real) FROM avance_real r WHERE r.id_catalogo=c.id), 0)
                * c.precio_unitario) AS importe_real,
            CASE WHEN SUM(c.importe_contratado) > 0
                THEN ROUND(SUM(COALESCE((SELECT SUM(r.cantidad_real) FROM avance_real r WHERE r.id_catalogo=c.id), 0)
                    * c.precio_unitario) / SUM(c.importe_contratado) * 100, 1)
                ELSE 0 END AS pct_financiero_real,
            -- Estimado
            SUM(COALESCE(c.cantidad_estimada, 0) * c.precio_unitario) AS importe_estimado,
            CASE WHEN SUM(c.importe_contratado) > 0
                THEN ROUND(SUM(COALESCE(c.cantidad_estimada, 0) * c.precio_unitario)
                    / SUM(c.importe_contratado) * 100, 1)
                ELSE 0 END AS pct_financiero_estimado,
            -- Estatus del tramo
            CASE
                WHEN SUM(COALESCE((SELECT SUM(r.cantidad_real) FROM avance_real r WHERE r.id_catalogo=c.id), 0)
                     * c.precio_unitario)
                     >= SUM(COALESCE((SELECT SUM(p.cantidad_programada) FROM avance_programa_semanal p
                                      WHERE p.id_catalogo=c.id AND p.semana <= %s), 0)
                            * c.precio_unitario)
                    THEN 'En tiempo/Adelanto'
                WHEN SUM(COALESCE((SELECT SUM(r.cantidad_real) FROM avance_real r WHERE r.id_catalogo=c.id), 0)) = 0
                     AND SUM(COALESCE((SELECT SUM(p.cantidad_programada) FROM avance_programa_semanal p
                                       WHERE p.id_catalogo=c.id AND p.semana <= %s), 0)) > 0
                    THEN 'Atraso'
                WHEN SUM(COALESCE((SELECT SUM(r.cantidad_real) FROM avance_real r WHERE r.id_catalogo=c.id), 0)) = 0
                    THEN 'Sin iniciar'
                ELSE 'Atraso'
            END AS estatus
        FROM avance_catalogo c
        WHERE c.id_obra=%s
        GROUP BY c.tramo
        ORDER BY MIN(c.item_id)
    """, (semana_corte, semana_corte, semana_corte, semana_corte, id_obra))


def get_avance_programa_semana(id_obra, semana):
    """Programa de una semana específica con datos del catálogo y avance real."""
    return query("""
        SELECT p.*, c.tramo, c.codigo, c.concepto, c.unidad,
               c.cantidad_contratada, c.precio_unitario, c.importe_contratado,
               COALESCE((SELECT SUM(r.cantidad_real) FROM avance_real r
                         WHERE r.id_catalogo=c.id AND r.semana=p.semana), 0) AS cantidad_real_semana,
               COALESCE((SELECT SUM(r.cantidad_real) FROM avance_real r
                         WHERE r.id_catalogo=c.id), 0) AS cantidad_real_acumulada
        FROM avance_programa_semanal p
        INNER JOIN avance_catalogo c ON c.id = p.id_catalogo
        WHERE p.id_obra=%s AND p.semana=%s
        ORDER BY c.item_id
    """, (id_obra, semana))


def get_avance_semanas_disponibles(id_obra):
    """Lista de semanas con programa cargado."""
    return query("""
        SELECT DISTINCT semana, MIN(fecha_inicio) AS fecha_inicio, MAX(fecha_fin) AS fecha_fin
        FROM avance_programa_semanal WHERE id_obra=%s
        GROUP BY semana ORDER BY semana
    """, (id_obra,))


def get_avance_parametros(id_obra):
    return query("SELECT * FROM avance_parametros WHERE id_obra=%s", (id_obra,), one=True)


def get_avance_kpis(id_obra, semana_corte=None):
    """KPIs generales del avance de una obra (como el 'Resumen General' del Excel).
    Incluye: contratado, programado a la fecha, real ejercido, estimado, semana actual."""
    if semana_corte is None:
        semana_corte = _calcular_semana_actual_obra(id_obra)
    if semana_corte is None:
        semana_corte = 9999

    return query("""
        SELECT
            (SELECT COUNT(*) FROM avance_catalogo WHERE id_obra=%s) AS total_conceptos,
            (SELECT COUNT(DISTINCT tramo) FROM avance_catalogo WHERE id_obra=%s) AS total_tramos,
            (SELECT COALESCE(SUM(importe_contratado), 0) FROM avance_catalogo WHERE id_obra=%s) AS importe_contratado,
            -- Real: SUM(cantidad_real * PU)
            (SELECT COALESCE(SUM(r.cantidad_real * c.precio_unitario), 0)
             FROM avance_real r INNER JOIN avance_catalogo c ON c.id=r.id_catalogo
             WHERE r.id_obra=%s) AS importe_real,
            -- Programado a la fecha (hasta semana de corte)
            (SELECT COALESCE(SUM(p.cantidad_programada * c.precio_unitario), 0)
             FROM avance_programa_semanal p INNER JOIN avance_catalogo c ON c.id=p.id_catalogo
             WHERE p.id_obra=%s AND p.semana <= %s) AS importe_programado,
            -- Estimado: SUM(cantidad_estimada * PU)
            (SELECT COALESCE(SUM(c.cantidad_estimada * c.precio_unitario), 0)
             FROM avance_catalogo c WHERE c.id_obra=%s) AS importe_estimado,
            (SELECT MAX(semana) FROM avance_programa_semanal WHERE id_obra=%s) AS semanas_programa,
            %s AS semana_actual
    """, (id_obra, id_obra, id_obra, id_obra, id_obra, semana_corte, id_obra, id_obra, semana_corte), one=True)


def registrar_avance_real(id_catalogo, id_obra, semana, fecha, cantidad, obs, registrado_por):
    """Registra avance real de un concepto. El importe se calcula automáticamente
    desde el PU del catálogo (no se almacena redundantemente).
    Permite múltiples registros por concepto (acumulativos por semana/fecha)."""
    # Obtener PU para calcular importe (se guarda para auditoría/histórico)
    cat = query("SELECT precio_unitario FROM avance_catalogo WHERE id=%s", (id_catalogo,), one=True)
    pu = float(cat["precio_unitario"]) if cat else 0
    importe = round(float(cantidad) * pu, 2)
    return execute("""
        INSERT INTO avance_real (id_catalogo, id_obra, semana, fecha, cantidad_real, importe_real, observaciones, registrado_por)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (id_catalogo, id_obra, semana, fecha, cantidad, importe, obs, registrado_por))


def get_avance_historial_real(id_catalogo):
    """Historial de registros de avance real de un concepto (para auditoría)."""
    return query("""
        SELECT r.*, u.nombre AS registrado_por_nombre
        FROM avance_real r
        LEFT JOIN usuarios u ON u.id = r.registrado_por
        WHERE r.id_catalogo=%s
        ORDER BY r.creado_en DESC
    """, (id_catalogo,))


# ── Avance Físico: Captura mensual (pestaña "Avance Físico" del Excel) ────

def _init_tabla_avance_meses():
    """Crea la tabla de meses configurados manualmente por obra."""
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS avance_meses (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            id_obra         INT NOT NULL,
            num             INT NOT NULL COMMENT 'Num de mes (1, 2, 3...)',
            label           VARCHAR(100) DEFAULT NULL COMMENT 'Ej: Enero 2026, Mayo 2026',
            fecha_inicio    DATE NOT NULL,
            fecha_fin       DATE NOT NULL,
            creado_en       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_obra (id_obra),
            UNIQUE KEY uq_obra_num (id_obra, num)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # Tabla para guardar estimado por mes por concepto
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS avance_estimado_mes (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            id_catalogo     INT NOT NULL,
            id_obra         INT NOT NULL,
            mes_num         INT NOT NULL,
            cantidad_estimada DECIMAL(14,3) DEFAULT 0,
            INDEX idx_catalogo (id_catalogo),
            INDEX idx_obra_mes (id_obra, mes_num),
            UNIQUE KEY uq_cat_mes (id_catalogo, mes_num)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

try:
    _init_tabla_avance_meses()
except Exception:
    pass


def get_meses_contrato(id_obra):
    """Obtiene los meses de la obra. Primero busca meses configurados manualmente
    (tabla avance_meses). Si no hay, genera automáticamente desde avance_parametros."""
    # 1. Buscar meses manuales
    meses_manual = query("""
        SELECT num, label, fecha_inicio, fecha_fin
        FROM avance_meses WHERE id_obra=%s ORDER BY num
    """, (id_obra,))

    if meses_manual:
        resultado = []
        for m in meses_manual:
            fi = m["fecha_inicio"]
            ff = m["fecha_fin"]
            if isinstance(fi, date):
                fi_str = fi.strftime("%Y-%m-%d")
            else:
                fi_str = str(fi)
            if isinstance(ff, date):
                ff_str = ff.strftime("%Y-%m-%d")
            else:
                ff_str = str(ff)
            # Generar rango legible
            fi_d = fi if isinstance(fi, date) else datetime.strptime(str(fi), "%Y-%m-%d").date()
            ff_d = ff if isinstance(ff, date) else datetime.strptime(str(ff), "%Y-%m-%d").date()
            rango = f"{fi_d.strftime('%d/%m')} al {ff_d.strftime('%d/%m/%Y')}"
            resultado.append({
                "num": m["num"],
                "label": m["label"] or f"Mes {m['num']}",
                "rango": rango,
                "fecha_inicio": fi_str,
                "fecha_fin": ff_str,
            })
        return resultado

    # 2. Fallback: generar automáticamente desde parámetros
    params = query("SELECT fecha_inicio, fecha_fin FROM avance_parametros WHERE id_obra=%s", (id_obra,), one=True)
    if not params or not params.get("fecha_inicio") or not params.get("fecha_fin"):
        return []

    fi = params["fecha_inicio"]
    ff = params["fecha_fin"]
    if isinstance(fi, str):
        fi = datetime.strptime(fi, "%Y-%m-%d").date()
    if isinstance(ff, str):
        ff = datetime.strptime(ff, "%Y-%m-%d").date()

    _MESES_ES = {1:"Enero",2:"Febrero",3:"Marzo",4:"Abril",5:"Mayo",6:"Junio",
                 7:"Julio",8:"Agosto",9:"Septiembre",10:"Octubre",11:"Noviembre",12:"Diciembre"}

    meses = []
    current = fi
    num = 1
    while current <= ff:
        mes_inicio = current
        if current.month == 12:
            mes_fin_natural = date(current.year + 1, 1, 1) - timedelta(days=1)
        else:
            mes_fin_natural = date(current.year, current.month + 1, 1) - timedelta(days=1)
        mes_fin = min(mes_fin_natural, ff)

        label = f"{_MESES_ES[current.month]} {current.year}"
        rango = f"{mes_inicio.strftime('%d/%m')} al {mes_fin.strftime('%d/%m/%Y')}"
        meses.append({
            "num": num,
            "label": label,
            "rango": rango,
            "fecha_inicio": mes_inicio.strftime("%Y-%m-%d"),
            "fecha_fin": mes_fin.strftime("%Y-%m-%d"),
        })
        num += 1
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)

    return meses


def agregar_mes_avance(id_obra, num, label, fecha_inicio, fecha_fin):
    """Agrega un mes manual a la configuración de la obra."""
    return execute("""
        INSERT INTO avance_meses (id_obra, num, label, fecha_inicio, fecha_fin)
        VALUES (%s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE label=VALUES(label), fecha_inicio=VALUES(fecha_inicio), fecha_fin=VALUES(fecha_fin)
    """, (id_obra, num, label, fecha_inicio, fecha_fin))


def eliminar_mes_avance(id_obra, num):
    """Elimina un mes de la configuración de la obra."""
    execute("DELETE FROM avance_meses WHERE id_obra=%s AND num=%s", (id_obra, num))


def get_meses_manuales(id_obra):
    """Obtiene los meses configurados manualmente (para el formulario de edición)."""
    return query("SELECT * FROM avance_meses WHERE id_obra=%s ORDER BY num", (id_obra,))


def get_avance_captura_mensual(id_obra, meses):
    """Obtiene la grilla de captura: por cada concepto, el real y estimado de cada mes.
    Retorna lista de conceptos con campo 'meses_data' que contiene {mes_num: {real: X, estimada: Y}}.
    El 'real' por mes viene de avance_real (agrupado por fecha en rango del mes).
    El 'estimado' por mes viene de avance_estimado_mes."""
    catalogo = query("""
        SELECT id, item_id, tramo, codigo, concepto, unidad, cantidad_contratada,
               precio_unitario, importe_contratado, cantidad_estimada
        FROM avance_catalogo WHERE id_obra=%s ORDER BY item_id
    """, (id_obra,))

    if not catalogo:
        return []

    # Obtener todos los registros reales de la obra
    reales = query("""
        SELECT id_catalogo, fecha, cantidad_real
        FROM avance_real WHERE id_obra=%s
    """, (id_obra,))

    # Obtener estimados por mes
    estimados_mes = query("""
        SELECT id_catalogo, mes_num, cantidad_estimada
        FROM avance_estimado_mes WHERE id_obra=%s
    """, (id_obra,))

    # Agrupar reales por (id_catalogo, mes_num)
    from collections import defaultdict
    real_por_mes = defaultdict(lambda: defaultdict(float))
    for r in reales:
        if not r["fecha"]:
            continue
        f = r["fecha"]
        if isinstance(f, str):
            f = datetime.strptime(f, "%Y-%m-%d").date()
        # Encontrar a qué mes del contrato pertenece
        for m in meses:
            mi = datetime.strptime(m["fecha_inicio"], "%Y-%m-%d").date() if isinstance(m["fecha_inicio"], str) else m["fecha_inicio"]
            mf = datetime.strptime(m["fecha_fin"], "%Y-%m-%d").date() if isinstance(m["fecha_fin"], str) else m["fecha_fin"]
            if mi <= f <= mf:
                real_por_mes[r["id_catalogo"]][m["num"]] += float(r["cantidad_real"])
                break

    # Agrupar estimados por (id_catalogo, mes_num)
    est_por_mes = defaultdict(lambda: defaultdict(float))
    for e in estimados_mes:
        est_por_mes[e["id_catalogo"]][e["mes_num"]] = float(e["cantidad_estimada"] or 0)

    # Construir resultado
    for c in catalogo:
        c["acumulado_real"] = sum(real_por_mes[c["id"]].values())
        c["acumulado_estimada"] = sum(est_por_mes[c["id"]].values()) or float(c["cantidad_estimada"] or 0)
        c["meses_data"] = {}
        for m in meses:
            c["meses_data"][m["num"]] = {
                "real": real_por_mes[c["id"]].get(m["num"], 0),
                "estimada": est_por_mes[c["id"]].get(m["num"], 0),
            }

    return catalogo


def guardar_avance_captura_mensual(id_obra, datos, registrado_por):
    """Guarda la captura mensual de avance real y estimado.
    datos = lista de {id_catalogo, mes_num, fecha_inicio_mes, fecha_fin_mes, real, estimada}
    Para 'real': borra los registros del mes y re-inserta con la cantidad nueva.
    Para 'estimada': actualiza avance_catalogo.cantidad_estimada con la suma de TODOS los meses."""
    from collections import defaultdict

    # Agrupar datos por concepto
    por_concepto = defaultdict(list)
    for d in datos:
        por_concepto[d["id_catalogo"]].append(d)

    for id_catalogo, entradas in por_concepto.items():
        cat = query("SELECT precio_unitario FROM avance_catalogo WHERE id=%s",
                    (id_catalogo,), one=True)
        if not cat:
            continue
        pu = float(cat["precio_unitario"])

        total_estimada = 0
        for entry in entradas:
            real_val = float(entry.get("real") or 0)
            est_val = float(entry.get("estimada") or 0)
            total_estimada += est_val
            fecha_inicio_mes = entry["fecha_inicio_mes"]
            fecha_fin_mes = entry["fecha_fin_mes"]

            # ── REAL ──
            # Borrar registros existentes de este concepto en este rango de fechas
            execute("""DELETE FROM avance_real WHERE id_catalogo=%s AND id_obra=%s
                       AND fecha >= %s AND fecha <= %s""",
                    (id_catalogo, id_obra, fecha_inicio_mes, fecha_fin_mes))
            if real_val > 0:
                # Insertar el nuevo valor
                importe = round(real_val * pu, 2)
                semana = calcular_semana_combustible(fecha_inicio_mes)
                execute("""INSERT INTO avance_real
                           (id_catalogo, id_obra, semana, fecha, cantidad_real, importe_real, observaciones, registrado_por)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                        (id_catalogo, id_obra, semana, fecha_inicio_mes, real_val, importe, None, registrado_por))

            # ── ESTIMADO por mes: guardar en avance_estimado_mes ──
            execute("""INSERT INTO avance_estimado_mes (id_catalogo, id_obra, mes_num, cantidad_estimada)
                       VALUES (%s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE cantidad_estimada=%s""",
                    (id_catalogo, id_obra, entry["mes_num"], est_val, est_val))

        # Actualizar cantidad_estimada global (suma de todos los meses)
        execute("UPDATE avance_catalogo SET cantidad_estimada=%s WHERE id=%s",
                (total_estimada, id_catalogo))


def get_curva_s_data(id_obra):
    """Obtiene datos para la Curva S: acumulado programado vs real por semana.
    El programado usa importe_acumulado de la tabla (precalculado en importación).
    El real se calcula como SUM(cantidad_real * PU) agrupado por semana."""
    return query("""
        SELECT
            p.semana,
            MIN(p.fecha_inicio) AS fecha_inicio,
            SUM(p.importe_programado) AS imp_programado_sem,
            -- Acumulado programado: sumar todo hasta esta semana
            (SELECT COALESCE(SUM(p2.importe_programado), 0)
             FROM avance_programa_semanal p2 WHERE p2.id_obra=%s AND p2.semana <= p.semana)
                AS imp_acumulado_programado,
            -- Real de la semana: SUM(cantidad_real * PU)
            COALESCE((SELECT SUM(r.cantidad_real * c.precio_unitario)
                      FROM avance_real r
                      INNER JOIN avance_catalogo c ON c.id = r.id_catalogo
                      WHERE r.id_obra=%s AND r.semana=p.semana), 0) AS imp_real_sem
        FROM avance_programa_semanal p
        WHERE p.id_obra=%s
        GROUP BY p.semana
        ORDER BY p.semana
    """, (id_obra, id_obra, id_obra))


def importar_avance_excel(wb, id_obra):
    """Importa el Excel de Control de Avance Físico y Financiero.
    Lee la hoja 'Avance Fisico-Financiero' para catálogo y la hoja
    'Distribucion Semanal (Detalle)' para el programa semanal.
    Retorna (conceptos_creados, semanas_creadas)."""
    from openpyxl.utils import get_column_letter

    conceptos_creados = 0
    semanas_creadas = 0

    # ── 1. Leer catálogo desde hoja "Avance Fisico-Financiero" ──
    ws_avance = None
    for ws in wb.worksheets:
        if "avance" in ws.title.lower() and "fisico" in ws.title.lower():
            ws_avance = ws
            break
    if not ws_avance:
        ws_avance = wb.worksheets[0]  # Fallback: primera hoja

    # Buscar fila de encabezados (con "No." y "Concepto")
    header_row = None
    for i, row in enumerate(ws_avance.iter_rows(min_row=1, max_row=15, values_only=False), 1):
        for cell in row:
            if cell.value and "Concepto" in str(cell.value):
                header_row = i
                break
        if header_row:
            break
    if not header_row:
        header_row = 4  # Default

    # Leer conceptos (filas con número en col A)
    for row in ws_avance.iter_rows(min_row=header_row + 1, values_only=True):
        if not row or len(row) < 8:
            continue
        num = row[0]
        if not num or not str(num).strip().isdigit():
            continue
        item_id = int(str(num).strip())
        tramo = str(row[1] or "").strip()
        codigo = str(row[2] or "").strip()
        concepto = str(row[3] or "").strip()
        unidad = str(row[4] or "").strip()
        cantidad = float(row[5] or 0) if row[5] else 0
        pu = float(row[6] or 0) if row[6] else 0
        importe = float(row[7] or 0) if row[7] else 0
        if not concepto:
            continue
        if importe == 0 and cantidad > 0 and pu > 0:
            importe = round(cantidad * pu, 2)

        # Upsert concepto
        existente = query("SELECT id FROM avance_catalogo WHERE id_obra=%s AND item_id=%s",
                          (id_obra, item_id), one=True)
        if existente:
            execute("""UPDATE avance_catalogo SET tramo=%s, codigo=%s, concepto=%s, unidad=%s,
                       cantidad_contratada=%s, precio_unitario=%s, importe_contratado=%s
                       WHERE id=%s""",
                    (tramo, codigo, concepto, unidad, cantidad, pu, importe, existente["id"]))
        else:
            execute("""INSERT INTO avance_catalogo
                       (id_obra, item_id, tramo, codigo, concepto, unidad, cantidad_contratada, precio_unitario, importe_contratado)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (id_obra, item_id, tramo, codigo, concepto, unidad, cantidad, pu, importe))
            conceptos_creados += 1

    # ── 2. Leer programa semanal desde hoja "Distribucion Semanal" ──
    ws_semanal = None
    for ws in wb.worksheets:
        if "distribucion" in ws.title.lower() or "semanal" in ws.title.lower():
            ws_semanal = ws
            break
    if not ws_semanal:
        return conceptos_creados, 0

    # Buscar encabezados
    header_row_s = None
    for i, row in enumerate(ws_semanal.iter_rows(min_row=1, max_row=10, values_only=False), 1):
        for cell in row:
            if cell.value and "ItemID" in str(cell.value):
                header_row_s = i
                break
        if header_row_s:
            break
    if not header_row_s:
        header_row_s = 3

    for row in ws_semanal.iter_rows(min_row=header_row_s + 1, values_only=True):
        if not row or len(row) < 12:
            continue
        item_id_raw = row[0]
        semana_raw = row[1]
        if not item_id_raw or not semana_raw:
            continue
        # Saltar filas que son encabezados o texto
        if isinstance(item_id_raw, str) and any(c.isalpha() for c in item_id_raw):
            continue
        try:
            item_id = int(float(str(item_id_raw)))
            semana = int(float(str(semana_raw)))
        except (ValueError, TypeError):
            continue

        fecha_ini = row[2] if row[2] else None
        fecha_fin = row[3] if row[3] else None
        # Columnas: 4=tramo, 5=codigo, 6=concepto, 7=unidad, 8=cant_programada, 9=imp_programado, 10=cant_acum, 11=imp_acum, 12=%
        def safe_float(val):
            if val is None: return 0
            try: return float(val)
            except (ValueError, TypeError): return 0
        cant_prog = safe_float(row[8]) if len(row) > 8 else 0
        imp_prog = safe_float(row[9]) if len(row) > 9 else 0
        cant_acum = safe_float(row[10]) if len(row) > 10 else 0
        imp_acum = safe_float(row[11]) if len(row) > 11 else 0
        pct_acum = safe_float(row[12]) if len(row) > 12 else 0
        # Convertir porcentaje si viene como decimal (0.156 -> 15.6)
        if 0 < pct_acum < 1:
            pct_acum = round(pct_acum * 100, 1)

        # Convertir fechas si vienen como datetime
        if hasattr(fecha_ini, 'strftime'):
            fecha_ini = fecha_ini.strftime("%Y-%m-%d")
        elif fecha_ini and isinstance(fecha_ini, str) and any(c.isalpha() for c in str(fecha_ini)):
            fecha_ini = None  # Es texto de encabezado, no fecha
        else:
            fecha_ini = None
        if hasattr(fecha_fin, 'strftime'):
            fecha_fin = fecha_fin.strftime("%Y-%m-%d")
        elif fecha_fin and isinstance(fecha_fin, str) and any(c.isalpha() for c in str(fecha_fin)):
            fecha_fin = None  # Es texto de encabezado, no fecha
        else:
            fecha_fin = None

        # Buscar id_catalogo
        cat = query("SELECT id FROM avance_catalogo WHERE id_obra=%s AND item_id=%s",
                    (id_obra, item_id), one=True)
        if not cat:
            continue

        # Upsert programa semanal
        existente = query("SELECT id FROM avance_programa_semanal WHERE id_catalogo=%s AND semana=%s",
                          (cat["id"], semana), one=True)
        if existente:
            execute("""UPDATE avance_programa_semanal SET fecha_inicio=%s, fecha_fin=%s,
                       cantidad_programada=%s, importe_programado=%s, cantidad_acumulada=%s,
                       importe_acumulado=%s, pct_avance_acumulado=%s WHERE id=%s""",
                    (fecha_ini, fecha_fin, cant_prog, imp_prog, cant_acum, imp_acum, pct_acum, existente["id"]))
        else:
            execute("""INSERT INTO avance_programa_semanal
                       (id_catalogo, id_obra, semana, fecha_inicio, fecha_fin,
                        cantidad_programada, importe_programado, cantidad_acumulada, importe_acumulado, pct_avance_acumulado)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (cat["id"], id_obra, semana, fecha_ini, fecha_fin, cant_prog, imp_prog, cant_acum, imp_acum, pct_acum))
            semanas_creadas += 1

    # ── 3. Guardar parámetros si se detectan ──
    ws_params = None
    for ws in wb.worksheets:
        if "parametro" in ws.title.lower() or "param" in ws.title.lower():
            ws_params = ws
            break
    if ws_params:
        fecha_inicio_obra = None
        fecha_fin_obra = None
        duracion = None
        for row in ws_params.iter_rows(min_row=1, max_row=10, values_only=True):
            if not row:
                continue
            for i, cell in enumerate(row):
                val = str(cell or "").lower()
                if "inicio" in val and "fin" not in val and i + 1 < len(row) and row[i + 1]:
                    next_val = row[i + 1]
                    if hasattr(next_val, 'strftime'):  # Solo si es datetime
                        fecha_inicio_obra = next_val
                if "fin" in val and "inicio" not in val and i + 1 < len(row) and row[i + 1]:
                    next_val = row[i + 1]
                    if hasattr(next_val, 'strftime'):  # Solo si es datetime
                        fecha_fin_obra = next_val
                if "duraci" in val and i + 1 < len(row) and row[i + 1]:
                    try:
                        duracion = int(float(str(row[i + 1])))
                    except (ValueError, TypeError):
                        pass
        if fecha_inicio_obra or fecha_fin_obra:
            if hasattr(fecha_inicio_obra, 'strftime'):
                fecha_inicio_obra = fecha_inicio_obra.strftime("%Y-%m-%d")
            else:
                fecha_inicio_obra = None
            if hasattr(fecha_fin_obra, 'strftime'):
                fecha_fin_obra = fecha_fin_obra.strftime("%Y-%m-%d")
            else:
                fecha_fin_obra = None
            if fecha_inicio_obra or fecha_fin_obra:
                execute("""INSERT INTO avance_parametros (id_obra, fecha_inicio, fecha_fin, duracion_dias)
                           VALUES (%s, %s, %s, %s)
                           ON DUPLICATE KEY UPDATE fecha_inicio=VALUES(fecha_inicio),
                           fecha_fin=VALUES(fecha_fin), duracion_dias=VALUES(duracion_dias)""",
                        (id_obra, fecha_inicio_obra, fecha_fin_obra, duracion))

    return conceptos_creados, semanas_creadas


# ══════════════════════════════════════════════════════════════════
#  CONTROL DE ESTIMACIONES Y AJUSTES DE COSTOS
#  Seguimiento de estimaciones por obra: cobrado, faltante, %avance
# ══════════════════════════════════════════════════════════════════

def _init_tabla_estimaciones():
    """Crea las tablas del módulo de Estimaciones y Ajustes de Costos."""
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS estimaciones_obra (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            id_obra             INT DEFAULT NULL,
            identificacion_esma VARCHAR(100) DEFAULT NULL COMMENT 'Nombre interno ESMA',
            contrato            VARCHAR(200) DEFAULT NULL,
            descripcion         TEXT DEFAULT NULL,
            dependencia         VARCHAR(150) DEFAULT NULL,
            fecha_inicio        DATE DEFAULT NULL,
            fecha_fin           DATE DEFAULT NULL,
            duracion_dias       INT DEFAULT NULL,
            superintendente     VARCHAR(150) DEFAULT NULL,
            tipo_ajuste         VARCHAR(60) DEFAULT NULL COMMENT 'Fraccion I, III, etc',
            estimaciones_tipo   VARCHAR(30) DEFAULT 'Quincenal' COMMENT 'Quincenal/Mensual',
            monto_contratado    DECIMAL(14,2) DEFAULT 0,
            monto_cobrado       DECIMAL(14,2) DEFAULT 0,
            monto_faltante      DECIMAL(14,2) DEFAULT 0,
            pct_avance          DECIMAL(6,2) DEFAULT 0,
            observaciones       TEXT DEFAULT NULL,
            auxiliar            VARCHAR(100) DEFAULT NULL,
            creado_en           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_obra (id_obra)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS estimaciones_periodos (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            id_estimacion_obra  INT NOT NULL,
            numero_estimacion   INT DEFAULT NULL COMMENT 'Num de estimacion (1,2,3...)',
            periodo_inicio      DATE DEFAULT NULL,
            periodo_fin         DATE DEFAULT NULL,
            periodo_label       VARCHAR(60) DEFAULT NULL COMMENT 'Ej: 01/05/26-15/05/26',
            monto               DECIMAL(14,2) DEFAULT 0,
            estatus             VARCHAR(30) DEFAULT 'pendiente' COMMENT 'pendiente/cobrada/en_revision',
            observaciones       VARCHAR(255) DEFAULT NULL,
            INDEX idx_est (id_estimacion_obra)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS ajustes_costos (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            id_estimacion_obra  INT NOT NULL,
            mes                 VARCHAR(20) NOT NULL COMMENT 'Febrero, Marzo, etc',
            fecha_publicacion   DATE DEFAULT NULL,
            fecha_limite        DATE DEFAULT NULL,
            monto               DECIMAL(14,2) DEFAULT 0 COMMENT 'Monto del ajuste',
            estatus             VARCHAR(30) DEFAULT 'pendiente',
            cobrado             TINYINT(1) DEFAULT 0 COMMENT '1=cobrado, 0=no cobrado',
            observaciones       VARCHAR(255) DEFAULT NULL,
            INDEX idx_est (id_estimacion_obra)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS estimaciones_documentos (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            id_estimacion_obra  INT NOT NULL,
            nombre_original     VARCHAR(255) NOT NULL,
            nombre_archivo      VARCHAR(255) NOT NULL COMMENT 'Nombre en disco',
            tipo                VARCHAR(60) DEFAULT NULL COMMENT 'Estimacion/Ajuste/General',
            descripcion         VARCHAR(255) DEFAULT NULL,
            subido_por          INT DEFAULT NULL,
            creado_en           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_est (id_estimacion_obra)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)


# ── CRUD Estimaciones ─────────────────────────────────────────────

def get_estimaciones_obras():
    """Lista todas las obras con su info de estimaciones."""
    return query("""
        SELECT e.*, ob.nombre AS obra_nombre
        FROM estimaciones_obra e
        LEFT JOIN obras ob ON ob.id = e.id_obra
        ORDER BY e.id
    """)


def get_estimacion_obra(eid):
    return query("""
        SELECT e.*, ob.nombre AS obra_nombre
        FROM estimaciones_obra e
        LEFT JOIN obras ob ON ob.id = e.id_obra
        WHERE e.id=%s
    """, (eid,), one=True)


def get_periodos_estimacion(id_estimacion_obra):
    return query("""
        SELECT * FROM estimaciones_periodos
        WHERE id_estimacion_obra=%s ORDER BY numero_estimacion, periodo_inicio
    """, (id_estimacion_obra,))


def get_ajustes_estimacion(id_estimacion_obra):
    return query("""
        SELECT * FROM ajustes_costos
        WHERE id_estimacion_obra=%s ORDER BY id
    """, (id_estimacion_obra,))


def crear_estimacion_obra(d):
    d = dict(d)
    d.setdefault("monto_faltante", float(d.get("monto_contratado") or 0) - float(d.get("monto_cobrado") or 0))
    d.setdefault("pct_avance", round(float(d.get("monto_cobrado") or 0) / float(d.get("monto_contratado") or 1) * 100, 2) if float(d.get("monto_contratado") or 0) > 0 else 0)
    return execute("""
        INSERT INTO estimaciones_obra
            (id_obra, identificacion_esma, contrato, descripcion, dependencia,
             fecha_inicio, fecha_fin, duracion_dias, superintendente, tipo_ajuste,
             estimaciones_tipo, monto_contratado, monto_cobrado, monto_faltante,
             pct_avance, observaciones, auxiliar)
        VALUES (%(id_obra)s, %(identificacion_esma)s, %(contrato)s, %(descripcion)s,
                %(dependencia)s, %(fecha_inicio)s, %(fecha_fin)s, %(duracion_dias)s,
                %(superintendente)s, %(tipo_ajuste)s, %(estimaciones_tipo)s,
                %(monto_contratado)s, %(monto_cobrado)s, %(monto_faltante)s,
                %(pct_avance)s, %(observaciones)s, %(auxiliar)s)
    """, d)


def actualizar_montos_estimacion(eid, cobrado):
    """Actualiza monto cobrado y recalcula faltante y %."""
    est = query("SELECT monto_contratado FROM estimaciones_obra WHERE id=%s", (eid,), one=True)
    if not est:
        return
    contratado = float(est["monto_contratado"] or 0)
    faltante = round(contratado - float(cobrado), 2)
    pct = round(float(cobrado) / contratado * 100, 2) if contratado > 0 else 0
    execute("UPDATE estimaciones_obra SET monto_cobrado=%s, monto_faltante=%s, pct_avance=%s WHERE id=%s",
            (cobrado, faltante, pct, eid))


def crear_periodo_estimacion(id_est, numero, periodo_label, monto, estatus="pendiente"):
    return execute("""
        INSERT INTO estimaciones_periodos (id_estimacion_obra, numero_estimacion, periodo_label, monto, estatus)
        VALUES (%s, %s, %s, %s, %s)
    """, (id_est, numero, periodo_label, monto, estatus))


def crear_ajuste_costo(id_est, mes, fecha_pub, fecha_lim, monto=0, estatus="pendiente"):
    return execute("""
        INSERT INTO ajustes_costos (id_estimacion_obra, mes, fecha_publicacion, fecha_limite, monto, estatus)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (id_est, mes, fecha_pub, fecha_lim, monto, estatus))


def editar_periodo_estimacion(pid, numero, periodo_label, monto, estatus):
    """Edita un periodo de estimación existente."""
    execute("""UPDATE estimaciones_periodos
               SET numero_estimacion=%s, periodo_label=%s, monto=%s, estatus=%s
               WHERE id=%s""", (numero, periodo_label, monto, estatus, pid))


def eliminar_periodo_estimacion(pid):
    """Elimina un periodo de estimación."""
    execute("DELETE FROM estimaciones_periodos WHERE id=%s", (pid,))


def editar_ajuste_costo(aid, mes, fecha_pub, fecha_lim, monto, estatus, cobrado):
    """Edita un ajuste de costos existente."""
    execute("""UPDATE ajustes_costos
               SET mes=%s, fecha_publicacion=%s, fecha_limite=%s, monto=%s, estatus=%s, cobrado=%s
               WHERE id=%s""", (mes, fecha_pub, fecha_lim, monto, estatus, cobrado, aid))


def eliminar_ajuste_costo(aid):
    """Elimina un ajuste de costos."""
    execute("DELETE FROM ajustes_costos WHERE id=%s", (aid,))


def toggle_periodo_cobrado(pid, estatus):
    """Cambia estatus de un periodo entre cobrada/pendiente."""
    execute("UPDATE estimaciones_periodos SET estatus=%s WHERE id=%s", (estatus, pid))


def toggle_ajuste_cobrado(aid, cobrado):
    """Cambia estatus cobrado de un ajuste de costos."""
    execute("UPDATE ajustes_costos SET cobrado=%s WHERE id=%s", (cobrado, aid))


# ── Documentos de Estimaciones ────────────────────────────────────

def get_documentos_estimacion(id_estimacion_obra):
    """Obtiene documentos adjuntos de una estimación."""
    return query("""
        SELECT d.*, u.nombre AS subido_por_nombre
        FROM estimaciones_documentos d
        LEFT JOIN usuarios u ON u.id = d.subido_por
        WHERE d.id_estimacion_obra=%s ORDER BY d.creado_en DESC
    """, (id_estimacion_obra,))


def crear_documento_estimacion(id_est, nombre_original, nombre_archivo, tipo, descripcion, subido_por):
    return execute("""
        INSERT INTO estimaciones_documentos (id_estimacion_obra, nombre_original, nombre_archivo, tipo, descripcion, subido_por)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (id_est, nombre_original, nombre_archivo, tipo, descripcion, subido_por))


def eliminar_documento_estimacion(did):
    """Elimina un documento y retorna su nombre en disco."""
    doc = query("SELECT nombre_archivo FROM estimaciones_documentos WHERE id=%s", (did,), one=True)
    if doc:
        execute("DELETE FROM estimaciones_documentos WHERE id=%s", (did,))
    return doc



# ══════════════════════════════════════════════════════════════════
#  CHAT INTERNO — Mensajería entre usuarios del sistema
#  Soporta conversaciones 1-a-1, archivos adjuntos y lectura/no-leído
# ══════════════════════════════════════════════════════════════════

def _init_tabla_chat():
    """Crea las tablas del módulo de chat interno."""
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS chat_conversaciones (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            titulo      VARCHAR(200) DEFAULT NULL COMMENT 'Nombre del grupo o NULL para 1-a-1',
            es_grupo    TINYINT(1) NOT NULL DEFAULT 0,
            creado_por  INT DEFAULT NULL,
            creado_en   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS chat_participantes (
            id                INT AUTO_INCREMENT PRIMARY KEY,
            id_conversacion   INT NOT NULL,
            id_usuario        INT NOT NULL,
            ultimo_leido      DATETIME DEFAULT NULL COMMENT 'Fecha del ultimo mensaje leido',
            UNIQUE KEY uq_conv_user (id_conversacion, id_usuario),
            INDEX idx_usuario (id_usuario)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS chat_mensajes (
            id                INT AUTO_INCREMENT PRIMARY KEY,
            id_conversacion   INT NOT NULL,
            id_usuario        INT NOT NULL COMMENT 'Quien envio el mensaje',
            contenido         TEXT DEFAULT NULL,
            archivo           VARCHAR(255) DEFAULT NULL COMMENT 'Nombre del archivo adjunto en disco',
            archivo_original  VARCHAR(255) DEFAULT NULL COMMENT 'Nombre original del archivo',
            archivo_tipo      VARCHAR(60) DEFAULT NULL COMMENT 'MIME type',
            creado_en         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_conv (id_conversacion),
            INDEX idx_usuario (id_usuario),
            INDEX idx_fecha (creado_en)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)


def get_conversaciones_usuario(id_usuario):
    """Lista de conversaciones del usuario con ultimo mensaje y conteo no-leidos."""
    return query("""
        SELECT c.id, c.titulo, c.es_grupo,
               m.contenido AS ultimo_mensaje, m.creado_en AS ultimo_fecha,
               mu.nombre AS ultimo_autor,
               (SELECT COUNT(*) FROM chat_mensajes cm
                WHERE cm.id_conversacion = c.id
                  AND cm.creado_en > COALESCE(p.ultimo_leido, '2000-01-01')
                  AND cm.id_usuario != %s) AS no_leidos,
               CASE WHEN c.es_grupo = 0 THEN
                 (SELECT u2.nombre FROM chat_participantes p2
                  JOIN usuarios u2 ON u2.id = p2.id_usuario
                  WHERE p2.id_conversacion = c.id AND p2.id_usuario != %s LIMIT 1)
               ELSE NULL END AS nombre_contacto
        FROM chat_conversaciones c
        JOIN chat_participantes p ON p.id_conversacion = c.id AND p.id_usuario = %s
        LEFT JOIN chat_mensajes m ON m.id = (
            SELECT MAX(id) FROM chat_mensajes WHERE id_conversacion = c.id
        )
        LEFT JOIN usuarios mu ON mu.id = m.id_usuario
        ORDER BY COALESCE(m.creado_en, c.creado_en) DESC
    """, (id_usuario, id_usuario, id_usuario))


def get_o_crear_conversacion_directa(id_usuario1, id_usuario2):
    """Obtiene una conversacion 1-a-1 existente entre dos usuarios, o la crea."""
    existente = query("""
        SELECT c.id FROM chat_conversaciones c
        JOIN chat_participantes p1 ON p1.id_conversacion = c.id AND p1.id_usuario = %s
        JOIN chat_participantes p2 ON p2.id_conversacion = c.id AND p2.id_usuario = %s
        WHERE c.es_grupo = 0
        LIMIT 1
    """, (id_usuario1, id_usuario2), one=True)
    if existente:
        return existente["id"]
    # Crear nueva conversacion
    cid = execute("INSERT INTO chat_conversaciones (es_grupo, creado_por) VALUES (0, %s)", (id_usuario1,))
    execute("INSERT INTO chat_participantes (id_conversacion, id_usuario) VALUES (%s, %s)", (cid, id_usuario1))
    execute("INSERT INTO chat_participantes (id_conversacion, id_usuario) VALUES (%s, %s)", (cid, id_usuario2))
    return cid


def crear_conversacion_grupo(titulo, id_usuarios, creado_por):
    """Crea una conversacion grupal con multiples participantes."""
    cid = execute("INSERT INTO chat_conversaciones (titulo, es_grupo, creado_por) VALUES (%s, 1, %s)",
                  (titulo, creado_por))
    for uid in id_usuarios:
        execute("INSERT INTO chat_participantes (id_conversacion, id_usuario) VALUES (%s, %s)", (cid, uid))
    return cid


def get_mensajes_conversacion(id_conversacion, limit=50, offset=0):
    """Obtiene mensajes de una conversacion, mas recientes primero."""
    return query("""
        SELECT m.*, COALESCE(u.nombre, 'Correo entrante') AS autor_nombre
        FROM chat_mensajes m
        LEFT JOIN usuarios u ON u.id = m.id_usuario
        WHERE m.id_conversacion = %s
        ORDER BY m.creado_en DESC
        LIMIT %s OFFSET %s
    """, (id_conversacion, limit, offset))


def enviar_mensaje(id_conversacion, id_usuario, contenido, archivo=None, archivo_original=None, archivo_tipo=None):
    """Envia un mensaje (texto y/o archivo) a una conversacion."""
    if archivo:
        return execute("""
            INSERT INTO chat_mensajes (id_conversacion, id_usuario, contenido, archivo, archivo_original, archivo_tipo)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (id_conversacion, id_usuario, contenido or None, archivo, archivo_original, archivo_tipo))
    else:
        return execute("""
            INSERT INTO chat_mensajes (id_conversacion, id_usuario, contenido)
            VALUES (%s, %s, %s)
        """, (id_conversacion, id_usuario, contenido or None))



def marcar_conversacion_leida(id_conversacion, id_usuario):
    """Marca todos los mensajes como leidos para un usuario."""
    execute("""
        UPDATE chat_participantes SET ultimo_leido = NOW()
        WHERE id_conversacion = %s AND id_usuario = %s
    """, (id_conversacion, id_usuario))


def es_participante(id_conversacion, id_usuario):
    """Verifica si un usuario es participante de una conversacion."""
    r = query("SELECT id FROM chat_participantes WHERE id_conversacion=%s AND id_usuario=%s",
              (id_conversacion, id_usuario), one=True)
    return bool(r)


def get_total_no_leidos(id_usuario):
    """Total de mensajes no leidos del usuario (para badge en sidebar)."""
    r = query("""
        SELECT COALESCE(SUM(sub.no_leidos), 0) AS total
        FROM (
            SELECT (SELECT COUNT(*) FROM chat_mensajes cm
                    WHERE cm.id_conversacion = p.id_conversacion
                      AND cm.creado_en > COALESCE(p.ultimo_leido, '2000-01-01')
                      AND cm.id_usuario != %s) AS no_leidos
            FROM chat_participantes p WHERE p.id_usuario = %s
        ) sub
    """, (id_usuario, id_usuario), one=True)
    return int(r["total"]) if r else 0


def get_participantes_conversacion(id_conversacion):
    """Lista de participantes de una conversacion."""
    return query("""
        SELECT u.id, u.nombre, u.email, u.rol
        FROM chat_participantes p
        JOIN usuarios u ON u.id = p.id_usuario
        WHERE p.id_conversacion = %s
        ORDER BY u.nombre
    """, (id_conversacion,))


# ══════════════════════════════════════════════════════════════════
#  PRESUPUESTO — GASTOS PREVISTOS (resumen ejecutivo por categoría)
#  Categorías: Aportaciones, Materiales, Mano de obra, Seguro e impuestos,
#              Equipo de seguridad, Herramienta y equipo, Indirectos
#  "Real" se calcula de requisiciones autorizadas + OC autorizadas
#  "Gastado" se calcula de caja chica aprobada + pagos efectuados
# ══════════════════════════════════════════════════════════════════

CATEGORIAS_GASTOS_PREVISTOS = [
    "APORTACIONES",
    "MATERIALES",
    "MANO DE OBRA",
    "SEGURO E IMPUESTOS",
    "EQUIPO DE SEGURIDAD",
    "HERRAMIENTA Y EQUIPO",
    "INDIRECTOS",
]

def _crear_tabla_gastos_previstos():
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS presupuesto_gastos_previstos (
            id INT AUTO_INCREMENT PRIMARY KEY,
            id_obra INT NOT NULL,
            categoria VARCHAR(60) NOT NULL,
            monto_presupuestado DECIMAL(14,2) DEFAULT 0,
            activo TINYINT(1) NOT NULL DEFAULT 1,
            creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            actualizado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_obra (id_obra),
            UNIQUE KEY uq_obra_cat (id_obra, categoria)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

try:
    _crear_tabla_gastos_previstos()
except Exception:
    pass


def get_gastos_previstos(id_obra):
    """Obtiene las categorías de gastos previstos de una obra con sus montos presupuestados."""
    return query("""
        SELECT * FROM presupuesto_gastos_previstos
        WHERE id_obra = %s AND activo = 1
        ORDER BY FIELD(categoria, 'APORTACIONES','MATERIALES','MANO DE OBRA',
                       'SEGURO E IMPUESTOS','EQUIPO DE SEGURIDAD','HERRAMIENTA Y EQUIPO','INDIRECTOS'), categoria
    """, (id_obra,))


def guardar_gastos_previstos(id_obra, categorias_montos):
    """Guarda/actualiza los montos presupuestados por categoría.
    categorias_montos: dict {categoria: monto_presupuestado}"""
    for cat, monto in categorias_montos.items():
        cat = cat.strip().upper()
        monto = float(monto or 0)
        existing = query(
            "SELECT id FROM presupuesto_gastos_previstos WHERE id_obra=%s AND categoria=%s",
            (id_obra, cat), one=True)
        if existing:
            execute("UPDATE presupuesto_gastos_previstos SET monto_presupuestado=%s, activo=1 WHERE id=%s",
                    (monto, existing["id"]))
        else:
            execute("""INSERT INTO presupuesto_gastos_previstos (id_obra, categoria, monto_presupuestado)
                       VALUES (%s, %s, %s)""", (id_obra, cat, monto))


def inicializar_gastos_previstos(id_obra):
    """Inicializa las 7 categorías base para una obra (con monto 0)."""
    for cat in CATEGORIAS_GASTOS_PREVISTOS:
        existing = query(
            "SELECT id FROM presupuesto_gastos_previstos WHERE id_obra=%s AND categoria=%s",
            (id_obra, cat), one=True)
        if not existing:
            execute("""INSERT INTO presupuesto_gastos_previstos (id_obra, categoria, monto_presupuestado)
                       VALUES (%s, %s, 0)""", (id_obra, cat))


def _mapear_categoria_partida(categoria_partida):
    """Mapea la categoría de una partida de requisición a la categoría de gastos previstos."""
    cat = (categoria_partida or "").upper().strip()
    mapa = {
        "MATERIALES": "MATERIALES",
        "MATERIAL": "MATERIALES",
        "MANO DE OBRA": "MANO DE OBRA",
        "NOMINA": "MANO DE OBRA",
        "NÓMINA": "MANO DE OBRA",
        "HERRAMIENTA": "HERRAMIENTA Y EQUIPO",
        "HERRAMIENTA Y EQUIPO": "HERRAMIENTA Y EQUIPO",
        "EQUIPOS": "HERRAMIENTA Y EQUIPO",
        "EQUIPO DE SEGURIDAD": "EQUIPO DE SEGURIDAD",
        "SEGURIDAD": "EQUIPO DE SEGURIDAD",
        "SEGUROS": "SEGURO E IMPUESTOS",
        "SEGURO E IMPUESTOS": "SEGURO E IMPUESTOS",
        "IMPUESTOS": "SEGURO E IMPUESTOS",
        "INDIRECTOS": "INDIRECTOS",
        "APORTACIONES": "APORTACIONES",
    }
    return mapa.get(cat, "INDIRECTOS")


def _mapear_tipo_pedido_oc(tipo_pedido):
    """Mapea tipo_pedido de OC a categoría de gastos previstos."""
    tp = (tipo_pedido or "").upper().strip()
    mapa = {
        "MATERIALES": "MATERIALES",
        "MATERIAL": "MATERIALES",
        "HERRAMIENTA": "HERRAMIENTA Y EQUIPO",
        "HERRAMIENTA Y EQUIPO": "HERRAMIENTA Y EQUIPO",
        "EQUIPO": "HERRAMIENTA Y EQUIPO",
        "SEGURIDAD": "EQUIPO DE SEGURIDAD",
        "EQUIPO DE SEGURIDAD": "EQUIPO DE SEGURIDAD",
        "MANO DE OBRA": "MANO DE OBRA",
        "SERVICIOS": "INDIRECTOS",
    }
    return mapa.get(tp, "MATERIALES")


def calcular_real_gastos_previstos(id_obra):
    """Calcula el monto REAL (comprometido) por categoría:
    - Requisiciones aprobadas: suma monto_autorizado por categoría de partida
    - OC autorizadas: suma total por tipo_pedido
    Retorna dict {categoria: monto_real}
    """
    resultado = {cat: 0.0 for cat in CATEGORIAS_GASTOS_PREVISTOS}

    # Requisiciones aprobadas → monto_autorizado por categoría
    reqs = query("""
        SELECT rp.categoria, SUM(rp.monto_autorizado) AS total
        FROM requisicion_partidas rp
        JOIN requisiciones r ON r.id = rp.id_requisicion
        WHERE r.id_obra = %s AND r.estatus IN ('aprobado','enviado')
        GROUP BY rp.categoria
    """, (id_obra,))
    for row in (reqs or []):
        cat_mapeada = _mapear_categoria_partida(row["categoria"])
        resultado[cat_mapeada] += float(row["total"] or 0)

    # OC autorizadas → total por tipo_pedido
    ocs = query("""
        SELECT tipo_pedido, SUM(total) AS total
        FROM ordenes_compra
        WHERE id_obra = %s AND estatus = 'autorizado'
        GROUP BY tipo_pedido
    """, (id_obra,))
    for row in (ocs or []):
        cat_mapeada = _mapear_tipo_pedido_oc(row["tipo_pedido"])
        resultado[cat_mapeada] += float(row["total"] or 0)

    return resultado


def calcular_gastado_gastos_previstos(id_obra):
    """Calcula el monto GASTADO (ejercido/pagado) por categoría:
    - Caja chica aprobada → se asigna a INDIRECTOS (gastos menores operativos)
    - Requisiciones con partidas pagadas (monto_autorizado donde estatus req=aprobado)
    - OC con estatus autorizado (ya comprometido = ejercido)
    Retorna dict {categoria: monto_gastado}
    """
    resultado = {cat: 0.0 for cat in CATEGORIAS_GASTOS_PREVISTOS}

    # Caja chica aprobada → todo a INDIRECTOS
    cc = query("""
        SELECT COALESCE(SUM(p.total), 0) AS total_cc
        FROM caja_chica_partidas p
        JOIN caja_chica_comprobaciones c ON c.id = p.id_comprobacion
        WHERE c.id_obra = %s AND c.estatus = 'aprobado'
    """, (id_obra,), one=True)
    resultado["INDIRECTOS"] += float((cc or {}).get("total_cc") or 0)

    # Requisiciones aprobadas con monto_autorizado > 0 → distribuir por categoría
    reqs = query("""
        SELECT rp.categoria, SUM(rp.monto_autorizado) AS total
        FROM requisicion_partidas rp
        JOIN requisiciones r ON r.id = rp.id_requisicion
        WHERE r.id_obra = %s AND r.estatus = 'aprobado'
        GROUP BY rp.categoria
    """, (id_obra,))
    for row in (reqs or []):
        cat_mapeada = _mapear_categoria_partida(row["categoria"])
        resultado[cat_mapeada] += float(row["total"] or 0)

    return resultado


def get_resumen_gastos_previstos(id_obra):
    """Retorna el resumen completo para la vista:
    Lista de dicts con {categoria, presupuestado, real, gastado, pct_gastado}"""
    previstos = get_gastos_previstos(id_obra)
    real = calcular_real_gastos_previstos(id_obra)
    gastado = calcular_gastado_gastos_previstos(id_obra)

    # Si no hay registros, inicializar
    if not previstos:
        inicializar_gastos_previstos(id_obra)
        previstos = get_gastos_previstos(id_obra)

    resultado = []
    for row in previstos:
        cat = row["categoria"]
        presup = float(row["monto_presupuestado"] or 0)
        r = real.get(cat, 0.0)
        g = gastado.get(cat, 0.0)
        pct = round((g / presup) * 100, 1) if presup > 0 else 0.0
        resultado.append({
            "id": row["id"],
            "categoria": cat,
            "presupuestado": presup,
            "real": r,
            "gastado": g,
            "pct_gastado": pct,
        })

    return resultado


def importar_gastos_previstos_excel(id_obra, filas):
    """Importa gastos previstos desde Excel.
    filas: lista de dicts con keys 'categoria' y 'monto_presupuestado'
    Retorna cantidad procesada."""
    count = 0
    for fila in filas:
        cat = (fila.get("categoria") or "").strip().upper()
        monto = float(fila.get("monto_presupuestado") or 0)
        if not cat:
            continue
        guardar_gastos_previstos(id_obra, {cat: monto})
        count += 1
    return count


# ══════════════════════════════════════════════════════════════════
#  INSUMOS DE LA PROPUESTA (Concurso/Licitación)
#  Catálogo de lo concursado + columnas dinámicas de requisiciones
# ══════════════════════════════════════════════════════════════════

def _crear_tablas_insumos_propuesta():
    # Catálogo principal: lo que se concursó
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS insumos_propuesta (
            id INT AUTO_INCREMENT PRIMARY KEY,
            concepto VARCHAR(500) NOT NULL,
            unidad VARCHAR(30) NOT NULL DEFAULT 'pza',
            cantidad_concursada DECIMAL(14,3) DEFAULT 0,
            precio_concursado DECIMAL(14,2) DEFAULT 0,
            importe_concursado DECIMAL(14,2) DEFAULT 0,
            observaciones VARCHAR(500) DEFAULT NULL,
            activo TINYINT(1) NOT NULL DEFAULT 1,
            creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_concepto (concepto(100))
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # Requisiciones dinámicas: cada "columna" de requisición por insumo
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS insumos_propuesta_requisiciones (
            id INT AUTO_INCREMENT PRIMARY KEY,
            id_insumo INT NOT NULL,
            numero_requisicion INT NOT NULL DEFAULT 1 COMMENT 'Req 1, Req 2, etc.',
            cantidad DECIMAL(14,3) DEFAULT 0,
            precio DECIMAL(14,2) DEFAULT 0,
            proveedor VARCHAR(200) DEFAULT NULL,
            fecha DATE DEFAULT NULL,
            observaciones VARCHAR(300) DEFAULT NULL,
            creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_insumo (id_insumo),
            INDEX idx_num_req (numero_requisicion)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

try:
    _crear_tablas_insumos_propuesta()
except Exception:
    pass


def get_insumos_propuesta(search=None):
    """Lista todos los insumos del concurso activos."""
    sql = "SELECT * FROM insumos_propuesta WHERE activo=1"
    params = []
    if search:
        sql += " AND (concepto LIKE %s OR unidad LIKE %s)"
        params += [f"%{search}%", f"%{search}%"]
    sql += " ORDER BY id"
    return query(sql, params)


def get_insumo_propuesta(insumo_id):
    return query("SELECT * FROM insumos_propuesta WHERE id=%s", (insumo_id,), one=True)


def crear_insumo_propuesta(d):
    """Crea un insumo del concurso."""
    cantidad = float(d.get("cantidad_concursada") or 0)
    precio = float(d.get("precio_concursado") or 0)
    importe = cantidad * precio if not d.get("importe_concursado") else float(d["importe_concursado"])
    return execute("""
        INSERT INTO insumos_propuesta (concepto, unidad, cantidad_concursada, precio_concursado, importe_concursado, observaciones)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (d["concepto"], d.get("unidad", "pza"), cantidad, precio, importe, d.get("observaciones")))


def actualizar_insumo_propuesta(insumo_id, d):
    """Actualiza un insumo del concurso."""
    cantidad = float(d.get("cantidad_concursada") or 0)
    precio = float(d.get("precio_concursado") or 0)
    importe = cantidad * precio if not d.get("importe_concursado") else float(d["importe_concursado"])
    execute("""
        UPDATE insumos_propuesta SET concepto=%s, unidad=%s, cantidad_concursada=%s,
               precio_concursado=%s, importe_concursado=%s, observaciones=%s
        WHERE id=%s
    """, (d["concepto"], d.get("unidad", "pza"), cantidad, precio, importe, d.get("observaciones"), insumo_id))


def eliminar_insumo_propuesta(insumo_id):
    """Desactiva un insumo (soft delete)."""
    execute("UPDATE insumos_propuesta SET activo=0 WHERE id=%s", (insumo_id,))


def get_requisiciones_insumos(insumo_ids=None):
    """Obtiene todas las requisiciones de insumos. Si se pasan ids, filtra por esos insumos."""
    sql = "SELECT * FROM insumos_propuesta_requisiciones"
    params = []
    if insumo_ids:
        placeholders = ",".join(["%s"] * len(insumo_ids))
        sql += f" WHERE id_insumo IN ({placeholders})"
        params = list(insumo_ids)
    sql += " ORDER BY id_insumo, numero_requisicion"
    return query(sql, params)


def get_max_numero_requisicion():
    """Obtiene el número de requisición más alto registrado."""
    r = query("SELECT MAX(numero_requisicion) AS mx FROM insumos_propuesta_requisiciones", one=True)
    return (r or {}).get("mx") or 0


def agregar_requisicion_insumo(id_insumo, numero_requisicion, cantidad, precio, proveedor=None, fecha=None, observaciones=None):
    """Agrega una línea de requisición a un insumo."""
    return execute("""
        INSERT INTO insumos_propuesta_requisiciones
            (id_insumo, numero_requisicion, cantidad, precio, proveedor, fecha, observaciones)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (id_insumo, numero_requisicion, float(cantidad or 0), float(precio or 0), proveedor, fecha, observaciones))


def actualizar_requisicion_insumo(req_id, d):
    """Actualiza una línea de requisición."""
    execute("""
        UPDATE insumos_propuesta_requisiciones SET
            cantidad=%s, precio=%s, proveedor=%s, fecha=%s, observaciones=%s
        WHERE id=%s
    """, (float(d.get("cantidad") or 0), float(d.get("precio") or 0),
          d.get("proveedor"), d.get("fecha"), d.get("observaciones"), req_id))


def eliminar_requisicion_insumo(req_id):
    """Elimina una línea de requisición."""
    execute("DELETE FROM insumos_propuesta_requisiciones WHERE id=%s", (req_id,))


def get_resumen_insumos_propuesta():
    """Retorna el resumen completo para la vista:
    Lista de insumos con sus requisiciones agrupadas por número."""
    insumos = get_insumos_propuesta()
    if not insumos:
        return [], 0

    ids = [i["id"] for i in insumos]
    reqs = get_requisiciones_insumos(ids)

    # Agrupar requisiciones por insumo
    reqs_por_insumo = {}
    max_num = 0
    for r in reqs:
        iid = r["id_insumo"]
        if iid not in reqs_por_insumo:
            reqs_por_insumo[iid] = {}
        num = r["numero_requisicion"]
        reqs_por_insumo[iid][num] = r
        if num > max_num:
            max_num = num

    # Construir resultado
    resultado = []
    for ins in insumos:
        item = {
            "id": ins["id"],
            "concepto": ins["concepto"],
            "unidad": ins["unidad"],
            "cantidad_concursada": float(ins["cantidad_concursada"] or 0),
            "precio_concursado": float(ins["precio_concursado"] or 0),
            "importe_concursado": float(ins["importe_concursado"] or 0),
            "observaciones": ins["observaciones"],
            "requisiciones": reqs_por_insumo.get(ins["id"], {}),
        }
        resultado.append(item)

    return resultado, max_num


def importar_insumos_propuesta_excel(wb):
    """Importa insumos de la propuesta desde un workbook de openpyxl.
    Columnas esperadas: A=Concepto, B=Unidad, C=Cantidad, D=Precio, E=Importe (opcional)
    Retorna cantidad de registros creados."""
    ws = wb.worksheets[0]
    count = 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        concepto = str(row[0] or "").strip() if row[0] else ""
        if not concepto:
            continue
        unidad = str(row[1] or "pza").strip() if len(row) > 1 and row[1] else "pza"
        cantidad = float(row[2] or 0) if len(row) > 2 and row[2] else 0
        precio = float(row[3] or 0) if len(row) > 3 and row[3] else 0
        importe = float(row[4] or 0) if len(row) > 4 and row[4] else cantidad * precio
        crear_insumo_propuesta({
            "concepto": concepto,
            "unidad": unidad,
            "cantidad_concursada": cantidad,
            "precio_concursado": precio,
            "importe_concursado": importe,
        })
        count += 1
    return count


# ══════════════════════════════════════════════════════════════════
#  PROGRAMA DE EJECUCIÓN DE MANO DE OBRA
#  Cronograma semanal por concepto/partida
# ══════════════════════════════════════════════════════════════════

def _crear_tablas_programa_mano_obra():
    # Catálogo de conceptos/partidas
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS programa_mano_obra (
            id INT AUTO_INCREMENT PRIMARY KEY,
            partida VARCHAR(30) DEFAULT NULL,
            trabajo VARCHAR(200) DEFAULT NULL,
            concepto VARCHAR(500) NOT NULL,
            unidad VARCHAR(30) NOT NULL DEFAULT 'pza',
            observaciones VARCHAR(500) DEFAULT NULL,
            activo TINYINT(1) NOT NULL DEFAULT 1,
            creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_partida (partida),
            INDEX idx_concepto (concepto(100))
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # Valores semanales: cada registro es una celda (concepto × semana)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS programa_mano_obra_semanas (
            id INT AUTO_INCREMENT PRIMARY KEY,
            id_concepto INT NOT NULL,
            numero_semana INT NOT NULL DEFAULT 1,
            cantidad DECIMAL(14,3) DEFAULT 0,
            creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_concepto (id_concepto),
            INDEX idx_semana (numero_semana),
            UNIQUE KEY uq_concepto_semana (id_concepto, numero_semana)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

try:
    _crear_tablas_programa_mano_obra()
except Exception:
    pass


def get_programa_mano_obra(search=None):
    """Lista todos los conceptos del programa activos."""
    sql = "SELECT * FROM programa_mano_obra WHERE activo=1"
    params = []
    if search:
        sql += " AND (concepto LIKE %s OR partida LIKE %s OR trabajo LIKE %s)"
        params += [f"%{search}%", f"%{search}%", f"%{search}%"]
    sql += " ORDER BY partida, id"
    return query(sql, params)


def get_concepto_mano_obra(cid):
    return query("SELECT * FROM programa_mano_obra WHERE id=%s", (cid,), one=True)


def crear_concepto_mano_obra(d):
    """Crea un concepto en el programa de mano de obra."""
    return execute("""
        INSERT INTO programa_mano_obra (partida, trabajo, concepto, unidad, observaciones)
        VALUES (%s, %s, %s, %s, %s)
    """, (d.get("partida"), d.get("trabajo"), d["concepto"], d.get("unidad", "pza"), d.get("observaciones")))


def actualizar_concepto_mano_obra(cid, d):
    """Actualiza un concepto existente."""
    execute("""
        UPDATE programa_mano_obra SET partida=%s, trabajo=%s, concepto=%s, unidad=%s, observaciones=%s
        WHERE id=%s
    """, (d.get("partida"), d.get("trabajo"), d["concepto"], d.get("unidad", "pza"), d.get("observaciones"), cid))


def eliminar_concepto_mano_obra(cid):
    """Desactiva un concepto (soft delete)."""
    execute("UPDATE programa_mano_obra SET activo=0 WHERE id=%s", (cid,))


def get_semanas_mano_obra(concepto_ids=None):
    """Obtiene todos los valores semanales."""
    sql = "SELECT * FROM programa_mano_obra_semanas"
    params = []
    if concepto_ids:
        placeholders = ",".join(["%s"] * len(concepto_ids))
        sql += f" WHERE id_concepto IN ({placeholders})"
        params = list(concepto_ids)
    sql += " ORDER BY id_concepto, numero_semana"
    return query(sql, params)


def get_max_semana_mano_obra():
    """Obtiene el número de semana más alto registrado."""
    r = query("SELECT MAX(numero_semana) AS mx FROM programa_mano_obra_semanas", one=True)
    return (r or {}).get("mx") or 0


def guardar_semana_mano_obra(id_concepto, numero_semana, cantidad):
    """Guarda o actualiza el valor de una celda (concepto × semana)."""
    cantidad = float(cantidad or 0)
    existing = query(
        "SELECT id FROM programa_mano_obra_semanas WHERE id_concepto=%s AND numero_semana=%s",
        (id_concepto, numero_semana), one=True)
    if existing:
        execute("UPDATE programa_mano_obra_semanas SET cantidad=%s WHERE id=%s",
                (cantidad, existing["id"]))
    else:
        execute("""INSERT INTO programa_mano_obra_semanas (id_concepto, numero_semana, cantidad)
                   VALUES (%s, %s, %s)""", (id_concepto, numero_semana, cantidad))


def guardar_programa_semanas_batch(datos_semanas):
    """Guarda múltiples celdas de semana.
    datos_semanas: lista de dicts {id_concepto, numero_semana, cantidad}"""
    for d in datos_semanas:
        guardar_semana_mano_obra(d["id_concepto"], d["numero_semana"], d["cantidad"])


def get_resumen_programa_mano_obra():
    """Retorna el resumen completo para la vista:
    Lista de conceptos con sus semanas y totales."""
    conceptos = get_programa_mano_obra()
    if not conceptos:
        return [], 0

    ids = [c["id"] for c in conceptos]
    semanas = get_semanas_mano_obra(ids)

    # Agrupar semanas por concepto
    semanas_por_concepto = {}
    max_sem = 0
    for s in semanas:
        cid = s["id_concepto"]
        if cid not in semanas_por_concepto:
            semanas_por_concepto[cid] = {}
        num = s["numero_semana"]
        semanas_por_concepto[cid][num] = float(s["cantidad"] or 0)
        if num > max_sem:
            max_sem = num

    # Construir resultado
    resultado = []
    for c in conceptos:
        sems = semanas_por_concepto.get(c["id"], {})
        total = sum(sems.values())
        item = {
            "id": c["id"],
            "partida": c["partida"] or "",
            "trabajo": c["trabajo"] or "",
            "concepto": c["concepto"],
            "unidad": c["unidad"],
            "semanas": sems,
            "total": total,
        }
        resultado.append(item)

    return resultado, max_sem


def importar_programa_mano_obra_excel(wb):
    """Importa programa de mano de obra desde Excel.
    Columnas: A=Partida, B=Trabajo, C=Concepto, D=Unidad, E en adelante=Semana 1, 2, 3...
    Retorna cantidad de registros procesados."""
    ws = wb.worksheets[0]
    count = 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not row[2]:  # Concepto obligatorio (columna C)
            continue
        partida = str(row[0] or "").strip() if row[0] else ""
        trabajo = str(row[1] or "").strip() if len(row) > 1 and row[1] else ""
        concepto = str(row[2]).strip()
        unidad = str(row[3] or "pza").strip() if len(row) > 3 and row[3] else "pza"

        # Crear concepto
        cid = crear_concepto_mano_obra({
            "partida": partida, "trabajo": trabajo,
            "concepto": concepto, "unidad": unidad,
        })

        # Semanas (columna E en adelante = índice 4+)
        for i in range(4, len(row)):
            val = float(row[i] or 0) if row[i] else 0
            if val > 0:
                guardar_semana_mano_obra(cid, i - 3, val)  # Semana 1 = índice 4

        count += 1
    return count


# ══════════════════════════════════════════════════════════════════
#  ANÁLISIS FINANCIERO (Flujo de Efectivo Semanal)
#  Egresos auto-calculados + Ingresos manuales, 52 semanas
# ══════════════════════════════════════════════════════════════════

def _crear_tablas_analisis_financiero():
    # Configuración por obra
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS analisis_financiero_config (
            id INT AUTO_INCREMENT PRIMARY KEY,
            id_obra INT NOT NULL,
            costo_contrato DECIMAL(14,2) DEFAULT 0 COMMENT 'Costo del contrato s/IVA',
            pct_anticipo DECIMAL(5,2) DEFAULT 20.00,
            pct_fondo_garantia DECIMAL(5,2) DEFAULT 10.00,
            pct_retencion_extra DECIMAL(5,2) DEFAULT 2.00 COMMENT 'SUTERM u otra retención',
            label_retencion_extra VARCHAR(60) DEFAULT 'Retención 2% SUTERM',
            fecha_inicio DATE DEFAULT NULL COMMENT 'Inicio semana 1',
            semanas_proyecto INT DEFAULT 52,
            creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            actualizado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_obra (id_obra)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # Ingresos semanales (captura manual)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS analisis_financiero_ingresos (
            id INT AUTO_INCREMENT PRIMARY KEY,
            id_obra INT NOT NULL,
            numero_semana INT NOT NULL,
            inversion DECIMAL(14,2) DEFAULT 0,
            anticipo DECIMAL(14,2) DEFAULT 0,
            importe_estimado DECIMAL(14,2) DEFAULT 0,
            devolucion_fondo_garantia DECIMAL(14,2) DEFAULT 0,
            devolucion_apoyos DECIMAL(14,2) DEFAULT 0,
            amortizacion_anticipo DECIMAL(14,2) DEFAULT 0,
            retencion_fondo_garantia DECIMAL(14,2) DEFAULT 0,
            retencion_extra DECIMAL(14,2) DEFAULT 0,
            importe_liquido_pagado DECIMAL(14,2) DEFAULT 0,
            creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_obra_sem (id_obra, numero_semana),
            INDEX idx_obra (id_obra)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # Egresos manuales adicionales (nómina, indirectos campo/oficina, IMSS, equipo)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS analisis_financiero_egresos (
            id INT AUTO_INCREMENT PRIMARY KEY,
            id_obra INT NOT NULL,
            numero_semana INT NOT NULL,
            materiales DECIMAL(14,2) DEFAULT 0,
            mano_obra DECIMAL(14,2) DEFAULT 0,
            pagos_imss DECIMAL(14,2) DEFAULT 0,
            equipo_herramienta DECIMAL(14,2) DEFAULT 0,
            nomina DECIMAL(14,2) DEFAULT 0,
            indirectos_campo DECIMAL(14,2) DEFAULT 0,
            indirectos_oficina DECIMAL(14,2) DEFAULT 0,
            creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_obra_sem (id_obra, numero_semana),
            INDEX idx_obra (id_obra)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

try:
    _crear_tablas_analisis_financiero()
except Exception:
    pass


# ══════════════════════════════════════════════════════════════════
#  ANÁLISIS FINANCIERO — Rubros y mapeo de códigos de costo
# ══════════════════════════════════════════════════════════════════

def _init_tablas_analisis_rubros():
    """Crea las tablas analisis_rubros y codigo_rubro si no existen y las puebla."""
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS analisis_rubros (
            id      INT AUTO_INCREMENT PRIMARY KEY,
            clave   VARCHAR(40) NOT NULL UNIQUE,
            etiqueta VARCHAR(120) NOT NULL,
            seccion ENUM('DIRECTO','INDIRECTO') NOT NULL,
            orden   SMALLINT NOT NULL DEFAULT 0,
            activo  TINYINT(1) NOT NULL DEFAULT 1
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS codigo_rubro (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            prefijo     VARCHAR(30) NOT NULL UNIQUE,
            rubro_clave VARCHAR(40) NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # Semilla rubros (solo si la tabla está vacía)
    if not query("SELECT 1 FROM analisis_rubros LIMIT 1"):
        rubros = [
            ("equipo",            "Equipo, Herramienta y Maquinaria", "DIRECTO",   1),
            ("combustibles",      "Combustibles",                     "DIRECTO",   2),
            ("materiales",        "Materiales",                       "DIRECTO",   3),
            ("subcontratos",      "Subcontratos",                     "DIRECTO",   4),
            ("mano_obra",         "Mano de Obra",                     "DIRECTO",   5),
            ("acarreos",          "Acarreos",                         "DIRECTO",   6),
            ("pagos_imss",        "Pagos IMSS",                       "INDIRECTO", 1),
            ("nomina",            "Costo de Nómina",                  "INDIRECTO", 2),
            ("indirectos_campo",  "Indirectos de Campo",              "INDIRECTO", 3),
            ("indirectos_oficina","Indirectos de Oficina",            "INDIRECTO", 4),
            ("sin_clasificar",    "Sin clasificar",                   "INDIRECTO", 99),
        ]
        for clave, etiqueta, seccion, orden in rubros:
            execute("INSERT IGNORE INTO analisis_rubros (clave,etiqueta,seccion,orden) VALUES (%s,%s,%s,%s)",
                    (clave, etiqueta, seccion, orden))
    # Semilla prefijos (solo si la tabla está vacía)
    if not query("SELECT 1 FROM codigo_rubro LIMIT 1"):
        prefijos = [
            ("1",    "equipo"),
            ("2",    "combustibles"),
            ("3",    "materiales"),
            ("4",    "subcontratos"),
            ("4-06", "mano_obra"),         # sobreescribe familia 4
            ("5",    "acarreos"),
            ("6-01", "pagos_imss"),
            ("6-02", "pagos_imss"),
            ("6-03", "nomina"),
            ("6-04", "nomina"),
            ("7",    "indirectos_campo"),  # fallback familia 7
            ("7-03", "indirectos_oficina"),
            ("7-04", "indirectos_oficina"),
            ("7-05", "indirectos_oficina"),
            ("7-10", "indirectos_oficina"),
            ("7-17", "indirectos_oficina"),
            ("7-19", "indirectos_oficina"),
        ]
        for prefijo, rubro_clave in prefijos:
            execute("INSERT IGNORE INTO codigo_rubro (prefijo,rubro_clave) VALUES (%s,%s)",
                    (prefijo, rubro_clave))

try:
    _init_tablas_analisis_rubros()
except Exception as _e:
    import sys
    print(f"[WARN] _init_tablas_analisis_rubros: {_e}", file=sys.stderr)


def get_analisis_rubros():
    """Devuelve los rubros activos ordenados por sección y orden."""
    return query("SELECT * FROM analisis_rubros WHERE activo=1 ORDER BY seccion, orden")


def get_codigo_rubro_map():
    """Devuelve dict {prefijo: rubro_clave} ordenado de más largo a más corto
    para que resolver_rubro encuentre el prefijo más específico primero."""
    filas = query("SELECT prefijo, rubro_clave FROM codigo_rubro ORDER BY LENGTH(prefijo) DESC")
    return {f["prefijo"]: f["rubro_clave"] for f in (filas or [])}


def resolver_rubro(codigo_cc, mapa):
    """Dado un código de costo (ej. '4-06-001') y el mapa de prefijos,
    devuelve la clave de rubro por el prefijo más largo que coincida.
    Si no hay coincidencia retorna 'sin_clasificar'."""
    if not codigo_cc:
        return "sin_clasificar"
    codigo_cc = str(codigo_cc).strip()
    # El mapa ya viene ordenado de más largo a más corto
    for prefijo, rubro in mapa.items():
        if codigo_cc == prefijo or codigo_cc.startswith(prefijo + "-"):
            return rubro
    return "sin_clasificar"


def get_egresos_desde_requisiciones(id_obra, cfg=None):
    """Calcula los egresos por semana y rubro desde requisicion_partidas pagadas.

    Retorna:
        egresos_semana  — dict {semana_num: {rubro_clave: float}}
        fuera_de_rango  — dict {rubro_clave: float}  (pagos fuera del calendario)
        sin_fecha       — dict {rubro_clave: float}  (pagos sin fecha_pago)
    """
    if cfg is None:
        cfg = get_analisis_financiero_config(id_obra)

    num_semanas = int(cfg.get("semanas_proyecto") or 52)
    fecha_inicio = cfg.get("fecha_inicio")
    if fecha_inicio and not isinstance(fecha_inicio, date):
        try:
            from datetime import datetime as _dt
            fecha_inicio = _dt.strptime(str(fecha_inicio), "%Y-%m-%d").date()
        except Exception:
            fecha_inicio = None

    mapa = get_codigo_rubro_map()

    # Traer todas las partidas pagadas de la obra
    partidas = query("""
        SELECT
            p.monto_autorizado,
            p.fecha_pago,
            COALESCE(p.id_codigo_costo, r.id_codigo_costo) AS id_cc,
            cc.codigo AS codigo_cc
        FROM requisicion_partidas p
        JOIN requisiciones r ON r.id = p.id_requisicion
        LEFT JOIN codigos_costo cc
               ON cc.id = COALESCE(p.id_codigo_costo, r.id_codigo_costo)
        WHERE r.id_obra = %s
          AND p.estatus_pago = 'pagado'
          AND (p.monto_autorizado IS NOT NULL AND p.monto_autorizado > 0)
    """, (id_obra,))

    egresos_semana = {}   # {semana_num: {rubro_clave: float}}
    fuera_de_rango = {}   # {rubro_clave: float}
    sin_fecha       = {}  # {rubro_clave: float}

    for p in (partidas or []):
        monto  = float(p["monto_autorizado"] or 0)
        codigo = p.get("codigo_cc") or ""
        rubro  = resolver_rubro(codigo, mapa)
        fp     = p.get("fecha_pago")

        if not fp:
            sin_fecha[rubro] = sin_fecha.get(rubro, 0) + monto
            continue

        if fecha_inicio:
            if not isinstance(fp, date):
                try:
                    from datetime import datetime as _dt2
                    fp = _dt2.strptime(str(fp), "%Y-%m-%d").date()
                except Exception:
                    sin_fecha[rubro] = sin_fecha.get(rubro, 0) + monto
                    continue
            semana_num = (fp - fecha_inicio).days // 7 + 1
            if semana_num < 1 or semana_num > num_semanas:
                fuera_de_rango[rubro] = fuera_de_rango.get(rubro, 0) + monto
            else:
                if semana_num not in egresos_semana:
                    egresos_semana[semana_num] = {}
                egresos_semana[semana_num][rubro] = (
                    egresos_semana[semana_num].get(rubro, 0) + monto
                )
        else:
            # Sin fecha_inicio configurada: acumular en semana -1 (fuera de rango)
            fuera_de_rango[rubro] = fuera_de_rango.get(rubro, 0) + monto

    return egresos_semana, fuera_de_rango, sin_fecha


def get_partidas_egreso_celda(id_obra, semana_num, rubro_clave, cfg=None):
    """Devuelve la lista de partidas que componen una celda específica
    (obra + semana + rubro) para el modal de detalle."""
    if cfg is None:
        cfg = get_analisis_financiero_config(id_obra)

    fecha_inicio = cfg.get("fecha_inicio")
    if fecha_inicio and not isinstance(fecha_inicio, date):
        try:
            from datetime import datetime as _dt
            fecha_inicio = _dt.strptime(str(fecha_inicio), "%Y-%m-%d").date()
        except Exception:
            fecha_inicio = None

    num_semanas = int(cfg.get("semanas_proyecto") or 52)
    mapa = get_codigo_rubro_map()

    partidas = query("""
        SELECT
            p.id, p.monto_autorizado, p.fecha_pago, p.concepto, p.proveedor,
            r.semana, r.semana_num AS req_semana_num,
            COALESCE(p.id_codigo_costo, r.id_codigo_costo) AS id_cc,
            cc.codigo AS codigo_cc, cc.descripcion AS desc_cc
        FROM requisicion_partidas p
        JOIN requisiciones r ON r.id = p.id_requisicion
        LEFT JOIN codigos_costo cc
               ON cc.id = COALESCE(p.id_codigo_costo, r.id_codigo_costo)
        WHERE r.id_obra = %s
          AND p.estatus_pago = 'pagado'
          AND (p.monto_autorizado IS NOT NULL AND p.monto_autorizado > 0)
        ORDER BY p.fecha_pago
    """, (id_obra,))

    resultado = []
    for p in (partidas or []):
        codigo = p.get("codigo_cc") or ""
        rubro  = resolver_rubro(codigo, mapa)
        if rubro != rubro_clave:
            continue

        fp = p.get("fecha_pago")
        if not fp:
            if rubro_clave in ("sin_clasificar",) or semana_num == -1:
                resultado.append(p)
            continue

        if fecha_inicio:
            if not isinstance(fp, date):
                try:
                    from datetime import datetime as _dt2
                    fp = _dt2.strptime(str(fp), "%Y-%m-%d").date()
                except Exception:
                    continue
            sn = (fp - fecha_inicio).days // 7 + 1
        else:
            sn = -1  # fuera de rango

        # semana_num == 0 → "fuera de rango"
        if semana_num == 0:
            if sn < 1 or sn > num_semanas:
                resultado.append(p)
        elif sn == semana_num:
            resultado.append(p)

    return resultado


def get_analisis_financiero_config(id_obra):
    """Obtiene o crea la configuración de análisis financiero de una obra."""
    cfg = query("SELECT * FROM analisis_financiero_config WHERE id_obra=%s", (id_obra,), one=True)
    if not cfg:
        execute("""INSERT INTO analisis_financiero_config (id_obra, costo_contrato, pct_anticipo,
                   pct_fondo_garantia, pct_retencion_extra, semanas_proyecto)
                   VALUES (%s, 0, 20, 10, 2, 52)""", (id_obra,))
        cfg = query("SELECT * FROM analisis_financiero_config WHERE id_obra=%s", (id_obra,), one=True)
    return cfg


def guardar_analisis_financiero_config(id_obra, d):
    """Guarda/actualiza la configuración."""
    existing = query("SELECT id FROM analisis_financiero_config WHERE id_obra=%s", (id_obra,), one=True)
    if existing:
        execute("""UPDATE analisis_financiero_config SET
                   costo_contrato=%s, pct_anticipo=%s, pct_fondo_garantia=%s,
                   pct_retencion_extra=%s, label_retencion_extra=%s,
                   fecha_inicio=%s, semanas_proyecto=%s
                   WHERE id_obra=%s""",
                (float(d.get("costo_contrato") or 0), float(d.get("pct_anticipo") or 20),
                 float(d.get("pct_fondo_garantia") or 10), float(d.get("pct_retencion_extra") or 2),
                 d.get("label_retencion_extra") or "Retención 2% SUTERM",
                 d.get("fecha_inicio") or None, int(d.get("semanas_proyecto") or 52), id_obra))
    else:
        execute("""INSERT INTO analisis_financiero_config
                   (id_obra, costo_contrato, pct_anticipo, pct_fondo_garantia, pct_retencion_extra,
                    label_retencion_extra, fecha_inicio, semanas_proyecto)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (id_obra, float(d.get("costo_contrato") or 0), float(d.get("pct_anticipo") or 20),
                 float(d.get("pct_fondo_garantia") or 10), float(d.get("pct_retencion_extra") or 2),
                 d.get("label_retencion_extra") or "Retención 2% SUTERM",
                 d.get("fecha_inicio") or None, int(d.get("semanas_proyecto") or 52)))


def get_egresos_semana(id_obra, numero_semana):
    """Obtiene egresos de una semana."""
    return query("SELECT * FROM analisis_financiero_egresos WHERE id_obra=%s AND numero_semana=%s",
                 (id_obra, numero_semana), one=True)


def get_egresos_todas_semanas(id_obra):
    """Obtiene todos los egresos registrados."""
    rows = query("SELECT * FROM analisis_financiero_egresos WHERE id_obra=%s ORDER BY numero_semana", (id_obra,))
    return {r["numero_semana"]: r for r in (rows or [])}


def guardar_egresos_semana(id_obra, numero_semana, d):
    """Guarda egresos de una semana (upsert)."""
    existing = query("SELECT id FROM analisis_financiero_egresos WHERE id_obra=%s AND numero_semana=%s",
                     (id_obra, numero_semana), one=True)
    vals = (float(d.get("materiales") or 0), float(d.get("mano_obra") or 0),
            float(d.get("pagos_imss") or 0), float(d.get("equipo_herramienta") or 0),
            float(d.get("nomina") or 0), float(d.get("indirectos_campo") or 0),
            float(d.get("indirectos_oficina") or 0))
    if existing:
        execute("""UPDATE analisis_financiero_egresos SET
                   materiales=%s, mano_obra=%s, pagos_imss=%s, equipo_herramienta=%s,
                   nomina=%s, indirectos_campo=%s, indirectos_oficina=%s WHERE id=%s""",
                vals + (existing["id"],))
    else:
        execute("""INSERT INTO analisis_financiero_egresos
                   (id_obra, numero_semana, materiales, mano_obra, pagos_imss,
                    equipo_herramienta, nomina, indirectos_campo, indirectos_oficina)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (id_obra, numero_semana) + vals)


def get_ingresos_semana(id_obra, numero_semana):
    """Obtiene ingresos de una semana."""
    return query("SELECT * FROM analisis_financiero_ingresos WHERE id_obra=%s AND numero_semana=%s",
                 (id_obra, numero_semana), one=True)


def get_ingresos_todas_semanas(id_obra):
    """Obtiene todos los ingresos registrados."""
    rows = query("SELECT * FROM analisis_financiero_ingresos WHERE id_obra=%s ORDER BY numero_semana", (id_obra,))
    return {r["numero_semana"]: r for r in (rows or [])}


def guardar_ingresos_semana(id_obra, numero_semana, d):
    """Guarda ingresos de una semana (upsert)."""
    existing = query("SELECT id FROM analisis_financiero_ingresos WHERE id_obra=%s AND numero_semana=%s",
                     (id_obra, numero_semana), one=True)
    vals = (float(d.get("inversion") or 0), float(d.get("anticipo") or 0),
            float(d.get("importe_estimado") or 0), float(d.get("devolucion_fondo_garantia") or 0),
            float(d.get("devolucion_apoyos") or 0), float(d.get("amortizacion_anticipo") or 0),
            float(d.get("retencion_fondo_garantia") or 0), float(d.get("retencion_extra") or 0),
            float(d.get("importe_liquido_pagado") or 0))
    if existing:
        execute("""UPDATE analisis_financiero_ingresos SET
                   inversion=%s, anticipo=%s, importe_estimado=%s, devolucion_fondo_garantia=%s,
                   devolucion_apoyos=%s, amortizacion_anticipo=%s, retencion_fondo_garantia=%s,
                   retencion_extra=%s, importe_liquido_pagado=%s WHERE id=%s""",
                vals + (existing["id"],))
    else:
        execute("""INSERT INTO analisis_financiero_ingresos
                   (id_obra, numero_semana, inversion, anticipo, importe_estimado,
                    devolucion_fondo_garantia, devolucion_apoyos, amortizacion_anticipo,
                    retencion_fondo_garantia, retencion_extra, importe_liquido_pagado)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (id_obra, numero_semana) + vals)


def get_resumen_analisis_financiero(id_obra):
    """Calcula el resumen financiero completo para la vista.
    Los EGRESOS se calculan en vivo desde requisicion_partidas (estatus_pago='pagado').
    Los INGRESOS siguen siendo captura manual.
    Retorna dict con config, rubros, semanas, totales."""
    cfg = get_analisis_financiero_config(id_obra)
    num_semanas = int(cfg["semanas_proyecto"] or 52)
    ingresos_all = get_ingresos_todas_semanas(id_obra)

    # Rubros dinámicos desde BD
    rubros = get_analisis_rubros()
    rubros_directos   = [r for r in rubros if r["seccion"] == "DIRECTO"]
    rubros_indirectos = [r for r in rubros if r["seccion"] == "INDIRECTO"]

    # Egresos calculados desde requisiciones
    egresos_semana, fuera_de_rango, sin_fecha = get_egresos_desde_requisiciones(id_obra, cfg)

    # Combinar sin_fecha en fuera_de_rango para simplificar visualización
    for rubro_clave, monto in sin_fecha.items():
        fuera_de_rango[rubro_clave] = fuera_de_rango.get(rubro_clave, 0) + monto

    semanas = []
    egreso_acum = 0
    ingreso_acum = 0
    costo_contrato = float(cfg["costo_contrato"] or 0)

    fecha_inicio = cfg.get("fecha_inicio")

    for n in range(1, num_semanas + 1):
        ig = ingresos_all.get(n, {})
        eg_sem = egresos_semana.get(n, {})

        # Egresos por rubro para esta semana
        rubros_valores = {r["clave"]: eg_sem.get(r["clave"], 0) for r in rubros}

        subtotal_directo   = sum(eg_sem.get(r["clave"], 0) for r in rubros_directos)
        subtotal_indirecto = sum(eg_sem.get(r["clave"], 0) for r in rubros_indirectos)
        total_egresos      = subtotal_directo + subtotal_indirecto
        egreso_acum       += total_egresos

        # Ingresos
        inversion        = float(ig.get("inversion") or 0) if ig else 0
        anticipo         = float(ig.get("anticipo") or 0) if ig else 0
        importe_estimado = float(ig.get("importe_estimado") or 0) if ig else 0
        dev_fondo        = float(ig.get("devolucion_fondo_garantia") or 0) if ig else 0
        dev_apoyos       = float(ig.get("devolucion_apoyos") or 0) if ig else 0
        amort_anticipo   = float(ig.get("amortizacion_anticipo") or 0) if ig else 0
        ret_fondo        = float(ig.get("retencion_fondo_garantia") or 0) if ig else 0
        ret_extra        = float(ig.get("retencion_extra") or 0) if ig else 0
        liquido          = float(ig.get("importe_liquido_pagado") or 0) if ig else 0

        total_ingresos = (inversion + anticipo + importe_estimado + dev_fondo + dev_apoyos
                          - amort_anticipo - ret_fondo - ret_extra + liquido)
        ingreso_acum += total_ingresos

        pct_egreso = round((total_egresos / costo_contrato * 100), 2) if costo_contrato > 0 else 0

        # Fechas
        fecha_sem_ini = fecha_sem_fin = None
        if fecha_inicio:
            fi = fecha_inicio if isinstance(fecha_inicio, date) else (
                __import__("datetime").datetime.strptime(str(fecha_inicio), "%Y-%m-%d").date()
            )
            fecha_sem_ini = fi + __import__("datetime").timedelta(days=(n - 1) * 7)
            fecha_sem_fin = fecha_sem_ini + __import__("datetime").timedelta(days=6)

        semanas.append({
            "numero":           n,
            "fecha_inicio":     fecha_sem_ini,
            "fecha_fin":        fecha_sem_fin,
            "rubros":           rubros_valores,   # {clave: monto}
            "subtotal_directo":   subtotal_directo,
            "subtotal_indirecto": subtotal_indirecto,
            "total_egresos":    total_egresos,
            "egreso_acumulado": egreso_acum,
            "pct_egreso":       pct_egreso,
            # Ingresos (igual que antes)
            "inversion":                  inversion,
            "anticipo":                   anticipo,
            "importe_estimado":           importe_estimado,
            "devolucion_fondo_garantia":  dev_fondo,
            "devolucion_apoyos":          dev_apoyos,
            "amortizacion_anticipo":      amort_anticipo,
            "retencion_fondo_garantia":   ret_fondo,
            "retencion_extra":            ret_extra,
            "importe_liquido_pagado":     liquido,
            "total_ingresos":             total_ingresos,
            "ingreso_acumulado":          ingreso_acum,
            "recursos_financieros":       ingreso_acum - egreso_acum,
        })

    # Totales acumulados por rubro (para columna ACUMULADO)
    totales_rubro = {}
    for r in rubros:
        totales_rubro[r["clave"]] = sum(
            egresos_semana.get(n, {}).get(r["clave"], 0) for n in range(1, num_semanas + 1)
        )

    return {
        "config":             cfg,
        "rubros":             rubros,
        "rubros_directos":    rubros_directos,
        "rubros_indirectos":  rubros_indirectos,
        "semanas":            semanas,
        "totales_rubro":      totales_rubro,
        "fuera_de_rango":     fuera_de_rango,
        "total_egresos":      egreso_acum,
        "total_ingresos":     ingreso_acum,
        "recursos_financieros": ingreso_acum - egreso_acum,
    }


# ══════════════════════════════════════════════════════════════════
#  LIQUIDACIÓN DE OBRA (Cierre financiero)
#  Compara presupuesto contratado vs gasto real por categoría
# ══════════════════════════════════════════════════════════════════

def _crear_tabla_liquidacion_obra():
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS liquidacion_obra (
            id INT AUTO_INCREMENT PRIMARY KEY,
            id_obra INT NOT NULL,
            cliente VARCHAR(200) DEFAULT NULL,
            no_proyecto VARCHAR(100) DEFAULT NULL,
            fecha DATE DEFAULT NULL,
            presupuesto_contratado DECIMAL(14,2) DEFAULT 0,
            importe_real DECIMAL(14,2) DEFAULT 0,
            total_aportaciones DECIMAL(14,2) DEFAULT 0,
            mano_obra DECIMAL(14,2) DEFAULT 0,
            materiales DECIMAL(14,2) DEFAULT 0,
            equipo_seguridad DECIMAL(14,2) DEFAULT 0,
            herramienta_equipo DECIMAL(14,2) DEFAULT 0,
            impuestos DECIMAL(14,2) DEFAULT 0,
            indirectos DECIMAL(14,2) DEFAULT 0,
            observaciones TEXT DEFAULT NULL,
            creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            actualizado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_obra (id_obra)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

try:
    _crear_tabla_liquidacion_obra()
except Exception:
    pass


def get_liquidacion_obra(id_obra):
    """Obtiene la liquidación de una obra, o None si no existe."""
    return query("SELECT * FROM liquidacion_obra WHERE id_obra=%s", (id_obra,), one=True)


def guardar_liquidacion_obra(id_obra, d):
    """Guarda o actualiza la liquidación de una obra."""
    existing = query("SELECT id FROM liquidacion_obra WHERE id_obra=%s", (id_obra,), one=True)
    if existing:
        execute("""UPDATE liquidacion_obra SET
                   cliente=%s, no_proyecto=%s, fecha=%s, presupuesto_contratado=%s,
                   importe_real=%s, total_aportaciones=%s, mano_obra=%s, materiales=%s,
                   equipo_seguridad=%s, herramienta_equipo=%s, impuestos=%s, indirectos=%s,
                   observaciones=%s
                   WHERE id_obra=%s""",
                (d.get("cliente"), d.get("no_proyecto"), d.get("fecha") or None,
                 float(d.get("presupuesto_contratado") or 0), float(d.get("importe_real") or 0),
                 float(d.get("total_aportaciones") or 0), float(d.get("mano_obra") or 0),
                 float(d.get("materiales") or 0), float(d.get("equipo_seguridad") or 0),
                 float(d.get("herramienta_equipo") or 0), float(d.get("impuestos") or 0),
                 float(d.get("indirectos") or 0), d.get("observaciones"), id_obra))
    else:
        execute("""INSERT INTO liquidacion_obra
                   (id_obra, cliente, no_proyecto, fecha, presupuesto_contratado, importe_real,
                    total_aportaciones, mano_obra, materiales, equipo_seguridad,
                    herramienta_equipo, impuestos, indirectos, observaciones)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (id_obra, d.get("cliente"), d.get("no_proyecto"), d.get("fecha") or None,
                 float(d.get("presupuesto_contratado") or 0), float(d.get("importe_real") or 0),
                 float(d.get("total_aportaciones") or 0), float(d.get("mano_obra") or 0),
                 float(d.get("materiales") or 0), float(d.get("equipo_seguridad") or 0),
                 float(d.get("herramienta_equipo") or 0), float(d.get("impuestos") or 0),
                 float(d.get("indirectos") or 0), d.get("observaciones")))


def calcular_liquidacion_automatica(id_obra):
    """Calcula la liquidación jalando datos de los módulos existentes.
    Retorna dict con los montos calculados automáticamente."""
    # Presupuesto contratado: de estimaciones o presupuesto_obra
    est = query("SELECT monto_contratado FROM estimaciones_obra WHERE id_obra=%s", (id_obra,), one=True)
    presupuesto = float((est or {}).get("monto_contratado") or 0)

    # Si no hay estimación, intentar de presupuesto_obra
    if presupuesto == 0:
        po = query("SELECT COALESCE(SUM(monto_revisado), 0) AS total FROM presupuesto_obra WHERE id_obra=%s",
                   (id_obra,), one=True)
        presupuesto = float((po or {}).get("total") or 0)

    # Gastos reales por categoría (de gastos previstos)
    gastos = get_gastos_previstos(id_obra)
    real_por_cat = {}
    for g in (gastos or []):
        real_por_cat[g["categoria"]] = float(g.get("monto_presupuestado") or 0)

    # Calcular gastado real de los módulos
    gastado = calcular_gastado_gastos_previstos(id_obra)

    mano_obra = gastado.get("MANO DE OBRA", 0)
    materiales = gastado.get("MATERIALES", 0)
    equipo_seg = gastado.get("EQUIPO DE SEGURIDAD", 0)
    herr_equipo = gastado.get("HERRAMIENTA Y EQUIPO", 0)
    impuestos_val = gastado.get("SEGURO E IMPUESTOS", 0)
    indirectos_val = gastado.get("INDIRECTOS", 0)
    aportaciones = gastado.get("APORTACIONES", 0)

    importe_real = mano_obra + materiales + equipo_seg + herr_equipo + impuestos_val + indirectos_val + aportaciones

    return {
        "presupuesto_contratado": presupuesto,
        "importe_real": importe_real,
        "total_aportaciones": aportaciones,
        "mano_obra": mano_obra,
        "materiales": materiales,
        "equipo_seguridad": equipo_seg,
        "herramienta_equipo": herr_equipo,
        "impuestos": impuestos_val,
        "indirectos": indirectos_val,
    }


# ══════════════════════════════════════════════════════════════════
#  CONTROL DE INGRESOS
#  Registro detallado de cobros/ingresos con retenciones, IVA, líquido
# ══════════════════════════════════════════════════════════════════

def _crear_tabla_control_ingresos():
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS control_ingresos (
            id INT AUTO_INCREMENT PRIMARY KEY,
            id_obra INT DEFAULT NULL,
            descripcion VARCHAR(500) NOT NULL,
            tipo_ingreso VARCHAR(100) DEFAULT NULL COMMENT 'Estimación, Anticipo, Ajuste, etc.',
            no_factura VARCHAR(80) DEFAULT NULL,
            fecha_tramite DATE DEFAULT NULL,
            estatus VARCHAR(50) DEFAULT 'pendiente' COMMENT 'pendiente, en_tramite, cobrado, cancelado',
            importe DECIMAL(14,2) DEFAULT 0,
            deduccion_retencion DECIMAL(14,2) DEFAULT 0,
            subtotal DECIMAL(14,2) DEFAULT 0,
            iva DECIMAL(14,2) DEFAULT 0,
            aportaciones_despues_iva DECIMAL(14,2) DEFAULT 0,
            liquido_pagado DECIMAL(14,2) DEFAULT 0,
            liquido_pendiente DECIMAL(14,2) DEFAULT 0,
            observaciones VARCHAR(500) DEFAULT NULL,
            creado_por INT DEFAULT NULL,
            creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_obra (id_obra),
            INDEX idx_estatus (estatus),
            INDEX idx_fecha (fecha_tramite)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

try:
    _crear_tabla_control_ingresos()
except Exception:
    pass


def get_control_ingresos(id_obra=None, estatus=None, search=None):
    """Lista registros de control de ingresos."""
    sql = "SELECT ci.*, o.nombre AS obra_nombre FROM control_ingresos ci LEFT JOIN obras o ON o.id = ci.id_obra WHERE 1=1"
    params = []
    if id_obra:
        sql += " AND ci.id_obra = %s"
        params.append(id_obra)
    if estatus:
        sql += " AND ci.estatus = %s"
        params.append(estatus)
    if search:
        sql += " AND (ci.descripcion LIKE %s OR ci.no_factura LIKE %s OR ci.tipo_ingreso LIKE %s)"
        params += [f"%{search}%", f"%{search}%", f"%{search}%"]
    sql += " ORDER BY ci.fecha_tramite DESC, ci.id DESC"
    return query(sql, params)


def get_ingreso(ingreso_id):
    return query("SELECT * FROM control_ingresos WHERE id=%s", (ingreso_id,), one=True)


def crear_ingreso(d):
    """Crea un registro de ingreso. Calcula líquido pendiente automáticamente."""
    importe = float(d.get("importe") or 0)
    deduccion = float(d.get("deduccion_retencion") or 0)
    subtotal = importe - deduccion
    iva_val = float(d.get("iva") or 0)
    aportaciones = float(d.get("aportaciones_despues_iva") or 0)
    liquido_pagado = float(d.get("liquido_pagado") or 0)
    liquido_pendiente = subtotal + iva_val + aportaciones - liquido_pagado

    return execute("""
        INSERT INTO control_ingresos
            (id_obra, descripcion, tipo_ingreso, no_factura, fecha_tramite, estatus,
             importe, deduccion_retencion, subtotal, iva, aportaciones_despues_iva,
             liquido_pagado, liquido_pendiente, observaciones, creado_por)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (d.get("id_obra"), d["descripcion"], d.get("tipo_ingreso"), d.get("no_factura"),
          d.get("fecha_tramite") or None, d.get("estatus", "pendiente"),
          importe, deduccion, subtotal, iva_val, aportaciones, liquido_pagado,
          liquido_pendiente, d.get("observaciones"), d.get("creado_por")))


def actualizar_ingreso(ingreso_id, d):
    """Actualiza un registro de ingreso."""
    importe = float(d.get("importe") or 0)
    deduccion = float(d.get("deduccion_retencion") or 0)
    subtotal = importe - deduccion
    iva_val = float(d.get("iva") or 0)
    aportaciones = float(d.get("aportaciones_despues_iva") or 0)
    liquido_pagado = float(d.get("liquido_pagado") or 0)
    liquido_pendiente = subtotal + iva_val + aportaciones - liquido_pagado

    execute("""
        UPDATE control_ingresos SET
            id_obra=%s, descripcion=%s, tipo_ingreso=%s, no_factura=%s, fecha_tramite=%s,
            estatus=%s, importe=%s, deduccion_retencion=%s, subtotal=%s, iva=%s,
            aportaciones_despues_iva=%s, liquido_pagado=%s, liquido_pendiente=%s, observaciones=%s
        WHERE id=%s
    """, (d.get("id_obra"), d["descripcion"], d.get("tipo_ingreso"), d.get("no_factura"),
          d.get("fecha_tramite") or None, d.get("estatus", "pendiente"),
          importe, deduccion, subtotal, iva_val, aportaciones, liquido_pagado,
          liquido_pendiente, d.get("observaciones"), ingreso_id))


def eliminar_ingreso(ingreso_id):
    """Elimina un registro de ingreso."""
    execute("DELETE FROM control_ingresos WHERE id=%s", (ingreso_id,))


def get_totales_ingresos(id_obra=None):
    """Obtiene totales de ingresos."""
    sql = """SELECT
        COALESCE(SUM(importe), 0) AS total_importe,
        COALESCE(SUM(deduccion_retencion), 0) AS total_deduccion,
        COALESCE(SUM(subtotal), 0) AS total_subtotal,
        COALESCE(SUM(iva), 0) AS total_iva,
        COALESCE(SUM(aportaciones_despues_iva), 0) AS total_aportaciones,
        COALESCE(SUM(liquido_pagado), 0) AS total_pagado,
        COALESCE(SUM(liquido_pendiente), 0) AS total_pendiente,
        COUNT(*) AS total_registros
        FROM control_ingresos WHERE 1=1"""
    params = []
    if id_obra:
        sql += " AND id_obra=%s"
        params.append(id_obra)
    return query(sql, params, one=True)


# ══════════════════════════════════════════════════════════════════
#  HISTORIAL DE ACTIVIDADES (auditoría de seguridad)
#  Solo backend — se consulta directamente desde la BD.
# ══════════════════════════════════════════════════════════════════

def _init_tabla_historial_actividades():
    """Crea la tabla si no existe (llamado al arranque de la app)."""
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS historial_actividades (
            id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            id_usuario     INT             DEFAULT NULL,
            nombre         VARCHAR(120)    DEFAULT NULL,
            email          VARCHAR(180)    DEFAULT NULL,
            rol            VARCHAR(60)     DEFAULT NULL,
            accion         VARCHAR(60)     NOT NULL,
            modulo         VARCHAR(80)     DEFAULT NULL,
            descripcion    VARCHAR(500)    DEFAULT NULL,
            objeto_id      VARCHAR(60)     DEFAULT NULL,
            objeto_tipo    VARCHAR(80)     DEFAULT NULL,
            ip             VARCHAR(45)     NOT NULL DEFAULT '',
            user_agent     VARCHAR(300)    DEFAULT NULL,
            metodo         CHAR(6)         DEFAULT NULL,
            ruta           VARCHAR(300)    DEFAULT NULL,
            resultado      ENUM('ok','error','denegado') NOT NULL DEFAULT 'ok',
            detalle_error  VARCHAR(500)    DEFAULT NULL,
            fecha_hora     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY idx_usuario  (id_usuario),
            KEY idx_email    (email),
            KEY idx_accion   (accion),
            KEY idx_fecha    (fecha_hora),
            KEY idx_ip       (ip),
            KEY idx_resultado(resultado)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
          COMMENT='Auditoría de accesos y acciones de usuarios'
    """)


def registrar_actividad(
    accion,
    ip,
    id_usuario=None,
    nombre=None,
    email=None,
    rol=None,
    modulo=None,
    descripcion=None,
    objeto_id=None,
    objeto_tipo=None,
    user_agent=None,
    metodo=None,
    ruta=None,
    resultado="ok",
    detalle_error=None,
    geo_pais=None,
    geo_ciudad=None,
    geo_region=None,
    geo_lat=None,
    geo_lon=None,
):
    """Inserta un registro en historial_actividades.

    Parámetros mínimos:
        accion  — 'login' | 'logout' | 'login_fallido' | 'exportar' |
                  'crear' | 'editar' | 'eliminar' | 'ver'
        ip      — dirección IP del cliente

    Los campos geo_* son opcionales y se llenan desde get_geo_ip() en app.py.

    Nunca lanza excepción: si falla el INSERT, lo silencia para que
    no interrumpa el flujo normal de la aplicación.
    """
    try:
        execute("""
            INSERT INTO historial_actividades
                (id_usuario, nombre, email, rol,
                 accion, modulo, descripcion, objeto_id, objeto_tipo,
                 ip, geo_pais, geo_ciudad, geo_region, geo_lat, geo_lon,
                 user_agent, metodo, ruta,
                 resultado, detalle_error)
            VALUES
                (%s, %s, %s, %s,
                 %s, %s, %s, %s, %s,
                 %s, %s, %s, %s, %s, %s,
                 %s, %s, %s,
                 %s, %s)
                
                
        """, (
            id_usuario, nombre, email, rol,
            accion, modulo, descripcion, objeto_id, objeto_tipo,
            ip[:45] if ip else "",
            (geo_pais  or "")[:80]  or None,
            (geo_ciudad or "")[:120] or None,
            (geo_region or "")[:120] or None,
            geo_lat,
            geo_lon,
            (user_agent or "")[:300] or None,
            (metodo or "")[:6] or None,
            (ruta or "")[:300] or None,
            resultado,
            (detalle_error or "")[:500] or None,
        ))
    except Exception as _e:
        import traceback, sys
        print(f"[AUDIT ERROR] {_e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)


def get_historial_actividades(id_usuario=None, q=None, limite=None, id_obra=None):
    """Devuelve los registros de auditoría (join con la tabla usuarios) con
    filtros opcionales. Ideal para la pantalla de auditoría.

    id_usuario -> filtra por id de usuario (None/0 = todos)
    q          -> busca libre en descripción, ruta, ip y nombre/email del usuario
    limite     -> máximo de filas (None = sin límite)
    id_obra    -> filtra por obra (busca 'id_obra=N' en la descripción)

    Devuelve una lista de dicts ordenada por fecha DESC.
    """
    sql = """
        SELECT h.*,
               u.nombre AS user_nombre,
               u.email  AS user_email,
               u.rol    AS user_rol
        FROM historial_actividades h
        LEFT JOIN usuarios u ON u.id = h.id_usuario
        WHERE 1=1
    """
    params = []
    if id_usuario:
        sql += " AND h.id_usuario = %s"
        params.append(int(id_usuario))
    if id_obra:
        # Las actividades de obra incluyen el id en la descripción como
        # "id_obra=N" o en la ruta como "/obras/N"
        sql += (" AND (h.descripcion LIKE %s OR h.ruta LIKE %s)")
        params.extend([f"%id_obra={int(id_obra)}%", f"%/obras/{int(id_obra)}%"])
    if q:
        like = f"%{q}%"
        sql += (" AND (h.descripcion LIKE %s OR h.ruta LIKE %s OR h.ip LIKE %s "
                "OR h.nombre LIKE %s OR u.nombre LIKE %s OR u.email LIKE %s)")
        params.extend([like, like, like, like, like, like])
    sql += " ORDER BY h.fecha_hora DESC, h.id DESC"
    if limite:
        sql += " LIMIT %s"
        params.append(int(limite))
    return query(sql, params)


# ══════════════════════════════════════════════════════════════════
#  CÁMARAS — Tabla y CRUD
# ══════════════════════════════════════════════════════════════════

def _init_tabla_camaras():
    """Crea la tabla camaras si no existe."""
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS camaras (
            id            INT AUTO_INCREMENT PRIMARY KEY,
            nombre        VARCHAR(100) NOT NULL,
            eco           VARCHAR(20)  DEFAULT NULL COMMENT 'ECO del equipo asociado',
            id_obra       INT          DEFAULT NULL,
            url_stream    VARCHAR(500) NOT NULL    COMMENT 'rtsp://, http:// o índice numérico',
            descripcion   VARCHAR(255) DEFAULT NULL,
            activa        TINYINT(1)   NOT NULL DEFAULT 1,
            creado_por    INT          DEFAULT NULL,
            creado_en     DATETIME     DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_eco   (eco),
            INDEX idx_obra  (id_obra)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)


def get_camaras(id_obra=None, eco=None, solo_activas=True):
    """Lista cámaras con nombre de obra y equipo."""
    sql = """
        SELECT c.*,
               ob.nombre  AS obra_nombre,
               m.nombre_equipo
        FROM camaras c
        LEFT JOIN obras    ob ON ob.id = c.id_obra
        LEFT JOIN maquinas m  ON m.eco = c.eco
        WHERE 1=1
    """
    params = []
    if solo_activas:
        sql += " AND c.activa = 1"
    if id_obra:
        sql += " AND c.id_obra = %s"
        params.append(id_obra)
    if eco:
        sql += " AND c.eco = %s"
        params.append(eco)
    sql += " ORDER BY c.nombre"
    return query(sql, params)


def get_camara(cam_id):
    return query("""
        SELECT c.*,
               ob.nombre AS obra_nombre,
               m.nombre_equipo
        FROM camaras c
        LEFT JOIN obras    ob ON ob.id = c.id_obra
        LEFT JOIN maquinas m  ON m.eco = c.eco
        WHERE c.id = %s
    """, (cam_id,), one=True)


def crear_camara(datos):
    return execute("""
        INSERT INTO camaras (nombre, eco, id_obra, url_stream, descripcion, activa, creado_por)
        VALUES (%(nombre)s, %(eco)s, %(id_obra)s, %(url_stream)s,
                %(descripcion)s, %(activa)s, %(creado_por)s)
    """, datos)


def actualizar_camara(cam_id, datos):
    execute("""
        UPDATE camaras
        SET nombre      = %(nombre)s,
            eco         = %(eco)s,
            id_obra     = %(id_obra)s,
            url_stream  = %(url_stream)s,
            descripcion = %(descripcion)s,
            activa      = %(activa)s
        WHERE id = %(id)s
    """, {**datos, "id": cam_id})


def eliminar_camara(cam_id):
    execute("DELETE FROM camaras WHERE id = %s", (cam_id,))


def toggle_camara_activa(cam_id):
    execute("UPDATE camaras SET activa = NOT activa WHERE id = %s", (cam_id,))


# ══════════════════════════════════════════════════════════════════
#  VEHÍCULOS — Catálogo de vehículos de la empresa
#  Campos: id_vehiculo, marca, modelo, anio, cilindros,
#          serie (único), placa (único), id_obra (FK obras)
# ══════════════════════════════════════════════════════════════════

def _init_tabla_vehiculos():
    """Crea la tabla vehiculos si no existe."""
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS vehiculos (
            id_vehiculo INT PRIMARY KEY AUTO_INCREMENT,
            marca       VARCHAR(50)  NULL,
            modelo      VARCHAR(50)  NULL,
            anio        INT          NULL,
            cilindros   INT,
            serie       VARCHAR(30)  UNIQUE NULL,
            placa       VARCHAR(15)  UNIQUE,
            id_obra     INT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)


def get_vehiculos(search=None, obra=None):
    """Lista todos los vehículos con nombre de obra."""
    sql = """
        SELECT v.*, ob.nombre AS obra_nombre
        FROM vehiculos v
        LEFT JOIN obras ob ON ob.id = v.id_obra
        WHERE 1=1
    """
    params = []
    if search:
        sql += " AND (v.placa LIKE %s OR v.marca LIKE %s OR v.modelo LIKE %s OR v.serie LIKE %s)"
        params += [f"%{search}%"] * 4
    if obra:
        sql += " AND v.id_obra=%s"
        params.append(obra)
    sql += " ORDER BY v.placa"
    return query(sql, params)


def get_vehiculo(vid):
    """Obtiene un vehículo por id con nombre de obra."""
    return query("""
        SELECT v.*, ob.nombre AS obra_nombre
        FROM vehiculos v
        LEFT JOIN obras ob ON ob.id = v.id_obra
        WHERE v.id_vehiculo = %s
    """, (vid,), one=True)


def vehiculo_existe(serie=None, placa=None, excluir_id=None):
    """Verifica unicidad de serie y placa.
    Retorna lista de mensajes de conflicto o None si no hay."""
    conflictos = []
    if serie and serie.strip():
        sql = "SELECT id_vehiculo FROM vehiculos WHERE serie=%s"
        params = [serie.strip()]
        if excluir_id:
            sql += " AND id_vehiculo<>%s"
            params.append(excluir_id)
        if query(sql, params):
            conflictos.append(f"El número de serie '{serie}' ya existe")
    if placa and placa.strip():
        sql = "SELECT id_vehiculo FROM vehiculos WHERE placa=%s"
        params = [placa.strip()]
        if excluir_id:
            sql += " AND id_vehiculo<>%s"
            params.append(excluir_id)
        if query(sql, params):
            conflictos.append(f"La placa '{placa}' ya existe")
    return conflictos if conflictos else None


def crear_vehiculo(d):
    """Inserta un vehículo nuevo. d debe contener las claves del dict."""
    return execute("""
        INSERT INTO vehiculos (marca, modelo, anio, cilindros, serie, placa, id_obra)
        VALUES (%(marca)s, %(modelo)s, %(anio)s, %(cilindros)s,
                %(serie)s, %(placa)s, %(id_obra)s)
    """, d)


def actualizar_vehiculo(d):
    """Actualiza un vehículo existente. d debe incluir id_vehiculo."""
    execute("""
        UPDATE vehiculos
        SET marca=%(marca)s, modelo=%(modelo)s, anio=%(anio)s, cilindros=%(cilindros)s,
            serie=%(serie)s, placa=%(placa)s, id_obra=%(id_obra)s
        WHERE id_vehiculo=%(id_vehiculo)s
    """, d)


def eliminar_vehiculo(vid):
    execute("DELETE FROM vehiculos WHERE id_vehiculo=%s", (vid,))


def fix():
    conn = mysql.connector.connect(**DB_CONFIG)
    cur  = conn.cursor()

    # 1. Cambiar default de la base de datos
    print("[1/3] Cambiando default de la BD a %s/%s..." % (TARGET_CHARSET, TARGET_COLLATION))
    cur.execute(
        "ALTER DATABASE esma_telemetria CHARACTER SET %s COLLATE %s"
        % (TARGET_CHARSET, TARGET_COLLATION)
    )
    conn.commit()
    print("      OK - BD actualizada")

    # 2. Obtener todas las tablas
    cur.execute("SHOW TABLES")
    tablas = [row[0] for row in cur.fetchall()]
    print("\n[2/3] Convirtiendo %d tabla(s)..." % len(tablas))

    ok_count  = 0
    err_count = 0
    for tabla in tablas:
        try:
            cur.execute(
                "ALTER TABLE `%s` CONVERT TO CHARACTER SET %s COLLATE %s"
                % (tabla, TARGET_CHARSET, TARGET_COLLATION)
            )
            conn.commit()
            print("      OK  - %s" % tabla)
            ok_count += 1
        except Exception as e:
            conn.rollback()
            print("      ERR - %s: %s" % (tabla, e))
            err_count += 1

    print("\n      Total: %d OK, %d errores" % (ok_count, err_count))

    # 3. Verificar columnas que aun tengan collation diferente
    print("\n[3/3] Verificando columnas con collation distinta...")
    cur.execute("""
        SELECT TABLE_NAME, COLUMN_NAME, CHARACTER_SET_NAME, COLLATION_NAME
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = 'esma_telemetria'
          AND COLLATION_NAME IS NOT NULL
          AND COLLATION_NAME != '%s'
        ORDER BY TABLE_NAME, COLUMN_NAME
    """ % TARGET_COLLATION)
    pendientes = cur.fetchall()

    if pendientes:
        print("      ADVERTENCIA - %d columna(s) con collation diferente:" % len(pendientes))
        for tabla, col, charset, collation in pendientes:
            # Forzar conversion columna por columna
            try:
                cur.execute(
                    "ALTER TABLE `%s` MODIFY COLUMN `%s` "
                    % (tabla, col) +
                    "(SELECT CONCAT(COLUMN_TYPE,' CHARACTER SET %s COLLATE %s') "
                    % (TARGET_CHARSET, TARGET_COLLATION) +
                    "FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA='esma_telemetria' "
                    "AND TABLE_NAME='%s' AND COLUMN_NAME='%s')" % (tabla, col)
                )
            except Exception:
                pass
            print("        %s.%s: %s/%s" % (tabla, col, charset, collation))
    else:
        print("      OK - Todas las columnas tienen la misma collation")

    cur.close()
    conn.close()
    print("\nListo. Reinicia el servidor Flask.")

    
if __name__ == "__main__":
    fix()


# ══════════════════════════════════════════════════════════════════
#  FOTOS DE EVIDENCIA DE OBRA  (avance físico georreferenciado)
# ══════════════════════════════════════════════════════════════════

def _init_tabla_foto_evidencia_obra():
    """Crea la tabla foto_evidencia_obra si no existe."""
    execute_ddl("""
        CREATE TABLE IF NOT EXISTS foto_evidencia_obra (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            id_obra     INT NOT NULL,
            archivo     VARCHAR(255) NOT NULL,
            descripcion TEXT,
            tramo       VARCHAR(200) DEFAULT NULL COMMENT 'Tramo o KM de referencia',
            latitud     DECIMAL(10,7) NOT NULL,
            longitud    DECIMAL(10,7) NOT NULL,
            precision_m FLOAT DEFAULT NULL COMMENT 'Precisión GPS en metros',
            subido_por  INT DEFAULT NULL,
            creado_en   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_obra (id_obra),
            INDEX idx_geo (latitud, longitud)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)


def get_fotos_evidencia_obra(id_obra=None):
    """Devuelve fotos de evidencia. Si id_obra=None trae todas."""
    sql = """
        SELECT f.*, ob.nombre AS obra_nombre, u.nombre AS subido_por_nombre
        FROM foto_evidencia_obra f
        LEFT JOIN obras ob ON ob.id = f.id_obra
        LEFT JOIN usuarios u ON u.id = f.subido_por
    """
    params = []
    if id_obra is not None:
        sql += " WHERE f.id_obra = %s"
        params.append(id_obra)
    sql += " ORDER BY f.creado_en DESC"
    return query(sql, params)


def insertar_foto_evidencia_obra(d):
    """Inserta una nueva foto de evidencia.
    d: {id_obra, archivo, descripcion, tramo, latitud, longitud, precision_m, subido_por}
    """
    return execute("""
        INSERT INTO foto_evidencia_obra
            (id_obra, archivo, descripcion, tramo, latitud, longitud, precision_m, subido_por)
        VALUES
            (%(id_obra)s, %(archivo)s, %(descripcion)s, %(tramo)s,
             %(latitud)s, %(longitud)s, %(precision_m)s, %(subido_por)s)
    """, d)


def eliminar_foto_evidencia_obra(foto_id, id_obra=None):
    """Elimina una foto por id. Si id_obra se pasa, verifica que pertenezca a esa obra."""
    row = query("SELECT * FROM foto_evidencia_obra WHERE id=%s", (foto_id,), one=True)
    if not row:
        return None
    if id_obra is not None and row["id_obra"] != id_obra:
        return None
    execute("DELETE FROM foto_evidencia_obra WHERE id=%s", (foto_id,))
    return row
