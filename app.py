"""
app.py — Servidor Flask principal
GRUPO ESMA — Plataforma de Telemetría
Estructura tipo Procore: Inicio · Reportes 360 (Combustible) · Documentos ·
Equipos · Obras · Inspecciones · Incidentes · Registro diario · Mapa GPS.
"""
import os, hashlib
from datetime import datetime, date, timedelta
from flask import (Flask, render_template, jsonify, request,
                   redirect, url_for, session, flash, send_file, abort)
from flask_socketio import SocketIO
import database as db



app = Flask(__name__)
app.secret_key = "esma_telemetria_2026_secreto"
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB
socketio = SocketIO(app, cors_allowed_origins="*")

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ROLES_ORDEN = {"admin": 5, "supervisor": 4, "operador": 3, "reportes": 2, "cliente": 1}

app.jinja_env.filters['rol_label'] = lambda r: db.get_roles_labels().get(r, r)

def hash_pwd(pwd):
    return hashlib.sha256(pwd.encode()).hexdigest()

# ── Decoradores de acceso ─────────────────────────────────────────
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def rol_minimo(rol):
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def decorated(*args, **kwargs):
            user_rol = session.get("user_rol", "cliente")
            if ROLES_ORDEN.get(user_rol, 0) < ROLES_ORDEN.get(rol, 0):
                flash("No tienes permisos para esta acción.", "danger")
                return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return decorated
    return decorator

def get_current_user():
    if "user_id" in session:
        return {"id": session["user_id"], "nombre": session["user_nombre"],
                "email": session["user_email"], "rol": session["user_rol"],
                "id_obra_asignada": session.get("user_obra_asignada")}
    return None

def permiso_requerido(modulo, accion="leer"):
    """Decorador que verifica si el usuario en sesión tiene el permiso
    (modulo, accion) según la tabla permisos_rol.
    Admin siempre pasa. Si no tiene permiso, redirige al dashboard con flash."""
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def decorated(*args, **kwargs):
            rol = session.get("user_rol", "cliente")
            if rol == "admin":
                return f(*args, **kwargs)
            perms = db.get_permisos_rol(rol)
            mod_perms = perms.get(modulo, {})
            if not mod_perms.get(accion):
                flash("No tienes permiso para acceder a este módulo.", "danger")
                return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return decorated
    return decorator

def obra_permitida(oid):
    """True si el usuario en sesión puede administrar la obra `oid`.
    Admin: siempre. Superintendente de Obra / Administrador de Obra: solo
    la obra que tienen asignada. Otros roles: no (esta función es solo
    para acciones de administración de obra, no de solo lectura)."""
    rol = session.get("user_rol", "cliente")
    if rol == "admin":
        return True
    if rol in db.ROLES_RESTRINGIDOS_A_OBRA:
        asignada = session.get("user_obra_asignada")
        return asignada is not None and int(asignada) == int(oid)
    return False

def hoy_str():       return date.today().strftime("%Y-%m-%d")
def hace(dias):      return (date.today() - timedelta(days=dias)).strftime("%Y-%m-%d")

# ══════════════════════════════════════════════════════════════════
#  AUTH
# ══════════════════════════════════════════════════════════════════
@app.route("/login", methods=["GET","POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    error = None
    if request.method == "POST":
        email = request.form.get("email","").strip()
        pwd   = request.form.get("password","")
        user  = db.get_usuario_by_email(email)
        if user and user["password"] == hash_pwd(pwd):
            session["user_id"]     = user["id"]
            session["user_nombre"] = user["nombre"]
            session["user_email"]  = user["email"]
            session["user_rol"]    = user["rol"]
            session["user_obra_asignada"] = user.get("id_obra_asignada")
            return redirect(url_for("dashboard"))
        error = "Correo o contraseña incorrectos"
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ══════════════════════════════════════════════════════════════════
#  INICIO / DASHBOARD
# ══════════════════════════════════════════════════════════════════
@app.route("/")
@login_required
def dashboard():
    user = get_current_user()
    # Verificar si el usuario tiene permiso dashboard_completo.leer
    rol = session.get("user_rol", "cliente")
    if rol == "admin":
        ver_dashboard_completo = True
    else:
        perms = db.get_permisos_rol(rol)
        ver_dashboard_completo = perms.get("dashboard_completo", {}).get("leer", False)

    kpis = db.get_kpis() if ver_dashboard_completo else {}
    incidentes = db.get_incidentes()[:6] if ver_dashboard_completo else []
    try:
        alertas_planta = db.get_planta_alertas_todas()[:8] if ver_dashboard_completo else []
    except Exception:
        alertas_planta = []
    obras_dash = db.get_obras() if ver_dashboard_completo else []
    return render_template("dashboard.html", kpis=kpis, user=user, incidentes=incidentes,
                           alertas_planta=alertas_planta,
                           ver_dashboard_completo=ver_dashboard_completo,
                           obras_dash=obras_dash)

# ══════════════════════════════════════════════════════════════════
#  REPORTES 360 · COMBUSTIBLE  (núcleo de auditoría)
# ══════════════════════════════════════════════════════════════════
@app.route("/combustible")
@login_required
@permiso_requerido("combustible", "leer")
def combustible():
    fi  = request.args.get("fecha_ini", hace(30))
    ff  = request.args.get("fecha_fin", hoy_str())
    sem = request.args.get("semaforo", "")
    obr = request.args.get("obra", "")
    eco = request.args.get("eco", "")
    user     = get_current_user()
    rol = session.get("user_rol", "cliente")
    es_admin = (rol == "admin")

    # Obras donde el usuario puede LEER combustible
    if es_admin:
        obras = db.get_obras()
    else:
        # Obras con cualquier permiso en combustible (leer, crear, editar)
        obras_leer_raw = db.get_obras_permitidas(user["id"], "combustible", "leer")
        obras_crear_raw = db.get_obras_permitidas(user["id"], "combustible", "crear")
        # Unir todas las obras donde tiene algún permiso
        obras_map = {}
        for o in obras_leer_raw:
            obras_map[o["id_obra"]] = o["obra_nombre"]
        for o in obras_crear_raw:
            obras_map[o["id_obra"]] = o["obra_nombre"]
        obras = [{"id": oid, "nombre": nombre} for oid, nombre in obras_map.items()]
        # Fallback: si no tiene permisos por obra pero tiene obra asignada, usar esa
        if not obras and user.get("id_obra_asignada"):
            obra_asig = db.get_obra(user["id_obra_asignada"])
            if obra_asig:
                obras = [{"id": obra_asig["id"], "nombre": obra_asig["nombre"]}]

    # Obras donde el usuario puede CREAR combustible (para botones y modal)
    if es_admin:
        obras_crear = db.get_obras()
    else:
        obras_crear = [{"id": o["id_obra"], "nombre": o["obra_nombre"]} for o in obras_crear_raw]
        # Fallback: si no tiene permisos por obra pero tiene obra asignada
        if not obras_crear and user.get("id_obra_asignada"):
            obra_asig = db.get_obra(user["id_obra_asignada"])
            if obra_asig:
                obras_crear = [{"id": obra_asig["id"], "nombre": obra_asig["nombre"]}]

    ids_permitidos = {o["id"] for o in obras}

    # Filtrar reportes solo a obras permitidas
    obra_filtro = int(obr) if obr else None
    if obra_filtro and obra_filtro not in ids_permitidos:
        obra_filtro = None  # No tiene permiso para esa obra

    reportes = db.get_reportes_combustible(fi, ff, sem or None, obra_filtro, eco or None)
    # Si no es admin, filtrar a obras con permiso
    if not es_admin:
        reportes = [r for r in reportes if r.get("id_obra") in ids_permitidos]

    kpis     = db.get_combustible_kpis(fi, ff)
    por_obra = db.get_combustible_por_obra(fi, ff)
    # Filtrar faltantes por obra a solo las permitidas
    if not es_admin:
        por_obra = [o for o in por_obra if o.get("id_obra") in ids_permitidos]

    # Determinar si el usuario puede ver datos de telemetría en la gráfica
    # Se activa solo si tiene 'leer' en combustible para alguna obra
    if es_admin:
        ver_telemetria = True
    else:
        ver_telemetria = len(obras_leer_raw) > 0

    # Inyectar número de semana automático a cada reporte
    for r in reportes:
        r["semana_num"] = db.calcular_semana_combustible(r.get("fecha"))

    # Separar reportes por tipo de combustible
    reportes_diesel = [r for r in reportes if (r.get("tipo_combustible") or "diesel") == "diesel"]
    reportes_gasolina = [r for r in reportes if (r.get("tipo_combustible") or "diesel") == "gasolina"]

    puede_crear = es_admin or len(obras_crear) > 0

    return render_template("combustible.html", reportes=reportes,
                           reportes_diesel=reportes_diesel,
                           reportes_gasolina=reportes_gasolina,
                           kpis=kpis, por_obra=por_obra, obras=obras, user=user,
                           fi=fi, ff=ff, sem=sem, obr=obr, eco=eco,
                           ver_telemetria=ver_telemetria,
                           obras_crear=obras_crear, puede_crear=puede_crear)

@app.route("/combustible/nuevo", methods=["GET","POST"])
@login_required
@permiso_requerido("combustible", "crear")
def combustible_nuevo():
    user  = get_current_user()
    es_admin = (user["rol"] == "admin")
    if es_admin:
        obras = db.get_obras()
    else:
        obras_raw = db.get_obras_permitidas(user["id"], "combustible", "crear")
        obras = [{"id": o["id_obra"], "nombre": o["obra_nombre"]} for o in obras_raw]
    maquinas = db.get_maquinas()
    pre_eco = request.args.get("eco", "")
    pre_fecha = request.args.get("fecha", hoy_str())
    if request.method == "POST":
        f = request.form
        eco = f["eco"].upper()
        fecha = f["fecha"]
        tipo_comb = f.get("tipo_combustible", "diesel")
        maq = db.get_maquina(eco)
        # Telemetría siempre se toma automáticamente del equipo
        t = db.telemetria_consumo_dia(eco, fecha)
        tel = t.get("litros_consumidos") or 0
        from datetime import datetime as _dt
        semana = (_dt.strptime(fecha,"%Y-%m-%d").date() - date(2025,12,29)).days // 7 + 1

        litros = float(f.get("litros_cargados") or 0)
        costo_total = float(f.get("costo_total") or 0) or None
        costo_por_litro = round(costo_total / litros, 2) if costo_total and litros > 0 else None

        datos = {
            "eco": eco, "nombre_equipo": (maq or {}).get("nombre_equipo",""),
            "marca": (maq or {}).get("marca",""),
            "id_obra": int(f.get("id_obra")) if f.get("id_obra") else (maq or {}).get("id_obra"),
            "fecha": fecha, "semana": semana, "operador": f.get("responsable",""),
            "litros_cargados": litros,
            "litros_telemetria": float(tel or 0),
            "horas_maquina": None,
            "observaciones": f.get("observaciones",""),
            "registrado_por": session["user_id"],
            "tipo_combustible": tipo_comb,
            "costo_total": costo_total,
            "costo_por_litro": costo_por_litro,
            "frente_trabajo": f.get("frente_trabajo") or None,
            "actividad": f.get("actividad") or None,
            "origen_carga": f.get("origen_carga") or None,
            "responsable": f.get("responsable") or None,
            "folio_ticket": f.get("folio_ticket") or None,
        }

        if tipo_comb == "diesel":
            h_ini = float(f.get("horometro_inicial") or 0) or None
            h_fin = float(f.get("horometro_final") or 0) or None
            horas = round(h_fin - h_ini, 2) if h_ini and h_fin else None
            lt_por_hr = round(litros / horas, 2) if horas and horas > 0 and litros > 0 else None
            costo_por_hr = round(costo_total / horas, 2) if costo_total and horas and horas > 0 else None
            datos.update({
                "horometro_inicial": h_ini, "horometro_final": h_fin,
                "horas_maquina": horas, "lt_por_hr": lt_por_hr, "costo_por_hr": costo_por_hr,
                "frente_trabajo": f.get("frente_trabajo") or None,
            })
        else:  # gasolina
            o_ini = float(f.get("odometro_inicial") or 0) or None
            o_fin = float(f.get("odometro_final") or 0) or None
            km = round(o_fin - o_ini, 2) if o_ini and o_fin else None
            km_por_litro = round(km / litros, 3) if km and litros > 0 else None
            costo_por_km = round(costo_total / km, 2) if costo_total and km and km > 0 else None
            datos.update({
                "odometro_inicial": o_ini, "odometro_final": o_fin,
                "km_recorridos": km, "km_por_litro": km_por_litro,
                "costo_por_km": costo_por_km, "destino": f.get("destino") or None,
            })

        db.crear_reporte_combustible(datos)
        flash(f"Reporte de combustible de {eco} registrado.", "success")
        return redirect(url_for("combustible"))
    return render_template("combustible_form.html", user=user, obras=obras,
                           maquinas=maquinas, pre_eco=pre_eco, pre_fecha=pre_fecha)

@app.route("/combustible/<int:rid>/justificar", methods=["POST"])
@login_required
@permiso_requerido("combustible", "editar")
@rol_minimo("supervisor")
def combustible_justificar(rid):
    just = 1 if request.form.get("justificado") == "1" else 0
    obs  = request.form.get("observaciones")
    db.marcar_reporte_justificado(rid, just, obs)
    flash("Reporte actualizado.", "success")
    return redirect(request.referrer or url_for("combustible"))


# ══════════════════════════════════════════════════════════════════
#  COMBUSTIBLE — IMPORTAR EXCEL SEMANAL
#  Detecta secciones DIESEL y GASOLINA en la hoja de combustible,
#  soporta hojas en cualquier orden y encabezados en filas variables.
# ══════════════════════════════════════════════════════════════════
@app.route("/combustible/importar-excel", methods=["POST"])
@login_required
@permiso_requerido("combustible", "crear")
def combustible_importar_excel():
    from openpyxl import load_workbook as lw
    from datetime import datetime as _dt, date as _date, timedelta

    user = get_current_user()
    id_obra = request.form.get("id_obra")
    archivo = request.files.get("archivo_excel")

    if not id_obra or not archivo or not archivo.filename:
        flash("Selecciona una obra y un archivo Excel.", "danger")
        return redirect(url_for("combustible"))

    ext = os.path.splitext(archivo.filename)[1].lower()
    if ext not in (".xlsx", ".xls"):
        flash("Solo se aceptan archivos Excel (.xlsx, .xls).", "danger")
        return redirect(url_for("combustible"))

    id_obra = int(id_obra)

    try:
        wbi = lw(archivo, read_only=True, data_only=True)
    except Exception as e:
        flash(f"No se pudo leer el archivo: {e}", "danger")
        return redirect(url_for("combustible"))

    # ── Buscar la hoja de combustible ──
    # Busca hoja que contenga "combustible" en el nombre, o que tenga "DIESEL" en el contenido
    hoja_comb = None
    for nombre in wbi.sheetnames:
        if "combustible" in nombre.lower() or "comb" in nombre.lower():
            hoja_comb = nombre
            break
    # Si no la encuentra por nombre, buscar por contenido
    if not hoja_comb:
        for nombre in wbi.sheetnames:
            try:
                ws_test = wbi[nombre]
                for row in ws_test.iter_rows(min_row=1, max_row=30, values_only=True):
                    texto = " ".join(str(c or "").upper() for c in row)
                    if "DIESEL" in texto and ("FECHA" in texto or "MAQUINA" in texto or "LITROS" in texto):
                        hoja_comb = nombre
                        break
                if hoja_comb:
                    break
            except Exception:
                continue
    # Último recurso: si solo hay una hoja o tomar la primera con datos
    if not hoja_comb:
        if len(wbi.sheetnames) == 1:
            hoja_comb = wbi.sheetnames[0]
        else:
            # Tomar la última hoja (muchos reportes ponen datos al final)
            hoja_comb = wbi.sheetnames[-1]

    ws = wbi[hoja_comb]
    filas = list(ws.iter_rows(min_row=1, values_only=True))

    if not filas:
        flash("La hoja de combustible está vacía.", "danger")
        return redirect(url_for("combustible"))

    # ── Detectar secciones DIESEL y GASOLINA ──
    # Buscar filas que contengan "DIESEL" o "GASOLINA" como marcador de sección
    idx_diesel = None
    idx_gasolina = None
    for i, fila in enumerate(filas):
        if not fila:
            continue
        textos = [str(c or "").strip().upper() for c in fila]
        texto_unido = " ".join(textos)
        # Detectar inicio de sección DIESEL
        if idx_diesel is None and "DIESEL" in textos:
            idx_diesel = i
        # Detectar inicio de sección GASOLINA
        if "GASOLINA" in textos:
            idx_gasolina = i

    importados_diesel = 0
    importados_gasolina = 0
    errores = 0
    debug_info = []

    def _encontrar_encabezado(filas_seccion, palabras_clave):
        """Busca la fila de encabezado dentro de una sección."""
        for idx, fila in enumerate(filas_seccion[:15]):
            if not fila:
                continue
            texto = " ".join(_normalizar_texto(c) for c in fila if c is not None)
            coincidencias = sum(1 for kw in palabras_clave if kw in texto)
            if coincidencias >= 3:
                return idx
        return None

    def _mapear_cols(header, mapeo):
        """Mapea columnas normalizadas a campos."""
        header_norm = [_normalizar_texto(c) for c in header]
        col_map = {}
        for campo, aliases in mapeo.items():
            aliases_norm = [_normalizar_texto(a) for a in aliases]
            for i, h in enumerate(header_norm):
                if not h:
                    continue
                if h in aliases_norm:
                    col_map[campo] = i
                    break
                if any(a in h for a in aliases_norm if len(a) >= 4):
                    col_map[campo] = i
                    break
                if any(h in a for a in aliases_norm if len(h) >= 4):
                    col_map[campo] = i
                    break
        return col_map

    def _limpiar_num(valor):
        """Convierte un valor a float, limpiando formatos como '$1,234.56' o '4,711.2 Km'."""
        if valor is None:
            return None
        if isinstance(valor, (int, float)):
            return float(valor)
        txt = str(valor).strip()
        # Quitar símbolos comunes
        txt = txt.replace("$", "").replace("Km", "").replace("km", "")
        txt = txt.replace("L", "").replace("lt", "").replace("Lt", "")
        txt = txt.replace("$/L", "").replace("$/Km", "").replace("$/Hr", "")
        txt = txt.strip()
        if not txt or txt in ("", "—", "-", "N/A"):
            return None
        # Quitar comas de miles
        txt = txt.replace(",", "")
        # Quitar espacios
        txt = txt.strip()
        try:
            return float(txt)
        except (ValueError, TypeError):
            return None

    def _limpiar_fecha(valor):
        """Convierte fecha de Excel."""
        return _convertir_fecha_excel(valor)

    # ── Calcular número de semana ──
    semana_num = None
    # Intentar extraer de nombre de hoja o contenido
    import re
    for fila in filas[:20]:
        if not fila:
            continue
        for c in fila:
            if c is not None:
                m = re.search(r'(?:SEM(?:ANA)?\.?\s*#?\s*(\d+))|(?:#(\d+))', str(c).upper())
                if m:
                    semana_num = int(m.group(1) or m.group(2))
                    break
        if semana_num:
            break

    # ─── SECCIÓN DIESEL ──────────────────────────────────────────
    if idx_diesel is not None:
        # Determinar fin de sección diesel (hasta GASOLINA o fin de datos)
        fin_diesel = idx_gasolina if idx_gasolina else len(filas)
        filas_diesel = filas[idx_diesel:fin_diesel]

        idx_header = _encontrar_encabezado(filas_diesel,
            ["fecha", "litros", "costo", "horometro", "maquina", "equipo"])

        if idx_header is not None:
            header = filas_diesel[idx_header]
            mapeo_diesel = {
                "eco": ["maquina equipo", "maquina", "equipo", "eco", "id equipo"],
                "fecha": ["fecha", "date"],
                "litros": ["litros cargados", "litros", "lts cargados"],
                "costo_total": ["costo total del combustible", "costo total", "costo"],
                "horometro_ini": ["horometro inicial", "horometro ini", "hor ini"],
                "horometro_fin": ["horometro final", "horometro fin", "hor fin"],
                "horas_maquina": ["horas maquina", "hrs maquina", "horas"],
                "costo_litro": ["costo por litro", "costo litro", "$ lt"],
                "lt_por_hr": ["lt por hr", "lts hr", "litros hora", "lts por hr"],
                "costo_por_hr": ["costo por hr", "costo hr", "$ hr"],
                "frente": ["frente de trabajo", "frente trabajo", "frente"],
                "actividad": ["actividad"],
                "origen": ["origen de carga", "origen carga", "origen"],
                "responsable": ["responsable", "operador"],
                "observaciones": ["observaciones", "comentarios", "observaciones comentarios"],
                "folio": ["folio ticket", "folio", "ticket"],
            }
            col_map = _mapear_cols(header, mapeo_diesel)
            debug_info.append(f"Diesel: encabezado fila {idx_diesel + idx_header + 1}, cols={list(col_map.keys())}")

            filas_datos = filas_diesel[idx_header + 1:]
            for fila in filas_datos:
                if not fila or all(c is None or str(c).strip() == "" for c in fila):
                    continue
                try:
                    def _val_d(campo):
                        idx = col_map.get(campo)
                        if idx is None or idx >= len(fila):
                            return None
                        v = fila[idx]
                        if v is None or str(v).strip() in ("", "—", "-"):
                            return None
                        return v

                    eco_raw = _val_d("eco")
                    if not eco_raw:
                        continue  # Fila vacía de datos
                    eco = str(eco_raw).strip().upper()

                    fecha = _limpiar_fecha(_val_d("fecha"))
                    if not fecha:
                        errores += 1
                        continue

                    litros = _limpiar_num(_val_d("litros"))
                    if not litros or litros <= 0:
                        errores += 1
                        continue

                    costo_total = _limpiar_num(_val_d("costo_total"))
                    h_ini = _limpiar_num(_val_d("horometro_ini"))
                    h_fin = _limpiar_num(_val_d("horometro_fin"))
                    horas = _limpiar_num(_val_d("horas_maquina"))
                    # Si no viene horas, calcular de horómetros
                    if not horas and h_ini and h_fin and h_fin > h_ini:
                        horas = round(h_fin - h_ini, 2)

                    costo_litro = _limpiar_num(_val_d("costo_litro"))
                    if not costo_litro and costo_total and litros > 0:
                        costo_litro = round(costo_total / litros, 2)

                    lt_hr = _limpiar_num(_val_d("lt_por_hr"))
                    if not lt_hr and litros > 0 and horas and horas > 0:
                        lt_hr = round(litros / horas, 2)

                    costo_hr = _limpiar_num(_val_d("costo_por_hr"))
                    if not costo_hr and costo_total and horas and horas > 0:
                        costo_hr = round(costo_total / horas, 2)

                    # Buscar equipo en BD
                    maq = db.get_maquina(eco)
                    # Telemetría
                    t = db.telemetria_consumo_dia(eco, fecha)
                    tel = t.get("litros_consumidos") or 0

                    semana = semana_num
                    if not semana:
                        from datetime import datetime as _dtx
                        try:
                            fd = _dtx.strptime(fecha, "%Y-%m-%d").date()
                            semana = (fd - date(2025, 12, 29)).days // 7 + 1
                        except Exception:
                            semana = None

                    datos = {
                        "eco": eco,
                        "nombre_equipo": (maq or {}).get("nombre_equipo", ""),
                        "marca": (maq or {}).get("marca", ""),
                        "id_obra": id_obra,
                        "fecha": fecha,
                        "semana": semana,
                        "operador": str(_val_d("responsable") or ""),
                        "litros_cargados": litros,
                        "litros_telemetria": float(tel or 0),
                        "horas_maquina": horas,
                        "observaciones": str(_val_d("observaciones") or ""),
                        "registrado_por": session["user_id"],
                        "tipo_combustible": "diesel",
                        "costo_total": costo_total,
                        "costo_por_litro": costo_litro,
                        "horometro_inicial": h_ini,
                        "horometro_final": h_fin,
                        "lt_por_hr": lt_hr,
                        "costo_por_hr": costo_hr,
                        "frente_trabajo": str(_val_d("frente") or "") or None,
                        "actividad": str(_val_d("actividad") or "") or None,
                        "origen_carga": str(_val_d("origen") or "") or None,
                        "responsable": str(_val_d("responsable") or "") or None,
                        "folio_ticket": str(_val_d("folio") or "") or None,
                    }
                    db.crear_reporte_combustible(datos)
                    importados_diesel += 1
                except Exception as exc:
                    errores += 1
                    if len(debug_info) < 5:
                        debug_info.append(f"  Error diesel: {exc}")
        else:
            debug_info.append("Diesel: no se encontró fila de encabezado")

    # ─── SECCIÓN GASOLINA ─────────────────────────────────────────
    if idx_gasolina is not None:
        filas_gasolina = filas[idx_gasolina:]

        idx_header = _encontrar_encabezado(filas_gasolina,
            ["fecha", "litros", "costo", "odometro", "vehiculo", "km"])

        if idx_header is not None:
            header = filas_gasolina[idx_header]
            mapeo_gasolina = {
                "eco": ["vehiculo", "equipo", "eco", "id equipo", "maquina"],
                "fecha": ["fecha", "date"],
                "litros": ["litros cargados", "litros", "lts cargados"],
                "costo_total": ["costo total del combustible", "costo total", "costo"],
                "odometro_ini": ["odometro inicial", "odom ini", "km inicial"],
                "odometro_fin": ["odometro final", "odom fin", "km final"],
                "km_recorridos": ["km recorridos", "km", "kilometros"],
                "costo_litro": ["costo por litro", "costo litro", "$ lt"],
                "km_litro": ["km por litro", "km lt", "km litro"],
                "costo_km": ["costo por km", "costo km", "$ km"],
                "destino": ["destino", "frente de trabajo", "frente"],
                "actividad": ["actividad"],
                "origen": ["origen de carga", "origen carga", "origen"],
                "responsable": ["responsable", "operador", "chofer"],
                "observaciones": ["observaciones", "comentarios"],
                "folio": ["folio ticket", "folio", "ticket"],
            }
            col_map = _mapear_cols(header, mapeo_gasolina)
            debug_info.append(f"Gasolina: encabezado fila {idx_gasolina + idx_header + 1}, cols={list(col_map.keys())}")

            filas_datos = filas_gasolina[idx_header + 1:]
            for fila in filas_datos:
                if not fila or all(c is None or str(c).strip() == "" for c in fila):
                    continue
                try:
                    def _val_g(campo):
                        idx = col_map.get(campo)
                        if idx is None or idx >= len(fila):
                            return None
                        v = fila[idx]
                        if v is None or str(v).strip() in ("", "—", "-"):
                            return None
                        return v

                    eco_raw = _val_g("eco")
                    if not eco_raw:
                        continue
                    eco = str(eco_raw).strip().upper()

                    fecha = _limpiar_fecha(_val_g("fecha"))
                    if not fecha:
                        errores += 1
                        continue

                    litros = _limpiar_num(_val_g("litros"))
                    if not litros or litros <= 0:
                        errores += 1
                        continue

                    costo_total = _limpiar_num(_val_g("costo_total"))
                    o_ini = _limpiar_num(_val_g("odometro_ini"))
                    o_fin = _limpiar_num(_val_g("odometro_fin"))
                    km = _limpiar_num(_val_g("km_recorridos"))
                    if not km and o_ini and o_fin and o_fin > o_ini:
                        km = round(o_fin - o_ini, 2)

                    costo_litro = _limpiar_num(_val_g("costo_litro"))
                    if not costo_litro and costo_total and litros > 0:
                        costo_litro = round(costo_total / litros, 2)

                    km_litro = _limpiar_num(_val_g("km_litro"))
                    if not km_litro and km and litros > 0:
                        km_litro = round(km / litros, 3)

                    costo_km = _limpiar_num(_val_g("costo_km"))
                    if not costo_km and costo_total and km and km > 0:
                        costo_km = round(costo_total / km, 2)

                    # Buscar equipo en BD
                    maq = db.get_maquina(eco)
                    # Para gasolina no suele haber telemetría pero intentamos
                    t = db.telemetria_consumo_dia(eco, fecha)
                    tel = t.get("litros_consumidos") or 0

                    semana = semana_num
                    if not semana:
                        from datetime import datetime as _dtx
                        try:
                            fd = _dtx.strptime(fecha, "%Y-%m-%d").date()
                            semana = (fd - date(2025, 12, 29)).days // 7 + 1
                        except Exception:
                            semana = None

                    datos = {
                        "eco": eco,
                        "nombre_equipo": (maq or {}).get("nombre_equipo", ""),
                        "marca": (maq or {}).get("marca", ""),
                        "id_obra": id_obra,
                        "fecha": fecha,
                        "semana": semana,
                        "operador": str(_val_g("responsable") or ""),
                        "litros_cargados": litros,
                        "litros_telemetria": float(tel or 0),
                        "horas_maquina": None,
                        "observaciones": str(_val_g("observaciones") or ""),
                        "registrado_por": session["user_id"],
                        "tipo_combustible": "gasolina",
                        "costo_total": costo_total,
                        "costo_por_litro": costo_litro,
                        "odometro_inicial": o_ini,
                        "odometro_final": o_fin,
                        "km_recorridos": km,
                        "km_por_litro": km_litro,
                        "costo_por_km": costo_km,
                        "destino": str(_val_g("destino") or "") or None,
                        "actividad": str(_val_g("actividad") or "") or None,
                        "origen_carga": str(_val_g("origen") or "") or None,
                        "responsable": str(_val_g("responsable") or "") or None,
                        "folio_ticket": str(_val_g("folio") or "") or None,
                    }
                    db.crear_reporte_combustible(datos)
                    importados_gasolina += 1
                except Exception as exc:
                    errores += 1
                    if len(debug_info) < 5:
                        debug_info.append(f"  Error gasolina: {exc}")
        else:
            debug_info.append("Gasolina: no se encontró fila de encabezado")

    # ── Resultado ──
    total = importados_diesel + importados_gasolina
    if total == 0 and errores == 0:
        hojas_info = ", ".join(f"'{h}'" for h in wbi.sheetnames)
        msg_debug = " | ".join(debug_info) if debug_info else "No se detectaron secciones DIESEL/GASOLINA"
        flash(f"No se encontraron datos de combustible válidos. "
              f"Hojas: [{hojas_info}]. {msg_debug}. "
              f"El sistema busca las secciones 'DIESEL' y 'GASOLINA' dentro del archivo.",
              "warning")
    elif total == 0 and errores > 0:
        msg_debug = " | ".join(debug_info) if debug_info else ""
        flash(f"Se encontraron {errores} fila(s) pero ninguna pudo importarse. "
              f"Posibles causas: ECO no reconocido, fecha inválida o litros vacíos. {msg_debug}",
              "danger")
    else:
        msg_parts = []
        if importados_diesel:
            msg_parts.append(f"{importados_diesel} carga(s) de diesel")
        if importados_gasolina:
            msg_parts.append(f"{importados_gasolina} carga(s) de gasolina")
        msg = "Importación exitosa: " + ", ".join(msg_parts) + "."
        if errores:
            msg += f" ({errores} fila(s) omitidas por datos incompletos)"
        flash(msg, "success")

    return redirect(url_for("combustible"))


# ══════════════════════════════════════════════════════════════════
#  REPORTES 360 · ACARREO DE MATERIALES
# ══════════════════════════════════════════════════════════════════
@app.route("/acarreo")
@login_required
@permiso_requerido("acarreo", "leer")
def acarreo():
    obr = request.args.get("obra", "")
    sem = request.args.get("semana", "")
    obra_id = int(obr) if obr else None
    kpis     = db.get_kpis_acarreo(obra_id, sem or None)
    resumen  = db.get_resumen_acarreo(obra_id, sem or None)
    pagado   = db.get_pagado_acarreo(obra_id, sem or None)
    viajes   = db.get_viajes_acarreo(obra_id, sem or None, limit=100)
    user     = get_current_user()
    es_admin = (user["rol"] == "admin")
    if es_admin:
        obras = db.get_obras()
    else:
        obras_raw = db.get_obras_permitidas(user["id"], "acarreo", "leer")
        obras = [{"id": o["id_obra"], "nombre": o["obra_nombre"]} for o in obras_raw]
    semanas  = db.get_semanas_acarreo()
    return render_template("acarreo.html", kpis=kpis, resumen=resumen, pagado=pagado,
                           viajes=viajes, obras=obras, semanas=semanas,
                           materiales=db.MATERIALES_ACARREO, user=user,
                           obr=obr, sem=sem)

@app.route("/acarreo/nuevo", methods=["POST"])
@login_required
@permiso_requerido("acarreo", "crear")
@rol_minimo("reportes")
def acarreo_nuevo():
    user = get_current_user()
    obra_id = request.form.get("obra_id") or None
    db.insertar_viaje_acarreo(
        obra_id=int(obra_id) if obra_id else None,
        semana=request.form.get("semana"),
        fecha=request.form.get("fecha") or hoy_str(),
        material=request.form.get("material"),
        placa=request.form.get("placa"),
        origen=request.form.get("origen"),
        destino=request.form.get("destino"),
        volumen=request.form.get("volumen") or 0,
        folio_esma=request.form.get("folio_esma"),
        registrado_por=user["id"] if user else None,
    )
    flash("Viaje de acarreo registrado.", "success")
    return redirect(url_for("acarreo", obra=obra_id or "", semana=request.form.get("semana") or ""))

@app.route("/acarreo/pagado", methods=["POST"])
@login_required
@permiso_requerido("acarreo", "editar")
@rol_minimo("supervisor")
def acarreo_pagado():
    user = get_current_user()
    obra_id = request.form.get("obra_id") or None
    db.set_pagado_acarreo(
        obra_id=int(obra_id) if obra_id else None,
        semana=request.form.get("semana"),
        material=request.form.get("material"),
        m3_pagados=request.form.get("m3_pagados") or 0,
        actualizado_por=user["id"] if user else None,
    )
    flash("Volumen pagado actualizado.", "success")
    return redirect(url_for("acarreo", obra=obra_id or "", semana=request.form.get("semana") or ""))

# ══════════════════════════════════════════════════════════════════
#  REPORTES DE OBRA (subida de Excel por personal de obra)
# ══════════════════════════════════════════════════════════════════
REPORTES_OBRA_FOLDER = os.path.join(os.path.dirname(__file__), "uploads", "reportes_obra")
os.makedirs(REPORTES_OBRA_FOLDER, exist_ok=True)

@app.route("/reportes-obra")
@login_required
@permiso_requerido("reportes_obra", "leer")
def reportes_obra():
    user = get_current_user()
    es_admin = (user["rol"] == "admin")
    # Obras donde el usuario tiene permiso leer (admin ve todas)
    if es_admin:
        obras_permitidas = db.get_obras()
    else:
        obras_permitidas = db.get_obras_permitidas_reportes(user["id"], "leer")
        # Convertir a formato compatible con get_obras() [{id, nombre, ...}]
        obras_permitidas = [{"id": o["id_obra"], "nombre": o["obra_nombre"]} for o in obras_permitidas]
    ids_permitidos = {o["id"] for o in obras_permitidas}
    filtro_obra = request.args.get("obra", "")
    # Filtrar reportes solo de obras permitidas
    if filtro_obra and int(filtro_obra) in ids_permitidos:
        reportes = db.get_reportes_obra_excel(id_obra=int(filtro_obra), limit=100)
    elif not filtro_obra:
        reportes = db.get_reportes_obra_excel(id_obra=None, limit=100)
        reportes = [r for r in reportes if r["id_obra"] in ids_permitidos]
    else:
        reportes = []
    # Obras donde puede crear (para el modal de subir)
    if es_admin:
        obras_crear = db.get_obras()
    else:
        obras_crear_raw = db.get_obras_permitidas_reportes(user["id"], "crear")
        obras_crear = [{"id": o["id_obra"], "nombre": o["obra_nombre"]} for o in obras_crear_raw]
    # Semáforo: solo obras que el usuario puede ver
    obras_con_reporte = db.get_obras_con_reporte_reciente(dias=10)
    ultimo_por_obra = db.get_ultimo_reporte_por_obra()
    semaforo = []
    for ob in obras_permitidas:
        tiene = ob["id"] in obras_con_reporte
        ultimo = ultimo_por_obra.get(ob["id"])
        # Obtener link_drive de la obra
        obra_completa = db.get_obra(ob["id"]) if not ob.get("link_drive") else ob
        link_drive = (obra_completa or {}).get("link_drive") if obra_completa else ob.get("link_drive")
        semaforo.append({
            "id": ob["id"],
            "nombre": ob["nombre"],
            "tiene_reporte": tiene,
            "ultimo": ultimo,
            "link_drive": link_drive,
        })
    return render_template("reportes_obra.html", user=user, obras=obras_permitidas,
                           obras_crear=obras_crear, reportes=reportes,
                           semaforo=semaforo, filtro_obra=filtro_obra, es_admin=es_admin)


@app.route("/reportes-obra/subir", methods=["POST"])
@login_required
@permiso_requerido("reportes_obra", "crear")
def reportes_obra_subir():
    user = get_current_user()
    id_obra = request.form.get("id_obra")
    semana = request.form.get("semana", "").strip()
    notas = request.form.get("notas", "").strip()
    archivo = request.files.get("archivo")
    if not id_obra or not archivo or not archivo.filename:
        flash("Selecciona una obra y un archivo.", "danger")
        return redirect(url_for("reportes_obra"))
    # Verificar permiso crear en esa obra
    es_admin = (user["rol"] == "admin")
    if not es_admin and not db.usuario_puede_reportes_obra(user["id"], int(id_obra), "crear"):
        flash("No tienes permiso para subir reportes en esta obra.", "danger")
        return redirect(url_for("reportes_obra"))
    # Validar extensión (acepta excel, pdf, imágenes, etc)
    ext = os.path.splitext(archivo.filename)[1].lower()
    extensiones_permitidas = (".xlsx", ".xls", ".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png", ".zip", ".rar")
    if ext not in extensiones_permitidas:
        flash(f"Tipo de archivo no permitido. Extensiones válidas: {', '.join(extensiones_permitidas)}", "danger")
        return redirect(url_for("reportes_obra"))
    # Guardar archivo con nombre único
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre_disco = f"{ts}_{user['id']}_{archivo.filename}"
    ruta = os.path.join(REPORTES_OBRA_FOLDER, nombre_disco)
    archivo.save(ruta)
    db.crear_reporte_obra_excel(
        id_obra=int(id_obra),
        subido_por=user["id"],
        semana=semana or None,
        nombre_archivo=archivo.filename,
        archivo_disco=nombre_disco,
        notas=notas or None,
    )
    flash(f"Reporte '{archivo.filename}' subido correctamente.", "success")
    return redirect(url_for("reportes_obra"))


@app.route("/reportes-obra/descargar/<int:rid>")
@login_required
@permiso_requerido("reportes_obra", "leer")
def reportes_obra_descargar(rid):
    reporte = db.get_reporte_obra_excel_by_id(rid)
    if not reporte:
        abort(404)
    ruta = os.path.join(REPORTES_OBRA_FOLDER, reporte["archivo_disco"])
    if not os.path.exists(ruta):
        flash("Archivo no encontrado en el servidor.", "danger")
        return redirect(url_for("reportes_obra"))
    return send_file(ruta, as_attachment=True, download_name=reporte["nombre_archivo"])


@app.route("/permisos/permisos-obra", methods=["GET", "POST"])
@login_required
@rol_minimo("admin")
def reportes_obra_permisos():
    """Admin: asignar permisos por usuario por obra (todos los módulos)."""
    user = get_current_user()
    obras = db.get_obras()
    usuarios = db.get_usuarios()
    modulo_filtro = request.args.get("modulo", "")

    if request.method == "POST":
        action = request.form.get("action")
        if action == "guardar":
            id_usuario = int(request.form.get("id_usuario"))
            id_obra = int(request.form.get("id_obra"))
            modulo = request.form.get("modulo")
            crear = 1 if request.form.get("crear") else 0
            leer = 1 if request.form.get("leer") else 0
            editar = 1 if request.form.get("editar") else 0
            eliminar = 1 if request.form.get("eliminar") else 0
            db.guardar_permiso_usuario_obra(id_usuario, id_obra, modulo, crear, leer, editar, eliminar)
            flash("Permiso asignado correctamente.", "success")
        elif action == "eliminar":
            id_usuario = int(request.form.get("id_usuario"))
            id_obra = int(request.form.get("id_obra"))
            modulo = request.form.get("modulo")
            db.eliminar_permiso_usuario_obra(id_usuario, id_obra, modulo)
            flash("Permiso eliminado.", "success")
        return redirect(url_for("reportes_obra_permisos", modulo=modulo_filtro))

    permisos = db.get_todos_permisos_usuario_obra(modulo_filtro or None)
    return render_template("reportes_obra_permisos.html", user=user, obras=obras,
                           usuarios=usuarios, permisos=permisos,
                           modulos_por_obra=db.MODULOS_POR_OBRA,
                           modulo_filtro=modulo_filtro)


# ══════════════════════════════════════════════════════════════════
#  DOCUMENTOS
# ══════════════════════════════════════════════════════════════════
@app.route("/planta")
@login_required
@permiso_requerido("planta", "leer")
def planta():
    user = get_current_user()
    es_admin = (user["rol"] == "admin")
    rol = session.get("user_rol", "cliente")
    if es_admin:
        obras = db.get_obras()
    else:
        obras_raw = db.get_obras_permitidas(user["id"], "planta", "leer")
        obras = [{"id": o["id_obra"], "nombre": o["obra_nombre"]} for o in obras_raw]
    # Roles restringidos a obra: solo ven su obra asignada
    restringido_a_obra = (rol in db.ROLES_RESTRINGIDOS_A_OBRA)
    if restringido_a_obra and user.get("id_obra_asignada"):
        obr = str(user["id_obra_asignada"])
        obras = [o for o in obras if o["id"] == user["id_obra_asignada"]]
    else:
        obr = request.args.get("obra") or (str(user["id_obra_asignada"]) if user.get("id_obra_asignada") else "")
    if not obr and obras:
        obr = str(obras[0]["id"])
    id_obra = int(obr) if obr else None
    fi = request.args.get("fecha_ini", "")
    ff = request.args.get("fecha_fin", "")
    cfg = db.get_planta_config(id_obra) if id_obra else None
    stock = db.get_planta_stock_actual(id_obra) if id_obra else None
    alertas = db.get_planta_alertas(id_obra) if id_obra else []
    producciones = db.get_planta_producciones(id_obra, fi or None, ff or None) if id_obra else []
    return render_template("planta.html", user=user, obras=obras, obr=obr, cfg=cfg,
                           stock=stock, alertas=alertas, producciones=producciones,
                           restringido_a_obra=restringido_a_obra, fi=fi, ff=ff)

@app.route("/planta/config", methods=["GET","POST"])
@login_required
@permiso_requerido("planta", "editar")
def planta_config():
    user = get_current_user()
    es_admin = (user["rol"] == "admin")
    if es_admin:
        obras = db.get_obras()
    else:
        obras_raw = db.get_obras_permitidas(user["id"], "planta", "editar")
        obras = [{"id": o["id_obra"], "nombre": o["obra_nombre"]} for o in obras_raw]
    obr = request.args.get("obra") or request.form.get("id_obra") or (str(obras[0]["id"]) if obras else "")
    id_obra = int(obr)
    if request.method == "POST":
        f = request.form
        datos = {c: (f.get(c) or None) for c in db.PLANTA_CONFIG_DEFAULTS.keys()}
        db.guardar_planta_config(id_obra, datos)
        flash("Parámetros de planta actualizados.", "success")
        return redirect(url_for("planta", obra=id_obra))
    cfg = db.get_planta_config(id_obra)
    return render_template("planta_config_form.html", user=user, obras=obras, obr=obr, cfg=cfg)

@app.route("/planta/produccion/nueva", methods=["GET","POST"])
@login_required
@permiso_requerido("planta", "crear")
def planta_produccion_nueva():
    user = get_current_user()
    es_admin = (user["rol"] == "admin")
    if es_admin:
        obras = db.get_obras()
    else:
        obras_raw = db.get_obras_permitidas(user["id"], "planta", "crear")
        obras = [{"id": o["id_obra"], "nombre": o["obra_nombre"]} for o in obras_raw]
    obr = request.args.get("obra") or request.form.get("id_obra") or (str(obras[0]["id"]) if obras else "")
    id_obra = int(obr)
    if request.method == "POST":
        f = request.form
        campos_num = ["num_camiones","vol_m3","asf_ini","asf_desc","asf_final","alt_ini","alt_desc",
                      "alt_final","emu_ini","emu_desc","emu_final","grava_ini","grava_recib",
                      "arena_ini","arena_recib"]
        datos = {"id_obra": id_obra, "fecha": f["fecha"], "material": f.get("material"),
                  "creado_por": session["user_id"]}
        for c in campos_num:
            v = f.get(c)
            datos[c] = float(v) if v not in (None,"") else None
        db.crear_planta_produccion(datos)
        flash("Registro de producción guardado.", "success")
        return redirect(url_for("planta", obra=id_obra))
    return render_template("planta_produccion_form.html", user=user, obras=obras, obr=obr,
                           hoy=hoy_str())

@app.route("/planta/produccion/<int:pid>/validar", methods=["POST"])
@login_required
@permiso_requerido("planta", "editar")
def planta_produccion_validar(pid):
    db.validar_planta_produccion(pid)
    flash("Registro validado.", "success")
    return redirect(request.referrer or url_for("planta"))

@app.route("/planta/avance/nueva", methods=["GET","POST"])
@login_required
@permiso_requerido("planta", "crear")
def planta_avance_nueva():
    user = get_current_user()
    es_admin = (user["rol"] == "admin")
    if es_admin:
        obras = db.get_obras()
    else:
        obras_raw = db.get_obras_permitidas(user["id"], "planta", "crear")
        obras = [{"id": o["id_obra"], "nombre": o["obra_nombre"]} for o in obras_raw]
    obr = request.args.get("obra") or request.form.get("id_obra") or (str(obras[0]["id"]) if obras else "")
    id_obra = int(obr)
    if request.method == "POST":
        f = request.form
        datos = {"id_obra": id_obra, "fecha": f["fecha"], "carril": f.get("carril"),
                  "inicio": float(f["inicio"]), "termino": float(f["termino"]),
                  "ancho": float(f["ancho"]), "espesor": float(f["espesor"]),
                  "creado_por": session["user_id"]}
        db.crear_planta_avance(datos)
        flash("Avance físico registrado.", "success")
        return redirect(url_for("planta_avance", obra=id_obra))
    return render_template("planta_avance_form.html", user=user, obras=obras, obr=obr, hoy=hoy_str())

@app.route("/planta/avance")
@login_required
@permiso_requerido("planta", "leer")
def planta_avance():
    user = get_current_user()
    obras = db.get_obras()
    obr = request.args.get("obra") or (str(obras[0]["id"]) if obras else "")
    fi = request.args.get("fecha_ini", "")
    ff = request.args.get("fecha_fin", "")
    id_obra = int(obr) if obr else None
    avance = db.get_planta_avance(id_obra, fi or None, ff or None) if id_obra else []
    return render_template("planta_avance.html", user=user, obras=obras, obr=obr, avance=avance, fi=fi, ff=ff)

@app.route("/planta/remisiones")
@login_required
@permiso_requerido("planta", "leer")
def planta_remisiones():
    user = get_current_user()
    obras = db.get_obras()
    obr = request.args.get("obra") or (str(obras[0]["id"]) if obras else "")
    prod = request.args.get("producto") or ""
    fi = request.args.get("fecha_ini", "")
    ff = request.args.get("fecha_fin", "")
    id_obra = int(obr) if obr else None
    remisiones = db.get_planta_remisiones(id_obra, prod or None, fi or None, ff or None) if id_obra else []
    return render_template("planta_remisiones.html", user=user, obras=obras, obr=obr,
                           prod=prod, remisiones=remisiones, fi=fi, ff=ff)

@app.route("/planta/remisiones/nueva", methods=["GET","POST"])
@login_required
@permiso_requerido("planta", "crear")
def planta_remision_nueva():
    user = get_current_user()
    es_admin = (user["rol"] == "admin")
    if es_admin:
        obras = db.get_obras()
    else:
        obras_raw = db.get_obras_permitidas(user["id"], "planta", "crear")
        obras = [{"id": o["id_obra"], "nombre": o["obra_nombre"]} for o in obras_raw]
    obr = request.args.get("obra") or request.form.get("id_obra") or (str(obras[0]["id"]) if obras else "")
    id_obra = int(obr)
    if request.method == "POST":
        f = request.form
        # Calcular neto envío si no viene directo
        peso_bruto_envio = float(f["peso_bruto_envio"]) if f.get("peso_bruto_envio") else None
        tara_envio = float(f["tara_envio"]) if f.get("tara_envio") else None
        peso_neto_envio = float(f["peso_neto_envio"]) if f.get("peso_neto_envio") else None
        if not peso_neto_envio and peso_bruto_envio and tara_envio:
            peso_neto_envio = round(peso_bruto_envio - tara_envio, 2)
        datos = {"id_obra": id_obra, "producto": f.get("producto","asfalto"),
                  "proveedor": f.get("proveedor"), "fecha_llegada": f.get("fecha_llegada") or None,
                  "fecha_salida": f.get("fecha_salida") or None, "remision": f.get("remision"),
                  "certificado": f.get("certificado"), "placas_tracto": f.get("placas_tracto"),
                  "placas_tanque": f.get("placas_tanque"),
                  "peso_bruto_envio": peso_bruto_envio,
                  "tara_envio": tara_envio,
                  "peso_neto_envio": peso_neto_envio,
                  "peso_bruto_recibo": float(f["peso_bruto_recibo"]) if f.get("peso_bruto_recibo") else None,
                  "tara_recibo": float(f["tara_recibo"]) if f.get("tara_recibo") else None,
                  "precio_tonelada": float(f["precio_tonelada"]) if f.get("precio_tonelada") else None,
                  "creado_por": session["user_id"]}
        db.crear_planta_remision(datos)
        flash("Remisión registrada.", "success")
        return redirect(url_for("planta_remisiones", obra=id_obra, producto=datos["producto"]))
    return render_template("planta_remision_form.html", user=user, obras=obras, obr=obr, hoy=hoy_str())


# ══════════════════════════════════════════════════════════════════
#  PLANTA DE ASFALTO — IMPORTAR EXCEL (helpers)
# ══════════════════════════════════════════════════════════════════

def _normalizar_texto(txt):
    """Normaliza texto para comparación: quita acentos, puntuación, lower."""
    import unicodedata, re
    if not txt:
        return ""
    txt = str(txt).strip().lower()
    nfkd = unicodedata.normalize('NFKD', txt)
    txt = ''.join(c for c in nfkd if not unicodedata.combining(c))
    txt = re.sub(r'[^a-z0-9\s#³]', ' ', txt)
    txt = re.sub(r'\s+', ' ', txt).strip()
    return txt


def _convertir_fecha_excel(valor):
    """Convierte un valor de celda Excel a string 'YYYY-MM-DD'."""
    from datetime import datetime as _dt, date as _date, timedelta
    if valor is None:
        return None
    if isinstance(valor, _dt):
        return valor.strftime("%Y-%m-%d")
    if isinstance(valor, _date):
        return valor.strftime("%Y-%m-%d")
    if isinstance(valor, (int, float)):
        try:
            num = int(valor)
            if 40000 < num < 55000:
                base = _date(1899, 12, 30)
                return (base + timedelta(days=num)).strftime("%Y-%m-%d")
        except (ValueError, OverflowError):
            pass
    txt = str(valor).strip()
    if not txt or txt in ("", "\u2014", "-", "N/A", "n/a"):
        return None
    for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y",
                "%d/%m/%y", "%d-%m-%y", "%Y/%m/%d"]:
        try:
            return _dt.strptime(txt, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return txt


def _detectar_fila_encabezado(filas, palabras_clave):
    """Busca la primera fila que contenga al menos 2 de las palabras clave."""
    for idx, fila in enumerate(filas[:10]):
        if not fila:
            continue
        texto_unido = " | ".join(_normalizar_texto(c) for c in fila if c is not None)
        if sum(1 for kw in palabras_clave if kw in texto_unido) >= 2:
            return idx
    return 0


def _mapear_columnas(header_normalizada, mapeo):
    """Mapea columnas del encabezado a campos usando aliases normalizados."""
    col_map = {}
    for campo, aliases in mapeo.items():
        aliases_norm = [_normalizar_texto(a) for a in aliases]
        for i, h in enumerate(header_normalizada):
            if h in aliases_norm:
                col_map[campo] = i
                break
            if any(a in h for a in aliases_norm if len(a) >= 3):
                col_map[campo] = i
                break
            if any(h in a for a in aliases_norm if len(h) >= 4):
                col_map[campo] = i
                break
    return col_map


def _buscar_hoja(hojas_dict, aliases_nombre, wbi, palabras_clave_contenido=None):
    """Busca una hoja por nombre o por contenido."""
    for alias in aliases_nombre:
        alias_norm = _normalizar_texto(alias)
        for hoja_lower, hoja_real in hojas_dict.items():
            if alias_norm == _normalizar_texto(hoja_lower):
                return hoja_real
            if alias_norm in _normalizar_texto(hoja_lower):
                return hoja_real
    if palabras_clave_contenido:
        for hoja_real in wbi.sheetnames:
            try:
                ws = wbi[hoja_real]
                for row in ws.iter_rows(min_row=1, max_row=5, values_only=True):
                    texto_unido = " ".join(_normalizar_texto(c) for c in row if c is not None)
                    if sum(1 for kw in palabras_clave_contenido if kw in texto_unido) >= 2:
                        return hoja_real
            except Exception:
                continue
    return None


# ══════════════════════════════════════════════════════════════════
#  PLANTA DE ASFALTO — IMPORTAR EXCEL
#  Detecta hojas y columnas automáticamente, inserta en producción,
#  avance físico y/o remisiones según lo que contenga el archivo.
# ══════════════════════════════════════════════════════════════════
@app.route("/planta/importar-excel", methods=["POST"])
@login_required
@permiso_requerido("planta", "crear")
def planta_importar_excel():
    from openpyxl import load_workbook as lw
    user = get_current_user()
    id_obra = request.form.get("id_obra")
    archivo = request.files.get("archivo_excel")

    if not id_obra or not archivo or not archivo.filename:
        flash("Selecciona una obra y un archivo Excel.", "danger")
        return redirect(url_for("planta", obra=id_obra or ""))

    ext = os.path.splitext(archivo.filename)[1].lower()
    if ext not in (".xlsx", ".xls"):
        flash("Solo se aceptan archivos Excel (.xlsx, .xls).", "danger")
        return redirect(url_for("planta", obra=id_obra))

    id_obra = int(id_obra)

    try:
        wbi = lw(archivo, read_only=True, data_only=True)
    except Exception as e:
        flash(f"No se pudo leer el archivo: {e}", "danger")
        return redirect(url_for("planta", obra=id_obra))

    hojas = {h.lower().strip(): h for h in wbi.sheetnames}
    importados_prod = 0
    importados_avance = 0
    importados_remisiones = 0
    errores = 0
    debug_info = []

    # ─── PRODUCCIÓN ───────────────────────────────────────────────
    hoja_prod = _buscar_hoja(hojas,
        ["producción", "produccion", "prod", "production"],
        wbi,
        palabras_clave_contenido=["fecha", "vol", "asf", "camiones", "material"])
    # Si solo tiene una hoja y no encontró ninguna específica, asumir producción
    if not hoja_prod and len(wbi.sheetnames) == 1:
        hoja_prod = wbi.sheetnames[0]

    if hoja_prod:
        ws = wbi[hoja_prod]
        filas = list(ws.iter_rows(min_row=1, values_only=True))
        if filas and len(filas) >= 2:
            # Auto-detectar fila de encabezado
            idx_header = _detectar_fila_encabezado(filas, ["fecha", "material", "vol", "camiones", "asf"])
            header_raw = filas[idx_header]
            header_norm = [_normalizar_texto(c) for c in header_raw]
            debug_info.append(f"Producción: hoja='{hoja_prod}', encabezado en fila {idx_header+1}, cols={header_norm}")

            mapeo_prod = {
                "fecha": ["fecha", "date"],
                "material": ["material", "tipo material", "tipo"],
                "num_camiones": ["# camiones", "#camiones", "camiones", "num camiones", "no camiones", "num_camiones"],
                "vol_m3": ["vol m³", "vol m3", "vol_m3", "volumen", "volumen m3", "vol  m3"],
                "asf_ini": ["asf ini", "asf ini lt", "asf_ini", "asfalto inicial", "asfalto ini"],
                "asf_desc": ["asf desc", "asf desc lt", "asf_desc", "descarga asfalto", "asfalto descarga"],
                "asf_final": ["asf final", "asf final lt", "asf_final", "asfalto final"],
                "alt_ini": ["alt ini", "alt ini lt", "alt_ini", "alterno inicial", "comb alt ini"],
                "alt_desc": ["alt desc", "alt desc lt", "alt_desc", "alterno descarga", "comb alt desc"],
                "alt_final": ["alt final", "alt final lt", "alt_final", "alterno final", "comb alt final"],
                "emu_ini": ["emu ini", "emu ini lt", "emu_ini", "emulsion inicial"],
                "emu_desc": ["emu desc", "emu desc lt", "emu_desc", "emulsion descarga"],
                "emu_final": ["emu final", "emu final lt", "emu_final", "emulsion final"],
                "grava_ini": ["grava ini", "grava inicial", "grava_ini"],
                "grava_recib": ["grava recib", "grava recibida", "grava_recib"],
                "arena_ini": ["arena ini", "arena inicial", "arena_ini"],
                "arena_recib": ["arena recib", "arena recibida", "arena_recib"],
            }
            col_map_prod = _mapear_columnas(header_norm, mapeo_prod)
            debug_info.append(f"  Columnas mapeadas: {col_map_prod}")

            # Si no encontró "fecha", intentar detectar por posición (primera col con datos tipo fecha)
            if "fecha" not in col_map_prod:
                for i, h in enumerate(header_norm):
                    if "fecha" in h or "date" in h or "dia" in h:
                        col_map_prod["fecha"] = i
                        break

            filas_datos = filas[idx_header + 1:]
            for fila in filas_datos:
                if not fila or all(c is None or str(c).strip() == "" for c in fila):
                    continue
                try:
                    idx_fecha = col_map_prod.get("fecha")
                    if idx_fecha is None or idx_fecha >= len(fila):
                        errores += 1
                        continue
                    valor_fecha = fila[idx_fecha]
                    fecha = _convertir_fecha_excel(valor_fecha)
                    if not fecha:
                        errores += 1
                        continue

                    def _val_p(campo):
                        idx = col_map_prod.get(campo)
                        if idx is None or idx >= len(fila):
                            return None
                        v = fila[idx]
                        if v is None or str(v).strip() in ("", "\u2014", "-"):
                            return None
                        return v

                    def _num_p(campo):
                        v = _val_p(campo)
                        if v is None:
                            return None
                        try:
                            return float(v)
                        except (ValueError, TypeError):
                            return None

                    datos = {
                        "id_obra": id_obra, "fecha": fecha,
                        "material": str(_val_p("material") or ""),
                        "num_camiones": _num_p("num_camiones"),
                        "vol_m3": _num_p("vol_m3"),
                        "asf_ini": _num_p("asf_ini"),
                        "asf_desc": _num_p("asf_desc"),
                        "asf_final": _num_p("asf_final"),
                        "alt_ini": _num_p("alt_ini"),
                        "alt_desc": _num_p("alt_desc"),
                        "alt_final": _num_p("alt_final"),
                        "emu_ini": _num_p("emu_ini"),
                        "emu_desc": _num_p("emu_desc"),
                        "emu_final": _num_p("emu_final"),
                        "grava_ini": _num_p("grava_ini"),
                        "grava_recib": _num_p("grava_recib"),
                        "arena_ini": _num_p("arena_ini"),
                        "arena_recib": _num_p("arena_recib"),
                        "creado_por": session["user_id"],
                    }
                    db.crear_planta_produccion(datos)
                    importados_prod += 1
                except Exception as exc:
                    errores += 1
                    if len(debug_info) < 10:
                        debug_info.append(f"  Error fila: {exc}")

    # ─── AVANCE FÍSICO ────────────────────────────────────────────
    hoja_avance = _buscar_hoja(hojas,
        ["avance físico", "avance fisico", "avance", "advance"],
        wbi,
        palabras_clave_contenido=["fecha", "carril", "inicio", "termino", "ancho", "espesor"])

    if hoja_avance:
        ws = wbi[hoja_avance]
        filas = list(ws.iter_rows(min_row=1, values_only=True))
        if filas and len(filas) >= 2:
            idx_header = _detectar_fila_encabezado(filas, ["fecha", "carril", "inicio", "ancho", "espesor"])
            header_norm = [_normalizar_texto(c) for c in filas[idx_header]]
            debug_info.append(f"Avance: hoja='{hoja_avance}', encabezado fila {idx_header+1}")

            mapeo_av = {
                "fecha": ["fecha", "date"],
                "carril": ["carril", "lane", "cuerpo"],
                "inicio": ["inicio", "cadenamiento inicio", "cad inicio"],
                "termino": ["termino", "cadenamiento termino", "cad termino", "fin"],
                "ancho": ["ancho", "ancho m", "width"],
                "espesor": ["espesor", "espesor m", "thickness"],
            }
            col_map_av = _mapear_columnas(header_norm, mapeo_av)

            filas_datos = filas[idx_header + 1:]
            for fila in filas_datos:
                if not fila or all(c is None or str(c).strip() == "" for c in fila):
                    continue
                try:
                    idx_fecha = col_map_av.get("fecha")
                    fecha = _convertir_fecha_excel(fila[idx_fecha] if idx_fecha is not None and idx_fecha < len(fila) else None)
                    if not fecha:
                        errores += 1
                        continue

                    def _val_av(campo):
                        idx = col_map_av.get(campo)
                        if idx is None or idx >= len(fila):
                            return None
                        v = fila[idx]
                        if v is None or str(v).strip() in ("", "\u2014", "-"):
                            return None
                        return v

                    inicio = _val_av("inicio")
                    termino = _val_av("termino")
                    ancho = _val_av("ancho")
                    espesor = _val_av("espesor")
                    if not all([inicio, termino, ancho, espesor]):
                        errores += 1
                        continue

                    datos = {
                        "id_obra": id_obra, "fecha": fecha,
                        "carril": str(_val_av("carril") or ""),
                        "inicio": float(inicio), "termino": float(termino),
                        "ancho": float(ancho), "espesor": float(espesor),
                        "creado_por": session["user_id"],
                    }
                    db.crear_planta_avance(datos)
                    importados_avance += 1
                except Exception:
                    errores += 1

    # ─── REMISIONES ───────────────────────────────────────────────
    hoja_rem = _buscar_hoja(hojas,
        ["remisiones", "remision", "remisión", "receipts"],
        wbi,
        palabras_clave_contenido=["fecha", "remision", "proveedor", "peso", "placas"])

    if hoja_rem:
        ws = wbi[hoja_rem]
        filas = list(ws.iter_rows(min_row=1, values_only=True))
        if filas and len(filas) >= 2:
            idx_header = _detectar_fila_encabezado(filas, ["fecha", "proveedor", "remision", "peso", "placas"])
            header_norm = [_normalizar_texto(c) for c in filas[idx_header]]
            debug_info.append(f"Remisiones: hoja='{hoja_rem}', encabezado fila {idx_header+1}")

            mapeo_rem = {
                "fecha_llegada": ["fecha llegada", "fecha_llegada", "fecha recibo", "llegada", "fecha"],
                "fecha_salida": ["fecha salida", "fecha_salida", "salida"],
                "producto": ["producto", "tipo producto", "material"],
                "proveedor": ["proveedor", "supplier"],
                "remision": ["remision", "no remision", "factura"],
                "certificado": ["certificado", "cert calidad", "certificado de calidad"],
                "placas_tracto": ["placas tracto", "placas_tracto", "tracto"],
                "placas_tanque": ["placas tanque", "placas_tanque", "tanque"],
                "peso_bruto_envio": ["peso bruto envio", "bruto envio", "peso_bruto_envio"],
                "tara_envio": ["tara envio", "tara_envio"],
                "peso_neto_envio": ["neto envio", "peso neto envio", "peso_neto_envio"],
                "peso_bruto_recibo": ["peso bruto recibo", "bruto recibo", "peso_bruto_recibo"],
                "tara_recibo": ["tara recibo", "tara_recibo"],
                "precio_tonelada": ["precio por tonelada", "precio tonelada", "precio tn", "precio_tonelada"],
            }
            col_map_rem = _mapear_columnas(header_norm, mapeo_rem)

            filas_datos = filas[idx_header + 1:]
            for fila in filas_datos:
                if not fila or all(c is None or str(c).strip() == "" for c in fila):
                    continue
                try:
                    def _val_rem(campo):
                        idx = col_map_rem.get(campo)
                        if idx is None or idx >= len(fila):
                            return None
                        v = fila[idx]
                        if v is None or str(v).strip() in ("", "\u2014", "-"):
                            return None
                        return v

                    def _num_rem(campo):
                        v = _val_rem(campo)
                        if v is None:
                            return None
                        try:
                            return float(v)
                        except (ValueError, TypeError):
                            return None

                    fecha_llegada = _convertir_fecha_excel(_val_rem("fecha_llegada"))
                    fecha_salida = _convertir_fecha_excel(_val_rem("fecha_salida"))

                    prod_raw = str(_val_rem("producto") or "asfalto").lower().strip()
                    producto = "emulsion" if "emul" in prod_raw else "asfalto"

                    peso_neto_envio = _num_rem("peso_neto_envio")
                    peso_bruto_envio = _num_rem("peso_bruto_envio")
                    tara_envio = _num_rem("tara_envio")
                    if not peso_neto_envio and peso_bruto_envio and tara_envio:
                        peso_neto_envio = round(peso_bruto_envio - tara_envio, 2)

                    peso_bruto_recibo = _num_rem("peso_bruto_recibo")
                    tara_recibo = _num_rem("tara_recibo")

                    if not fecha_llegada and not peso_bruto_recibo:
                        errores += 1
                        continue

                    datos = {
                        "id_obra": id_obra, "producto": producto,
                        "proveedor": str(_val_rem("proveedor") or ""),
                        "fecha_llegada": fecha_llegada,
                        "fecha_salida": fecha_salida or None,
                        "remision": str(_val_rem("remision") or ""),
                        "certificado": str(_val_rem("certificado") or ""),
                        "placas_tracto": str(_val_rem("placas_tracto") or ""),
                        "placas_tanque": str(_val_rem("placas_tanque") or ""),
                        "peso_bruto_envio": peso_bruto_envio,
                        "tara_envio": tara_envio,
                        "peso_neto_envio": peso_neto_envio,
                        "peso_bruto_recibo": peso_bruto_recibo,
                        "tara_recibo": tara_recibo,
                        "precio_tonelada": _num_rem("precio_tonelada"),
                        "creado_por": session["user_id"],
                    }
                    db.crear_planta_remision(datos)
                    importados_remisiones += 1
                except Exception:
                    errores += 1

    # ── Resultado ──
    total = importados_prod + importados_avance + importados_remisiones
    if total == 0 and errores == 0:
        # No encontró nada — mostrar info de debug
        hojas_info = ", ".join(f"'{h}'" for h in wbi.sheetnames)
        msg_debug = " | ".join(debug_info) if debug_info else "No se detectaron hojas válidas"
        flash(f"No se encontraron datos válidos. Hojas en el archivo: [{hojas_info}]. "
              f"Detalle: {msg_debug}. "
              f"El sistema busca hojas con nombres como 'Producción', 'Avance Físico' o 'Remisiones', "
              f"o detecta automáticamente por contenido (columnas como 'Fecha', 'Material', 'Vol m3', etc).",
              "warning")
    elif total == 0 and errores > 0:
        # Encontró la hoja pero todas las filas fallaron
        hojas_info = ", ".join(f"'{h}'" for h in wbi.sheetnames)
        msg_debug = " | ".join(debug_info) if debug_info else ""
        flash(f"Se encontraron {errores} fila(s) pero ninguna pudo importarse. "
              f"Posibles causas: la columna 'Fecha' no fue detectada o tiene formato incorrecto. "
              f"Hojas: [{hojas_info}]. {msg_debug}",
              "danger")
    else:
        msg_parts = []
        if importados_prod:
            msg_parts.append(f"{importados_prod} registro(s) de producción")
        if importados_avance:
            msg_parts.append(f"{importados_avance} tramo(s) de avance físico")
        if importados_remisiones:
            msg_parts.append(f"{importados_remisiones} remisión(es)")
        msg = "Importación exitosa: " + ", ".join(msg_parts) + "."
        if errores:
            msg += f" ({errores} fila(s) omitidas por errores o datos incompletos)"
        flash(msg, "success")

    return redirect(url_for("planta", obra=id_obra))


@app.route("/documentos")
@login_required
@permiso_requerido("documentos", "leer")
def documentos():
    tipo       = request.args.get("tipo", "")
    search     = request.args.get("q", "")
    # Parámetros de navegación
    obra_id    = request.args.get("obra_id") or None
    carpeta_id = request.args.get("carpeta", "__none__")

    # Convertir obra_id a int
    oid_filter = int(obra_id) if obra_id else None

    # Convertir carpeta_id al filtro SQL
    if carpeta_id == "raiz":
        cid_filter = None          # documentos sin carpeta
    elif carpeta_id == "__none__":
        cid_filter = "__none__"    # todos
    else:
        try:    cid_filter = int(carpeta_id)
        except: cid_filter = "__none__"

    # Todas las carpetas (para construir el árbol completo en el panel)
    todas_carpetas = db.get_carpetas()
    user = get_current_user()
    es_admin = (user["rol"] == "admin")
    if es_admin:
        obras = db.get_obras()
    else:
        obras_raw = db.get_obras_permitidas(user["id"], "documentos", "leer")
        obras = [{"id": o["id_obra"], "nombre": o["obra_nombre"]} for o in obras_raw]
    maquinas       = db.get_maquinas()
    user           = get_current_user()

    # Documentos filtrados
    lista = db.get_documentos(
        tipo=tipo or None,
        search=search or None,
        id_obra=oid_filter if (carpeta_id == "__none__" and oid_filter) else None,
        id_carpeta=cid_filter
    )

    return render_template("documentos.html",
                           documentos=lista, obras=obras,
                           maquinas=maquinas, todas_carpetas=todas_carpetas,
                           user=user, tipo=tipo, search=search,
                           carpeta_activa=carpeta_id, obra_activa=obra_id or "")

@app.route("/documentos/subir", methods=["POST"])
@login_required
@permiso_requerido("documentos", "crear")
def subir_documento():
    archivo    = request.files.get("archivo")
    tipo       = request.form.get("tipo","otro")
    nombre     = request.form.get("nombre","")
    id_maquina = request.form.get("id_maquina") or None
    id_obra    = request.form.get("id_obra") or None
    id_carpeta = request.form.get("id_carpeta") or None
    if id_carpeta:
        try: id_carpeta = int(id_carpeta)
        except (ValueError, TypeError): id_carpeta = None
    if not archivo or archivo.filename == "":
        flash("Selecciona un archivo.", "danger")
        return redirect(request.referrer)
    fname= f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{archivo.filename}"
    archivo.save(os.path.join(UPLOAD_FOLDER, fname))
    db.crear_documento(tipo, nombre or archivo.filename, fname,
                       id_maquina, id_obra, session["user_id"], id_carpeta)
    flash("Documento subido correctamente.", "success")
    return redirect(request.referrer)

@app.route("/documentos/carpetas/nueva", methods=["POST"])
@login_required
@permiso_requerido("documentos", "crear")
def nueva_carpeta():
    nombre   = request.form.get("nombre","").strip()
    padre_id = request.form.get("padre_id") or None
    id_obra  = request.form.get("id_obra") or None
    if padre_id:
        try: padre_id = int(padre_id)
        except (ValueError, TypeError): padre_id = None
    if id_obra:
        try: id_obra = int(id_obra)
        except (ValueError, TypeError): id_obra = None
    if not nombre:
        flash("Escribe un nombre para la carpeta.", "danger")
    else:
        db.crear_carpeta(nombre, padre_id, id_obra)
        flash(f"Carpeta '{nombre}' creada.", "success")
    return redirect(request.referrer or url_for("documentos"))

@app.route("/documentos/carpetas/<int:cid>/eliminar", methods=["POST"])
@login_required
@permiso_requerido("documentos", "eliminar")
def eliminar_carpeta(cid):
    db.eliminar_carpeta(cid)
    flash("Carpeta eliminada.", "success")
    return redirect(url_for("documentos"))

@app.route("/documentos/<int:did>/descargar")
@login_required
def descargar_documento(did):
    doc = db.query("SELECT * FROM documentos WHERE id=%s", (did,), one=True)
    if not doc: abort(404)
    path = os.path.join(UPLOAD_FOLDER, doc["archivo"])
    if not os.path.exists(path): abort(404)
    
    # Extraemos la extensión del archivo real (ej. '.pdf', '.xlsx')
    _, extension = os.path.splitext(doc["archivo"])
    
    # Tomamos el nombre que le puso el usuario
    nombre_descarga = doc["nombre"]
    
    # Si el usuario no escribió la extensión en el nombre, se la agregamos automáticamente
    if not nombre_descarga.lower().endswith(extension.lower()):
        nombre_descarga += extension
        
    return send_file(path, as_attachment=True, download_name=nombre_descarga)


@app.route("/documentos/<int:did>/vista")
@login_required
def vista_documento(did):
    """Sirve el archivo inline para vista previa en el navegador."""
    doc = db.query("SELECT * FROM documentos WHERE id=%s", (did,), one=True)
    if not doc: abort(404)
    path = os.path.join(UPLOAD_FOLDER, doc["archivo"])
    if not os.path.exists(path): abort(404)
    return send_file(path, as_attachment=False)

@app.route("/documentos/<int:did>/editar", methods=["GET","POST"])
@login_required
@permiso_requerido("documentos", "editar")
def editar_documento(did):
    doc = db.query("SELECT * FROM documentos WHERE id=%s", (did,), one=True)
    if not doc: abort(404)
    user = get_current_user()
    if request.method == "POST":
        f = request.form
        nombre = f.get("nombre", doc["nombre"])
        tipo = f.get("tipo", doc["tipo"])
        db.execute("UPDATE documentos SET nombre=%s, tipo=%s WHERE id=%s", (nombre, tipo, did))
        flash("Documento actualizado.", "success")
        return redirect(request.form.get("next") or url_for("documentos"))
    # Determinar la URL de retorno
    next_url = request.referrer or url_for("documentos")
    return render_template("documento_editar.html", doc=doc, user=user, next_url=next_url)

@app.route("/documentos/<int:did>/eliminar", methods=["POST"])
@login_required
@permiso_requerido("documentos", "eliminar")
def eliminar_documento(did):
    doc = db.eliminar_documento(did)
    if doc:
        p = os.path.join(UPLOAD_FOLDER, doc["archivo"])
        if os.path.exists(p):
            try: os.remove(p)
            except OSError: pass
    flash("Documento eliminado.", "success")
    return redirect(request.referrer or url_for("documentos"))

# ══════════════════════════════════════════════════════════════════
#  MAQUINAS / EQUIPOS
# ══════════════════════════════════════════════════════════════════
@app.route("/maquinas")
@login_required
@permiso_requerido("equipos", "leer")
def maquinas():
    search = request.args.get("q","")
    clasif = request.args.get("clasificacion","")
    lista  = db.get_maquinas(search or None, clasif or None)
    obras  = db.get_obras()
    clasifs= db.get_clasificaciones()
    user   = get_current_user()

    # Enriquecer cada máquina con su último mantenimiento y semáforo
    ult_mants = db.get_ultimos_mantenimientos_todos()
    for m in lista:
        um = ult_mants.get(m["eco"])
        m["ultimo_mant"] = um
        m["sem_mant"] = db.calcular_semaforo_mantenimiento(
            m.get("horas_totales_horometro"),
            um["horometro"] if um else None
        )

    return render_template("maquinas.html", maquinas=lista, obras=obras,
                           clasifs=clasifs, search=search, clasificacion=clasif, user=user)

@app.route("/ficha/<eco>")
def ficha_publica(eco):
    """Ficha técnica pública del equipo — sin login, pensada para acceso por QR."""
    maq = db.get_maquina(eco)
    if not maq: abort(404)
    ultimo_mant = db.get_ultimo_mantenimiento(eco)
    sem_mant = db.calcular_semaforo_mantenimiento(
        maq.get("horas_totales_horometro"),
        ultimo_mant["horometro"] if ultimo_mant else None
    )
    mantenimientos = db.get_mantenimientos_maquina(eco)
    user = get_current_user()
    return render_template("ficha_publica.html", maq=maq, ultimo_mant=ultimo_mant,
                           sem_mant=sem_mant, mantenimientos=mantenimientos, user=user)

@app.route("/maquinas/<eco>")
@login_required
@permiso_requerido("equipos", "leer")
def maquina_detalle(eco):
    maq   = db.get_maquina(eco)
    if not maq: abort(404)
    # Filtro de fechas (default: últimos 30 días)
    fi = request.args.get("fecha_ini", "")
    ff = request.args.get("fecha_fin", "")
    if fi and ff:
        horas = _jsonable(db.get_horas_maquina_rango(eco, fi, ff))
        consu = _jsonable(db.get_consumo_maquina_rango(eco, fi, ff))
        reportes = db.get_reportes_maquina_rango(eco, fi, ff)
        try:
            cargas = _jsonable(db.get_cargas_detectadas(eco, fi, ff))
        except Exception:
            cargas = []
    else:
        horas = _jsonable(db.get_horas_maquina(eco, 30))
        consu = _jsonable(db.get_consumo_maquina(eco, 30))
        reportes = db.get_reportes_maquina(eco, 30)
        try:
            cargas = _jsonable(db.get_cargas_detectadas(eco))
        except Exception:
            cargas = []
    docs  = db.get_documentos(id_maquina=maq["id"])
    mantenimientos = db.get_mantenimientos_maquina(eco)
    ultimo_mant = db.get_ultimo_mantenimiento(eco)
    sem_mant = db.calcular_semaforo_mantenimiento(
        maq.get("horas_totales_horometro"),
        ultimo_mant["horometro"] if ultimo_mant else None
    )
    user  = get_current_user()
    try:
        historial_obras = db.get_historial_obras_equipo(eco)
    except Exception:
        historial_obras = []

    # Determinar permisos del usuario para este módulo (equipos).
    # Se verifica si tiene el permiso en CUALQUIER obra asignada,
    # no necesariamente la obra de esta máquina.
    # Admin siempre puede todo.
    puede_leer_graficas = True
    puede_crear_equipo = True
    puede_editar_equipo = True
    puede_eliminar_equipo = True
    if user["rol"] != "admin":
        puede_leer_graficas = False
        puede_crear_equipo = False
        puede_editar_equipo = False
        puede_eliminar_equipo = False
        perms_equipo = db.get_permisos_usuario_obra(user["id"], "equipos")
        for p in perms_equipo:
            if p.get("leer"):
                puede_leer_graficas = True
            if p.get("crear"):
                puede_crear_equipo = True
            if p.get("editar"):
                puede_editar_equipo = True
            if p.get("eliminar"):
                puede_eliminar_equipo = True

    return render_template("maquina_detalle.html", maq=maq, horas=horas,
                           consumo=consu, reportes=reportes, documentos=docs,
                           mantenimientos=mantenimientos, ultimo_mant=ultimo_mant,
                           sem_mant=sem_mant, user=user, historial_obras=historial_obras,
                           cargas=cargas, fi=fi, ff=ff,
                           puede_leer_graficas=puede_leer_graficas,
                           puede_crear_equipo=puede_crear_equipo,
                           puede_editar_equipo=puede_editar_equipo,
                           puede_eliminar_equipo=puede_eliminar_equipo,
                           historial_gps=_jsonable(db.get_historial_gps(eco, fi or None, ff or None)))

@app.route("/maquinas/<eco>/mantenimiento/nuevo", methods=["POST"])
@login_required
@permiso_requerido("equipos", "editar")
def mantenimiento_nuevo(eco):
    maq = db.get_maquina(eco)
    if not maq: abort(404)
    f = request.form
    user = get_current_user()
    db.crear_mantenimiento(
        eco,
        f.get("fecha") or hoy_str(),
        f.get("hora") or datetime.now().strftime("%H:%M"),
        f.get("horometro"),
        f.get("descripcion", ""),
        user["id"]
    )
    flash(f"Mantenimiento registrado para {eco}.", "success")
    return redirect(url_for("maquina_detalle", eco=eco))

@app.route("/maquinas/<eco>/mantenimiento/<int:mid>/editar", methods=["GET","POST"])
@login_required
@permiso_requerido("equipos", "editar")
def mantenimiento_editar(eco, mid):
    maq = db.get_maquina(eco)
    if not maq: abort(404)
    mt = db.get_mantenimiento(mid)
    if not mt: abort(404)
    user = get_current_user()
    if request.method == "POST":
        f = request.form
        db.actualizar_mantenimiento(
            mid,
            f.get("fecha") or str(mt["fecha"]),
            f.get("hora") or str(mt["hora"]),
            f.get("horometro") or mt["horometro"],
            f.get("descripcion", "")
        )
        flash(f"Mantenimiento actualizado para {eco}.", "success")
        return redirect(url_for("maquina_detalle", eco=eco))
    return render_template("mantenimiento_editar.html", maq=maq, mt=mt, user=user)

@app.route("/maquinas/<eco>/mantenimiento/<int:mid>/eliminar", methods=["POST"])
@login_required
@permiso_requerido("equipos", "eliminar")
def mantenimiento_eliminar(eco, mid):
    maq = db.get_maquina(eco)
    if not maq: abort(404)
    db.eliminar_mantenimiento(mid)
    flash(f"Mantenimiento eliminado para {eco}.", "success")
    return redirect(url_for("maquina_detalle", eco=eco))

@app.route("/maquinas/nueva", methods=["GET","POST"])
@login_required
@permiso_requerido("equipos", "crear")
@rol_minimo("supervisor")
def maquina_nueva():
    obras = db.get_obras()
    user  = get_current_user()
    if request.method == "POST":
        f = request.form
        eco = f["eco"].upper()
        serie = f.get("serie","").strip()
        # Validar unicidad de ECO y Serie
        conflictos = db.maquina_existe(eco=eco, serie=serie)
        if conflictos:
            for c in conflictos:
                flash(c, "danger")
            return render_template("maquina_form.html", maq=None, obras=obras, user=user, accion="Nueva")
        # Manejo de foto del equipo
        foto_nombre = None
        foto_archivo = request.files.get("foto")
        if foto_archivo and foto_archivo.filename:
            ext = os.path.splitext(foto_archivo.filename)[1].lower()
            foto_nombre = f"equipo_{eco}{ext}"
            foto_archivo.save(os.path.join(UPLOAD_FOLDER, foto_nombre))
        db.crear_maquina({
            "eco": eco, "proveedor": f.get("proveedor",""),
            "nombre_equipo": f["nombre_equipo"], "marca": f.get("marca",""),
            "modelo": f.get("modelo",""), "serie": serie,
            "anio": f.get("anio") or None, "clasificacion": f.get("clasificacion",""),
            "cantidad": int(f.get("cantidad",1)), "id_obra": f.get("id_obra") or None,
            "ubicacion": f.get("ubicacion",""), "link_ubicacion": f.get("link_ubicacion",""),
            "foto": foto_nombre,
        })
        flash(f"Máquina {eco} creada correctamente.", "success")
        return redirect(url_for("maquinas"))
    return render_template("maquina_form.html", maq=None, obras=obras, user=user, accion="Nueva")

@app.route("/maquinas/<eco>/editar", methods=["GET","POST"])
@login_required
@permiso_requerido("equipos", "editar")
def maquina_editar(eco):
    maq  = db.get_maquina(eco)
    if not maq: abort(404)
    obras = db.get_obras()
    user  = get_current_user()
    es_admin = (user["rol"] == "admin")
    if request.method == "POST":
        f = request.form
        if es_admin:
            serie = f.get("serie","").strip()
            conflictos = db.maquina_existe(serie=serie, excluir_eco=eco)
            if conflictos:
                for c in conflictos:
                    flash(c, "danger")
                adjuntos = db.get_documentos(id_maquina=maq["id"])
                return render_template("maquina_form.html", maq=maq, obras=obras, user=user, accion="Editar", adjuntos=adjuntos, es_admin=es_admin)
            foto_anterior = maq.get("foto")
            foto_nombre = foto_anterior
            foto_archivo = request.files.get("foto")
            if foto_archivo and foto_archivo.filename:
                ext = os.path.splitext(foto_archivo.filename)[1].lower()
                foto_nombre = f"equipo_{eco}{ext}"
                foto_archivo.save(os.path.join(UPLOAD_FOLDER, foto_nombre))
                if foto_anterior and foto_anterior != foto_nombre:
                    try:
                        os.remove(os.path.join(UPLOAD_FOLDER, foto_anterior))
                    except OSError:
                        pass
            if f.get("eliminar_foto") == "1":
                if foto_nombre:
                    try:
                        os.remove(os.path.join(UPLOAD_FOLDER, foto_nombre))
                    except OSError:
                        pass
                foto_nombre = None
            db.actualizar_maquina({
                "eco": eco, "proveedor": f.get("proveedor",""),
                "nombre_equipo": f["nombre_equipo"], "marca": f.get("marca",""),
                "modelo": f.get("modelo",""), "serie": serie,
                "anio": f.get("anio") or None, "clasificacion": f.get("clasificacion",""),
                "cantidad": int(f.get("cantidad",1)), "id_obra": f.get("id_obra") or None,
                "ubicacion": f.get("ubicacion",""), "link_ubicacion": f.get("link_ubicacion",""),
                "foto": foto_nombre, "capacidad_litros": None,
            })
            # Guardar capacidad del tanque en tabla estado (no en maquinas)
            cap_litros = f.get("capacidad_litros") or None
            if cap_litros:
                db.execute("UPDATE estado SET capacidad_litros=%s WHERE codigo_eco=%s",
                           (cap_litros, eco))
        else:
            # Non-admin solo puede cambiar ubicación, link y foto
            foto_anterior = maq.get("foto")
            foto_nombre = foto_anterior
            foto_archivo = request.files.get("foto")
            if foto_archivo and foto_archivo.filename:
                ext = os.path.splitext(foto_archivo.filename)[1].lower()
                foto_nombre = f"equipo_{eco}{ext}"
                foto_archivo.save(os.path.join(UPLOAD_FOLDER, foto_nombre))
                # Borrar foto anterior si es diferente
                if foto_anterior and foto_anterior != foto_nombre:
                    try:
                        os.remove(os.path.join(UPLOAD_FOLDER, foto_anterior))
                    except OSError:
                        pass
            if f.get("eliminar_foto") == "1":
                if foto_nombre:
                    try:
                        os.remove(os.path.join(UPLOAD_FOLDER, foto_nombre))
                    except OSError:
                        pass
                foto_nombre = None
            db.execute("""UPDATE maquinas SET ubicacion=%s, link_ubicacion=%s, foto=%s WHERE eco=%s""",
                       (f.get("ubicacion",""), f.get("link_ubicacion",""), foto_nombre, eco))
        flash("Máquina actualizada correctamente.", "success")
        return redirect(url_for("maquina_editar", eco=eco))
    adjuntos = db.get_documentos(id_maquina=maq["id"])
    return render_template("maquina_form.html", maq=maq, obras=obras, user=user, accion="Editar", adjuntos=adjuntos, es_admin=es_admin)

@app.route("/maquinas/<eco>/adjuntos/subir", methods=["POST"])
@login_required
@permiso_requerido("equipos", "editar")
def maquina_adjunto_subir(eco):
    """Sube uno o varios archivos PDF adjuntos al equipo."""
    maq = db.get_maquina(eco)
    if not maq: abort(404)
    archivos = request.files.getlist("adjuntos")
    count = 0
    for archivo in archivos:
        if archivo and archivo.filename:
            fname = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{archivo.filename}"
            archivo.save(os.path.join(UPLOAD_FOLDER, fname))
            nombre_display = request.form.get("nombre_adjunto") or archivo.filename
            db.crear_documento("adjunto_equipo", nombre_display, fname,
                               maq["id"], maq.get("id_obra"), session["user_id"])
            count += 1
    if count:
        flash(f"{count} archivo(s) adjuntado(s) al equipo.", "success")
    else:
        flash("Selecciona al menos un archivo.", "danger")
    return redirect(url_for("maquina_editar", eco=eco))

@app.route("/maquinas/exportar/excel")
@login_required
@permiso_requerido("equipos", "leer")
def maquinas_exportar_excel():
    search = request.args.get("q","")
    clasif = request.args.get("clasificacion","")
    lista  = db.get_maquinas(search or None, clasif or None)
    ult_mants = db.get_ultimos_mantenimientos_todos()

    wb = Workbook()
    ws = wb.active
    ws.title = "Equipos"
    FONT_HEADER = Font(bold=True, color="FFFFFF")
    FILL_HEADER = PatternFill("solid", fgColor="2E3192")
    ALIGN_C = Alignment(horizontal="center")

    headers = ["ECO", "Nombre / Tipo", "Proveedor", "Marca", "Modelo", "Serie",
               "Año", "Clasificación", "Obra asignada", "Ubicación",
               "Horómetro (h)", "Último mant. (h)", "Fecha últ. mant."]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.alignment = ALIGN_C

    for m in lista:
        um = ult_mants.get(m["eco"])
        ws.append([
            m["eco"],
            m.get("nombre_equipo") or "",
            m.get("proveedor") or "",
            m.get("marca") or "",
            m.get("modelo") or "",
            m.get("serie") or "",
            m.get("anio") or "",
            m.get("clasificacion") or "",
            m.get("obra_nombre") or "",
            m.get("ubicacion") or "",
            float(m["horas_totales_horometro"]) if m.get("horas_totales_horometro") else "",
            float(um["horometro"]) if um else "",
            str(um["fecha"]) if um else "",
        ])

    for col in ws.columns:
        mx = max((len(str(c.value or "")) for c in col), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(mx + 4, 42)

    nombre_archivo = f"Equipos_ESMA_{hoy_str()}.xlsx"
    ruta = os.path.join(UPLOAD_FOLDER, nombre_archivo)
    wb.save(ruta)
    return send_file(ruta, as_attachment=True, download_name=nombre_archivo)

@app.route("/maquinas/importar", methods=["POST"])
@login_required
@permiso_requerido("equipos", "crear")
@rol_minimo("supervisor")
def maquinas_importar_excel():
    """Importa equipos desde un archivo Excel. Omite filas con ECO o Serie duplicados."""
    from openpyxl import load_workbook as lw
    archivo = request.files.get("archivo_excel")
    if not archivo or archivo.filename == "":
        flash("Selecciona un archivo Excel.", "danger")
        return redirect(url_for("maquina_nueva"))

    try:
        wbi = lw(archivo, read_only=True, data_only=True)
        ws = wbi.active
    except Exception as e:
        flash(f"No se pudo leer el archivo Excel: {e}", "danger")
        return redirect(url_for("maquina_nueva"))

    # Detectar encabezados en la primera fila
    filas = list(ws.iter_rows(min_row=1, values_only=True))
    if not filas or len(filas) < 2:
        flash("El archivo está vacío o no tiene datos.", "danger")
        return redirect(url_for("maquina_nueva"))

    # Mapear columnas por nombre (case-insensitive)
    header = [str(c or "").strip().lower() for c in filas[0]]
    col_map = {
        "eco": None, "codigo eco": None, "código eco": None,
        "nombre": None, "nombre del equipo": None, "nombre equipo": None, "nombre / tipo": None,
        "proveedor": None, "marca": None, "modelo": None,
        "serie": None, "número de serie": None, "numero de serie": None,
        "año": None, "anio": None, "clasificacion": None, "clasificación": None,
        "cantidad": None, "ubicacion": None, "ubicación": None,
    }
    for i, h in enumerate(header):
        for key in col_map:
            if key in h:
                col_map[key] = i
                break

    # Determinar índice de cada campo
    def idx(keys):
        for k in keys:
            if col_map.get(k) is not None:
                return col_map[k]
        return None

    i_eco   = idx(["eco", "codigo eco", "código eco"])
    i_nombre= idx(["nombre", "nombre del equipo", "nombre equipo", "nombre / tipo"])
    i_prov  = idx(["proveedor"])
    i_marca = idx(["marca"])
    i_modelo= idx(["modelo"])
    i_serie = idx(["serie", "número de serie", "numero de serie"])
    i_anio  = idx(["año", "anio"])
    i_clasif= idx(["clasificacion", "clasificación"])
    i_cant  = idx(["cantidad"])
    i_ubic  = idx(["ubicacion", "ubicación"])

    if i_eco is None:
        flash("No se encontró la columna 'ECO' o 'Código ECO' en el archivo.", "danger")
        return redirect(url_for("maquina_nueva"))

    importados = 0
    omitidos = 0
    errores = 0

    for fila in filas[1:]:
        if not fila or all(c is None or str(c).strip() == "" for c in fila):
            continue  # fila vacía

        eco = str(fila[i_eco] or "").strip().upper()
        if not eco:
            errores += 1
            continue

        serie = str(fila[i_serie] or "").strip() if i_serie is not None else ""
        nombre = str(fila[i_nombre] or "").strip() if i_nombre is not None else ""

        # Verificar duplicados
        conflictos = db.maquina_existe(eco=eco, serie=serie)
        if conflictos:
            omitidos += 1
            continue

        # Insertar
        try:
            db.crear_maquina({
                "eco": eco,
                "proveedor": str(fila[i_prov] or "").strip() if i_prov is not None else "ESMA",
                "nombre_equipo": nombre,
                "marca": str(fila[i_marca] or "").strip() if i_marca is not None else "",
                "modelo": str(fila[i_modelo] or "").strip() if i_modelo is not None else "",
                "serie": serie,
                "anio": int(float(fila[i_anio])) if i_anio is not None and fila[i_anio] else None,
                "clasificacion": str(fila[i_clasif] or "").strip() if i_clasif is not None else "",
                "cantidad": int(float(fila[i_cant])) if i_cant is not None and fila[i_cant] else 1,
                "id_obra": None,
                "ubicacion": str(fila[i_ubic] or "").strip() if i_ubic is not None else "",
                "link_ubicacion": "",
                "foto": None,
            })
            importados += 1
        except Exception:
            errores += 1

    msg = f"Importación completada: {importados} equipo(s) agregado(s)."
    if omitidos:
        msg += f" Se omitieron {omitidos} porque ya existen (ECO o Serie duplicados)."
    if errores:
        msg += f" {errores} fila(s) con errores fueron ignoradas."
    flash(msg, "success" if importados > 0 else "warning")
    return redirect(url_for("maquinas"))

# ══════════════════════════════════════════════════════════════════
#  MAPA
# ══════════════════════════════════════════════════════════════════
@app.route("/mapa")
@login_required
@permiso_requerido("mapa", "leer")
def mapa():
    user = get_current_user()
    return render_template("mapa.html", user=user)


# ── MAPA DE OBRAS (KML) ──────────────────────────────────────────

@app.route("/mapa-obras")
@login_required
def mapa_obras():
    user = get_current_user()
    return render_template("mapa_obras.html", user=user)


@app.route("/mapa-obras/exportar-kml", methods=["POST"])
@login_required
def mapa_obras_exportar_kml():
    """Convierte GeoJSON a KML y lo devuelve como descarga."""
    data = request.get_json()
    if not data or not data.get("features"):
        return "No hay elementos", 400

    # Generar KML desde GeoJSON
    kml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        '<Document>',
        '<name>Mapa de Obras - ESMA</name>',
        '<description>Exportado desde plataforma ESMA</description>',
        '<Style id="estilo_linea"><LineStyle><color>ff923E2E</color><width>3</width></LineStyle></Style>',
        '<Style id="estilo_poly"><LineStyle><color>ff923E2E</color><width>2</width></LineStyle><PolyStyle><color>33923E2E</color></PolyStyle></Style>',
        '<Style id="estilo_punto"><IconStyle><color>ff923E2E</color><scale>1.1</scale></IconStyle></Style>',
    ]

    for feat in data.get("features", []):
        geom = feat.get("geometry", {})
        props = feat.get("properties", {})
        nombre = props.get("name", "") or "Sin nombre"
        tipo_geom = geom.get("type", "")
        coords = geom.get("coordinates", [])

        kml_lines.append("<Placemark>")
        kml_lines.append(f"<name>{nombre}</name>")

        if tipo_geom == "Point":
            kml_lines.append("<styleUrl>#estilo_punto</styleUrl>")
            kml_lines.append("<Point>")
            kml_lines.append(f"<coordinates>{coords[0]},{coords[1]},0</coordinates>")
            kml_lines.append("</Point>")

        elif tipo_geom == "LineString":
            kml_lines.append("<styleUrl>#estilo_linea</styleUrl>")
            kml_lines.append("<LineString><tessellate>1</tessellate><coordinates>")
            coord_str = " ".join(f"{c[0]},{c[1]},0" for c in coords)
            kml_lines.append(coord_str)
            kml_lines.append("</coordinates></LineString>")

        elif tipo_geom == "Polygon":
            kml_lines.append("<styleUrl>#estilo_poly</styleUrl>")
            kml_lines.append("<Polygon><outerBoundaryIs><LinearRing><coordinates>")
            ring = coords[0] if coords else []
            coord_str = " ".join(f"{c[0]},{c[1]},0" for c in ring)
            kml_lines.append(coord_str)
            kml_lines.append("</coordinates></LinearRing></outerBoundaryIs></Polygon>")

        kml_lines.append("</Placemark>")

    kml_lines.append("</Document>")
    kml_lines.append("</kml>")

    kml_content = "\n".join(kml_lines)
    from io import BytesIO
    buf = BytesIO(kml_content.encode("utf-8"))
    buf.seek(0)
    return send_file(buf, mimetype="application/vnd.google-earth.kml+xml",
                     download_name="mapa_obras.kml", as_attachment=True)

# ══════════════════════════════════════════════════════════════════
#  OBRAS
# ══════════════════════════════════════════════════════════════════
@app.route("/obras")
@login_required
@permiso_requerido("obras", "leer")
def obras():
    ver = request.args.get("ver", "vigentes")
    lista = db.get_obras(archivada=(1 if ver == "archivadas" else 0))
    user  = get_current_user()
    return render_template("obras.html", obras=lista, user=user, ver=ver)

@app.route("/obras/<int:oid>")
@login_required
@permiso_requerido("obras", "leer")
def obra_detalle(oid):
    obra     = db.get_obra(oid)
    if not obra: abort(404)
    equipos  = db.get_equipos_obra(oid)
    docs          = db.get_documentos(id_obra=oid, id_carpeta="__all__")
    maquinas_disp = db.get_maquinas_para_asignar(oid)
    carpetas_obra = db.get_carpetas(id_obra=oid)
    try:
        equipo_proyecto = db.get_equipo_proyecto(oid)
    except Exception:
        equipo_proyecto = []
    usuarios_sistema = db.get_usuarios()
    user          = get_current_user()
    # Permisos específicos de este usuario para ESTA obra
    es_admin = (user["rol"] == "admin")
    if es_admin:
        perms_obra = {"documentos": {"crear": True, "leer": True, "editar": True, "eliminar": True},
                      "equipos": {"crear": True, "leer": True, "editar": True, "eliminar": True}}
    else:
        perms_obra = {}
        for mod in ["documentos", "equipos", "inspecciones", "incidentes", "registro"]:
            rows = db.get_permisos_usuario_obra(user["id"], mod)
            for p in rows:
                if p["id_obra"] == oid:
                    perms_obra[mod] = {"crear": bool(p["crear"]), "leer": bool(p["leer"]),
                                       "editar": bool(p["editar"]), "eliminar": bool(p["eliminar"])}
                    break
    return render_template("obra_detalle.html", obra=obra, equipos=equipos,
                           documentos=docs, maquinas_disp=maquinas_disp,
                           carpetas_obra=carpetas_obra, user=user,
                           equipo_proyecto=equipo_proyecto,
                           roles_equipo=db.ROLES_EQUIPO_PROYECTO,
                           usuarios_sistema=usuarios_sistema,
                           perms_obra=perms_obra)

# --- NUEVAS RUTAS PARA ASIGNAR/LIBERAR MÁQUINAS ---
@app.route("/obras/<int:oid>/asignar_maquina", methods=["POST"])
@login_required
@rol_minimo("operador")
def obra_asignar_maquina(oid):
    if not obra_permitida(oid):
        flash("Solo puedes administrar la obra que tienes asignada.", "danger")
        return redirect(url_for("obra_detalle", oid=oid))
    eco = request.form.get("eco")
    if eco:
        db.actualizar_obra_maquina(eco, oid)
        flash(f"Máquina {eco} transferida a esta obra exitosamente.", "success")
    return redirect(url_for("obra_detalle", oid=oid))

@app.route("/obras/<int:oid>/liberar_maquina", methods=["POST"])
@login_required
@rol_minimo("operador")
def obra_liberar_maquina(oid):
    if not obra_permitida(oid):
        flash("Solo puedes administrar la obra que tienes asignada.", "danger")
        return redirect(url_for("obra_detalle", oid=oid))
    eco = request.form.get("eco")
    if eco:
        db.actualizar_obra_maquina(eco, None)
        flash(f"Máquina {eco} liberada de esta obra.", "success")
    return redirect(url_for("obra_detalle", oid=oid))

# --- EQUIPO DEL PROYECTO ---
@app.route("/obras/<int:oid>/equipo/agregar", methods=["POST"])
@login_required
@rol_minimo("operador")
def obra_equipo_agregar(oid):
    if not obra_permitida(oid):
        flash("Solo puedes administrar la obra que tienes asignada.", "danger")
        return redirect(url_for("obra_detalle", oid=oid))
    f = request.form
    nombre = f.get("nombre","").strip()
    if not nombre:
        flash("El nombre del miembro es obligatorio.", "danger")
        return redirect(url_for("obra_detalle", oid=oid))
    db.crear_miembro_equipo(
        id_obra=oid,
        rol=f.get("rol","Otro"),
        nombre=nombre,
        correo=f.get("correo","").strip(),
        oficina=f.get("oficina","").strip(),
        movil=f.get("movil","").strip(),
    )
    flash(f"Miembro «{nombre}» agregado al equipo del proyecto.", "success")
    return redirect(url_for("obra_detalle", oid=oid))

@app.route("/obras/<int:oid>/equipo/<int:mid>/eliminar", methods=["POST"])
@login_required
@rol_minimo("operador")
def obra_equipo_eliminar(oid, mid):
    if not obra_permitida(oid):
        flash("Solo puedes administrar la obra que tienes asignada.", "danger")
        return redirect(url_for("obra_detalle", oid=oid))
    db.eliminar_miembro_equipo(mid)
    flash("Miembro eliminado del equipo.", "success")
    return redirect(url_for("obra_detalle", oid=oid))



@app.route("/obras/nueva", methods=["GET","POST"])
@login_required
@rol_minimo("admin")
def obra_nueva():
    # Superintendente de Obra y Administrador de Obra solo administran su obra
    # asignada; crear obras nuevas es exclusivo del Admin.
    user = get_current_user()
    if request.method == "POST":
        f = request.form
        db.crear_obra({
            "nombre": f["nombre"], "cliente": f.get("cliente",""),
            "ubicacion": f.get("ubicacion",""),
            "fecha_inicio": f.get("fecha_inicio") or None,
            "fecha_fin":    f.get("fecha_fin") or None,
            "estado":       f.get("estado","activa"),
        })
        flash("Obra creada correctamente.", "success")
        return redirect(url_for("obras"))
    return render_template("obra_form.html", obra=None, user=user, accion="Nueva")

@app.route("/obras/<int:oid>/editar", methods=["GET","POST"])
@login_required
@rol_minimo("operador")
def obra_editar(oid):
    obra = db.get_obra(oid)
    if not obra: abort(404)
    if not obra_permitida(oid):
        flash("Solo puedes administrar la obra que tienes asignada.", "danger")
        return redirect(url_for("obra_detalle", oid=oid))
    user = get_current_user()
    if request.method == "POST":
        f = request.form
        db.actualizar_obra({
            "id": oid, "nombre": f["nombre"], "cliente": f.get("cliente",""),
            "ubicacion": f.get("ubicacion",""),
            "fecha_inicio": f.get("fecha_inicio") or None,
            "fecha_fin":    f.get("fecha_fin") or None,
            "estado":       f.get("estado","activa"),
            "link_drive":   f.get("link_drive","").strip() or None,
        })
        flash("Obra actualizada.", "success")
        return redirect(url_for("obra_detalle", oid=oid))
    return render_template("obra_form.html", obra=obra, user=user, accion="Editar")

@app.route("/obras/<int:oid>/archivar", methods=["POST"])
@login_required
@rol_minimo("operador")
def obra_archivar(oid):
    obra = db.get_obra(oid)
    if not obra: abort(404)
    if not obra_permitida(oid):
        flash("Solo puedes administrar la obra que tienes asignada.", "danger")
        return redirect(url_for("obra_detalle", oid=oid))
    db.archivar_obra(oid)
    flash(f"Obra «{obra['nombre']}» movida al archivo histórico.", "success")
    return redirect(request.referrer or url_for("obras"))

@app.route("/obras/<int:oid>/desarchivar", methods=["POST"])
@login_required
@rol_minimo("operador")
def obra_desarchivar(oid):
    obra = db.get_obra(oid)
    if not obra: abort(404)
    if not obra_permitida(oid):
        flash("Solo puedes administrar la obra que tienes asignada.", "danger")
        return redirect(url_for("obra_detalle", oid=oid))
    db.desarchivar_obra(oid)
    flash(f"Obra «{obra['nombre']}» regresó a obras vigentes.", "success")
    return redirect(request.referrer or url_for("obras"))

# ══════════════════════════════════════════════════════════════════
#  INSPECCIONES
# ══════════════════════════════════════════════════════════════════
@app.route("/inspecciones")
@login_required
@permiso_requerido("inspecciones", "leer")
def inspecciones():
    fi  = request.args.get("fecha_ini", hace(30))
    ff  = request.args.get("fecha_fin", hoy_str())
    res = request.args.get("resultado", "")
    lista = db.get_inspecciones(fi, ff, res or None)
    user  = get_current_user()
    return render_template("inspecciones.html", inspecciones=lista, user=user,
                           fi=fi, ff=ff, res=res)

@app.route("/inspecciones/nueva", methods=["GET","POST"])
@login_required
@permiso_requerido("inspecciones", "crear")
@rol_minimo("reportes")
def inspeccion_nueva():
    user = get_current_user()
    obras = db.get_obras()
    maquinas = db.get_maquinas()
    if request.method == "POST":
        f = request.form
        folio = db.crear_inspeccion({
            "codigo_eco": f.get("codigo_eco","").upper() or None,
            "id_obra": f.get("id_obra") or None, "fecha": f["fecha"],
            "inspector": f.get("inspector",""), "tipo": f.get("tipo","rutinaria"),
            "resultado": f.get("resultado","conforme"), "severidad": f.get("severidad","bajo"),
            "hallazgos": f.get("hallazgos",""), "registrado_por": session["user_id"]})
        flash(f"Inspección {folio} registrada.", "success")
        return redirect(url_for("inspecciones"))
    return render_template("inspeccion_form.html", user=user, obras=obras,
                           maquinas=maquinas, hoy=hoy_str())

# ══════════════════════════════════════════════════════════════════
#  INCIDENTES
# ══════════════════════════════════════════════════════════════════
@app.route("/incidentes")
@login_required
@permiso_requerido("incidentes", "leer")
def incidentes():
    est = request.args.get("estado", "")
    sev = request.args.get("severidad", "")
    lista = db.get_incidentes(est or None, sev or None)
    user  = get_current_user()
    return render_template("incidentes.html", incidentes=lista, user=user, est=est, sev=sev)

@app.route("/incidentes/nuevo", methods=["GET","POST"])
@login_required
@permiso_requerido("incidentes", "crear")
@rol_minimo("reportes")
def incidente_nuevo():
    user = get_current_user()
    obras = db.get_obras()
    maquinas = db.get_maquinas()
    if request.method == "POST":
        f = request.form
        folio = db.crear_incidente({
            "codigo_eco": f.get("codigo_eco","").upper() or None,
            "id_obra": f.get("id_obra") or None, "fecha": f["fecha"],
            "tipo": f.get("tipo","operativo"), "descripcion": f.get("descripcion",""),
            "severidad": f.get("severidad","medio"), "estado": f.get("estado","abierto"),
            "responsable": f.get("responsable",""), "reportado_por": session["user_id"]})
        flash(f"Incidente {folio} registrado.", "success")
        return redirect(url_for("incidentes"))
    return render_template("incidente_form.html", user=user, obras=obras,
                           maquinas=maquinas, hoy=hoy_str())

@app.route("/incidentes/<int:iid>/estado", methods=["POST"])
@login_required
@permiso_requerido("incidentes", "editar")
@rol_minimo("supervisor")
def incidente_estado(iid):
    db.actualizar_estado_incidente(iid, request.form.get("estado","abierto"))
    flash("Estado del incidente actualizado.", "success")
    return redirect(request.referrer or url_for("incidentes"))

# ══════════════════════════════════════════════════════════════════
#  REGISTRO DIARIO
# ══════════════════════════════════════════════════════════════════
@app.route("/registro")
@login_required
@permiso_requerido("registro", "leer")
def registro():
    fi = request.args.get("fecha_ini", hace(14))
    ff = request.args.get("fecha_fin", hoy_str())
    lista = db.get_registros(fi, ff)
    user  = get_current_user()
    return render_template("registro.html", registros=lista, user=user, fi=fi, ff=ff)

@app.route("/registro/nuevo", methods=["GET","POST"])
@login_required
@permiso_requerido("registro", "crear")
@rol_minimo("reportes")
def registro_nuevo():
    user = get_current_user()
    obras = db.get_obras()
    if request.method == "POST":
        f = request.form
        db.crear_registro({
            "fecha": f["fecha"], "id_obra": f.get("id_obra") or None,
            "autor": f.get("autor",""), "clima": f.get("clima",""),
            "equipos_activos": f.get("equipos_activos") or None,
            "notas": f.get("notas",""), "registrado_por": session["user_id"]})
        flash("Registro diario guardado.", "success")
        return redirect(url_for("registro"))
    return render_template("registro_form.html", user=user, obras=obras, hoy=hoy_str())

# ══════════════════════════════════════════════════════════════════
#  USUARIOS (solo admin)
# ══════════════════════════════════════════════════════════════════
@app.route("/usuarios")
@login_required
@permiso_requerido("usuarios", "leer")
def usuarios():
    user = get_current_user()
    es_admin = (user["rol"] == "admin")
    if es_admin:
        lista = db.get_usuarios()
    else:
        # Non-admin solo se ve a sí mismo
        lista = [db.get_usuario_by_id(user["id"])]
    return render_template("usuarios.html", usuarios=lista, user=user, es_admin=es_admin)

@app.route("/usuarios/nuevo", methods=["GET","POST"])
@login_required
@rol_minimo("admin")
def usuario_nuevo():
    user = get_current_user()
    obras = db.get_obras()
    if request.method == "POST":
        f = request.form
        obra_asig = f.get("id_obra_asignada") or None
        try:
            db.crear_usuario(f["nombre"], f["email"], hash_pwd(f["password"]), f["rol"],
                             int(obra_asig) if obra_asig else None)
            flash("Usuario creado.", "success")
        except Exception as e:
            flash(f"Error al crear usuario: {e}", "danger")
            return render_template("usuario_form.html", u=None, user=user, accion="Nuevo",
                                   obras=obras, roles_restringidos=db.ROLES_RESTRINGIDOS_A_OBRA,
                                   todos_roles=db.get_roles_permisos())
        return redirect(url_for("usuarios"))
    return render_template("usuario_form.html", u=None, user=user, accion="Nuevo",
                           obras=obras, roles_restringidos=db.ROLES_RESTRINGIDOS_A_OBRA,
                           todos_roles=db.get_roles_permisos())

@app.route("/usuarios/<int:uid>/editar", methods=["GET","POST"])
@login_required
def usuario_editar(uid):
    u    = db.get_usuario_by_id(uid)
    user = get_current_user()
    es_admin = (user["rol"] == "admin")
    obras = db.get_obras()
    # Non-admin solo puede editarse a sí mismo
    if not es_admin and uid != user["id"]:
        flash("Solo puedes editar tu propio perfil.", "danger")
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        f = request.form
        if es_admin:
            # Admin puede cambiar todo
            obra_asig = f.get("id_obra_asignada") or None
            db.actualizar_usuario(uid, f["nombre"], f["email"], f["rol"], int(f.get("activo",1)),
                                  int(obra_asig) if obra_asig else None)
        else:
            # Non-admin solo puede cambiar nombre, email, contraseña
            db.actualizar_usuario(uid, f["nombre"], f["email"], u["rol"], 1, u.get("id_obra_asignada"))
        if f.get("password"):
            db.cambiar_password(uid, hash_pwd(f["password"]))
        flash("Usuario actualizado.", "success")
        # Actualizar sesión si se editó a sí mismo
        if uid == user["id"]:
            session["user_nombre"] = f["nombre"]
            session["user_email"] = f["email"]
        if es_admin:
            return redirect(url_for("usuarios"))
        else:
            return redirect(url_for("dashboard"))
    return render_template("usuario_form.html", u=u, user=user, accion="Editar",
                           obras=obras, roles_restringidos=db.ROLES_RESTRINGIDOS_A_OBRA,
                           todos_roles=db.get_roles_permisos(), es_admin=es_admin)

# ══════════════════════════════════════════════════════════════════
#  EXPORTAR EXCEL
# ══════════════════════════════════════════════════════════════════
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment


@app.route('/exportar')
@login_required
@permiso_requerido("exportar", "leer")
def exportar():
    user = get_current_user()
    # Traemos eco + nombre_equipo para mostrar etiqueta pero filtrar por ECO
    equipos = db.query("SELECT eco, serie FROM maquinas ORDER BY serie")
    obras   = db.get_obras()
    return render_template('exportar.html',
        hoy=hoy_str(),
        hace30=hace(30),
        equipos=equipos,
        obras=obras,
        user=user
    )

@app.route('/exportar/equipos_obra/<int:oid>')
@login_required
def equipos_por_obra(oid):
    """Devuelve JSON con los equipos asignados a una obra (para el selector dinámico)."""
    from flask import jsonify
    equipos = db.query(
        "SELECT eco, nombre_equipo, serie FROM maquinas WHERE id_obra=%s ORDER BY eco", (oid,))
    return jsonify(equipos)


# ══════════════════════════════════════════════════════════════════
#  EXPORTAR EXCEL
# ══════════════════════════════════════════════════════════════════


@app.route('/exportar/excel')
@login_required
@permiso_requerido("exportar", "leer")
def exportar_excel():
    tabla   = request.args.get('tabla')
    fi      = request.args.get('fecha_ini')
    ff      = request.args.get('fecha_fin')
    equipos = request.args.get('equipos', '')
    lista   = [e.strip() for e in equipos.split(',')] if equipos else []

    wb = Workbook()  # ← faltaba esto

    FONT_HEADER = Font(bold=True, color="FFFFFF")
    FILL_HEADER = PatternFill("solid", fgColor="1FBBA6")
    ALIGN_C     = Alignment(horizontal="center")
    SEM_FILL    = {
        "OK":               "3FB950",
        "Revisar":          "D29922",
        "Alerta":           "E8843A",
        "Fraude Probable":  "F85149"
    }

    def escribir_hoja(ws, encabezados, filas, col_semaforo=None):
        ws.append(encabezados)
        for cell in ws[1]:
            cell.font = FONT_HEADER
            cell.fill = FILL_HEADER
            cell.alignment = ALIGN_C
        for fila in filas:
            ws.append([str(v) if v is not None else "" for v in fila.values()])
            if col_semaforo and col_semaforo in fila:
                color = SEM_FILL.get(str(fila[col_semaforo]))
                if color:
                    idx = list(fila.keys()).index(col_semaforo) + 1
                    c = ws.cell(row=ws.max_row, column=idx)
                    c.fill = PatternFill("solid", fgColor=color)
                    c.font = Font(bold=True, color="FFFFFF")
        for col in ws.columns:
            mx = max((len(str(c.value or "")) for c in col), default=10)
            ws.column_dimensions[col[0].column_letter].width = min(mx + 4, 42)

    if tabla == "estado":
        ws = wb.active
        ws.title = "Estado Equipos"
        escribir_hoja(ws,
            ["ID","ECO","Serie","Equipo","Marca","Modelo","Última actualización",
             "Latitud","Longitud","Horómetro (hrs)","Nivel combustible (%)","Capacidad (L)"],
            db.get_estado_export(fi, ff, lista))

    elif tabla == "horas":
        ws = wb.active
        ws.title = "Horas Diarias"
        escribir_hoja(ws,
            ["ECO","Equipo","Marca","Modelo","Fecha","Hrs trabajadas",
             "Hrs motor conectado","Hrs ralentí","Motor desconectado"],
            db.get_horas_export(fi, ff, lista))
        

    

    elif tabla == "utilizacion":
        ws = wb.active
        ws.title = "Utilización"
        escribir_hoja(ws,
            ["ECO","Equipo","Marca","Modelo","Fecha",
             "Lts/Hr","Lts consumidos","Hrs máquina","Hrs ralentí"],
            db.get_utilizacion_export(fi, ff, lista))

    elif tabla == "combustible":
        ws = wb.active
        ws.title = "Reportes 360 Combustible"
        escribir_hoja(ws,
            ["ECO","Equipo","Marca","Obra","Fecha","Operador",
             "Lts cargados","Lts telemetría","Lts faltantes","Desviación %",
             "Semáforo","Justificado","Observaciones"],
            db.get_combustible_export(fi, ff, lista),
            col_semaforo="semaforo")

    elif tabla == "completo":
        wb.remove(wb.active)
        ws = wb.create_sheet("Estado")
        escribir_hoja(ws,
            ["ID","ECO","Serie","Equipo","Marca","Modelo","Últ. act.",
             "Lat","Lon","Horómetro","Nivel","Capacidad"],
            db.get_estado_export(fi, ff, lista))
        
        ws = wb.create_sheet("Horas")
        escribir_hoja(ws,
            ["ECO","Equipo","Marca","Modelo","Fecha","Hrs trab",
             "Hrs motor","Hrs ralentí","Motor desc"],
            db.get_horas_export(fi, ff, lista))
        ws = wb.create_sheet("Utilización")
        escribir_hoja(ws,
            ["ECO","Equipo","Marca","Modelo","Fecha",
             "Lts/Hr","Lts cons","Hrs máq","Hrs ralentí"],
            db.get_utilizacion_export(fi, ff, lista))
        ws = wb.create_sheet("Combustible 360")
        escribir_hoja(ws,
            ["ECO","Equipo","Marca","Obra","Fecha","Operador",
             "Lts cargados","Lts telemetría","Lts faltantes",
             "Desv %","Semáforo","Justif.","Obs"],
            db.get_combustible_export(fi, ff, lista),
            col_semaforo="semaforo")

    else:
        flash("Tabla no válida.", "danger")
        return redirect(url_for("exportar"))

    nombre_archivo = f"ESMA_{tabla}_{fi}_{ff}.xlsx"
    ruta = os.path.join(UPLOAD_FOLDER, nombre_archivo)
    wb.save(ruta)
    return send_file(ruta, as_attachment=True, download_name=nombre_archivo)

# ══════════════════════════════════════════════════════════════════
#  EXPORTAR EXCEL — PLANTA DE ASFALTO
# ══════════════════════════════════════════════════════════════════
@app.route('/planta/exportar/excel')
@login_required
@permiso_requerido("planta", "leer")
def planta_exportar_excel():
    seccion = request.args.get('seccion', 'produccion')
    obr = request.args.get('obra')
    if not obr:
        flash("Selecciona una obra.", "danger")
        return redirect(url_for("planta"))
    id_obra = int(obr)
    obra = db.get_obra(id_obra)
    obra_nombre = obra["nombre"] if obra else "obra"

    wb = Workbook()
    FONT_HEADER = Font(bold=True, color="FFFFFF")
    FILL_HEADER = PatternFill("solid", fgColor="2E3192")
    ALIGN_C = Alignment(horizontal="center")

    def auto_width(ws):
        for col in ws.columns:
            mx = max((len(str(c.value or "")) for c in col), default=10)
            ws.column_dimensions[col[0].column_letter].width = min(mx + 4, 42)

    if seccion == 'produccion':
        ws = wb.active
        ws.title = "Producción"
        headers = ["Fecha", "Material", "# Camiones", "Vol. m³",
                   "Asf. ini (lt)", "Asf. desc (lt)", "Asf. final (lt)", "Asf. cons (lt)",
                   "Rend. lts/m³", "Alt. cons (lt)", "Emu. cons (lt)",
                   "Grava final (m³)", "Arena final (m³)", "Abundamiento", "Validado"]
        ws.append(headers)
        for cell in ws[1]:
            cell.font = FONT_HEADER
            cell.fill = FILL_HEADER
            cell.alignment = ALIGN_C
        producciones = db.get_planta_producciones(id_obra)
        for p in producciones:
            ws.append([
                str(p.get("fecha", "")),
                p.get("material") or "",
                p.get("num_camiones") or "",
                float(p["vol_m3"]) if p.get("vol_m3") is not None else "",
                float(p["asf_ini"]) if p.get("asf_ini") is not None else "",
                float(p["asf_desc"] or 0) if p.get("asf_desc") is not None else "",
                float(p["asf_final"]) if p.get("asf_final") is not None else "",
                float(p["asf_cons"]) if p.get("asf_cons") is not None else "",
                float(p["asf_rend"]) if p.get("asf_rend") is not None else "",
                float(p["alt_cons"]) if p.get("alt_cons") is not None else "",
                float(p["emu_cons"]) if p.get("emu_cons") is not None else "",
                float(p["grava_final"]) if p.get("grava_final") is not None else "",
                float(p["arena_final"]) if p.get("arena_final") is not None else "",
                float(p["abundamiento"]) if p.get("abundamiento") is not None else "",
                "Sí" if p.get("validado") else "No",
            ])
        auto_width(ws)

    elif seccion == 'avance':
        ws = wb.active
        ws.title = "Avance Físico"
        headers = ["Fecha", "Carril", "Inicio", "Término", "Distancia (m)",
                   "Ancho (m)", "Área (m²)", "Espesor (m)",
                   "Vol. compacto (m³)", "Acumulado (m³)"]
        ws.append(headers)
        for cell in ws[1]:
            cell.font = FONT_HEADER
            cell.fill = FILL_HEADER
            cell.alignment = ALIGN_C
        avance = db.get_planta_avance(id_obra)
        for a in avance:
            ws.append([
                str(a.get("fecha", "")),
                a.get("carril") or "",
                float(a["inicio"]) if a.get("inicio") is not None else "",
                float(a["termino"]) if a.get("termino") is not None else "",
                float(a["distancia"]) if a.get("distancia") is not None else "",
                float(a["ancho"]) if a.get("ancho") is not None else "",
                float(a["area"]) if a.get("area") is not None else "",
                float(a["espesor"]) if a.get("espesor") is not None else "",
                float(a["vol_compacto"]) if a.get("vol_compacto") is not None else "",
                float(a["acumulado"]) if a.get("acumulado") is not None else "",
            ])
        auto_width(ws)

    elif seccion == 'remisiones':
        ws = wb.active
        ws.title = "Remisiones"
        prod_filtro = request.args.get('producto') or None
        headers = ["Fecha llegada", "Fecha salida", "Producto", "Proveedor",
                   "Remisión", "Certificado", "Placas tracto", "Placas tanque",
                   "Neto envío (tn)", "Neto recibo (tn)", "Diferencia (tn)",
                   "Merma", "Acumulado (tn)"]
        ws.append(headers)
        for cell in ws[1]:
            cell.font = FONT_HEADER
            cell.fill = FILL_HEADER
            cell.alignment = ALIGN_C
        remisiones = db.get_planta_remisiones(id_obra, prod_filtro)
        for r in remisiones:
            ws.append([
                str(r.get("fecha_llegada") or ""),
                str(r.get("fecha_salida") or ""),
                "Asfalto" if r.get("producto") == "asfalto" else "Emulsión",
                r.get("proveedor") or "",
                r.get("remision") or "",
                r.get("certificado") or "",
                r.get("placas_tracto") or "",
                r.get("placas_tanque") or "",
                float(r["peso_neto_envio"]) if r.get("peso_neto_envio") is not None else "",
                float(r["peso_neto_recibo"]) if r.get("peso_neto_recibo") is not None else "",
                float(r["diferencia"]) if r.get("diferencia") is not None else "",
                "Sí" if r.get("merma") else "No",
                float(r["tn_acumuladas"]) if r.get("tn_acumuladas") is not None else "",
            ])
        auto_width(ws)

    else:
        flash("Sección no válida.", "danger")
        return redirect(url_for("planta", obra=obr))

    # ── Agregar hoja Resumen KPIs y Alertas a todos los exports ──
    stock = db.get_planta_stock_actual(id_obra)
    alertas = db.get_planta_alertas(id_obra)

    ws_kpi = wb.create_sheet("Resumen KPIs")
    ws_kpi.append(["INDICADOR", "VALOR"])
    for cell in ws_kpi[1]:
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.alignment = ALIGN_C
    kpis_data = [
        ("Asfalto recibido (lt)", stock.get("asf_recibido", 0)),
        ("Consumo acumulado (kg)", stock.get("asf_consumo_acum_kg", 0)),
        ("Asfalto restante (lt)", stock.get("asf_final", 0)),
        ("Volumen producido (m³)", stock.get("vol_producido", 0)),
        ("Rendimiento promedio (lts/m³)", stock.get("asf_rend_prom") or "—"),
        ("Días con stock", stock.get("dias_stock_asf") or "—"),
        ("Grava restante (m³)", stock.get("grava_final") or 0),
        ("Arena restante (m³)", stock.get("arena_final") or 0),
        ("Combustible alterno restante (lt)", stock.get("alt_final", 0)),
        ("Emulsión restante (lt)", stock.get("emu_final", 0)),
    ]
    for ind, val in kpis_data:
        ws_kpi.append([ind, val])
    auto_width(ws_kpi)

    ws_al = wb.create_sheet("Alertas")
    ws_al.append(["INDICADOR", "ESTADO / VALOR ACTUAL", "ACCIÓN REQUERIDA", "NIVEL"])
    for cell in ws_al[1]:
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.alignment = ALIGN_C
    for a in alertas:
        ws_al.append([a["indicador"], a["valor"], a["accion"], a["nivel"]])
    auto_width(ws_al)

    nombre_archivo = f"Planta_{seccion}_{obra_nombre}_{hoy_str()}.xlsx".replace(" ", "_")
    ruta = os.path.join(UPLOAD_FOLDER, nombre_archivo)
    wb.save(ruta)
    return send_file(ruta, as_attachment=True, download_name=nombre_archivo)


@app.route("/dashboard/excel")
@login_required
def dashboard_exportar_excel():
    """Exporta los datos del dashboard a Excel con el rango de fechas seleccionado."""
    fi = request.args.get("fecha_ini", hace(7))
    ff = request.args.get("fecha_fin", hoy_str())
    
    wb = Workbook()
    FONT_HEADER = Font(bold=True, color="FFFFFF")
    FILL_HEADER = PatternFill("solid", fgColor="1c1e5e")
    ALIGN_C = Alignment(horizontal="center")
    
    # Hoja 1: Consumo por día
    ws = wb.active
    ws.title = "Consumo diario"
    consumo = db.query("""
        SELECT fecha, ROUND(SUM(litros_consumidos),2) AS litros_consumidos,
               ROUND(SUM(horas_maquina),2) AS horas_maquina
        FROM utilizacion WHERE fecha BETWEEN %s AND %s
        GROUP BY fecha ORDER BY fecha
    """, (fi, ff))
    ws.append(["Fecha", "Litros consumidos", "Horas máquina"])
    for cell in ws[1]:
        cell.font = FONT_HEADER; cell.fill = FILL_HEADER; cell.alignment = ALIGN_C
    for r in consumo:
        ws.append([str(r["fecha"]), float(r["litros_consumidos"] or 0), float(r["horas_maquina"] or 0)])
    
    # Hoja 2: Horas motor por día
    ws2 = wb.create_sheet("Horas motor")
    horas = db.query("""
        SELECT fecha, ROUND(SUM(horas_trabajadas),2) AS horas_trabajadas,
               ROUND(SUM(horas_ralenti),2) AS horas_ralenti
        FROM horas_diarias WHERE fecha BETWEEN %s AND %s
        GROUP BY fecha ORDER BY fecha
    """, (fi, ff))
    ws2.append(["Fecha", "Horas trabajadas", "Horas ralentí"])
    for cell in ws2[1]:
        cell.font = FONT_HEADER; cell.fill = FILL_HEADER; cell.alignment = ALIGN_C
    for r in horas:
        ws2.append([str(r["fecha"]), float(r["horas_trabajadas"] or 0), float(r["horas_ralenti"] or 0)])
    
    # Hoja 3: Top consumo
    ws3 = wb.create_sheet("Top consumo")
    top = db.query("""
        SELECT u.codigo_eco, m.nombre_equipo, m.marca,
               ROUND(SUM(u.litros_consumidos),1) AS total_litros,
               ROUND(AVG(u.litros_hora),2) AS promedio_lts_hora,
               ROUND(SUM(u.horas_maquina),1) AS total_horas
        FROM utilizacion u LEFT JOIN maquinas m ON m.eco=u.codigo_eco
        WHERE u.fecha BETWEEN %s AND %s
        GROUP BY u.codigo_eco, m.nombre_equipo, m.marca
        ORDER BY total_litros DESC LIMIT 20
    """, (fi, ff))
    ws3.append(["ECO", "Equipo", "Marca", "Total litros", "Promedio lts/hr", "Total horas"])
    for cell in ws3[1]:
        cell.font = FONT_HEADER; cell.fill = FILL_HEADER; cell.alignment = ALIGN_C
    for r in top:
        ws3.append([r["codigo_eco"], r["nombre_equipo"], r["marca"],
                    float(r["total_litros"] or 0), float(r["promedio_lts_hora"] or 0), float(r["total_horas"] or 0)])
    
    # Hoja 4: Resumen por obra
    ws4 = wb.create_sheet("Resumen por obra")
    resumen = db.get_resumen_combustible_obra(fi, ff)
    ws4.append(["Obra", "Reporte Telemetría", "Reporte Obra", "Diferencia cargas", "Equipos", "Consumo Telemetría", "Diferencia consumo"])
    for cell in ws4[1]:
        cell.font = FONT_HEADER; cell.fill = FILL_HEADER; cell.alignment = ALIGN_C
    for r in resumen:
        ws4.append([r["obra"], r["reporte_telemetria"], r["reporte_obra"], r["diferencia_carga"],
                    r["equipos"], r["consumo_telemetria"], r["diferencia_consumo"]])
    
    # Auto-width
    for ws_obj in wb.worksheets:
        for col in ws_obj.columns:
            mx = max((len(str(c.value or "")) for c in col), default=10)
            ws_obj.column_dimensions[col[0].column_letter].width = min(mx + 4, 40)
    
    nombre_archivo = f"Dashboard_ESMA_{fi}_a_{ff}.xlsx"
    ruta = os.path.join(UPLOAD_FOLDER, nombre_archivo)
    wb.save(ruta)
    return send_file(ruta, as_attachment=True, download_name=nombre_archivo)


# ══════════════════════════════════════════════════════════════════
#  API JSON
# ══════════════════════════════════════════════════════════════════
@app.route("/api/mapa")
@login_required
def api_mapa():
    filas = db.get_maquinas_mapa()
    salida = []
    for f in filas:
        lat, lon = f.get("latitud"), f.get("longitud")
        if lat is not None and lon is not None:
            f["latitud"]  = float(lat); f["longitud"] = float(lon)
            f["fuente_ubicacion"] = "gps"
        else:
            f["latitud"] = None; f["longitud"] = None
            f["fuente_ubicacion"] = "sin_ubicacion"
        if f.get("nivel_combustible") is not None:
            f["nivel_combustible"] = float(f["nivel_combustible"])
        if f.get("horas_totales_horometro") is not None:
            f["horas_totales_horometro"] = float(f["horas_totales_horometro"])
        f["fecha_ultima_actualizacion"] = str(f.get("fecha_ultima_actualizacion") or "")
        salida.append(f)
    return jsonify(salida)

@app.route("/api/kpis")
@login_required
def api_kpis():
    k = db.get_kpis()
    return jsonify({key:(float(v) if hasattr(v,"is_integer") or str(type(v))=="<class 'decimal.Decimal'>" else v) for key,v in k.items()})

@app.route("/api/estado")
@login_required
def api_estado():
    return jsonify(_jsonable(db.get_estado_equipos()))

@app.route("/api/consumo_semana")
@login_required
def api_consumo():
    fi = request.args.get("fecha_ini", "")
    ff = request.args.get("fecha_fin", "")
    obra = request.args.get("obra", "")
    if fi and ff:
        sql = """SELECT fecha, ROUND(SUM(litros_consumidos),2) AS litros_consumidos,
                   ROUND(SUM(horas_maquina),2) AS horas_maquina
            FROM utilizacion u"""
        params = []
        if obra:
            sql += " LEFT JOIN maquinas m ON m.eco=u.codigo_eco WHERE u.fecha BETWEEN %s AND %s AND m.id_obra=%s"
            params = [fi, ff, int(obra)]
        else:
            sql += " WHERE u.fecha BETWEEN %s AND %s"
            params = [fi, ff]
        sql += " GROUP BY u.fecha ORDER BY u.fecha"
        data = db.query(sql, params)
    else:
        if obra:
            data = db.query("""
                SELECT u.fecha, ROUND(SUM(u.litros_consumidos),2) AS litros_consumidos,
                       ROUND(SUM(u.horas_maquina),2) AS horas_maquina
                FROM utilizacion u LEFT JOIN maquinas m ON m.eco=u.codigo_eco
                WHERE u.fecha >= CURDATE() - INTERVAL 7 DAY AND m.id_obra=%s
                GROUP BY u.fecha ORDER BY u.fecha
            """, (int(obra),))
        else:
            data = db.get_consumo_semana()
    return jsonify(_jsonable(data))

@app.route("/api/horas_semana")
@login_required
def api_horas():
    fi = request.args.get("fecha_ini", "")
    ff = request.args.get("fecha_fin", "")
    obra = request.args.get("obra", "")
    if fi and ff:
        sql = """SELECT h.fecha, ROUND(SUM(h.horas_trabajadas),2) AS horas_trabajadas,
                   ROUND(SUM(h.horas_ralenti),2) AS horas_ralenti
            FROM horas_diarias h"""
        if obra:
            sql += " LEFT JOIN maquinas m ON m.eco=h.codigo_eco WHERE h.fecha BETWEEN %s AND %s AND m.id_obra=%s"
            params = [fi, ff, int(obra)]
        else:
            sql += " WHERE h.fecha BETWEEN %s AND %s"
            params = [fi, ff]
        sql += " GROUP BY h.fecha ORDER BY h.fecha"
        data = db.query(sql, params)
    else:
        if obra:
            data = db.query("""
                SELECT h.fecha, ROUND(SUM(h.horas_trabajadas),2) AS horas_trabajadas,
                       ROUND(SUM(h.horas_ralenti),2) AS horas_ralenti
                FROM horas_diarias h LEFT JOIN maquinas m ON m.eco=h.codigo_eco
                WHERE h.fecha >= CURDATE() - INTERVAL 7 DAY AND m.id_obra=%s
                GROUP BY h.fecha ORDER BY h.fecha
            """, (int(obra),))
        else:
            data = db.get_horas_semana()
    return jsonify(_jsonable(data))

@app.route("/api/top_consumo")
@login_required
def api_top():
    fi = request.args.get("fecha_ini", "")
    ff = request.args.get("fecha_fin", "")
    obra = request.args.get("obra", "")
    sql = """SELECT u.codigo_eco, m.nombre_equipo, m.marca, m.clasificacion,
               ROUND(SUM(u.litros_consumidos),1) AS total_litros,
               ROUND(AVG(u.litros_hora),2) AS promedio_lts_hora,
               ROUND(SUM(u.horas_maquina),1) AS total_horas
        FROM utilizacion u LEFT JOIN maquinas m ON m.eco=u.codigo_eco WHERE 1=1"""
    params = []
    if fi and ff:
        sql += " AND u.fecha BETWEEN %s AND %s"; params += [fi, ff]
    else:
        sql += " AND u.fecha >= CURDATE() - INTERVAL 7 DAY"
    if obra:
        sql += " AND m.id_obra=%s"; params.append(int(obra))
    sql += " GROUP BY u.codigo_eco, m.nombre_equipo, m.marca, m.clasificacion ORDER BY total_litros DESC LIMIT 10"
    data = db.query(sql, params)
    return jsonify(_jsonable(data))

@app.route("/api/resumen_combustible_obra")
@login_required
def api_resumen_combustible_obra():
    fi = request.args.get("fecha_ini", hace(30))
    ff = request.args.get("fecha_fin", hoy_str())
    obra = request.args.get("obra", "")
    data = db.get_resumen_combustible_obra(fi, ff)
    if obra:
        data = [d for d in data if str(d.get("obra","")).strip() != ""]
        # Filtrar por nombre de obra
        obra_obj = db.get_obra(int(obra))
        if obra_obj:
            data = [d for d in data if obra_obj["nombre"] in str(d.get("obra",""))]
    return jsonify(_jsonable(data))

@app.route("/api/cargas_semanal")
@login_required
def api_cargas_semanal():
    semanas = request.args.get("semanas", 8, type=int)
    obra = request.args.get("obra", "")
    id_obra = int(obra) if obra else None
    data = db.get_cargas_vs_reporte_semanal(semanas, id_obra)
    return jsonify(_jsonable(data))

@app.route("/api/combustible_tendencia")
@login_required
def api_comb_tend():
    fi = request.args.get("fecha_ini", hace(30))
    ff = request.args.get("fecha_fin", hoy_str())
    obra = request.args.get("obra", "") or None
    eco = request.args.get("eco", "") or None
    obra = int(obra) if obra else None
    return jsonify(_jsonable(db.get_combustible_tendencia(fi, ff, obra=obra, eco=eco)))

@app.route("/api/nivel_combustible/<eco>")
@login_required
def api_nivel_combustible(eco):
    """Historial de nivel de combustible (%) para gráfica detallada."""
    fi = request.args.get("fecha_ini", "")
    ff = request.args.get("fecha_fin", "")
    datos = db.get_historial_nivel_combustible(eco, fi or None, ff or None)
    return jsonify(_jsonable(datos))

def _jsonable(rows):
    import decimal, datetime as _dt
    out = []
    for r in rows:
        d = {}
        for k, v in r.items():
            if isinstance(v, decimal.Decimal): d[k] = float(v)
            elif isinstance(v, (_dt.date, _dt.datetime)): d[k] = str(v)
            else: d[k] = v
        out.append(d)
    return out

app.jinja_env.globals['logo_path'] = '/uploads/logo.png'

from flask import send_from_directory

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route("/api/telemetria", methods=["POST"])
def recibir_telemetria():
    data = request.get_json(silent=True)
    if not data: return jsonify({"error":"JSON inválido"}), 400
    eco = data.get("eco","").upper()
    if not eco: return jsonify({"error":"ECO requerido"}), 400
    base = {"eco":eco,"serie":data.get("serie",""),
        "nombre_equipo":data.get("nombre_equipo",""),"marca":data.get("marca",""),
        "modelo":data.get("modelo",""),"fecha":data.get("fecha"),
        "lat":data.get("latitud"),"lon":data.get("longitud"),
        "horometro":data.get("horas_totales_horometro"),
        "nivel_combustible":data.get("nivel_combustible"),
        "capacidad_litros":data.get("capacidad_litros")}
    db.insertar_estado(base)
    if data.get("horas_trabajadas") is not None:
        db.upsert_horas({"eco":eco,"serie":data.get("serie",""),
            "nombre_equipo":data.get("nombre_equipo",""),"marca":data.get("marca",""),
            "modelo":data.get("modelo",""),"fecha":data.get("fecha_dia"),
            "horas_trabajadas":data.get("horas_trabajadas"),
            "horas_motor_conectado":data.get("horas_motor_conectado"),
            "horas_ralenti":data.get("horas_ralenti"),
            "motor_desconectado":data.get("motor_desconectado")})
    if data.get("litros_consumidos") is not None:
        db.upsert_utilizacion({"eco":eco,"serie":data.get("serie",""),
            "nombre_equipo":data.get("nombre_equipo",""),"marca":data.get("marca",""),
            "modelo":data.get("modelo",""),"fecha":data.get("fecha_dia"),
            "litros_hora":data.get("litros_hora"),
            "litros_consumidos":data.get("litros_consumidos"),
            "horas_maquina":data.get("horas_maquina"),
            "horas_ralenti":data.get("horas_ralenti"),
            "ralenti_porcentaje":data.get("ralenti_porcentaje")})
    socketio.emit("actualizacion", {"eco":eco,
        "nivel_combustible":data.get("nivel_combustible"),
        "latitud":data.get("latitud"),"longitud":data.get("longitud"),
        "horometro":data.get("horas_totales_horometro")})
    return jsonify({"ok":True,"eco":eco})


# ══════════════════════════════════════════════════════════════════
#  PERMISOS CRUD POR ROL
# ══════════════════════════════════════════════════════════════════
@app.route("/permisos", methods=["GET", "POST"])
@login_required
@rol_minimo("admin")
def permisos():
    user = get_current_user()
    if request.method == "POST":
        f = request.form
        rol = f.get("rol")
        if rol and rol != "admin":  # admin siempre tiene todo, no se toca
            permisos_dict = {}
            for modulo, _ in db.MODULOS_PERMISOS:
                permisos_dict[modulo] = {
                    "crear":    1 if f.get(f"{modulo}_crear")    else 0,
                    "leer":     1 if f.get(f"{modulo}_leer")     else 0,
                    "editar":   1 if f.get(f"{modulo}_editar")   else 0,
                    "eliminar": 1 if f.get(f"{modulo}_eliminar") else 0,
                }
            db.guardar_permisos_rol(rol, permisos_dict)
            flash(f"Permisos del rol «{rol}» actualizados.", "success")
        else:
            flash("El rol admin siempre tiene acceso total.", "warning")
        return redirect(url_for("permisos") + f"?rol={rol}")

    rol_sel = request.args.get("rol", "supervisor")
    todos_roles = db.get_roles_permisos()
    todos   = db.get_todos_permisos()
    perms_rol = todos.get(rol_sel, {})
    roles_labels = db.get_roles_labels()
    roles_custom = db.get_roles_custom()
    return render_template("permisos.html",
                           user=user,
                           rol_sel=rol_sel,
                           roles=todos_roles,
                           modulos=db.MODULOS_PERMISOS,
                           acciones=db.ACCIONES,
                           perms=perms_rol,
                           todos=todos,
                           roles_labels=roles_labels,
                           roles_custom=roles_custom,
                           roles_base=db.ROLES_PERMISOS_BASE)


@app.route("/permisos/rol/nuevo", methods=["POST"])
@login_required
@rol_minimo("admin")
def rol_nuevo():
    nombre = request.form.get("nombre", "").strip()
    codigo = request.form.get("codigo", "").strip().lower()
    # Sanitizar código: solo letras, números y guion bajo
    import re
    codigo = re.sub(r'[^a-z0-9_]', '', codigo)
    if not nombre or not codigo:
        flash("Debes indicar un nombre y un código para el rol.", "danger")
        return redirect(url_for("permisos"))
    if codigo in db.ROLES_PERMISOS_BASE:
        flash("Ese código ya está reservado por un rol del sistema.", "danger")
        return redirect(url_for("permisos"))
    result = db.crear_rol_custom(codigo, nombre)
    if result:
        flash(f"Rol «{nombre}» creado exitosamente. Configura sus permisos.", "success")
        return redirect(url_for("permisos") + f"?rol={codigo}")
    else:
        flash("No se pudo crear el rol. Verifica que el código no esté duplicado.", "danger")
        return redirect(url_for("permisos"))


@app.route("/permisos/rol/<codigo>/eliminar", methods=["POST"])
@login_required
@rol_minimo("admin")
def rol_eliminar(codigo):
    if db.eliminar_rol_custom(codigo):
        flash(f"Rol «{codigo}» eliminado.", "success")
    else:
        flash("No se puede eliminar un rol del sistema.", "danger")
    return redirect(url_for("permisos"))

# ══════════════════════════════════════════════════════════════════
#  REQUISICIONES SEMANALES
# ══════════════════════════════════════════════════════════════════

@app.route("/requisiciones")
@login_required
@permiso_requerido("requisiciones", "leer")
def requisiciones():
    user = get_current_user()
    obras = db.get_obras()
    obra_filtro = request.args.get("obra", "")
    empresa_filtro = request.args.get("empresa", "")
    estatus_filtro = request.args.get("estatus", "")
    reqs = db.get_requisiciones(
        id_obra=int(obra_filtro) if obra_filtro else None,
        empresa=empresa_filtro or None,
        estatus=estatus_filtro or None
    )
    kpis = db.get_kpis_requisiciones(int(obra_filtro) if obra_filtro else None)
    return render_template("requisiciones.html", user=user, obras=obras,
                           requisiciones=reqs, kpis=kpis,
                           obra_filtro=obra_filtro, empresa_filtro=empresa_filtro,
                           estatus_filtro=estatus_filtro)

@app.route("/requisiciones/<int:rid>")
@login_required
@permiso_requerido("requisiciones", "leer")
def requisicion_detalle(rid):
    req = db.get_requisicion(rid)
    if not req: abort(404)
    user = get_current_user()
    partidas = db.get_partidas_requisicion(rid)
    nomina_imss = db.get_nomina_imss_requisicion(rid)
    nomina_sin = db.get_nomina_sin_imss_requisicion(rid)
    finiquitos = db.get_finiquitos_requisicion(rid)
    descansos = db.get_descansos_requisicion(rid)
    return render_template("requisicion_detalle.html", user=user, req=req,
                           partidas=partidas, nomina_imss=nomina_imss,
                           nomina_sin=nomina_sin, finiquitos=finiquitos,
                           descansos=descansos)

@app.route("/requisiciones/<int:rid>/aprobar", methods=["POST"])
@login_required
@permiso_requerido("requisiciones", "editar")
def requisicion_aprobar(rid):
    user = get_current_user()
    db.aprobar_requisicion(rid, user["id"])
    flash("Requisición aprobada.", "success")
    return redirect(url_for("requisicion_detalle", rid=rid))

@app.route("/requisiciones/<int:rid>/rechazar", methods=["POST"])
@login_required
@permiso_requerido("requisiciones", "editar")
def requisicion_rechazar(rid):
    user = get_current_user()
    obs = request.form.get("observaciones", "")
    db.rechazar_requisicion(rid, user["id"], obs)
    flash("Requisición rechazada.", "success")
    return redirect(url_for("requisicion_detalle", rid=rid))

@app.route("/requisiciones/<int:rid>/enviar", methods=["POST"])
@login_required
@permiso_requerido("requisiciones", "crear")
def requisicion_enviar(rid):
    db.enviar_requisicion(rid)
    flash("Requisición enviada a tesorería.", "success")
    return redirect(url_for("requisicion_detalle", rid=rid))

@app.route("/requisiciones/nueva", methods=["GET", "POST"])
@login_required
@permiso_requerido("requisiciones", "crear")
def requisicion_nueva():
    """Crear una requisicion semanal de forma manual."""
    user = get_current_user()
    obras = db.get_obras()
    if request.method == "GET":
        return render_template("requisicion_form.html", user=user, obras=obras,
                               categorias=db.CATEGORIAS_REQUISICION, codigos_costo=db.get_codigos_costo())
    f = request.form
    id_obra = int(f["id_obra"]) if f.get("id_obra") else None
    semana_num = int(f["semana_num"]) if f.get("semana_num") else None
    fecha_inicio = f.get("fecha_inicio") or None
    fecha_fin = f.get("fecha_fin") or None
    semana_str = None
    if fecha_inicio and semana_num:
        anio = fecha_inicio[:4]
        semana_str = f"{anio}-W{semana_num:02d}"
    elif semana_num:
        semana_str = f"W{semana_num}"

    req_id = db.crear_requisicion({
        "id_obra": id_obra,
        "empresa": f.get("empresa", "ESMA"),
        "semana": semana_str,
        "semana_num": semana_num,
        "fecha_inicio": fecha_inicio,
        "fecha_fin": fecha_fin,
        "residente": f.get("residente") or None,
        "total_solicitado": 0,
        "total_autorizado": 0,
        "estatus": "borrador",
        "observaciones": f.get("observaciones") or None,
        "id_codigo_costo": int(f["id_codigo_costo"]) if f.get("id_codigo_costo") else None,
        "creado_por": session["user_id"],
    })

    # Guardar partidas
    categorias_list = f.getlist("part_cat[]")
    proveedores_list = f.getlist("part_proveedor[]")
    conceptos_list = f.getlist("part_concepto[]")
    montos_list = f.getlist("part_monto[]")
    for i, concepto in enumerate(conceptos_list):
        cat = categorias_list[i] if i < len(categorias_list) else "Otros"
        prov = proveedores_list[i] if i < len(proveedores_list) else ""
        monto = float(montos_list[i]) if i < len(montos_list) and montos_list[i] else 0
        if not concepto.strip() and monto <= 0:
            continue
        db.crear_partida_requisicion({
            "id_requisicion": req_id,
            "categoria": cat,
            "proveedor": prov.strip() or None,
            "contacto_proveedor": None,
            "concepto": concepto.strip() or None,
            "periodo": None,
            "monto_solicitado": monto,
            "monto_autorizado": 0,
            "observaciones": None,
        })

    db._recalcular_totales_requisicion(req_id)
    flash("Requisicion creada exitosamente.", "success")
    return redirect(url_for("requisicion_detalle", rid=req_id))


@app.route("/requisiciones/importar", methods=["GET", "POST"])
@login_required
@permiso_requerido("requisiciones", "crear")
def requisicion_importar():
    """Importa requerimiento semanal completo desde Excel formato ESMA-GREMIAL.
    Parsea hojas: REQ, C-IMSS, S-IMSS, FINIQ."""
    user = get_current_user()
    obras = db.get_obras()

    if request.method == "GET":
        return render_template("requisicion_importar.html", user=user, obras=obras)

    from openpyxl import load_workbook
    import re

    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        flash("Selecciona un archivo Excel.", "danger")
        return redirect(url_for("requisicion_importar"))

    id_obra_form = request.form.get("id_obra") or None

    try:
        wb = load_workbook(archivo, data_only=True)
    except Exception as e:
        flash(f"Error al leer el archivo: {e}", "danger")
        return redirect(url_for("requisicion_importar"))

    hojas = {ws.title.upper().strip(): ws for ws in wb.worksheets}
    resultados = []

    def _parsear_semana_texto(ws):
        """Busca 'SEMANA DEL LUNES X DE MES AL DOMINGO Y DE MES DEL AÑO' en las primeras filas."""
        meses = {"ENERO":1,"FEBRERO":2,"MARZO":3,"ABRIL":4,"MAYO":5,"JUNIO":6,
                 "JULIO":7,"AGOSTO":8,"SEPTIEMBRE":9,"OCTUBRE":10,"NOVIEMBRE":11,"DICIEMBRE":12}
        semana_num = None
        fecha_ini = None
        fecha_fin = None
        for row in ws.iter_rows(min_row=1, max_row=15, values_only=True):
            for cell in row:
                val = str(cell or "")
                if "# SEMANA" in val.upper() or "SEMANA" == val.strip().upper():
                    # Número de semana en esta fila
                    for c in row:
                        if c and str(c).strip().isdigit():
                            semana_num = int(str(c).strip())
                            break
                m = re.search(r'SEMANA DEL\s+(?:LUNES\s+)?(\d+)\s+DE\s+(\w+)\s+AL\s+(?:DOMINGO\s+)?(\d+)\s+DE\s+(\w+)\s+DEL\s+(\d{4})', val, re.IGNORECASE)
                if m:
                    dia_ini = int(m.group(1))
                    mes_ini = meses.get(m.group(2).upper(), 1)
                    dia_fin = int(m.group(3))
                    mes_fin = meses.get(m.group(4).upper(), 1)
                    anio = int(m.group(5))
                    try:
                        fecha_ini = date(anio, mes_ini, dia_ini)
                        fecha_fin = date(anio, mes_fin, dia_fin)
                    except ValueError:
                        pass
        # Buscar semana_num en celdas si no se encontró
        if not semana_num:
            for row in ws.iter_rows(min_row=1, max_row=10, values_only=True):
                for i, cell in enumerate(row):
                    if cell and "SEMANA" in str(cell).upper() and i+1 < len(row):
                        nxt = row[i+1] if i+1 < len(row) else None
                        if nxt and str(nxt).strip().isdigit():
                            semana_num = int(str(nxt).strip())
                            break
        return semana_num, fecha_ini, fecha_fin

    def _float(val):
        if val is None: return 0.0
        try:
            s = str(val).replace("$","").replace(",","").replace(" ","").strip()
            if s in ("", "-", "- 0", "-0"): return 0.0
            return float(s)
        except (ValueError, TypeError):
            return 0.0

    # ── Procesar hojas REQ ──
    for empresa_key, hoja_name in [("ESMA", "REQ ESMA"), ("GREMIAL", "REQ GREMIAL")]:
        ws = hojas.get(hoja_name.upper())
        if not ws:
            continue
        semana_num, fecha_ini, fecha_fin = _parsear_semana_texto(ws)
        semana_str = f"{fecha_ini.year}-W{semana_num:02d}" if fecha_ini and semana_num else (f"W{semana_num}" if semana_num else None)

        id_obra = int(id_obra_form) if id_obra_form else None

        req_id = db.crear_requisicion({
            "id_obra": id_obra, "empresa": empresa_key,
            "semana": semana_str, "semana_num": semana_num,
            "fecha_inicio": fecha_ini.strftime("%Y-%m-%d") if fecha_ini else None,
            "fecha_fin": fecha_fin.strftime("%Y-%m-%d") if fecha_fin else None,
            "residente": None, "total_solicitado": 0, "total_autorizado": 0,
            "estatus": "borrador", "observaciones": None, "creado_por": user["id"],
        })

        # Parsear partidas: buscar filas con categorías y montos
        categoria_actual = "Otros"
        categorias_map = {"ADMINISTRACION": "Administración", "MANEJO Y ADMINISTRACION": "Administración",
                          "MAQUINARIA": "Maquinaria", "MATERIALES": "Materiales",
                          "SERVICIOS": "Servicios", "OTROS": "Otros", "COMISIONES": "Comisiones",
                          "FINIQUITOS": "Finiquitos"}

        # Extraer residente de las primeras filas
        residente_obra = None
        for row in ws.iter_rows(min_row=1, max_row=12, values_only=True):
            for cell in row:
                val = str(cell or "")
                if "Residente" in val or "RESIDENTE" in val:
                    # El residente suele estar en la siguiente celda o misma fila
                    for c in row:
                        c_str = str(c or "").strip()
                        if c_str and c_str not in val and "SELECCIONAR" not in c_str.upper() and len(c_str) > 5:
                            if not c_str.startswith("FECHA") and not c_str.startswith("Fernando"):
                                residente_obra = c_str
                                break
                    break
            if residente_obra:
                break
        # Actualizar residente en la requisicion
        if residente_obra:
            db.execute("UPDATE requisiciones SET residente=%s WHERE id=%s", (residente_obra, req_id))

        for row in ws.iter_rows(min_row=8, values_only=True):
            if not row or len(row) < 4:
                continue
            # Detectar cambio de categoría
            es_fila_categoria = False
            for i, cell in enumerate(row[:3]):
                val_upper = str(cell or "").strip().upper()
                for key, cat in categorias_map.items():
                    if val_upper.startswith(key):
                        categoria_actual = cat
                        es_fila_categoria = True
                        break
                if es_fila_categoria:
                    break

            # Detectar fila con monto (columnas: proveedor, concepto, _, solicitado, autorizado, total)
            proveedor = str(row[0] or "").strip() if row[0] else ""
            concepto = str(row[1] or "").strip() if len(row) > 1 and row[1] else ""
            # Buscar montos en las últimas columnas
            solicitado = 0
            autorizado = 0
            if len(row) >= 5:
                solicitado = _float(row[3]) if len(row) > 3 else 0
                autorizado = _float(row[4]) if len(row) > 4 else 0

            # Si la fila es una categoría sin concepto separado, usar concepto de col 1
            if es_fila_categoria:
                # Si hay un concepto en col 1 y monto > 0, guardar la partida con proveedor limpio
                if concepto and (solicitado > 0 or autorizado > 0):
                    proveedor = ""  # No usar nombre de categoría como proveedor
                elif not concepto and (solicitado > 0 or autorizado > 0):
                    # La categoría misma es el concepto (ej: "ADMINISTRACION" con monto)
                    concepto = categoria_actual
                    proveedor = ""
                else:
                    continue  # Solo cambio de categoría sin datos

            # Solo guardar si hay proveedor/concepto con monto > 0
            if (proveedor or concepto) and (solicitado > 0 or autorizado > 0):
                if "TOTAL" in proveedor.upper() or "TOTAL" in concepto.upper():
                    continue
                if "XXXXXX" in proveedor or "XXXXXX" in concepto:
                    continue
                # Extraer contacto del proveedor (formato: "NOMBRE PROVEEDOR\nNOMBRE CONTACTO - TELEFONO")
                contacto_prov = None
                if "\n" in proveedor:
                    lineas_prov = [l.strip() for l in proveedor.split("\n") if l.strip()]
                    if len(lineas_prov) >= 2:
                        proveedor = lineas_prov[0]
                        contacto_prov = " | ".join(lineas_prov[1:])
                elif " - " in proveedor and any(c.isdigit() for c in proveedor.split(" - ")[-1]):
                    # "NOMBRE CONTACTO - 5541458123" inline
                    pass  # dejarlo en contacto junto al nombre
                db.crear_partida_requisicion({
                    "id_requisicion": req_id, "categoria": categoria_actual,
                    "proveedor": proveedor or None, "contacto_proveedor": contacto_prov,
                    "concepto": concepto or None, "periodo": None,
                    "monto_solicitado": solicitado, "monto_autorizado": autorizado,
                    "observaciones": None,
                })

        db._recalcular_totales_requisicion(req_id)
        resultados.append(f"REQ {empresa_key}: requisición #{req_id} creada")

        # ── Procesar hojas C-IMSS (nómina con IMSS) ──
        imss_hoja = hojas.get(f"C-IMSS {empresa_key}")
        if imss_hoja:
            cat_personal = "Otro"
            count_imss = 0
            for row in imss_hoja.iter_rows(min_row=5, values_only=True):
                if not row or len(row) < 10:
                    continue
                # Detectar categoría de personal (filas sin número pero con texto)
                first = row[0]
                second = str(row[1] or "").strip() if len(row) > 1 and row[1] else ""
                if not first and second and not any(c.isdigit() for c in second[:3]):
                    # Es un encabezado de categoría
                    if second.upper() not in ("", "REALIZÓ:", "VO. BO.", "AUTORIZÓ:"):
                        cat_personal = second
                    continue
                # Fila de empleado: #, nombre, puesto, fecha_ingreso, dias, sal_diario, ...
                if first and str(first).strip().isdigit():
                    nombre = str(row[1] or "").strip() if len(row) > 1 else ""
                    if not nombre or len(nombre) < 3:
                        continue
                    puesto = str(row[2] or "").strip() if len(row) > 2 else ""
                    fecha_ing = row[3] if len(row) > 3 else None
                    dias = int(_float(row[4])) if len(row) > 4 else 0
                    sal_diario = _float(row[5]) if len(row) > 5 else 0
                    sal_prop = _float(row[6]) if len(row) > 6 else 0
                    sal_sem = _float(row[7]) if len(row) > 7 else 0
                    hrs_extra = _float(row[8]) if len(row) > 8 else 0
                    costo_hrs = _float(row[9]) if len(row) > 9 else 0
                    descanso = _float(row[10]) if len(row) > 10 else 0
                    compensacion = _float(row[11]) if len(row) > 11 else 0
                    pago_te = _float(row[12]) if len(row) > 12 else 0
                    comidas = _float(row[13]) if len(row) > 13 else 0
                    total_real = _float(row[14]) if len(row) > 14 else 0

                    if total_real <= 0 and sal_diario <= 0:
                        continue

                    db.crear_nomina_imss({
                        "id_requisicion": req_id, "id_empleado": None,
                        "nombre_empleado": nombre, "puesto": puesto,
                        "categoria_personal": cat_personal,
                        "fecha_ingreso": str(fecha_ing)[:10] if fecha_ing else None,
                        "dias": dias, "salario_diario": sal_diario,
                        "salario_proporcional": sal_prop, "salario_semanal": sal_sem,
                        "horas_extra": hrs_extra, "costo_horas_extra": costo_hrs,
                        "descanso_pagado": descanso, "compensacion": compensacion,
                        "pago_tiempo_extra": pago_te, "comidas": comidas,
                        "total_real": total_real, "observaciones": None,
                    })
                    count_imss += 1
            if count_imss:
                resultados.append(f"C-IMSS {empresa_key}: {count_imss} empleados")

        # ── Procesar hojas S-IMSS (nómina sin IMSS) ──
        sin_imss_hoja = hojas.get(f"S-IMSS {empresa_key}")
        if sin_imss_hoja:
            count_sin = 0
            for row in sin_imss_hoja.iter_rows(min_row=5, values_only=True):
                if not row or len(row) < 8:
                    continue
                first = row[0]
                if first and str(first).strip().isdigit():
                    nombre = str(row[1] or "").strip() if len(row) > 1 else ""
                    if not nombre or len(nombre) < 3:
                        continue
                    puesto = str(row[2] or "").strip() if len(row) > 2 else ""
                    dias = int(_float(row[3])) if len(row) > 3 else 0
                    sal_diario = _float(row[4]) if len(row) > 4 else 0
                    sal_prop = _float(row[5]) if len(row) > 5 else 0
                    sal_sem = _float(row[6]) if len(row) > 6 else 0
                    hrs_extra = _float(row[7]) if len(row) > 7 else 0
                    costo_hrs = _float(row[8]) if len(row) > 8 else 0
                    compensacion = _float(row[9]) if len(row) > 9 else 0
                    pago_te = _float(row[10]) if len(row) > 10 else 0
                    comidas = _float(row[11]) if len(row) > 11 else 0
                    total_real = _float(row[12]) if len(row) > 12 else 0

                    if total_real <= 0 and sal_diario <= 0:
                        continue

                    db.crear_nomina_sin_imss({
                        "id_requisicion": req_id, "id_empleado": None,
                        "nombre_empleado": nombre, "puesto": puesto,
                        "dias": dias, "salario_diario": sal_diario,
                        "salario_proporcional": sal_prop, "salario_semanal": sal_sem,
                        "horas_extra": hrs_extra, "costo_horas_extra": costo_hrs,
                        "compensacion": compensacion, "pago_tiempo_extra": pago_te,
                        "comidas": comidas, "total_real": total_real, "observaciones": None,
                    })
                    count_sin += 1
            if count_sin:
                resultados.append(f"S-IMSS {empresa_key}: {count_sin} empleados")

        # ── Procesar hojas FINIQ ──
        finiq_hoja = hojas.get(f"FINIQ {empresa_key}")
        if finiq_hoja:
            count_finiq = 0
            for row in finiq_hoja.iter_rows(min_row=5, values_only=True):
                if not row or len(row) < 5:
                    continue
                first = row[0]
                if first and str(first).strip().isdigit():
                    obra_finiq = str(row[1] or "").strip() if len(row) > 1 else ""
                    empleado_id_raw = str(row[2] or "").strip() if len(row) > 2 else ""
                    nombre = str(row[3] or "").strip() if len(row) > 3 else ""
                    costo = _float(row[4]) if len(row) > 4 else 0
                    if not nombre or len(nombre) < 3 or "XXXX" in nombre:
                        continue
                    if costo <= 0:
                        continue
                    db.crear_finiquito({
                        "id_requisicion": req_id, "id_obra": id_obra,
                        "id_empleado": None, "nombre_empleado": nombre,
                        "costo_empresa": costo,
                    })
                    count_finiq += 1
            if count_finiq:
                resultados.append(f"FINIQ {empresa_key}: {count_finiq} finiquitos")

        # ── Procesar hoja DESCAN (descansos) ──
        descan_hoja = hojas.get(f"DESCAN {empresa_key}")
        if descan_hoja:
            count_desc = 0
            for row in descan_hoja.iter_rows(min_row=5, values_only=True):
                if not row or len(row) < 6:
                    continue
                first = row[0]
                if first and str(first).strip().isdigit():
                    nombre = str(row[1] or "").strip() if len(row) > 1 else ""
                    if not nombre or len(nombre) < 3 or "XXXX" in nombre:
                        continue
                    puesto = str(row[2] or "").strip() if len(row) > 2 else ""
                    origen = str(row[3] or "").strip() if len(row) > 3 else ""
                    fecha_alta = row[4] if len(row) > 4 else None
                    sueldo = _float(row[5]) if len(row) > 5 else 0
                    # Fechas de descanso en columnas 6..10
                    descansos = []
                    for di in range(6, 11):
                        dval = row[di] if len(row) > di else None
                        if dval and str(dval).strip():
                            descansos.append(str(dval)[:10])
                        else:
                            descansos.append(None)
                    db.crear_descanso({
                        "id_requisicion": req_id, "nombre": nombre,
                        "puesto": puesto or None, "origen": origen or None,
                        "fecha_alta": str(fecha_alta)[:10] if fecha_alta else None,
                        "sueldo": sueldo,
                        "descanso_1": descansos[0], "descanso_2": descansos[1],
                        "descanso_3": descansos[2], "descanso_4": descansos[3],
                        "descanso_5": descansos[4],
                    })
                    count_desc += 1
            if count_desc:
                resultados.append(f"DESCAN {empresa_key}: {count_desc} registros")

        # ── Extraer firmas (Solicitó / Revisión / Autorizó) ──
        solicito_nombre = None
        solicito_puesto = None
        reviso_nombre = None
        reviso_puesto = None
        autorizo_nombre = None
        autorizo_puesto = None
        # Las firmas están al final de la hoja REQ
        ws_firmas = hojas.get(f"REQ {empresa_key}".upper())
        if ws_firmas:
            for row in ws_firmas.iter_rows(min_row=1, values_only=True):
                if not row:
                    continue
                row_str = [str(c or "").strip() for c in row]
                # Buscar fila con "SOLICITÓ" / "REVISIÓN" / "AUTORIZÓ"
                if any("SOLICIT" in c.upper() for c in row_str):
                    continue  # Esta es la etiqueta, los nombres están en la siguiente
                # Buscar fila con nombres de firmantes (ING. / LIC. seguido de nombre)
                for i, c in enumerate(row_str):
                    if c and ("ING." in c.upper() or "LIC." in c.upper() or "ARQ." in c.upper()):
                        if not solicito_nombre:
                            solicito_nombre = c
                        elif not reviso_nombre:
                            reviso_nombre = c
                        elif not autorizo_nombre:
                            autorizo_nombre = c
                # Buscar fila con puestos (Administrador / Tesoreria / Dirección)
                for i, c in enumerate(row_str):
                    if "Administrador" in c or "ADMINISTRADOR" in c.upper():
                        solicito_puesto = c
                    elif "Tesoreria" in c or "TESORERIA" in c.upper():
                        reviso_puesto = c
                    elif "Direcci" in c or "DIRECCI" in c.upper():
                        autorizo_puesto = c

            if solicito_nombre or reviso_nombre or autorizo_nombre:
                db.actualizar_firmas_requisicion(
                    req_id, solicito_nombre, solicito_puesto,
                    reviso_nombre, reviso_puesto, autorizo_nombre, autorizo_puesto)

        # ── Procesar hoja REQ-AUTORIZADO para montos autorizados ──
        req_aut_hoja = hojas.get(f"REQ-AUTORIZADO")
        if not req_aut_hoja:
            req_aut_hoja = hojas.get(f"REQ-AUTORIZADO {empresa_key}".upper())
        if req_aut_hoja:
            # Leer montos autorizados y actualizar partidas existentes por concepto
            partidas_existentes = db.get_partidas_requisicion(req_id)
            cat_aut = "Otros"
            idx_partida = 0
            for row in req_aut_hoja.iter_rows(min_row=8, values_only=True):
                if not row or len(row) < 5:
                    continue
                # Detectar categoría
                for i, cell in enumerate(row[:3]):
                    val_upper = str(cell or "").strip().upper()
                    for key, cat in categorias_map.items():
                        if val_upper.startswith(key):
                            cat_aut = cat
                            break
                proveedor_aut = str(row[0] or "").strip() if row[0] else ""
                concepto_aut = str(row[1] or "").strip() if len(row) > 1 and row[1] else ""
                monto_aut = _float(row[4]) if len(row) > 4 else 0
                total_aut = _float(row[5]) if len(row) > 5 else 0
                monto_final = total_aut if total_aut > 0 else monto_aut
                if not (proveedor_aut or concepto_aut) or monto_final <= 0:
                    continue
                if "TOTAL" in proveedor_aut.upper() or "XXXXXX" in proveedor_aut:
                    continue
                # Buscar partida correspondiente por concepto similar
                for p in partidas_existentes:
                    p_conc = (p.get("concepto") or "").upper()
                    p_prov = (p.get("proveedor") or "").upper()
                    if (concepto_aut.upper() in p_conc or p_conc in concepto_aut.upper() or
                        (proveedor_aut.upper() and proveedor_aut.upper()[:20] in p_prov)):
                        if float(p.get("monto_autorizado") or 0) == 0:
                            db.execute("UPDATE requisicion_partidas SET monto_autorizado=%s WHERE id=%s",
                                      (monto_final, p["id"]))
                            break

            db._recalcular_totales_requisicion(req_id)
            resultados.append(f"REQ-AUTORIZADO: montos actualizados")

        # Recalcular totales finales
        db._recalcular_totales_requisicion(req_id)

    if resultados:
        flash("Importación completada: " + " | ".join(resultados), "success")
    else:
        flash("No se encontraron hojas válidas en el archivo.", "warning")
    return redirect(url_for("requisiciones"))


@app.route("/requisiciones/exportar/excel")
@login_required
@permiso_requerido("requisiciones", "leer")
def requisiciones_exportar_excel():
    """Exporta las requisiciones a Excel con sus partidas."""
    obra_filtro = request.args.get("obra", "")
    empresa_filtro = request.args.get("empresa", "")
    estatus_filtro = request.args.get("estatus", "")
    reqs = db.get_requisiciones(
        id_obra=int(obra_filtro) if obra_filtro else None,
        empresa=empresa_filtro or None,
        estatus=estatus_filtro or None,
        limit=500
    )

    wb = Workbook()
    FONT_HEADER = Font(bold=True, color="FFFFFF")
    FILL_HEADER = PatternFill("solid", fgColor="2E3192")
    ALIGN_C = Alignment(horizontal="center")

    def auto_width(ws):
        for col in ws.columns:
            mx = max((len(str(c.value or "")) for c in col), default=10)
            ws.column_dimensions[col[0].column_letter].width = min(mx + 4, 42)

    # Hoja 1: Resumen requisiciones
    ws = wb.active
    ws.title = "Requisiciones"
    headers = ["ID", "Semana", "Empresa", "Obra", "Residente", "Fecha inicio",
               "Fecha fin", "Total solicitado", "Total autorizado", "Estatus", "Creado"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.alignment = ALIGN_C
    for r in reqs:
        ws.append([
            r.get("id"),
            r.get("semana") or r.get("semana_num") or "",
            r.get("empresa", ""),
            r.get("obra_nombre") or "",
            r.get("residente") or "",
            str(r.get("fecha_inicio") or ""),
            str(r.get("fecha_fin") or ""),
            float(r.get("total_solicitado") or 0),
            float(r.get("total_autorizado") or 0),
            r.get("estatus", ""),
            str(r.get("creado_en") or ""),
        ])
    auto_width(ws)

    # Hoja 2: Partidas detalle
    ws2 = wb.create_sheet("Partidas")
    headers2 = ["ID Requisicion", "Semana", "Empresa", "Categoria", "Proveedor",
                "Concepto", "Monto solicitado", "Monto autorizado"]
    ws2.append(headers2)
    for cell in ws2[1]:
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.alignment = ALIGN_C
    for r in reqs:
        partidas = db.get_partidas_requisicion(r["id"])
        for p in partidas:
            ws2.append([
                r.get("id"),
                r.get("semana") or r.get("semana_num") or "",
                r.get("empresa", ""),
                p.get("categoria", ""),
                p.get("proveedor") or "",
                p.get("concepto") or "",
                float(p.get("monto_solicitado") or 0),
                float(p.get("monto_autorizado") or 0),
            ])
    auto_width(ws2)

    nombre_archivo = f"Requisiciones_{hoy_str()}.xlsx"
    ruta = os.path.join(UPLOAD_FOLDER, nombre_archivo)
    wb.save(ruta)
    return send_file(ruta, as_attachment=True, download_name=nombre_archivo)


@app.route("/requisiciones/<int:rid>/exportar")
@login_required
@permiso_requerido("requisiciones", "leer")
def requisicion_exportar_oficial(rid):
    """Exporta una requisición individual en formato oficial ESMA/GREMIAL."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    import tempfile

    req = db.get_requisicion(rid)
    if not req:
        abort(404)
    partidas = db.get_partidas_requisicion(rid)
    nomina_imss = db.get_nomina_imss_requisicion(rid)
    nomina_sin = db.get_nomina_sin_imss_requisicion(rid)
    finiquitos = db.get_finiquitos_requisicion(rid)
    descansos = db.get_descansos_requisicion(rid)

    empresa_nombre = "ESMA INSTALACIONES S.A. DE C.V." if req["empresa"] == "ESMA" else "GREMIAL CONSTRUCCIONES S.A. DE C.V."
    wb = Workbook()
    money_fmt = '#,##0.00'
    hd_font = Font(bold=True, size=14)
    sub_font = Font(bold=True, size=11)
    tbl_hd_font = Font(bold=True, size=9, color="FFFFFF")
    tbl_hd_fill = PatternFill("solid", fgColor="1A5276")
    cat_font = Font(bold=True, size=10)
    cat_fill = PatternFill("solid", fgColor="D5E8D4")
    cell_font = Font(size=9)
    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin'))

    # ═══ HOJA REQ ═══
    ws = wb.active
    ws.title = "REQ"

    # Encabezado
    ws.merge_cells("A1:F1")
    ws["A1"] = empresa_nombre
    ws["A1"].font = hd_font
    ws.merge_cells("A2:F2")
    ws["A2"] = "REQUERIMIENTO SEMANAL"
    ws["A2"].font = sub_font

    ws["E3"] = "# SEMANA"
    ws["F3"] = req["semana_num"]
    ws["F3"].font = Font(bold=True, size=14)

    row = 4
    ws.cell(row, 1, "Nombre de Obra / Proyecto:").font = sub_font
    ws.cell(row, 2, req["obra_nombre"] or "")
    row += 1
    ws.cell(row, 1, "Nombre del Residente de Obra:").font = sub_font
    ws.cell(row, 2, req["residente"] or "")
    ws.cell(row, 5, "FECHA:")
    ws.cell(row, 6, req.get("fecha_inicio") or "")

    # Rango semana
    row += 1
    sem_txt = ""
    if req["fecha_inicio"] and req["fecha_fin"]:
        sem_txt = f"SEMANA DEL {req['fecha_inicio']} AL {req['fecha_fin']}"
    ws.cell(row, 1, sem_txt).font = sub_font

    # Encabezados tabla
    row += 2
    headers = ["PROVEEDOR", "CONCEPTO", "", "SOLICITADO", "AUTORIZADO", "TOTAL"]
    for ci, h in enumerate(headers, 1):
        c = ws.cell(row, ci, h)
        c.font = tbl_hd_font
        c.fill = tbl_hd_fill
        c.border = thin_border

    # Agrupar partidas por categoría
    categorias_orden = ["Administración", "Maquinaria", "Materiales", "Servicios", "Otros", "Comisiones"]
    partidas_por_cat = {}
    for p in partidas:
        cat = p.get("categoria") or "Otros"
        partidas_por_cat.setdefault(cat, []).append(p)

    total_sol = 0
    total_aut = 0
    for cat in categorias_orden:
        items = partidas_por_cat.get(cat, [])
        if not items:
            continue
        row += 1
        # Fila de categoría
        cat_sol = sum(float(p["monto_solicitado"] or 0) for p in items)
        cat_aut = sum(float(p["monto_autorizado"] or 0) for p in items)
        ws.cell(row, 1, cat.upper()).font = cat_font
        ws.cell(row, 1).fill = cat_fill
        ws.cell(row, 4, cat_sol).number_format = money_fmt
        ws.cell(row, 5, cat_aut).number_format = money_fmt
        ws.cell(row, 6, cat_sol).number_format = money_fmt
        for ci in range(1, 7):
            ws.cell(row, ci).border = thin_border

        for p in items:
            row += 1
            ws.cell(row, 1, p["proveedor"] or "").font = cell_font
            ws.cell(row, 2, p["concepto"] or "").font = cell_font
            sol = float(p["monto_solicitado"] or 0)
            aut = float(p["monto_autorizado"] or 0)
            ws.cell(row, 4, sol).number_format = money_fmt
            ws.cell(row, 5, aut).number_format = money_fmt
            ws.cell(row, 6, sol).number_format = money_fmt
            total_sol += sol
            total_aut += aut
            for ci in range(1, 7):
                ws.cell(row, ci).border = thin_border

    # Fila total
    row += 1
    ws.cell(row, 1, "TOTAL:").font = Font(bold=True, size=11)
    ws.cell(row, 4, total_sol).number_format = money_fmt
    ws.cell(row, 4).font = Font(bold=True)
    ws.cell(row, 5, total_aut).number_format = money_fmt
    ws.cell(row, 5).font = Font(bold=True)
    ws.cell(row, 6, total_sol).number_format = money_fmt
    ws.cell(row, 6).font = Font(bold=True)

    # Firmas
    row += 3
    ws.cell(row, 1, "SOLICITÓ").font = sub_font
    ws.cell(row, 3, "REVISIÓN").font = sub_font
    ws.cell(row, 5, "AUTORIZÓ").font = sub_font
    row += 2
    ws.cell(row, 1, req.get("solicito_nombre") or "")
    ws.cell(row, 3, req.get("reviso_nombre") or "")
    ws.cell(row, 5, req.get("autorizo_nombre") or "")
    row += 1
    ws.cell(row, 1, req.get("solicito_puesto") or "").font = Font(size=9, italic=True)
    ws.cell(row, 3, req.get("reviso_puesto") or "").font = Font(size=9, italic=True)
    ws.cell(row, 5, req.get("autorizo_puesto") or "").font = Font(size=9, italic=True)

    # Ajustar anchos
    for ci, w in enumerate([30, 45, 5, 16, 16, 16], 1):
        ws.column_dimensions[get_column_letter(ci)].width = w

    # ═══ HOJA C-IMSS ═══
    if nomina_imss:
        ws2 = wb.create_sheet("C-IMSS")
        ws2.merge_cells("A1:N1")
        ws2["A1"] = empresa_nombre
        ws2["A1"].font = hd_font
        ws2.merge_cells("A2:N2")
        ws2["A2"] = sem_txt
        ws2["A2"].font = sub_font
        ws2.cell(3, 2, f"OBRA: {req['obra_nombre'] or ''}")

        row2 = 5
        hdrs = ["#", "NOMBRE DEL TRABAJADOR", "PUESTO", "FECHA DE INGRESO", "DIAS",
                "SAL. DIARIO", "SAL. SEMANAL", "HORAS EXTRAS", "COSTO HRS EXTRA",
                "DESCANSO", "COMPENSACION", "$ TIEMPO EXTRA", "COMIDAS", "TOTAL REAL"]
        for ci, h in enumerate(hdrs, 1):
            c = ws2.cell(row2, ci, h)
            c.font = tbl_hd_font
            c.fill = tbl_hd_fill

        cat_actual = ""
        for idx, n in enumerate(nomina_imss, 1):
            if n.get("categoria_personal") and n["categoria_personal"] != cat_actual:
                cat_actual = n["categoria_personal"]
                row2 += 1
                ws2.cell(row2, 2, cat_actual).font = cat_font
            row2 += 1
            ws2.cell(row2, 1, idx)
            ws2.cell(row2, 2, n["nombre_empleado"] or "")
            ws2.cell(row2, 3, n["puesto"] or "")
            ws2.cell(row2, 4, n.get("fecha_ingreso") or "")
            ws2.cell(row2, 5, n["dias"])
            ws2.cell(row2, 6, float(n["salario_diario"] or 0)).number_format = money_fmt
            ws2.cell(row2, 7, float(n["salario_semanal"] or 0)).number_format = money_fmt
            ws2.cell(row2, 8, float(n["horas_extra"] or 0))
            ws2.cell(row2, 9, float(n["costo_horas_extra"] or 0)).number_format = money_fmt
            ws2.cell(row2, 10, float(n.get("descanso_pagado") or 0)).number_format = money_fmt
            ws2.cell(row2, 11, float(n["compensacion"] or 0)).number_format = money_fmt
            ws2.cell(row2, 12, float(n["pago_tiempo_extra"] or 0)).number_format = money_fmt
            ws2.cell(row2, 13, float(n["comidas"] or 0)).number_format = money_fmt
            ws2.cell(row2, 14, float(n["total_real"] or 0)).number_format = money_fmt

        # Total nómina
        row2 += 1
        total_nom = sum(float(n["total_real"] or 0) for n in nomina_imss)
        ws2.cell(row2, 13, "TOTAL:").font = Font(bold=True)
        ws2.cell(row2, 14, total_nom).number_format = money_fmt
        ws2.cell(row2, 14).font = Font(bold=True)

        # Firmas
        row2 += 3
        ws2.cell(row2, 1, "REALIZÓ:").font = sub_font
        ws2.cell(row2, 6, "Vo. Bo.").font = sub_font
        ws2.cell(row2, 11, "AUTORIZÓ:").font = sub_font
        row2 += 2
        ws2.cell(row2, 1, req.get("solicito_nombre") or "")
        ws2.cell(row2, 6, req.get("reviso_nombre") or "")
        ws2.cell(row2, 11, req.get("autorizo_nombre") or "")

    # ═══ HOJA S-IMSS ═══
    if nomina_sin:
        ws3 = wb.create_sheet("S-IMSS")
        ws3.merge_cells("A1:M1")
        ws3["A1"] = empresa_nombre
        ws3["A1"].font = hd_font

        row3 = 4
        hdrs3 = ["No.", "NOMBRE DEL TRABAJADOR", "PUESTO", "DIAS", "SAL. DIARIO",
                 "SAL. SEMANAL", "SAL. SEMANA", "HRS EXTRA", "COSTO HRS EXTRA",
                 "COMPENSACION", "$ TIEMPO EXTRA", "COMIDAS", "TOTAL REAL"]
        for ci, h in enumerate(hdrs3, 1):
            ws3.cell(row3, ci, h).font = tbl_hd_font
            ws3.cell(row3, ci).fill = tbl_hd_fill

        for idx, n in enumerate(nomina_sin, 1):
            row3 += 1
            ws3.cell(row3, 1, idx)
            ws3.cell(row3, 2, n["nombre_empleado"] or "")
            ws3.cell(row3, 3, n["puesto"] or "")
            ws3.cell(row3, 4, n["dias"])
            ws3.cell(row3, 5, float(n["salario_diario"] or 0)).number_format = money_fmt
            ws3.cell(row3, 6, float(n.get("salario_proporcional") or 0)).number_format = money_fmt
            ws3.cell(row3, 7, float(n["salario_semanal"] or 0)).number_format = money_fmt
            ws3.cell(row3, 8, float(n["horas_extra"] or 0))
            ws3.cell(row3, 9, float(n["costo_horas_extra"] or 0)).number_format = money_fmt
            ws3.cell(row3, 10, float(n["compensacion"] or 0)).number_format = money_fmt
            ws3.cell(row3, 11, float(n["pago_tiempo_extra"] or 0)).number_format = money_fmt
            ws3.cell(row3, 12, float(n["comidas"] or 0)).number_format = money_fmt
            ws3.cell(row3, 13, float(n["total_real"] or 0)).number_format = money_fmt

    # ═══ HOJA FINIQUITOS ═══
    if finiquitos:
        ws4 = wb.create_sheet("FINIQ")
        ws4["A1"] = empresa_nombre
        ws4["A1"].font = hd_font
        ws4.cell(3, 1, f"SEMANA {req['semana_num'] or ''}")
        ws4.cell(3, 2, sem_txt)

        row4 = 5
        for ci, h in enumerate(["#", "OBRA", "EMPLEADO", "NOMBRE", "COSTO EMPRESA"], 1):
            ws4.cell(row4, ci, h).font = tbl_hd_font
            ws4.cell(row4, ci).fill = tbl_hd_fill

        for idx, f in enumerate(finiquitos, 1):
            row4 += 1
            ws4.cell(row4, 1, idx)
            ws4.cell(row4, 2, req["obra_nombre"] or "")
            ws4.cell(row4, 3, "")
            ws4.cell(row4, 4, f["nombre_empleado"] or "")
            ws4.cell(row4, 5, float(f["costo_empresa"] or 0)).number_format = money_fmt

    # ═══ HOJA DESCANSOS ═══
    if descansos:
        ws5 = wb.create_sheet("DESCAN")
        ws5["A1"] = empresa_nombre
        ws5["A1"].font = hd_font
        ws5.cell(3, 1, f"OBRA: {req['obra_nombre'] or ''}")

        row5 = 5
        for ci, h in enumerate(["#", "NOMBRE", "PUESTO", "ORIGEN", "ALTA", "SUELDO",
                                  "1er", "2do", "3ero", "4to", "5to"], 1):
            ws5.cell(row5, ci, h).font = tbl_hd_font
            ws5.cell(row5, ci).fill = tbl_hd_fill

        for idx, d in enumerate(descansos, 1):
            row5 += 1
            ws5.cell(row5, 1, idx)
            ws5.cell(row5, 2, d["nombre"] or "")
            ws5.cell(row5, 3, d["puesto"] or "")
            ws5.cell(row5, 4, d["origen"] or "")
            ws5.cell(row5, 5, d.get("fecha_alta") or "")
            ws5.cell(row5, 6, float(d["sueldo"] or 0)).number_format = money_fmt
            ws5.cell(row5, 7, d.get("descanso_1") or "")
            ws5.cell(row5, 8, d.get("descanso_2") or "")
            ws5.cell(row5, 9, d.get("descanso_3") or "")
            ws5.cell(row5, 10, d.get("descanso_4") or "")
            ws5.cell(row5, 11, d.get("descanso_5") or "")

    # Guardar y enviar
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    wb.save(tmp.name)
    tmp.close()
    nombre = f"REQ_Sem{req['semana_num'] or ''}_{req['empresa']}_{req['obra_nombre'] or 'general'}.xlsx"
    return send_file(tmp.name, as_attachment=True, download_name=nombre,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ══════════════════════════════════════════════════════════════════
#  RECURSOS HUMANOS
# ══════════════════════════════════════════════════════════════════

@app.route("/rrhh")
@login_required
@permiso_requerido("rrhh", "leer")
def rrhh():
    user = get_current_user()
    search = request.args.get("q", "")
    obra = request.args.get("obra", "")
    depto = request.args.get("departamento", "")
    activo = request.args.get("activo", "1")
    empleados = db.get_empleados(
        search=search or None,
        obra=int(obra) if obra else None,
        departamento=depto or None,
        activo=int(activo) if activo != "" else None
    )
    obras = db.get_obras()
    kpis = db.get_kpis_rrhh()
    return render_template("rrhh.html", empleados=empleados, user=user,
                           obras=obras, kpis=kpis, q=search, obra_filtro=obra,
                           depto_filtro=depto, activo_filtro=activo,
                           departamentos=db.DEPARTAMENTOS_RRHH)

@app.route("/rrhh/empleado/nuevo", methods=["GET", "POST"])
@login_required
@permiso_requerido("rrhh", "crear")
def empleado_nuevo():
    user = get_current_user()
    obras = db.get_obras()
    if request.method == "POST":
        f = request.form
        foto_nombre = None
        foto_archivo = request.files.get("foto")
        if foto_archivo and foto_archivo.filename:
            ext = os.path.splitext(foto_archivo.filename)[1].lower()
            foto_nombre = f"emp_{f.get('curp','')[:10]}_{int(__import__('time').time())}{ext}"
            foto_archivo.save(os.path.join(UPLOAD_FOLDER, foto_nombre))
        db.crear_empleado({
            "numero_empleado": f.get("numero_empleado") or None,
            "nombre": f["nombre"], "apellido_paterno": f["apellido_paterno"],
            "apellido_materno": f.get("apellido_materno") or None,
            "curp": f.get("curp") or None, "rfc": f.get("rfc") or None,
            "nss": f.get("nss") or None,
            "fecha_nacimiento": f.get("fecha_nacimiento") or None,
            "telefono": f.get("telefono") or None, "email": f.get("email") or None,
            "direccion": f.get("direccion") or None,
            "puesto": f.get("puesto") or None, "departamento": f.get("departamento") or None,
            "id_obra": int(f["id_obra"]) if f.get("id_obra") else None,
            "tipo_contrato": f.get("tipo_contrato") or "Planta",
            "fecha_ingreso": f.get("fecha_ingreso") or None,
            "salario_diario": f.get("salario_diario") or None,
            "salario_semanal": f.get("salario_semanal") or None,
            "tasa_hora_extra": f.get("tasa_hora_extra") or None,
            "banco": f.get("banco") or None, "cuenta_banco": f.get("cuenta_banco") or None,
            "clabe": f.get("clabe") or None,
            "contacto_emergencia": f.get("contacto_emergencia") or None,
            "foto": foto_nombre, "creado_por": user["id"],
        })
        flash("Empleado registrado correctamente.", "success")
        return redirect(url_for("rrhh"))
    return render_template("empleado_form.html", emp=None, user=user, obras=obras,
                           accion="Nuevo", departamentos=db.DEPARTAMENTOS_RRHH,
                           tipos_contrato=db.TIPOS_CONTRATO)

@app.route("/rrhh/empleado/<int:eid>")
@login_required
@permiso_requerido("rrhh", "leer")
def empleado_detalle(eid):
    emp = db.get_empleado(eid)
    if not emp: abort(404)
    user = get_current_user()
    nominas = db.get_nomina_empleado(eid)
    fi = request.args.get("fecha_ini", hace(30))
    ff = request.args.get("fecha_fin", hoy_str())
    asistencia = db.get_asistencia_empleado(eid, fi, ff)
    return render_template("empleado_detalle.html", emp=emp, user=user,
                           nominas=nominas, asistencia=asistencia, fi=fi, ff=ff)

@app.route("/rrhh/empleado/<int:eid>/editar", methods=["GET", "POST"])
@login_required
@permiso_requerido("rrhh", "editar")
def empleado_editar(eid):
    emp = db.get_empleado(eid)
    if not emp: abort(404)
    user = get_current_user()
    obras = db.get_obras()
    if request.method == "POST":
        f = request.form
        foto_nombre = emp.get("foto")
        foto_archivo = request.files.get("foto")
        if foto_archivo and foto_archivo.filename:
            ext = os.path.splitext(foto_archivo.filename)[1].lower()
            foto_nombre = f"emp_{emp['id']}_{int(__import__('time').time())}{ext}"
            foto_archivo.save(os.path.join(UPLOAD_FOLDER, foto_nombre))
        db.actualizar_empleado(eid, {
            "numero_empleado": f.get("numero_empleado") or None,
            "nombre": f["nombre"], "apellido_paterno": f["apellido_paterno"],
            "apellido_materno": f.get("apellido_materno") or None,
            "curp": f.get("curp") or None, "rfc": f.get("rfc") or None,
            "nss": f.get("nss") or None,
            "fecha_nacimiento": f.get("fecha_nacimiento") or None,
            "telefono": f.get("telefono") or None, "email": f.get("email") or None,
            "direccion": f.get("direccion") or None,
            "puesto": f.get("puesto") or None, "departamento": f.get("departamento") or None,
            "id_obra": int(f["id_obra"]) if f.get("id_obra") else None,
            "tipo_contrato": f.get("tipo_contrato") or "Planta",
            "fecha_ingreso": f.get("fecha_ingreso") or None,
            "salario_diario": f.get("salario_diario") or None,
            "salario_semanal": f.get("salario_semanal") or None,
            "tasa_hora_extra": f.get("tasa_hora_extra") or None,
            "banco": f.get("banco") or None, "cuenta_banco": f.get("cuenta_banco") or None,
            "clabe": f.get("clabe") or None,
            "contacto_emergencia": f.get("contacto_emergencia") or None,
            "foto": foto_nombre,
        })
        flash("Empleado actualizado.", "success")
        return redirect(url_for("empleado_detalle", eid=eid))
    return render_template("empleado_form.html", emp=emp, user=user, obras=obras,
                           accion="Editar", departamentos=db.DEPARTAMENTOS_RRHH,
                           tipos_contrato=db.TIPOS_CONTRATO)

@app.route("/rrhh/empleado/<int:eid>/baja", methods=["POST"])
@login_required
@permiso_requerido("rrhh", "editar")
def empleado_baja(eid):
    fecha = request.form.get("fecha_baja") or hoy_str()
    db.baja_empleado(eid, fecha)
    flash("Empleado dado de baja.", "success")
    return redirect(url_for("rrhh"))

@app.route("/rrhh/empleado/<int:eid>/reactivar", methods=["POST"])
@login_required
@permiso_requerido("rrhh", "editar")
def empleado_reactivar(eid):
    db.reactivar_empleado(eid)
    flash("Empleado reactivado.", "success")
    return redirect(url_for("rrhh"))

# ── ASISTENCIA ────────────────────────────────────────────────────

@app.route("/rrhh/asistencia", methods=["GET", "POST"])
@login_required
@permiso_requerido("rrhh", "leer")
def rrhh_asistencia():
    user = get_current_user()
    obras = db.get_obras()
    obra_filtro = request.args.get("obra", "")
    # Semana actual por default (lunes a domingo)
    hoy = date.today()
    lunes = hoy - timedelta(days=hoy.weekday())
    domingo = lunes + timedelta(days=6)
    fi = request.args.get("fecha_ini", lunes.strftime("%Y-%m-%d"))
    ff = request.args.get("fecha_fin", domingo.strftime("%Y-%m-%d"))

    if request.method == "POST":
        f = request.form
        # Registro masivo de asistencia
        empleados_ids = f.getlist("id_empleado")
        for eid in empleados_ids:
            fecha = f.get(f"fecha_{eid}")
            tipo = f.get(f"tipo_{eid}", "asistencia")
            entrada = f.get(f"entrada_{eid}") or None
            salida = f.get(f"salida_{eid}") or None
            hrs_normales_raw = f.get(f"horas_normales_{eid}") or None
            hrs_extra = f.get(f"horas_extra_{eid}") or 0
            obs = f.get(f"obs_{eid}") or None
            obra_id = f.get(f"obra_{eid}") or obra_filtro or None
            # Si es asistencia, entrada y salida son obligatorios
            if tipo == "asistencia" and (not entrada or not salida):
                flash("Si el tipo es Asistencia, debes registrar hora de Entrada y Salida.", "danger")
                return redirect(url_for("rrhh_asistencia", obra=obra_filtro, fecha_ini=fi, fecha_fin=ff))
            # Calcular horas automáticamente desde entrada/salida
            if tipo == "asistencia" and entrada and salida:
                from datetime import datetime as _dt
                t_entrada = _dt.strptime(entrada, "%H:%M")
                t_salida = _dt.strptime(salida, "%H:%M")
                diff = (t_salida - t_entrada).total_seconds() / 3600
                if diff < 0:
                    diff += 24  # Turno nocturno
                horas_totales = round(diff, 4)
                hrs_normales = min(horas_totales, 8.0)
                hrs_extra = round(max(horas_totales - 8.0, 0), 4)
            elif tipo == "asistencia" and not hrs_normales_raw:
                hrs_normales = 8.0
                hrs_extra = 0
            else:
                hrs_normales = float(hrs_normales_raw) if hrs_normales_raw else 0.0
                hrs_extra = float(hrs_extra) if hrs_extra else 0
            db.registrar_asistencia(
                int(eid), fecha, int(obra_id) if obra_id else None,
                entrada, salida,
                hrs_normales,
                float(hrs_extra),
                tipo, obs, user["id"]
            )
        flash("Asistencia registrada.", "success")
        return redirect(url_for("rrhh_asistencia", obra=obra_filtro, fecha_ini=fi, fecha_fin=ff))

    resumen = db.get_resumen_asistencia_semana(fi, ff, int(obra_filtro) if obra_filtro else None)
    empleados = db.get_empleados(obra=int(obra_filtro) if obra_filtro else None, activo=1)
    return render_template("rrhh_asistencia.html", user=user, obras=obras,
                           resumen=resumen, empleados=empleados,
                           fi=fi, ff=ff, obra_filtro=obra_filtro)

@app.route("/rrhh/asistencia/importar", methods=["POST"])
@login_required
@permiso_requerido("rrhh", "crear")
def rrhh_asistencia_importar():
    """Importa asistencia semanal desde Excel formato ESMA-GREMIAL.
    Detecta obra, semana, empleados (crea si no existen) y registra asistencia."""
    from openpyxl import load_workbook
    from datetime import datetime as _dt

    user = get_current_user()
    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        flash("Selecciona un archivo Excel.", "danger")
        return redirect(url_for("rrhh_asistencia"))

    id_obra_form = request.form.get("id_obra") or None

    try:
        wb = load_workbook(archivo, data_only=True)
    except Exception as e:
        flash(f"Error al leer el archivo: {e}", "danger")
        return redirect(url_for("rrhh_asistencia"))

    total_registros = 0
    empleados_creados = 0

    for ws in wb.worksheets:
        # Buscar la fila con "SEMANA DEL" para extraer las fechas
        semana_num = None
        fecha_inicio = None
        fecha_fin = None
        obra_nombre_excel = None

        for row in ws.iter_rows(min_row=1, max_row=15, values_only=False):
            for cell in row:
                val = str(cell.value or "")
                # Detectar numero de semana
                if "SEMANA No" in val.upper() or "SEMANA NO" in val.upper():
                    # El número suele estar en la siguiente celda o misma fila
                    for c2 in row:
                        if c2.value and str(c2.value).strip().isdigit():
                            semana_num = int(str(c2.value).strip())
                            break
                # Detectar "SEMANA DEL X AL Y DEL Z"
                if "SEMANA DEL" in val.upper():
                    # Parsear rango de fechas desde el texto
                    import re
                    # Formato: "SEMANA DEL  12 DE ENERO AL  18 DE ENERO DEL 2026"
                    m = re.search(r'SEMANA DEL\s+(\d+)\s+DE\s+(\w+)\s+AL\s+(\d+)\s+DE\s+(\w+)\s+DEL\s+(\d{4})', val, re.IGNORECASE)
                    if m:
                        meses = {"ENERO":1,"FEBRERO":2,"MARZO":3,"ABRIL":4,"MAYO":5,"JUNIO":6,
                                 "JULIO":7,"AGOSTO":8,"SEPTIEMBRE":9,"OCTUBRE":10,"NOVIEMBRE":11,"DICIEMBRE":12}
                        dia_ini = int(m.group(1))
                        mes_ini = meses.get(m.group(2).upper(), 1)
                        dia_fin = int(m.group(3))
                        mes_fin = meses.get(m.group(4).upper(), 1)
                        anio = int(m.group(5))
                        try:
                            fecha_inicio = date(anio, mes_ini, dia_ini)
                            fecha_fin = date(anio, mes_fin, dia_fin)
                        except ValueError:
                            pass
                # Detectar obra
                if "OBRA:" in val.upper():
                    # La obra suele estar en celdas siguientes
                    idx = row.index(cell)
                    for c2 in row[idx+1:]:
                        if c2.value and str(c2.value).strip() and "ERROR" not in str(c2.value).upper():
                            obra_nombre_excel = str(c2.value).strip()
                            break

        if not fecha_inicio or not fecha_fin:
            continue  # No se pudo detectar la semana, saltar hoja

        # Generar lista de fechas (lunes a domingo)
        dias_semana = []
        d = fecha_inicio
        while d <= fecha_fin:
            dias_semana.append(d)
            d += timedelta(days=1)
        if len(dias_semana) < 7:
            # Rellenar hasta 7 días
            while len(dias_semana) < 7:
                dias_semana.append(dias_semana[-1] + timedelta(days=1))

        # Determinar id_obra
        id_obra = None
        if id_obra_form:
            id_obra = int(id_obra_form)
        elif obra_nombre_excel:
            # Buscar obra por nombre
            obra_match = db.query("SELECT id FROM obras WHERE nombre LIKE %s LIMIT 1",
                                  (f"%{obra_nombre_excel}%",), one=True)
            if obra_match:
                id_obra = obra_match["id"]

        # Buscar filas de datos de empleados
        # La tabla empieza después de los encabezados (fila con #, NOMBRE DEL TRABAJADOR, PUESTO...)
        data_start = None
        for i, row in enumerate(ws.iter_rows(min_row=1, values_only=False), 1):
            for cell in row:
                val = str(cell.value or "").upper()
                if "NOMBRE DEL TRABAJADOR" in val:
                    data_start = i + 1
                    break
            if data_start:
                break

        if not data_start:
            continue

        # Leer filas de empleados
        for row in ws.iter_rows(min_row=data_start, values_only=True):
            # Columnas esperadas:
            # 0: #, 1: nombre, 2: puesto, 3: fecha_ingreso
            # Luego por cada día (7 días): entrada/salida, hrs_extra, firma (3 cols por día)
            # Total: 4 + (3 * 7) = 25 columnas mínimo
            if not row or len(row) < 5:
                continue

            num_emp = row[0]
            nombre_completo = str(row[1] or "").strip() if row[1] else ""
            puesto = str(row[2] or "").strip() if row[2] else ""
            fecha_ingreso_raw = row[3]

            if not nombre_completo or nombre_completo.upper() in ("OBSERVACIONES:", "RESPONSABLE DE FRENTE:", ""):
                continue
            # Ignorar filas que no tienen nombre real
            if len(nombre_completo) < 3:
                continue

            # Buscar o crear empleado
            # Separar nombre: intentar "APELLIDO PATERNO APELLIDO MATERNO NOMBRE(S)"
            # o simplemente guardar como nombre completo
            partes = nombre_completo.split()
            if len(partes) >= 3:
                apellido_p = partes[0]
                apellido_m = partes[1]
                nombre = " ".join(partes[2:])
            elif len(partes) == 2:
                apellido_p = partes[0]
                apellido_m = ""
                nombre = partes[1]
            else:
                apellido_p = nombre_completo
                apellido_m = ""
                nombre = ""

            # Buscar empleado existente por nombre completo
            emp = db.query("""
                SELECT id FROM empleados
                WHERE CONCAT(nombre,' ',apellido_paterno,' ',COALESCE(apellido_materno,''))
                      LIKE %s
                   OR CONCAT(apellido_paterno,' ',COALESCE(apellido_materno,''),' ',nombre)
                      LIKE %s
                LIMIT 1
            """, (f"%{nombre_completo}%", f"%{nombre_completo}%"), one=True)

            if not emp:
                # Crear empleado nuevo
                fecha_ing = None
                if fecha_ingreso_raw:
                    if isinstance(fecha_ingreso_raw, (date, _dt)):
                        fecha_ing = fecha_ingreso_raw.strftime("%Y-%m-%d") if hasattr(fecha_ingreso_raw, 'strftime') else str(fecha_ingreso_raw)
                    else:
                        try:
                            fecha_ing = str(fecha_ingreso_raw)[:10]
                        except Exception:
                            pass

                emp_id = db.crear_empleado({
                    "numero_empleado": str(num_emp) if num_emp else None,
                    "nombre": nombre or nombre_completo,
                    "apellido_paterno": apellido_p,
                    "apellido_materno": apellido_m or None,
                    "curp": None, "rfc": None, "nss": None,
                    "fecha_nacimiento": None, "telefono": None, "email": None,
                    "direccion": None, "puesto": puesto or None,
                    "departamento": "Operación",
                    "id_obra": id_obra, "tipo_contrato": "Planta",
                    "fecha_ingreso": fecha_ing,
                    "salario_diario": None, "salario_semanal": None,
                    "banco": None, "cuenta_banco": None, "clabe": None,
                    "contacto_emergencia": None, "foto": None,
                    "creado_por": user["id"],
                })
                empleados_creados += 1
            else:
                emp_id = emp["id"]

            # Leer asistencia por día (7 días)
            # Estructura por día: entrada/salida (1 col), hrs_extra (1 col), firma (1 col) = 3 cols
            col_base = 4  # Columna donde empiezan los días
            for dia_idx in range(min(7, len(dias_semana))):
                col_entrada = col_base + (dia_idx * 3)
                col_hrs_extra = col_base + (dia_idx * 3) + 1
                # col_firma = col_base + (dia_idx * 3) + 2  # No usamos firma

                if col_entrada >= len(row):
                    break

                entrada_salida_raw = row[col_entrada] if col_entrada < len(row) else None
                hrs_extra_raw = row[col_hrs_extra] if col_hrs_extra < len(row) else None

                fecha_dia = dias_semana[dia_idx]

                # Parsear entrada/salida
                entrada = None
                salida = None
                if entrada_salida_raw:
                    es = str(entrada_salida_raw).strip()
                    # Puede venir como "07:00\n17:00" o "07:00-17:00" o separado
                    import re as _re
                    tiempos = _re.findall(r'(\d{1,2}:\d{2})', es)
                    if len(tiempos) >= 2:
                        entrada = tiempos[0]
                        salida = tiempos[1]
                    elif len(tiempos) == 1:
                        entrada = tiempos[0]

                # Parsear horas extra
                hrs_extra = 0
                if hrs_extra_raw:
                    try:
                        hrs_extra = float(hrs_extra_raw)
                    except (ValueError, TypeError):
                        hrs_extra = 0

                # Determinar tipo
                tipo = "asistencia"
                if entrada or salida or hrs_extra > 0:
                    tipo = "asistencia"
                elif entrada_salida_raw and str(entrada_salida_raw).strip().upper() in ("F", "FALTA"):
                    tipo = "falta"
                elif entrada_salida_raw and str(entrada_salida_raw).strip().upper() in ("P", "PERMISO"):
                    tipo = "permiso"
                elif entrada_salida_raw and str(entrada_salida_raw).strip().upper() in ("I", "INCAP", "INCAPACIDAD"):
                    tipo = "incapacidad"
                elif entrada_salida_raw and str(entrada_salida_raw).strip().upper() in ("V", "VAC", "VACACIONES"):
                    tipo = "vacaciones"
                elif entrada_salida_raw and str(entrada_salida_raw).strip().upper() in ("D", "DESC", "DESCANSO"):
                    tipo = "descanso"
                else:
                    # Sin datos = no registrar
                    continue

                # Calcular horas normales
                horas_normales = 8.0
                if entrada and salida:
                    try:
                        h1 = _dt.strptime(entrada, "%H:%M")
                        h2 = _dt.strptime(salida, "%H:%M")
                        diff = (h2 - h1).seconds / 3600
                        horas_normales = round(min(diff, 12), 2)  # Cap 12h
                    except Exception:
                        horas_normales = 8.0

                db.registrar_asistencia(
                    emp_id, fecha_dia.strftime("%Y-%m-%d"), id_obra,
                    entrada, salida, horas_normales, hrs_extra,
                    tipo, None, user["id"]
                )
                total_registros += 1

    flash(f"Importación completada: {total_registros} registros de asistencia. "
          f"{empleados_creados} empleados nuevos creados.", "success")
    return redirect(url_for("rrhh_asistencia"))

# ── ASISTENCIA QR ─────────────────────────────────────────────────

@app.route("/rrhh/empleado/<int:eid>/qr")
def empleado_qr(eid):
    """Genera y devuelve la imagen QR del empleado. Acceso público para ficha QR."""
    import qrcode
    import qrcode.image.svg
    from io import BytesIO

    emp = db.get_empleado(eid)
    if not emp or not emp.get("numero_empleado"):
        abort(404)

    # El QR contiene el numero_empleado
    qr_data = emp["numero_empleado"]
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(qr_data)
    qr.make(fit=True)

    # Intentar generar PNG (requiere Pillow), si falla usar SVG
    try:
        img = qr.make_image(fill_color="#2E3192", back_color="white")
        buf = BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return send_file(buf, mimetype="image/png",
                         download_name=f"QR_{emp['numero_empleado']}.png")
    except Exception:
        # Fallback: generar SVG (no requiere Pillow)
        factory = qrcode.image.svg.SvgPathImage
        img = qr.make_image(image_factory=factory)
        buf = BytesIO()
        img.save(buf)
        buf.seek(0)
        return send_file(buf, mimetype="image/svg+xml",
                         download_name=f"QR_{emp['numero_empleado']}.svg")


@app.route("/asistencia/ficha-qr/<int:eid>")
def asistencia_ficha_qr(eid):
    """Página pública donde el empleado puede ver y descargar su QR de asistencia."""
    emp = db.get_empleado(eid)
    if not emp:
        abort(404)
    return render_template("asistencia_ficha_qr.html", emp=emp)


@app.route("/asistencia/scanner")
@login_required
@permiso_requerido("rrhh", "crear")
def asistencia_scanner():
    """Página con lector de cámara QR para registrar asistencia."""
    user = get_current_user()
    return render_template("asistencia_scanner.html", user=user)


@app.route("/api/asistencia/qr", methods=["POST"])
@login_required
@permiso_requerido("rrhh", "crear")
def api_asistencia_qr():
    """API para procesar un escaneo QR de asistencia con foto de evidencia.
    Primer escaneo del día = entrada, segundo = salida, alternando."""
    from datetime import datetime as dt
    import base64

    data = request.get_json()
    if not data:
        return jsonify({"ok": False, "msg": "Datos invalidos"}), 400
    numero_empleado = (data.get("numero_empleado") or "").strip()
    if not numero_empleado:
        return jsonify({"ok": False, "msg": "QR invalido: sin numero de empleado"}), 400

    foto_base64 = data.get("foto")  # data:image/jpeg;base64,...

    try:
        emp = db.get_empleado_por_numero(numero_empleado)
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Error al buscar empleado: {e}"}), 500

    if not emp:
        return jsonify({"ok": False, "msg": f"Empleado {numero_empleado} no encontrado o inactivo"}), 404

    hoy = date.today().strftime("%Y-%m-%d")
    ahora = dt.now().strftime("%H:%M:%S")
    nombre_completo = f"{emp['apellido_paterno']} {emp.get('apellido_materno') or ''}, {emp['nombre']}".strip()

    # Guardar foto de evidencia si viene
    foto_nombre = None
    if foto_base64 and "," in foto_base64:
        try:
            header, img_data = foto_base64.split(",", 1)
            img_bytes = base64.b64decode(img_data)
            ts = int(dt.now().timestamp())
            foto_nombre = f"asist_{numero_empleado}_{hoy}_{ts}.jpg"
            foto_path = os.path.join(UPLOAD_FOLDER, foto_nombre)
            with open(foto_path, "wb") as f:
                f.write(img_bytes)
        except Exception:
            foto_nombre = None  # Si falla guardar foto, continuar sin ella

    try:
        # Obtener escaneos del día para determinar si toca entrada o salida
        escaneos = db.get_escaneos_hoy(emp["id"], hoy)
        n_escaneos = len(escaneos)

        if n_escaneos % 2 == 0:
            # Toca ENTRADA
            db.registrar_escaneo_qr(emp["id"], hoy, ahora, "entrada", emp.get("id_obra"), foto_nombre)
            return jsonify({
                "ok": True,
                "tipo": "entrada",
                "msg": f"ENTRADA #{n_escaneos // 2 + 1} registrada",
                "empleado": nombre_completo,
                "numero": numero_empleado,
                "hora": ahora[:5],
                "foto_url": f"/uploads/{foto_nombre}" if foto_nombre else None,
            })
        else:
            # Toca SALIDA
            db.registrar_escaneo_qr(emp["id"], hoy, ahora, "salida", emp.get("id_obra"), foto_nombre)
            return jsonify({
                "ok": True,
                "tipo": "salida",
                "msg": f"SALIDA #{(n_escaneos + 1) // 2} registrada",
                "empleado": nombre_completo,
                "numero": numero_empleado,
                "hora": ahora[:5],
                "foto_url": f"/uploads/{foto_nombre}" if foto_nombre else None,
            })
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Error: {e}"}), 500


@app.route("/rrhh/asistencia/evidencia/<int:eid>")
@login_required
@permiso_requerido("rrhh", "leer")
def asistencia_evidencia(eid):
    """Muestra las fotos de evidencia de un empleado en un rango de fechas."""
    user = get_current_user()
    emp = db.get_empleado(eid)
    if not emp:
        abort(404)
    fi = request.args.get("fi", hoy_str())
    ff = request.args.get("ff", hoy_str())
    escaneos = db.query("""
        SELECT * FROM escaneos_qr
        WHERE id_empleado=%s AND fecha BETWEEN %s AND %s
        ORDER BY fecha DESC, hora DESC
    """, (eid, fi, ff))
    return render_template("asistencia_evidencia.html", user=user, emp=emp,
                           escaneos=escaneos, fi=fi, ff=ff)


# ── NÓMINA ────────────────────────────────────────────────────────

@app.route("/rrhh/nomina")
@login_required
@permiso_requerido("rrhh", "leer")
def rrhh_nomina():
    user = get_current_user()
    obras = db.get_obras()
    semana = request.args.get("semana", "")
    obra_filtro = request.args.get("obra", "")

    semanas_disponibles = db.get_semanas_nomina()
    if not semana and semanas_disponibles:
        semana = semanas_disponibles[0]["semana"]

    nomina = []
    kpis = None
    if semana:
        nomina = db.get_nomina_semanal(semana, int(obra_filtro) if obra_filtro else None)
        kpis = db.get_kpis_nomina(semana)

    return render_template("rrhh_nomina.html", user=user, obras=obras,
                           nomina=nomina, kpis=kpis, semana=semana,
                           semanas_disponibles=semanas_disponibles,
                           obra_filtro=obra_filtro,
                           empleados_lista=db.get_empleados(activo=1))

@app.route("/rrhh/nomina/generar", methods=["POST"])
@login_required
@permiso_requerido("rrhh", "crear")
def rrhh_nomina_generar():
    user = get_current_user()
    f = request.form
    fi = f["fecha_inicio"]
    ff = f["fecha_fin"]
    # Generar clave de semana usando sistema ESMA (Sem 1 = 29/dic/2025, ciclo 52)
    from datetime import datetime as dt
    fecha_ini = dt.strptime(fi, "%Y-%m-%d")
    sem_num = db.calcular_semana_combustible(fecha_ini)
    semana = f"SEM-{sem_num:02d}" if sem_num else f"SEM-{fecha_ini.isocalendar()[1]:02d}"
    obra = int(f["id_obra"]) if f.get("id_obra") else None
    count = db.generar_nomina_semanal(semana, fi, ff, user["id"], id_obra=obra)
    flash(f"Nómina generada para {count} empleados (semana {semana}).", "success")
    return redirect(url_for("rrhh_nomina", semana=semana))


@app.route("/rrhh/nomina/manual", methods=["POST"])
@login_required
@permiso_requerido("rrhh", "crear")
def rrhh_nomina_manual():
    """Inserta un registro individual de nómina de forma manual."""
    user = get_current_user()
    f = request.form
    fi = f["fecha_inicio"]
    ff = f["fecha_fin"]
    id_empleado = int(f["id_empleado"])
    dias = float(f.get("dias_trabajados") or 0)
    hrs_extra = float(f.get("horas_extra") or 0)
    salario_base = float(f.get("salario_base") or 0)
    pago_extras = float(f.get("pago_horas_extra") or 0)
    total = float(f.get("total_pagar") or 0)
    if total <= 0:
        total = salario_base + pago_extras

    # Calcular semana ESMA
    from datetime import datetime as dt
    fecha_ini = dt.strptime(fi, "%Y-%m-%d")
    sem_num = db.calcular_semana_combustible(fecha_ini)
    semana = f"SEM-{sem_num:02d}" if sem_num else f"SEM-{fecha_ini.isocalendar()[1]:02d}"

    db.execute("""
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
    """, (id_empleado, semana, fi, ff, dias,
          dias * 8, hrs_extra, salario_base, pago_extras, total, user["id"]))

    flash(f"Registro de nómina agregado ({semana}).", "success")
    return redirect(url_for("rrhh_nomina", semana=semana))


@app.route("/rrhh/nomina/aprobar", methods=["POST"])
@login_required
@permiso_requerido("rrhh", "editar")
def rrhh_nomina_aprobar():
    semana = request.form["semana"]
    db.aprobar_nomina(semana)
    flash(f"Nómina de semana {semana} aprobada.", "success")
    return redirect(url_for("rrhh_nomina", semana=semana))

@app.route("/rrhh/nomina/pagar", methods=["POST"])
@login_required
@permiso_requerido("rrhh", "editar")
def rrhh_nomina_pagar():
    semana = request.form["semana"]
    db.marcar_nomina_pagada(semana)
    flash(f"Nómina de semana {semana} marcada como pagada.", "success")
    return redirect(url_for("rrhh_nomina", semana=semana))


@app.route("/rrhh/nomina/importar", methods=["POST"])
@login_required
@permiso_requerido("rrhh", "crear")
def rrhh_nomina_importar():
    """Importa nómina semanal desde Excel.
    Detecta empleados, días trabajados, horas extra, y calcula la semana ESMA."""
    from openpyxl import load_workbook
    from datetime import datetime as _dt

    user = get_current_user()
    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        flash("Selecciona un archivo Excel.", "danger")
        return redirect(url_for("rrhh_nomina"))

    id_obra_form = request.form.get("id_obra") or None

    try:
        wb = load_workbook(archivo, data_only=True)
    except Exception as e:
        flash(f"Error al leer el archivo: {e}", "danger")
        return redirect(url_for("rrhh_nomina"))

    total_importados = 0
    semana_detectada = None

    for ws in wb.worksheets:
        # Buscar fila encabezado con columnas de nómina
        header_row = None
        col_map = {}
        fecha_ref = None

        for ri, row in enumerate(ws.iter_rows(min_row=1, max_row=20, values_only=True), start=1):
            # Buscar una fecha de referencia para calcular la semana
            for cell_val in row:
                if cell_val and isinstance(cell_val, _dt):
                    fecha_ref = cell_val
                    break
                if cell_val and isinstance(cell_val, str):
                    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
                        try:
                            fecha_ref = _dt.strptime(cell_val.strip(), fmt)
                            break
                        except ValueError:
                            continue
                if fecha_ref:
                    break

            # Detectar fila de encabezado
            row_str = [str(c or "").strip().upper() for c in row]
            if any(k in " ".join(row_str) for k in ["EMPLEADO", "NOMBRE", "TRABAJADOR"]):
                header_row = ri
                for ci, h in enumerate(row_str):
                    h_clean = h.strip()
                    if any(x in h_clean for x in ["EMPLEADO", "NOMBRE", "TRABAJADOR"]):
                        col_map["nombre"] = ci
                    elif "PUESTO" in h_clean or "CARGO" in h_clean:
                        col_map["puesto"] = ci
                    elif "DIA" in h_clean and ("TRAB" in h_clean or "LAB" in h_clean):
                        col_map["dias"] = ci
                    elif "DIA" in h_clean:
                        col_map.setdefault("dias", ci)
                    elif "EXTRA" in h_clean and "HORA" in h_clean:
                        col_map["horas_extra"] = ci
                    elif "EXTRA" in h_clean:
                        col_map.setdefault("horas_extra", ci)
                    elif "SALARIO" in h_clean and ("BASE" in h_clean or "DIAR" in h_clean):
                        col_map["salario"] = ci
                    elif "TOTAL" in h_clean and "PAGAR" in h_clean:
                        col_map["total"] = ci
                    elif "TOTAL" in h_clean:
                        col_map.setdefault("total", ci)
                break

        if not header_row or "nombre" not in col_map:
            continue  # Hoja sin estructura reconocible

        # Calcular semana ESMA desde la fecha detectada
        if not fecha_ref:
            # Usar fecha de hoy si no se detectó fecha
            fecha_ref = _dt.now()

        sem_num = db.calcular_semana_combustible(fecha_ref)
        semana_clave = f"SEM-{sem_num:02d}" if sem_num else f"SEM-{_dt.now().isocalendar()[1]:02d}"
        fecha_inicio = fecha_ref.strftime("%Y-%m-%d")
        # Fin de semana = inicio + 6 días
        from datetime import timedelta as _td
        fecha_fin_calc = (fecha_ref + _td(days=6)).strftime("%Y-%m-%d")

        if not semana_detectada:
            semana_detectada = semana_clave

        # Procesar filas de datos
        for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
            nombre_val = row[col_map["nombre"]] if col_map.get("nombre") is not None and len(row) > col_map["nombre"] else None
            if not nombre_val or str(nombre_val).strip() == "":
                continue

            nombre_str = str(nombre_val).strip()
            dias = float(row[col_map["dias"]] or 0) if col_map.get("dias") is not None and len(row) > col_map.get("dias", 999) else 0
            hrs_extra = float(row[col_map["horas_extra"]] or 0) if col_map.get("horas_extra") is not None and len(row) > col_map.get("horas_extra", 999) else 0
            salario_base = float(row[col_map["salario"]] or 0) if col_map.get("salario") is not None and len(row) > col_map.get("salario", 999) else 0
            total_pagar = float(row[col_map["total"]] or 0) if col_map.get("total") is not None and len(row) > col_map.get("total", 999) else 0

            if dias <= 0 and total_pagar <= 0:
                continue  # Fila vacía

            # Buscar empleado por nombre
            partes = nombre_str.split()
            empleados = db.get_empleados(search=nombre_str)
            id_empleado = empleados[0]["id"] if empleados else None

            if not id_empleado:
                # Crear empleado básico
                apellido_p = partes[-2] if len(partes) >= 3 else (partes[-1] if len(partes) >= 2 else "")
                apellido_m = partes[-1] if len(partes) >= 3 else ""
                nombre_e = " ".join(partes[:-2]) if len(partes) >= 3 else (partes[0] if partes else nombre_str)
                id_empleado = db.crear_empleado({
                    "nombre": nombre_e,
                    "apellido_paterno": apellido_p,
                    "apellido_materno": apellido_m,
                    "puesto": str(row[col_map["puesto"]]).strip() if col_map.get("puesto") is not None and len(row) > col_map.get("puesto", 999) else "",
                    "id_obra": int(id_obra_form) if id_obra_form else None,
                    "salario_diario": round(salario_base / dias, 2) if dias > 0 else 0,
                    "tipo_nomina": "IMSS",
                    "estatus": "activo",
                })

            # Calcular pago horas extra si no viene total
            pago_extras = round(total_pagar - salario_base, 2) if total_pagar > salario_base else 0
            if total_pagar <= 0:
                total_pagar = salario_base + pago_extras

            db.execute("""
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
            """, (id_empleado, semana_clave, fecha_inicio, fecha_fin_calc, dias,
                  dias * 8, hrs_extra, salario_base, pago_extras, total_pagar, user["id"]))
            total_importados += 1

    if total_importados > 0:
        flash(f"Nómina importada: {total_importados} registros (semana {semana_detectada}).", "success")
    else:
        flash("No se detectaron registros de nómina en el archivo.", "warning")

    return redirect(url_for("rrhh_nomina", semana=semana_detectada or ""))


# ══════════════════════════════════════════════════════════════════
#  ÓRDENES DE COMPRA
# ══════════════════════════════════════════════════════════════════

@app.route("/ordenes-compra")
@login_required
@permiso_requerido("ordenes_compra", "leer")
def ordenes_compra():
    user = get_current_user()
    obras = db.get_obras()
    obra_filtro = request.args.get("obra", "")
    estatus_filtro = request.args.get("estatus", "")
    proveedor_filtro = request.args.get("proveedor", "")
    fi = request.args.get("fecha_ini", "")
    ff = request.args.get("fecha_fin", "")
    ordenes = db.get_ordenes_compra(
        id_obra=int(obra_filtro) if obra_filtro else None,
        proveedor=proveedor_filtro or None,
        estatus=estatus_filtro or None,
        fi=fi or None, ff=ff or None
    )
    kpis = db.get_kpis_oc(
        id_obra=int(obra_filtro) if obra_filtro else None,
        fi=fi or None, ff=ff or None
    )
    return render_template("ordenes_compra.html", user=user, obras=obras,
                           ordenes=ordenes, kpis=kpis,
                           obra_filtro=obra_filtro, estatus_filtro=estatus_filtro,
                           proveedor_filtro=proveedor_filtro, fi=fi, ff=ff)


@app.route("/ordenes-compra/nueva", methods=["GET", "POST"])
@login_required
@permiso_requerido("ordenes_compra", "crear")
def orden_compra_nueva():
    user = get_current_user()
    obras = db.get_obras()
    if request.method == "POST":
        f = request.form
        id_obra = int(f["id_obra"]) if f.get("id_obra") else None
        numero = db.get_siguiente_numero_oc(id_obra)
        datos = {
            "numero_pedido": numero,
            "folio": f.get("folio") or None,
            "fecha": f.get("fecha") or hoy_str(),
            "tipo_pedido": f.get("tipo_pedido", "Materiales"),
            "id_obra": id_obra,
            "descripcion_obra": f.get("descripcion_obra") or None,
            "proveedor": f.get("proveedor") or None,
            "rfc_proveedor": f.get("rfc_proveedor") or None,
            "contacto_pago": f.get("contacto_pago") or None,
            "telefono_proveedor": f.get("telefono_proveedor") or None,
            "email_proveedor": f.get("email_proveedor") or None,
            "condiciones_pago": f.get("condiciones_pago") or None,
            "forma_pago": f.get("forma_pago") or None,
            "metodo_pago": f.get("metodo_pago") or None,
            "uso_cfdi": f.get("uso_cfdi") or None,
            "moneda": f.get("moneda", "MXN"),
            "tiempo_entrega": f.get("tiempo_entrega") or None,
            "subtotal": 0, "iva": 0, "total": 0,
            "flete_logistica": float(f["flete_logistica"]) if f.get("flete_logistica") else None,
            "retencion": float(f["retencion"]) if f.get("retencion") else None,
            "importe_letra": f.get("importe_letra") or None,
            "responsable": f.get("responsable") or "Elena de la Rocha Calderon",
            "estatus": "borrador",
            "observaciones": f.get("observaciones") or None,
            "id_codigo_costo": int(f["id_codigo_costo"]) if f.get("id_codigo_costo") else None,
            "creado_por": session["user_id"],
        }
        oid = db.crear_orden_compra(datos)
        # Guardar partidas
        descripciones = f.getlist("part_desc[]")
        cantidades = f.getlist("part_cant[]")
        unidades = f.getlist("part_unidad[]")
        precios = f.getlist("part_pu[]")
        for i, desc in enumerate(descripciones):
            if not desc.strip():
                continue
            cant = float(cantidades[i]) if i < len(cantidades) and cantidades[i] else 0
            uni = unidades[i] if i < len(unidades) else ""
            pu = float(precios[i]) if i < len(precios) and precios[i] else 0
            imp = round(cant * pu, 2)
            db.crear_partida_orden(oid, i + 1, desc.strip(), cant, uni, pu, imp)
        db.recalcular_totales_oc(oid)
        flash(f"Orden de Compra #{numero} creada.", "success")
        return redirect(url_for("orden_compra_detalle", oid=oid))
    proveedores = db.get_proveedores_oc()
    return render_template("orden_compra_form.html", user=user, obras=obras,
                           proveedores=proveedores, proveedores_autofill=db.get_proveedores_autofill(),
                           oc=None, partidas=[], codigos_costo=db.get_codigos_costo(),
                           tipos_pedido=db.TIPOS_PEDIDO_OC,
                           condiciones_pago=db.CONDICIONES_PAGO_OC,
                           monedas=db.MONEDAS_OC,
                           formas_pago=db.FORMAS_PAGO_OC,
                           metodos_pago=db.METODOS_PAGO_OC,
                           usos_cfdi=db.USOS_CFDI_OC)


@app.route("/ordenes-compra/<int:oid>")
@login_required
@permiso_requerido("ordenes_compra", "leer")
def orden_compra_detalle(oid):
    oc = db.get_orden_compra(oid)
    if not oc:
        abort(404)
    partidas = db.get_partidas_orden(oid)
    user = get_current_user()
    return render_template("orden_compra_detalle.html", user=user, oc=oc, partidas=partidas)


@app.route("/ordenes-compra/<int:oid>/pdf")
@login_required
@permiso_requerido("ordenes_compra", "leer")
def orden_compra_pdf(oid):
    """Genera y descarga el PDF de la Orden de Compra."""
    from xhtml2pdf import pisa
    from io import BytesIO

    oc = db.get_orden_compra(oid)
    if not oc:
        abort(404)
    partidas = db.get_partidas_orden(oid)

    # Logo path (absolute para xhtml2pdf)
    logo_path = os.path.join(os.path.dirname(__file__), "logo1.png").replace("\\", "/")
    if not os.path.exists(logo_path):
        logo_path = None

    html = render_template("orden_compra_pdf.html", oc=oc, partidas=partidas,
                           logo_path=logo_path)

    buffer = BytesIO()
    pdf = pisa.CreatePDF(html, dest=buffer, encoding="utf-8")
    if pdf.err:
        flash("Error al generar PDF.", "danger")
        return redirect(url_for("orden_compra_detalle", oid=oid))

    buffer.seek(0)
    folio = oc.get("folio") or f"OC-{oc['numero_pedido'] or oc['id']}"
    nombre = f"{folio}_{oc.get('proveedor','')[:30]}".replace(" ", "_").replace("/", "-")
    return send_file(buffer, as_attachment=True,
                     download_name=f"{nombre}.pdf",
                     mimetype="application/pdf")


@app.route("/ordenes-compra/<int:oid>/editar", methods=["GET", "POST"])
@login_required
@permiso_requerido("ordenes_compra", "editar")
def orden_compra_editar(oid):
    oc = db.get_orden_compra(oid)
    if not oc:
        abort(404)
    user = get_current_user()
    obras = db.get_obras()
    if request.method == "POST":
        f = request.form
        datos = {
            "id": oid,
            "fecha": f.get("fecha") or str(oc["fecha"]),
            "tipo_pedido": f.get("tipo_pedido", oc["tipo_pedido"]),
            "id_obra": int(f["id_obra"]) if f.get("id_obra") else oc["id_obra"],
            "descripcion_obra": f.get("descripcion_obra") or None,
            "proveedor": f.get("proveedor") or None,
            "rfc_proveedor": f.get("rfc_proveedor") or None,
            "contacto_pago": f.get("contacto_pago") or None,
            "telefono_proveedor": f.get("telefono_proveedor") or None,
            "email_proveedor": f.get("email_proveedor") or None,
            "condiciones_pago": f.get("condiciones_pago") or None,
            "forma_pago": f.get("forma_pago") or None,
            "metodo_pago": f.get("metodo_pago") or None,
            "uso_cfdi": f.get("uso_cfdi") or None,
            "moneda": f.get("moneda", "MXN"),
            "tiempo_entrega": f.get("tiempo_entrega") or None,
            "flete_logistica": float(f["flete_logistica"]) if f.get("flete_logistica") else None,
            "retencion": float(f["retencion"]) if f.get("retencion") else None,
            "importe_letra": f.get("importe_letra") or None,
            "responsable": f.get("responsable") or "Elena de la Rocha Calderon",
            "observaciones": f.get("observaciones") or None,
            "id_codigo_costo": int(f["id_codigo_costo"]) if f.get("id_codigo_costo") else None,
        }
        db.actualizar_orden_compra(oid, datos)
        # Reemplazar partidas
        db.eliminar_partidas_orden(oid)
        descripciones = f.getlist("part_desc[]")
        cantidades = f.getlist("part_cant[]")
        unidades = f.getlist("part_unidad[]")
        precios = f.getlist("part_pu[]")
        for i, desc in enumerate(descripciones):
            if not desc.strip():
                continue
            cant = float(cantidades[i]) if i < len(cantidades) and cantidades[i] else 0
            uni = unidades[i] if i < len(unidades) else ""
            pu = float(precios[i]) if i < len(precios) and precios[i] else 0
            imp = round(cant * pu, 2)
            db.crear_partida_orden(oid, i + 1, desc.strip(), cant, uni, pu, imp)
        db.recalcular_totales_oc(oid)
        flash("Orden de Compra actualizada.", "success")
        return redirect(url_for("orden_compra_detalle", oid=oid))
    partidas = db.get_partidas_orden(oid)
    proveedores = db.get_proveedores_oc()
    return render_template("orden_compra_form.html", user=user, obras=obras,
                           proveedores=proveedores, proveedores_autofill=db.get_proveedores_autofill(),
                           oc=oc, partidas=partidas, codigos_costo=db.get_codigos_costo(),
                           tipos_pedido=db.TIPOS_PEDIDO_OC,
                           condiciones_pago=db.CONDICIONES_PAGO_OC,
                           monedas=db.MONEDAS_OC,
                           formas_pago=db.FORMAS_PAGO_OC,
                           metodos_pago=db.METODOS_PAGO_OC,
                           usos_cfdi=db.USOS_CFDI_OC)


@app.route("/ordenes-compra/<int:oid>/enviar", methods=["POST"])
@login_required
@permiso_requerido("ordenes_compra", "crear")
def orden_compra_enviar(oid):
    db.enviar_orden_compra(oid)
    flash("Orden de Compra enviada a autorización.", "success")
    return redirect(url_for("orden_compra_detalle", oid=oid))


@app.route("/ordenes-compra/<int:oid>/autorizar", methods=["POST"])
@login_required
@permiso_requerido("ordenes_compra", "editar")
@rol_minimo("supervisor")
def orden_compra_autorizar(oid):
    user = get_current_user()
    db.autorizar_orden_compra(oid, user["id"])
    flash("Orden de Compra autorizada.", "success")
    return redirect(url_for("orden_compra_detalle", oid=oid))


@app.route("/ordenes-compra/<int:oid>/rechazar", methods=["POST"])
@login_required
@permiso_requerido("ordenes_compra", "editar")
@rol_minimo("supervisor")
def orden_compra_rechazar(oid):
    user = get_current_user()
    obs = request.form.get("observaciones", "")
    db.rechazar_orden_compra(oid, user["id"], obs)
    flash("Orden de Compra rechazada.", "success")
    return redirect(url_for("orden_compra_detalle", oid=oid))


@app.route("/ordenes-compra/<int:oid>/cancelar", methods=["POST"])
@login_required
@permiso_requerido("ordenes_compra", "eliminar")
def orden_compra_cancelar(oid):
    obs = request.form.get("observaciones", "")
    db.cancelar_orden_compra(oid, obs)
    flash("Orden de Compra cancelada.", "success")
    return redirect(url_for("orden_compra_detalle", oid=oid))


@app.route("/ordenes-compra/importar", methods=["GET", "POST"])
@login_required
@permiso_requerido("ordenes_compra", "crear")
def orden_compra_importar():
    """Importa ordenes de compra desde un archivo Excel formato ESMA.
    Cada hoja del Excel representa una orden de compra independiente con
    encabezado (proveedor, RFC, moneda, condiciones, obra) y tabla de partidas."""
    user = get_current_user()
    obras = db.get_obras()

    if request.method == "GET":
        return render_template("orden_compra_importar.html", user=user, obras=obras)

    from openpyxl import load_workbook

    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        flash("Selecciona un archivo Excel.", "danger")
        return redirect(url_for("orden_compra_importar"))

    id_obra_default = int(request.form["id_obra"]) if request.form.get("id_obra") else None

    try:
        wb = load_workbook(archivo, data_only=True)
    except Exception as e:
        flash(f"Error al leer el archivo: {e}", "danger")
        return redirect(url_for("orden_compra_importar"))

    # ── Utilidades ──────────────────────────────────────────────────────
    def _float(val):
        if val is None:
            return 0.0
        try:
            s = str(val).replace("$", "").replace(",", "").replace(" ", "").strip()
            if s in ("", "-", "-0", "- 0"):
                return 0.0
            return float(s)
        except (ValueError, TypeError):
            return 0.0

    def _str(val):
        """Convierte a string limpio o None."""
        if val is None:
            return None
        s = str(val).strip()
        return s if s else None

    def _buscar_valor_derecha(ws, texto_buscar, max_row=35):
        """Busca un label en la hoja y devuelve el valor de la celda(s) a su derecha."""
        texto_lower = texto_buscar.lower().replace(":", "").strip()
        for row in ws.iter_rows(min_row=1, max_row=max_row, max_col=ws.max_column):
            for idx, cell in enumerate(row):
                if cell.value and texto_lower in str(cell.value).lower().replace(":", "").strip():
                    # Buscar valor en celdas siguientes de la misma fila
                    for offset in range(1, min(5, len(row) - idx)):
                        next_cell = row[idx + offset]
                        if next_cell.value is not None and str(next_cell.value).strip():
                            return str(next_cell.value).strip()
                    return None
        return None

    def _buscar_valor_misma_fila(ws, texto_buscar, col_offset=1, max_row=35):
        """Busca un label y devuelve el valor N celdas a la derecha."""
        texto_lower = texto_buscar.lower().replace(":", "").strip()
        for row in ws.iter_rows(min_row=1, max_row=max_row, max_col=ws.max_column):
            for idx, cell in enumerate(row):
                if cell.value and texto_lower in str(cell.value).lower().replace(":", "").strip():
                    target = idx + col_offset
                    if target < len(row) and row[target].value is not None:
                        return str(row[target].value).strip()
                    # Si no hay en offset, buscar la primera no-vacia a la derecha
                    for offset in range(1, min(6, len(row) - idx)):
                        if row[idx + offset].value is not None and str(row[idx + offset].value).strip():
                            return str(row[idx + offset].value).strip()
                    return None
        return None

    def _parsear_fecha(ws, max_row=20):
        """Busca la fecha en la hoja (label 'Fecha:')."""
        val = _buscar_valor_derecha(ws, "Fecha")
        if val:
            # Intentar parsear distintos formatos
            import re
            from datetime import datetime as dt
            # formato m/d/yy o mm/dd/yy
            m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", val)
            if m:
                mes, dia, anio = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if anio < 100:
                    anio += 2000
                try:
                    return dt(anio, mes, dia).strftime("%Y-%m-%d")
                except ValueError:
                    pass
            # formato yyyy-mm-dd
            m = re.match(r"(\d{4})-(\d{2})-(\d{2})", val)
            if m:
                return val[:10]
        return None

    def _extraer_partidas(ws):
        """Extrae la tabla de partidas (POS, DESCRIPCION, CANTIDAD, UNIDAD, P.U., IMPORTE)."""
        partidas = []
        # Buscar fila de encabezado de tabla (contiene POS y DESCRIPCION)
        header_row_idx = None
        col_map = {}  # pos, descripcion, cantidad, unidad, precio_unitario, importe

        for row_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=ws.max_row, values_only=False), start=1):
            row_vals = [str(c.value or "").strip().lower() for c in row]
            # Buscar fila que tenga "pos" y "descripci" en alguna celda
            has_pos = any("pos" == v for v in row_vals)
            has_desc = any("descripci" in v for v in row_vals)
            has_cantidad = any("cantidad" in v for v in row_vals)
            if has_pos and has_desc:
                header_row_idx = row_idx
                for ci, val in enumerate(row_vals):
                    if val == "pos":
                        col_map["pos"] = ci
                    elif "descripci" in val:
                        col_map["descripcion"] = ci
                    elif "cantidad" in val:
                        col_map["cantidad"] = ci
                    elif "unidad" in val:
                        col_map["unidad"] = ci
                    elif "precio" in val or "p.u" in val:
                        col_map["precio_unitario"] = ci
                    elif "importe" in val or "monto" in val:
                        col_map["importe"] = ci
                break

        if header_row_idx is None:
            return partidas

        # Si no se encontraron todas las columnas, usar posiciones relativas
        # El formato ESMA tiene: POS | DESCRIPCION | (vacias) | CANTIDAD | UNIDAD | PRECIO UNITARIO | IMPORTE
        # Usamos fallback basado en la posicion de POS
        pos_col = col_map.get("pos", 0)

        # Leer filas de datos despues del header
        for row in ws.iter_rows(min_row=header_row_idx + 1, max_row=ws.max_row, values_only=True):
            if not row:
                continue
            row_list = list(row)

            # Detectar fin de tabla: si encontramos SUBTOTAL o IMPORTE CON LETRA
            row_text = " ".join(str(c or "").upper() for c in row_list)
            if "SUBTOTAL" in row_text and "DESCRIPCI" not in row_text:
                break
            if "IMPORTE CON LETRA" in row_text:
                break

            # Extraer POS - debe ser numerico
            pos_val = row_list[pos_col] if pos_col < len(row_list) else None
            try:
                pos_num = int(float(str(pos_val or "0")))
            except (ValueError, TypeError):
                pos_num = 0
            if pos_num <= 0:
                continue

            # Extraer descripcion: buscar en columna de descripcion
            desc_col = col_map.get("descripcion", pos_col + 1)
            desc = _str(row_list[desc_col]) if desc_col < len(row_list) else None
            if not desc:
                # Intentar concatenar celdas contiguas no vacias despues de POS
                parts = []
                for ci in range(pos_col + 1, min(pos_col + 5, len(row_list))):
                    v = _str(row_list[ci])
                    if v:
                        try:
                            float(str(v).replace("$", "").replace(",", ""))
                            break  # Llegamos a numeros
                        except ValueError:
                            parts.append(v)
                    else:
                        continue
                desc = " ".join(parts) if parts else None

            if not desc:
                continue

            # Extraer numeros: cantidad, unidad, precio, importe
            # Buscar de derecha a izquierda los valores numericos
            cantidad_col = col_map.get("cantidad")
            unidad_col = col_map.get("unidad")
            pu_col = col_map.get("precio_unitario")
            importe_col = col_map.get("importe")

            if cantidad_col is not None:
                cantidad = _float(row_list[cantidad_col] if cantidad_col < len(row_list) else 0)
            else:
                # Fallback: buscar primer numero despues de la descripcion
                cantidad = 0
                for ci in range(desc_col + 1, len(row_list)):
                    v = _float(row_list[ci])
                    if v > 0:
                        cantidad = v
                        break

            if unidad_col is not None:
                unidad = _str(row_list[unidad_col]) if unidad_col < len(row_list) else ""
            else:
                unidad = ""
                # Buscar texto de unidad entre descripcion y numeros
                for ci in range(desc_col + 1, len(row_list)):
                    v = _str(row_list[ci])
                    if v and not v.replace("$", "").replace(",", "").replace(".", "").replace("-", "").strip().isdigit():
                        try:
                            float(v.replace("$", "").replace(",", ""))
                        except ValueError:
                            unidad = v
                            break

            if pu_col is not None:
                pu = _float(row_list[pu_col] if pu_col < len(row_list) else 0)
            else:
                pu = 0

            if importe_col is not None:
                importe = _float(row_list[importe_col] if importe_col < len(row_list) else 0)
            else:
                importe = 0

            # Si no tenemos precio pero si importe y cantidad, calcular
            if pu == 0 and importe > 0 and cantidad > 0:
                pu = round(importe / cantidad, 2)
            # Si no tenemos importe pero si precio y cantidad, calcular
            if importe == 0 and pu > 0 and cantidad > 0:
                importe = round(cantidad * pu, 2)

            partidas.append({
                "pos": pos_num,
                "descripcion": desc,
                "cantidad": cantidad,
                "unidad": unidad or "",
                "precio_unitario": pu,
                "importe": importe,
            })

        return partidas

    # ── Hojas a ignorar (catálogos, condiciones) ────────────────────────
    hojas_ignorar = {"catalago", "condiciones", "catalogo"}

    # ── Procesar cada hoja como una OC ──────────────────────────────────
    count = 0
    errores = []

    for ws in wb.worksheets:
        nombre_hoja = (ws.title or "").strip()
        if nombre_hoja.lower() in hojas_ignorar:
            continue

        # Extraer metadatos del encabezado ESMA
        proveedor = _buscar_valor_derecha(ws, "Proveedor")
        rfc_proveedor = _buscar_valor_derecha(ws, "RFC")
        # El RFC de ESMA (EIN900430AH4) esta primero; el del proveedor esta en otra fila
        # Buscar el segundo RFC que no sea el de ESMA
        rfc_encontrado = None
        for row in ws.iter_rows(min_row=1, max_row=30, max_col=ws.max_column):
            for idx, cell in enumerate(row):
                if cell.value and "rfc" in str(cell.value).lower().replace(":", "").strip():
                    # Buscar valor a la derecha
                    for offset in range(1, min(5, len(row) - idx)):
                        next_cell = row[idx + offset]
                        if next_cell.value and str(next_cell.value).strip():
                            val = str(next_cell.value).strip()
                            if val != "EIN900430AH4":
                                rfc_encontrado = val
                            break
        rfc_proveedor = rfc_encontrado

        condiciones_pago = _buscar_valor_derecha(ws, "Condiciones de pago")
        moneda = _buscar_valor_derecha(ws, "Moneda") or "MXN"
        tipo_pedido = _buscar_valor_derecha(ws, "Tipo de Pedido") or "Materiales"
        numero_pedido = _buscar_valor_derecha(ws, "Número de Pedido") or _buscar_valor_derecha(ws, "Numero de Pedido")
        forma_pago = _buscar_valor_derecha(ws, "Forma de pago")
        metodo_pago = _buscar_valor_derecha(ws, "Método de pago") or _buscar_valor_derecha(ws, "Metodo de pago")
        uso_cfdi = _buscar_valor_derecha(ws, "Uso de CFDI")
        tiempo_entrega = _buscar_valor_derecha(ws, "Tiempo de entrega")
        contacto_pago = _buscar_valor_derecha(ws, "Contacto de Pagos")
        telefono_prov = _buscar_valor_derecha(ws, "Teléfono") or _buscar_valor_derecha(ws, "Telefono")
        email_prov = _buscar_valor_derecha(ws, "E-mail") or _buscar_valor_derecha(ws, "Email")
        proyecto_obra = _buscar_valor_derecha(ws, "Proyecto / Obra") or _buscar_valor_derecha(ws, "Proyecto")
        fecha_str = _parsear_fecha(ws)

        # Extraer partidas
        partidas = _extraer_partidas(ws)

        if not partidas:
            errores.append(f"Hoja '{nombre_hoja}': sin partidas válidas")
            continue

        if not proveedor:
            errores.append(f"Hoja '{nombre_hoja}': sin proveedor")
            continue

        # Determinar obra: usar la seleccionada o buscar por nombre del proyecto
        id_obra = id_obra_default
        if proyecto_obra and not id_obra:
            # Intentar buscar obra por nombre
            for o in obras:
                if o["nombre"].lower().strip() == proyecto_obra.lower().strip():
                    id_obra = o["id"]
                    break

        # Crear la orden
        try:
            numero = numero_pedido or str(db.get_siguiente_numero_oc(id_obra))
            oid = db.crear_orden_compra({
                "numero_pedido": numero,
                "folio": None,
                "fecha": fecha_str or hoy_str(),
                "tipo_pedido": tipo_pedido,
                "id_obra": id_obra,
                "descripcion_obra": proyecto_obra,
                "proveedor": proveedor,
                "rfc_proveedor": rfc_proveedor,
                "contacto_pago": contacto_pago,
                "telefono_proveedor": telefono_prov,
                "email_proveedor": email_prov,
                "condiciones_pago": condiciones_pago,
                "forma_pago": forma_pago,
                "metodo_pago": metodo_pago,
                "uso_cfdi": uso_cfdi,
                "moneda": moneda,
                "tiempo_entrega": tiempo_entrega,
                "subtotal": 0, "iva": 0, "total": 0,
                "flete_logistica": None,
                "retencion": None,
                "importe_letra": None,
                "responsable": "Elena de la Rocha Calderon",
                "estatus": "borrador",
                "observaciones": f"Importado desde Excel: {archivo.filename} (hoja: {nombre_hoja})",
                "creado_por": session["user_id"],
            })
            for p in partidas:
                db.crear_partida_orden(oid, p["pos"], p["descripcion"],
                                       p["cantidad"], p["unidad"],
                                       p["precio_unitario"], p["importe"])
            db.recalcular_totales_oc(oid)
            count += 1
        except Exception as e:
            errores.append(f"Hoja '{nombre_hoja}': error al guardar - {e}")

    if count:
        msg = f"Importacion completada: {count} orden(es) de compra creada(s)."
        if errores:
            msg += f" ({len(errores)} hoja(s) con problemas)"
        flash(msg, "success")
    else:
        flash("No se encontraron datos validos. " + "; ".join(errores[:3]), "warning")
    return redirect(url_for("ordenes_compra"))


@app.route("/ordenes-compra/exportar/excel")
@login_required
@permiso_requerido("ordenes_compra", "leer")
def ordenes_compra_exportar_excel():
    """Exporta las ordenes de compra a Excel con sus partidas."""
    obra_filtro = request.args.get("obra", "")
    proveedor_filtro = request.args.get("proveedor", "")
    estatus_filtro = request.args.get("estatus", "")
    fi = request.args.get("fecha_ini", "")
    ff = request.args.get("fecha_fin", "")
    ordenes = db.get_ordenes_compra(
        id_obra=int(obra_filtro) if obra_filtro else None,
        proveedor=proveedor_filtro or None,
        estatus=estatus_filtro or None,
        fi=fi or None, ff=ff or None,
        limit=500
    )

    wb = Workbook()
    FONT_HEADER = Font(bold=True, color="FFFFFF")
    FILL_HEADER = PatternFill("solid", fgColor="2E3192")
    ALIGN_C = Alignment(horizontal="center")

    def auto_width(ws):
        for col in ws.columns:
            mx = max((len(str(c.value or "")) for c in col), default=10)
            ws.column_dimensions[col[0].column_letter].width = min(mx + 4, 42)

    # Hoja 1: Resumen OC
    ws = wb.active
    ws.title = "Ordenes de Compra"
    headers = ["# Pedido", "Folio", "Fecha", "Tipo", "Obra", "Proveedor",
               "RFC", "Moneda", "Subtotal", "IVA", "Total", "Estatus",
               "Condiciones pago", "Responsable", "Creado"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.alignment = ALIGN_C
    for oc in ordenes:
        ws.append([
            oc.get("numero_pedido") or oc.get("id"),
            oc.get("folio") or "",
            str(oc.get("fecha") or ""),
            oc.get("tipo_pedido") or "",
            oc.get("obra_nombre") or "",
            oc.get("proveedor") or "",
            oc.get("rfc_proveedor") or "",
            oc.get("moneda", "MXN"),
            float(oc.get("subtotal") or 0),
            float(oc.get("iva") or 0),
            float(oc.get("total") or 0),
            oc.get("estatus", ""),
            oc.get("condiciones_pago") or "",
            oc.get("responsable") or "",
            str(oc.get("creado_en") or ""),
        ])
    auto_width(ws)

    # Hoja 2: Partidas detalle
    ws2 = wb.create_sheet("Partidas")
    headers2 = ["# Pedido", "Proveedor", "Fecha", "Pos", "Descripcion",
                "Cantidad", "Unidad", "P.U.", "Importe"]
    ws2.append(headers2)
    for cell in ws2[1]:
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.alignment = ALIGN_C
    for oc in ordenes:
        partidas = db.get_partidas_orden(oc["id"])
        for p in partidas:
            ws2.append([
                oc.get("numero_pedido") or oc.get("id"),
                oc.get("proveedor") or "",
                str(oc.get("fecha") or ""),
                p.get("pos") or "",
                p.get("descripcion") or "",
                float(p.get("cantidad") or 0),
                p.get("unidad") or "",
                float(p.get("precio_unitario") or 0),
                float(p.get("importe") or 0),
            ])
    auto_width(ws2)

    nombre_archivo = f"Ordenes_Compra_{hoy_str()}.xlsx"
    ruta = os.path.join(UPLOAD_FOLDER, nombre_archivo)
    wb.save(ruta)
    return send_file(ruta, as_attachment=True, download_name=nombre_archivo)

# ══════════════════════════════════════════════════════════════════
#  PROVEEDORES
# ══════════════════════════════════════════════════════════════════

@app.route("/proveedores")
@login_required
@permiso_requerido("proveedores", "leer")
def proveedores():
    user = get_current_user()
    search = request.args.get("q", "")
    tipo_filtro = request.args.get("tipo", "")
    estado_filtro = request.args.get("estado", "activos")
    activo = None if estado_filtro == "todos" else (0 if estado_filtro == "inactivos" else 1)
    lista = db.get_proveedores(search=search or None, tipo=tipo_filtro or None, activo=activo)
    return render_template("proveedores.html", user=user, proveedores=lista,
                           search=search, tipo_filtro=tipo_filtro, estado_filtro=estado_filtro,
                           tipos=db.TIPOS_PROVEEDOR)


@app.route("/proveedores/nuevo", methods=["GET", "POST"])
@login_required
@permiso_requerido("proveedores", "crear")
def proveedor_nuevo():
    user = get_current_user()
    if request.method == "POST":
        f = request.form
        datos = {
            "razon_social": f["razon_social"].strip(),
            "tipo_persona": f.get("tipo_persona", "moral"),
            "rfc": (f.get("rfc") or "").strip().upper() or None,
            "tipo_proveedor": f.get("tipo_proveedor") or None,
            "direccion": f.get("direccion") or None,
            "ciudad": f.get("ciudad") or None,
            "estado": f.get("estado") or None,
            "cp": f.get("cp") or None,
            "pais": f.get("pais") or "México",
            "telefono": f.get("telefono") or None,
            "email": f.get("email") or None,
            "contacto": f.get("contacto") or None,
            "banco": f.get("banco") or None,
            "cuenta_clabe": f.get("cuenta_clabe") or None,
            "condiciones_pago_habitual": f.get("condiciones_pago_habitual") or None,
            "observaciones": f.get("observaciones") or None,
            "creado_por": session["user_id"],
        }
        pid = db.crear_proveedor(datos)
        flash(f"Proveedor '{datos['razon_social']}' registrado.", "success")
        return redirect(url_for("proveedor_detalle", pid=pid))
    return render_template("proveedor_form.html", user=user, prov=None, accion="Nuevo",
                           tipos=db.TIPOS_PROVEEDOR, condiciones_pago=db.CONDICIONES_PAGO_OC)


@app.route("/proveedores/<int:pid>")
@login_required
@permiso_requerido("proveedores", "leer")
def proveedor_detalle(pid):
    prov = db.get_proveedor(pid)
    if not prov:
        abort(404)
    user = get_current_user()
    evaluaciones = db.get_evaluaciones_proveedor(pid)
    calif = db.get_calificacion_promedio_proveedor(pid)
    obras = db.get_obras()
    import json
    criterios_servicio = db.CRITERIOS_EVALUACION_SERVICIO
    criterios_materiales = db.CRITERIOS_EVALUACION_MATERIALES
    # JSON para JavaScript (solo codigo y peso por rubro)
    cs_json = json.dumps({k: {"peso": v["peso"], "criterios": v["criterios"]} for k, v in criterios_servicio.items()})
    cm_json = json.dumps({k: {"peso": v["peso"], "criterios": v["criterios"]} for k, v in criterios_materiales.items()})
    return render_template("proveedor_detalle.html", user=user, prov=prov,
                           evaluaciones=evaluaciones, calif=calif, obras=obras,
                           criterios_servicio=criterios_servicio,
                           criterios_materiales=criterios_materiales,
                           criterios_servicio_json=cs_json,
                           criterios_materiales_json=cm_json)


@app.route("/proveedores/<int:pid>/editar", methods=["GET", "POST"])
@login_required
@permiso_requerido("proveedores", "editar")
def proveedor_editar(pid):
    prov = db.get_proveedor(pid)
    if not prov:
        abort(404)
    user = get_current_user()
    if request.method == "POST":
        f = request.form
        datos = {
            "razon_social": f["razon_social"].strip(),
            "tipo_persona": f.get("tipo_persona", "moral"),
            "rfc": (f.get("rfc") or "").strip().upper() or None,
            "tipo_proveedor": f.get("tipo_proveedor") or None,
            "direccion": f.get("direccion") or None,
            "ciudad": f.get("ciudad") or None,
            "estado": f.get("estado") or None,
            "cp": f.get("cp") or None,
            "pais": f.get("pais") or "México",
            "telefono": f.get("telefono") or None,
            "email": f.get("email") or None,
            "contacto": f.get("contacto") or None,
            "banco": f.get("banco") or None,
            "cuenta_clabe": f.get("cuenta_clabe") or None,
            "condiciones_pago_habitual": f.get("condiciones_pago_habitual") or None,
            "observaciones": f.get("observaciones") or None,
        }
        db.actualizar_proveedor(pid, datos)
        flash("Proveedor actualizado.", "success")
        return redirect(url_for("proveedor_detalle", pid=pid))
    return render_template("proveedor_form.html", user=user, prov=prov, accion="Editar",
                           tipos=db.TIPOS_PROVEEDOR, condiciones_pago=db.CONDICIONES_PAGO_OC)


@app.route("/proveedores/<int:pid>/estado", methods=["POST"])
@login_required
@permiso_requerido("proveedores", "eliminar")
def proveedor_cambiar_estado(pid):
    nuevo = 0 if request.form.get("activo") == "0" else 1
    db.cambiar_estado_proveedor(pid, nuevo)
    flash("Proveedor reactivado." if nuevo else "Proveedor dado de baja.", "success")
    return redirect(url_for("proveedor_detalle", pid=pid))


@app.route("/proveedores/<int:pid>/evaluar", methods=["POST"])
@login_required
@permiso_requerido("proveedores", "crear")
def proveedor_evaluar(pid):
    f = request.form
    tipo_eval = f.get("tipo_evaluacion", "servicio")

    # Recoger sub-criterios del formulario (campos con prefijo crit_)
    criterios = {}
    config = db.CRITERIOS_EVALUACION_SERVICIO if tipo_eval == "servicio" else db.CRITERIOS_EVALUACION_MATERIALES
    for rubro_key, rubro in config.items():
        for codigo, _ in rubro["criterios"]:
            val = f.get(f"crit_{codigo}", "0")
            criterios[codigo] = float(val) if val else 0

    datos = {
        "id_proveedor": pid,
        "id_obra": int(f["id_obra"]) if f.get("id_obra") else None,
        "tipo_evaluacion": tipo_eval,
        "evaluador": f.get("evaluador") or None,
        "fecha": f.get("fecha") or hoy_str(),
        "fecha_inicio": f.get("fecha_inicio") or None,
        "fecha_fin": f.get("fecha_fin") or None,
        "objeto_contrato": f.get("objeto_contrato") or None,
        "num_contrato": f.get("num_contrato") or None,
        "comentarios": f.get("comentarios") or None,
        "criterios": criterios,
    }
    db.crear_evaluacion_proveedor(datos)
    flash("Evaluación registrada.", "success")
    return redirect(url_for("proveedor_detalle", pid=pid))


# ══════════════════════════════════════════════════════════════════
#  PRESUPUESTO Y CÓDIGOS DE COSTO
# ══════════════════════════════════════════════════════════════════

@app.route("/presupuesto/codigos")
@login_required
@permiso_requerido("presupuesto", "leer")
def codigos_costo():
    user = get_current_user()
    search = request.args.get("q", "")
    lista = db.get_codigos_costo(search=search or None)
    return render_template("codigos_costo.html", user=user, codigos=lista, search=search)


@app.route("/presupuesto/codigos/importar", methods=["GET", "POST"])
@login_required
@permiso_requerido("presupuesto", "crear")
def codigos_costo_importar():
    user = get_current_user()
    if request.method == "GET":
        return render_template("codigos_costo_importar.html", user=user)

    from openpyxl import load_workbook
    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        flash("Selecciona el archivo 'Códigos de costo_Import_template'.", "danger")
        return redirect(url_for("codigos_costo_importar"))
    try:
        wb = load_workbook(archivo, data_only=True)
        creados, actualizados = db.importar_codigos_costo_excel(wb)
    except Exception as e:
        flash(f"Error al importar códigos de costo: {e}", "danger")
        return redirect(url_for("codigos_costo_importar"))
    flash(f"Catálogo de códigos de costo importado: {creados} nuevos, {actualizados} actualizados.", "success")
    return redirect(url_for("codigos_costo"))


@app.route("/presupuesto/codigos/nuevo", methods=["GET", "POST"])
@login_required
@permiso_requerido("presupuesto", "crear")
def codigo_costo_nuevo():
    user = get_current_user()
    if request.method == "POST":
        f = request.form
        n1 = f.get("nivel1", "").strip() or None
        n2 = f.get("nivel2", "").strip() or None
        n3 = f.get("nivel3", "").strip() or None
        n4 = f.get("nivel4", "").strip() or None
        n5 = f.get("nivel5", "").strip() or None
        desc = f.get("descripcion", "").strip()
        tipo = f.get("tipo_costo", "").strip() or None
        if not desc:
            flash("La descripción es obligatoria.", "danger")
            return redirect(url_for("codigo_costo_nuevo"))
        niveles = [n for n in (n1, n2, n3, n4, n5) if n]
        if not niveles:
            flash("Al menos un nivel es obligatorio.", "danger")
            return redirect(url_for("codigo_costo_nuevo"))
        codigo = "-".join(niveles)
        db.upsert_codigo_costo(codigo, desc, n1, n2, n3, n4, n5, tipo)
        flash(f"Código {codigo} guardado.", "success")
        return redirect(url_for("codigos_costo"))
    return render_template("codigo_costo_form.html", user=user, codigo=None)


@app.route("/presupuesto/codigos/<int:cid>/editar", methods=["GET", "POST"])
@login_required
@permiso_requerido("presupuesto", "editar")
def codigo_costo_editar(cid):
    user = get_current_user()
    codigo = db.get_codigo_costo(cid)
    if not codigo:
        abort(404)
    if request.method == "POST":
        f = request.form
        n1 = f.get("nivel1", "").strip() or None
        n2 = f.get("nivel2", "").strip() or None
        n3 = f.get("nivel3", "").strip() or None
        n4 = f.get("nivel4", "").strip() or None
        n5 = f.get("nivel5", "").strip() or None
        desc = f.get("descripcion", "").strip()
        tipo = f.get("tipo_costo", "").strip() or None
        if not desc:
            flash("La descripción es obligatoria.", "danger")
            return redirect(url_for("codigo_costo_editar", cid=cid))
        niveles = [n for n in (n1, n2, n3, n4, n5) if n]
        nuevo_codigo = "-".join(niveles) if niveles else codigo["codigo"]
        db.execute("""UPDATE codigos_costo SET codigo=%s, nivel1=%s, nivel2=%s, nivel3=%s,
                      nivel4=%s, nivel5=%s, descripcion=%s, tipo_costo=%s WHERE id=%s""",
                   (nuevo_codigo, n1, n2, n3, n4, n5, desc, tipo, cid))
        flash(f"Código {nuevo_codigo} actualizado.", "success")
        return redirect(url_for("codigos_costo"))
    return render_template("codigo_costo_form.html", user=user, codigo=codigo)


@app.route("/presupuesto/codigos/<int:cid>/toggle", methods=["POST"])
@login_required
@permiso_requerido("presupuesto", "editar")
def codigo_costo_toggle(cid):
    db.execute("UPDATE codigos_costo SET activo = NOT activo WHERE id=%s", (cid,))
    flash("Estado actualizado.", "success")
    return redirect(url_for("codigos_costo"))


@app.route("/presupuesto")
@login_required
@permiso_requerido("presupuesto", "leer")
def presupuesto():
    user = get_current_user()
    obras = db.get_obras()
    obra_id = request.args.get("obra", "")
    lineas = db.get_presupuesto_obra(int(obra_id)) if obra_id else []
    kpis = db.get_kpis_presupuesto(int(obra_id)) if obra_id else None
    return render_template("presupuesto.html", user=user, obras=obras,
                           obra_id=obra_id, lineas=lineas, kpis=kpis)


@app.route("/presupuesto/importar", methods=["GET", "POST"])
@login_required
@permiso_requerido("presupuesto", "crear")
def presupuesto_importar():
    """Importa budget_details.csv (presupuesto por código de costo) y/o
    direct_costs.csv (costos directos/facturas) exportados de Procore para una obra."""
    user = get_current_user()
    obras = db.get_obras()
    if request.method == "GET":
        return render_template("presupuesto_importar.html", user=user, obras=obras)

    import csv, io
    obra_id = request.form.get("id_obra")
    if not obra_id:
        flash("Selecciona la obra.", "danger")
        return redirect(url_for("presupuesto_importar"))
    obra_id = int(obra_id)

    total_presupuesto = 0
    total_costos = 0

    archivo_presupuesto = request.files.get("archivo_presupuesto")
    if archivo_presupuesto and archivo_presupuesto.filename:
        try:
            texto = archivo_presupuesto.stream.read().decode("utf-8-sig")
            filas = list(csv.DictReader(io.StringIO(texto)))
            total_presupuesto = db.importar_presupuesto_csv(obra_id, filas)
        except Exception as e:
            flash(f"Error al importar presupuesto: {e}", "danger")
            return redirect(url_for("presupuesto_importar"))

    archivo_costos = request.files.get("archivo_costos")
    if archivo_costos and archivo_costos.filename:
        try:
            texto = archivo_costos.stream.read().decode("utf-8-sig")
            filas = list(csv.DictReader(io.StringIO(texto)))
            total_costos = db.importar_costos_directos_csv(obra_id, filas)
        except Exception as e:
            flash(f"Error al importar costos directos: {e}", "danger")
            return redirect(url_for("presupuesto_importar"))

    flash(f"Importación completa: {total_presupuesto} renglones de presupuesto, "
          f"{total_costos} costos directos.", "success")
    return redirect(url_for("presupuesto", obra=obra_id))


# ══════════════════════════════════════════════════════════════════
#  ANÁLISIS DE COMPRA (comparación de cotizaciones)
# ══════════════════════════════════════════════════════════════════

@app.route("/analisis-compra")
@login_required
@permiso_requerido("analisis_compra", "leer")
def analisis_compra():
    user = get_current_user()
    obras = db.get_obras()
    obra_filtro = request.args.get("obra", "")
    estatus_filtro = request.args.get("estatus", "")
    lista = db.get_analisis_compra(id_obra=int(obra_filtro) if obra_filtro else None,
                                    estatus=estatus_filtro or None)
    return render_template("analisis_compra.html", user=user, obras=obras, lista=lista,
                           obra_filtro=obra_filtro, estatus_filtro=estatus_filtro)


@app.route("/analisis-compra/nuevo", methods=["GET", "POST"])
@login_required
@permiso_requerido("analisis_compra", "crear")
def analisis_compra_nuevo():
    user = get_current_user()
    obras = db.get_obras()
    if request.method == "POST":
        f = request.form
        datos = {
            "id_obra": int(f["id_obra"]) if f.get("id_obra") else None,
            "descripcion": f["descripcion"].strip(),
            "requisitante": f.get("requisitante") or None,
            "fecha": f.get("fecha") or hoy_str(),
            "observaciones": f.get("observaciones") or None,
            "creado_por": session["user_id"],
        }
        aid = db.crear_analisis_compra(datos)
        flash("Análisis de compra creado. Agrega las cotizaciones a comparar.", "success")
        return redirect(url_for("analisis_compra_detalle", aid=aid))
    return render_template("analisis_compra_form.html", user=user, obras=obras)


@app.route("/analisis-compra/<int:aid>")
@login_required
@permiso_requerido("analisis_compra", "leer")
def analisis_compra_detalle(aid):
    analisis = db.get_analisis(aid)
    if not analisis:
        abort(404)
    user = get_current_user()
    cotizaciones = db.get_cotizaciones_analisis(aid)
    return render_template("analisis_compra_detalle.html", user=user, analisis=analisis,
                           cotizaciones=cotizaciones)


@app.route("/analisis-compra/<int:aid>/cotizacion/nueva", methods=["POST"])
@login_required
@permiso_requerido("analisis_compra", "crear")
def analisis_compra_cotizacion_nueva(aid):
    analisis = db.get_analisis(aid)
    if not analisis:
        abort(404)
    f = request.form
    descripciones = f.getlist("item_desc[]")
    cantidades = f.getlist("item_cant[]")
    unidades = f.getlist("item_unidad[]")
    precios = f.getlist("item_pu[]")
    items = []
    for i, desc in enumerate(descripciones):
        if not desc.strip():
            continue
        items.append({
            "descripcion": desc.strip(),
            "cantidad": float(cantidades[i]) if i < len(cantidades) and cantidades[i] else 0,
            "unidad": unidades[i] if i < len(unidades) else "",
            "precio_unitario": float(precios[i]) if i < len(precios) and precios[i] else 0,
        })
    if not f.get("proveedor", "").strip():
        flash("Indica el proveedor de la cotización.", "danger")
        return redirect(url_for("analisis_compra_detalle", aid=aid))
    db.crear_cotizacion_analisis(aid, f["proveedor"].strip(), f.get("numero_cotizacion") or None,
                                 f.get("fecha_visita") or None, f.get("observaciones") or None, items)
    flash("Cotización agregada.", "success")
    return redirect(url_for("analisis_compra_detalle", aid=aid))


@app.route("/analisis-compra/<int:aid>/cotizacion/<int:cid>/eliminar", methods=["POST"])
@login_required
@permiso_requerido("analisis_compra", "eliminar")
def analisis_compra_cotizacion_eliminar(aid, cid):
    db.eliminar_cotizacion_analisis(cid)
    flash("Cotización eliminada.", "success")
    return redirect(url_for("analisis_compra_detalle", aid=aid))


@app.route("/analisis-compra/<int:aid>/ganadora", methods=["POST"])
@login_required
@permiso_requerido("analisis_compra", "editar")
def analisis_compra_ganadora(aid):
    cid = int(request.form["id_cotizacion"])
    db.marcar_cotizacion_ganadora(aid, cid)
    flash("Cotización ganadora marcada.", "success")
    return redirect(url_for("analisis_compra_detalle", aid=aid))


@app.route("/analisis-compra/<int:aid>/generar-oc", methods=["POST"])
@login_required
@permiso_requerido("ordenes_compra", "crear")
def analisis_compra_generar_oc(aid):
    analisis = db.get_analisis(aid)
    if not analisis or not analisis["id_cotizacion_ganadora"]:
        flash("Marca primero una cotización como ganadora.", "danger")
        return redirect(url_for("analisis_compra_detalle", aid=aid))
    cot = db.get_cotizacion(analisis["id_cotizacion_ganadora"])
    numero = db.get_siguiente_numero_oc(analisis["id_obra"])
    datos = {
        "numero_pedido": numero, "folio": None, "fecha": hoy_str(),
        "tipo_pedido": "Materiales", "id_obra": analisis["id_obra"],
        "descripcion_obra": analisis["descripcion"], "proveedor": cot["proveedor"],
        "rfc_proveedor": None, "contacto_pago": None, "telefono_proveedor": None,
        "email_proveedor": None, "condiciones_pago": None, "forma_pago": None,
        "metodo_pago": None, "uso_cfdi": None, "moneda": "MXN", "tiempo_entrega": None,
        "subtotal": 0, "iva": 0, "total": 0, "flete_logistica": None, "retencion": None,
        "importe_letra": None, "responsable": "Elena de la Rocha Calderon",
        "estatus": "borrador",
        "observaciones": f"Generada desde Análisis de Compra #{aid} ({cot.get('numero_cotizacion') or 's/n'}).",
        "id_codigo_costo": None,
        "creado_por": session["user_id"],
    }
    oid = db.crear_orden_compra(datos)
    for i, it in enumerate(cot["items"]):
        importe = round(float(it["cantidad"] or 0) * float(it["precio_unitario"] or 0), 2)
        db.crear_partida_orden(oid, i + 1, it["descripcion"], it["cantidad"], it["unidad"],
                               it["precio_unitario"], importe)
    db.recalcular_totales_oc(oid)
    db.marcar_orden_generada(aid, oid)
    flash(f"Orden de Compra #{numero} generada desde el análisis de compra.", "success")
    return redirect(url_for("orden_compra_editar", oid=oid))


# ══════════════════════════════════════════════════════════════════
#  CAJA CHICA / REEMBOLSOS / VIÁTICOS  (Modelo Maestro-Detalle)
# ══════════════════════════════════════════════════════════════════

@app.route("/caja-chica")
@login_required
@permiso_requerido("caja_chica", "leer")
def caja_chica():
    user = get_current_user()
    obras = db.get_obras()
    obra_filtro = request.args.get("obra", "")
    tipo_filtro = request.args.get("tipo", "")
    estatus_filtro = request.args.get("estatus", "")
    lista = db.get_caja_chica(id_obra=int(obra_filtro) if obra_filtro else None,
                              tipo=tipo_filtro or None, estatus=estatus_filtro or None)
    kpis = db.get_kpis_caja_chica(id_obra=int(obra_filtro) if obra_filtro else None, tipo=tipo_filtro or None)
    return render_template("caja_chica.html", user=user, obras=obras, comprobaciones=lista, kpis=kpis,
                           obra_filtro=obra_filtro, tipo_filtro=tipo_filtro, estatus_filtro=estatus_filtro,
                           tipos=db.TIPOS_CAJA_CHICA)


@app.route("/caja-chica/nuevo", methods=["GET", "POST"])
@login_required
@permiso_requerido("caja_chica", "crear")
def caja_chica_nuevo():
    user = get_current_user()
    obras = db.get_obras()
    if request.method == "POST":
        f = request.form
        # Inferir datos del encabezado desde las partidas
        partidas_indices = f.get("partidas_indices", "")
        # Buscar la primera fecha de partida para calcular semana
        primera_fecha = None
        if partidas_indices:
            for idx in partidas_indices.split(","):
                idx = idx.strip()
                if idx and f.get(f"partida_fecha_{idx}"):
                    primera_fecha = f.get(f"partida_fecha_{idx}")
                    break
        # Calcular semana desde la fecha (calendario ESMA: sem 1 = 29/dic/2025)
        num_semana = None
        semana_inicio = None
        semana_fin = None
        if primera_fecha:
            from datetime import datetime as dt2
            try:
                fd = dt2.strptime(primera_fecha, "%Y-%m-%d")
                lunes_sem1 = dt2(2025, 12, 29)
                diff_days = (fd - lunes_sem1).days
                if diff_days >= 0:
                    num_semana = ((diff_days // 7) % 52) + 1
                    # Calcular el lunes de esa semana
                    dias_desde_lunes = fd.weekday()  # 0=lunes
                    inicio = fd - timedelta(days=dias_desde_lunes)
                    fin = inicio + timedelta(days=6)
                    semana_inicio = inicio.strftime("%Y-%m-%d")
                    semana_fin = fin.strftime("%Y-%m-%d")
            except Exception:
                pass
        datos = {
            "id_obra": None,
            "empresa": "ESMA",
            "tipo": "caja_chica",
            "elaboro": user.get("nombre") or None,
            "num_semana": num_semana,
            "semana_inicio": semana_inicio,
            "semana_fin": semana_fin,
            "fecha_elaboracion": hoy_str(),
            "fecha_deposito": None,
            "monto_deposito": 0,
            "observaciones": None,
            "estatus": "borrador",
            "creado_por": session["user_id"],
        }
        cid = db.crear_comprobacion_caja_chica(datos)
        # Procesar partidas dinámicas (deducibles y no deducibles)
        if partidas_indices:
            cfdi_folder = os.path.join(UPLOAD_FOLDER, "cfdi_caja_chica")
            os.makedirs(cfdi_folder, exist_ok=True)
            for idx in partidas_indices.split(","):
                idx = idx.strip()
                if not idx:
                    continue
                es_deducible = int(f.get(f"partida_tipo_{idx}", "1"))
                if es_deducible:
                    subtotal = float(f.get(f"partida_subtotal_{idx}") or 0)
                else:
                    subtotal = float(f.get(f"partida_subtotal_noded_{idx}") or 0)
                iva = float(f.get(f"partida_iva_{idx}") or 0) if es_deducible else 0
                otras = float(f.get(f"partida_otras_{idx}") or 0) if es_deducible else 0
                ish = float(f.get(f"partida_ish_{idx}") or 0) if es_deducible else 0
                ret_isr = float(f.get(f"partida_retencion_isr_{idx}") or 0) if es_deducible else 0
                ret_iva = float(f.get(f"partida_retencion_iva_{idx}") or 0) if es_deducible else 0
                if es_deducible:
                    total = subtotal + iva + otras + ish - ret_isr - ret_iva
                else:
                    total = subtotal
                # Archivo CFDI de la partida
                archivo_cfdi_nombre = None
                cfdi_key = f"partida_cfdi_{idx}"
                if cfdi_key in request.files:
                    arc = request.files[cfdi_key]
                    if arc and arc.filename:
                        ext = os.path.splitext(arc.filename)[1].lower()
                        if ext in (".pdf", ".xml"):
                            archivo_cfdi_nombre = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{cid}_{idx}_{arc.filename}"
                            arc.save(os.path.join(cfdi_folder, archivo_cfdi_nombre))
                partida_datos = {
                    "id_comprobacion": cid,
                    "es_deducible": es_deducible,
                    "fecha": f.get(f"partida_fecha_{idx}") or None,
                    "proveedor": f.get(f"partida_proveedor_{idx}") or None,
                    "concepto": f.get(f"partida_concepto_{idx}") or None,
                    "folio_fiscal": f.get(f"partida_folio_fiscal_{idx}") or None,
                    "rfc": (f.get(f"partida_rfc_{idx}") or "").strip().upper() or None,
                    "subtotal": subtotal,
                    "iva_pct": float(f.get(f"partida_iva_pct_{idx}") or 16),
                    "iva": iva,
                    "otras": otras,
                    "ish": ish,
                    "ish_pct": float(f.get(f"partida_ish_pct_{idx}") or 0),
                    "retencion_isr": ret_isr,
                    "retencion_isr_pct": float(f.get(f"partida_retencion_isr_pct_{idx}") or 0),
                    "retencion_iva": ret_iva,
                    "retencion_iva_pct": float(f.get(f"partida_retencion_iva_pct_{idx}") or 0),
                    "total": total,
                    "nota_folio": f.get(f"partida_nota_folio_{idx}") or None,
                    "archivo_cfdi": archivo_cfdi_nombre,
                    "estatus_pago": f.get(f"partida_estatus_pago_{idx}", "no_pagado"),
                }
                db.crear_partida_caja_chica(partida_datos)
        flash("Comprobación creada con sus partidas.", "success")
        return redirect(url_for("caja_chica_detalle", cid=cid))
    return render_template("caja_chica_form.html", user=user, obras=obras, tipos=db.TIPOS_CAJA_CHICA)


@app.route("/caja-chica/<int:cid>")
@login_required
@permiso_requerido("caja_chica", "leer")
def caja_chica_detalle(cid):
    comp = db.get_comprobacion_caja_chica(cid)
    if not comp:
        abort(404)
    user = get_current_user()
    partidas_ded = db.get_partidas_caja_chica(cid, solo_deducibles=True)
    partidas_noded = db.get_partidas_caja_chica(cid, solo_deducibles=False)
    resumen = db.get_resumen_caja_chica(cid)
    return render_template("caja_chica_detalle.html", user=user, comp=comp,
                           partidas_ded=partidas_ded, partidas_noded=partidas_noded,
                           resumen=resumen, tipos=db.TIPOS_CAJA_CHICA)


@app.route("/caja-chica/<int:cid>/editar", methods=["GET", "POST"])
@login_required
@permiso_requerido("caja_chica", "editar")
def caja_chica_editar(cid):
    comp = db.get_comprobacion_caja_chica(cid)
    if not comp:
        abort(404)
    user = get_current_user()
    obras = db.get_obras()
    if request.method == "POST":
        f = request.form
        datos = {
            "id_obra": int(f["id_obra"]) if f.get("id_obra") else None,
            "empresa": f.get("empresa", "ESMA"),
            "tipo": f.get("tipo", "caja_chica"),
            "elaboro": f.get("elaboro") or None,
            "num_semana": int(f["num_semana"]) if f.get("num_semana") else None,
            "semana_inicio": f.get("semana_inicio") or None,
            "semana_fin": f.get("semana_fin") or None,
            "fecha_elaboracion": f.get("fecha_elaboracion") or None,
            "fecha_deposito": f.get("fecha_deposito") or None,
            "monto_deposito": float(f.get("monto_deposito") or 0),
            "observaciones": f.get("observaciones") or None,
        }
        db.actualizar_comprobacion_caja_chica(cid, datos)
        flash("Comprobación actualizada.", "success")
        return redirect(url_for("caja_chica_detalle", cid=cid))
    return render_template("caja_chica_form.html", user=user, obras=obras,
                           tipos=db.TIPOS_CAJA_CHICA, comp=comp)


@app.route("/caja-chica/<int:cid>/partida", methods=["POST"])
@login_required
@permiso_requerido("caja_chica", "crear")
def caja_chica_partida_nueva(cid):
    f = request.form
    subtotal = float(f.get("subtotal") or 0)
    iva = float(f.get("iva") or 0)
    otras = float(f.get("otras") or 0)
    ish = float(f.get("ish") or 0)
    ret_isr = float(f.get("retencion_isr") or 0)
    ret_iva = float(f.get("retencion_iva") or 0)
    total = subtotal + iva + otras + ish - ret_isr - ret_iva
    # Manejo de archivo CFDI PDF
    archivo_cfdi_nombre = None
    if "archivo_cfdi" in request.files:
        archivo = request.files["archivo_cfdi"]
        if archivo and archivo.filename:
            ext = os.path.splitext(archivo.filename)[1].lower()
            if ext in (".pdf", ".xml"):
                cfdi_folder = os.path.join(UPLOAD_FOLDER, "cfdi_caja_chica")
                os.makedirs(cfdi_folder, exist_ok=True)
                archivo_cfdi_nombre = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{cid}_{archivo.filename}"
                archivo.save(os.path.join(cfdi_folder, archivo_cfdi_nombre))
            else:
                flash("Solo se permiten archivos PDF o XML para CFDI.", "danger")
                return redirect(url_for("caja_chica_detalle", cid=cid))
    datos = {
        "id_comprobacion": cid,
        "es_deducible": 1 if f.get("es_deducible", "1") == "1" else 0,
        "fecha": f.get("fecha") or None,
        "proveedor": f.get("proveedor") or None,
        "concepto": f.get("concepto") or None,
        "folio_fiscal": f.get("folio_fiscal") or None,
        "rfc": (f.get("rfc") or "").strip().upper() or None,
        "subtotal": subtotal,
        "iva_pct": float(f.get("iva_pct") or 16),
        "iva": iva,
        "otras": otras,
        "ish": ish,
        "ish_pct": float(f.get("ish_pct") or 0),
        "retencion_isr": ret_isr,
        "retencion_isr_pct": float(f.get("retencion_isr_pct") or 0),
        "retencion_iva": ret_iva,
        "retencion_iva_pct": float(f.get("retencion_iva_pct") or 0),
        "total": total,
        "nota_folio": f.get("nota_folio") or None,
        "archivo_cfdi": archivo_cfdi_nombre,
        "estatus_pago": f.get("estatus_pago", "no_pagado"),
    }
    db.crear_partida_caja_chica(datos)
    flash("Partida agregada.", "success")
    return redirect(url_for("caja_chica_detalle", cid=cid))


@app.route("/caja-chica/<int:cid>/partida/<int:pid>/eliminar", methods=["POST"])
@login_required
@permiso_requerido("caja_chica", "editar")
def caja_chica_partida_eliminar(cid, pid):
    # Borrar archivo CFDI del disco si existe
    partida = db.get_partida_caja_chica(pid)
    if partida and partida.get("archivo_cfdi"):
        ruta = os.path.join(UPLOAD_FOLDER, "cfdi_caja_chica", partida["archivo_cfdi"])
        if os.path.exists(ruta):
            os.remove(ruta)
    db.eliminar_partida_caja_chica(pid)
    flash("Partida eliminada.", "success")
    return redirect(url_for("caja_chica_detalle", cid=cid))


@app.route("/caja-chica/<int:cid>/partida/<int:pid>/cfdi", methods=["POST"])
@login_required
@permiso_requerido("caja_chica", "editar")
def caja_chica_partida_cfdi(cid, pid):
    """Subir o reemplazar el archivo CFDI (PDF/XML) de una partida."""
    if "archivo_cfdi" not in request.files:
        flash("No se seleccionó ningún archivo.", "danger")
        return redirect(url_for("caja_chica_detalle", cid=cid))
    archivo = request.files["archivo_cfdi"]
    if not archivo or not archivo.filename:
        flash("No se seleccionó ningún archivo.", "danger")
        return redirect(url_for("caja_chica_detalle", cid=cid))
    ext = os.path.splitext(archivo.filename)[1].lower()
    if ext not in (".pdf", ".xml"):
        flash("Solo se permiten archivos PDF o XML para CFDI.", "danger")
        return redirect(url_for("caja_chica_detalle", cid=cid))
    # Borrar archivo anterior si existe
    partida = db.get_partida_caja_chica(pid)
    if partida and partida.get("archivo_cfdi"):
        ruta_vieja = os.path.join(UPLOAD_FOLDER, "cfdi_caja_chica", partida["archivo_cfdi"])
        if os.path.exists(ruta_vieja):
            os.remove(ruta_vieja)
    cfdi_folder = os.path.join(UPLOAD_FOLDER, "cfdi_caja_chica")
    os.makedirs(cfdi_folder, exist_ok=True)
    fname = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{cid}_{pid}_{archivo.filename}"
    archivo.save(os.path.join(cfdi_folder, fname))
    db.actualizar_cfdi_partida(pid, fname)
    flash("CFDI adjuntado correctamente.", "success")
    return redirect(url_for("caja_chica_detalle", cid=cid))


@app.route("/caja-chica/<int:cid>/partida/<int:pid>/ver-cfdi")
@login_required
@permiso_requerido("caja_chica", "leer")
def caja_chica_partida_ver_cfdi(cid, pid):
    """Descargar/ver el archivo CFDI de una partida."""
    partida = db.get_partida_caja_chica(pid)
    if not partida or not partida.get("archivo_cfdi"):
        flash("No hay CFDI adjunto para esta partida.", "danger")
        return redirect(url_for("caja_chica_detalle", cid=cid))
    cfdi_folder = os.path.join(UPLOAD_FOLDER, "cfdi_caja_chica")
    ruta = os.path.join(cfdi_folder, partida["archivo_cfdi"])
    if not os.path.exists(ruta):
        flash("Archivo CFDI no encontrado en el servidor.", "danger")
        return redirect(url_for("caja_chica_detalle", cid=cid))
    return send_file(ruta, as_attachment=False, download_name=partida["archivo_cfdi"])


@app.route("/caja-chica/<int:cid>/partida/<int:pid>/estatus-pago", methods=["POST"])
@login_required
@permiso_requerido("caja_chica", "editar")
def caja_chica_partida_estatus_pago(cid, pid):
    """Cambiar el estatus de pago de una partida (pagado/no_pagado)."""
    nuevo_estatus = request.form.get("estatus_pago", "no_pagado")
    if nuevo_estatus not in ("pagado", "no_pagado"):
        nuevo_estatus = "no_pagado"
    db.actualizar_estatus_pago_partida(pid, nuevo_estatus)
    flash(f"Estatus de pago actualizado: {nuevo_estatus.replace('_', ' ').title()}.", "success")
    return redirect(url_for("caja_chica_detalle", cid=cid))


@app.route("/caja-chica/<int:cid>/enviar", methods=["POST"])
@login_required
@permiso_requerido("caja_chica", "crear")
def caja_chica_enviar(cid):
    db.enviar_comprobacion_caja_chica(cid)
    flash("Comprobación enviada a aprobación.", "success")
    return redirect(url_for("caja_chica_detalle", cid=cid))


@app.route("/caja-chica/<int:cid>/aprobar", methods=["POST"])
@login_required
@permiso_requerido("caja_chica", "editar")
@rol_minimo("supervisor")
def caja_chica_aprobar(cid):
    user = get_current_user()
    db.aprobar_comprobacion_caja_chica(cid, user["id"])
    flash("Comprobación aprobada.", "success")
    return redirect(url_for("caja_chica_detalle", cid=cid))


@app.route("/caja-chica/<int:cid>/rechazar", methods=["POST"])
@login_required
@permiso_requerido("caja_chica", "editar")
@rol_minimo("supervisor")
def caja_chica_rechazar(cid):
    user = get_current_user()
    obs = request.form.get("observaciones", "")
    db.rechazar_comprobacion_caja_chica(cid, user["id"], obs)
    flash("Comprobación rechazada.", "success")
    return redirect(url_for("caja_chica_detalle", cid=cid))


@app.route("/caja-chica/<int:cid>/exportar")
@login_required
@permiso_requerido("caja_chica", "leer")
def caja_chica_exportar(cid):
    """Exporta la comprobación en formato Excel oficial ESMA."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    import tempfile

    comp = db.get_comprobacion_caja_chica(cid)
    if not comp:
        abort(404)
    partidas_ded = db.get_partidas_caja_chica(cid, solo_deducibles=True)
    partidas_noded = db.get_partidas_caja_chica(cid, solo_deducibles=False)
    resumen = db.get_resumen_caja_chica(cid)

    tipo_lbl = {"reembolso": "REEMBOLSO DE GASTOS", "viaticos": "VIATICOS", "caja_chica": "CAJA CHICA"}
    empresa_nombre = "ESMA INSTALACIONES S.A. DE C.V." if comp["empresa"] == "ESMA" else "GREMIAL CONSTRUCCIONES, S.A. DE C.V."

    wb = Workbook()
    ws = wb.active
    ws.title = tipo_lbl.get(comp["tipo"], "CAJA CHICA")

    # Estilos
    hd_font = Font(bold=True, size=14)
    sub_font = Font(bold=True, size=11)
    tbl_hd_font = Font(bold=True, size=9, color="FFFFFF")
    tbl_hd_fill = PatternFill("solid", fgColor="1A5276")
    cell_font = Font(size=9)
    money_fmt = '#,##0.00'
    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin'))

    # Encabezado empresa
    ws.merge_cells("A1:M1")
    ws["A1"] = empresa_nombre
    ws["A1"].font = hd_font

    ws.merge_cells("A2:M2")
    ws["A2"] = "CAJA CHICA / COMPROBACIÓN DE GASTOS"
    ws["A2"].font = sub_font

    # Info general
    row = 4
    ws.cell(row, 1, "Elaboró:").font = sub_font
    ws.cell(row, 2, comp["elaboro"] or "")
    ws.cell(row, 10, "FECHA DE ELABORACIÓN")
    ws.cell(row, 12, comp["fecha_elaboracion"])
    row += 1
    ws.cell(row, 1, "Proyecto:").font = sub_font
    ws.cell(row, 2, comp["obra_nombre"] or "")
    ws.cell(row, 10, "No. DE SEMANA")
    ws.cell(row, 12, comp["num_semana"])
    row += 1
    ws.cell(row, 1, "Descripción:").font = sub_font
    ws.merge_cells(f"B{row}:H{row}")
    ws.cell(row, 2, comp.get("obra_descripcion") or "")

    # Info banco
    row += 2
    ws.cell(row, 1, "INFORMACIÓN DEL BANCO").font = sub_font
    row += 1
    ws.cell(row, 1, "FECHA DE DEPOSITO")
    ws.cell(row, 3, comp["fecha_deposito"])
    ws.cell(row, 5, "MONTO DE DEPOSITO")
    ws.cell(row, 7, float(comp["monto_deposito"] or 0))
    ws.cell(row, 7).number_format = money_fmt
    ws.cell(row, 9, "TOTAL COMPROBADO")
    ws.cell(row, 11, float(resumen["total_deducible"] or 0))
    ws.cell(row, 11).number_format = money_fmt

    # Rango semana
    row += 2
    sem_txt = ""
    if comp["semana_inicio"] and comp["semana_fin"]:
        sem_txt = f"SEMANA DEL {comp['semana_inicio']} AL {comp['semana_fin']}"
    ws.cell(row, 1, sem_txt).font = sub_font

    # Encabezados tabla deducible
    row += 2
    ws.cell(row, 1, "DEDUCIBLE").font = sub_font
    row += 1
    headers = ["#", "FECHA", "RAZÓN SOCIAL", "CONCEPTO", "FOLIO FISCAL", "RFC",
               "SUBTOTAL", "% IVA", "IVA", "OTRAS", "ISH", "RET ISR", "RET IVA", "TOTAL"]
    for ci, h in enumerate(headers, 1):
        c = ws.cell(row, ci, h)
        c.font = tbl_hd_font
        c.fill = tbl_hd_fill
        c.border = thin_border

    # Filas deducibles
    for idx, p in enumerate(partidas_ded, 1):
        row += 1
        ws.cell(row, 1, idx).font = cell_font
        ws.cell(row, 2, p["fecha"]).font = cell_font
        ws.cell(row, 3, p["proveedor"] or "").font = cell_font
        ws.cell(row, 4, p["concepto"] or "").font = cell_font
        ws.cell(row, 5, p["folio_fiscal"] or "").font = cell_font
        ws.cell(row, 6, p["rfc"] or "").font = cell_font
        ws.cell(row, 7, float(p["subtotal"] or 0)).number_format = money_fmt
        ws.cell(row, 8, f'{float(p["iva_pct"] or 0):.0f}%').font = cell_font
        ws.cell(row, 9, float(p["iva"] or 0)).number_format = money_fmt
        ws.cell(row, 10, float(p["otras"] or 0)).number_format = money_fmt
        ws.cell(row, 11, float(p["ish"] or 0)).number_format = money_fmt
        ws.cell(row, 12, float(p["retencion_isr"] or 0)).number_format = money_fmt
        ws.cell(row, 13, float(p["retencion_iva"] or 0)).number_format = money_fmt
        ws.cell(row, 14, float(p["total"] or 0)).number_format = money_fmt

    # No deducible
    if partidas_noded:
        row += 2
        ws.cell(row, 1, "NO DEDUCIBLE").font = sub_font
        row += 1
        headers_nd = ["#", "FECHA", "PROVEEDOR", "CONCEPTO", "SUBTOTAL", "NOTA/FOLIO", "TOTAL"]
        for ci, h in enumerate(headers_nd, 1):
            c = ws.cell(row, ci, h)
            c.font = tbl_hd_font
            c.fill = tbl_hd_fill
        for idx, p in enumerate(partidas_noded, 1):
            row += 1
            ws.cell(row, 1, idx)
            ws.cell(row, 2, p["fecha"])
            ws.cell(row, 3, p["proveedor"] or "")
            ws.cell(row, 4, p["concepto"] or "")
            ws.cell(row, 5, float(p["subtotal"] or 0)).number_format = money_fmt
            ws.cell(row, 6, p["nota_folio"] or "")
            ws.cell(row, 7, float(p["total"] or 0)).number_format = money_fmt

    # Resumen fiscal
    row += 3
    resumen_items = [
        ("TOTAL DEDUCIBLE", resumen["total_deducible"]),
        ("TOTAL NO DEDUCIBLE", resumen["total_no_deducible"]),
        ("BASE IVA", resumen["base_iva"]),
        ("IVA", resumen["total_iva"]),
        ("RETENCIÓN IVA", resumen["total_retencion_iva"]),
        ("RETENCIÓN ISR", resumen["total_retencion_isr"]),
        ("ISH", resumen["total_ish"]),
        ("OTRAS", resumen["total_otras"]),
    ]
    for lbl, val in resumen_items:
        ws.cell(row, 11, lbl).font = sub_font
        ws.cell(row, 13, float(val or 0)).number_format = money_fmt
        row += 1

    # Ajustar anchos
    for ci in range(1, 15):
        ws.column_dimensions[get_column_letter(ci)].width = 14

    # Guardar y enviar
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    wb.save(tmp.name)
    tmp.close()
    nombre = f"Caja_Chica_Sem{comp['num_semana'] or ''}_{comp['empresa']}_{comp['obra_nombre'] or 'general'}.xlsx"
    return send_file(tmp.name, as_attachment=True, download_name=nombre,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ══════════════════════════════════════════════════════════════════
#  IMPORTAR EXCEL CAJA CHICA (formato ESMA) — 2 pasos
#  Paso 1: Parsear Excel y mostrar partidas + pedir CFDIs
#  Paso 2: Validar CFDIs y crear comprobación
# ══════════════════════════════════════════════════════════════════

def _parsear_excel_caja_chica(archivo):
    """Parsea un Excel formato ESMA y retorna (encabezado_dict, partidas_ded, partidas_noded)."""
    import openpyxl
    wb = openpyxl.load_workbook(archivo, data_only=True)
    ws = wb.active
    elaboro = None; num_semana = None; semana_inicio = None; semana_fin = None

    for row in ws.iter_rows(min_row=1, max_row=25, values_only=False):
        for cell in row:
            val = str(cell.value or "").strip()
            if "Elaboró" in val or "Elaboro" in val:
                nc = ws.cell(row=cell.row, column=cell.column + 1)
                if nc.value: elaboro = str(nc.value).strip()
            elif "SEMANA" in val.upper() and "COMPROBAR" in val.upper():
                for c2 in row:
                    if c2.value and str(c2.value).strip().isdigit():
                        num_semana = int(str(c2.value).strip()); break

    partidas_ded = []; partidas_noded = []
    seccion = None; header_ded = None; header_noded = None

    for row_idx, row in enumerate(ws.iter_rows(min_row=1, values_only=False), 1):
        row_text = " ".join([str(c.value or "").strip().upper() for c in row])
        if "DEDUCIBLE" in row_text:
            is_no = any("NO DEDUCIBLE" in str(c.value or "").strip().upper() for c in row)
            if not is_no:
                seccion = "ded"; header_ded = row_idx; continue
        if "NO DEDUCIBLE" in row_text:
            seccion = "noded"; header_noded = row_idx; continue

        if seccion == "ded" and header_ded and row_idx > header_ded:
            col_vals = [c.value for c in row]
            non_empty = [v for v in col_vals if v and str(v).strip() and "ERROR" not in str(v) and str(v).strip() != "$   - 0"]
            if len(non_empty) < 2: continue
            fecha = None; iva_pct = 16; strings = []; numbers = []; uuid_val = None; rfc_val = None
            for ci, cell in enumerate(row):
                cv = cell.value
                if cv is None: continue
                if isinstance(cv, datetime): fecha = cv.strftime("%Y-%m-%d"); continue
                sv = str(cv).strip()
                if not sv or sv == "0" or "ERROR" in sv: continue
                if ci < 3 and "/" in sv and not fecha:
                    for fmt in ("%d/%m/%Y", "%m/%d/%Y"):
                        try: fecha = datetime.strptime(sv, fmt).strftime("%Y-%m-%d"); break
                        except ValueError: continue
                    if fecha: continue
                if len(sv) >= 30 and sv.count("-") >= 3: uuid_val = sv; continue
                if 12 <= len(sv) <= 13 and sv.isalnum(): rfc_val = sv.upper(); continue
                try:
                    cleaned = sv.replace("$","").replace(",","").replace(" ","")
                    if cleaned and cleaned != "-": numbers.append(float(cleaned)); continue
                except (ValueError, TypeError): pass
                if "%" in sv:
                    try:
                        pct = float(sv.replace("%","").strip())
                        if pct in (0,8,10,16): iva_pct = pct
                    except ValueError: pass
                    continue
                strings.append(sv)
            proveedor = strings[0] if len(strings) >= 2 else None
            concepto = strings[1] if len(strings) >= 2 else (strings[0] if strings else None)
            subtotal = iva = total = 0
            if len(numbers) >= 2: subtotal = numbers[0]; iva = numbers[1]; total = numbers[-1]
            elif len(numbers) == 1: total = numbers[0]; subtotal = total
            if total == 0 and subtotal == 0: continue
            if iva == 0 and subtotal > 0 and iva_pct > 0: iva = round(subtotal * iva_pct / 100, 2)
            if total == 0: total = subtotal + iva
            partidas_ded.append({"fecha": fecha, "proveedor": proveedor, "concepto": concepto,
                "folio_fiscal": uuid_val, "rfc": rfc_val, "subtotal": round(subtotal,2),
                "iva_pct": iva_pct, "iva": round(iva,2), "otras": 0, "ish": 0,
                "retencion_isr": 0, "retencion_iva": 0, "total": round(total,2)})

        elif seccion == "noded" and header_noded and row_idx > header_noded:
            vals = [c.value for c in row]
            non_empty = [v for v in vals if v and str(v).strip() and "ERROR" not in str(v)]
            if len(non_empty) < 2: continue
            fecha = None; strings = []; numbers = []
            for cv in vals:
                if cv is None: continue
                if isinstance(cv, datetime): fecha = cv.strftime("%Y-%m-%d"); continue
                sv = str(cv).strip()
                if not sv or "ERROR" in sv: continue
                try:
                    cleaned = sv.replace("$","").replace(",","").replace(" ","")
                    if cleaned and cleaned != "-" and cleaned != "0": numbers.append(float(cleaned)); continue
                except (ValueError, TypeError): pass
                if sv and sv != "0": strings.append(sv)
            proveedor = strings[0] if len(strings) >= 2 else None
            concepto = strings[1] if len(strings) >= 2 else (strings[0] if strings else None)
            subtotal = numbers[0] if numbers else 0
            if subtotal == 0 and not concepto: continue
            partidas_noded.append({"fecha": fecha, "proveedor": proveedor, "concepto": concepto,
                "subtotal": round(subtotal,2), "nota_folio": None})

    # Inferir semana desde primera fecha
    primera_fecha = next((p["fecha"] for p in partidas_ded + partidas_noded if p.get("fecha")), None)
    if primera_fecha and not num_semana:
        try:
            fd = datetime.strptime(primera_fecha, "%Y-%m-%d")
            diff = (fd - datetime(2025, 12, 29)).days
            if diff >= 0:
                num_semana = ((diff // 7) % 52) + 1
                ini = fd - timedelta(days=fd.weekday())
                semana_inicio = ini.strftime("%Y-%m-%d")
                semana_fin = (ini + timedelta(days=6)).strftime("%Y-%m-%d")
        except Exception: pass

    encabezado = {"elaboro": elaboro, "num_semana": num_semana,
                  "semana_inicio": semana_inicio, "semana_fin": semana_fin}
    return encabezado, partidas_ded, partidas_noded


@app.route("/caja-chica/importar", methods=["POST"])
@login_required
@permiso_requerido("caja_chica", "crear")
def caja_chica_importar():
    """Paso 1: Parsear Excel y redirigir al paso 2 para adjuntar CFDIs."""
    import json
    if "archivo" not in request.files or not request.files["archivo"].filename:
        flash("No se seleccionó ningún archivo.", "danger")
        return redirect(url_for("caja_chica"))
    archivo = request.files["archivo"]
    ext = os.path.splitext(archivo.filename)[1].lower()
    if ext not in (".xlsx", ".xls"):
        flash("Solo se permiten archivos Excel (.xlsx).", "danger")
        return redirect(url_for("caja_chica"))
    empresa = request.form.get("empresa", "ESMA")
    id_obra = request.form.get("id_obra", "")
    try:
        encabezado, partidas_ded, partidas_noded = _parsear_excel_caja_chica(archivo)
        if not partidas_ded and not partidas_noded:
            flash("No se detectaron partidas. Verifica que el Excel tenga secciones DEDUCIBLE / NO DEDUCIBLE.", "danger")
            return redirect(url_for("caja_chica"))
        # Verificar si se subieron CFDIs directamente en paso 1
        cfdi_files = request.files.getlist("archivos_cfdi")
        cfdi_files = [f for f in cfdi_files if f and f.filename]
        # Si hay deducibles y se subieron suficientes CFDIs → crear todo directo
        if partidas_ded and len(cfdi_files) >= len(partidas_ded):
            # Validar extensiones
            for arc in cfdi_files[:len(partidas_ded)]:
                ext2 = os.path.splitext(arc.filename)[1].lower()
                if ext2 not in (".pdf", ".xml"):
                    flash("Solo se permiten archivos PDF o XML como CFDI.", "danger")
                    return redirect(url_for("caja_chica"))
            # Crear comprobación directa
            datos = {"id_obra": int(id_obra) if id_obra else None, "empresa": empresa, "tipo": "caja_chica",
                     "elaboro": encabezado.get("elaboro"), "num_semana": encabezado.get("num_semana"),
                     "semana_inicio": encabezado.get("semana_inicio"), "semana_fin": encabezado.get("semana_fin"),
                     "fecha_elaboracion": hoy_str(), "fecha_deposito": None, "monto_deposito": 0,
                     "observaciones": f"Importado de: {archivo.filename}",
                     "estatus": "borrador", "creado_por": session["user_id"]}
            cid = db.crear_comprobacion_caja_chica(datos)
            cfdi_folder = os.path.join(UPLOAD_FOLDER, "cfdi_caja_chica")
            os.makedirs(cfdi_folder, exist_ok=True)
            for i, p in enumerate(partidas_ded):
                arc = cfdi_files[i]
                fname = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{cid}_{i}_{arc.filename}"
                arc.save(os.path.join(cfdi_folder, fname))
                db.crear_partida_caja_chica({"id_comprobacion": cid, "es_deducible": 1,
                    "fecha": p["fecha"], "proveedor": p["proveedor"], "concepto": p["concepto"],
                    "folio_fiscal": p["folio_fiscal"], "rfc": p["rfc"], "subtotal": p["subtotal"],
                    "iva_pct": p["iva_pct"], "iva": p["iva"], "otras": p["otras"], "ish": p["ish"],
                    "ish_pct": 0, "retencion_isr": p["retencion_isr"], "retencion_isr_pct": 0,
                    "retencion_iva": p["retencion_iva"], "retencion_iva_pct": 0, "total": p["total"],
                    "nota_folio": None, "archivo_cfdi": fname, "estatus_pago": "no_pagado"})
            for p in partidas_noded:
                db.crear_partida_caja_chica({"id_comprobacion": cid, "es_deducible": 0,
                    "fecha": p["fecha"], "proveedor": p["proveedor"], "concepto": p["concepto"],
                    "folio_fiscal": None, "rfc": None, "subtotal": p["subtotal"], "iva_pct": 0,
                    "iva": 0, "otras": 0, "ish": 0, "ish_pct": 0, "retencion_isr": 0,
                    "retencion_isr_pct": 0, "retencion_iva": 0, "retencion_iva_pct": 0,
                    "total": p["subtotal"], "nota_folio": p.get("nota_folio"),
                    "archivo_cfdi": None, "estatus_pago": "no_pagado"})
            total_p = len(partidas_ded) + len(partidas_noded)
            flash(f"Importación exitosa: {len(partidas_ded)} deducibles (con CFDI) + {len(partidas_noded)} no deducibles = {total_p} partidas.", "success")
            return redirect(url_for("caja_chica_detalle", cid=cid))
        # Si hay deducibles pero NO se subieron CFDIs suficientes → Paso 2
        if partidas_ded:
            session["caja_chica_import"] = json.dumps({
                "empresa": empresa, "id_obra": int(id_obra) if id_obra else None,
                "encabezado": encabezado, "partidas_ded": partidas_ded,
                "partidas_noded": partidas_noded, "archivo_nombre": archivo.filename,
            })
            return render_template("caja_chica_importar_cfdi.html", user=get_current_user(),
                                   partidas_ded=partidas_ded, partidas_noded=partidas_noded)
        # Solo no deducibles → crear directo
        datos = {"id_obra": int(id_obra) if id_obra else None, "empresa": empresa, "tipo": "caja_chica",
                 "elaboro": encabezado.get("elaboro"), "num_semana": encabezado.get("num_semana"),
                 "semana_inicio": encabezado.get("semana_inicio"), "semana_fin": encabezado.get("semana_fin"),
                 "fecha_elaboracion": hoy_str(), "fecha_deposito": None, "monto_deposito": 0,
                 "observaciones": f"Importado de: {archivo.filename}",
                 "estatus": "borrador", "creado_por": session["user_id"]}
        cid = db.crear_comprobacion_caja_chica(datos)
        for p in partidas_noded:
            db.crear_partida_caja_chica({"id_comprobacion": cid, "es_deducible": 0,
                "fecha": p["fecha"], "proveedor": p["proveedor"], "concepto": p["concepto"],
                "folio_fiscal": None, "rfc": None, "subtotal": p["subtotal"], "iva_pct": 0,
                "iva": 0, "otras": 0, "ish": 0, "ish_pct": 0, "retencion_isr": 0,
                "retencion_isr_pct": 0, "retencion_iva": 0, "retencion_iva_pct": 0,
                "total": p["subtotal"], "nota_folio": p.get("nota_folio"),
                "archivo_cfdi": None, "estatus_pago": "no_pagado"})
        flash(f"Importación exitosa: {len(partidas_noded)} partidas no deducibles.", "success")
        return redirect(url_for("caja_chica_detalle", cid=cid))
    except Exception as e:
        flash(f"Error al parsear el archivo: {str(e)}", "danger")
        return redirect(url_for("caja_chica"))


@app.route("/caja-chica/importar/confirmar", methods=["POST"])
@login_required
@permiso_requerido("caja_chica", "crear")
def caja_chica_importar_confirmar():
    """Paso 2: Validar CFDIs deducibles obligatorios y crear comprobación."""
    import json
    import_data = session.pop("caja_chica_import", None)
    if not import_data:
        flash("Sesión de importación expirada. Vuelve a subir el Excel.", "danger")
        return redirect(url_for("caja_chica"))
    data = json.loads(import_data)
    partidas_ded = data["partidas_ded"]
    partidas_noded = data["partidas_noded"]
    encabezado = data["encabezado"]
    empresa = data["empresa"]
    id_obra = data["id_obra"]
    archivo_nombre = data["archivo_nombre"]
    cfdi_folder = os.path.join(UPLOAD_FOLDER, "cfdi_caja_chica")
    os.makedirs(cfdi_folder, exist_ok=True)
    # Validar todos los CFDIs deducibles
    cfdi_archivos = []
    faltantes = 0
    for i in range(len(partidas_ded)):
        key = f"cfdi_ded_{i}"
        if key not in request.files or not request.files[key].filename:
            faltantes += 1
        else:
            arc = request.files[key]
            ext = os.path.splitext(arc.filename)[1].lower()
            if ext not in (".pdf", ".xml"):
                flash(f"Partida #{i+1}: solo PDF o XML.", "danger")
                session["caja_chica_import"] = json.dumps(data)
                return render_template("caja_chica_importar_cfdi.html", user=get_current_user(),
                                       partidas_ded=partidas_ded, partidas_noded=partidas_noded)
            cfdi_archivos.append(arc)
    if faltantes > 0:
        flash(f"Faltan {faltantes} CFDI(s). Cada partida deducible requiere su CFDI (PDF/XML).", "danger")
        session["caja_chica_import"] = json.dumps(data)
        return render_template("caja_chica_importar_cfdi.html", user=get_current_user(),
                               partidas_ded=partidas_ded, partidas_noded=partidas_noded)
    # Crear comprobación
    datos = {"id_obra": id_obra, "empresa": empresa, "tipo": "caja_chica",
             "elaboro": encabezado.get("elaboro"), "num_semana": encabezado.get("num_semana"),
             "semana_inicio": encabezado.get("semana_inicio"), "semana_fin": encabezado.get("semana_fin"),
             "fecha_elaboracion": hoy_str(), "fecha_deposito": None, "monto_deposito": 0,
             "observaciones": f"Importado de: {archivo_nombre}",
             "estatus": "borrador", "creado_por": session["user_id"]}
    cid = db.crear_comprobacion_caja_chica(datos)
    # Partidas deducibles con CFDI
    for i, p in enumerate(partidas_ded):
        arc = cfdi_archivos[i]
        fname = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{cid}_{i}_{arc.filename}"
        arc.save(os.path.join(cfdi_folder, fname))
        db.crear_partida_caja_chica({"id_comprobacion": cid, "es_deducible": 1,
            "fecha": p["fecha"], "proveedor": p["proveedor"], "concepto": p["concepto"],
            "folio_fiscal": p["folio_fiscal"], "rfc": p["rfc"], "subtotal": p["subtotal"],
            "iva_pct": p["iva_pct"], "iva": p["iva"], "otras": p["otras"], "ish": p["ish"],
            "ish_pct": 0, "retencion_isr": p["retencion_isr"], "retencion_isr_pct": 0,
            "retencion_iva": p["retencion_iva"], "retencion_iva_pct": 0, "total": p["total"],
            "nota_folio": None, "archivo_cfdi": fname, "estatus_pago": "no_pagado"})
    # Partidas no deducibles (CFDI opcional)
    for i, p in enumerate(partidas_noded):
        cfdi_nombre = None
        key = f"cfdi_noded_{i}"
        if key in request.files and request.files[key].filename:
            arc = request.files[key]
            ext = os.path.splitext(arc.filename)[1].lower()
            if ext in (".pdf", ".xml"):
                cfdi_nombre = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{cid}_nd{i}_{arc.filename}"
                arc.save(os.path.join(cfdi_folder, cfdi_nombre))
        db.crear_partida_caja_chica({"id_comprobacion": cid, "es_deducible": 0,
            "fecha": p["fecha"], "proveedor": p["proveedor"], "concepto": p["concepto"],
            "folio_fiscal": None, "rfc": None, "subtotal": p["subtotal"], "iva_pct": 0,
            "iva": 0, "otras": 0, "ish": 0, "ish_pct": 0, "retencion_isr": 0,
            "retencion_isr_pct": 0, "retencion_iva": 0, "retencion_iva_pct": 0,
            "total": p["subtotal"], "nota_folio": p.get("nota_folio"),
            "archivo_cfdi": cfdi_nombre, "estatus_pago": "no_pagado"})
    total_p = len(partidas_ded) + len(partidas_noded)
    flash(f"Importación exitosa: {len(partidas_ded)} deducibles (con CFDI) + {len(partidas_noded)} no deducibles = {total_p} partidas.", "success")
    return redirect(url_for("caja_chica_detalle", cid=cid))


# ══════════════════════════════════════════════════════════════════
#  SOLICITUD DE CANCELACIÓN DE CFDI
# ══════════════════════════════════════════════════════════════════

@app.route("/cancelaciones")
@login_required
@permiso_requerido("cancelaciones_cfdi", "leer")
def cancelaciones():
    user = get_current_user()
    obras = db.get_obras()
    obra_filtro = request.args.get("obra", "")
    estatus_filtro = request.args.get("estatus", "")
    empresa_filtro = request.args.get("empresa", "")
    lista = db.get_solicitudes_cancelacion(id_obra=int(obra_filtro) if obra_filtro else None,
                                           estatus=estatus_filtro or None,
                                           empresa=empresa_filtro or None)
    return render_template("cancelaciones.html", user=user, obras=obras, solicitudes=lista,
                           obra_filtro=obra_filtro, estatus_filtro=estatus_filtro,
                           empresa_filtro=empresa_filtro, empresas=db.EMPRESAS_CANCELACION)


@app.route("/cancelaciones/nueva", methods=["GET", "POST"])
@login_required
@permiso_requerido("cancelaciones_cfdi", "crear")
def cancelacion_nueva():
    user = get_current_user()
    obras = db.get_obras()
    if request.method == "POST":
        f = request.form
        datos = {
            "id_obra": int(f["id_obra"]) if f.get("id_obra") else None,
            "empresa": f.get("empresa") or "ESMA",
            "folio_fiscal": f.get("folio_fiscal") or None,
            "razon_social": f.get("razon_social") or None,
            "rfc": (f.get("rfc") or "").strip().upper() or None,
            "clave_cancelacion": f.get("clave_cancelacion") or None,
            "monto": float(f.get("monto") or 0),
            "justificacion": f.get("justificacion") or None,
            "cfdi_reemplaza": f.get("cfdi_reemplaza") or None,
            "fecha_solicitud": f.get("fecha_solicitud") or hoy_str(),
            "solicitado_por": session["user_id"],
        }
        db.crear_solicitud_cancelacion(datos)
        flash("Solicitud de cancelación registrada.", "success")
        return redirect(url_for("cancelaciones"))
    return render_template("cancelacion_form.html", user=user, obras=obras,
                           claves=db.CLAVES_CANCELACION_SAT, empresas=db.EMPRESAS_CANCELACION)


@app.route("/cancelaciones/<int:sid>/estado", methods=["POST"])
@login_required
@permiso_requerido("cancelaciones_cfdi", "editar")
def cancelacion_cambiar_estado(sid):
    nuevo = request.form.get("estatus", "pendiente")
    db.cambiar_estatus_cancelacion(sid, nuevo)
    flash("Estatus actualizado.", "success")
    return redirect(url_for("cancelaciones"))


# ══════════════════════════════════════════════════════════════════
#  CONTRATOS (importación desde Excel/CSV tipo Procore)
# ══════════════════════════════════════════════════════════════════

@app.route("/contratos")
@login_required
@permiso_requerido("contratos", "leer")
def contratos():
    user = get_current_user()
    obras = db.get_obras()
    search = request.args.get("q", "")
    tipo_filtro = request.args.get("tipo", "")
    estatus_filtro = request.args.get("estatus", "")
    obra_filtro = request.args.get("obra", "")
    lista = db.get_contratos(
        id_obra=int(obra_filtro) if obra_filtro else None,
        tipo=tipo_filtro or None,
        estatus=estatus_filtro or None,
        search=search or None
    )
    resumen = db.get_contratos_resumen(id_obra=int(obra_filtro) if obra_filtro else None)
    return render_template("contratos.html", user=user, obras=obras, contratos=lista,
                           resumen=resumen, search=search, tipo_filtro=tipo_filtro,
                           estatus_filtro=estatus_filtro, obra_filtro=obra_filtro)


@app.route("/contratos/nuevo", methods=["GET", "POST"])
@login_required
@permiso_requerido("contratos", "crear")
def contrato_nuevo():
    user = get_current_user()
    obras = db.get_obras()
    if request.method == "POST":
        f = request.form

        def _dec(v):
            try:
                return float(str(v).replace(",", "").strip()) if v else 0
            except (ValueError, TypeError):
                return 0

        datos = {
            "numero": f["numero"].strip(),
            "compania_contratista": f.get("compania_contratista") or None,
            "tipo_contrato": f.get("tipo_contrato") or None,
            "titulo": f.get("titulo") or None,
            "estatus": f.get("estatus") or "Aprobado",
            "ejecutado": f.get("ejecutado") or "No",
            "monto_original": _dec(f.get("monto_original")),
            "ordenes_cambio_aprobadas": _dec(f.get("ordenes_cambio_aprobadas")),
            "monto_revisado": _dec(f.get("monto_revisado")),
            "facturado": _dec(f.get("facturado")),
            "pagos_emitidos": _dec(f.get("pagos_emitidos")),
            "pct_pagado": _dec(f.get("pct_pagado")),
            "saldo_restante": _dec(f.get("saldo_restante")),
            "proveedor": f.get("proveedor") or None,
            "telefono_proveedor": f.get("telefono_proveedor") or None,
            "email_proveedor": f.get("email_proveedor") or None,
            "id_obra": int(f["id_obra"]) if f.get("id_obra") else None,
            "creado_por": session["user_id"],
        }
        cid = db.crear_contrato(datos)
        flash(f"Contrato '{datos['numero']}' registrado.", "success")
        return redirect(url_for("contrato_detalle", cid=cid))
    return render_template("contrato_form.html", user=user, obras=obras, c=None, accion="Nuevo")


@app.route("/contratos/<int:cid>/editar", methods=["GET", "POST"])
@login_required
@permiso_requerido("contratos", "editar")
def contrato_editar(cid):
    contrato = db.get_contrato(cid)
    if not contrato:
        abort(404)
    user = get_current_user()
    obras = db.get_obras()
    if request.method == "POST":
        f = request.form

        def _dec(v):
            try:
                return float(str(v).replace(",", "").strip()) if v else 0
            except (ValueError, TypeError):
                return 0

        datos = {
            "numero": f["numero"].strip(),
            "compania_contratista": f.get("compania_contratista") or None,
            "tipo_contrato": f.get("tipo_contrato") or None,
            "titulo": f.get("titulo") or None,
            "estatus": f.get("estatus") or "Aprobado",
            "ejecutado": f.get("ejecutado") or "No",
            "monto_original": _dec(f.get("monto_original")),
            "ordenes_cambio_aprobadas": _dec(f.get("ordenes_cambio_aprobadas")),
            "monto_revisado": _dec(f.get("monto_revisado")),
            "facturado": _dec(f.get("facturado")),
            "pagos_emitidos": _dec(f.get("pagos_emitidos")),
            "pct_pagado": _dec(f.get("pct_pagado")),
            "saldo_restante": _dec(f.get("saldo_restante")),
            "proveedor": f.get("proveedor") or None,
            "telefono_proveedor": f.get("telefono_proveedor") or None,
            "email_proveedor": f.get("email_proveedor") or None,
            "id_obra": int(f["id_obra"]) if f.get("id_obra") else None,
        }
        sets = ", ".join(f"{k}=%({k})s" for k in datos)
        datos["_id"] = cid
        db.execute(f"UPDATE contratos SET {sets} WHERE id=%(_id)s", datos)
        flash("Contrato actualizado.", "success")
        return redirect(url_for("contrato_detalle", cid=cid))
    return render_template("contrato_form.html", user=user, obras=obras, c=contrato, accion="Editar")


@app.route("/contratos/<int:cid>")
@login_required
@permiso_requerido("contratos", "leer")
def contrato_detalle(cid):
    contrato = db.get_contrato(cid)
    if not contrato:
        abort(404)
    user = get_current_user()
    return render_template("contrato_detalle.html", user=user, c=contrato)


@app.route("/contratos/importar", methods=["GET", "POST"])
@login_required
@permiso_requerido("contratos", "crear")
def contratos_importar():
    """Importa contratos desde Excel (.xlsx) o CSV con formato Procore."""
    user = get_current_user()
    obras = db.get_obras()
    if request.method == "GET":
        return render_template("contratos_importar.html", user=user, obras=obras)

    obra_id = request.form.get("id_obra")
    obra_id = int(obra_id) if obra_id else None

    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        flash("Selecciona un archivo.", "danger")
        return redirect(url_for("contratos_importar"))

    nombre = archivo.filename.lower()
    if not nombre.endswith((".xlsx", ".xls", ".csv")):
        flash("El archivo debe ser .xlsx, .xls o .csv", "danger")
        return redirect(url_for("contratos_importar"))

    try:
        if nombre.endswith(".csv"):
            import csv, io
            contenido = archivo.stream.read()
            for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
                try:
                    texto = contenido.decode(enc)
                    break
                except (UnicodeDecodeError, ValueError):
                    continue
            else:
                texto = contenido.decode("latin-1")
            filas = list(csv.DictReader(io.StringIO(texto)))
        else:
            from openpyxl import load_workbook
            import io
            wb = load_workbook(io.BytesIO(archivo.stream.read()), read_only=True, data_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            wb.close()
            if not rows or len(rows) < 2:
                flash("El archivo está vacío o solo tiene encabezados.", "warning")
                return redirect(url_for("contratos_importar"))
            headers = [str(h).strip() if h else "" for h in rows[0]]
            filas = []
            for row in rows[1:]:
                fila = {}
                for i, h in enumerate(headers):
                    if h and i < len(row):
                        fila[h] = row[i]
                if any(v for v in fila.values()):
                    filas.append(fila)

        if not filas:
            flash("El archivo no contiene datos.", "warning")
            return redirect(url_for("contratos_importar"))

        total = db.importar_contratos_excel(filas, id_obra=obra_id, creado_por=session["user_id"])
        flash(f"Importación exitosa: {total} contratos procesados.", "success")
    except Exception as e:
        flash(f"Error al importar: {e}", "danger")
        return redirect(url_for("contratos_importar"))

    return redirect(url_for("contratos"))


@app.route("/contratos/<int:cid>/eliminar", methods=["POST"])
@login_required
@permiso_requerido("contratos", "eliminar")
def contrato_eliminar(cid):
    db.execute("DELETE FROM contratos WHERE id=%s", (cid,))
    flash("Contrato eliminado.", "success")
    return redirect(url_for("contratos"))


# ══════════════════════════════════════════════════════════════════
@app.context_processor
def inject_globals():
    kpis_nav = {}
    user_perms = {}
    if "user_id" in session:
        try:
            kpis_nav = db.get_kpis()
        except Exception:
            kpis_nav = {}
        try:
            kpis_nav["alertas_planta"] = len([a for a in db.get_planta_alertas_todas()
                                               if a["nivel"] == "danger"])
        except Exception:
            kpis_nav["alertas_planta"] = 0
        try:
            rol = session.get("user_rol", "cliente")
            if rol == "admin":
                user_perms = {m: {"crear":True,"leer":True,"editar":True,"eliminar":True} for m,_ in db.MODULOS_PERMISOS}
            else:
                user_perms = db.get_permisos_rol(rol)
        except Exception:
            user_perms = {}
    def puede_editar_obra(obra_id):
        return obra_permitida(obra_id)

    def puede_crear_obra():
        return session.get("user_rol") == "admin"

    return {"ROLES_ORDEN": ROLES_ORDEN, "kpis_nav": kpis_nav, "user_perms": user_perms,
            "puede_editar_obra": puede_editar_obra, "puede_crear_obra": puede_crear_obra}

# Inicializar tabla de roles custom al arrancar
try:
    db._init_tabla_roles_custom()
except Exception as _e:
    print(f"[WARN] No se pudo inicializar roles_custom: {_e}")

# Inicializar tabla de permisos al arrancar
try:
    db.init_permisos_si_vacios()
except Exception as _e:
    print(f"[WARN] No se pudo inicializar permisos: {_e}")

# Inicializar tabla de mantenimientos al arrancar
try:
    db._init_tabla_mantenimientos()
except Exception as _e:
    print(f"[WARN] No se pudo inicializar mantenimientos: {_e}")

# Inicializar tablas de acarreo al arrancar
try:
    db._init_tabla_acarreo()
except Exception as _e:
    print(f"[WARN] No se pudo inicializar acarreo: {_e}")

# Inicializar tabla equipo_proyecto al arrancar
try:
    db._init_tabla_equipo_proyecto()
except Exception as _e:
    print(f"[WARN] No se pudo inicializar equipo_proyecto: {_e}")

# Inicializar tabla historial_obras_equipo al arrancar
try:
    db._init_tabla_historial_obras()
except Exception as _e:
    print(f"[WARN] No se pudo inicializar historial_obras: {_e}")

# Inicializar tablas de RRHH al arrancar
try:
    db._init_tabla_rrhh()
except Exception as _e:
    print(f"[WARN] No se pudo inicializar tablas RRHH: {_e}")

# Migración: campo tasa_hora_extra en empleados
try:
    db.execute_ddl("ALTER TABLE empleados ADD COLUMN tasa_hora_extra DECIMAL(10,2) DEFAULT NULL COMMENT 'Costo por hora extra' AFTER salario_semanal")
except Exception:
    pass

# Inicializar tablas de Requisiciones al arrancar
try:
    db._init_tabla_requisiciones()
except Exception as _e:
    print(f"[WARN] No se pudo inicializar tablas Requisiciones: {_e}")

# Inicializar tabla de descansos de requisiciones
try:
    db._init_tabla_descansos()
except Exception as _e:
    print(f"[WARN] No se pudo inicializar tabla descansos: {_e}")

# Migración: campos de firmas en requisiciones
try:
    db._init_columnas_firmas_requisicion()
except Exception as _e:
    print(f"[WARN] No se pudo migrar columnas firmas requisicion: {_e}")

# Inicializar tablas de Órdenes de Compra al arrancar
try:
    db._init_tabla_ordenes_compra()
except Exception as _e:
    print(f"[WARN] No se pudo inicializar tablas Órdenes de Compra: {_e}")

# Migración: usuarios.id_obra_asignada y obras.archivada
try:
    db._init_columnas_obra_asignada()
except Exception as _e:
    print(f"[WARN] No se pudo migrar columnas de obra asignada/archivada: {_e}")

# Migración: maquinas.foto
try:
    db._init_columna_foto_maquina()
except Exception as _e:
    print(f"[WARN] No se pudo migrar columna foto de maquinas: {_e}")

# Migración: reportes_combustible.tipo_combustible
try:
    db._init_columna_tipo_combustible()
except Exception as _e:
    print(f"[WARN] No se pudo migrar tipo_combustible: {_e}")

# Migración: escaneos_qr.foto_evidencia
try:
    db._init_columna_foto_escaneo()
except Exception as _e:
    print(f"[WARN] No se pudo migrar foto_evidencia escaneos: {_e}")

# Migración: campos extra en planta_remisiones
try:
    db._init_columnas_remisiones_extra()
except Exception as _e:
    print(f"[WARN] No se pudo migrar remisiones extra: {_e}")

# Inicializar tablas de Planta de Asfalto al arrancar
try:
    db._init_tabla_planta()
except Exception as _e:
    print(f"[WARN] No se pudo inicializar planta de asfalto: {_e}")

# Inicializar tabla de reportes de obra al arrancar
try:
    db._init_tabla_reportes_obra()
    db._init_tabla_permisos_reportes_obra()
except Exception as _e:
    print(f"[WARN] No se pudo inicializar reportes_obra: {_e}")

# Inicializar tabla de Proveedores al arrancar
try:
    db._init_tabla_proveedores()
except Exception as _e:
    print(f"[WARN] No se pudo inicializar proveedores: {_e}")

# Inicializar tablas de Presupuesto / Códigos de Costo al arrancar
try:
    db._init_tabla_presupuesto()
except Exception as _e:
    print(f"[WARN] No se pudo inicializar presupuesto: {_e}")

# Migración: enlace de códigos de costo en OC y Requisiciones
try:
    db._init_columna_codigo_costo()
except Exception as _e:
    print(f"[WARN] No se pudo migrar id_codigo_costo: {_e}")

# Inicializar tablas de Análisis de Compra al arrancar
try:
    db._init_tabla_analisis_compra()
except Exception as _e:
    print(f"[WARN] No se pudo inicializar analisis_compra: {_e}")

# Inicializar tabla de Caja Chica al arrancar
try:
    db._init_tabla_caja_chica()
except Exception as _e:
    print(f"[WARN] No se pudo inicializar caja_chica: {_e}")

# Inicializar tabla de Solicitudes de Cancelación CFDI al arrancar
try:
    db._init_tabla_cancelaciones_cfdi()
except Exception as _e:
    print(f"[WARN] No se pudo inicializar cancelaciones_cfdi: {_e}")

# Inicializar tabla de Contratos al arrancar
try:
    db._init_tabla_contratos()
except Exception as _e:
    print(f"[WARN] No se pudo inicializar contratos: {_e}")

if __name__ == "__main__":
    print("="*50)
    print("  GRUPO ESMA — Plataforma de Telemetría")
    print("  http://localhost:5000")
    print("="*50)
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)