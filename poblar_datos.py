"""
poblar_datos.py — Genera datos DEMO para la plataforma en localhost.
GRUPO ESMA — Plataforma de Telemetría

Ejecutar UNA vez después de importar esma_telemetria.sql:
    py poblar_datos.py

Genera:
  · 30 días de estado/horas/utilización para 6 equipos con telemetría
  · historial_estado (varias lecturas por día)
  · reportes_combustible con anomalías (OK/Revisar/Alerta/Fraude Probable)
  · inspecciones, incidentes y registro diario de ejemplo
"""
import random
from datetime import date, datetime, timedelta
import database as db

random.seed(7)  # reproducible

EQUIPOS = [
    {"eco":"EXC-001","serie":"VCEC350DC00271259","nombre":"EXCAVADORA","marca":"VOLVO","modelo":"EC350DL","cap":500,"obra":4,"lat":19.3464,"lon":-98.7880},
    {"eco":"EXC-008","serie":"VCEC350DC00271424","nombre":"EXCAVADORA","marca":"VOLVO","modelo":"EC350DL","cap":500,"obra":2,"lat":30.4833,"lon":-108.9333},
    {"eco":"EXC-009","serie":"VCEC350DP00281740","nombre":"EXCAVADORA","marca":"VOLVO","modelo":"EC350DL","cap":500,"obra":2,"lat":30.4840,"lon":-108.9340},
    {"eco":"CGD-001","serie":"VGEL110FAJ0071129","nombre":"CARGADOR FRONTAL","marca":"VOLVO","modelo":"L110F","cap":310,"obra":4,"lat":19.3470,"lon":-98.7890},
    {"eco":"TOR-005","serie":"100197","nombre":"TRACTOR","marca":"KOMATSU","modelo":"D155AX-8","cap":400,"obra":1,"lat":20.1117,"lon":-99.3341},
    {"eco":"MTN-001","serie":"60270","nombre":"MOTOCONFORMADORA","marca":"KOMATSU","modelo":"GD655-6","cap":350,"obra":5,"lat":19.2227,"lon":-98.6656},
]

OPERADORES = ["J. Ramírez","M. Hernández","L. Gómez","A. Torres","R. Sánchez","E. Mendoza"]

def semana_operativa(f):
    # Semana 1 ancla: lunes 29-dic-2025
    ancla = date(2025, 12, 29)
    return (f - ancla).days // 7 + 1

def poblar():
    hoy = date.today()
    print("Poblando 30 días de telemetría + reportes...")
    horometro = {e["eco"]: random.uniform(1500, 8500) for e in EQUIPOS}

    n_rep = 0
    for d_off in range(29, -1, -1):
        f = hoy - timedelta(days=d_off)
        fstr = f.strftime("%Y-%m-%d")
        for e in EQUIPOS:
            trabajadas = round(random.uniform(6, 10), 2)
            ralenti    = round(random.uniform(0.5, 2.5), 2)
            motor_con  = round(trabajadas + ralenti, 2)
            lts_hora   = round(random.uniform(9, 22), 2)
            consumido_tel = round(lts_hora * trabajadas, 2)   # telemetría
            horometro[e["eco"]] += trabajadas
            nivel = round(random.uniform(15, 95), 2)

            # estado (último) y horas/utilización del día
            db.upsert_estado({"eco":e["eco"],"serie":e["serie"],"nombre_equipo":e["nombre"],
                "marca":e["marca"],"modelo":e["modelo"],
                "fecha":f.strftime("%Y-%m-%d %H:%M:%S"),
                "lat":round(e["lat"]+random.uniform(-.002,.002),7),
                "lon":round(e["lon"]+random.uniform(-.002,.002),7),
                "horometro":round(horometro[e["eco"]],2),
                "nivel_combustible":nivel,"capacidad_litros":e["cap"]})
            db.upsert_horas({"eco":e["eco"],"serie":e["serie"],"nombre_equipo":e["nombre"],
                "marca":e["marca"],"modelo":e["modelo"],"fecha":fstr,
                "horas_trabajadas":trabajadas,"horas_motor_conectado":motor_con,
                "horas_ralenti":ralenti,"motor_desconectado":round(max(0,8-motor_con),2)})
            db.upsert_utilizacion({"eco":e["eco"],"serie":e["serie"],"nombre_equipo":e["nombre"],
                "marca":e["marca"],"modelo":e["modelo"],"fecha":fstr,
                "litros_hora":lts_hora,"litros_consumidos":consumido_tel,
                "horas_maquina":trabajadas,"horas_ralenti":ralenti,
                "ralenti_porcentaje":round(ralenti/motor_con*100,2)})

            # historial: 3 lecturas en el día
            for h in (8, 13, 18):
                db.insertar_historial({"eco":e["eco"],"serie":e["serie"],"nombre_equipo":e["nombre"],
                    "marca":e["marca"],"modelo":e["modelo"],
                    "fecha":f.strftime(f"%Y-%m-%d {h:02d}:00:00"),
                    "lat":round(e["lat"]+random.uniform(-.002,.002),7),
                    "lon":round(e["lon"]+random.uniform(-.002,.002),7),
                    "horometro":round(horometro[e["eco"]],2),
                    "nivel_combustible":round(random.uniform(15,95),2),
                    "capacidad_litros":e["cap"]})

            # reporte de combustible (lo CARGADO según ticket/manual)
            # La mayoría sale OK; inyectamos anomalías al azar
            r = random.random()
            if r < 0.08:        # fraude probable: cargaron mucho más de lo consumido
                cargado = round(consumido_tel * random.uniform(1.28, 1.55), 2)
            elif r < 0.18:      # alerta
                cargado = round(consumido_tel * random.uniform(1.14, 1.20), 2)
            elif r < 0.32:      # revisar
                cargado = round(consumido_tel * random.uniform(1.06, 1.11), 2)
            elif r < 0.40:      # litros a favor (telemetría > cargado): posible carga fantasma
                cargado = round(consumido_tel * random.uniform(0.80, 0.93), 2)
            else:               # OK
                cargado = round(consumido_tel * random.uniform(0.97, 1.04), 2)

            db.crear_reporte_combustible({
                "eco":e["eco"],"nombre_equipo":e["nombre"],"marca":e["marca"],
                "id_obra":e["obra"],"fecha":fstr,"semana":semana_operativa(f),
                "operador":random.choice(OPERADORES),
                "litros_cargados":cargado,"litros_telemetria":consumido_tel,
                "horas_maquina":trabajadas,"observaciones":None,"registrado_por":1})
            n_rep += 1
    print(f"  {n_rep} reportes de combustible generados.")

    # ── Inspecciones de ejemplo ────────────────────────────────────
    print("Generando inspecciones, incidentes y bitácora...")
    tipos_insp = ["rutinaria","combustible","mantenimiento","seguridad"]
    for i in range(12):
        e = random.choice(EQUIPOS)
        res = random.choice(["conforme","conforme","observaciones","no_conforme"])
        sev = {"conforme":"bajo","observaciones":"medio","no_conforme":"alto"}[res]
        db.crear_inspeccion({"codigo_eco":e["eco"],"id_obra":e["obra"],
            "fecha":(hoy-timedelta(days=random.randint(0,25))).strftime("%Y-%m-%d"),
            "inspector":random.choice(OPERADORES),"tipo":random.choice(tipos_insp),
            "resultado":res,"severidad":sev,
            "hallazgos":"Revisión de niveles, fugas y horómetro." if res=="conforme"
                        else "Diferencia detectada en consumo / nivel de tanque. Requiere seguimiento.",
            "registrado_por":1})

    # ── Incidentes de ejemplo ──────────────────────────────────────
    incid = [
        ("ordeña","Caída nocturna de nivel de combustible sin operación registrada.","alto","abierto","Pedro · Control"),
        ("combustible","Reporte de litros cargados no coincide con telemetría (>25%).","critico","en_proceso","Supervisor de Obra"),
        ("falla","Sensor de horómetro sin transmitir 2 días.","medio","abierto","Soporte Fletrack"),
        ("operativo","Equipo fuera de geocerca de obra asignada.","medio","cerrado","Supervisor de Obra"),
        ("seguridad","Exceso de velocidad reportado en traslado.","bajo","cerrado","Supervisor de Obra"),
    ]
    for tipo,desc,sev,est,resp in incid:
        e = random.choice(EQUIPOS)
        db.crear_incidente({"codigo_eco":e["eco"],"id_obra":e["obra"],
            "fecha":(hoy-timedelta(days=random.randint(0,15))).strftime("%Y-%m-%d"),
            "tipo":tipo,"descripcion":desc,"severidad":sev,"estado":est,
            "responsable":resp,"reportado_por":1})

    # ── Registro diario ────────────────────────────────────────────
    for d_off in range(0, 6):
        f = hoy - timedelta(days=d_off)
        for obra in (1,2,4,5):
            db.crear_registro({"fecha":f.strftime("%Y-%m-%d"),"id_obra":obra,
                "autor":random.choice(OPERADORES),
                "clima":random.choice(["Despejado","Nublado","Lluvia ligera","Caluroso"]),
                "equipos_activos":random.randint(2,6),
                "notas":"Jornada normal de operación. Sin novedades mayores.",
                "registrado_por":1})

    print("¡Listo! Datos demo cargados.")

if __name__ == "__main__":
    poblar()
