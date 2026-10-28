"""
app.py — Servidor Flask principal
GRUPO ESMA — Plataforma de Telemetría
Estructura tipo Procore: Inicio · Reportes 360 (Combustible) · Documentos ·
Equipos · Obras · Mapa GPS.
"""
import os, hashlib, sys
from datetime import datetime, date, timedelta
from flask import (Flask, render_template, jsonify, request,
                   redirect, url_for, session, flash, send_file, abort)
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash
import database as db



# Cargar variables de entorno desde .env
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass  # Si no tiene python-dotenv, usa variables de entorno del sistema


# app = Flask(__name__,
#            static_folder="/var/www/html/static",
#            static_url_path="/static/fonts")

app = Flask(__name__)

@app.route('/js/<path:filename>')
def js_files(filename):
    if os.name == 'nt': 
        # Obtiene la carpeta donde está este archivo de Python y le apunta a 'js'
        base_dir = os.path.dirname(os.path.abspath(__file__))
        carpeta_js = os.path.join(base_dir, 'js')
    else:
        carpeta_js = "/var/www/html/js"
        
    return send_from_directory(carpeta_js, filename)

# ── SEGURIDAD: Secret key desde variable de entorno (no hardcodeado) ──
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "esma_2026_k9x4m2p7q8w1v3n6j5r0")

# ── SEGURIDAD: Sesiones expiran en 8 horas ──
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
app.config["SESSION_COOKIE_HTTPONLY"] = True      # JS no puede leer la cookie
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"    # Protección CSRF básica
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB

socketio = SocketIO(app, cors_allowed_origins=os.environ.get(
    "CORS_ORIGINS", "https://telemetriaesma.duckdns.org"))

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
DOCS_FOLDER = os.path.join(UPLOAD_FOLDER, "documentos")
os.makedirs(DOCS_FOLDER, exist_ok=True)

# ── Subcarpetas organizadas por módulo ──
CHAT_FOLDER = os.path.join(UPLOAD_FOLDER, "chat")
os.makedirs(CHAT_FOLDER, exist_ok=True)
EQUIPOS_FOLDER = os.path.join(UPLOAD_FOLDER, "equipos")
os.makedirs(EQUIPOS_FOLDER, exist_ok=True)
EMPLEADOS_FOLDER = os.path.join(UPLOAD_FOLDER, "empleados")
os.makedirs(EMPLEADOS_FOLDER, exist_ok=True)
ASISTENCIA_FOLDER = os.path.join(UPLOAD_FOLDER, "asistencia")
os.makedirs(ASISTENCIA_FOLDER, exist_ok=True)
CFDI_FOLDER = os.path.join(UPLOAD_FOLDER, "cfdi_caja_chica")
os.makedirs(CFDI_FOLDER, exist_ok=True)
COTIZACIONES_FOLDER = os.path.join(UPLOAD_FOLDER, "cotizaciones")
os.makedirs(COTIZACIONES_FOLDER, exist_ok=True)
PROVEEDORES_FOLDER = os.path.join(UPLOAD_FOLDER, "proveedores")
os.makedirs(PROVEEDORES_FOLDER, exist_ok=True)
FOTOS_OBRA_FOLDER = os.path.join(UPLOAD_FOLDER, "fotos_obra")
os.makedirs(FOTOS_OBRA_FOLDER, exist_ok=True)

# ══════════════════════════════════════════════════════════════════
#  UTILIDAD DE CORREO — Gmail SMTP (via subproceso)
# ══════════════════════════════════════════════════════════════════

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "AUCOTRACK Plataforma")
SMTP_FROM_EMAIL = os.environ.get("SMTP_FROM_EMAIL", SMTP_USER)

# Log de configuración SMTP al arrancar
if SMTP_USER:
    print(f"[EMAIL] SMTP configurado: {SMTP_USER} via {SMTP_HOST}:{SMTP_PORT}")
else:
    print("[EMAIL] ⚠ SMTP NO configurado — los correos no se enviarán")


def enviar_email(destinatario, asunto, cuerpo_html, cuerpo_texto=None, adjunto_path=None, adjunto_nombre=None, headers=None):
    """Envía un correo via SMTP usando un subproceso independiente
    (evita conflictos gevent/eventlet con sockets).
    headers: dict opcional con headers extra (ej: {"Reply-To": "...", "X-ESMA-CID": "5"})
    Retorna True si se lanzó el envío."""
    if not SMTP_USER or not SMTP_PASSWORD:
        print("[EMAIL] SMTP no configurado — correo no enviado")
        return False

    import subprocess, json
    payload = json.dumps({
        "host": SMTP_HOST, "port": SMTP_PORT,
        "user": SMTP_USER, "password": SMTP_PASSWORD,
        "from_name": SMTP_FROM_NAME, "from_email": SMTP_FROM_EMAIL,
        "destinatario": destinatario, "asunto": asunto,
        "cuerpo_html": cuerpo_html, "cuerpo_texto": cuerpo_texto or "",
        "adjunto_path": adjunto_path, "adjunto_nombre": adjunto_nombre,
        "headers": headers or {},
    })
    script = os.path.join(os.path.dirname(__file__), "enviar_correo.py")
    try:
        proc = subprocess.Popen(
            [sys.executable, script],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=os.path.dirname(__file__)
        )
        stdout, stderr = proc.communicate(input=payload.encode(), timeout=30)
        if proc.returncode == 0:
            print(f"[EMAIL] ✓ {stdout.decode().strip()}")
            return True
        else:
            print(f"[EMAIL] ✗ {stderr.decode().strip()}")
            return False
    except subprocess.TimeoutExpired:
        proc.kill()
        print(f"[EMAIL] ✗ Timeout enviando a {destinatario}")
        return False
    except Exception as e:
        print(f"[EMAIL] ✗ Error lanzando subproceso: {e}")
        return False

# Carpetas de búsqueda para eliminación de archivos (en orden de prioridad)
_ALL_UPLOAD_FOLDERS = None  # Se inicializa después de definir REPORTES_OBRA_FOLDER

def borrar_archivo_fisico(nombre_archivo):
    """Busca y elimina un archivo en cualquiera de las subcarpetas de uploads.
    Retorna True si se eliminó, False si no se encontró."""
    global _ALL_UPLOAD_FOLDERS
    if _ALL_UPLOAD_FOLDERS is None:
        _ALL_UPLOAD_FOLDERS = [
            DOCS_FOLDER, EQUIPOS_FOLDER, EMPLEADOS_FOLDER, CHAT_FOLDER,
            ASISTENCIA_FOLDER, CFDI_FOLDER, COTIZACIONES_FOLDER, FOTOS_OBRA_FOLDER,
            os.path.join(UPLOAD_FOLDER, "reportes_obra"), UPLOAD_FOLDER
        ]
    if not nombre_archivo:
        return False
    for folder in _ALL_UPLOAD_FOLDERS:
        ruta = os.path.join(folder, nombre_archivo)
        if os.path.exists(ruta):
            try:
                os.remove(ruta)
                return True
            except OSError:
                pass
    return False

# ══════════════════════════════════════════════════════════════════
#  RATE LIMITER — Protección contra saturación de BD
#  Limites: 300 req/min por IP (general), 30 req/min en APIs pesadas
# ══════════════════════════════════════════════════════════════════
from collections import defaultdict
import threading, time as _time

class RateLimiter:
    """Rate limiter en memoria por IP. Thread-safe."""
    def __init__(self):
        self.requests = defaultdict(list)  # ip -> [timestamps]
        self.lock = threading.Lock()
        # Limpieza automática cada 5 minutos
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()

    def is_allowed(self, ip, limit=300, window=60):
        """Verifica si la IP puede hacer una request. limit por window (segundos)."""
        now = _time.time()
        with self.lock:
            # Filtrar requests dentro de la ventana
            self.requests[ip] = [t for t in self.requests[ip] if now - t < window]
            if len(self.requests[ip]) >= limit:
                return False
            self.requests[ip].append(now)
            return True

    def _cleanup_loop(self):
        """Limpia IPs inactivas cada 5 minutos."""
        while True:
            _time.sleep(300)
            now = _time.time()
            with self.lock:
                stale = [ip for ip, times in self.requests.items() if not times or now - times[-1] > 120]
                for ip in stale:
                    del self.requests[ip]

rate_limiter = RateLimiter()


def get_client_ip():
    """Obtiene la IP real del cliente, considerando proxy inverso (Nginx)."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or ""


# ── Caché de geolocalización (evita consultar la misma IP dos veces) ──
_geo_cache = {}

def get_geo_ip(ip):
    """Consulta ip-api.com y retorna dict con pais, ciudad, region, lat, lon.
    - IPs privadas/locales se devuelven sin datos (no se consultan).
    - Resultado se cachea en memoria para no repetir llamadas.
    - Timeout de 2 s para no frenar la app si el servicio falla.
    """
    if not ip:
        return {}
    # IPs privadas / loopback — no tiene sentido geolocalizarlas
    private_prefixes = ("127.", "10.", "192.168.", "::1", "localhost")
    if any(ip.startswith(p) for p in private_prefixes) or ip.startswith("172."):
        return {}
    if ip in _geo_cache:
        return _geo_cache[ip]
    try:
        import requests as _req
        resp = _req.get(
            f"http://ip-api.com/json/{ip}",
            params={"fields": "status,country,regionName,city,lat,lon", "lang": "es"},
            timeout=2,
        )
        data = resp.json()
        if data.get("status") == "success":
            geo = {
                "geo_pais":   data.get("country"),
                "geo_ciudad": data.get("city"),
                "geo_region": data.get("regionName"),
                "geo_lat":    data.get("lat"),
                "geo_lon":    data.get("lon"),
            }
            _geo_cache[ip] = geo
            return geo
    except Exception:
        pass
    _geo_cache[ip] = {}
    return {}


@app.before_request
def check_rate_limit():
    """Aplica rate limiting antes de cada request."""
    ip = get_client_ip()
    # Rutas estáticas y uploads no cuentan
    if request.path.startswith("/static/") or request.path.startswith("/uploads/"):
        return None
    # APIs pesadas: 60 req/min
    if request.path.startswith("/api/"):
        if not rate_limiter.is_allowed(ip, limit=60, window=60):
            return jsonify({"ok": False, "msg": "Demasiadas solicitudes. Espera un momento."}), 429
    # General: 300 req/min por IP
    elif not rate_limiter.is_allowed(ip, limit=300, window=60):
        return "Demasiadas solicitudes. Por favor espera un momento.", 429
    return None


@app.before_request
def refrescar_rol_sesion():
    """Sincroniza el rol y la obra asignada del usuario en sesión con la BD en
    cada request. Así, si un admin cambia el rol de un usuario, los permisos por
    defecto de ese rol (o de admin) se aplican de inmediato SIN necesidad de que
    el usuario vuelva a iniciar sesión. Los permisos siempre se resuelven por rol
    (get_permisos_rol / bypass de admin), independientes de la obra asignada."""
    if request.path.startswith("/static/") or request.path.startswith("/uploads/"):
        return None
    if "user_id" not in session:
        return None
    try:
        u = db.get_usuario_by_id(session["user_id"])
        if not u:
            # El usuario fue eliminado: cerrar sesión.
            session.clear()
            return None
        # Si fue desactivado, cerrar sesión.
        if not u.get("activo", 1):
            session.clear()
            return None
        session["user_rol"] = u["rol"]
        session["user_obra_asignada"] = u.get("id_obra_asignada")
    except Exception:
        # Ante cualquier error de BD, no bloquear la request.
        pass
    return None

app.jinja_env.filters['rol_label'] = lambda r: db.get_roles_labels().get(r, r)

# ── Filtro de fecha legible: 2026-agosto-04 12:21:00 ──
_MESES = {1:"enero",2:"febrero",3:"marzo",4:"abril",5:"mayo",6:"junio",
           7:"julio",8:"agosto",9:"septiembre",10:"octubre",11:"noviembre",12:"diciembre"}






import re

def _formato_fecha(valor):
    """Convierte fecha/datetime a formato '04 - agosto - 2026 12:21:00'."""
    if not valor:
        return ""
    if isinstance(valor, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                valor = datetime.strptime(valor, fmt)
                break
            except ValueError:
                continue
        else:
            return valor  # No se pudo parsear, devolver tal cual
    if isinstance(valor, date) and not isinstance(valor, datetime):
        return f"{valor.day:02d} - {_MESES[valor.month]} - {valor.year}"
    if isinstance(valor, datetime):
        return f"{valor.day:02d} - {_MESES[valor.month]} - {valor.year} {valor.hour:02d}:{valor.minute:02d}:{valor.second:02d}"
    return str(valor)

app.jinja_env.filters['fecha'] = _formato_fecha


def _extract_filter(clave, diccionario, default=None):
    """Devuelve ``diccionario[clave]`` (o ``default`` si no existe).

    Diseñado para usarse dentro de cadenas de ``map()``:
        rubros | map(attribute='clave') | map('extract', totales, default=0) | sum
    El elemento actual de ``map`` se pasa como primer argumento (``clave``).
    """
    if isinstance(diccionario, dict):
        return diccionario.get(clave, default)
    return default


app.jinja_env.filters['extract'] = _extract_filter



# Auto-formatear fechas al renderizar en templates (sin tocar cada template)
_finalize_original = app.jinja_env.finalize























from datetime import datetime, date












def _auto_fecha(valor):

    # datetime
    if isinstance(valor, datetime):
        return f"{valor.day:02d} - {_MESES[valor.month]} - {valor.year} {valor.hour:02d}:{valor.minute:02d}:{valor.second:02d}"

    # date
    if isinstance(valor, date):
        return f"{valor.day:02d} - {_MESES[valor.month]} - {valor.year}"

    # IMPORTANTE:
    # NO convertir strings tipo 2026-07-24.
    # Los inputs type="date" necesitan exactamente yyyy-MM-dd.

    return valor if _finalize_original is None else (
        _finalize_original(valor) if _finalize_original else valor
    )


app.jinja_env.finalize = _auto_fecha











# ── SEGURIDAD: Hashing de contraseñas con salt (werkzeug/pbkdf2) ──
def hash_pwd(pwd):
    """Genera hash seguro con salt (pbkdf2:sha256). Compatible hacia atrás con SHA256 viejo."""
    return generate_password_hash(pwd, method="pbkdf2:sha256")

def verificar_pwd(pwd_ingresada, hash_guardado):
    """Verifica contraseña. Soporta hash viejo (sha256 plano) y nuevo (pbkdf2)."""
    if hash_guardado.startswith("pbkdf2:"):
        # Hash nuevo (seguro)
        return check_password_hash(hash_guardado, pwd_ingresada)
    else:
        # Hash viejo (sha256 sin salt) — compatibilidad temporal
        return hash_guardado == hashlib.sha256(pwd_ingresada.encode()).hexdigest()


# ── SEGURIDAD: Rate limiting en login (en memoria) ──
_login_intentos = {}  # ip -> {"count": int, "ultimo": timestamp}

def _login_rate_limit_check(ip):
    """Retorna True si la IP excedió 5 intentos en 60 segundos."""
    ahora = datetime.now().timestamp()
    info = _login_intentos.get(ip)
    if not info:
        return False
    # Limpiar si pasaron más de 60 seg
    if ahora - info["ultimo"] > 60:
        del _login_intentos[ip]
        return False
    return info["count"] >= 5

def _login_rate_limit_registro(ip):
    """Registra un intento fallido de login."""
    ahora = datetime.now().timestamp()
    info = _login_intentos.get(ip)
    if not info or (ahora - info["ultimo"] > 60):
        _login_intentos[ip] = {"count": 1, "ultimo": ahora}
    else:
        _login_intentos[ip]["count"] += 1
        _login_intentos[ip]["ultimo"] = ahora


# ── SEGURIDAD: Headers de seguridad en todas las respuestas ──
@app.after_request
def agregar_headers_seguridad(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

# ── Decoradores de acceso ─────────────────────────────────────────
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

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
#  STATIC FILES — Servir archivos estáticos desde /var/www/html/static/
# ══════════════════════════════════════════════════════════════════
@app.route("/static/<path:filename>")
def serve_static(filename):
    return send_file(os.path.join("/var/www/html/static", filename))


# ══════════════════════════════════════════════════════════════════
#  AUTH
# ══════════════════════════════════════════════════════════════════
@app.route("/login", methods=["GET","POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    error = None
    if request.method == "POST":
        # Rate limiting: max 5 intentos por minuto por IP
        ip = get_client_ip()
        if _login_rate_limit_check(ip):
            error = "Demasiados intentos. Espera 1 minuto."
            return render_template("login.html", error=error)

        email = request.form.get("email","").strip()
        pwd   = request.form.get("password","")
        user  = db.get_usuario_by_email(email)
        if user and verificar_pwd(pwd, user["password"]):
            # Si el hash es viejo (sha256), migrar a hash seguro
            if not user["password"].startswith("pbkdf2:"):
                db.execute("UPDATE usuarios SET password=%s WHERE id=%s",
                           (hash_pwd(pwd), user["id"]))
            session.permanent = True  # Usa el lifetime configurado (8h)
            session["user_id"]     = user["id"]
            session["user_nombre"] = user["nombre"]
            session["user_email"]  = user["email"]
            session["user_rol"]    = user["rol"]
            session["user_obra_asignada"] = user.get("id_obra_asignada")
            # ── Auditoría: login exitoso ──
            db.registrar_actividad(
                accion="login", ip=ip,
                id_usuario=user["id"], nombre=user["nombre"],
                email=user["email"], rol=user["rol"],
                modulo="auth", descripcion=f"Inicio de sesión exitoso",
                metodo="POST", ruta="/login",
                user_agent=request.headers.get("User-Agent","")[:300],
                **get_geo_ip(ip),
            )
            return redirect(url_for("dashboard"))
        # Login fallido
        _login_rate_limit_registro(ip)
        # ── Auditoría: login fallido ──
        db.registrar_actividad(
            accion="login_fallido", ip=ip,
            email=email,
            modulo="auth",
            descripcion=f"Intento fallido para: {email}",
            metodo="POST", ruta="/login",
            resultado="denegado",
            user_agent=request.headers.get("User-Agent","")[:300],
            **get_geo_ip(ip),
        )
        error = "Correo o contraseña incorrectos"
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    # ── Auditoría: logout ──
    if "user_id" in session:
        db.registrar_actividad(
            accion="logout",
            ip=get_client_ip(),
            id_usuario=session.get("user_id"),
            nombre=session.get("user_nombre"),
            email=session.get("user_email"),
            rol=session.get("user_rol"),
            modulo="auth",
            descripcion="Cierre de sesión",
            metodo="GET", ruta="/logout",
            user_agent=request.headers.get("User-Agent","")[:300],
            **get_geo_ip(get_client_ip()),
        )
    session.clear()
    return redirect(url_for("login"))


# ══════════════════════════════════════════════════════════════════
#  REGISTRO PÚBLICO DE PROVEEDORES (sin login)
# ══════════════════════════════════════════════════════════════════
@app.route("/registro-proveedor-gremial", methods=["GET", "POST"])
def registro_proveedor_publico():
    """Formulario público para que proveedores se registren por sí solos.
    El registro queda en estado 'pendiente' hasta que el área lo valide."""
    error = None
    if request.method == "POST":
        f = request.form
        razon_social = (f.get("razon_social") or "").strip()
        email_prov = (f.get("email") or "").strip()
        telefono = (f.get("telefono") or "").strip()

        if not razon_social:
            error = "La razón social es obligatoria."
        elif not email_prov or "@" not in email_prov:
            error = "Ingresa un correo electrónico válido."
        elif not telefono:
            error = "El teléfono es obligatorio."
        else:
            datos = {
                "razon_social": razon_social,
                "tipo_persona": f.get("tipo_persona", "moral"),
                "rfc": (f.get("rfc") or "").strip().upper() or None,
                "tipo_proveedor": f.get("tipo_proveedor") or None,
                "tipo_producto_servicio": f.get("tipo_producto_servicio") or None,
                "direccion": f.get("direccion") or None,
                "ciudad": f.get("ciudad") or None,
                "estado": f.get("estado") or None,
                "cp": f.get("cp") or None,
                "pais": "México",
                "telefono": telefono,
                "email": email_prov,
                "contacto": f.get("contacto") or None,
                "banco": f.get("banco") or None,
                "cuenta_clabe": f.get("cuenta_clabe") or None,
                "condiciones_pago_habitual": f.get("condiciones_pago_habitual") or None,
                "observaciones": f.get("observaciones") or None,
                "creado_por": None,
                "estado_registro": "pendiente",
            }
            pid = db.crear_proveedor_publico(datos)

            # Guardar documentos del checklist de alta
            DOCS_CHECKLIST = [
                "doc_1_acta_constitutiva", "doc_2_poder_notarial", "doc_3_identificacion",
                "doc_4_rfc", "doc_5_situacion_fiscal", "doc_6_comprobante_domicilio",
                "doc_7_opinion_cumplimiento", "doc_8_registro_patronal", "doc_9_repse",
                "doc_10_estado_cuenta", "doc_11_curriculum"
            ]
            EXTENSIONES_PERMITIDAS = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.csv'}
            for campo in DOCS_CHECKLIST:
                archivo = request.files.get(campo)
                if archivo and archivo.filename:
                    ext = os.path.splitext(archivo.filename)[1].lower()
                    if ext not in EXTENSIONES_PERMITIDAS:
                        continue
                    import time as _t
                    nombre_disco = f"prov_{pid}_{campo}_{int(_t.time())}{ext}"
                    archivo.save(os.path.join(PROVEEDORES_FOLDER, nombre_disco))
                    # Nombre legible del documento
                    nombre_legible = campo.replace("doc_", "").replace("_", " ").title()
                    db.guardar_documento_proveedor(pid, nombre_disco, f"{nombre_legible} - {archivo.filename}", ext, None)

            # También guardar archivos genéricos si los hay
            archivos = request.files.getlist("documentos")
            for archivo in archivos:
                if archivo and archivo.filename:
                    ext = os.path.splitext(archivo.filename)[1].lower()
                    if ext not in EXTENSIONES_PERMITIDAS:
                        continue
                    import time as _t
                    nombre_disco = f"prov_{pid}_{int(_t.time())}_{archivo.filename}"
                    archivo.save(os.path.join(PROVEEDORES_FOLDER, nombre_disco))
                    db.guardar_documento_proveedor(pid, nombre_disco, archivo.filename, ext, None)

            # Notificar al área de proveedores (usuarios admin)
            admins = db.query("SELECT email, nombre FROM usuarios WHERE rol='admin' AND activo=1 AND email IS NOT NULL")
            for admin in admins:
                asunto = f"Nuevo registro de proveedor: {razon_social}"
                cuerpo_html = f"""
                <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px">
                  <div style="background:#2E3192;color:#fff;padding:14px 20px;border-radius:8px 8px 0 0">
                    <strong>ESMA — Nuevo Proveedor Pendiente</strong>
                  </div>
                  <div style="background:#f8f9fa;border:1px solid #e0e0e0;border-top:none;padding:20px;border-radius:0 0 8px 8px">
                    <p style="margin:0 0 12px">Se ha registrado un nuevo proveedor que requiere validación:</p>
                    <table style="font-size:13px;border-collapse:collapse;width:100%">
                      <tr><td style="padding:4px 8px;color:#666;font-weight:600">Razón social:</td><td style="padding:4px 8px">{razon_social}</td></tr>
                      <tr><td style="padding:4px 8px;color:#666;font-weight:600">RFC:</td><td style="padding:4px 8px">{datos['rfc'] or '—'}</td></tr>
                      <tr><td style="padding:4px 8px;color:#666;font-weight:600">Email:</td><td style="padding:4px 8px">{email_prov}</td></tr>
                      <tr><td style="padding:4px 8px;color:#666;font-weight:600">Teléfono:</td><td style="padding:4px 8px">{telefono}</td></tr>
                      <tr><td style="padding:4px 8px;color:#666;font-weight:600">Tipo:</td><td style="padding:4px 8px">{datos['tipo_proveedor'] or '—'}</td></tr>
                    </table>
                    <div style="margin-top:16px">
                      <a href="https://telemetriaesma.duckdns.org/proveedores/{pid}"
                         style="display:inline-block;background:#2E3192;color:#fff;padding:8px 18px;border-radius:6px;text-decoration:none;font-size:13px">
                        Revisar proveedor
                      </a>
                    </div>
                  </div>
                </div>"""
                enviar_email(admin["email"], asunto, cuerpo_html,
                             cuerpo_texto=f"Nuevo proveedor pendiente: {razon_social} ({email_prov})")

            return render_template("proveedor_registro_publico.html", success=True, obras=db.get_obras())

    return render_template("proveedor_registro_publico.html", success=False, error=error, obras=db.get_obras())













@app.route("/registro-proveedor-esma", methods=["GET", "POST"])
def registro_proveedor_publico_esma():
    """Formulario público para que proveedores se registren por sí solos.
    El registro queda en estado 'pendiente' hasta que el área lo valide."""
    error = None
    if request.method == "POST":
        f = request.form
        razon_social = (f.get("razon_social") or "").strip()
        email_prov = (f.get("email") or "").strip()
        telefono = (f.get("telefono") or "").strip()

        if not razon_social:
            error = "La razón social es obligatoria."
        elif not email_prov or "@" not in email_prov:
            error = "Ingresa un correo electrónico válido."
        elif not telefono:
            error = "El teléfono es obligatorio."
        else:
            datos = {
                "razon_social": razon_social,
                "tipo_persona": f.get("tipo_persona", "moral"),
                "rfc": (f.get("rfc") or "").strip().upper() or None,
                "tipo_proveedor": f.get("tipo_proveedor") or None,
                "tipo_producto_servicio": f.get("tipo_producto_servicio") or None,
                "direccion": f.get("direccion") or None,
                "ciudad": f.get("ciudad") or None,
                "estado": f.get("estado") or None,
                "cp": f.get("cp") or None,
                "pais": "México",
                "telefono": telefono,
                "email": email_prov,
                "contacto": f.get("contacto") or None,
                "banco": f.get("banco") or None,
                "cuenta_clabe": f.get("cuenta_clabe") or None,
                "condiciones_pago_habitual": f.get("condiciones_pago_habitual") or None,
                "observaciones": f.get("observaciones") or None,
                "creado_por": None,
                "estado_registro": "pendiente",
            }
            pid = db.crear_proveedor_publico(datos)

            # Guardar documentos del checklist de alta
            DOCS_CHECKLIST = [
                "doc_1_acta_constitutiva", "doc_2_poder_notarial", "doc_3_identificacion",
                "doc_4_rfc", "doc_5_situacion_fiscal", "doc_6_comprobante_domicilio",
                "doc_7_opinion_cumplimiento", "doc_8_registro_patronal", "doc_9_repse",
                "doc_10_estado_cuenta", "doc_11_curriculum"
            ]
            EXTENSIONES_PERMITIDAS = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.csv'}
            for campo in DOCS_CHECKLIST:
                archivo = request.files.get(campo)
                if archivo and archivo.filename:
                    ext = os.path.splitext(archivo.filename)[1].lower()
                    if ext not in EXTENSIONES_PERMITIDAS:
                        continue
                    import time as _t
                    nombre_disco = f"prov_{pid}_{campo}_{int(_t.time())}{ext}"
                    archivo.save(os.path.join(PROVEEDORES_FOLDER, nombre_disco))
                    # Nombre legible del documento
                    nombre_legible = campo.replace("doc_", "").replace("_", " ").title()
                    db.guardar_documento_proveedor(pid, nombre_disco, f"{nombre_legible} - {archivo.filename}", ext, None)

            # También guardar archivos genéricos si los hay
            archivos = request.files.getlist("documentos")
            for archivo in archivos:
                if archivo and archivo.filename:
                    ext = os.path.splitext(archivo.filename)[1].lower()
                    if ext not in EXTENSIONES_PERMITIDAS:
                        continue
                    import time as _t
                    nombre_disco = f"prov_{pid}_{int(_t.time())}_{archivo.filename}"
                    archivo.save(os.path.join(PROVEEDORES_FOLDER, nombre_disco))
                    db.guardar_documento_proveedor(pid, nombre_disco, archivo.filename, ext, None)

            # Notificar al área de proveedores (usuarios admin)
            admins = db.query("SELECT email, nombre FROM usuarios WHERE rol='admin' AND activo=1 AND email IS NOT NULL")
            for admin in admins:
                asunto = f"Nuevo registro de proveedor: {razon_social}"
                cuerpo_html = f"""
                <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px">
                  <div style="background:#2E3192;color:#fff;padding:14px 20px;border-radius:8px 8px 0 0">
                    <strong>ESMA — Nuevo Proveedor Pendiente</strong>
                  </div>
                  <div style="background:#f8f9fa;border:1px solid #e0e0e0;border-top:none;padding:20px;border-radius:0 0 8px 8px">
                    <p style="margin:0 0 12px">Se ha registrado un nuevo proveedor que requiere validación:</p>
                    <table style="font-size:13px;border-collapse:collapse;width:100%">
                      <tr><td style="padding:4px 8px;color:#666;font-weight:600">Razón social:</td><td style="padding:4px 8px">{razon_social}</td></tr>
                      <tr><td style="padding:4px 8px;color:#666;font-weight:600">RFC:</td><td style="padding:4px 8px">{datos['rfc'] or '—'}</td></tr>
                      <tr><td style="padding:4px 8px;color:#666;font-weight:600">Email:</td><td style="padding:4px 8px">{email_prov}</td></tr>
                      <tr><td style="padding:4px 8px;color:#666;font-weight:600">Teléfono:</td><td style="padding:4px 8px">{telefono}</td></tr>
                      <tr><td style="padding:4px 8px;color:#666;font-weight:600">Tipo:</td><td style="padding:4px 8px">{datos['tipo_proveedor'] or '—'}</td></tr>
                    </table>
                    <div style="margin-top:16px">
                      <a href="https://telemetriaesma.duckdns.org/proveedores/{pid}"
                         style="display:inline-block;background:#2E3192;color:#fff;padding:8px 18px;border-radius:6px;text-decoration:none;font-size:13px">
                        Revisar proveedor
                      </a>
                    </div>
                  </div>
                </div>"""
                enviar_email(admin["email"], asunto, cuerpo_html,
                             cuerpo_texto=f"Nuevo proveedor pendiente: {razon_social} ({email_prov})")

            return render_template("proveedor_registro_publico_esma.html", success=True, obras=db.get_obras())

    return render_template("proveedor_registro_publico_esma.html", success=False, error=error, obras=db.get_obras())

# ══════════════════════════════════════════════════════════════════
#  REGISTRO PÚBLICO — CONTROL DE CALIDAD
# ══════════════════════════════════════════════════════════════════


@app.route("/registro-control-calidad-esma", methods=["GET", "POST"])
def registro_control_calidad_esma():
    """Página pública de Control de Calidad: cotizaciones, facturas y resultados por obra."""
    error = None
    success = False
    success_msg = None

    if request.method == "POST":
        f = request.form
        accion = f.get("accion", "")
        id_prov = f.get("id_proveedor")
        EXTENSIONES_PERMITIDAS = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.csv', '.xml'}

        if not id_prov:
            error = "Debe seleccionar un proveedor."
        else:
            pid = int(id_prov)
            prov = db.get_proveedor(pid)
            if not prov:
                error = "Proveedor no encontrado."

            elif accion == "nueva_cotizacion":
                # ─── CREAR NUEVA ORDEN DE SERVICIO CC ───
                id_obra = f.get("id_obra")
                descripcion = (f.get("descripcion_servicio") or "").strip()
                monto = f.get("monto_cotizado")
                moneda = f.get("moneda", "MXN")

                # Validar plazo de Control de Calidad
                from datetime import date as _date, datetime as _dt
                def _parse_fecha_plazo(val):
                    """Convierte un valor de BD a datetime.date o None."""
                    if val is None:
                        return None
                    if hasattr(val, 'year'):  # ya es date/datetime
                        return val if isinstance(val, _date) else val.date()
                    s = str(val).strip()[:10]
                    if not s or s == '0000-00-00' or s == 'None':
                        return None
                    try:
                        return _dt.strptime(s, "%Y-%m-%d").date()
                    except ValueError:
                        return None

                plazo_hasta = _parse_fecha_plazo(prov.get("plazo_cc_hasta"))
                plazo_desde = _parse_fecha_plazo(prov.get("plazo_cc_desde"))
                hoy = _date.today()
                if plazo_hasta and hoy > plazo_hasta:
                    desde_txt = plazo_desde.strftime("%d/%m/%Y") if plazo_desde else "N/A"
                    hasta_txt = plazo_hasta.strftime("%d/%m/%Y")
                    error = (f"⛔ Su plazo para subir soporte de Control de Calidad fue del {desde_txt} al {hasta_txt} y ya se encuentra vencido. "
                             f"Comuníquese con el área de Administración para realizar una solicitud de ampliación de plazo.")
                elif plazo_desde and hoy < plazo_desde:
                    error = f"El plazo para subir soporte de Control de Calidad inicia el {plazo_desde.strftime('%d/%m/%Y')}. Vuelva en esa fecha."
                elif not id_obra:
                    error = "Debe seleccionar una obra."
                elif not descripcion:
                    error = "La descripción del servicio es obligatoria."
                else:
                    archivos_cot = request.files.getlist("archivo_cotizacion")
                    nombres_disco = []
                    nombres_cot = []
                    import time as _t
                    for idx, archivo_cot in enumerate(archivos_cot):
                        if archivo_cot and archivo_cot.filename:
                            ext = os.path.splitext(archivo_cot.filename)[1].lower()
                            if ext in EXTENSIONES_PERMITIDAS:
                                nombre_disco = f"cc_orden_{pid}_{int(_t.time())}_{idx}{ext}"
                                archivo_cot.save(os.path.join(PROVEEDORES_FOLDER, nombre_disco))
                                nombres_disco.append(nombre_disco)
                                nombres_cot.append(archivo_cot.filename)
                    # Guardar múltiples archivos separados por | en la misma columna
                    nombre_disco = "|".join(nombres_disco) if nombres_disco else None
                    nombre_cot   = "|".join(nombres_cot)   if nombres_cot   else None

                    # Procesar archivos CFDI (PDF/XML)
                    archivos_cfdi = request.files.getlist("archivo_cfdi")
                    nombres_disco_cfdi = []
                    nombres_cfdi = []
                    EXTENSIONES_CFDI = {'.pdf', '.xml'}
                    for idx_c, archivo_c in enumerate(archivos_cfdi):
                        if archivo_c and archivo_c.filename:
                            ext_c = os.path.splitext(archivo_c.filename)[1].lower()
                            if ext_c in EXTENSIONES_CFDI:
                                nombre_disco_c = f"cc_cfdi_{pid}_{int(_t.time())}_{idx_c}{ext_c}"
                                archivo_c.save(os.path.join(PROVEEDORES_FOLDER, nombre_disco_c))
                                nombres_disco_cfdi.append(nombre_disco_c)
                                nombres_cfdi.append(archivo_c.filename)
                    nombre_disco_cfdi_str = "|".join(nombres_disco_cfdi) if nombres_disco_cfdi else None
                    nombre_cfdi_str       = "|".join(nombres_cfdi)       if nombres_cfdi       else None

                    datos_orden = {
                        "id_proveedor": pid,
                        "id_obra": int(id_obra),
                        "descripcion_servicio": descripcion,
                        "monto_cotizado": float(monto) if monto else None,
                        "moneda": moneda,
                        "archivo_cotizacion": nombre_disco,
                        "nombre_cotizacion": nombre_cot,
                        "archivo_cfdi": nombre_disco_cfdi_str,
                        "nombre_cfdi": nombre_cfdi_str,
                        "observaciones": f.get("observaciones") or None,
                        "periodo_desde": f.get("periodo_desde") or None,
                        "periodo_hasta": f.get("periodo_hasta") or None,
                    }
                    db.crear_orden_cc(datos_orden)

                    # Notificar admins
                    admins = db.query("SELECT email, nombre FROM usuarios WHERE rol='admin' AND activo=1 AND email IS NOT NULL")
                    obra = db.get_obra(int(id_obra))
                    for admin in admins:
                        asunto = f"Nueva cotización CC: {prov['razon_social']} — {obra['nombre'] if obra else ''}"
                        cuerpo_html = f"""
                    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px">
                      <div style="background:#2E3192;color:#fff;padding:14px 20px;border-radius:8px 8px 0 0">
                        <strong>ESMA — Nueva Cotización Control de Calidad</strong>
                      </div>
                      <div style="background:#f8f9fa;border:1px solid #e0e0e0;border-top:none;padding:20px;border-radius:0 0 8px 8px">
                        <p style="margin:0 0 12px">Se ha recibido una nueva cotización de Control de Calidad:</p>
                        <table style="font-size:13px;border-collapse:collapse;width:100%">
                          <tr><td style="padding:4px 8px;color:#666;font-weight:600">Proveedor:</td><td>{prov['razon_social']}</td></tr>
                          <tr><td style="padding:4px 8px;color:#666;font-weight:600">Obra:</td><td>{obra['nombre'] if obra else '—'}</td></tr>
                          <tr><td style="padding:4px 8px;color:#666;font-weight:600">Servicio:</td><td>{descripcion[:80]}</td></tr>
                          <tr><td style="padding:4px 8px;color:#666;font-weight:600">Monto:</td><td>${float(monto) if monto else 0:,.2f} {moneda}</td></tr>
                        </table>
                      </div>
                    </div>"""
                        enviar_email(admin["email"], asunto, cuerpo_html,
                                     cuerpo_texto=f"Cotización CC: {prov['razon_social']} - {obra['nombre'] if obra else ''} - ${monto}")

                    success = True
                    success_msg = f"Cotización enviada correctamente para la obra: {obra['nombre'] if obra else ''}."

            elif accion == "subir_factura":
                # ─── SUBIR FACTURA PARA ORDEN PAGADA ───
                # Validar plazo de Control de Calidad
                from datetime import date as _date, datetime as _dt
                def _parse_fecha_plazo_f(val):
                    if val is None:
                        return None
                    if hasattr(val, 'year'):
                        return val if isinstance(val, _date) else val.date()
                    s = str(val).strip()[:10]
                    if not s or s == '0000-00-00' or s == 'None':
                        return None
                    try:
                        return _dt.strptime(s, "%Y-%m-%d").date()
                    except ValueError:
                        return None

                plazo_hasta_f = _parse_fecha_plazo_f(prov.get("plazo_cc_hasta"))
                plazo_desde_f = _parse_fecha_plazo_f(prov.get("plazo_cc_desde"))
                hoy_f = _date.today()
                if plazo_hasta_f and hoy_f > plazo_hasta_f:
                    desde_txt = plazo_desde_f.strftime("%d/%m/%Y") if plazo_desde_f else "N/A"
                    hasta_txt = plazo_hasta_f.strftime("%d/%m/%Y")
                    error = (f"⛔ Su plazo para subir soporte de Control de Calidad fue del {desde_txt} al {hasta_txt} y ya se encuentra vencido. "
                             f"Comuníquese con el área de Administración para realizar una solicitud de ampliación de plazo.")
                elif plazo_desde_f and hoy_f < plazo_desde_f:
                    error = f"El plazo para subir soporte de Control de Calidad inicia el {plazo_desde_f.strftime('%d/%m/%Y')}. Vuelva en esa fecha."

                id_orden = f.get("id_orden")
                archivo_fact = request.files.get("archivo_factura")
                if not error and (not id_orden or not archivo_fact or not archivo_fact.filename):
                    error = "Debe adjuntar el archivo de factura."
                elif not error:
                    ext = os.path.splitext(archivo_fact.filename)[1].lower()
                    if ext in EXTENSIONES_PERMITIDAS:
                        import time as _t
                        nombre_disco = f"cc_factura_{pid}_{id_orden}_{int(_t.time())}{ext}"
                        archivo_fact.save(os.path.join(PROVEEDORES_FOLDER, nombre_disco))
                        db.subir_factura_orden_cc(int(id_orden), nombre_disco, archivo_fact.filename)
                        success = True
                        success_msg = "Factura subida correctamente. El servicio ha sido marcado como facturado."
                    else:
                        error = "Formato de archivo no permitido."

            elif accion == "subir_resultados":
                # ─── SUBIR RESULTADOS DE LABORATORIO ───
                # Validar plazo de Control de Calidad
                from datetime import date as _date, datetime as _dt
                def _parse_fecha_plazo_r(val):
                    if val is None:
                        return None
                    if hasattr(val, 'year'):
                        return val if isinstance(val, _date) else val.date()
                    s = str(val).strip()[:10]
                    if not s or s == '0000-00-00' or s == 'None':
                        return None
                    try:
                        return _dt.strptime(s, "%Y-%m-%d").date()
                    except ValueError:
                        return None

                plazo_hasta_r = _parse_fecha_plazo_r(prov.get("plazo_cc_hasta"))
                plazo_desde_r = _parse_fecha_plazo_r(prov.get("plazo_cc_desde"))
                hoy_r = _date.today()
                if plazo_hasta_r and hoy_r > plazo_hasta_r:
                    desde_txt = plazo_desde_r.strftime("%d/%m/%Y") if plazo_desde_r else "N/A"
                    hasta_txt = plazo_hasta_r.strftime("%d/%m/%Y")
                    error = (f"⛔ Su plazo para subir soporte de Control de Calidad fue del {desde_txt} al {hasta_txt} y ya se encuentra vencido. "
                             f"Comuníquese con el área de Administración para realizar una solicitud de ampliación de plazo.")
                elif plazo_desde_r and hoy_r < plazo_desde_r:
                    error = f"El plazo para subir soporte de Control de Calidad inicia el {plazo_desde_r.strftime('%d/%m/%Y')}. Vuelva en esa fecha."

                id_orden = f.get("id_orden")
                archivo_res = request.files.get("archivo_resultados")
                if not error and (not id_orden or not archivo_res or not archivo_res.filename):
                    error = "Debe adjuntar el archivo de resultados."
                elif not error:
                    ext = os.path.splitext(archivo_res.filename)[1].lower()
                    if ext in EXTENSIONES_PERMITIDAS:
                        import time as _t
                        nombre_disco = f"cc_resultados_{pid}_{id_orden}_{int(_t.time())}{ext}"
                        archivo_res.save(os.path.join(PROVEEDORES_FOLDER, nombre_disco))
                        db.subir_resultados_orden_cc(int(id_orden), nombre_disco, archivo_res.filename)
                        success = True
                        success_msg = "Resultados de laboratorio subidos. El servicio ha sido completado."
                    else:
                        error = "Formato de archivo no permitido."

    # ─── Preparar datos para el template ───
    proveedores_cc = db.get_proveedores_control_calidad_todos()

    # Normalizar fechas de plazo CC a strings ISO para el template
    from datetime import date as _date_type
    for _p in proveedores_cc:
        for _campo in ("plazo_cc_desde", "plazo_cc_hasta"):
            val = _p.get(_campo)
            if val is None:
                _p[_campo] = ""
            elif hasattr(val, "strftime"):
                _p[_campo] = val.strftime("%Y-%m-%d")
            else:
                _p[_campo] = str(val)[:10] if str(val) not in ("None", "0000-00-00") else ""

    # Obras por proveedor (IDs)
    obras_por_prov = {}
    for prov in proveedores_cc:
        prov_obras = db.get_obras_proveedor(prov["id"])
        obras_por_prov[str(prov["id"])] = [o["id"] for o in prov_obras]

    # Órdenes por proveedor (para historial JS)
    ordenes_por_prov = {}
    facturas_pendientes = {}
    for prov in proveedores_cc:
        ordenes = db.get_ordenes_cc_proveedor_por_obra(prov["id"])
        ordenes_por_prov[str(prov["id"])] = [
            {
                "id": o["id"],
                "obra_nombre": o["obra_nombre"],
                "descripcion_servicio": o["descripcion_servicio"],
                "monto_cotizado": float(o["monto_cotizado"]) if o["monto_cotizado"] else 0,
                "estado": o["estado"],
                "fecha_cotizacion": o["fecha_cotizacion"].strftime("%d/%m/%Y") if o.get("fecha_cotizacion") else "",
            }
            for o in ordenes
        ]
        facturas_pendientes[prov["id"]] = db.contar_facturas_pendientes_proveedor(prov["id"])

    # Obras como dict para JS
    todas_obras = db.get_obras()
    obras_json = {str(o["id"]): {"nombre": o["nombre"], "ubicacion": o.get("ubicacion") or ""} for o in todas_obras}

    from datetime import date as _fecha_hoy
    fecha_hoy_iso = _fecha_hoy.today().strftime("%Y-%m-%d")

    return render_template("control_calidad_registro_esma.html",
                           success=success, success_msg=success_msg, error=error,
                           proveedores_cc=proveedores_cc,
                           obras_por_proveedor=obras_por_prov,
                           ordenes_por_proveedor=ordenes_por_prov,
                           facturas_pendientes=facturas_pendientes,
                           obras_json=obras_json,
                           fecha_hoy_iso=fecha_hoy_iso)


























@app.route("/registro-control-calidad-gremial", methods=["GET", "POST"])
def registro_control_calidad():
    """Página pública de Control de Calidad: cotizaciones, facturas y resultados por obra."""
    error = None
    success = False
    success_msg = None

    if request.method == "POST":
        f = request.form
        accion = f.get("accion", "")
        id_prov = f.get("id_proveedor")
        EXTENSIONES_PERMITIDAS = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.csv', '.xml'}

        if not id_prov:
            error = "Debe seleccionar un proveedor."
        else:
            pid = int(id_prov)
            prov = db.get_proveedor(pid)
            if not prov:
                error = "Proveedor no encontrado."

            elif accion == "nueva_cotizacion":
                # ─── CREAR NUEVA ORDEN DE SERVICIO CC ───
                id_obra = f.get("id_obra")
                descripcion = (f.get("descripcion_servicio") or "").strip()
                monto = f.get("monto_cotizado")
                moneda = f.get("moneda", "MXN")

                # Validar plazo de Control de Calidad
                from datetime import date as _date, datetime as _dt
                def _parse_fecha_plazo(val):
                    """Convierte un valor de BD a datetime.date o None."""
                    if val is None:
                        return None
                    if hasattr(val, 'year'):  # ya es date/datetime
                        return val if isinstance(val, _date) else val.date()
                    s = str(val).strip()[:10]
                    if not s or s == '0000-00-00' or s == 'None':
                        return None
                    try:
                        return _dt.strptime(s, "%Y-%m-%d").date()
                    except ValueError:
                        return None

                plazo_hasta = _parse_fecha_plazo(prov.get("plazo_cc_hasta"))
                plazo_desde = _parse_fecha_plazo(prov.get("plazo_cc_desde"))
                hoy = _date.today()
                if plazo_hasta and hoy > plazo_hasta:
                    desde_txt = plazo_desde.strftime("%d/%m/%Y") if plazo_desde else "N/A"
                    hasta_txt = plazo_hasta.strftime("%d/%m/%Y")
                    error = (f"⛔ Su plazo para subir soporte de Control de Calidad fue del {desde_txt} al {hasta_txt} y ya se encuentra vencido. "
                             f"Comuníquese con el área de Administración para realizar una solicitud de ampliación de plazo.")
                elif plazo_desde and hoy < plazo_desde:
                    error = f"El plazo para subir soporte de Control de Calidad inicia el {plazo_desde.strftime('%d/%m/%Y')}. Vuelva en esa fecha."
                elif not id_obra:
                    error = "Debe seleccionar una obra."
                elif not descripcion:
                    error = "La descripción del servicio es obligatoria."
                else:
                    archivos_cot = request.files.getlist("archivo_cotizacion")
                    nombres_disco = []
                    nombres_cot = []
                    import time as _t
                    for idx, archivo_cot in enumerate(archivos_cot):
                        if archivo_cot and archivo_cot.filename:
                            ext = os.path.splitext(archivo_cot.filename)[1].lower()
                            if ext in EXTENSIONES_PERMITIDAS:
                                nombre_disco = f"cc_orden_{pid}_{int(_t.time())}_{idx}{ext}"
                                archivo_cot.save(os.path.join(PROVEEDORES_FOLDER, nombre_disco))
                                nombres_disco.append(nombre_disco)
                                nombres_cot.append(archivo_cot.filename)
                    # Guardar múltiples archivos separados por | en la misma columna
                    nombre_disco = "|".join(nombres_disco) if nombres_disco else None
                    nombre_cot   = "|".join(nombres_cot)   if nombres_cot   else None

                    # Procesar archivos CFDI (PDF/XML)
                    archivos_cfdi = request.files.getlist("archivo_cfdi")
                    nombres_disco_cfdi = []
                    nombres_cfdi = []
                    EXTENSIONES_CFDI = {'.pdf', '.xml'}
                    for idx_c, archivo_c in enumerate(archivos_cfdi):
                        if archivo_c and archivo_c.filename:
                            ext_c = os.path.splitext(archivo_c.filename)[1].lower()
                            if ext_c in EXTENSIONES_CFDI:
                                nombre_disco_c = f"cc_cfdi_{pid}_{int(_t.time())}_{idx_c}{ext_c}"
                                archivo_c.save(os.path.join(PROVEEDORES_FOLDER, nombre_disco_c))
                                nombres_disco_cfdi.append(nombre_disco_c)
                                nombres_cfdi.append(archivo_c.filename)
                    nombre_disco_cfdi_str = "|".join(nombres_disco_cfdi) if nombres_disco_cfdi else None
                    nombre_cfdi_str       = "|".join(nombres_cfdi)       if nombres_cfdi       else None

                    datos_orden = {
                        "id_proveedor": pid,
                        "id_obra": int(id_obra),
                        "descripcion_servicio": descripcion,
                        "monto_cotizado": float(monto) if monto else None,
                        "moneda": moneda,
                        "archivo_cotizacion": nombre_disco,
                        "nombre_cotizacion": nombre_cot,
                        "archivo_cfdi": nombre_disco_cfdi_str,
                        "nombre_cfdi": nombre_cfdi_str,
                        "observaciones": f.get("observaciones") or None,
                        "periodo_desde": f.get("periodo_desde") or None,
                        "periodo_hasta": f.get("periodo_hasta") or None,
                    }
                    db.crear_orden_cc(datos_orden)

                    # Notificar admins
                    admins = db.query("SELECT email, nombre FROM usuarios WHERE rol='admin' AND activo=1 AND email IS NOT NULL")
                    obra = db.get_obra(int(id_obra))
                    for admin in admins:
                        asunto = f"Nueva cotización CC: {prov['razon_social']} — {obra['nombre'] if obra else ''}"
                        cuerpo_html = f"""
                    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px">
                      <div style="background:#2E3192;color:#fff;padding:14px 20px;border-radius:8px 8px 0 0">
                        <strong>ESMA — Nueva Cotización Control de Calidad</strong>
                      </div>
                      <div style="background:#f8f9fa;border:1px solid #e0e0e0;border-top:none;padding:20px;border-radius:0 0 8px 8px">
                        <p style="margin:0 0 12px">Se ha recibido una nueva cotización de Control de Calidad:</p>
                        <table style="font-size:13px;border-collapse:collapse;width:100%">
                          <tr><td style="padding:4px 8px;color:#666;font-weight:600">Proveedor:</td><td>{prov['razon_social']}</td></tr>
                          <tr><td style="padding:4px 8px;color:#666;font-weight:600">Obra:</td><td>{obra['nombre'] if obra else '—'}</td></tr>
                          <tr><td style="padding:4px 8px;color:#666;font-weight:600">Servicio:</td><td>{descripcion[:80]}</td></tr>
                          <tr><td style="padding:4px 8px;color:#666;font-weight:600">Monto:</td><td>${float(monto) if monto else 0:,.2f} {moneda}</td></tr>
                        </table>
                      </div>
                    </div>"""
                        enviar_email(admin["email"], asunto, cuerpo_html,
                                     cuerpo_texto=f"Cotización CC: {prov['razon_social']} - {obra['nombre'] if obra else ''} - ${monto}")

                    success = True
                    success_msg = f"Cotización enviada correctamente para la obra: {obra['nombre'] if obra else ''}."

            elif accion == "subir_factura":
                # ─── SUBIR FACTURA PARA ORDEN PAGADA ───
                # Validar plazo de Control de Calidad
                from datetime import date as _date, datetime as _dt
                def _parse_fecha_plazo_f(val):
                    if val is None:
                        return None
                    if hasattr(val, 'year'):
                        return val if isinstance(val, _date) else val.date()
                    s = str(val).strip()[:10]
                    if not s or s == '0000-00-00' or s == 'None':
                        return None
                    try:
                        return _dt.strptime(s, "%Y-%m-%d").date()
                    except ValueError:
                        return None

                plazo_hasta_f = _parse_fecha_plazo_f(prov.get("plazo_cc_hasta"))
                plazo_desde_f = _parse_fecha_plazo_f(prov.get("plazo_cc_desde"))
                hoy_f = _date.today()
                if plazo_hasta_f and hoy_f > plazo_hasta_f:
                    desde_txt = plazo_desde_f.strftime("%d/%m/%Y") if plazo_desde_f else "N/A"
                    hasta_txt = plazo_hasta_f.strftime("%d/%m/%Y")
                    error = (f"⛔ Su plazo para subir soporte de Control de Calidad fue del {desde_txt} al {hasta_txt} y ya se encuentra vencido. "
                             f"Comuníquese con el área de Administración para realizar una solicitud de ampliación de plazo.")
                elif plazo_desde_f and hoy_f < plazo_desde_f:
                    error = f"El plazo para subir soporte de Control de Calidad inicia el {plazo_desde_f.strftime('%d/%m/%Y')}. Vuelva en esa fecha."

                id_orden = f.get("id_orden")
                archivo_fact = request.files.get("archivo_factura")
                if not error and (not id_orden or not archivo_fact or not archivo_fact.filename):
                    error = "Debe adjuntar el archivo de factura."
                elif not error:
                    ext = os.path.splitext(archivo_fact.filename)[1].lower()
                    if ext in EXTENSIONES_PERMITIDAS:
                        import time as _t
                        nombre_disco = f"cc_factura_{pid}_{id_orden}_{int(_t.time())}{ext}"
                        archivo_fact.save(os.path.join(PROVEEDORES_FOLDER, nombre_disco))
                        db.subir_factura_orden_cc(int(id_orden), nombre_disco, archivo_fact.filename)
                        success = True
                        success_msg = "Factura subida correctamente. El servicio ha sido marcado como facturado."
                    else:
                        error = "Formato de archivo no permitido."

            elif accion == "subir_resultados":
                # ─── SUBIR RESULTADOS DE LABORATORIO ───
                # Validar plazo de Control de Calidad
                from datetime import date as _date, datetime as _dt
                def _parse_fecha_plazo_r(val):
                    if val is None:
                        return None
                    if hasattr(val, 'year'):
                        return val if isinstance(val, _date) else val.date()
                    s = str(val).strip()[:10]
                    if not s or s == '0000-00-00' or s == 'None':
                        return None
                    try:
                        return _dt.strptime(s, "%Y-%m-%d").date()
                    except ValueError:
                        return None

                plazo_hasta_r = _parse_fecha_plazo_r(prov.get("plazo_cc_hasta"))
                plazo_desde_r = _parse_fecha_plazo_r(prov.get("plazo_cc_desde"))
                hoy_r = _date.today()
                if plazo_hasta_r and hoy_r > plazo_hasta_r:
                    desde_txt = plazo_desde_r.strftime("%d/%m/%Y") if plazo_desde_r else "N/A"
                    hasta_txt = plazo_hasta_r.strftime("%d/%m/%Y")
                    error = (f"⛔ Su plazo para subir soporte de Control de Calidad fue del {desde_txt} al {hasta_txt} y ya se encuentra vencido. "
                             f"Comuníquese con el área de Administración para realizar una solicitud de ampliación de plazo.")
                elif plazo_desde_r and hoy_r < plazo_desde_r:
                    error = f"El plazo para subir soporte de Control de Calidad inicia el {plazo_desde_r.strftime('%d/%m/%Y')}. Vuelva en esa fecha."

                id_orden = f.get("id_orden")
                archivo_res = request.files.get("archivo_resultados")
                if not error and (not id_orden or not archivo_res or not archivo_res.filename):
                    error = "Debe adjuntar el archivo de resultados."
                elif not error:
                    ext = os.path.splitext(archivo_res.filename)[1].lower()
                    if ext in EXTENSIONES_PERMITIDAS:
                        import time as _t
                        nombre_disco = f"cc_resultados_{pid}_{id_orden}_{int(_t.time())}{ext}"
                        archivo_res.save(os.path.join(PROVEEDORES_FOLDER, nombre_disco))
                        db.subir_resultados_orden_cc(int(id_orden), nombre_disco, archivo_res.filename)
                        success = True
                        success_msg = "Resultados de laboratorio subidos. El servicio ha sido completado."
                    else:
                        error = "Formato de archivo no permitido."

    # ─── Preparar datos para el template ───
    proveedores_cc = db.get_proveedores_control_calidad_todos()

    # Normalizar fechas de plazo CC a strings ISO para el template
    from datetime import date as _date_type
    for _p in proveedores_cc:
        for _campo in ("plazo_cc_desde", "plazo_cc_hasta"):
            val = _p.get(_campo)
            if val is None:
                _p[_campo] = ""
            elif hasattr(val, "strftime"):
                _p[_campo] = val.strftime("%Y-%m-%d")
            else:
                _p[_campo] = str(val)[:10] if str(val) not in ("None", "0000-00-00") else ""

    # Obras por proveedor (IDs)
    obras_por_prov = {}
    for prov in proveedores_cc:
        prov_obras = db.get_obras_proveedor(prov["id"])
        obras_por_prov[str(prov["id"])] = [o["id"] for o in prov_obras]

    # Órdenes por proveedor (para historial JS)
    ordenes_por_prov = {}
    facturas_pendientes = {}
    for prov in proveedores_cc:
        ordenes = db.get_ordenes_cc_proveedor_por_obra(prov["id"])
        ordenes_por_prov[str(prov["id"])] = [
            {
                "id": o["id"],
                "obra_nombre": o["obra_nombre"],
                "descripcion_servicio": o["descripcion_servicio"],
                "monto_cotizado": float(o["monto_cotizado"]) if o["monto_cotizado"] else 0,
                "estado": o["estado"],
                "fecha_cotizacion": o["fecha_cotizacion"].strftime("%d/%m/%Y") if o.get("fecha_cotizacion") else "",
            }
            for o in ordenes
        ]
        facturas_pendientes[prov["id"]] = db.contar_facturas_pendientes_proveedor(prov["id"])

    # Obras como dict para JS
    todas_obras = db.get_obras()
    obras_json = {str(o["id"]): {"nombre": o["nombre"], "ubicacion": o.get("ubicacion") or ""} for o in todas_obras}

    from datetime import date as _fecha_hoy
    fecha_hoy_iso = _fecha_hoy.today().strftime("%Y-%m-%d")

    return render_template("control_calidad_registro.html",
                           success=success, success_msg=success_msg, error=error,
                           proveedores_cc=proveedores_cc,
                           obras_por_proveedor=obras_por_prov,
                           ordenes_por_proveedor=ordenes_por_prov,
                           facturas_pendientes=facturas_pendientes,
                           obras_json=obras_json,
                           fecha_hoy_iso=fecha_hoy_iso)


# ══════════════════════════════════════════════════════════════════
#  CONTROL DE CALIDAD — VISTA INTERNA (órdenes de servicio)
# ══════════════════════════════════════════════════════════════════

@app.route("/control-calidad/ordenes")
@login_required
@permiso_requerido("proveedores", "leer")
def control_calidad_ordenes():
    """Vista interna: lista de órdenes de servicio de Control de Calidad."""
    user = get_current_user()
    filtro_estado = request.args.get("estado", "")
    filtro_obra = request.args.get("obra", "")
    search = request.args.get("q", "")

    # Obtener órdenes con filtros
    ordenes = db.get_ordenes_cc(
        id_obra=int(filtro_obra) if filtro_obra else None,
        estado=filtro_estado or None
    )

    # Filtrar por búsqueda de proveedor
    if search:
        sl = search.lower()
        ordenes = [o for o in ordenes if sl in (o.get("proveedor_nombre") or "").lower()
                   or sl in (o.get("proveedor_rfc") or "").lower()]

    # KPIs
    todas = db.get_ordenes_cc()
    kpis = {
        "total": len(todas),
        "cotizadas": sum(1 for o in todas if o["estado"] == "cotizado"),
        "autorizadas": sum(1 for o in todas if o["estado"] == "autorizado"),
        "pagadas_sin_factura": sum(1 for o in todas if o["estado"] == "pagado"),
        "completas": sum(1 for o in todas if o["estado"] == "completo"),
    }

    obras = db.get_obras()
    return render_template("control_calidad_ordenes.html", user=user, ordenes=ordenes,
                           kpis=kpis, obras=obras, filtro_estado=filtro_estado,
                           filtro_obra=filtro_obra, search=search)


@app.route("/control-calidad/ordenes/<int:orden_id>/autorizar", methods=["POST"])
@login_required
@permiso_requerido("proveedores", "editar")
def cc_orden_autorizar(orden_id):
    """Autoriza una orden de servicio CC (cotizado → autorizado) con monto."""
    monto = request.form.get("monto_autorizado")
    monto_float = float(monto) if monto else None
    db.autorizar_orden_cc(orden_id, session["user_id"], monto_float)
    flash("Orden autorizada.", "success")
    return redirect(url_for("control_calidad_ordenes"))


@app.route("/control-calidad/ordenes/<int:orden_id>/rechazar", methods=["POST"])
@login_required
@permiso_requerido("proveedores", "editar")
def cc_orden_rechazar(orden_id):
    """Rechaza una orden de servicio CC."""
    db.rechazar_orden_cc(orden_id, session["user_id"])
    flash("Orden rechazada.", "success")
    return redirect(url_for("control_calidad_ordenes"))


@app.route("/control-calidad/ordenes/<int:orden_id>/revertir", methods=["POST"])
@login_required
@permiso_requerido("proveedores", "editar")
def cc_orden_revertir(orden_id):
    """Revierte una orden autorizada o rechazada de vuelta a cotizado."""
    db.revertir_orden_cc(orden_id)
    flash("Orden revertida a estado 'cotizado'.", "success")
    return redirect(url_for("control_calidad_ordenes"))


@app.route("/control-calidad/ordenes/<int:orden_id>/pagar", methods=["POST"])
@login_required
@permiso_requerido("proveedores", "editar")
def cc_orden_pagar(orden_id):
    """Marca una orden como pagada (autorizado → pagado). El proveedor deberá subir factura."""
    db.pagar_orden_cc(orden_id, session["user_id"])
    flash("Orden marcada como pagada. El proveedor debe subir la factura.", "success")
    return redirect(url_for("control_calidad_ordenes"))


@app.route("/control-calidad/ordenes/<int:orden_id>/archivo/<tipo>")
@login_required
@permiso_requerido("proveedores", "leer")
def cc_orden_archivo(orden_id, tipo):
    """Descarga/visualiza el primer archivo de una orden CC (cotizacion, factura, resultados)."""
    return cc_orden_archivo_idx(orden_id, tipo, 0)


@app.route("/control-calidad/ordenes/<int:orden_id>/archivo/<tipo>/<int:idx>")
@login_required
@permiso_requerido("proveedores", "leer")
def cc_orden_archivo_idx(orden_id, tipo, idx):
    """Descarga/visualiza el archivo #idx de una orden CC (soporta múltiples separados por |)."""
    orden = db.get_orden_cc(orden_id)
    if not orden:
        abort(404)
    campo_archivo = f"archivo_{tipo}"
    campo_nombre  = f"nombre_{tipo}"
    if tipo not in ("cotizacion", "factura", "resultados", "cfdi") or not orden.get(campo_archivo):
        abort(404)
    # Soporte para múltiples archivos separados por |
    archivos = orden[campo_archivo].split("|")
    nombres  = (orden.get(campo_nombre) or "").split("|")
    if idx >= len(archivos) or not archivos[idx]:
        abort(404)
    nombre_disco = archivos[idx].strip()
    nombre_descarga = nombres[idx].strip() if idx < len(nombres) and nombres[idx].strip() else nombre_disco
    ruta = os.path.join(PROVEEDORES_FOLDER, nombre_disco)
    if not os.path.exists(ruta):
        abort(404)
    return send_file(ruta, as_attachment=False, download_name=nombre_descarga)


# ══════════════════════════════════════════════════════════════════
#  ACTUALIZACIÓN PÚBLICA — PROVEEDORES CONTROL DE CALIDAD
# ══════════════════════════════════════════════════════════════════

@app.route("/actualizacion-control-calidad", methods=["GET", "POST"])
def actualizacion_control_calidad():
    """Formulario público para que proveedores de CC actualicen su documentación."""
    error = None
    selected_id = None

    # Obtener proveedores CC y obras
    proveedores_cc = db.get_proveedores_control_calidad()
    obras = db.get_obras()

    # Construir dict de obras por proveedor (para JS)
    obras_por_proveedor = {}
    for prov in proveedores_cc:
        prov_obras = db.get_obras_proveedor(prov["id"])
        obras_por_proveedor[str(prov["id"])] = [o["id"] for o in prov_obras]

    if request.method == "POST":
        f = request.form
        id_proveedor = f.get("id_proveedor")
        selected_id = int(id_proveedor) if id_proveedor else None

        if not id_proveedor:
            error = "Debe seleccionar un proveedor."
        else:
            pid = int(id_proveedor)
            prov = db.get_proveedor(pid)
            if not prov:
                error = "Proveedor no encontrado."
            else:
                # Actualizar datos del proveedor
                datos = {
                    "razon_social": prov["razon_social"],  # No se cambia
                    "tipo_persona": f.get("tipo_persona", prov["tipo_persona"]),
                    "rfc": (f.get("rfc") or "").strip().upper() or prov["rfc"],
                    "tipo_proveedor": "Control de Calidad",
                    "tipo_producto_servicio": f.get("actividad_comercial") or prov["tipo_producto_servicio"],
                    "direccion": f.get("direccion") or prov["direccion"],
                    "ciudad": f.get("ciudad") or prov["ciudad"],
                    "estado": f.get("estado") or prov["estado"],
                    "cp": f.get("cp") or prov["cp"],
                    "pais": "México",
                    "telefono": f.get("telefono") or prov["telefono"],
                    "email": f.get("email") or prov["email"],
                    "contacto": f.get("contacto") or prov["contacto"],
                    "banco": f.get("banco") or prov["banco"],
                    "cuenta_clabe": f.get("cuenta_clabe") or prov["cuenta_clabe"],
                    "condiciones_pago_habitual": prov["condiciones_pago_habitual"],
                    "observaciones": prov["observaciones"],
                }
                db.actualizar_proveedor(pid, datos)

                # Actualizar obras asignadas
                obras_seleccionadas = request.form.getlist("obras_asignadas")
                if obras_seleccionadas:
                    db.asignar_obras_proveedor(pid, obras_seleccionadas)

                # Guardar documentos del checklist
                DOCS_CHECKLIST = [
                    "doc_1_acta_constitutiva", "doc_2_poder_notarial", "doc_3_identificacion",
                    "doc_4_rfc", "doc_5_situacion_fiscal", "doc_6_comprobante_domicilio",
                    "doc_7_opinion_cumplimiento", "doc_8_registro_patronal", "doc_9_repse",
                    "doc_10_estado_cuenta", "doc_11_curriculum", "doc_12_ininme_factura"
                ]
                EXTENSIONES_PERMITIDAS = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.csv', '.xml'}
                for campo in DOCS_CHECKLIST:
                    archivo = request.files.get(campo)
                    if archivo and archivo.filename:
                        ext = os.path.splitext(archivo.filename)[1].lower()
                        if ext not in EXTENSIONES_PERMITIDAS:
                            continue
                        import time as _t
                        nombre_disco = f"cc_upd_{pid}_{campo}_{int(_t.time())}{ext}"
                        archivo.save(os.path.join(PROVEEDORES_FOLDER, nombre_disco))
                        nombre_legible = campo.replace("doc_", "").replace("_", " ").title()
                        db.guardar_documento_proveedor(pid, nombre_disco, f"Actualización - {nombre_legible} - {archivo.filename}", ext, None)

                # Guardar cotización si se adjuntó
                cotizacion = request.files.get("cotizacion")
                if cotizacion and cotizacion.filename:
                    ext = os.path.splitext(cotizacion.filename)[1].lower()
                    if ext in EXTENSIONES_PERMITIDAS:
                        import time as _t
                        nombre_disco = f"cc_upd_{pid}_cotizacion_{int(_t.time())}{ext}"
                        cotizacion.save(os.path.join(PROVEEDORES_FOLDER, nombre_disco))
                        desc_cot = f.get("descripcion_cotizacion") or ""
                        nombre_leg = f"Actualización Cotización - {cotizacion.filename}"
                        if desc_cot:
                            nombre_leg += f" ({desc_cot[:60]})"
                        db.guardar_documento_proveedor(pid, nombre_disco, nombre_leg, ext, None)

                # Notificar al área
                admins = db.query("SELECT email, nombre FROM usuarios WHERE rol='admin' AND activo=1 AND email IS NOT NULL")
                for admin in admins:
                    asunto = f"Actualización Control de Calidad: {prov['razon_social']}"
                    cuerpo_html = f"""
                <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px">
                  <div style="background:#2E3192;color:#fff;padding:14px 20px;border-radius:8px 8px 0 0">
                    <strong>ESMA — Actualización Proveedor Control de Calidad</strong>
                  </div>
                  <div style="background:#f8f9fa;border:1px solid #e0e0e0;border-top:none;padding:20px;border-radius:0 0 8px 8px">
                    <p style="margin:0 0 12px">El proveedor <strong>{prov['razon_social']}</strong> ha actualizado su documentación de Control de Calidad.</p>
                    <div style="margin-top:16px">
                      <a href="https://telemetriaesma.duckdns.org/proveedores/{pid}"
                         style="display:inline-block;background:#2E3192;color:#fff;padding:8px 18px;border-radius:6px;text-decoration:none;font-size:13px">
                        Ver proveedor
                      </a>
                    </div>
                  </div>
                </div>"""
                    enviar_email(admin["email"], asunto, cuerpo_html,
                                 cuerpo_texto=f"Actualización CC: {prov['razon_social']}")

                return render_template("control_calidad_actualizacion.html", success=True,
                                       proveedores_cc=proveedores_cc, obras=obras,
                                       obras_por_proveedor=obras_por_proveedor, selected_id=None)

    return render_template("control_calidad_actualizacion.html", success=False, error=error,
                           proveedores_cc=proveedores_cc, obras=obras,
                           obras_por_proveedor=obras_por_proveedor, selected_id=selected_id)


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

    # Filtros de fecha y obra
    fi = request.args.get("fecha_ini", "")
    ff = request.args.get("fecha_fin", "")
    obra_filtro = request.args.get("obra", "")

    kpis = db.get_kpis() if ver_dashboard_completo else {}
    try:
        alertas_planta = db.get_planta_alertas_todas()[:8] if ver_dashboard_completo else []
    except Exception:
        alertas_planta = []
    # Filtrar alertas por obra si se seleccionó
    if obra_filtro and alertas_planta:
        alertas_planta = [a for a in alertas_planta if str(a.get("id_obra")) == obra_filtro or obra_filtro in (a.get("obra") or "")]
    obras_dash = db.get_obras() if ver_dashboard_completo else []
    return render_template("dashboard.html", kpis=kpis, user=user,
                           alertas_planta=alertas_planta,
                           ver_dashboard_completo=ver_dashboard_completo,
                           obras_dash=obras_dash,
                           fi=fi, ff=ff, obra_filtro=obra_filtro)

# ══════════════════════════════════════════════════════════════════
#  REPORTES 360 · COMBUSTIBLE  (núcleo de auditoría)
# ══════════════════════════════════════════════════════════════════
@app.route("/combustible")
@login_required
@permiso_requerido("combustible", "leer")
def combustible():

    fi = request.args.get("fecha_ini") or hace(30)
    ff = request.args.get("fecha_fin") or hoy_str()

    sem = request.args.get("semaforo", "")
    obr = request.args.get("obra", "")
    eco = request.args.get("eco", "")

    print("🔥 COMBUSTIBLE FI:", repr(fi))
    print("🔥 COMBUSTIBLE FF:", repr(ff))
    print("🔥 COMBUSTIBLE ECO:", repr(eco))
    print("🔥 COMBUSTIBLE OBRA:", repr(obr))

    user = get_current_user()
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

    
    kpis = db.get_combustible_kpis(fi, ff, obra=obra_filtro)   # ✅
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

    fi_html = str(fi)[:10]
    ff_html = str(ff)[:10]

    print("🔥 FI HTML:", repr(fi_html))
    print("🔥 FF HTML:", repr(ff_html))

    return render_template(
    "combustible.html",
    reportes=reportes,
    reportes_diesel=reportes_diesel,
    reportes_gasolina=reportes_gasolina,
    kpis=kpis,
    por_obra=por_obra,
    obras=obras,
    user=user,
    fi=fi,
    ff=ff,
    fi_html=fi_html,
    ff_html=ff_html,
    sem=sem,
    obr=obr,
    eco=eco,
    ver_telemetria=ver_telemetria,
    obras_crear=obras_crear,
    puede_crear=puede_crear
)















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
    errores = 0          # filas que fallaron por excepción real (no se importaron)
    incompletas = 0      # filas importadas pero con datos faltantes (fecha de respaldo, etc.)
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

    # ── Fecha de respaldo para filas SIN fecha válida ──
    # La columna `fecha` es NOT NULL y forma parte de la clave única
    # (codigo_eco, fecha). Para NO omitir filas incompletas y evitar que
    # varias filas del mismo ECO se sobrescriban entre sí, generamos una
    # fecha única por cada fila incompleta del mismo ECO.
    _hoy_respaldo = _date.today()
    _contador_respaldo = {}
    def _fecha_respaldo(eco):
        n = _contador_respaldo.get(eco, 0)
        _contador_respaldo[eco] = n + 1
        return (_hoy_respaldo + timedelta(days=n)).strftime("%Y-%m-%d")

    def _clamp(v, max_abs):
        """Limita un número al rango soportado por la columna DECIMAL para
        que un valor fuera de rango NO haga fallar la inserción de la fila."""
        if v is None:
            return None
        try:
            v = float(v)
        except (ValueError, TypeError):
            return None
        if v > max_abs:
            return max_abs
        if v < -max_abs:
            return -max_abs
        return v

    def _insertar_combustible_seguro(datos):
        """Inserta la fila. Si el insert completo falla por algún valor problemático,
        reintenta con un payload mínimo para GARANTIZAR que la fila SÍ se guarde."""
        try:
            db.crear_reporte_combustible(datos)
            return
        except Exception as exc_full:
            # Reintento con lo mínimo indispensable (eco + fecha + litros + tipo)
            minimo = {
                "eco": datos.get("eco"),
                "nombre_equipo": datos.get("nombre_equipo", ""),
                "marca": datos.get("marca", ""),
                "id_obra": datos.get("id_obra"),
                "fecha": datos.get("fecha"),
                "semana": datos.get("semana"),
                "operador": datos.get("operador", ""),
                "litros_cargados": datos.get("litros_cargados"),
                "litros_telemetria": 0,
                "horas_maquina": None,
                "observaciones": (str(datos.get("observaciones") or "") +
                                  " [importado parcialmente]").strip(),
                "registrado_por": datos.get("registrado_por"),
                "tipo_combustible": datos.get("tipo_combustible", "diesel"),
            }
            db.crear_reporte_combustible(minimo)

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
                    # Si la fila no tiene ECO pero sí algún otro dato relevante,
                    # se importa igualmente con un ECO placeholder (no se omite).
                    if not eco_raw:
                        otros = [_val_d("fecha"), _val_d("litros"), _val_d("costo_total"),
                                 _val_d("responsable"), _val_d("folio")]
                        if all(v is None for v in otros):
                            continue  # Fila realmente vacía
                        eco = "SIN_ECO"
                    else:
                        eco = str(eco_raw).strip().upper()

                    # La fecha es NOT NULL en BD. Si falta o es inválida, usamos una
                    # fecha de respaldo única para no omitir la fila.
                    fecha = _limpiar_fecha(_val_d("fecha"))
                    if not fecha:
                        fecha = _fecha_respaldo(eco)
                        incompletas += 1  # SÍ se importa, solo se marca como incompleta

                    litros = _limpiar_num(_val_d("litros"))
                    if litros is not None and litros < 0:
                        litros = None

                    costo_total = _limpiar_num(_val_d("costo_total"))
                    h_ini = _limpiar_num(_val_d("horometro_ini"))
                    h_fin = _limpiar_num(_val_d("horometro_fin"))
                    horas = _limpiar_num(_val_d("horas_maquina"))
                    # Si no viene horas, calcular de horómetros
                    if not horas and h_ini and h_fin and h_fin > h_ini:
                        horas = round(h_fin - h_ini, 2)

                    costo_litro = _limpiar_num(_val_d("costo_litro"))
                    if not costo_litro and costo_total and litros and litros > 0:
                        costo_litro = round(costo_total / litros, 2)

                    lt_hr = _limpiar_num(_val_d("lt_por_hr"))
                    if not lt_hr and litros and litros > 0 and horas and horas > 0:
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
                        "eco": eco[:20],
                        "nombre_equipo": ((maq or {}).get("nombre_equipo", "") or "")[:150],
                        "marca": ((maq or {}).get("marca", "") or "")[:50],
                        "id_obra": id_obra,
                        "fecha": fecha,
                        "semana": semana,
                        "operador": str(_val_d("responsable") or "")[:120],
                        "litros_cargados": _clamp(litros, 999999.99),
                        "litros_telemetria": _clamp(float(tel or 0), 999999.99),
                        "horas_maquina": _clamp(horas, 999999.99),
                        "observaciones": str(_val_d("observaciones") or ""),
                        "registrado_por": session["user_id"],
                        "tipo_combustible": "diesel",
                        "costo_total": _clamp(costo_total, 9999999999.99),
                        "costo_por_litro": _clamp(costo_litro, 99999999.99),
                        "horometro_inicial": _clamp(h_ini, 99999999.99),
                        "horometro_final": _clamp(h_fin, 99999999.99),
                        "lt_por_hr": _clamp(lt_hr, 99999999.99),
                        "costo_por_hr": _clamp(costo_hr, 99999999.99),
                        "frente_trabajo": (str(_val_d("frente") or "") or None),
                        "actividad": (str(_val_d("actividad") or "") or None),
                        "origen_carga": (str(_val_d("origen") or "") or None),
                        "responsable": (str(_val_d("responsable") or "") or None),
                        "folio_ticket": (str(_val_d("folio") or "") or None),
                    }
                    if datos["frente_trabajo"]:
                        datos["frente_trabajo"] = datos["frente_trabajo"][:120]
                    if datos["actividad"]:
                        datos["actividad"] = datos["actividad"][:120]
                    if datos["origen_carga"]:
                        datos["origen_carga"] = datos["origen_carga"][:120]
                    if datos["responsable"]:
                        datos["responsable"] = datos["responsable"][:120]
                    if datos["folio_ticket"]:
                        datos["folio_ticket"] = datos["folio_ticket"][:60]
                    _insertar_combustible_seguro(datos)
                    importados_diesel += 1
                except Exception as exc:
                    errores += 1
                    if len(debug_info) < 8:
                        debug_info.append(f"Error diesel (eco={eco_raw}): {exc}")
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
                        otros = [_val_g("fecha"), _val_g("litros"), _val_g("costo_total"),
                                 _val_g("responsable"), _val_g("folio")]
                        if all(v is None for v in otros):
                            continue
                        eco = "SIN_ECO"
                    else:
                        eco = str(eco_raw).strip().upper()

                    fecha = _limpiar_fecha(_val_g("fecha"))
                    if not fecha:
                        fecha = _fecha_respaldo(eco)
                        incompletas += 1  # SÍ se importa, solo se marca como incompleta

                    litros = _limpiar_num(_val_g("litros"))
                    if litros is not None and litros < 0:
                        litros = None

                    costo_total = _limpiar_num(_val_g("costo_total"))
                    o_ini = _limpiar_num(_val_g("odometro_ini"))
                    o_fin = _limpiar_num(_val_g("odometro_fin"))
                    km = _limpiar_num(_val_g("km_recorridos"))
                    if not km and o_ini and o_fin and o_fin > o_ini:
                        km = round(o_fin - o_ini, 2)

                    costo_litro = _limpiar_num(_val_g("costo_litro"))
                    if not costo_litro and costo_total and litros and litros > 0:
                        costo_litro = round(costo_total / litros, 2)

                    km_litro = _limpiar_num(_val_g("km_litro"))
                    if not km_litro and km and litros and litros > 0:
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
                        "eco": eco[:20],
                        "nombre_equipo": ((maq or {}).get("nombre_equipo", "") or "")[:150],
                        "marca": ((maq or {}).get("marca", "") or "")[:50],
                        "id_obra": id_obra,
                        "fecha": fecha,
                        "semana": semana,
                        "operador": str(_val_g("responsable") or "")[:120],
                        "litros_cargados": _clamp(litros, 999999.99),
                        "litros_telemetria": _clamp(float(tel or 0), 999999.99),
                        "horas_maquina": None,
                        "observaciones": str(_val_g("observaciones") or ""),
                        "registrado_por": session["user_id"],
                        "tipo_combustible": "gasolina",
                        "costo_total": _clamp(costo_total, 9999999999.99),
                        "costo_por_litro": _clamp(costo_litro, 99999999.99),
                        "odometro_inicial": _clamp(o_ini, 99999999.99),
                        "odometro_final": _clamp(o_fin, 99999999.99),
                        "km_recorridos": _clamp(km, 99999999.99),
                        "km_por_litro": _clamp(km_litro, 9999999.999),
                        "costo_por_km": _clamp(costo_km, 99999999.99),
                        "destino": (str(_val_g("destino") or "") or None),
                        "actividad": (str(_val_g("actividad") or "") or None),
                        "origen_carga": (str(_val_g("origen") or "") or None),
                        "responsable": (str(_val_g("responsable") or "") or None),
                        "folio_ticket": (str(_val_g("folio") or "") or None),
                    }
                    if datos["destino"]:
                        datos["destino"] = datos["destino"][:120]
                    if datos["actividad"]:
                        datos["actividad"] = datos["actividad"][:120]
                    if datos["origen_carga"]:
                        datos["origen_carga"] = datos["origen_carga"][:120]
                    if datos["responsable"]:
                        datos["responsable"] = datos["responsable"][:120]
                    if datos["folio_ticket"]:
                        datos["folio_ticket"] = datos["folio_ticket"][:60]
                    _insertar_combustible_seguro(datos)
                    importados_gasolina += 1
                except Exception as exc:
                    errores += 1
                    if len(debug_info) < 8:
                        debug_info.append(f"Error gasolina (eco={eco_raw}): {exc}")
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
        flash(msg, "success")
        if errores:
            errs = [d for d in debug_info if d.startswith("Error")]
            detalle = " | ".join(errs[:8]) if errs else ""
            flash(f"{errores} fila(s) no se pudieron importar. Detalle: {detalle}",
                  "warning")

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
@permiso_requerido("permisos", "editar")
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
                           acciones_por_modulo=db.ACCIONES_POR_MODULO,
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
        campos_num = ["num_camiones","vol_m3",
                      "asf_ini","asf_desc","asf_final",
                      "alt_ini","alt_desc","alt_final",
                      "vol_compacto","vol_acumulado","abundamiento",
                      "emu_lts_m2","emu_ini","emu_desc","emu_final",
                      "grava_carpeta_ini","grava_carpeta_recib","grava_carpeta_cons","grava_carpeta_final",
                      "arena_ini","arena_recib","arena_cons","arena_final",
                      "grava_normal_ini","grava_normal_recib","grava_normal_cons","grava_normal_final",
                      "grava_sello_ini","grava_sello_recib","grava_sello_cons","grava_sello_final",
                      "grava_medio_ini","grava_medio_recib","grava_medio_cons","grava_medio_final"]
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
    # Toggle: si está validado, lo revierte; si no, lo valida
    reg = db.query("SELECT validado FROM planta_produccion WHERE id=%s", (pid,), one=True)
    if reg and reg["validado"]:
        db.execute("UPDATE planta_produccion SET validado=0 WHERE id=%s", (pid,))
        flash("Validación revertida — registro pendiente.", "success")
    else:
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
    # Manejar formato tipo 19"-"06"-"2026 (separadores con comillas)
    import re as _re
    txt_clean = _re.sub(r'["\']', '', txt).strip()
    txt_clean = _re.sub(r'\s*-\s*', '-', txt_clean)
    # Corregir años mal escritos: 0206→2026, 0202→2026, etc.
    # Detectar año de 4 dígitos al final que no esté en rango razonable
    m_year = _re.search(r'[/-](\d{4})$', txt_clean)
    if m_year:
        year_str = m_year.group(1)
        year_int = int(year_str)
        if year_int < 2020 or year_int > 2030:
            # Intentar reordenar dígitos para formar un año válido (2024-2027)
            from itertools import permutations
            digitos = list(year_str)
            for perm in permutations(digitos):
                candidato = int("".join(perm))
                if 2024 <= candidato <= 2027:
                    txt_clean = txt_clean[:m_year.start(1)] + str(candidato)
                    break
            else:
                # Si no se puede reordenar, asumir 2026 (año más probable del proyecto)
                txt_clean = txt_clean[:m_year.start(1)] + "2026"
    for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y",
                "%d/%m/%y", "%d-%m-%y", "%Y/%m/%d", "%d-%m-%Y"]:
        try:
            parsed = _dt.strptime(txt_clean, fmt)
            # Validar que el año sea razonable (2020-2030)
            if 2020 <= parsed.year <= 2030:
                return parsed.strftime("%Y-%m-%d")
            # Si el año no es razonable, intentar siguiente formato
            continue
        except ValueError:
            continue
    # Segundo intento sin validación de rango (para no perder datos)
    for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y",
                "%d/%m/%y", "%d-%m-%y", "%Y/%m/%d"]:
        try:
            return _dt.strptime(txt_clean, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # Intentar con el texto original
    for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y",
                "%d/%m/%y", "%d-%m-%y", "%Y/%m/%d"]:
        try:
            return _dt.strptime(txt, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _detectar_fila_encabezado(filas, palabras_clave):
    """Busca la primera fila que contenga al menos 2 de las palabras clave."""
    for idx, fila in enumerate(filas[:20]):
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
        ["producción", "produccion", "prod", "production", "produccion planta", "produccion planta nuevo"],
        wbi,
        palabras_clave_contenido=["fecha", "material", "cam", "vol"])
    # Si solo tiene una hoja y no encontró ninguna específica, asumir producción
    if not hoja_prod and len(wbi.sheetnames) == 1:
        hoja_prod = wbi.sheetnames[0]
    # Fallback: buscar hoja que contenga "planta" en el nombre
    if not hoja_prod:
        for hoja_lower, hoja_real in hojas.items():
            if "planta" in hoja_lower and "produccion" in hoja_lower:
                hoja_prod = hoja_real
                break

    if hoja_prod:
        ws = wbi[hoja_prod]
        filas = list(ws.iter_rows(min_row=1, values_only=True))
        if filas and len(filas) >= 2:
            # Auto-detectar fila de encabezado — buscar fila con "fecha" como celda individual
            idx_header = None
            for idx_h, fila_h in enumerate(filas[:25]):
                if not fila_h:
                    continue
                celdas_norm = [_normalizar_texto(c) for c in fila_h if c is not None]
                # La fila de encabezado debe tener "fecha" como celda independiente
                tiene_fecha = any(c == "fecha" or c == "#" and "fecha" in " ".join(celdas_norm) for c in celdas_norm)
                tiene_material = any("material" in c for c in celdas_norm)
                tiene_vol = any("vol" in c for c in celdas_norm)
                if tiene_fecha and (tiene_material or tiene_vol):
                    idx_header = idx_h
                    break
            if idx_header is None:
                idx_header = _detectar_fila_encabezado(filas, ["fecha", "material", "vol", "camiones", "asf"])
            header_raw = filas[idx_header]
            header_norm = [_normalizar_texto(c) for c in header_raw]
            debug_info.append(f"Producción: hoja='{hoja_prod}', encabezado en fila {idx_header+1}, cols={header_norm}")

            mapeo_prod = {
                "fecha": ["fecha", "date"],
                "material": ["material", "tipo material", "tipo"],
                "num_camiones": ["# camiones", "#camiones", "camiones", "num camiones", "no camiones", "num_camiones", "# cam", "# cam."],
                "vol_m3": ["vol m³", "vol m3", "vol_m3", "volumen", "volumen m3", "vol  m3", "vol m"],
                "asf_ini": ["asf ini", "asf ini lt", "asf_ini", "asfalto inicial", "asfalto ini", "ini. (lt)", "ini (lt)", "ini."],
                "asf_desc": ["asf desc", "asf desc lt", "asf_desc", "descarga asfalto", "asfalto descarga", "desc. (lt)", "desc (lt)", "desc."],
                "asf_final": ["asf final", "asf final lt", "asf_final", "asfalto final", "final (lt)", "final"],
                "alt_ini": ["alt ini", "alt ini lt", "alt_ini", "alterno inicial", "comb alt ini", "ini. (lt)_1"],
                "alt_desc": ["alt desc", "alt desc lt", "alt_desc", "alterno descarga", "comb alt desc", "desc. (lt)_1"],
                "alt_final": ["alt final", "alt final lt", "alt_final", "alterno final", "comb alt final", "final (lt)_1"],
                "emu_ini": ["emu ini", "emu ini lt", "emu_ini", "emulsion inicial", "ini. (lt)_2"],
                "emu_desc": ["emu desc", "emu desc lt", "emu_desc", "emulsion descarga", "desc. (lt)_2"],
                "emu_final": ["emu final", "emu final lt", "emu_final", "emulsion final", "final (lt)_2"],
                "grava_ini": ["grava ini", "grava inicial", "grava_ini", "ini. (m³)", "ini (m3)"],
                "grava_recib": ["grava recib", "grava recibida", "grava_recib", "recib. (m³)", "recib (m3)"],
                "arena_ini": ["arena ini", "arena inicial", "arena_ini"],
                "arena_recib": ["arena recib", "arena recibida", "arena_recib"],
                "vol_compacto": ["vol comp", "vol comp.", "vol compacto", "volumen compacto"],
                "vol_acumulado": ["acumulado", "vol acumulado", "acum"],
                "abundamiento": ["abundam", "abundam.", "abundamiento", "abund"],
            }
            col_map_prod = _mapear_columnas(header_norm, mapeo_prod)
            
            # ── Detección del formato ESMA con encabezados repetidos ──
            # El Excel ESMA usa "Ini. (lt)", "Desc. (lt)", "Final (lt)" repetidos para
            # Asfalto, Alterno y Emulsión. El mapeo por nombre solo detecta la primera
            # ocurrencia, así que forzamos mapeo por posición relativa a "fecha".
            # Se activa si: encontró fecha Y (no encontró alt_ini O no encontró emu_ini)
            # Y el encabezado tiene suficientes columnas.
            usa_posicion = False
            if "fecha" in col_map_prod:
                pos_fecha = col_map_prod["fecha"]
                # Verificar si hay encabezados repetidos (señal de formato ESMA)
                ini_count = sum(1 for h in header_norm if "ini" in h and ("lt" in h or "m3" in h or "m\u00b3" in h))
                if ini_count >= 2 or ("alt_ini" not in col_map_prod and len(header_norm) >= pos_fecha + 20):
                    usa_posicion = True

            if usa_posicion:
                pos_fecha = col_map_prod["fecha"]
                p = pos_fecha  # base offset
                # formato ESMA: #(p-1) Fecha(p) Material(p+1) #Cam(p+2) Vol(p+3) lts/m3(p+4)
                # Asfalto: Ini(p+5) Desc(p+6) Cons(p+7) Final(p+8) kg(p+9)
                # Alterno: Ini(p+10) Desc(p+11) Final(p+12) Cons(p+13) lts/m3(p+14)
                # Avance: Vol_comp(p+15) Acum(p+16) Abund(p+17)
                # Emulsión: lts/m2(p+18) Ini(p+19) Desc(p+20) Cons(p+21) Final(p+22)
                # Validado(p+23)
                # Grava_carp: Ini(p+24) Recib(p+25) Cons(p+26) Final(p+27)
                # Arena: Ini(p+28) Recib(p+29) Cons(p+30) Final(p+31)
                # Grava_norm: Ini(p+32) Recib(p+33) Cons(p+34) Final(p+35)
                # Grava_sello: Ini(p+36) Recib(p+37) Cons(p+38) Final(p+39)
                # Grava_medio: Ini(p+40) Recib(p+41) Cons(p+42) Final(p+43)
                col_map_prod = {"fecha": p}
                col_map_prod.update({
                    "material": p+1, "num_camiones": p+2, "vol_m3": p+3, "lts_m3": p+4,
                    "asf_ini": p+5, "asf_desc": p+6, "asf_cons": p+7, "asf_final": p+8, "asf_kg": p+9,
                    "alt_ini": p+10, "alt_desc": p+11, "alt_final": p+12, "alt_cons": p+13, "alt_lts_m3": p+14,
                    "vol_compacto": p+15, "vol_acumulado": p+16, "abundamiento": p+17,
                    "emu_lts_m2": p+18, "emu_ini": p+19, "emu_desc": p+20, "emu_cons": p+21, "emu_final": p+22,
                })
                if len(header_norm) >= p+44:
                    col_map_prod.update({
                        "grava_carpeta_ini": p+24, "grava_carpeta_recib": p+25, "grava_carpeta_cons": p+26, "grava_carpeta_final": p+27,
                        "arena_ini": p+28, "arena_recib": p+29, "arena_cons": p+30, "arena_final": p+31,
                        "grava_normal_ini": p+32, "grava_normal_recib": p+33, "grava_normal_cons": p+34, "grava_normal_final": p+35,
                        "grava_sello_ini": p+36, "grava_sello_recib": p+37, "grava_sello_cons": p+38, "grava_sello_final": p+39,
                        "grava_medio_ini": p+40, "grava_medio_recib": p+41, "grava_medio_cons": p+42, "grava_medio_final": p+43,
                    })
            
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
                # Filas con muy pocas celdas con contenido real (ej: solo # de fila) → saltar sin contar error
                celdas_con_valor = sum(1 for c in fila if c is not None and str(c).strip() not in ("", "—", "-", "✓ OK", "✓"))
                if celdas_con_valor < 3:
                    continue
                try:
                    idx_fecha = col_map_prod.get("fecha")
                    if idx_fecha is None or idx_fecha >= len(fila):
                        errores += 1
                        continue
                    valor_fecha = fila[idx_fecha]
                    fecha = _convertir_fecha_excel(valor_fecha)
                    if not fecha:
                        # Si la celda de fecha está vacía/None, es una fila residual → no contar como error
                        if valor_fecha is None or str(valor_fecha).strip() in ("", "—", "-"):
                            continue
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
                        "lts_m3": _num_p("lts_m3"),
                        "asf_ini": _num_p("asf_ini"),
                        "asf_desc": _num_p("asf_desc"),
                        "asf_cons": _num_p("asf_cons"),
                        "asf_final": _num_p("asf_final"),
                        "asf_kg": _num_p("asf_kg"),
                        "alt_ini": _num_p("alt_ini"),
                        "alt_desc": _num_p("alt_desc"),
                        "alt_final": _num_p("alt_final"),
                        "alt_cons": _num_p("alt_cons"),
                        "alt_lts_m3": _num_p("alt_lts_m3"),
                        "vol_compacto": _num_p("vol_compacto"),
                        "vol_acumulado": _num_p("vol_acumulado"),
                        "abundamiento": _num_p("abundamiento"),
                        "emu_lts_m2": _num_p("emu_lts_m2"),
                        "emu_ini": _num_p("emu_ini"),
                        "emu_desc": _num_p("emu_desc"),
                        "emu_cons": _num_p("emu_cons"),
                        "emu_final": _num_p("emu_final"),
                        "grava_carpeta_ini": _num_p("grava_carpeta_ini"),
                        "grava_carpeta_recib": _num_p("grava_carpeta_recib"),
                        "grava_carpeta_cons": _num_p("grava_carpeta_cons"),
                        "grava_carpeta_final": _num_p("grava_carpeta_final"),
                        "arena_ini": _num_p("arena_ini"),
                        "arena_recib": _num_p("arena_recib"),
                        "arena_cons": _num_p("arena_cons"),
                        "arena_final": _num_p("arena_final"),
                        "grava_normal_ini": _num_p("grava_normal_ini"),
                        "grava_normal_recib": _num_p("grava_normal_recib"),
                        "grava_normal_cons": _num_p("grava_normal_cons"),
                        "grava_normal_final": _num_p("grava_normal_final"),
                        "grava_sello_ini": _num_p("grava_sello_ini"),
                        "grava_sello_recib": _num_p("grava_sello_recib"),
                        "grava_sello_cons": _num_p("grava_sello_cons"),
                        "grava_sello_final": _num_p("grava_sello_final"),
                        "grava_medio_ini": _num_p("grava_medio_ini"),
                        "grava_medio_recib": _num_p("grava_medio_recib"),
                        "grava_medio_cons": _num_p("grava_medio_cons"),
                        "grava_medio_final": _num_p("grava_medio_final"),
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
                # Filas con muy pocas celdas con contenido → saltar sin contar error
                celdas_con_valor = sum(1 for c in fila if c is not None and str(c).strip() not in ("", "—", "-", "✓ OK", "✓"))
                if celdas_con_valor < 3:
                    continue
                try:
                    idx_fecha = col_map_av.get("fecha")
                    fecha = _convertir_fecha_excel(fila[idx_fecha] if idx_fecha is not None and idx_fecha < len(fila) else None)
                    if not fecha:
                        # Fila sin fecha real → residual, no contar como error
                        val_f = fila[idx_fecha] if idx_fecha is not None and idx_fecha < len(fila) else None
                        if val_f is None or str(val_f).strip() in ("", "—", "-"):
                            continue
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

                    def _parse_cadenamiento(val):
                        """Parsea cadenamiento tipo '91+276.00' → 91276.00, o float directo."""
                        if val is None:
                            return None
                        if isinstance(val, (int, float)):
                            return float(val)
                        txt = str(val).strip()
                        # Formato cadenamiento: km+metros (ej: 91+276.00)
                        import re as _re_cad
                        m = _re_cad.match(r'^(\d+)\+(\d+(?:\.\d+)?)$', txt)
                        if m:
                            km = int(m.group(1))
                            metros = float(m.group(2))
                            return km * 1000 + metros
                        # Intentar float directo
                        try:
                            return float(txt.replace(",", ""))
                        except (ValueError, TypeError):
                            return None

                    inicio_num = _parse_cadenamiento(inicio)
                    termino_num = _parse_cadenamiento(termino)
                    if inicio_num is None or termino_num is None:
                        errores += 1
                        continue

                    datos = {
                        "id_obra": id_obra, "fecha": fecha,
                        "carril": str(_val_av("carril") or ""),
                        "inicio": inicio_num, "termino": termino_num,
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
                # Filas con muy pocas celdas con contenido → saltar sin contar error
                celdas_con_valor = sum(1 for c in fila if c is not None and str(c).strip() not in ("", "—", "-", "✓ OK", "✓"))
                if celdas_con_valor < 3:
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
                        # Si no hay fecha ni peso, es fila residual → no contar como error
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
    archivo.save(os.path.join(DOCS_FOLDER, fname))
    doc_id = db.crear_documento(tipo, nombre or archivo.filename, fname,
                       id_maquina, id_obra, session["user_id"], id_carpeta)
    db.registrar_actividad(
        accion="crear", ip=get_client_ip(),
        id_usuario=session.get("user_id"), nombre=session.get("user_nombre"),
        email=session.get("user_email"), rol=session.get("user_rol"),
        modulo="documentos",
        descripcion=f"Subió documento '{nombre or archivo.filename}' (tipo={tipo})"
                    + (f" obra_id={id_obra}" if id_obra else "")
                    + (f" carpeta_id={id_carpeta}" if id_carpeta else ""),
        objeto_id=str(doc_id), objeto_tipo="documento",
        metodo="POST", ruta=request.path,
        user_agent=request.headers.get("User-Agent","")[:300],
        **get_geo_ip(get_client_ip()),
    )
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
        cid = db.crear_carpeta(nombre, padre_id, id_obra)
        db.registrar_actividad(
            accion="crear", ip=get_client_ip(),
            id_usuario=session.get("user_id"), nombre=session.get("user_nombre"),
            email=session.get("user_email"), rol=session.get("user_rol"),
            modulo="documentos",
            descripcion=f"Creó carpeta '{nombre}'"
                        + (f" padre_id={padre_id}" if padre_id else " (raíz)")
                        + (f" obra_id={id_obra}" if id_obra else ""),
            objeto_id=str(cid), objeto_tipo="carpeta",
            metodo="POST", ruta=request.path,
            user_agent=request.headers.get("User-Agent","")[:300],
            **get_geo_ip(get_client_ip()),
        )
        flash(f"Carpeta '{nombre}' creada.", "success")
    return redirect(request.referrer or url_for("documentos"))

@app.route("/documentos/carpetas/<int:cid>/eliminar", methods=["POST"])
@login_required
@permiso_requerido("documentos", "eliminar")
def eliminar_carpeta(cid):
    # Obtener nombre antes de borrar para el registro
    carpeta = db.query("SELECT * FROM doc_carpetas WHERE id=%s", (cid,), one=True)
    nombre_carp = carpeta["nombre"] if carpeta else str(cid)
    db.eliminar_carpeta(cid)
    db.registrar_actividad(
        accion="eliminar", ip=get_client_ip(),
        id_usuario=session.get("user_id"), nombre=session.get("user_nombre"),
        email=session.get("user_email"), rol=session.get("user_rol"),
        modulo="documentos",
        descripcion=f"Eliminó carpeta '{nombre_carp}' (id={cid})",
        objeto_id=str(cid), objeto_tipo="carpeta",
        metodo="POST", ruta=request.path,
        user_agent=request.headers.get("User-Agent","")[:300],
        **get_geo_ip(get_client_ip()),
    )
    flash("Carpeta eliminada.", "success")
    return redirect(url_for("documentos"))

# ══════════════════════════════════════════════════════════════════
#  API JSON — Documentos de obra (drag & drop)
# ══════════════════════════════════════════════════════════════════

@app.route("/obras/<int:oid>/api/nueva_carpeta", methods=["POST"])
@login_required
@permiso_requerido("documentos", "crear")
def obra_api_nueva_carpeta(oid):
    """Crea una carpeta (o la reutiliza si ya existe con el mismo nombre y padre)
    y responde JSON. Usado por el drag & drop del front-end."""
    data     = request.get_json(silent=True) or {}
    nombre   = (data.get("nombre") or "").strip()
    padre_id = data.get("padre_id") or None
    if padre_id is not None:
        try: padre_id = int(padre_id)
        except (ValueError, TypeError): padre_id = None

    if not nombre:
        return {"ok": False, "error": "nombre requerido"}, 400

    # Reutilizar carpeta si ya existe (mismo nombre + padre + obra)
    existentes = db.get_carpetas(id_obra=oid)
    for c in existentes:
        c_padre = c["padre_id"]
        if c["nombre"] == nombre and (c_padre or None) == (padre_id or None):
            return {"ok": True, "carpeta_id": c["id"], "nombre": c["nombre"], "reutilizada": True}

    cid = db.crear_carpeta(nombre, padre_id, oid)
    db.registrar_actividad(
        accion="crear", ip=get_client_ip(),
        id_usuario=session.get("user_id"), nombre=session.get("user_nombre"),
        email=session.get("user_email"), rol=session.get("user_rol"),
        modulo="documentos",
        descripcion=f"Creó carpeta '{nombre}' vía drag&drop"
                    + (f" padre_id={padre_id}" if padre_id else " (raíz)")
                    + f" obra_id={oid}",
        objeto_id=str(cid), objeto_tipo="carpeta",
        metodo="POST", ruta=request.path,
        user_agent=request.headers.get("User-Agent","")[:300],
        **get_geo_ip(get_client_ip()),
    )
    return {"ok": True, "carpeta_id": cid, "nombre": nombre, "reutilizada": False}


@app.route("/obras/<int:oid>/api/subir_documento", methods=["POST"])
@login_required
@permiso_requerido("documentos", "crear")
def obra_api_subir_documento(oid):
    """Sube un archivo vía AJAX y responde JSON con los datos del documento creado.
    Usado por el drag & drop del front-end."""
    archivo    = request.files.get("archivo")
    tipo       = request.form.get("tipo", "otro")
    nombre     = (request.form.get("nombre") or "").strip()
    id_carpeta = request.form.get("id_carpeta") or None
    if id_carpeta is not None:
        try: id_carpeta = int(id_carpeta)
        except (ValueError, TypeError): id_carpeta = None

    if not archivo or archivo.filename == "":
        return {"ok": False, "error": "archivo requerido"}, 400

    # Sanitizar nombre de archivo (solo el basename, sin barras)
    nombre_original = os.path.basename(archivo.filename)
    fname = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{nombre_original}"
    archivo.save(os.path.join(DOCS_FOLDER, fname))

    doc_id = db.crear_documento(
        tipo,
        nombre or nombre_original,
        fname,
        None,          # id_maquina
        oid,
        session["user_id"],
        id_carpeta,
    )

    # Nombre del usuario para la respuesta
    user = get_current_user()
    db.registrar_actividad(
        accion="crear", ip=get_client_ip(),
        id_usuario=session.get("user_id"), nombre=session.get("user_nombre"),
        email=session.get("user_email"), rol=session.get("user_rol"),
        modulo="documentos",
        descripcion=f"Subió documento '{nombre or nombre_original}' (tipo={tipo})"
                    + (f" carpeta_id={id_carpeta}" if id_carpeta else "")
                    + f" obra_id={oid}",
        objeto_id=str(doc_id), objeto_tipo="documento",
        metodo="POST", ruta=request.path,
        user_agent=request.headers.get("User-Agent","")[:300],
        **get_geo_ip(get_client_ip()),
    )
    return {
        "ok": True,
        "doc": {
            "id":          doc_id,
            "nombre":      nombre or nombre_original,
            "tipo":        tipo,
            "id_carpeta":  id_carpeta,
            "subido_por":  user.get("nombre", ""),
            "subido_en":   datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
    }


def _ruta_archivo_documento(nombre_archivo):
    """Busca el archivo de un documento en las subcarpetas de uploads.
    Hace búsqueda case-insensitive en sistemas donde el FS distinga
    mayúsculas (Linux/ext4) para tolerar archivos subidos con nombre en
    mayúsculas (ej. PEDIMENTO.PDF) cuyo nombre en disco puede diferir.
    Retorna la ruta completa o None."""
    if not nombre_archivo:
        return None
    nombre_archivo = os.path.basename(nombre_archivo)  # evita path traversal
    if not nombre_archivo:
        return None

    carpetas = [EQUIPOS_FOLDER, DOCS_FOLDER, UPLOAD_FOLDER, EMPLEADOS_FOLDER,
                CHAT_FOLDER, ASISTENCIA_FOLDER, CFDI_FOLDER, COTIZACIONES_FOLDER,
                PROVEEDORES_FOLDER, REPORTES_OBRA_FOLDER]

    for carpeta in carpetas:
        # Intento exacto primero (rápido)
        ruta = os.path.join(carpeta, nombre_archivo)
        if os.path.isfile(ruta):
            return ruta

    # Fallback case-insensitive: recorre cada carpeta buscando coincidencia
    nombre_lower = nombre_archivo.lower()
    for carpeta in carpetas:
        try:
            for fname in os.listdir(carpeta):
                if fname.lower() == nombre_lower:
                    ruta = os.path.join(carpeta, fname)
                    if os.path.isfile(ruta):
                        return ruta
        except OSError:
            continue

    return None


@app.route("/documentos/<int:did>/descargar")
@login_required
def descargar_documento(did):
    doc = db.query("SELECT * FROM documentos WHERE id=%s", (did,), one=True)
    if not doc: abort(404)
    path = _ruta_archivo_documento(doc["archivo"])
    if not path: abort(404)
    
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
    path = _ruta_archivo_documento(doc["archivo"])
    if not path: abort(404)
    return send_file(path, as_attachment=False)

@app.route("/documentos/<int:did>/reemplazar", methods=["POST"])
@login_required
@permiso_requerido("documentos", "editar")
def reemplazar_documento(did):
    """Reemplaza el archivo físico de un documento existente manteniendo
    el mismo registro en la BD (nombre, tipo, carpeta, obra, etc.)."""
    doc = db.query("SELECT * FROM documentos WHERE id=%s", (did,), one=True)
    if not doc:
        return {"ok": False, "error": "Documento no encontrado"}, 404

    archivo = request.files.get("archivo")
    if not archivo or archivo.filename == "":
        return {"ok": False, "error": "No se recibió ningún archivo"}, 400

    # Conservar la extensión del nuevo archivo
    nombre_original = os.path.basename(archivo.filename)
    _, ext_nueva = os.path.splitext(nombre_original)

    # Nuevo nombre en disco con timestamp para evitar colisiones de caché
    fname_nuevo = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{nombre_original}"
    ruta_nueva = os.path.join(DOCS_FOLDER, fname_nuevo)
    archivo.save(ruta_nueva)

    # Borrar el archivo físico anterior si existe (no falla si ya no está)
    ruta_vieja = _ruta_archivo_documento(doc["archivo"])
    if ruta_vieja:
        try:
            os.remove(ruta_vieja)
        except OSError:
            pass  # si ya no existe, no importa

    # Actualizar solo el campo 'archivo' en la BD
    db.execute("UPDATE documentos SET archivo=%s WHERE id=%s", (fname_nuevo, did))

    db.registrar_actividad(
        accion="editar", ip=get_client_ip(),
        id_usuario=session.get("user_id"), nombre=session.get("user_nombre"),
        email=session.get("user_email"), rol=session.get("user_rol"),
        modulo="documentos",
        descripcion=f"Reemplazó archivo de documento '{doc['nombre']}' → '{nombre_original}' (id={did})",
        objeto_id=str(did), objeto_tipo="documento",
        metodo="POST", ruta=request.path,
        user_agent=request.headers.get("User-Agent", "")[:300],
        **get_geo_ip(get_client_ip()),
    )

    return {"ok": True, "archivo": fname_nuevo, "nombre_original": nombre_original}


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
        db.registrar_actividad(
            accion="editar", ip=get_client_ip(),
            id_usuario=session.get("user_id"), nombre=session.get("user_nombre"),
            email=session.get("user_email"), rol=session.get("user_rol"),
            modulo="documentos",
            descripcion=f"Editó documento '{nombre}' (tipo={tipo}, id={did})",
            objeto_id=str(did), objeto_tipo="documento",
            metodo="POST", ruta=request.path,
            user_agent=request.headers.get("User-Agent","")[:300],
            **get_geo_ip(get_client_ip()),
        )
        flash("Documento actualizado.", "success")
        return redirect(request.form.get("next") or url_for("documentos"))
    # Determinar la URL de retorno
    next_url = request.referrer or url_for("documentos")
    return render_template("documento_editar.html", doc=doc, user=user, next_url=next_url)

@app.route("/documentos/<int:did>/eliminar", methods=["POST"])
@login_required
@permiso_requerido("documentos", "eliminar")
def eliminar_documento(did):
    # Si la petición viene como JSON o con cabecera X-Requested-With, responde JSON
    wants_json = (request.is_json or
                  request.headers.get("X-Requested-With") == "XMLHttpRequest" or
                  request.headers.get("Accept","").startswith("application/json"))
    doc = db.eliminar_documento(did)
    if doc:
        borrar_archivo_fisico(doc["archivo"])
        db.registrar_actividad(
            accion="eliminar", ip=get_client_ip(),
            id_usuario=session.get("user_id"), nombre=session.get("user_nombre"),
            email=session.get("user_email"), rol=session.get("user_rol"),
            modulo="documentos",
            descripcion=f"Eliminó documento '{doc['nombre']}' (archivo={doc['archivo']})"
                        + (f" id_obra={doc['id_obra']}" if doc.get("id_obra") else "")
                        + (f" carpeta_id={doc['id_carpeta']}" if doc.get("id_carpeta") else ""),
            objeto_id=str(did), objeto_tipo="documento",
            metodo="POST", ruta=request.path,
            user_agent=request.headers.get("User-Agent","")[:300],
            **get_geo_ip(get_client_ip()),
        )
        if wants_json:
            return jsonify({"ok": True, "id": did})
    else:
        if wants_json:
            return jsonify({"ok": False, "error": "Documento no encontrado"}), 404
    flash("Documento eliminado.", "success")
    return redirect(request.referrer or url_for("documentos"))


@app.route("/api/documentos/eliminar-lote", methods=["POST"])
@login_required
@permiso_requerido("documentos", "eliminar")
def api_eliminar_documentos_lote():
    """Elimina uno o varios documentos por ID. Recibe JSON {ids: [1,2,3]}
    o form data ids=1&ids=2. Responde JSON sin redirigir."""
    if request.is_json:
        ids = request.get_json(silent=True) or {}
        ids = ids.get("ids", [])
    else:
        ids = request.form.getlist("ids")
    eliminados = []
    errores = []
    for did in ids:
        try:
            did = int(did)
        except (ValueError, TypeError):
            errores.append({"id": did, "error": "id inválido"})
            continue
        doc = db.eliminar_documento(did)
        if doc:
            borrar_archivo_fisico(doc["archivo"])
            db.registrar_actividad(
                accion="eliminar", ip=get_client_ip(),
                id_usuario=session.get("user_id"), nombre=session.get("user_nombre"),
                email=session.get("user_email"), rol=session.get("user_rol"),
                modulo="documentos",
                descripcion=f"Eliminó documento '{doc['nombre']}' (archivo={doc['archivo']})"
                            + (f" id_obra={doc['id_obra']}" if doc.get("id_obra") else ""),
                objeto_id=str(did), objeto_tipo="documento",
                metodo="POST", ruta=request.path,
                user_agent=request.headers.get("User-Agent","")[:300],
                **get_geo_ip(get_client_ip()),
            )
            eliminados.append(did)
        else:
            errores.append({"id": did, "error": "no encontrado"})
    return jsonify({"ok": True, "eliminados": eliminados, "errores": errores})

# --- AUDITORIA / HISTORIAL DE ACTIVIDADES ---
@app.route("/auditoria")
@login_required
@permiso_requerido("auditoria", "leer")
def auditoria():
    """Pantalla de auditoría: lista TODAS las actividades registradas en
    `historial_actividades`, con filtro por usuario y buscador por texto.
    Muestra qué hizo cada usuario, en qué módulo, en qué obra y cuándo.
    """
    id_usuario = request.args.get("id_usuario", "").strip()
    q = (request.args.get("q") or "").strip()

    registros = db.get_historial_actividades(
        id_usuario=int(id_usuario) if id_usuario.isdigit() else None,
        q=q or None,
    )

    # Mapa obra_id -> nombre, para resolver "en qué obra" desde la descripción
    try:
        obras = db.get_obras(archivada=None)
        obras_map = {o["id"]: o.get("nombre") for o in obras if o.get("id")}
    except Exception:
        obras_map = {}

    usuarios = db.get_usuarios()

    user = get_current_user()
    return render_template(
        "historial_actividades.html",
        registros=registros,
        usuarios=usuarios,
        obras_map=obras_map,
        filtro_user=id_usuario or None,
        search=q,
        user=user,
    )


@app.template_filter("obra_nombre")
def _obra_nombre_filter(descripcion, obras_map):
    """Jinja filter: extrae 'obra_id=N' de la descripción y devuelve el nombre
    de la obra (o None). Uso en plantilla:
        {{ r.descripcion | obra_nombre(obras_map) }}
    """
    if not descripcion:
        return None
    m = re.search(r"obra_id=(\d+)", str(descripcion))
    return obras_map.get(int(m.group(1))) if m else None


@app.template_filter("obra_id_num")
def _obra_id_num_filter(descripcion):
    """Jinja filter: extrae el número de obra de 'obra_id=N' en la descripción.
    Uso en plantilla: {% set oid = r.descripcion | obra_id_num() %}
    para enlazar a la página de esa obra.
    """
    if not descripcion:
        return None
    m = re.search(r"obra_id=(\d+)", str(descripcion))
    return int(m.group(1)) if m else None


# ══════════════════════════════════════════════════════════════════
#  MAQUINAS / EQUIPOS
# ══════════════════════════════════════════════════════════════════
@app.route("/maquinas")
@login_required
@permiso_requerido("equipos", "leer")
def maquinas():
    search = request.args.get("q","")
    clasif = request.args.get("clasificacion","")
    obra   = request.args.get("obra","")
    lista  = db.get_maquinas(search or None, clasif or None, obra or None)
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
                           clasifs=clasifs, search=search, clasificacion=clasif,
                           obra=obra, user=user)

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
        reportes = db.get_auditoria_combustible_maquina(eco, fi=fi, ff=ff)
        try:
            cargas = _jsonable(db.get_cargas_detectadas(eco, fi, ff))
        except Exception:
            cargas = []
    else:
        horas = _jsonable(db.get_horas_maquina(eco, 30))
        consu = _jsonable(db.get_consumo_maquina(eco, 30))
        reportes = db.get_auditoria_combustible_maquina(eco, fi=hace(30), ff=hoy_str())
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
            foto_archivo.save(os.path.join(EQUIPOS_FOLDER, foto_nombre))





        # db.crear_maquina({
        #     "eco": eco, "proveedor": f.get("proveedor",""),
        #     "nombre_equipo": f["nombre_equipo"], "marca": f.get("marca",""),
        #     "modelo": f.get("modelo",""), "serie": serie,
        #     "anio": f.get("anio") or None, "clasificacion": f.get("clasificacion",""),
        #     "cantidad": int(f.get("cantidad",1)), "id_obra": f.get("id_obra") or None,
        #     "ubicacion": f.get("ubicacion",""), "link_ubicacion": f.get("link_ubicacion",""),
        #     "foto": foto_nombre,
        # })
        db.crear_maquina({
            "eco": eco, "proveedor": f.get("proveedor",""),
            "nombre_equipo": f["nombre_equipo"], "marca": f.get("marca",""),
            "modelo": f.get("modelo",""), "serie": serie,
            "anio": f.get("anio") or None, "clasificacion": f.get("clasificacion",""),
            "cantidad": int(f.get("cantidad",1)), "id_obra": f.get("id_obra") or None,
            "ubicacion": f.get("ubicacion",""), "link_ubicacion": f.get("link_ubicacion",""),
            "foto": foto_nombre,
            "capacidad_litros": f.get("capacidad_litros") or None,
        })




        flash(f"Máquina {eco} creada correctamente.", "success")
        db.registrar_actividad(
            accion="crear", ip=get_client_ip(),
            id_usuario=session.get("user_id"), nombre=session.get("user_nombre"),
            email=session.get("user_email"), rol=session.get("user_rol"),
            modulo="equipos", descripcion=f"Creó equipo ECO={eco}",
            objeto_id=eco, objeto_tipo="equipo",
            metodo="POST", ruta=request.path,
            user_agent=request.headers.get("User-Agent","")[:300],
            **get_geo_ip(get_client_ip()),
        )
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
                foto_archivo.save(os.path.join(EQUIPOS_FOLDER, foto_nombre))
                if foto_anterior and foto_anterior != foto_nombre:
                    try:
                        os.remove(os.path.join(EQUIPOS_FOLDER, foto_anterior))
                    except OSError:
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




            # db.actualizar_maquina({
            #     "eco": eco, "proveedor": f.get("proveedor",""),
            #     "nombre_equipo": f["nombre_equipo"], "marca": f.get("marca",""),
            #     "modelo": f.get("modelo",""), "serie": serie,
            #     "anio": f.get("anio") or None, "clasificacion": f.get("clasificacion",""),
            #     "cantidad": int(f.get("cantidad",1)), "id_obra": f.get("id_obra") or None,
            #     "ubicacion": f.get("ubicacion",""), "link_ubicacion": f.get("link_ubicacion",""),
            #     "foto": foto_nombre, "capacidad_litros": None,
            # })



            db.actualizar_maquina({
            "eco": eco, "proveedor": f.get("proveedor",""),
            "nombre_equipo": f["nombre_equipo"], "marca": f.get("marca",""),
            "modelo": f.get("modelo",""), "serie": serie,
            "anio": f.get("anio") or None, "clasificacion": f.get("clasificacion",""),
            "cantidad": int(f.get("cantidad",1)), "id_obra": f.get("id_obra") or None,
            "ubicacion": f.get("ubicacion",""), "link_ubicacion": f.get("link_ubicacion",""),
            "foto": foto_nombre,
            "capacidad_litros": f.get("capacidad_litros") or None,
        })







            # Guardar capacidad del tanque en tabla estado (no en maquinas)
            # cap_litros = f.get("capacidad_litros") or None
            # if cap_litros:
            #     db.execute("UPDATE estado SET capacidad_litros=%s WHERE codigo_eco=%s",
            #                (cap_litros, eco))


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
                        os.remove(os.path.join(EQUIPOS_FOLDER, foto_anterior))
                    except OSError:
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
        db.registrar_actividad(
            accion="editar", ip=get_client_ip(),
            id_usuario=session.get("user_id"), nombre=session.get("user_nombre"),
            email=session.get("user_email"), rol=session.get("user_rol"),
            modulo="equipos", descripcion=f"Editó equipo ECO={eco}",
            objeto_id=eco, objeto_tipo="equipo",
            metodo="POST", ruta=request.path,
            user_agent=request.headers.get("User-Agent","")[:300],
            **get_geo_ip(get_client_ip()),
        )
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
            archivo.save(os.path.join(EQUIPOS_FOLDER, fname))
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
    obra   = request.args.get("obra","")
    lista  = db.get_maquinas(search or None, clasif or None, obra or None)
    ult_mants = db.get_ultimos_mantenimientos_todos()

    wb = Workbook()
    ws = wb.active
    ws.title = "Equipos"
    FONT_HEADER = Font(bold=True, color="FFFFFF")
    FILL_HEADER = PatternFill("solid", fgColor="2E3192")
    ALIGN_C = Alignment(horizontal="center")

    headers = ["ECO", "Nombre / Tipo", "Proveedor", "Marca", "Modelo", "Serie",
               "Año", "Clasificación", "Obra asignada", "Ubicación",
               "Horómetro (h)", "Último mant. (h)", "Fecha últ. mant.", "capacidad litros"]
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
            float(m["capacidad_litros"]) if m.get("capacidad_litros") is not None else "",
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

    # Detectar en qué fila está el encabezado real (puede haber títulos/fechas antes)
    filas = list(ws.iter_rows(min_row=1, values_only=True))
    if not filas or len(filas) < 2:
        flash("El archivo está vacío o no tiene datos.", "danger")
        return redirect(url_for("maquina_nueva"))

    fila_header_idx = None
    header = None
    for idx_fila in range(min(15, len(filas))):  # busca en las primeras 15 filas
        posible_header = [str(c or "").strip().lower() for c in filas[idx_fila]]
        if any("eco" in h for h in posible_header):
            fila_header_idx = idx_fila
            header = posible_header
            break

    if header is None:
        flash("No se encontró la columna 'ECO' o 'Código ECO' en el archivo.", "danger")
        return redirect(url_for("maquina_nueva"))

    col_map = {
        "eco": None, "codigo eco": None, "código eco": None,
        "nombre": None, "nombre del equipo": None, "nombre equipo": None, "nombre / tipo": None,
        "descripcion maquinaria": None, "descripción maquinaria": None,
        "proveedor": None, "marca": None, "modelo": None,
        "serie": None, "número de serie": None, "numero de serie": None,
        "año": None, "anio": None, "clasificacion": None, "clasificación": None, "tipo": None,
        "cantidad": None, "ubicacion": None, "ubicación": None, "proyecto": None,
    }
    for i, h in enumerate(header):
        for key in col_map:
            if key in h:
                col_map[key] = i
                break

    def idx(keys):
        for k in keys:
            if col_map.get(k) is not None:
                return col_map[k]
        return None

    i_eco   = idx(["eco", "codigo eco", "código eco"])
    i_nombre= idx(["nombre", "nombre del equipo", "nombre equipo", "nombre / tipo",
                "descripcion maquinaria", "descripción maquinaria"])
    i_prov  = idx(["proveedor"])
    i_marca = idx(["marca"])
    i_modelo= idx(["modelo"])
    i_serie = idx(["serie", "número de serie", "numero de serie"])
    i_anio  = idx(["año", "anio"])
    i_clasif= idx(["clasificacion", "clasificación", "tipo"])
    i_cant  = idx(["cantidad"])
    i_ubic  = idx(["ubicacion", "ubicación", "proyecto"])

    if i_eco is None:
        flash("No se encontró la columna 'ECO' o 'Código ECO' en el archivo.", "danger")
        return redirect(url_for("maquina_nueva"))

    importados = 0
    omitidos = 0
    errores = 0
    detalle_errores = []

    for fila in filas[fila_header_idx + 1:]:
        if not fila or all(c is None or str(c).strip() == "" for c in fila):
            continue

        eco = str(fila[i_eco] or "").strip().upper()
        if not eco:
            errores += 1
            detalle_errores.append(f"Fila sin ECO: {fila[:5]}")
            continue

        serie = str(fila[i_serie] or "").strip() if i_serie is not None else ""
        nombre = str(fila[i_nombre] or "").strip() if i_nombre is not None else ""

        conflictos = db.maquina_existe(eco=eco, serie=serie)
        if conflictos:
            omitidos += 1
            continue

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
                "capacidad_litros": None,
            })
            importados += 1
        except Exception as e:
            errores += 1
            detalle_errores.append(f"ECO {eco}: {e}")

    

    msg = f"Importación completada: {importados} equipo(s) agregado(s)."
    if omitidos:
        msg += f" Se omitieron {omitidos} porque ya existen (ECO o Serie duplicados)."
    if errores:
        msg += f" {errores} fila(s) con errores fueron ignoradas."
        print("=== DETALLE DE ERRORES DE IMPORTACIÓN ===")
        for d in detalle_errores[:20]:
            print(d)
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


# ── MAPA DE OBRAS CON FOTOS GEOLOCALIZADAS ───────────────────────

@app.route("/mapa-obras-fotos")
@login_required
def mapa_obras_fotos():
    """Vista general: mapa con fotos de evidencia de TODAS las obras."""
    user = get_current_user()
    obras_lista = db.get_obras(archivada=0)
    return render_template("mapa_obras_fotos.html", user=user, obras=obras_lista)


@app.route("/api/fotos-evidencia-obra")
@login_required
def api_fotos_evidencia_obra():
    """Devuelve todas las fotos de evidencia de obra (o de una obra específica)."""
    id_obra = request.args.get("id_obra", type=int)
    fotos = db.get_fotos_evidencia_obra(id_obra=id_obra)
    salida = []
    for f in fotos:
        salida.append({
            "id":             f["id"],
            "id_obra":        f["id_obra"],
            "obra_nombre":    f.get("obra_nombre") or "",
            "archivo":        f["archivo"],
            "descripcion":    f.get("descripcion") or "",
            "tramo":          f.get("tramo") or "",
            "latitud":        float(f["latitud"]),
            "longitud":       float(f["longitud"]),
            "precision_m":    float(f["precision_m"]) if f.get("precision_m") else None,
            "subido_por_nombre": f.get("subido_por_nombre") or "",
            "creado_en":      str(f.get("creado_en") or ""),
        })
    return jsonify(salida)


@app.route("/obras/<int:oid>/fotos/subir", methods=["POST"])
@login_required
@permiso_requerido("obras", "leer")
def obra_subir_foto(oid):
    """Recibe una foto con coordenadas GPS y la guarda en foto_evidencia_obra."""
    obra = db.get_obra(oid)
    if not obra:
        return jsonify({"error": "Obra no encontrada"}), 404

    archivo = request.files.get("foto")
    if not archivo or not archivo.filename:
        return jsonify({"error": "No se recibió archivo"}), 400

    lat  = request.form.get("latitud", type=float)
    lon  = request.form.get("longitud", type=float)
    if lat is None or lon is None:
        return jsonify({"error": "Se requieren coordenadas GPS"}), 400

    import time as _t
    ext = os.path.splitext(archivo.filename)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".heic"):
        return jsonify({"error": "Tipo de archivo no permitido"}), 400

    nombre_disco = f"obra{oid}_{int(_t.time() * 1000)}{ext}"
    archivo.save(os.path.join(FOTOS_OBRA_FOLDER, nombre_disco))

    db.insertar_foto_evidencia_obra({
        "id_obra":      oid,
        "archivo":      nombre_disco,
        "descripcion":  request.form.get("descripcion", "").strip() or None,
        "tramo":        request.form.get("tramo", "").strip() or None,
        "latitud":      lat,
        "longitud":     lon,
        "precision_m":  request.form.get("precision_m", type=float),
        "subido_por":   session.get("user_id"),
    })
    return jsonify({"ok": True, "archivo": nombre_disco})


@app.route("/obras/<int:oid>/fotos/<int:fid>/eliminar", methods=["POST"])
@login_required
@permiso_requerido("obras", "editar")
def obra_eliminar_foto(oid, fid):
    """Elimina una foto de evidencia."""
    row = db.eliminar_foto_evidencia_obra(fid, id_obra=oid)
    if not row:
        return jsonify({"error": "No encontrado"}), 404
    borrar_archivo_fisico(row["archivo"])
    return jsonify({"ok": True})


@app.route("/uploads/fotos_obra/<path:filename>")
@login_required
def serve_foto_obra(filename):
    """Sirve las fotos de evidencia de obra."""
    return send_file(os.path.join(FOTOS_OBRA_FOLDER, filename))


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
    usuarios_sistema = db.get_usuarios()
    user          = get_current_user()
    # Permisos específicos de este usuario para ESTA obra
    es_admin = (user["rol"] == "admin")
    if es_admin:
        perms_obra = {"documentos": {"crear": True, "leer": True, "editar": True, "eliminar": True},
                      "equipos": {"crear": True, "leer": True, "editar": True, "eliminar": True}}
    else:
        perms_obra = {}
        for mod in ["documentos", "equipos"]:
            rows = db.get_permisos_usuario_obra(user["id"], mod)
            for p in rows:
                if p["id_obra"] == oid:
                    perms_obra[mod] = {"crear": bool(p["crear"]), "leer": bool(p["leer"]),
                                       "editar": bool(p["editar"]), "eliminar": bool(p["eliminar"])}
                    break

    # Historial de auditoría de esta obra (últimos 200 registros)
    historial_obra = db.get_historial_actividades(id_obra=oid, limite=200)

    return render_template("obra_detalle.html", obra=obra, equipos=equipos,
                           documentos=docs, maquinas_disp=maquinas_disp,
                           carpetas_obra=carpetas_obra, user=user,
                           equipo_proyecto=usuarios_sistema,
                           directorio_equipo=db.get_directorio_equipo_proyecto(),
                           perms_obra=perms_obra,
                           historial_obra=historial_obra,
                           usuarios_sistema=usuarios_sistema)

# --- API de auditoría de obra (para filtrado AJAX) ---
@app.route("/obras/<int:oid>/api/historial")
@login_required
@permiso_requerido("obras", "leer")
def obra_api_historial(oid):
    obra = db.get_obra(oid)
    if not obra:
        return jsonify([]), 404
    id_usuario = request.args.get("id_usuario", "").strip()
    q = (request.args.get("q") or "").strip()
    registros = db.get_historial_actividades(
        id_obra=oid,
        id_usuario=int(id_usuario) if id_usuario.isdigit() else None,
        q=q or None,
        limite=500,
    )
    return jsonify(_jsonable(registros))

# --- NUEVAS RUTAS PARA ASIGNAR/LIBERAR MÁQUINAS ---
@app.route("/obras/<int:oid>/asignar_maquina", methods=["POST"])
@login_required
@permiso_requerido("obras", "editar")
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
@permiso_requerido("obras", "editar")
def obra_liberar_maquina(oid):
    if not obra_permitida(oid):
        flash("Solo puedes administrar la obra que tienes asignada.", "danger")
        return redirect(url_for("obra_detalle", oid=oid))
    eco = request.form.get("eco")
    if eco:
        db.actualizar_obra_maquina(eco, None)
        flash(f"Máquina {eco} liberada de esta obra.", "success")
    return redirect(url_for("obra_detalle", oid=oid))


@app.route("/obras/nueva", methods=["GET","POST"])
@login_required
@permiso_requerido("obras", "crear")
def obra_nueva():
    # Superintendente de Obra y Administrador de Obra solo administran su obra
    # asignada; crear obras nuevas es exclusivo del Admin.
    user = get_current_user()
    if request.method == "POST":
        f = request.form
        db.crear_obra({
            "nombre": f["nombre"], "numero_contrato": f.get("numero_contrato","").strip() or None,
            "descripcion": f.get("descripcion",""),
            "cliente": f.get("cliente",""),
            "ubicacion": f.get("ubicacion",""),
            "fecha_inicio": f.get("fecha_inicio") or None,
            "fecha_fin":    f.get("fecha_fin") or None,
            "estado":       f.get("estado","activa"),
            "link_drive":   f.get("link_drive","").strip() or None,
        })
        flash("Obra creada correctamente.", "success")
        db.registrar_actividad(
            accion="crear", ip=get_client_ip(),
            id_usuario=session.get("user_id"), nombre=session.get("user_nombre"),
            email=session.get("user_email"), rol=session.get("user_rol"),
            modulo="obras", descripcion=f"Creó obra: {f['nombre']}",
            objeto_tipo="obra", metodo="POST", ruta=request.path,
            user_agent=request.headers.get("User-Agent","")[:300],
        )
        return redirect(url_for("obras"))
    return render_template("obra_form.html", obra=None, user=user, accion="Nueva")

@app.route("/obras/<int:oid>/editar", methods=["GET","POST"])
@login_required
@permiso_requerido("obras", "editar")
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
            "id": oid, "nombre": f["nombre"], "numero_contrato": f.get("numero_contrato","").strip() or None,
            "descripcion": f.get("descripcion",""),
            "cliente": f.get("cliente",""),
            "ubicacion": f.get("ubicacion",""),
            "fecha_inicio": f.get("fecha_inicio") or None,
            "fecha_fin":    f.get("fecha_fin") or None,
            "estado":       f.get("estado","activa"),
            "link_drive":   f.get("link_drive","").strip() or None,
        })
        flash("Obra actualizada.", "success")
        db.registrar_actividad(
            accion="editar", ip=get_client_ip(),
            id_usuario=session.get("user_id"), nombre=session.get("user_nombre"),
            email=session.get("user_email"), rol=session.get("user_rol"),
            modulo="obras", descripcion=f"Editó obra id={oid}: {f['nombre']}",
            objeto_id=str(oid), objeto_tipo="obra",
            metodo="POST", ruta=request.path,
            user_agent=request.headers.get("User-Agent","")[:300],
        )
        return redirect(url_for("obra_detalle", oid=oid))
    return render_template("obra_form.html", obra=obra, user=user, accion="Editar")

@app.route("/obras/<int:oid>/archivar", methods=["POST"])
@login_required
@permiso_requerido("obras", "editar")
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
@permiso_requerido("obras", "editar")
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
@permiso_requerido("usuarios", "crear")
def usuario_nuevo():
    user = get_current_user()
    obras = db.get_obras()
    if request.method == "POST":
        f = request.form
        obra_asig = f.get("id_obra_asignada") or None
        try:
            db.crear_usuario(f["nombre"], f["email"], hash_pwd(f["password"]), f["rol"],
                             int(obra_asig) if obra_asig else None,
                             movil=f.get("movil") or None)
            flash("Usuario creado.", "success")
            db.registrar_actividad(
                accion="crear", ip=get_client_ip(),
                id_usuario=session.get("user_id"), nombre=session.get("user_nombre"),
                email=session.get("user_email"), rol=session.get("user_rol"),
                modulo="usuarios", descripcion=f"Creó usuario: {f['email']} rol={f['rol']}",
                objeto_tipo="usuario", metodo="POST", ruta=request.path,
                user_agent=request.headers.get("User-Agent","")[:300],
            )
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
                                  int(obra_asig) if obra_asig else None,
                                  movil=f.get("movil") or None)
        else:
            # Non-admin solo puede cambiar nombre, email, contraseña y móvil
            db.actualizar_usuario(uid, f["nombre"], f["email"], u["rol"], 1,
                                  u.get("id_obra_asignada"),
                                  movil=f.get("movil") or None)
        if f.get("password"):
            db.cambiar_password(uid, hash_pwd(f["password"]))
        flash("Usuario actualizado.", "success")
        db.registrar_actividad(
            accion="editar", ip=get_client_ip(),
            id_usuario=session.get("user_id"), nombre=session.get("user_nombre"),
            email=session.get("user_email"), rol=session.get("user_rol"),
            modulo="usuarios", descripcion=f"Editó usuario id={uid}",
            objeto_id=str(uid), objeto_tipo="usuario",
            metodo="POST", ruta=request.path,
            user_agent=request.headers.get("User-Agent","")[:300],
        )
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
            ["ECO","Serie","Equipo","Marca","Modelo","Fecha","Hrs trabajadas",
             "Hrs motor conectado","Hrs ralentí","Motor desconectado"],
            db.get_horas_export(fi, ff, lista))
        

    

    elif tabla == "utilizacion":
        ws = wb.active
        ws.title = "Utilización"
        escribir_hoja(ws,
            ["ECO","Serie","Equipo","Marca","Modelo","Fecha",
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
            ["ECO","Serie","Equipo","Marca","Modelo","Fecha","Hrs trab",
             "Hrs motor","Hrs ralentí","Motor desc"],
            db.get_horas_export(fi, ff, lista))

        ws = wb.create_sheet("Utilización")
        escribir_hoja(ws,
            ["ECO","Serie","Equipo","Marca","Modelo","Fecha",
             "Lts/Hr","Lts cons","Hrs máq","Hrs ralentí"],
            db.get_utilizacion_export(fi, ff, lista))

        # Combustible 360: ignora la selección de equipos, trae TODAS las
        # máquinas (diesel y gasolina) con registros en el período, ordenadas
        # por tipo (diesel primero) y luego por ECO y fecha.
        ws = wb.create_sheet("Combustible 360")
        # Filas de metadato con el rango de fechas del reporte
        FILL_META = PatternFill("solid", fgColor="0F3460")
        FONT_META = Font(bold=True, color="FFFFFF", size=11)
        ws.append([f"Fecha inicio (Desde):  {fi}", "", "", "", "", "", "", "", "", "", "", "", "", ""])
        for cell in ws[1]:
            cell.fill = FILL_META
            cell.font  = FONT_META
        ws.append([f"Fecha fin (Hasta):     {ff}", "", "", "", "", "", "", "", "", "", "", "", "", ""])
        for cell in ws[2]:
            cell.fill = FILL_META
            cell.font  = FONT_META
        ws.append([])  # fila vacía separadora
        escribir_hoja(ws,
            ["Tipo","ECO","Equipo","Marca","Obra","Fecha","Operador",
             "Lts cargados","Lts telemetría","Lts faltantes",
             "Desv %","Semáforo","Justif.","Obs"],
            db.get_combustible_export_completo(fi, ff),
            col_semaforo="semaforo")

    else:
        flash("Tabla no válida.", "danger")
        return redirect(url_for("exportar"))

    nombre_archivo = f"ESMA_{tabla}_{fi}_{ff}.xlsx"
    ruta = os.path.join(UPLOAD_FOLDER, nombre_archivo)
    wb.save(ruta)
    # ── Auditoría: exportar Excel ──
    db.registrar_actividad(
        accion="exportar",
        ip=get_client_ip(),
        id_usuario=session.get("user_id"),
        nombre=session.get("user_nombre"),
        email=session.get("user_email"),
        rol=session.get("user_rol"),
        modulo="exportar",
        descripcion=f"Exportó Excel tabla='{tabla}' equipos='{equipos}' rango={fi}/{ff}",
        metodo="GET", ruta=request.full_path,
        user_agent=request.headers.get("User-Agent","")[:300],
    )
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

    # =========================================================
    # NORMALIZAR FECHAS
    # =========================================================

    def normalizar_fecha(valor):

        if not valor:
            return valor

        valor = str(valor).strip()

        # Formato ISO: 2026-08-23
        try:
            return datetime.strptime(
                valor[:10],
                "%Y-%m-%d"
            ).strftime("%Y-%m-%d")
        except ValueError:
            pass

        # Formato: 23 - agosto - 2026
        meses = {
            "enero": 1,
            "febrero": 2,
            "marzo": 3,
            "abril": 4,
            "mayo": 5,
            "junio": 6,
            "julio": 7,
            "agosto": 8,
            "septiembre": 9,
            "setiembre": 9,
            "octubre": 10,
            "noviembre": 11,
            "diciembre": 12
        }

        try:

            partes = [
                p.strip()
                for p in valor.split("-")
            ]

            if len(partes) == 3:

                dia = int(partes[0])
                mes = meses[partes[1].lower()]
                anio = int(partes[2])

                return f"{anio:04d}-{mes:02d}-{dia:02d}"

        except Exception:
            pass

        return valor

    fi = normalizar_fecha(fi)
    ff = normalizar_fecha(ff)

    print("🔥 TENDENCIA FI:", repr(fi))
    print("🔥 TENDENCIA FF:", repr(ff))
    print("🔥 TENDENCIA ECO:", repr(eco))
    print("🔥 TENDENCIA OBRA:", repr(obra))

    obra = int(obra) if obra else None
    tipo_combustible = request.args.get("tipo_combustible", "") or None

    resultado = db.get_combustible_tendencia(
        fi,
        ff,
        obra=obra,
        eco=eco,
        tipo_combustible=tipo_combustible
    )

    print("🔥 TENDENCIA RESULTADO:", resultado)

    return jsonify(_jsonable(resultado))









@app.route("/api/nivel_combustible/<eco>")
@login_required
def api_nivel_combustible(eco):
    """Historial de nivel de combustible (%) para gráfica detallada."""
    fi = request.args.get("fecha_ini", "")
    ff = request.args.get("fecha_fin", "")
    datos = db.get_historial_nivel_combustible(eco, fi or None, ff or None)
    return jsonify(_jsonable(datos))


@app.route("/api/presupuesto/validar-tope")
@login_required
def api_validar_tope_presupuesto():
    """API para validar en tiempo real si una cantidad excede el tope presupuestado.
    Usado por el formulario de requisiciones para alertar antes de guardar."""
    id_obra = request.args.get("id_obra")
    id_codigo_costo = request.args.get("id_codigo_costo")
    cantidad = request.args.get("cantidad", "0")
    if not id_obra or not id_codigo_costo:
        return jsonify({"permitido": True, "excede": False, "mensaje": ""})
    try:
        resultado = db.validar_tope_presupuesto(int(id_obra), int(id_codigo_costo), float(cantidad))
        return jsonify(resultado)
    except Exception as e:
        return jsonify({"permitido": True, "excede": False, "mensaje": str(e)})


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
app.jinja_env.globals['logo2_path'] = '/uploads/gremial_2.png'

from flask import send_from_directory

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    # Buscar archivo en subcarpetas (orden de prioridad)
    for folder in [UPLOAD_FOLDER, DOCS_FOLDER, EQUIPOS_FOLDER, EMPLEADOS_FOLDER,
                   CHAT_FOLDER, ASISTENCIA_FOLDER, CFDI_FOLDER, COTIZACIONES_FOLDER]:
        if os.path.exists(os.path.join(folder, filename)):
            return send_from_directory(folder, filename)
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
@permiso_requerido("permisos", "editar")
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
@permiso_requerido("permisos", "crear")
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
@permiso_requerido("permisos", "eliminar")
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
    rol = session.get("user_rol", "cliente")
    # Admin ve todas las obras; los demás solo las que tienen asignadas
    if rol == "admin":
        obras = db.get_obras()
    else:
        obras_permitidas = db.get_obras_permitidas(user["id"], "requisiciones", "leer")
        if obras_permitidas:
            ids_permitidos = {op["id_obra"] for op in obras_permitidas}
            todas = db.get_obras()
            obras = [o for o in todas if o["id"] in ids_permitidos]
        else:
            # Si no tiene permisos por obra específicos, mostrar según obra asignada
            obra_asignada = session.get("user_obra_asignada")
            if obra_asignada and rol in db.ROLES_RESTRINGIDOS_A_OBRA:
                todas = db.get_obras()
                obras = [o for o in todas if o["id"] == int(obra_asignada)]
            else:
                obras = db.get_obras()
    obra_filtro = request.args.get("obra", "")
    empresa_filtro = request.args.get("empresa", "")
    estatus_filtro = request.args.get("estatus", "")
    reqs = db.get_requisiciones(
        id_obra=int(obra_filtro) if obra_filtro else None,
        empresa=empresa_filtro or None,
        estatus=estatus_filtro or None
    )
    # Para roles restringidos, filtrar requisiciones solo de sus obras
    if rol != "admin":
        ids_obras_visibles = {o["id"] for o in obras}
        if ids_obras_visibles:
            reqs = [r for r in reqs if r.get("id_obra") in ids_obras_visibles]
    kpis = db.get_kpis_requisiciones(int(obra_filtro) if obra_filtro else None)
    # Calcular disponible por requisición (desde presupuesto de la obra)
    for r in reqs:
        r["disponible"] = None
        if r.get("id_obra") and r.get("id_codigo_costo"):
            tope = db.validar_tope_presupuesto(r["id_obra"], r["id_codigo_costo"], 0)
            if tope.get("presupuestado"):
                r["disponible"] = tope.get("disponible")
        elif r.get("id_obra"):
            # Buscar código de costo de las partidas
            cc = db.query("SELECT id_codigo_costo FROM requisicion_partidas WHERE id_requisicion=%s AND id_codigo_costo IS NOT NULL LIMIT 1",
                          (r["id"],), one=True)
            if cc and cc["id_codigo_costo"]:
                tope = db.validar_tope_presupuesto(r["id_obra"], cc["id_codigo_costo"], 0)
                if tope.get("presupuestado"):
                    r["disponible"] = tope.get("disponible")
    # Verificar si puede importar: admin siempre, otros si tienen permiso de rol para crear requisiciones
    if rol == "admin":
        puede_importar = True
        puede_ver_presupuesto = True
    else:
        perms = db.get_permisos_rol(rol)
        puede_importar = bool(perms.get("requisiciones", {}).get("crear"))
        obras_presup = db.get_obras_permitidas(user["id"], "requisiciones_presupuesto", "leer")
        puede_ver_presupuesto = bool(obras_presup)
    return render_template("requisiciones.html", user=user, obras=obras,
                           requisiciones=reqs, kpis=kpis,
                           obra_filtro=obra_filtro, empresa_filtro=empresa_filtro,
                           estatus_filtro=estatus_filtro,
                           puede_importar=puede_importar,
                           puede_ver_presupuesto=puede_ver_presupuesto,
                           panel_partidas=db.get_partidas_por_obra(int(obra_filtro) if obra_filtro else None),
                           panel_nomina_imss=db.get_nomina_imss_por_obra(int(obra_filtro) if obra_filtro else None),
                           panel_nomina_sin=db.get_nomina_sin_imss_por_obra(int(obra_filtro) if obra_filtro else None),
                           panel_finiquitos=db.get_finiquitos_por_obra(int(obra_filtro) if obra_filtro else None),
                           panel_descansos=db.get_descansos_por_obra(int(obra_filtro) if obra_filtro else None),
                           comision_imss=db.get_config_comision_imss(),
                           comision_sin_imss=db.get_config_comision_sin_imss())

def _puede_autorizar_req(user, req):
    """True si el usuario puede autorizar montos en esta requisición.
    Pasa si: es admin, o tiene el módulo 'requisiciones_autorizar' asignado
    por obra para la obra de esta requisición (cualquier permiso basta)."""
    rol = session.get("user_rol", "cliente")
    if rol == "admin":
        return True
    id_obra = req.get("id_obra") if req else None
    if id_obra:
        row = db.query(
            "SELECT id FROM permisos_usuario_obra WHERE id_usuario=%s AND id_obra=%s AND modulo=%s LIMIT 1",
            (user["id"], int(id_obra), "requisiciones_autorizar"),
            one=True
        )
        if row:
            return True
    return False


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
    # Comparación con nómina del sistema (si la requisición tiene semana)
    nomina_sistema = []
    if req.get("semana") and req.get("id_obra"):
        nomina_sistema = db.get_nomina_semanal(req["semana"], req["id_obra"])
    elif req.get("semana"):
        nomina_sistema = db.get_nomina_semanal(req["semana"])
    # Catálogo de códigos de costo para el formulario de edición
    codigos_costo = db.get_codigos_costo() if hasattr(db, 'get_codigos_costo') else []
    # Comprobantes de pago adjuntos
    comprobantes_pago = db.get_comprobantes_requisicion(rid)
    # Info de tope de presupuesto (para mostrar disponible en el detalle)
    tope_info = None
    if req.get("id_obra") and partidas:
        # Buscar el código de costo predominante de las partidas
        cc_id = next((p["id_codigo_costo"] for p in partidas if p.get("id_codigo_costo")), None)
        if not cc_id and req.get("id_codigo_costo"):
            cc_id = req["id_codigo_costo"]
        if cc_id:
            _t = db.validar_tope_presupuesto(req["id_obra"], cc_id, 0)
            tope_info = _t if _t.get("presupuestado") is not None else None
    return render_template("requisicion_detalle.html", user=user, req=req,
                           partidas=partidas, nomina_imss=nomina_imss,
                           nomina_sin=nomina_sin, finiquitos=finiquitos,
                           descansos=descansos, nomina_sistema=nomina_sistema,
                           codigos_costo=codigos_costo,
                           comprobantes_pago=comprobantes_pago,
                           tope_info=tope_info,
                           partidas_pendientes_arrastre=db.get_partidas_pendientes_obra(
                               req["id_obra"], excluir_requisicion=rid) if req.get("id_obra") else [],
                           comision_imss=db.get_config_comision_imss(),
                           comision_sin_imss=db.get_config_comision_sin_imss(),
                           can_autorizar_req=_puede_autorizar_req(user, req))

@app.route("/requisiciones/<int:rid>/panel")
@login_required
@permiso_requerido("requisiciones", "leer")
def requisicion_panel(rid):
    """Fragmento de pestañas para cargarse inline en la lista de requisiciones."""
    req = db.get_requisicion(rid)
    if not req: abort(404)
    user = get_current_user()
    partidas = db.get_partidas_requisicion(rid)
    nomina_imss = db.get_nomina_imss_requisicion(rid)
    nomina_sin = db.get_nomina_sin_imss_requisicion(rid)
    finiquitos = db.get_finiquitos_requisicion(rid)
    descansos = db.get_descansos_requisicion(rid)
    nomina_sistema = []
    if req.get("semana") and req.get("id_obra"):
        nomina_sistema = db.get_nomina_semanal(req["semana"], req["id_obra"])
    elif req.get("semana"):
        nomina_sistema = db.get_nomina_semanal(req["semana"])
    codigos_costo = db.get_codigos_costo() if hasattr(db, 'get_codigos_costo') else []
    tope_info = None
    if req.get("id_obra") and partidas:
        cc_id = next((p["id_codigo_costo"] for p in partidas if p.get("id_codigo_costo")), None)
        if not cc_id and req.get("id_codigo_costo"):
            cc_id = req["id_codigo_costo"]
        if cc_id:
            _t = db.validar_tope_presupuesto(req["id_obra"], cc_id, 0)
            tope_info = _t if _t.get("presupuestado") is not None else None
    return render_template("requisicion_panel.html", user=user, req=req,
                           partidas=partidas, nomina_imss=nomina_imss,
                           nomina_sin=nomina_sin, finiquitos=finiquitos,
                           descansos=descansos, nomina_sistema=nomina_sistema,
                           codigos_costo=codigos_costo,
                           tope_info=tope_info,
                           comision_imss=db.get_config_comision_imss(),
                           comision_sin_imss=db.get_config_comision_sin_imss())

@app.route("/requisiciones/<int:rid>/aprobar", methods=["POST"])
@login_required
@permiso_requerido("requisiciones", "editar")
def requisicion_aprobar(rid):
    user = get_current_user()
    f = request.form
    # Capturar montos autorizados por partida (si se enviaron)
    montos_autorizados = {}
    for key, val in f.items():
        if key.startswith("monto_autorizado_") and val:
            pid = int(key.replace("monto_autorizado_", ""))
            montos_autorizados[pid] = float(val)
    # Monto total autorizado manual (si se proporcionó)
    total_autorizado_manual = f.get("total_autorizado_manual")
    db.aprobar_requisicion(rid, user["id"], montos_autorizados=montos_autorizados or None)
    # Si hay un monto total autorizado manual, sobreescribir
    if total_autorizado_manual:
        db.execute("UPDATE requisiciones SET total_autorizado=%s WHERE id=%s",
                   (float(total_autorizado_manual), rid))
    flash("Requisición aprobada con montos autorizados.", "success")
    return redirect(url_for("requisicion_detalle", rid=rid))

@app.route("/requisiciones/<int:rid>/editar_autorizado", methods=["POST"])
@login_required
@permiso_requerido("requisiciones", "editar")
def requisicion_editar_autorizado(rid):
    """Edita el monto total autorizado directamente desde la cabecera."""
    total = float(request.form.get("total_autorizado") or 0)
    db.execute("UPDATE requisiciones SET total_autorizado=%s WHERE id=%s", (total, rid))
    flash("Monto autorizado actualizado.", "success")
    return redirect(url_for("requisicion_detalle", rid=rid))

@app.route("/requisiciones/<int:rid>/autorizar_montos", methods=["POST"])
@login_required
def requisicion_autorizar_montos(rid):
    """Permite editar manualmente los montos autorizados por partida sin cambiar estatus."""
    user = get_current_user()
    req = db.get_requisicion(rid)
    if not req:
        abort(404)
    if not _puede_autorizar_req(user, req):
        flash("No tienes permiso para autorizar montos en esta requisición.", "danger")
        return redirect(url_for("requisicion_detalle", rid=rid))
    f = request.form
    for key, val in f.items():
        if key.startswith("monto_autorizado_") and val:
            pid = int(key.replace("monto_autorizado_", ""))
            db.execute("UPDATE requisicion_partidas SET monto_autorizado=%s WHERE id=%s",
                       (float(val), pid))
    # Monto total manual
    total_manual = f.get("total_autorizado_manual", "").strip()
    if total_manual and float(total_manual) > 0:
        db.execute("UPDATE requisiciones SET total_autorizado=%s WHERE id=%s",
                   (float(total_manual), rid))
        # Recalcular solo total_solicitado y cantidades, sin tocar total_autorizado
        db._recalcular_solo_solicitado(rid)
    else:
        # Sin total manual: recalcular todo desde las partidas normalmente
        db._recalcular_totales_requisicion(rid)
    flash("Montos autorizados actualizados.", "success")
    return redirect(url_for("requisicion_detalle", rid=rid))


@app.route("/requisiciones/<int:rid>/comprobantes", methods=["POST"])
@login_required
@permiso_requerido("requisiciones", "editar")
def requisicion_subir_comprobantes(rid):
    """Sube comprobantes de pago a una requisición."""
    archivos = request.files.getlist("comprobantes")
    EXTENSIONES_PERMITIDAS = {'.pdf', '.xml', '.xlsx', '.xls', '.png', '.jpg', '.jpeg'}
    subidos = 0
    for archivo in archivos:
        if archivo and archivo.filename:
            ext = os.path.splitext(archivo.filename)[1].lower()
            if ext not in EXTENSIONES_PERMITIDAS:
                continue
            import time as _t
            nombre_disco = f"req_{rid}_comp_{int(_t.time())}_{archivo.filename}"
            archivo.save(os.path.join(PROVEEDORES_FOLDER, nombre_disco))
            db.guardar_comprobante_requisicion(rid, nombre_disco, archivo.filename, ext, session["user_id"])
            subidos += 1
    if subidos:
        flash(f"{subidos} comprobante(s) subido(s).", "success")
    else:
        flash("No se subieron comprobantes (formato no válido o vacío).", "danger")
    return redirect(url_for("requisicion_detalle", rid=rid))


@app.route("/requisiciones/comprobante/<int:comp_id>/ver")
@login_required
@permiso_requerido("requisiciones", "leer")
def requisicion_comprobante_ver(comp_id):
    """Visualiza un comprobante de pago."""
    comp = db.get_comprobante_requisicion(comp_id)
    if not comp:
        abort(404)
    ruta = os.path.join(PROVEEDORES_FOLDER, comp["nombre_archivo"])
    if not os.path.exists(ruta):
        abort(404)
    return send_file(ruta, as_attachment=False, download_name=comp["nombre_original"])


@app.route("/requisiciones/comprobante/<int:comp_id>/eliminar", methods=["POST"])
@login_required
@permiso_requerido("requisiciones", "editar")
def requisicion_comprobante_eliminar(comp_id):
    """Elimina un comprobante de pago."""
    comp = db.eliminar_comprobante_requisicion(comp_id)
    if comp:
        ruta = os.path.join(PROVEEDORES_FOLDER, comp["nombre_archivo"])
        if os.path.exists(ruta):
            os.remove(ruta)
        flash("Comprobante eliminado.", "success")
        return redirect(url_for("requisicion_detalle", rid=comp["id_requisicion"]))
    abort(404)


@app.route("/requisiciones/<int:rid>/partida/<int:pid>/asignar-codigo", methods=["POST"])
@login_required
@permiso_requerido("requisiciones", "editar")
def requisicion_asignar_codigo_costo(rid, pid):
    """Asigna un código de costo a una partida. Solo funciona si aún no tiene uno asignado."""
    id_codigo = request.form.get("id_codigo_costo")
    if not id_codigo:
        flash("Selecciona un código de costo.", "danger")
        return redirect(url_for("requisicion_detalle", rid=rid))
    # Verificar que la partida no tenga ya un código asignado
    partida = db.query("SELECT id_codigo_costo FROM requisicion_partidas WHERE id=%s", (pid,), one=True)
    if partida and partida.get("id_codigo_costo"):
        flash("Esta partida ya tiene un código de costo asignado.", "warning")
        return redirect(url_for("requisicion_detalle", rid=rid))
    db.execute("UPDATE requisicion_partidas SET id_codigo_costo=%s WHERE id=%s", (int(id_codigo), pid))
    flash("Código de costo asignado.", "success")
    return redirect(url_for("requisicion_detalle", rid=rid))



# ══════════════════════════════════════════════════════════════════
#  PAGO DE PARTIDAS: marcar pagado + adjuntar factura por partida
# ══════════════════════════════════════════════════════════════════

@app.route("/requisiciones/<int:rid>/partida/<int:pid>/pago", methods=["POST"])
@login_required
@permiso_requerido("requisiciones", "editar")
def requisicion_pago_partida(rid, pid):
    """Actualiza el estatus de pago de una partida individual.
    Opcionalmente sube la factura (archivo + folio)."""
    f = request.form
    estatus = f.get("estatus_pago", "pendiente")
    if estatus not in ("pendiente", "pagado", "cancelado"):
        estatus = "pendiente"

    fecha_pago = f.get("fecha_pago") or None
    no_factura = (f.get("no_factura") or "").strip() or None

    # Manejo de archivo de factura (opcional)
    factura_nombre = None
    factura_archivo = None
    archivo = request.files.get("factura_archivo")
    if archivo and archivo.filename:
        import time as _t
        ext = os.path.splitext(archivo.filename)[1].lower()
        EXTS_OK = {".pdf", ".xml", ".jpg", ".jpeg", ".png", ".xlsx"}
        if ext in EXTS_OK:
            factura_nombre = archivo.filename
            factura_archivo = f"fact_part_{pid}_{int(_t.time())}{ext}"
            archivo.save(os.path.join(PROVEEDORES_FOLDER, factura_archivo))
        else:
            flash("Formato de factura no válido (PDF, XML, JPG, PNG, XLSX).", "warning")

    db.actualizar_pago_partida(
        pid,
        estatus_pago=estatus,
        fecha_pago=fecha_pago,
        no_factura=no_factura,
        factura_nombre=factura_nombre,
        factura_archivo=factura_archivo,
    )
    flash("Pago actualizado.", "success")
    return redirect(url_for("requisicion_detalle", rid=rid))


@app.route("/requisiciones/partida/<int:pid>/factura/ver")
@login_required
@permiso_requerido("requisiciones", "leer")
def requisicion_partida_factura_ver(pid):
    """Descarga / visualiza la factura adjunta a una partida."""
    p = db.query("SELECT factura_archivo, factura_nombre FROM requisicion_partidas WHERE id=%s",
                 (pid,), one=True)
    if not p or not p.get("factura_archivo"):
        abort(404)
    ruta = os.path.join(PROVEEDORES_FOLDER, p["factura_archivo"])
    if not os.path.exists(ruta):
        abort(404)
    return send_from_directory(PROVEEDORES_FOLDER, p["factura_archivo"],
                               as_attachment=False,
                               download_name=p["factura_nombre"] or p["factura_archivo"])


# ── API: partidas pendientes de obra (para propuesta de arrastre) ──

@app.route("/api/partidas-pendientes-obra")
@login_required
@permiso_requerido("requisiciones", "leer")
def api_partidas_pendientes_obra():
    """Devuelve JSON con partidas pendientes de pago de una obra,
    para mostrar la propuesta de arrastre al crear nueva requisición."""
    id_obra = request.args.get("id_obra", type=int)
    excluir = request.args.get("excluir_req", type=int)
    if not id_obra:
        return {"partidas": []}
    partidas = db.get_partidas_pendientes_obra(id_obra, excluir_requisicion=excluir)
    # Serializar campos de fecha para JSON
    resultado = []
    for p in (partidas or []):
        row = dict(p)
        for k, v in row.items():
            if hasattr(v, "isoformat"):
                row[k] = v.isoformat()
        resultado.append(row)
    return {"partidas": resultado}


@app.route("/requisiciones/<int:rid>/arrastrar-partidas", methods=["POST"])
@login_required
@permiso_requerido("requisiciones", "editar")
def requisicion_arrastrar_partidas(rid):
    """Copia las partidas pendientes seleccionadas a esta requisición como arrastre."""
    ids_seleccionados = request.form.getlist("partida_ids[]")
    if not ids_seleccionados:
        flash("Ninguna partida seleccionada para arrastrar.", "warning")
        return redirect(url_for("requisicion_detalle", rid=rid))

    req = db.get_requisicion(rid)
    if not req:
        abort(404)

    copiadas = 0
    for pid_str in ids_seleccionados:
        try:
            pid_orig = int(pid_str)
        except ValueError:
            continue
        p_orig = db.query("""
            SELECT p.*, r.semana AS semana_orig
            FROM requisicion_partidas p
            JOIN requisiciones r ON r.id = p.id_requisicion
            WHERE p.id = %s
        """, (pid_orig,), one=True)
        if not p_orig:
            continue
        db.crear_partida_requisicion({
            "id_requisicion":    rid,
            "id_codigo_costo":   p_orig["id_codigo_costo"],
            "categoria":         p_orig["categoria"],
            "proveedor":         p_orig["proveedor"],
            "contacto_proveedor": p_orig["contacto_proveedor"],
            "concepto":          p_orig["concepto"],
            "periodo":           p_orig["periodo"],
            "monto_solicitado":  p_orig["monto_solicitado"],
            "monto_autorizado":  0,
            "observaciones":     p_orig["observaciones"],
            "cantidad":          p_orig.get("cantidad"),
            "unidad":            p_orig.get("unidad"),
            "estatus_pago":      "pendiente",
            "id_partida_origen": pid_orig,
            "semana_origen":     p_orig.get("semana_orig"),
        })
        copiadas += 1

    db._recalcular_totales_requisicion(rid)
    flash(f"{copiadas} partida(s) arrastrada(s) desde semanas anteriores.", "success")
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

def requisicion_enviar(rid):
    db.enviar_requisicion(rid)
    flash("Requisición enviada a tesorería.", "success")
    return redirect(url_for("requisicion_detalle", rid=rid))


@app.route("/requisiciones/<int:rid>/firmas", methods=["POST"])
@login_required
@permiso_requerido("requisiciones", "editar")
def requisicion_editar_firmas(rid):
    """Edita los nombres y puestos de las firmas de una requisición."""
    f = request.form
    db.actualizar_firmas_requisicion(
        rid,
        solicito_nombre=f.get("solicito_nombre") or None,
        solicito_puesto=f.get("solicito_puesto") or None,
        reviso_nombre=f.get("reviso_nombre") or None,
        reviso_puesto=f.get("reviso_puesto") or None,
        autorizo_nombre=f.get("autorizo_nombre") or None,
        autorizo_puesto=f.get("autorizo_puesto") or None,
    )
    flash("Firmas actualizadas.", "success")
    return redirect(url_for("requisicion_detalle", rid=rid))


@app.route("/requisiciones/<int:rid>/sincronizar-nomina", methods=["POST"])
@login_required
@permiso_requerido("requisiciones", "editar")
def requisicion_sincronizar_nomina(rid):
    """Sincroniza la nómina de esta requisición (IMSS y sin IMSS) hacia la tabla
    de nómina de RRHH, vinculando empleados por id o por nombre."""
    sincronizados, omitidos = db.sync_requisicion_a_nomina(rid)
    if sincronizados > 0:
        flash(f"Nómina sincronizada: {sincronizados} registros enviados a RRHH.", "success")
    if omitidos > 0:
        flash(f"{omitidos} registros omitidos (sin empleado vinculado). Asigna el empleado en la tabla de nómina IMSS/Sin IMSS.", "danger")
    if sincronizados == 0 and omitidos == 0:
        flash("No hay registros de nómina en esta requisición para sincronizar.", "danger")
    return redirect(url_for("requisicion_detalle", rid=rid))

# ── Crear/eliminar nómina IMSS manualmente ──
@app.route("/requisiciones/<int:rid>/nomina-imss/agregar", methods=["POST"])
@login_required
@permiso_requerido("requisiciones", "editar")
def requisicion_agregar_nomina_imss(rid):
    """Agrega un registro de nómina IMSS manualmente."""
    f = request.form
    req = db.get_requisicion(rid)
    datos = {
        "id_requisicion": rid,
        "id_obra": req["id_obra"] if req else None,
        "id_empleado": None,
        "nombre_empleado": (f.get("nombre_empleado") or "").strip(),
        "puesto": f.get("puesto") or None,
        "categoria_personal": f.get("categoria_personal") or None,
        "fecha_ingreso": f.get("fecha_ingreso") or None,
        "dias": int(f.get("dias") or 0),
        "salario_diario": float(f.get("salario_diario") or 0),
        "salario_proporcional": float(f.get("salario_proporcional") or 0),
        "salario_semanal": float(f.get("salario_semanal") or 0),
        "horas_extra": float(f.get("horas_extra") or 0),
        "costo_horas_extra": float(f.get("costo_horas_extra") or 0),
        "descanso_pagado": float(f.get("descanso_pagado") or 0),
        "compensacion": float(f.get("compensacion") or 0),
        "pago_tiempo_extra": float(f.get("pago_tiempo_extra") or 0),
        "comidas": float(f.get("comidas") or 0),
        "total_real": float(f.get("total_real") or 0),
        "observaciones": f.get("observaciones") or None,
    }
    if not datos["nombre_empleado"]:
        flash("El nombre del trabajador es obligatorio.", "danger")
        return redirect(url_for("requisicion_detalle", rid=rid))
    db.crear_nomina_imss(datos)
    db._recalcular_totales_requisicion(rid)
    flash("Registro de nómina IMSS agregado.", "success")
    return redirect(url_for("requisicion_detalle", rid=rid))


@app.route("/requisiciones/<int:rid>/partidas/<int:pid>/eliminar", methods=["POST"])
@login_required
@permiso_requerido("requisiciones", "editar")
def requisicion_eliminar_partida(rid, pid):
    """Elimina una partida de gasto de la requisición."""
    db.execute("DELETE FROM requisicion_partidas WHERE id=%s AND id_requisicion=%s", (pid, rid))
    db._recalcular_totales_requisicion(rid)
    flash("Partida eliminada.", "success")
    return redirect(url_for("requisicion_detalle", rid=rid))


@app.route("/requisiciones/<int:rid>/nomina-imss/<int:nid>/eliminar", methods=["POST"])
@login_required
@permiso_requerido("requisiciones", "editar")
def requisicion_eliminar_nomina_imss(rid, nid):
    """Elimina un registro de nómina IMSS."""
    db.execute("DELETE FROM nomina_imss WHERE id=%s AND id_requisicion=%s", (nid, rid))
    db._recalcular_totales_requisicion(rid)
    flash("Registro eliminado.", "success")
    return redirect(url_for("requisicion_detalle", rid=rid))


# ── Crear/eliminar nómina Sin IMSS manualmente ──
@app.route("/requisiciones/<int:rid>/nomina-sin-imss/agregar", methods=["POST"])
@login_required
@permiso_requerido("requisiciones", "editar")
def requisicion_agregar_nomina_sin_imss(rid):
    """Agrega un registro de nómina Sin IMSS manualmente."""
    f = request.form
    req = db.get_requisicion(rid)
    datos = {
        "id_requisicion": rid,
        "id_obra": req["id_obra"] if req else None,
        "id_empleado": None,
        "nombre_empleado": (f.get("nombre_empleado") or "").strip(),
        "puesto": f.get("puesto") or None,
        "dias": int(f.get("dias") or 0),
        "salario_diario": float(f.get("salario_diario") or 0),
        "salario_proporcional": float(f.get("salario_proporcional") or 0),
        "salario_semanal": float(f.get("salario_semanal") or 0),
        "horas_extra": float(f.get("horas_extra") or 0),
        "costo_horas_extra": float(f.get("costo_horas_extra") or 0),
        "compensacion": float(f.get("compensacion") or 0),
        "pago_tiempo_extra": float(f.get("pago_tiempo_extra") or 0),
        "comidas": float(f.get("comidas") or 0),
        "total_real": float(f.get("total_real") or 0),
        "observaciones": f.get("observaciones") or None,
    }
    if not datos["nombre_empleado"]:
        flash("El nombre del trabajador es obligatorio.", "danger")
        return redirect(url_for("requisicion_detalle", rid=rid))
    db.crear_nomina_sin_imss(datos)
    db._recalcular_totales_requisicion(rid)
    flash("Registro de nómina Sin IMSS agregado.", "success")
    return redirect(url_for("requisicion_detalle", rid=rid))


@app.route("/requisiciones/<int:rid>/nomina-sin-imss/<int:nid>/eliminar", methods=["POST"])
@login_required
@permiso_requerido("requisiciones", "editar")
def requisicion_eliminar_nomina_sin_imss(rid, nid):
    """Elimina un registro de nómina Sin IMSS."""
    db.execute("DELETE FROM nomina_sin_imss WHERE id=%s AND id_requisicion=%s", (nid, rid))
    db._recalcular_totales_requisicion(rid)
    flash("Registro eliminado.", "success")
    return redirect(url_for("requisicion_detalle", rid=rid))


# ── Crear/eliminar Finiquitos manualmente ──
@app.route("/requisiciones/<int:rid>/finiquitos/agregar", methods=["POST"])
@login_required
@permiso_requerido("requisiciones", "editar")
def requisicion_agregar_finiquito(rid):
    f = request.form
    nombre = (f.get("nombre_empleado") or "").strip()
    costo = float(f.get("costo_empresa") or 0)
    if not nombre:
        flash("El nombre del empleado es obligatorio.", "danger")
        return redirect(url_for("requisicion_detalle", rid=rid))
    db.crear_finiquito({
        "id_requisicion": rid,
        "id_obra": None,
        "id_empleado": None,
        "nombre_empleado": nombre,
        "costo_empresa": costo,
    })
    db._recalcular_totales_requisicion(rid)
    flash("Finiquito agregado.", "success")
    return redirect(url_for("requisicion_detalle", rid=rid))


@app.route("/requisiciones/<int:rid>/finiquitos/<int:fid>/eliminar", methods=["POST"])
@login_required
@permiso_requerido("requisiciones", "editar")
def requisicion_eliminar_finiquito(rid, fid):
    db.execute("DELETE FROM finiquitos WHERE id=%s AND id_requisicion=%s", (fid, rid))
    db._recalcular_totales_requisicion(rid)
    flash("Finiquito eliminado.", "success")
    return redirect(url_for("requisicion_detalle", rid=rid))


# ── Crear/eliminar Descansos manualmente ──
@app.route("/requisiciones/<int:rid>/descansos/agregar", methods=["POST"])
@login_required
@permiso_requerido("requisiciones", "editar")
def requisicion_agregar_descanso(rid):
    f = request.form
    nombre = (f.get("nombre") or "").strip()
    if not nombre:
        flash("El nombre es obligatorio.", "danger")
        return redirect(url_for("requisicion_detalle", rid=rid))
    db.crear_descanso({
        "id_requisicion": rid,
        "nombre": nombre,
        "puesto": f.get("puesto") or None,
        "origen": f.get("origen") or None,
        "fecha_alta": f.get("fecha_alta") or None,
        "sueldo": float(f.get("sueldo") or 0),
        "descanso_1": f.get("descanso_1") or None,
        "descanso_2": f.get("descanso_2") or None,
        "descanso_3": f.get("descanso_3") or None,
        "descanso_4": f.get("descanso_4") or None,
        "descanso_5": f.get("descanso_5") or None,
    })
    flash("Descanso agregado.", "success")
    return redirect(url_for("requisicion_detalle", rid=rid))


@app.route("/requisiciones/<int:rid>/descansos/<int:did>/eliminar", methods=["POST"])
@login_required
@permiso_requerido("requisiciones", "editar")
def requisicion_eliminar_descanso(rid, did):
    db.execute("DELETE FROM requisicion_descansos WHERE id=%s AND id_requisicion=%s", (did, rid))
    flash("Descanso eliminado.", "success")
    return redirect(url_for("requisicion_detalle", rid=rid))


@app.route("/requisiciones/config-comisiones", methods=["GET", "POST"])
@login_required
@permiso_requerido("comisiones_config", "editar")
def requisiciones_config_comisiones():
    """Permite modificar los porcentajes de comisión de nómina."""
    user = get_current_user()
    if request.method == "POST":
        imss = float(request.form.get("comision_imss") or 42)
        sin_imss = float(request.form.get("comision_sin_imss") or 30)
        db.set_config_comision("comision_imss", imss)
        db.set_config_comision("comision_sin_imss", sin_imss)
        flash(f"Comisiones actualizadas: IMSS {imss}%, Sin IMSS {sin_imss}%", "success")
        return redirect(url_for("requisiciones_config_comisiones"))
    return render_template("requisiciones_config_comisiones.html", user=user,
                           comision_imss=db.get_config_comision_imss(),
                           comision_sin_imss=db.get_config_comision_sin_imss())


@app.route("/requisiciones/nueva", methods=["GET", "POST"])
@login_required
def requisicion_nueva():
    """Crear una requisicion semanal de forma manual."""
    user = get_current_user()
    obras = db.get_obras()
    if request.method == "GET":
        id_obra_pre = request.args.get("obra", type=int)
        partidas_pendientes_pre = []
        if id_obra_pre:
            partidas_pendientes_pre = db.get_partidas_pendientes_obra(id_obra_pre)
        return render_template("requisicion_form.html", user=user, obras=obras,
                               categorias=db.CATEGORIAS_REQUISICION,
                               codigos_costo=db.get_codigos_costo(),
                               id_obra_pre=id_obra_pre,
                               partidas_pendientes_pre=partidas_pendientes_pre)
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
        "residente": f.get("residente") or (
            f"{user['nombre']} · {db.get_roles_labels().get(user.get('rol', ''), user.get('rol', ''))}"
            if user else None
        ),
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
    codigos_costo_list = f.getlist("part_codigo_costo[]")
    cantidades_list = f.getlist("part_cantidad[]")
    unidades_list = f.getlist("part_unidad[]")

    # Si la partida no tiene código de costo, heredar el de la cabecera
    cc_cabecera = int(f["id_codigo_costo"]) if f.get("id_codigo_costo") else None
    for i in range(len(codigos_costo_list)):
        if not codigos_costo_list[i] and cc_cabecera:
            codigos_costo_list[i] = str(cc_cabecera)

    # Validar topes de presupuesto (Opción B: Bloqueo duro — NO permite guardar si rebasa)
    id_obra_req = int(f.get("id_obra")) if f.get("id_obra") else None
    errores_tope = []
    for i, concepto in enumerate(conceptos_list):
        cc_id = int(codigos_costo_list[i]) if i < len(codigos_costo_list) and codigos_costo_list[i] else None
        cantidad = float(cantidades_list[i]) if i < len(cantidades_list) and cantidades_list[i] else None
        if id_obra_req and cc_id and cantidad:
            validacion = db.validar_tope_presupuesto(id_obra_req, cc_id, cantidad)
            if validacion.get("excede"):
                errores_tope.append(validacion["mensaje"])

    if errores_tope:
        flash("🚫 BLOQUEADO: " + " | ".join(errores_tope), "danger")
        return render_template("requisicion_form.html", user=user, obras=obras,
                               categorias=db.CATEGORIAS_REQUISICION, codigos_costo=db.get_codigos_costo())

    for i, concepto in enumerate(conceptos_list):
        cat = categorias_list[i] if i < len(categorias_list) else "Otros"
        prov = proveedores_list[i] if i < len(proveedores_list) else ""
        monto = float(montos_list[i]) if i < len(montos_list) and montos_list[i] else 0
        cc_id = int(codigos_costo_list[i]) if i < len(codigos_costo_list) and codigos_costo_list[i] else None
        cantidad = float(cantidades_list[i]) if i < len(cantidades_list) and cantidades_list[i] else None
        unidad = unidades_list[i] if i < len(unidades_list) and unidades_list[i] else None
        if not concepto.strip() and monto <= 0:
            continue
        db.crear_partida_requisicion({
            "id_requisicion": req_id,
            "id_codigo_costo": cc_id,
            "categoria": cat,
            "proveedor": prov.strip() or None,
            "contacto_proveedor": None,
            "concepto": concepto.strip() or None,
            "periodo": None,
            "monto_solicitado": monto,
            "monto_autorizado": 0,
            "observaciones": None,
            "cantidad": cantidad,
            "unidad": unidad,
        })

    db._recalcular_totales_requisicion(req_id)
    flash("Requisicion creada exitosamente.", "success")
    return redirect(url_for("requisicion_detalle", rid=req_id))


@app.route("/requisiciones/importar", methods=["GET", "POST"])
@login_required

def requisicion_importar():
    """Importa requerimiento semanal completo desde Excel formato ESMA-GREMIAL.
    Parsea hojas: REQ, C-IMSS, S-IMSS, FINIQ."""
    user = get_current_user()
    if user.get("rol") == "admin":
        obras = db.get_obras()
    else:
       
        obras_raw = db.get_obras_permitidas(user["id"], "requisiciones", "crear")
        obras = [{"id": o["id_obra"], "nombre": o["obra_nombre"]} for o in obras_raw]

    if request.method == "GET":
        return render_template("requisicion_importar.html", user=user, obras=obras)

    from openpyxl import load_workbook
    import re

    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        flash("Selecciona un archivo Excel.", "danger")
        return redirect(url_for("requisicion_importar"))

    id_obra_form = request.form.get("id_obra") or None
    if not id_obra_form:
        flash("Debes seleccionar una obra antes de importar.", "danger")
        return redirect(url_for("requisicion_importar"))

    try:
        wb = load_workbook(archivo, data_only=True)
    except Exception as e:
        flash(f"Error al leer el archivo: {e}", "danger")
        return redirect(url_for("requisicion_importar"))

    hojas = {ws.title.upper().strip(): ws for ws in wb.worksheets}
    resultados = []
    req_ids_creados = []  # Para rollback completo si alguna hoja falla

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
            # Si ya es número, retornar directo
            if isinstance(val, (int, float)):
                return float(val)
            s = str(val).replace("$", "").replace(" ", "").strip()
            if s in ("", "-", "- 0", "-0", "—"): return 0.0
            # Detectar formato europeo: punto como miles, coma como decimal
            # Ej: "6.000,00" → 6000.00  vs  formato americano "6,000.00" → 6000.00
            if "," in s and "." in s:
                # Si la coma viene después del punto → formato europeo (6.000,00)
                if s.rfind(",") > s.rfind("."):
                    s = s.replace(".", "").replace(",", ".")
                else:
                    # Formato americano (6,000.00)
                    s = s.replace(",", "")
            elif "," in s:
                # Solo coma: podría ser decimal europeo (6,5) o miles (6,000)
                partes = s.split(",")
                if len(partes) == 2 and len(partes[1]) <= 2:
                    # Es decimal: "6,50" → 6.50
                    s = s.replace(",", ".")
                else:
                    # Es miles: "6,000" → 6000
                    s = s.replace(",", "")
            return float(s)
        except (ValueError, TypeError):
            return 0.0

    def _parse_fecha(val):
        """Convierte cualquier formato de fecha a YYYY-MM-DD o None si no es válido."""
        if not val:
            return None
        # Si ya es objeto date/datetime de Python (openpyxl lo devuelve así)
        if hasattr(val, 'strftime'):
            return val.strftime('%Y-%m-%d')
        s = str(val).strip()[:15]
        if not s or s in ('-', '—', 'None'):
            return None
        import re as _re
        from datetime import date as _date
        # Formato ISO: YYYY-MM-DD
        if _re.match(r'^\d{4}-\d{2}-\d{2}$', s):
            return s
        # Formatos con separador / o -
        # Puede ser M/D/YYYY, MM/DD/YYYY, D/M/YYYY, DD/MM/YYYY, M/D/YY
        m = _re.match(r'^(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})$', s)
        if m:
            a, b, c = int(m.group(1)), int(m.group(2)), int(m.group(3))
            anio = c if c > 99 else (2000 + c)
            # Intentar M/D/YYYY (mes primero, como en Excel americano)
            for mes, dia in [(a, b), (b, a)]:
                if 1 <= mes <= 12 and 1 <= dia <= 31:
                    try:
                        _date(anio, mes, dia)
                        return f"{anio:04d}-{mes:02d}-{dia:02d}"
                    except ValueError:
                        continue
        return None


    for empresa_key, hoja_name in [("ESMA", "REQ ESMA"), ("GREMIAL", "REQ GREMIAL")]:
        ws = hojas.get(hoja_name.upper())
        if not ws:
            continue
        # Verificar que la hoja tenga partidas reales con proveedor/concepto específico,
        # no solo filas de encabezado de categoría (ADMINISTRACION, MAQUINARIA, etc.)
        _categorias_excluir = {"ADMINISTRACION", "MAQUINARIA", "MATERIALES", "SERVICIOS",
                               "OTROS", "OTROS (DESCRIBIR)", "COMISIONES", "FINIQUITOS",
                               "MANEJO Y ADMINISTRACION DE RECURSOS", "TOTAL:", "TOTAL"}
        tiene_datos = False
        _gremial_debug = []
        for _chk_row in ws.iter_rows(min_row=8, values_only=True):
            if not _chk_row or len(_chk_row) < 4:
                continue
            _vals = [str(c)[:25] if c is not None else "" for c in _chk_row]
            if any(v for v in _vals if v) and len(_gremial_debug) < 10:
                _gremial_debug.append("[" + "|".join(_vals) + "]")
            col_prov = 2 if empresa_key == "ESMA" else 0
            col_monto = 5 if empresa_key == "ESMA" else 3
            prov_val = str(_chk_row[col_prov] or "").strip() if len(_chk_row) > col_prov else ""
            monto_val = _chk_row[col_monto] if len(_chk_row) > col_monto else None
            # Excluir filas de categoría/encabezado y plantillas vacías
            prov_upper = prov_val.upper().split("(")[0].strip()
            if not prov_val or len(prov_val) <= 3:
                continue
            if prov_upper in _categorias_excluir:
                continue
            if "XXXXXX" in prov_val.upper() or "SELECCIONAR" in prov_val.upper():
                continue
            # Es una partida real si tiene proveedor Y monto numérico > 0
            if isinstance(monto_val, (int, float)) and monto_val > 0:
                tiene_datos = True
                break
        #flash(f"🔎 {empresa_key} tiene_datos={tiene_datos} | " + "  //  ".join(_gremial_debug[:6]), "info")
        if not tiene_datos:
            continue  # Hoja sin partidas reales, ignorar
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
        req_ids_creados.append(req_id)  # Registro para rollback completo

        # Parsear partidas: buscar filas con categorías y montos
        categoria_actual = "Otros"
        categorias_map = {"ADMINISTRACION": "Administración",
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

        # ── Detectar layout de columnas ──────────────────────────────────
        # Formato ESMA (8 cols): DESCRIPCION | CODIGO | PROVEEDOR | CONCEPTO | (vacio) | SOLICITADO | AUTORIZADO | TOTAL
        # Formato GREMIAL (6 cols): PROVEEDOR | CONCEPTO | (vacio) | SOLICITADO | AUTORIZADO | TOTAL
        tiene_cols_desc_codigo = False
        fila_datos_inicio = 8  # fila desde donde empezar a leer partidas
        for hdr_row in ws.iter_rows(min_row=1, max_row=20, values_only=True):
            if not hdr_row:
                continue
            fila_str = " ".join(str(c or "").upper() for c in hdr_row)
            if "DESCRIPCI" in fila_str and "CODIGO" in fila_str:
                tiene_cols_desc_codigo = True
                break
            if "PROVEEDOR" in fila_str and "CONCEPTO" in fila_str and "SOLICITADO" in fila_str:
                # header encontrado, determinar tipo por presencia de CODIGO
                if "CODIGO" in fila_str:
                    tiene_cols_desc_codigo = True
                break

        # Cache de lookup codigo -> id para no repetir queries por fila
        _cache_cc = {}

        def _resolver_cc(cod):
            if not cod:
                return None
            cod = str(cod).strip()
            if not cod:
                return None
            if cod in _cache_cc:
                return _cache_cc[cod]
            row_cc = db.query("SELECT id FROM codigos_costo WHERE codigo=%s", (cod,), one=True)
            result = int(row_cc["id"]) if row_cc else None
            _cache_cc[cod] = result
            return result

        # ── PASO 1: Recolectar partidas en memoria (sin insertar aun) ───
        partidas_pendientes = []

        for row in ws.iter_rows(min_row=8, values_only=True):
            if not row or len(row) < 4:
                continue

            # Detectar cambio de categoria
            es_fila_cat = False
            cols_cat = [0, 1, 2] if tiene_cols_desc_codigo else [0, 1]
            for chk in cols_cat:
                if chk < len(row) and row[chk]:
                    vu = str(row[chk]).strip().upper().split("(")[0].strip()
                    for key, cat in categorias_map.items():
                        if vu == key:
                            categoria_actual = cat
                            es_fila_cat = True
                            break
                if es_fila_cat:
                    break

            # Extraer campos segun layout
            if tiene_cols_desc_codigo:
                desc_cat   = str(row[0] or "").strip() if row[0] else ""
                codigo_str = str(row[1] or "").strip() if len(row) > 1 and row[1] else ""
                proveedor  = str(row[2] or "").strip() if len(row) > 2 and row[2] else ""
                concepto   = str(row[3] or "").strip() if len(row) > 3 and row[3] else ""
                solicitado = _float(row[5]) if len(row) > 5 else 0
                autorizado = _float(row[6]) if len(row) > 6 else 0
                if not proveedor and desc_cat and not es_fila_cat:
                    proveedor = desc_cat
            else:
                desc_cat   = ""
                codigo_str = ""
                proveedor  = str(row[0] or "").strip() if row[0] else ""
                concepto   = str(row[1] or "").strip() if len(row) > 1 and row[1] else ""
                solicitado = _float(row[3]) if len(row) > 3 else 0
                autorizado = _float(row[4]) if len(row) > 4 else 0

            if es_fila_cat:
                if not concepto:
                    continue
                proveedor = ""

            if not (proveedor or concepto) or (solicitado <= 0 and autorizado <= 0):
                continue
            if "TOTAL" in proveedor.upper() or "TOTAL" in concepto.upper():
                continue
            if "XXXXXX" in proveedor or "XXXXXX" in concepto:
                continue

            contacto_prov = None
            if "\n" in proveedor:
                lineas_prov = [l.strip() for l in proveedor.split("\n") if l.strip()]
                if len(lineas_prov) >= 2:
                    proveedor = lineas_prov[0]
                    contacto_prov = " | ".join(lineas_prov[1:])

            partidas_pendientes.append({
                "categoria":         categoria_actual,
                "proveedor":         proveedor or None,
                "contacto_proveedor":contacto_prov,
                "concepto":          concepto or None,
                "monto_solicitado":  solicitado,
                "monto_autorizado":  autorizado,
                "id_codigo_costo":   _resolver_cc(codigo_str),
                "desc_cat":          desc_cat,
            })

        # ── PASO 2: Validar topes ANTES de insertar ─────────────────────
        # Cada fila del Excel con código de costo asignado cuenta como 1 unidad requisitada.
        # El presupuesto se define en unidades (pza, m³, etc.), no en pesos.
        acumulado_lote = {}  # id_codigo_costo -> cantidad acumulada en este lote (unidades)
        errores_tope = []

        for p in partidas_pendientes:
            id_cc  = p["id_codigo_costo"]
            monto  = p["monto_solicitado"]
            nombre_ref = p.get("desc_cat") or p.get("concepto") or p.get("proveedor") or "?"
            if id_obra and id_cc and monto > 0:
                cantidad_esta_partida = 1  # cada fila = 1 unidad
                extra = acumulado_lote.get(id_cc, 0.0)
                validacion = db.validar_tope_presupuesto(id_obra, id_cc, cantidad_esta_partida + extra)
                if validacion.get("excede"):
                    errores_tope.append(
                        "" + validacion["mensaje"] + " (Fila: " + nombre_ref + ")"
                    )
                else:
                    acumulado_lote[id_cc] = extra + cantidad_esta_partida

        if errores_tope:
            # Rollback: eliminar TODOS los req creados en este import (ESMA y/o GREMIAL previos)
            for rid_rb in req_ids_creados:
                db.execute("DELETE FROM requisicion_partidas WHERE id_requisicion=%s", (rid_rb,))
                db.execute("DELETE FROM nomina_imss WHERE id_requisicion=%s", (rid_rb,))
                db.execute("DELETE FROM nomina_sin_imss WHERE id_requisicion=%s", (rid_rb,))
                db.execute("DELETE FROM finiquitos WHERE id_requisicion=%s", (rid_rb,))
                db.execute("DELETE FROM requisicion_descansos WHERE id_requisicion=%s", (rid_rb,))
                db.execute("DELETE FROM requisiciones WHERE id=%s", (rid_rb,))
            msg = (
                "\U0001f6ab IMPORTACI\u00d3N BLOQUEADA — REQ " + empresa_key + ": "
                "Las siguientes partidas exceden la proyecci\u00f3n presupuestada. "
                "Corrige el Excel y vuelve a intentarlo:"
                "" + "".join(errores_tope) + ""
            )
            flash(msg, "danger")
            return render_template("requisicion_importar.html", user=user, obras=obras)

        # ── PASO 3: Insertar (todo paso la validacion) ───────────────────
        for p in partidas_pendientes:
            db.crear_partida_requisicion({
                "id_requisicion":    req_id,
                "categoria":         p["categoria"],
                "proveedor":         p["proveedor"],
                "contacto_proveedor":p["contacto_proveedor"],
                "concepto":          p["concepto"],
                "periodo":           None,
                "monto_solicitado":  p["monto_solicitado"],
                "monto_autorizado":  p["monto_autorizado"],
                "observaciones":     None,
                "id_codigo_costo":   p["id_codigo_costo"],
                # Cada fila del Excel = 1 unidad (igual que captura manual)
                "cantidad":          1 if p["id_codigo_costo"] and p["monto_solicitado"] > 0 else None,
                "unidad":            None,
            })

        db._recalcular_totales_requisicion(req_id)
        resultados.append(f"REQ {empresa_key}: requisici\u00f3n #{req_id} creada")

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

                    # Sanitizar fecha de ingreso
                    fecha_ing_str = _parse_fecha(fecha_ing)

                    try:
                        db.crear_nomina_imss({
                            "id_requisicion": req_id, "id_empleado": None,
                            "nombre_empleado": nombre, "puesto": puesto,
                            "categoria_personal": cat_personal,
                            "fecha_ingreso": fecha_ing_str,
                            "dias": dias, "salario_diario": sal_diario,
                            "salario_proporcional": sal_prop, "salario_semanal": sal_sem,
                            "horas_extra": hrs_extra, "costo_horas_extra": costo_hrs,
                            "descanso_pagado": descanso, "compensacion": compensacion,
                            "pago_tiempo_extra": pago_te, "comidas": comidas,
                            "total_real": total_real, "observaciones": None,
                        })
                        count_imss += 1
                    except Exception as _e:
                        resultados.append(f"⚠️ C-IMSS fila {nombre}: {_e}")
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

                    try:
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
                    except Exception as _e:
                        resultados.append(f"⚠️ S-IMSS fila {nombre}: {_e}")
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
                    try:
                        db.crear_finiquito({
                            "id_requisicion": req_id, "id_obra": id_obra,
                            "id_empleado": None, "nombre_empleado": nombre,
                            "costo_empresa": costo,
                        })
                        count_finiq += 1
                    except Exception as _e:
                        resultados.append(f"⚠️ FINIQ fila {nombre}: {_e}")
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
                    descansos_parsed = []
                    for di in range(6, 11):
                        dval = row[di] if len(row) > di else None
                        descansos_parsed.append(_parse_fecha(dval))

                    try:
                        db.crear_descanso({
                            "id_requisicion": req_id, "nombre": nombre,
                            "puesto": puesto or None, "origen": origen or None,
                            "fecha_alta": _parse_fecha(fecha_alta),
                            "sueldo": sueldo,
                            "descanso_1": descansos_parsed[0], "descanso_2": descansos_parsed[1],
                            "descanso_3": descansos_parsed[2], "descanso_4": descansos_parsed[3],
                            "descanso_5": descansos_parsed[4],
                        })
                        count_desc += 1
                    except Exception as _e:
                        resultados.append(f"⚠️ DESCAN fila {nombre}: {_e}")
            if count_desc:
                resultados.append(f"DESCAN {empresa_key}: {count_desc} registros")

        # ── Extraer firmas (Solicitó / Revisión / Autorizó) ──
        solicito_nombre = residente_obra  # fallback: el residente de obra
        solicito_puesto = "Administrador de Obra"
        reviso_nombre = None
        reviso_puesto = "Tesoreria"
        autorizo_nombre = None
        autorizo_puesto = "Dirección"
        # Las firmas están al final de la hoja REQ (últimas ~25 filas)
        ws_firmas = hojas.get(f"REQ {empresa_key}".upper())
        if ws_firmas:
            all_rows = list(ws_firmas.iter_rows(values_only=True))
            # Buscar en TODAS las filas desde el final (no solo las últimas 25)
            firmas_rows = all_rows
            found_solicito_label = False
            _firmas_debug = []
            for row in firmas_rows:
                if not row:
                    continue
                row_str = [str(c or "").strip() for c in row]
                row_joined = " ".join(row_str).upper()
                if ("SOLICIT" in row_joined or "REALIZ" in row_joined) and ("AUTORIZ" in row_joined or "VO. BO" in row_joined):
                    found_solicito_label = True
                    _firmas_debug.append(f"LABEL: {row_joined[:80]}")
                    continue
                if not found_solicito_label:
                    continue
                _firmas_debug.append("ROW: " + str([c for c in row_str if c])[:120])
                nombres_fila = []
                for c in row_str:
                    if c and len(c) > 4:
                        c_upper = c.upper()
                        if (c_upper.startswith("ING.") or c_upper.startswith("LIC.") or
                                c_upper.startswith("ARQ.") or c_upper.startswith("C.P.")):
                            if len(c) <= 60 and not any(x in c_upper for x in
                                    ("REEMBOLSO", "PAGO", "CONSTRUCCION", "CARRETERA", "MODERNIZ")):
                                nombres_fila.append(c)
                if nombres_fila:
                    if len(nombres_fila) >= 1:
                        solicito_nombre = nombres_fila[0]
                    if len(nombres_fila) >= 2:
                        reviso_nombre = nombres_fila[1]
                    if len(nombres_fila) >= 3:
                        autorizo_nombre = nombres_fila[2]
                    break
            #flash(f"🔍 FIRMAS {empresa_key}: {_firmas_debug} → sol={solicito_nombre} rev={reviso_nombre} aut={autorizo_nombre}", "warning")
            if solicito_nombre or reviso_nombre or autorizo_nombre:
                try:
                    db.actualizar_firmas_requisicion(
                        req_id, solicito_nombre, solicito_puesto,
                        reviso_nombre, reviso_puesto, autorizo_nombre, autorizo_puesto)
                except Exception:
                    pass  # La función puede no existir en versiones anteriores del servidor

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
    rol = session.get("user_rol", "cliente")
    search = request.args.get("q", "")
    obra = request.args.get("obra", "")
    depto = request.args.get("departamento", "")
    activo = request.args.get("activo", "1")
    # Filtrar por obras permitidas (permisos por obra)
    if rol == "admin":
        obras = db.get_obras()
    else:
        obras_perm = db.get_obras_permitidas(user["id"], "rrhh", "leer")
        if obras_perm:
            obras = [{"id": o["id_obra"], "nombre": o["obra_nombre"]} for o in obras_perm]
            ids_permitidos = {o["id_obra"] for o in obras_perm}
            # Si no seleccionó obra y solo tiene una, forzar
            if not obra and len(ids_permitidos) == 1:
                obra = str(list(ids_permitidos)[0])
        else:
            obras = db.get_obras()
            ids_permitidos = None
    empleados = db.get_empleados(
        search=search or None,
        obra=int(obra) if obra else None,
        departamento=depto or None,
        activo=int(activo) if activo != "" else None
    )
    # Si tiene restricción por obra y no filtró, filtrar la lista
    if rol != "admin" and ids_permitidos and not obra:
        empleados = [e for e in empleados if e.get("id_obra") in ids_permitidos]
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
            foto_archivo.save(os.path.join(EMPLEADOS_FOLDER, foto_nombre))
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
            "horas_diarias": f.get("horas_diarias") or 8,
            "turno": f.get("turno") or "Diurno",
            "tasa_hora_extra": f.get("tasa_hora_extra") or None,
            "banco": f.get("banco") or None, "cuenta_banco": f.get("cuenta_banco") or None,
            "clabe": f.get("clabe") or None,
            "contacto_emergencia": f.get("contacto_emergencia") or None,
            "foto": foto_nombre, "creado_por": user["id"],
        })
        # Procesar documentos subidos junto con el nuevo empleado
        nuevo_id = db.query("SELECT MAX(id) AS id FROM empleados", one=True)["id"]
        doc_tipos = request.form.getlist("doc_tipo[]")
        doc_descripciones = request.form.getlist("doc_descripcion[]")
        doc_archivos = request.files.getlist("doc_archivo[]")
        for i, archivo_doc in enumerate(doc_archivos):
            if archivo_doc and archivo_doc.filename:
                tipo_doc = doc_tipos[i] if i < len(doc_tipos) else "Otro"
                desc_doc = doc_descripciones[i] if i < len(doc_descripciones) else None
                ext = os.path.splitext(archivo_doc.filename)[1].lower()
                nombre_doc = f"doc_{nuevo_id}_{tipo_doc.replace(' ','_')}_{int(__import__('time').time())}_{i}{ext}"
                archivo_doc.save(os.path.join(DOCS_FOLDER, nombre_doc))
                db.crear_documento_empleado(nuevo_id, tipo_doc, nombre_doc, archivo_doc.filename, desc_doc or None, user["id"])
        flash("Empleado registrado correctamente.", "success")
        return redirect(url_for("rrhh"))
    return render_template("empleado_form.html", emp=None, user=user, obras=obras,
                           accion="Nuevo", departamentos=db.DEPARTAMENTOS_RRHH,
                           tipos_contrato=db.TIPOS_CONTRATO, documentos=[])

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
            foto_archivo.save(os.path.join(EMPLEADOS_FOLDER, foto_nombre))
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
            "horas_diarias": f.get("horas_diarias") or 8,
            "turno": f.get("turno") or "Diurno",
            "tasa_hora_extra": f.get("tasa_hora_extra") or None,
            "banco": f.get("banco") or None, "cuenta_banco": f.get("cuenta_banco") or None,
            "clabe": f.get("clabe") or None,
            "contacto_emergencia": f.get("contacto_emergencia") or None,
            "foto": foto_nombre,
        })
        flash("Empleado actualizado.", "success")
        return redirect(url_for("empleado_detalle", eid=eid))
    documentos = db.get_documentos_empleado(eid)
    return render_template("empleado_form.html", emp=emp, user=user, obras=obras,
                           accion="Editar", departamentos=db.DEPARTAMENTOS_RRHH,
                           tipos_contrato=db.TIPOS_CONTRATO, documentos=documentos)

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

# ── DOCUMENTOS DE EMPLEADO ────────────────────────────────────────

@app.route("/uploads/documentos/<filename>")
@login_required
def documento_empleado_file(filename):
    """Sirve archivos de documentos de empleados."""
    return send_from_directory(DOCS_FOLDER, filename)

@app.route("/rrhh/empleado/<int:eid>/documento", methods=["POST"])
@login_required
@permiso_requerido("rrhh", "editar")
def empleado_subir_documento(eid):
    """Sube un documento al expediente del empleado."""
    user = get_current_user()
    archivo = request.files.get("documento")
    tipo = request.form.get("tipo_documento", "Otro")
    descripcion = request.form.get("descripcion") or None

    if not archivo or not archivo.filename:
        flash("Selecciona un archivo.", "danger")
        return redirect(url_for("empleado_editar", eid=eid))

    # Generar nombre único
    ext = os.path.splitext(archivo.filename)[1].lower()
    nombre_archivo = f"doc_{eid}_{tipo.replace(' ','_')}_{int(__import__('time').time())}{ext}"
    archivo.save(os.path.join(DOCS_FOLDER, nombre_archivo))

    db.crear_documento_empleado(eid, tipo, nombre_archivo, archivo.filename, descripcion, user["id"])
    flash(f"Documento '{tipo}' subido correctamente.", "success")
    return redirect(url_for("empleado_editar", eid=eid))


@app.route("/rrhh/empleado/<int:eid>/documento/<int:did>/eliminar", methods=["POST"])
@login_required
@permiso_requerido("rrhh", "editar")
def empleado_eliminar_documento(eid, did):
    """Elimina un documento del expediente del empleado."""
    archivo = db.eliminar_documento_empleado(did)
    if archivo:
        borrar_archivo_fisico(archivo)
    flash("Documento eliminado.", "success")
    return redirect(url_for("empleado_editar", eid=eid))

# ── ASISTENCIA ────────────────────────────────────────────────────

@app.route("/rrhh/asistencia", methods=["GET", "POST"])
@login_required
@permiso_requerido("rrhh", "leer")
def rrhh_asistencia():
    user = get_current_user()
    rol = session.get("user_rol", "cliente")
    # Obras permitidas por permisos por obra
    if rol == "admin":
        obras = db.get_obras()
        ids_permitidos = None
    else:
        obras_perm = db.get_obras_permitidas(user["id"], "rrhh", "leer")
        if obras_perm:
            obras = [{"id": o["id_obra"], "nombre": o["obra_nombre"]} for o in obras_perm]
            ids_permitidos = {o["id_obra"] for o in obras_perm}
        else:
            obras = db.get_obras()
            ids_permitidos = None
    obra_filtro = request.args.get("obra", "")
    # Si tiene restricción y solo una obra, forzar
    if ids_permitidos and not obra_filtro and len(ids_permitidos) == 1:
        obra_filtro = str(list(ids_permitidos)[0])
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
        frente_global = f.get("frente_global") or None
        autoriza_extras_global = f.get("autoriza_extras_global") or None
        for eid in empleados_ids:
            fecha = f.get(f"fecha_{eid}")
            tipo = f.get(f"tipo_{eid}", "asistencia")
            entrada = f.get(f"entrada_{eid}") or None
            salida = f.get(f"salida_{eid}") or None
            hrs_normales_raw = f.get(f"horas_normales_{eid}") or None
            hrs_extra = f.get(f"horas_extra_{eid}") or 0
            obs = f.get(f"obs_{eid}") or None
            obra_id = f.get(f"obra_{eid}") or obra_filtro or None
            frente = f.get(f"frente_{eid}") or frente_global or None
            autoriza_extras = f.get(f"autoriza_{eid}") or autoriza_extras_global or None
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
                # Usar horas_diarias del empleado para determinar jornada normal
                emp_data = db.get_empleado(int(eid))
                jornada = float(emp_data.get("horas_diarias") or 8) if emp_data else 8.0
                hrs_normales = min(horas_totales, jornada)
                hrs_extra = round(max(horas_totales - jornada, 0), 4)
            elif tipo == "asistencia" and not hrs_normales_raw:
                emp_data = db.get_empleado(int(eid))
                hrs_normales = float(emp_data.get("horas_diarias") or 8) if emp_data else 8.0
                hrs_extra = 0
            else:
                hrs_normales = float(hrs_normales_raw) if hrs_normales_raw else 0.0
                hrs_extra = float(hrs_extra) if hrs_extra else 0
            db.registrar_asistencia(
                int(eid), fecha, int(obra_id) if obra_id else None,
                entrada, salida,
                hrs_normales,
                float(hrs_extra),
                tipo, obs, user["id"],
                frente=frente,
                autoriza_extras=autoriza_extras if float(hrs_extra) > 0 else None
            )
        flash("Asistencia registrada.", "success")
        return redirect(url_for("rrhh_asistencia", obra=obra_filtro, fecha_ini=fi, fecha_fin=ff))

    resumen = db.get_resumen_asistencia_semana(fi, ff, int(obra_filtro) if obra_filtro else None)
    empleados = db.get_empleados(obra=int(obra_filtro) if obra_filtro else None, activo=1)
    return render_template("rrhh_asistencia.html", user=user, obras=obras,
                           resumen=resumen, empleados=empleados,
                           fi=fi, ff=ff, obra_filtro=obra_filtro)

@app.route("/rrhh/asistencia/autorizar/<int:eid>", methods=["POST"])
@login_required
@permiso_requerido("rrhh", "editar")
def rrhh_asistencia_autorizar(eid):
    """Actualiza quién autoriza las horas extras de un empleado en el periodo."""
    autoriza = request.form.get("autoriza_extras", "").strip() or None
    fi = request.form.get("fecha_ini", hoy_str())
    ff = request.form.get("fecha_fin", hoy_str())
    # Actualizar todos los registros de asistencia del empleado en ese rango que tengan horas extra
    db.execute("""
        UPDATE asistencia SET autoriza_extras=%s
        WHERE id_empleado=%s AND fecha BETWEEN %s AND %s AND horas_extra > 0
    """, (autoriza, eid, fi, ff))
    flash("Autorización actualizada.", "success")
    return redirect(url_for("rrhh_asistencia", fecha_ini=fi, fecha_fin=ff))

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
    obras = db.get_obras()
    return render_template("asistencia_scanner.html", user=user, obras=obras)


@app.route("/sw-asistencia.js")
def service_worker_asistencia():
    """Sirve el Service Worker desde la raíz para que tenga scope sobre /asistencia/."""
    return send_from_directory(app.static_folder, "sw-asistencia.js",
                              mimetype="application/javascript")


@app.route("/api/asistencia/qr", methods=["POST"])
@login_required
@permiso_requerido("rrhh", "crear")
def api_asistencia_qr():
    """API para procesar un escaneo QR de asistencia con foto de evidencia y GPS.
    Primer escaneo del día = entrada, segundo = salida, alternando.
    Soporta registros offline que se sincronizan después."""
    from datetime import datetime as dt
    import base64

    data = request.get_json()
    if not data:
        return jsonify({"ok": False, "msg": "Datos invalidos"}), 400
    numero_empleado = (data.get("numero_empleado") or "").strip()
    if not numero_empleado:
        return jsonify({"ok": False, "msg": "QR invalido: sin numero de empleado"}), 400

    foto_base64 = data.get("foto")  # data:image/jpeg;base64,...
    # Coordenadas GPS (pueden venir null si no se obtuvo señal)
    lat = data.get("lat")
    lng = data.get("lng")
    accuracy = data.get("accuracy")
    timestamp_local = data.get("timestamp_local")  # ISO string del momento real del registro

    try:
        emp = db.get_empleado_por_numero(numero_empleado)
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Error al buscar empleado: {e}"}), 500

    if not emp:
        return jsonify({"ok": False, "msg": f"Empleado {numero_empleado} no encontrado o inactivo"}), 404

    # Si viene timestamp_local (registro offline), usar esa fecha/hora
    if timestamp_local:
        try:
            ts_local = dt.fromisoformat(timestamp_local.replace("Z", "+00:00"))
            # Convertir a hora de México (UTC-6)
            from datetime import timezone, timedelta as td
            tz_mexico = timezone(td(hours=-6))
            ts_mexico = ts_local.astimezone(tz_mexico)
            hoy = ts_mexico.strftime("%Y-%m-%d")
            ahora = ts_mexico.strftime("%H:%M:%S")
        except Exception:
            from datetime import timezone, timedelta as td
            tz_mexico = timezone(td(hours=-6))
            ahora_mx = dt.now(tz_mexico)
            hoy = ahora_mx.strftime("%Y-%m-%d")
            ahora = ahora_mx.strftime("%H:%M:%S")
    else:
        from datetime import timezone, timedelta as td
        tz_mexico = timezone(td(hours=-6))
        ahora_mx = dt.now(tz_mexico)
        hoy = ahora_mx.strftime("%Y-%m-%d")
        ahora = ahora_mx.strftime("%H:%M:%S")

    nombre_completo = f"{emp['apellido_paterno']} {emp.get('apellido_materno') or ''}, {emp['nombre']}".strip()

    # Obra y frente del scanner (prioridad sobre la obra asignada al empleado)
    id_obra_scanner = data.get("id_obra")
    frente_scanner = data.get("frente")
    id_obra_registro = int(id_obra_scanner) if id_obra_scanner else emp.get("id_obra")

    # Guardar foto de evidencia si viene
    foto_nombre = None
    if foto_base64 and "," in foto_base64:
        try:
            header, img_data = foto_base64.split(",", 1)
            img_bytes = base64.b64decode(img_data)
            ts = int(dt.now().timestamp())
            foto_nombre = f"asist_{numero_empleado}_{hoy}_{ts}.jpg"
            foto_path = os.path.join(ASISTENCIA_FOLDER, foto_nombre)
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
            db.registrar_escaneo_qr(emp["id"], hoy, ahora, "entrada", id_obra_registro, foto_nombre, lat=lat, lng=lng, accuracy=accuracy)
            # Actualizar frente si se proporcionó
            if frente_scanner:
                db.execute("UPDATE asistencia SET frente=%s WHERE id_empleado=%s AND fecha=%s",
                           (frente_scanner, emp["id"], hoy))
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
            db.registrar_escaneo_qr(emp["id"], hoy, ahora, "salida", id_obra_registro, foto_nombre, lat=lat, lng=lng, accuracy=accuracy)
            # Actualizar frente si se proporcionó
            if frente_scanner:
                db.execute("UPDATE asistencia SET frente=%s WHERE id_empleado=%s AND fecha=%s",
                           (frente_scanner, emp["id"], hoy))
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
        SELECT eq.*, ob.nombre AS obra_nombre, a.frente
        FROM escaneos_qr eq
        LEFT JOIN obras ob ON ob.id = eq.id_obra
        LEFT JOIN asistencia a ON a.id_empleado = eq.id_empleado AND a.fecha = eq.fecha
        WHERE eq.id_empleado=%s AND eq.fecha BETWEEN %s AND %s
        ORDER BY eq.fecha DESC, eq.hora DESC
    """, (eid, fi, ff))
    return render_template("asistencia_evidencia.html", user=user, emp=emp,
                           escaneos=escaneos, fi=fi, ff=ff)


# ── NÓMINA ────────────────────────────────────────────────────────

@app.route("/rrhh/nomina")
@login_required
@permiso_requerido("rrhh", "leer")
def rrhh_nomina():
    user = get_current_user()
    rol = session.get("user_rol", "cliente")
    # Obras permitidas por permisos por obra
    if rol == "admin":
        obras = db.get_obras()
    else:
        obras_perm = db.get_obras_permitidas(user["id"], "rrhh", "leer")
        if obras_perm:
            obras = [{"id": o["id_obra"], "nombre": o["obra_nombre"]} for o in obras_perm]
            ids_permitidos = {o["id_obra"] for o in obras_perm}
        else:
            obras = db.get_obras()
            ids_permitidos = None
    semana = request.args.get("semana", "")
    obra_filtro = request.args.get("obra", "")
    # Si tiene restricción y solo una obra, forzar
    if rol != "admin" and obras_perm and not obra_filtro and len(ids_permitidos) == 1:
        obra_filtro = str(list(ids_permitidos)[0])

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
    sueldo_semanal = float(f.get("sueldo_semanal") or 0)
    pago_extras = float(f.get("pago_horas_extra") or 0)
    devengado = float(f.get("devengado") or 0)
    descuento_isr = float(f.get("descuento_isr") or 0)
    descuento_imss = float(f.get("descuento_imss") or 0)
    descuento_infonavit = float(f.get("descuento_infonavit") or 0)
    otros_descuentos = float(f.get("otros_descuentos") or 0)
    monto_empresa = float(f.get("monto_empresa") or 0)
    total = float(f.get("total_pagar") or 0)

    # Si no se capturó sueldo semanal, tomar del empleado
    if sueldo_semanal <= 0:
        emp_data = db.get_empleado(id_empleado)
        if emp_data:
            sueldo_semanal = float(emp_data.get("salario_semanal") or 0)

    # Calcular salario base (proporcional a dias trabajados)
    salario_base = round((sueldo_semanal / 6) * dias, 2) if sueldo_semanal > 0 else 0

    # Si devengado está en 0, calcular
    if devengado <= 0:
        devengado = round(salario_base + pago_extras, 2)

    # Total descuentos
    total_descuentos = round(descuento_isr + descuento_imss + descuento_infonavit + otros_descuentos, 2)

    # Si total está en 0, calcular
    if total <= 0:
        total = round(devengado - total_descuentos, 2)

    # Calcular semana ESMA
    from datetime import datetime as dt
    fecha_ini = dt.strptime(fi, "%Y-%m-%d")
    sem_num = db.calcular_semana_combustible(fecha_ini)
    semana = f"SEM-{sem_num:02d}" if sem_num else f"SEM-{fecha_ini.isocalendar()[1]:02d}"

    db.execute("""
        INSERT INTO nomina
            (id_empleado, semana, fecha_inicio, fecha_fin, dias_trabajados,
             horas_normales, horas_extra, salario_base, sueldo_semanal,
             pago_horas_extra, devengado,
             descuento_isr, descuento_imss, descuento_infonavit,
             otros_descuentos, total_descuentos,
             total_pagar, monto_empresa, generado_por)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
            otros_descuentos=VALUES(otros_descuentos),
            total_descuentos=VALUES(total_descuentos),
            total_pagar=VALUES(total_pagar),
            monto_empresa=VALUES(monto_empresa)
    """, (id_empleado, semana, fi, ff, dias,
          dias * 8, hrs_extra, salario_base, sueldo_semanal,
          pago_extras, devengado,
          descuento_isr, descuento_imss, descuento_infonavit,
          otros_descuentos, total_descuentos,
          total, monto_empresa, user["id"]))

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


@app.route("/rrhh/nomina/validar", methods=["POST"])
@login_required
@permiso_requerido("rrhh", "editar")
def rrhh_nomina_validar():
    """Valida la nómina de una semana: registra quién validó y cuándo."""
    user = get_current_user()
    semana = request.form["semana"]
    nombre_validador = f"{user.get('nombre','')} {user.get('apellido','')}"
    db.execute("""
        UPDATE nomina SET validado_por=%s, nombre_validador=%s, fecha_validacion=NOW()
        WHERE semana=%s AND validado_por IS NULL
    """, (user["id"], nombre_validador, semana))
    flash(f"Nómina de semana {semana} validada por {nombre_validador}.", "success")
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
        tipo_pedido = f.get("tipo_pedido", "3 - Materiales")
        numero = db.get_siguiente_numero_oc(id_obra, tipo_pedido=tipo_pedido)
        folio = db.generar_folio_oc(tipo_pedido, numero)
        datos = {
            "numero_pedido": numero,
            "folio": folio,
            "fecha": f.get("fecha") or hoy_str(),
            "tipo_pedido": tipo_pedido,
            "id_obra": id_obra,
            "descripcion_obra": f.get("descripcion_obra") or None,
            "proveedor": f.get("proveedor") or None,
            "rfc_proveedor": f.get("rfc_proveedor") or None,
            "contacto_pago": f.get("contacto_pago") or None,
            "telefono_proveedor": f.get("telefono_proveedor") or None,
            "email_proveedor": db.get_email_del_proveedor(f.get("proveedor")) or None,
            "email_contacto_pago": f.get("email_contacto_pago") or None,
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
        # Calcular totales y actualizar importe con letra automáticamente
        pct_iva = float(f.get("porcentaje_iva") or 16)
        sub, iva, total = db.recalcular_totales_oc(oid, porcentaje_iva=pct_iva)
        letra = f.get("importe_letra") or db.numero_a_letras(total)
        db.execute("UPDATE ordenes_compra SET importe_letra=%s WHERE id=%s", (letra, oid))
        # Correo de notificación al creador
        try:
            obra_nombre = ""
            if id_obra:
                obra = db.get_obra(id_obra)
                obra_nombre = obra["nombre"] if obra else ""
            cuerpo_html = f"""
            <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
              <h2 style="color:#1a5276;border-bottom:2px solid #1a5276;padding-bottom:8px">
                Nueva Orden de Compra Creada
              </h2>
              <table style="width:100%;border-collapse:collapse;font-size:14px">
                <tr><td style="padding:6px 0;color:#555;width:160px"><strong>Folio / No. Pedido:</strong></td>
                    <td style="padding:6px 0;font-weight:700;color:#1a5276">{folio}</td></tr>
                <tr><td style="padding:6px 0;color:#555"><strong>Tipo de pedido:</strong></td>
                    <td style="padding:6px 0">{tipo_pedido}</td></tr>
                <tr><td style="padding:6px 0;color:#555"><strong>Proyecto / Obra:</strong></td>
                    <td style="padding:6px 0">{obra_nombre}</td></tr>
                <tr><td style="padding:6px 0;color:#555"><strong>Proveedor:</strong></td>
                    <td style="padding:6px 0">{datos.get('proveedor') or '—'}</td></tr>
                <tr><td style="padding:6px 0;color:#555"><strong>Total:</strong></td>
                    <td style="padding:6px 0;font-weight:700">${total:,.2f} {datos.get('moneda','MXN')}</td></tr>
                <tr><td style="padding:6px 0;color:#555"><strong>Importe con letra:</strong></td>
                    <td style="padding:6px 0;font-style:italic">{letra}</td></tr>
                <tr><td style="padding:6px 0;color:#555"><strong>Creada por:</strong></td>
                    <td style="padding:6px 0">{user.get('nombre','')}</td></tr>
                <tr><td style="padding:6px 0;color:#555"><strong>Estatus:</strong></td>
                    <td style="padding:6px 0"><span style="background:#f39c12;color:#fff;padding:2px 8px;border-radius:4px">BORRADOR</span></td></tr>
              </table>
              <p style="margin-top:20px;font-size:12px;color:#888">
                Este es un aviso automático generado por el sistema ESMA. La orden debe ser enviada a autorización para proceder.
              </p>
            </div>"""
            cuerpo_texto = (f"Nueva OC creada: {folio} | Proveedor: {datos.get('proveedor','—')} | "
                            f"Obra: {obra_nombre} | Total: ${total:,.2f} {datos.get('moneda','MXN')}")
            if user.get("email"):
                enviar_email(user["email"], f"OC Creada: {folio}", cuerpo_html, cuerpo_texto,
                             headers={"X-ESMA-OC-ID": str(oid)})
        except Exception as e:
            app.logger.warning(f"[OC] No se pudo enviar correo de creación OC #{oid}: {e}")
        flash(f"Orden de Compra {folio} creada.", "success")
        return redirect(url_for("orden_compra_detalle", oid=oid))
    proveedores = db.get_proveedores_oc()
    return render_template("orden_compra_form.html", user=user, obras=obras,
                           proveedores=proveedores, proveedores_autofill=db.get_proveedores_autofill(),
                           proveedores_catalogo=db.get_proveedores_catalogo(),
                           oc=None, partidas=[], codigos_costo=db.get_codigos_costo(),
                           tipos_pedido=db.TIPOS_PEDIDO_OC,
                           condiciones_pago=db.CONDICIONES_PAGO_OC,
                           monedas=db.MONEDAS_OC,
                           formas_pago=db.FORMAS_PAGO_OC,
                           metodos_pago=db.METODOS_PAGO_OC,
                           usos_cfdi=db.USOS_CFDI_OC,
                           directorio_equipo=db.get_directorio_equipo_proyecto())


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
    from xhtml2pdf import pisa
    from io import BytesIO
    import traceback

    try:
        oc = db.get_orden_compra(oid)
        if not oc:
            abort(404)
        partidas = db.get_partidas_orden(oid)

        logo_path = os.path.join(os.path.dirname(__file__), "logo2.png").replace("\\", "/")
        if not os.path.exists(logo_path):
            logo_path = None

        html = render_template("orden_compra_pdf.html", oc=oc, partidas=partidas,
                               logo_path=logo_path)

        buffer = BytesIO()
        pdf = pisa.CreatePDF(html, dest=buffer, encoding="utf-8")
        if pdf.err:
            app.logger.error(f"xhtml2pdf error: {pdf.err}")
            flash("Error al generar PDF.", "danger")
            return redirect(url_for("orden_compra_detalle", oid=oid))

        buffer.seek(0)
        folio = oc.get("folio") or f"OC-{oc['numero_pedido'] or oc['id']}"
        nombre = f"{folio}_{oc.get('proveedor','')[:30]}".replace(" ", "_").replace("/", "-")
        return send_file(buffer, as_attachment=True,
                         download_name=f"{nombre}.pdf",
                         mimetype="application/pdf")
    except Exception as e:
        app.logger.error(f"Error generando PDF orden {oid}: {e}\n{traceback.format_exc()}")
        flash("Error al generar PDF.", "danger")
        return redirect(url_for("orden_compra_detalle", oid=oid))











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
            "email_proveedor": db.get_email_del_proveedor(f.get("proveedor")) or oc.get("email_proveedor") or None,
            "email_contacto_pago": f.get("email_contacto_pago") or None,
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
        pct_iva_edit = float(f.get("porcentaje_iva") or 16)
        _, _, total = db.recalcular_totales_oc(oid, porcentaje_iva=pct_iva_edit)
        # Recalcular importe con letra si el usuario no lo editó manualmente
        letra = f.get("importe_letra") or db.numero_a_letras(total)
        db.execute("UPDATE ordenes_compra SET importe_letra=%s WHERE id=%s", (letra, oid))
        flash("Orden de Compra actualizada.", "success")
        return redirect(url_for("orden_compra_detalle", oid=oid))
    partidas = db.get_partidas_orden(oid)
    proveedores = db.get_proveedores_oc()
    return render_template("orden_compra_form.html", user=user, obras=obras,
                           proveedores=proveedores, proveedores_autofill=db.get_proveedores_autofill(),
                           proveedores_catalogo=db.get_proveedores_catalogo(),
                           oc=oc, partidas=partidas, codigos_costo=db.get_codigos_costo(),
                           tipos_pedido=db.TIPOS_PEDIDO_OC,
                           condiciones_pago=db.CONDICIONES_PAGO_OC,
                           monedas=db.MONEDAS_OC,
                           formas_pago=db.FORMAS_PAGO_OC,
                           metodos_pago=db.METODOS_PAGO_OC,
                           usos_cfdi=db.USOS_CFDI_OC,
                           directorio_equipo=db.get_directorio_equipo_proyecto())


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
def orden_compra_autorizar(oid):
    user = get_current_user()
    db.autorizar_orden_compra(oid, user["id"])

    # ── Enviar correo al proveedor registrado ────────────────────────
    correo_enviado = False
    correo_email_destino = None
    try:
        oc = db.get_orden_compra(oid)
        email_proveedor = db.get_email_proveedor_oc(oid)
        print(f"[OC-AUTORIZAR] oid={oid} | email_proveedor='{email_proveedor}' | "
              f"email_en_oc='{oc.get('email_proveedor') if oc else None}' | "
              f"proveedor='{oc.get('proveedor') if oc else None}'", flush=True)
        app.logger.warning(f"[OC-AUTORIZAR] oid={oid} | email_proveedor='{email_proveedor}' | "
              f"email_en_oc='{oc.get('email_proveedor') if oc else None}' | "
              f"proveedor='{oc.get('proveedor') if oc else None}'")
        if oc and email_proveedor:
            correo_email_destino = email_proveedor
            partidas = db.get_partidas_orden(oid)
            filas_partidas = "".join(
                f"<tr><td style='padding:4px 8px;border:1px solid #ddd'>{p.get('pos','')}</td>"
                f"<td style='padding:4px 8px;border:1px solid #ddd'>{p.get('descripcion','')}</td>"
                f"<td style='padding:4px 8px;border:1px solid #ddd;text-align:center'>{p.get('cantidad','')}</td>"
                f"<td style='padding:4px 8px;border:1px solid #ddd;text-align:center'>{p.get('unidad','')}</td>"
                f"<td style='padding:4px 8px;border:1px solid #ddd;text-align:right'>${float(p.get('precio_unitario') or 0):,.2f}</td>"
                f"<td style='padding:4px 8px;border:1px solid #ddd;text-align:right'>${float(p.get('importe') or 0):,.2f}</td></tr>"
                for p in partidas
            )
            cuerpo_html = f"""
            <div style="font-family:Arial,sans-serif;max-width:700px;margin:0 auto">
              <div style="background:#003070;padding:16px 24px;border-radius:4px 4px 0 0">
                <h1 style="color:#fff;margin:0;font-size:20px">ESMA — Orden de Compra Autorizada</h1>
              </div>
              <div style="padding:20px 24px;border:1px solid #ddd;border-top:none">
                <p style="font-size:14px">Estimado(a) <strong>{oc.get('contacto_pago') or oc.get('proveedor','Proveedor')}</strong>,</p>
                <p style="font-size:13px;color:#444">
                  Le informamos que la siguiente Orden de Compra ha sido <strong style="color:#27ae60">AUTORIZADA</strong>
                  y está lista para proceder conforme a las condiciones acordadas.
                </p>
                <table style="width:100%;border-collapse:collapse;font-size:13px;margin:12px 0">
                  <tr><td style="padding:4px 0;color:#555;width:180px"><strong>No. de Pedido:</strong></td>
                      <td style="font-weight:700;color:#003070;font-size:16px">{oc.get('folio') or oc.get('numero_pedido','')}</td></tr>
                  <tr><td style="padding:4px 0;color:#555"><strong>Fecha:</strong></td>
                      <td>{oc.get('fecha','')}</td></tr>
                  <tr><td style="padding:4px 0;color:#555"><strong>Tipo de pedido:</strong></td>
                      <td>{oc.get('tipo_pedido','')}</td></tr>
                  <tr><td style="padding:4px 0;color:#555"><strong>Proyecto / Obra:</strong></td>
                      <td>{oc.get('obra_nombre') or '—'}</td></tr>
                  <tr><td style="padding:4px 0;color:#555"><strong>Condiciones de pago:</strong></td>
                      <td>{oc.get('condiciones_pago') or '—'}</td></tr>
                  <tr><td style="padding:4px 0;color:#555"><strong>Tiempo de entrega:</strong></td>
                      <td>{oc.get('tiempo_entrega') or '—'}</td></tr>
                </table>

                <h3 style="font-size:13px;color:#003070;margin:16px 0 6px 0">PARTIDAS</h3>
                <table style="width:100%;border-collapse:collapse;font-size:12px">
                  <thead>
                    <tr style="background:#003070;color:#fff">
                      <th style="padding:6px 8px;text-align:center">#</th>
                      <th style="padding:6px 8px;text-align:left">Descripción</th>
                      <th style="padding:6px 8px;text-align:center">Cantidad</th>
                      <th style="padding:6px 8px;text-align:center">Unidad</th>
                      <th style="padding:6px 8px;text-align:right">P.U.</th>
                      <th style="padding:6px 8px;text-align:right">Importe</th>
                    </tr>
                  </thead>
                  <tbody>{filas_partidas}</tbody>
                </table>

                <table style="width:100%;margin-top:8px;font-size:13px">
                  <tr><td style="text-align:right;padding:3px 8px"><strong>Subtotal:</strong></td>
                      <td style="text-align:right;width:120px">${float(oc.get('subtotal') or 0):,.2f}</td></tr>
                  <tr><td style="text-align:right;padding:3px 8px"><strong>IVA:</strong></td>
                      <td style="text-align:right">${float(oc.get('iva') or 0):,.2f}</td></tr>
                  {'<tr><td style="text-align:right;padding:3px 8px"><strong>Retención:</strong></td><td style="text-align:right">$' + f"{float(oc.get('retencion') or 0):,.2f}" + '</td></tr>' if oc.get('retencion') else ''}
                  <tr style="border-top:2px solid #003070">
                    <td style="text-align:right;padding:6px 8px;font-size:15px"><strong>TOTAL {oc.get('moneda','MXN')}:</strong></td>
                    <td style="text-align:right;font-size:15px;font-weight:700">${float(oc.get('total') or 0):,.2f}</td>
                  </tr>
                </table>

                {'<p style="font-size:12px;font-style:italic;color:#555;margin-top:8px">' + str(oc.get('importe_letra','')) + '</p>' if oc.get('importe_letra') else ''}

                <hr style="border:none;border-top:1px solid #eee;margin:20px 0">
                <p style="font-size:11px;color:#888">
                  Este correo es un aviso automático del sistema ESMA. Para cualquier aclaración
                  comuníquese con el responsable: <strong>{oc.get('responsable','')}</strong>.
                </p>
              </div>
            </div>"""
            cuerpo_texto = (
                f"Orden de Compra {oc.get('folio') or oc.get('numero_pedido','')} AUTORIZADA | "
                f"Proveedor: {oc.get('proveedor','—')} | "
                f"Total: ${float(oc.get('total') or 0):,.2f} {oc.get('moneda','MXN')}"
            )
            # ── Generar PDF y adjuntarlo ─────────────────────────────
            pdf_tmp_path = None
            nombre_pdf = None
            try:
                from xhtml2pdf import pisa
                from io import BytesIO
                import tempfile
                logo_path = os.path.join(os.path.dirname(__file__), "logo2.png").replace("\\", "/")
                if not os.path.exists(logo_path):
                    logo_path = None
                html_pdf = render_template("orden_compra_pdf.html", oc=oc, partidas=partidas,
                                           logo_path=logo_path)
                buffer = BytesIO()
                result = pisa.CreatePDF(html_pdf, dest=buffer, encoding="utf-8")
                if not result.err:
                    buffer.seek(0)
                    folio_str = str(oc.get('folio') or oc.get('numero_pedido') or oid)
                    nombre_pdf = f"OC_{folio_str}_{(oc.get('proveedor') or '')[:25].replace(' ','_')}.pdf"
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp.write(buffer.read())
                        pdf_tmp_path = tmp.name
            except Exception as pdf_err:
                app.logger.warning(f"[OC] PDF no generado para OC #{oid}: {pdf_err}")

            correo_enviado = enviar_email(
                email_proveedor,
                f"Orden de Compra Autorizada #{oc.get('folio') or oc.get('numero_pedido','')} — ESMA",
                cuerpo_html, cuerpo_texto,
                adjunto_path=pdf_tmp_path,
                adjunto_nombre=nombre_pdf,
                headers={"X-ESMA-OC-ID": str(oid)}
            )
            if pdf_tmp_path:
                try:
                    os.remove(pdf_tmp_path)
                except Exception:
                    pass
        else:
            app.logger.warning(f"[OC-AUTORIZAR] OC #{oid} — sin email de proveedor. email='{email_proveedor}'")
    except Exception as e:
        app.logger.warning(f"[OC] Error al enviar correo proveedor OC #{oid}: {e}", exc_info=True)

    # ── Flash condicional ─────────────────────────────────────────────
    if correo_enviado:
        flash(f"Orden de Compra autorizada. Correo enviado al proveedor ({correo_email_destino}).", "success")
    elif correo_email_destino:
        flash("Orden de Compra autorizada. Lo sentimos, no se pudo enviar el correo al proveedor.", "warning")
    else:
        flash("Orden de Compra autorizada. Sin correo: el proveedor no tiene email registrado.", "warning")

    return redirect(url_for("orden_compra_detalle", oid=oid))


@app.route("/ordenes-compra/<int:oid>/rechazar", methods=["POST"])
@login_required
@permiso_requerido("ordenes_compra", "editar")
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


@app.route("/ordenes-compra/<int:oid>/pago", methods=["POST"])
@login_required
@permiso_requerido("ordenes_compra", "editar")
def orden_compra_actualizar_pago(oid):
    """Actualiza el estatus de pago (pagado / no_pagado) de una orden de compra."""
    estatus_pago = request.form.get("estatus_pago", "no_pagado")
    if estatus_pago not in ("no_pagado", "pagado"):
        estatus_pago = "no_pagado"
    db.update_estatus_pago_orden(oid, estatus_pago)
    return ("", 204)


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
            numero = numero_pedido or str(db.get_siguiente_numero_oc(id_obra, tipo_pedido=tipo_pedido))
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
    n_pendientes = len(db.get_proveedores_pendientes())
    return render_template("proveedores.html", user=user, proveedores=lista,
                           search=search, tipo_filtro=tipo_filtro, estado_filtro=estado_filtro,
                           tipos=db.TIPOS_PROVEEDOR, n_pendientes=n_pendientes)


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
            "tipo_producto_servicio": f.get("tipo_producto_servicio") or None,
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
            "plazo_cc_desde": f.get("plazo_cc_desde") or None,
            "plazo_cc_hasta": f.get("plazo_cc_hasta") or None,
            "creado_por": session["user_id"],
        }
        pid = db.crear_proveedor(datos)
        # Asignar obras seleccionadas
        obras_sel = f.getlist("obras_asignadas")
        if obras_sel:
            db.asignar_obras_proveedor(pid, obras_sel)
        # Guardar documentos adjuntos
        archivos = request.files.getlist("documentos")
        EXTENSIONES_PERMITIDAS = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.csv'}
        for archivo in archivos:
            if archivo and archivo.filename:
                ext = os.path.splitext(archivo.filename)[1].lower()
                if ext not in EXTENSIONES_PERMITIDAS:
                    continue
                import time as _t
                nombre_disco = f"prov_{pid}_{int(_t.time())}_{archivo.filename}"
                archivo.save(os.path.join(PROVEEDORES_FOLDER, nombre_disco))
                db.guardar_documento_proveedor(pid, nombre_disco, archivo.filename, ext, session["user_id"])
        flash(f"Proveedor '{datos['razon_social']}' registrado.", "success")
        return redirect(url_for("proveedor_detalle", pid=pid))
    obras = db.get_obras()
    return render_template("proveedor_form.html", user=user, prov=None, accion="Nuevo",
                           tipos=db.TIPOS_PROVEEDOR, condiciones_pago=db.CONDICIONES_PAGO_OC,
                           obras=obras, obras_asignadas_ids=[])


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
                           documentos=db.get_documentos_proveedor(pid),
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
            "tipo_producto_servicio": f.get("tipo_producto_servicio") or None,
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
            "plazo_cc_desde": f.get("plazo_cc_desde") or None,
            "plazo_cc_hasta": f.get("plazo_cc_hasta") or None,
        }
        db.actualizar_proveedor(pid, datos)
        # Guardar plazo CC de forma explícita (respaldo independiente)
        db.actualizar_plazo_cc_proveedor(pid, f.get("plazo_cc_desde") or None, f.get("plazo_cc_hasta") or None)
        # Actualizar obras asignadas
        obras_sel = f.getlist("obras_asignadas")
        db.asignar_obras_proveedor(pid, obras_sel)
        # Guardar documentos adjuntos nuevos
        archivos = request.files.getlist("documentos")
        EXTENSIONES_PERMITIDAS = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.csv'}
        for archivo in archivos:
            if archivo and archivo.filename:
                ext = os.path.splitext(archivo.filename)[1].lower()
                if ext not in EXTENSIONES_PERMITIDAS:
                    continue
                import time as _t
                nombre_disco = f"prov_{pid}_{int(_t.time())}_{archivo.filename}"
                archivo.save(os.path.join(PROVEEDORES_FOLDER, nombre_disco))
                db.guardar_documento_proveedor(pid, nombre_disco, archivo.filename, ext, session["user_id"])
        flash("Proveedor actualizado.", "success")
        return redirect(url_for("proveedor_detalle", pid=pid))
    documentos = db.get_documentos_proveedor(pid)
    obras = db.get_obras()
    obras_actuales = db.get_obras_proveedor(pid)
    obras_asignadas_ids = [o["id"] for o in obras_actuales] if obras_actuales else []
    return render_template("proveedor_form.html", user=user, prov=prov, accion="Editar",
                           tipos=db.TIPOS_PROVEEDOR, condiciones_pago=db.CONDICIONES_PAGO_OC,
                           documentos=documentos, obras=obras, obras_asignadas_ids=obras_asignadas_ids)


@app.route("/proveedores/<int:pid>/estado", methods=["POST"])
@login_required
@permiso_requerido("proveedores", "eliminar")
def proveedor_cambiar_estado(pid):
    nuevo = int(request.form.get("activo", "1"))
    if nuevo not in (0, 1, 2):
        nuevo = 1
    db.cambiar_estado_proveedor(pid, nuevo)
    estados_msg = {1: "Proveedor activado.", 2: "Proveedor marcado como inactivo.", 0: "Proveedor dado de baja."}
    flash(estados_msg.get(nuevo, "Estado actualizado."), "success")
    return redirect(request.referrer or url_for("proveedores"))


@app.route("/proveedores/documento/<int:doc_id>")
@login_required
@permiso_requerido("proveedores", "leer")
def proveedor_documento_descargar(doc_id):
    """Descarga un documento adjunto de proveedor."""
    doc = db.query("SELECT * FROM proveedor_documentos WHERE id=%s", (doc_id,), one=True)
    if not doc:
        abort(404)
    ruta = os.path.join(PROVEEDORES_FOLDER, doc["nombre_archivo"])
    if not os.path.exists(ruta):
        abort(404)
    return send_file(ruta, as_attachment=True, download_name=doc["nombre_original"])


@app.route("/proveedores/documento/<int:doc_id>/ver")
@login_required
@permiso_requerido("proveedores", "leer")
def proveedor_documento_ver(doc_id):
    """Visualiza un documento adjunto de proveedor directamente en el navegador."""
    doc = db.query("SELECT * FROM proveedor_documentos WHERE id=%s", (doc_id,), one=True)
    if not doc:
        abort(404)
    ruta = os.path.join(PROVEEDORES_FOLDER, doc["nombre_archivo"])
    if not os.path.exists(ruta):
        abort(404)
    return send_file(ruta, as_attachment=False, download_name=doc["nombre_original"])


@app.route("/proveedores/documento/<int:doc_id>/eliminar", methods=["POST"])
@login_required
@permiso_requerido("proveedores", "editar")
def proveedor_documento_eliminar(doc_id):
    """Elimina un documento adjunto de proveedor."""
    # Verificar si está protegido (pagado)
    doc_check = db.get_documento_proveedor(doc_id)
    if doc_check and doc_check.get("estado_pago") == "pagado":
        flash("No se puede eliminar: este documento está marcado como PAGADO.", "danger")
        return redirect(url_for("proveedor_detalle", pid=doc_check["id_proveedor"]))
    doc = db.eliminar_documento_proveedor(doc_id)
    if doc:
        ruta = os.path.join(PROVEEDORES_FOLDER, doc["nombre_archivo"])
        if os.path.exists(ruta):
            os.remove(ruta)
        flash("Documento eliminado.", "success")
        return redirect(url_for("proveedor_detalle", pid=doc["id_proveedor"]))
    abort(404)


@app.route("/proveedores/documento/<int:doc_id>/marcar-pagado", methods=["POST"])
@login_required
@permiso_requerido("proveedores", "editar")
def proveedor_documento_marcar_pagado(doc_id):
    """Marca un documento ININME-FACTURA como pagado (irreversible)."""
    doc = db.marcar_documento_pagado(doc_id)
    if doc:
        flash("Documento marcado como PAGADO. Este estado no puede revertirse.", "success")
        return redirect(url_for("proveedor_detalle", pid=doc["id_proveedor"]))
    flash("No se pudo marcar como pagado.", "danger")
    return redirect(request.referrer or url_for("proveedores"))


@app.route("/proveedores/pendientes")
@login_required
@permiso_requerido("proveedores", "leer")
def proveedores_pendientes():
    """Lista proveedores con registro pendiente de aprobación."""
    user = get_current_user()
    pendientes = db.get_proveedores_pendientes()
    return render_template("proveedores_pendientes.html", user=user, pendientes=pendientes)


@app.route("/proveedores/<int:pid>/aprobar", methods=["POST"])
@login_required
@permiso_requerido("proveedores", "editar")
def proveedor_aprobar(pid):
    db.aprobar_proveedor(pid)
    flash("Proveedor aprobado y agregado al catálogo.", "success")
    return redirect(url_for("proveedores_pendientes"))


@app.route("/proveedores/<int:pid>/rechazar", methods=["POST"])
@login_required
@permiso_requerido("proveedores", "editar")
def proveedor_rechazar(pid):
    # Obtener archivos asociados antes de borrar registros de BD
    documentos = db.get_documentos_proveedor(pid)
    ordenes = db.get_ordenes_cc(id_proveedor=pid)

    # Borrar archivos físicos de documentos del proveedor
    for doc in documentos:
        ruta = os.path.join(PROVEEDORES_FOLDER, doc["nombre_archivo"])
        if os.path.exists(ruta):
            os.remove(ruta)

    # Borrar archivos físicos de órdenes CC (cotización, factura, resultados)
    for orden in ordenes:
        for campo in ("archivo_cotizacion", "archivo_factura", "archivo_resultados"):
            nombre = orden.get(campo)
            if nombre:
                ruta = os.path.join(PROVEEDORES_FOLDER, nombre)
                if os.path.exists(ruta):
                    os.remove(ruta)

    # Eliminar todos los registros de BD y el proveedor
    db.rechazar_proveedor_completo(pid)
    flash("Proveedor rechazado y todos sus datos eliminados.", "success")
    return redirect(url_for("proveedores_pendientes"))


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
#  CATÁLOGO DE CÓDIGOS DE COSTO (dentro de Requisiciones)
# ══════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════
#  PRESUPUESTO POR OBRA (topes de volumen para requisiciones)
# ══════════════════════════════════════════════════════════════════

@app.route("/requisiciones/presupuesto-obra")
@login_required
def presupuesto_obra():
    """Vista admin: gestionar presupuesto de volumen por obra."""
    user = get_current_user()
    rol = session.get("user_rol", "cliente")
    # Verificar permiso por obra (requisiciones_presupuesto) o admin
    if rol != "admin":
        obras_perm = db.get_obras_permitidas(user["id"], "requisiciones_presupuesto", "leer")
        if not obras_perm:
            flash("No tienes permiso para acceder a este módulo.", "danger")
            return redirect(url_for("dashboard"))
    obras = db.get_obras()
    id_obra = request.args.get("obra", "")
    conceptos = []
    acumulados = {}
    obra_nombre = ""
    codigos_costo = []

    # Filtrar obras por permiso para no-admin
    if rol != "admin":
        obras_perm = db.get_obras_permitidas(user["id"], "requisiciones_presupuesto", "leer")
        ids_permitidos = {o["id_obra"] for o in obras_perm}
        obras = [o for o in obras if o["id"] in ids_permitidos]

    if id_obra:
        id_obra = int(id_obra)
        obra = db.get_obra(id_obra)
        obra_nombre = obra["nombre"] if obra else ""
        conceptos = db.get_presupuesto_obra(id_obra)
        codigos_costo = db.get_codigos_costo() if hasattr(db, 'get_codigos_costo') else []
        # Calcular acumulados para cada concepto
        for c in conceptos:
            if c.get("id_codigo_costo"):
                acumulados[c["id"]] = db.get_cantidad_requisitada_acumulada(id_obra, c["id_codigo_costo"])
            else:
                acumulados[c["id"]] = 0

    return render_template("presupuesto_obra.html", user=user, obras=obras,
                           id_obra=id_obra, conceptos=conceptos, acumulados=acumulados,
                           obra_nombre=obra_nombre, codigos_costo=codigos_costo)


@app.route("/requisiciones/presupuesto-obra/agregar", methods=["POST"])
@login_required
def presupuesto_obra_agregar():
    """Agrega un concepto al presupuesto de una obra."""
    user = get_current_user()
    rol = session.get("user_rol", "cliente")
    f = request.form
    id_obra = int(f["id_obra"])
    # Verificar permiso por obra o admin
    if rol != "admin":
        obras_perm = db.get_obras_permitidas(user["id"], "requisiciones_presupuesto", "crear")
        ids_permitidos = {o["id_obra"] for o in obras_perm}
        if id_obra not in ids_permitidos:
            flash("No tienes permiso para modificar el presupuesto de esta obra.", "danger")
            return redirect(url_for("presupuesto_obra", obra=id_obra))
    # Validar código de costo obligatorio
    if not f.get("id_codigo_costo"):
        flash("El código de costo es obligatorio.", "danger")
        return redirect(url_for("presupuesto_obra", obra=id_obra))
    cantidad = float(f.get("cantidad_presupuestada") or 0)
    pu = float(f.get("precio_unitario") or 0)
    importe = float(f.get("importe_presupuestado") or 0)
    if importe == 0 and cantidad > 0 and pu > 0:
        importe = round(cantidad * pu, 2)
    datos = {
        "id_obra": id_obra,
        "id_codigo_costo": int(f["id_codigo_costo"]),
        "concepto": f["concepto"].strip(),
        "unidad": f.get("unidad", "m³"),
        "cantidad_presupuestada": cantidad,
        "precio_unitario": pu,
        "importe_presupuestado": importe,
    }
    try:
        db.crear_presupuesto_concepto(datos)
        flash("Concepto agregado al presupuesto.", "success")
    except Exception as e:
        flash(f"Error al agregar el concepto: {e}", "danger")
    return redirect(url_for("presupuesto_obra", obra=id_obra))


@app.route("/requisiciones/presupuesto-obra/<int:cid>/editar", methods=["POST"])
@login_required
def presupuesto_obra_editar(cid):
    """Edita un concepto del presupuesto de una obra."""
    user = get_current_user()
    rol = session.get("user_rol", "cliente")
    f = request.form
    id_obra = int(f["id_obra"])
    # Verificar permiso por obra o admin
    if rol != "admin":
        obras_perm = db.get_obras_permitidas(user["id"], "requisiciones_presupuesto", "editar")
        ids_permitidos = {o["id_obra"] for o in obras_perm}
        if id_obra not in ids_permitidos:
            flash("No tienes permiso para modificar el presupuesto de esta obra.", "danger")
            return redirect(url_for("presupuesto_obra", obra=id_obra))
    if not f.get("id_codigo_costo"):
        flash("El código de costo es obligatorio.", "danger")
        return redirect(url_for("presupuesto_obra", obra=id_obra))
    cantidad = float(f.get("cantidad_presupuestada") or 0)
    pu = float(f.get("precio_unitario") or 0)
    importe = float(f.get("importe_presupuestado") or 0)
    if importe == 0 and cantidad > 0 and pu > 0:
        importe = round(cantidad * pu, 2)
    datos = {
        "concepto":              f["concepto"].strip(),
        "unidad":                f.get("unidad", "m³"),
        "cantidad_presupuestada": cantidad,
        "precio_unitario":       pu,
        "importe_presupuestado": importe,
        "id_codigo_costo":       int(f["id_codigo_costo"]),
    }
    try:
        db.actualizar_presupuesto_concepto(cid, datos)
        flash("Concepto actualizado.", "success")
    except Exception as e:
        flash(f"Error al actualizar el concepto: {e}", "danger")
    return redirect(url_for("presupuesto_obra", obra=id_obra))


@app.route("/requisiciones/presupuesto-obra/<int:cid>/eliminar", methods=["POST"])
@login_required
def presupuesto_obra_eliminar(cid):
    """Elimina (desactiva) un concepto del presupuesto."""
    user = get_current_user()
    rol = session.get("user_rol", "cliente")
    id_obra = request.form.get("obra", "")
    # Verificar permiso por obra o admin
    if rol != "admin" and id_obra:
        obras_perm = db.get_obras_permitidas(user["id"], "requisiciones_presupuesto", "eliminar")
        ids_permitidos = {o["id_obra"] for o in obras_perm}
        if int(id_obra) not in ids_permitidos:
            flash("No tienes permiso para modificar el presupuesto de esta obra.", "danger")
            return redirect(url_for("presupuesto_obra", obra=id_obra))
    db.eliminar_presupuesto_concepto(cid)
    flash("Concepto eliminado del presupuesto.", "success")
    return redirect(url_for("presupuesto_obra", obra=id_obra))


@app.route("/requisiciones/presupuesto-obra/importar", methods=["POST"])
@login_required
def presupuesto_obra_importar():
    """Importa presupuesto desde archivo Excel."""
    user = get_current_user()
    rol = session.get("user_rol", "cliente")
    f = request.form
    id_obra = int(f["id_obra"])
    # Verificar permiso por obra o admin
    if rol != "admin":
        obras_perm = db.get_obras_permitidas(user["id"], "requisiciones_presupuesto", "crear")
        ids_permitidos = {o["id_obra"] for o in obras_perm}
        if id_obra not in ids_permitidos:
            flash("No tienes permiso para modificar el presupuesto de esta obra.", "danger")
            return redirect(url_for("presupuesto_obra", obra=id_obra))
    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        flash("Selecciona un archivo Excel.", "danger")
        return redirect(url_for("presupuesto_obra", obra=id_obra))
    try:
        from openpyxl import load_workbook
        wb = load_workbook(archivo, data_only=True)
        creados = db.importar_presupuesto_obra_excel(wb, id_obra)
        flash(f"Presupuesto importado: {creados} concepto(s).", "success")
    except Exception as e:
        flash(f"Error al importar: {e}", "danger")
    return redirect(url_for("presupuesto_obra", obra=id_obra))


# ══════════════════════════════════════════════════════════════════
#  PRESUPUESTO — GASTOS PREVISTOS (resumen ejecutivo por categoría)
# ══════════════════════════════════════════════════════════════════

@app.route("/presupuesto/gastos-previstos")
@login_required
@permiso_requerido("analisis_financiero", "leer")
def gastos_previstos():
    """Vista resumen: Presupuesto - Gastos Previstos por obra."""
    user = get_current_user()
    obras = db.get_obras()
    id_obra = request.args.get("obra", type=int)
    resumen = []
    obra_nombre = ""
    totales = {"presupuestado": 0, "real": 0, "gastado": 0, "pct": 0}

    if id_obra:
        obra = db.get_obra(id_obra)
        obra_nombre = obra["nombre"] if obra else ""
        resumen = db.get_resumen_gastos_previstos(id_obra)
        totales["presupuestado"] = sum(r["presupuestado"] for r in resumen)
        totales["real"] = sum(r["real"] for r in resumen)
        totales["gastado"] = sum(r["gastado"] for r in resumen)
        totales["pct"] = round((totales["gastado"] / totales["presupuestado"] * 100), 1) if totales["presupuestado"] > 0 else 0

    return render_template("presupuesto_gastos_previstos.html", user=user, obras=obras,
                           id_obra=id_obra, resumen=resumen, obra_nombre=obra_nombre, totales=totales)


@app.route("/presupuesto/gastos-previstos/guardar", methods=["POST"])
@login_required
@permiso_requerido("analisis_financiero", "editar")
def gastos_previstos_guardar():
    """Guarda/actualiza los montos presupuestados por categoría."""
    id_obra = int(request.form["id_obra"])
    categorias_montos = {}
    for key, val in request.form.items():
        if key.startswith("cat_"):
            cat_name = key[4:].replace("_", " ").upper()
            categorias_montos[cat_name] = val
    db.guardar_gastos_previstos(id_obra, categorias_montos)
    flash("Presupuesto de gastos previstos actualizado.", "success")
    return redirect(url_for("gastos_previstos", obra=id_obra))


@app.route("/presupuesto/gastos-previstos/importar", methods=["POST"])
@login_required
@permiso_requerido("analisis_financiero", "crear")
def gastos_previstos_importar():
    """Importa gastos previstos desde Excel."""
    id_obra = int(request.form["id_obra"])
    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        flash("Selecciona un archivo Excel.", "danger")
        return redirect(url_for("gastos_previstos", obra=id_obra))
    try:
        from openpyxl import load_workbook
        wb = load_workbook(archivo, data_only=True)
        ws = wb.worksheets[0]
        filas = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if row[0]:
                filas.append({
                    "categoria": str(row[0]).strip(),
                    "monto_presupuestado": float(row[1] or 0) if len(row) > 1 and row[1] else 0,
                })
        creados = db.importar_gastos_previstos_excel(id_obra, filas)
        flash(f"Importado: {creados} categoría(s) actualizadas.", "success")
    except Exception as e:
        flash(f"Error al importar: {e}", "danger")
    return redirect(url_for("gastos_previstos", obra=id_obra))


# ══════════════════════════════════════════════════════════════════
#  INSUMOS DE LA PROPUESTA (Concurso/Licitación)
# ══════════════════════════════════════════════════════════════════

@app.route("/insumos-propuesta")
@login_required
@permiso_requerido("insumos_propuesta", "leer")
def insumos_propuesta():
    """Vista principal: catálogo de insumos concursados + requisiciones dinámicas."""
    user = get_current_user()
    search = request.args.get("q", "")
    resumen, max_req = db.get_resumen_insumos_propuesta()

    # Filtrar por búsqueda
    if search:
        term = search.lower()
        resumen = [r for r in resumen if term in r["concepto"].lower() or term in r["unidad"].lower()]

    # Totales concursado
    total_concursado = sum(r["importe_concursado"] for r in resumen)

    return render_template("insumos_propuesta.html", user=user, resumen=resumen,
                           max_req=max_req, search=search, total_concursado=total_concursado)


@app.route("/insumos-propuesta/agregar", methods=["POST"])
@login_required
@permiso_requerido("insumos_propuesta", "crear")
def insumos_propuesta_agregar():
    """Agrega un insumo al catálogo del concurso."""
    f = request.form
    db.crear_insumo_propuesta({
        "concepto": f["concepto"],
        "unidad": f.get("unidad", "pza"),
        "cantidad_concursada": f.get("cantidad_concursada", 0),
        "precio_concursado": f.get("precio_concursado", 0),
        "importe_concursado": f.get("importe_concursado") or None,
        "observaciones": f.get("observaciones"),
    })
    flash("Insumo agregado al catálogo.", "success")
    return redirect(url_for("insumos_propuesta"))


@app.route("/insumos-propuesta/<int:iid>/editar", methods=["POST"])
@login_required
@permiso_requerido("insumos_propuesta", "editar")
def insumos_propuesta_editar(iid):
    """Edita un insumo existente."""
    f = request.form
    db.actualizar_insumo_propuesta(iid, {
        "concepto": f["concepto"],
        "unidad": f.get("unidad", "pza"),
        "cantidad_concursada": f.get("cantidad_concursada", 0),
        "precio_concursado": f.get("precio_concursado", 0),
        "importe_concursado": f.get("importe_concursado") or None,
        "observaciones": f.get("observaciones"),
    })
    flash("Insumo actualizado.", "success")
    return redirect(url_for("insumos_propuesta"))


@app.route("/insumos-propuesta/<int:iid>/eliminar", methods=["POST"])
@login_required
@permiso_requerido("insumos_propuesta", "editar")
def insumos_propuesta_eliminar(iid):
    """Elimina (desactiva) un insumo."""
    db.eliminar_insumo_propuesta(iid)
    flash("Insumo eliminado.", "success")
    return redirect(url_for("insumos_propuesta"))


@app.route("/insumos-propuesta/importar", methods=["POST"])
@login_required
@permiso_requerido("insumos_propuesta", "crear")
def insumos_propuesta_importar():
    """Importa insumos del concurso desde Excel."""
    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        flash("Selecciona un archivo Excel.", "danger")
        return redirect(url_for("insumos_propuesta"))
    try:
        from openpyxl import load_workbook
        wb = load_workbook(archivo, data_only=True)
        creados = db.importar_insumos_propuesta_excel(wb)
        flash(f"Importado: {creados} insumo(s) del concurso.", "success")
    except Exception as e:
        flash(f"Error al importar: {e}", "danger")
    return redirect(url_for("insumos_propuesta"))


@app.route("/insumos-propuesta/requisicion", methods=["POST"])
@login_required
@permiso_requerido("insumos_propuesta", "crear")
def insumos_propuesta_req():
    """Agrega una requisición a uno o varios insumos."""
    f = request.form
    numero_req = int(f.get("numero_requisicion") or (db.get_max_numero_requisicion() + 1))
    proveedor = f.get("proveedor", "").strip() or None
    fecha = f.get("fecha") or None

    # Se envían múltiples insumos: insumo_id[], cantidad[], precio[]
    ids = request.form.getlist("insumo_id[]")
    cantidades = request.form.getlist("req_cantidad[]")
    precios = request.form.getlist("req_precio[]")

    count = 0
    for i, iid in enumerate(ids):
        if not iid:
            continue
        cant = float(cantidades[i]) if i < len(cantidades) and cantidades[i] else 0
        precio = float(precios[i]) if i < len(precios) and precios[i] else 0
        if cant > 0 or precio > 0:
            db.agregar_requisicion_insumo(int(iid), numero_req, cant, precio, proveedor, fecha)
            count += 1

    if count:
        flash(f"Requisición #{numero_req} registrada para {count} insumo(s).", "success")
    else:
        flash("No se registraron datos — ingresa al menos una cantidad.", "warning")
    return redirect(url_for("insumos_propuesta"))


@app.route("/insumos-propuesta/requisicion/<int:rid>/eliminar", methods=["POST"])
@login_required
@permiso_requerido("insumos_propuesta", "editar")
def insumos_propuesta_req_eliminar(rid):
    """Elimina una línea de requisición."""
    db.eliminar_requisicion_insumo(rid)
    flash("Línea de requisición eliminada.", "success")
    return redirect(url_for("insumos_propuesta"))


# ══════════════════════════════════════════════════════════════════
#  PROGRAMA DE EJECUCIÓN DE MANO DE OBRA
# ══════════════════════════════════════════════════════════════════

@app.route("/programa-mano-obra")
@login_required
@permiso_requerido("programa_mano_obra", "leer")
def programa_mano_obra():
    """Vista principal: programa de ejecución de mano de obra por semana."""
    user = get_current_user()
    search = request.args.get("q", "")
    resumen, max_sem = db.get_resumen_programa_mano_obra()

    if search:
        term = search.lower()
        resumen = [r for r in resumen if term in r["concepto"].lower() or term in r["partida"].lower() or term in r["trabajo"].lower()]

    return render_template("programa_mano_obra.html", user=user, resumen=resumen,
                           max_sem=max_sem, search=search)


@app.route("/programa-mano-obra/agregar", methods=["POST"])
@login_required
@permiso_requerido("programa_mano_obra", "crear")
def programa_mano_obra_agregar():
    """Agrega un concepto al programa."""
    f = request.form
    db.crear_concepto_mano_obra({
        "partida": f.get("partida", "").strip(),
        "trabajo": f.get("trabajo", "").strip(),
        "concepto": f["concepto"],
        "unidad": f.get("unidad", "pza"),
        "observaciones": f.get("observaciones"),
    })
    flash("Concepto agregado al programa.", "success")
    return redirect(url_for("programa_mano_obra"))


@app.route("/programa-mano-obra/<int:cid>/eliminar", methods=["POST"])
@login_required
@permiso_requerido("programa_mano_obra", "editar")
def programa_mano_obra_eliminar(cid):
    """Elimina un concepto del programa."""
    db.eliminar_concepto_mano_obra(cid)
    flash("Concepto eliminado.", "success")
    return redirect(url_for("programa_mano_obra"))


@app.route("/programa-mano-obra/guardar-semanas", methods=["POST"])
@login_required
@permiso_requerido("programa_mano_obra", "editar")
def programa_mano_obra_guardar():
    """Guarda los valores de semanas editados."""
    f = request.form
    datos = []
    for key, val in f.items():
        # Keys format: sem_{id_concepto}_{numero_semana}
        if key.startswith("sem_") and val:
            parts = key.split("_")
            if len(parts) == 3:
                try:
                    datos.append({
                        "id_concepto": int(parts[1]),
                        "numero_semana": int(parts[2]),
                        "cantidad": float(val or 0),
                    })
                except (ValueError, IndexError):
                    pass
    if datos:
        db.guardar_programa_semanas_batch(datos)
        flash(f"Programa actualizado ({len(datos)} celdas).", "success")
    else:
        flash("No se detectaron cambios.", "warning")
    return redirect(url_for("programa_mano_obra"))


@app.route("/programa-mano-obra/agregar-semana", methods=["POST"])
@login_required
@permiso_requerido("programa_mano_obra", "editar")
def programa_mano_obra_agregar_semana():
    """Agrega una nueva semana (columna) al programa."""
    conceptos = db.get_programa_mano_obra()
    if not conceptos:
        # Las semanas se muestran como columnas de la tabla, ligadas a los
        # conceptos. Sin conceptos no hay dónde mostrarlas.
        flash("Primero agrega al menos un concepto. Las semanas aparecen como "
              "columnas de la tabla una vez que existe un concepto.", "warning")
        return redirect(url_for("programa_mano_obra"))
    max_sem = db.get_max_semana_mano_obra()
    nueva = max_sem + 1
    # Crear una celda vacía para que la nueva semana (columna) aparezca
    db.guardar_semana_mano_obra(conceptos[0]["id"], nueva, 0)
    flash(f"Semana {nueva} agregada. Aparece como una nueva columna en la tabla; "
          f"usa «Editar cantidades» para capturar los valores.", "success")
    return redirect(url_for("programa_mano_obra"))


@app.route("/programa-mano-obra/importar", methods=["POST"])
@login_required
@permiso_requerido("programa_mano_obra", "crear")
def programa_mano_obra_importar():
    """Importa el programa desde Excel."""
    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        flash("Selecciona un archivo Excel.", "danger")
        return redirect(url_for("programa_mano_obra"))
    try:
        from openpyxl import load_workbook
        wb = load_workbook(archivo, data_only=True)
        creados = db.importar_programa_mano_obra_excel(wb)
        flash(f"Importado: {creados} concepto(s) con sus semanas.", "success")
    except Exception as e:
        flash(f"Error al importar: {e}", "danger")
    return redirect(url_for("programa_mano_obra"))


# ══════════════════════════════════════════════════════════════════
#  ANÁLISIS FINANCIERO (Flujo de Efectivo Semanal)
# ══════════════════════════════════════════════════════════════════

@app.route("/analisis-financiero")
@login_required
@permiso_requerido("analisis_financiero", "leer")
def analisis_financiero():
    """Vista principal: Análisis Financiero semanal por obra."""
    user = get_current_user()
    obras = db.get_obras()
    id_obra = request.args.get("obra", type=int)
    resumen = None
    obra_nombre = ""

    if id_obra:
        obra = db.get_obra(id_obra)
        obra_nombre = obra["nombre"] if obra else ""
        resumen = db.get_resumen_analisis_financiero(id_obra)

    return render_template("analisis_financiero.html", user=user, obras=obras,
                           id_obra=id_obra, resumen=resumen, obra_nombre=obra_nombre)


@app.route("/analisis-financiero/config", methods=["POST"])
@login_required
@permiso_requerido("analisis_financiero", "editar")
def analisis_financiero_config():
    """Guarda configuración del análisis financiero."""
    f = request.form
    id_obra = int(f["id_obra"])
    db.guardar_analisis_financiero_config(id_obra, {
        "costo_contrato": f.get("costo_contrato", 0),
        "pct_anticipo": f.get("pct_anticipo", 20),
        "pct_fondo_garantia": f.get("pct_fondo_garantia", 10),
        "pct_retencion_extra": f.get("pct_retencion_extra", 2),
        "label_retencion_extra": f.get("label_retencion_extra", "Retención 2% SUTERM"),
        "fecha_inicio": f.get("fecha_inicio") or None,
        "semanas_proyecto": f.get("semanas_proyecto", 52),
    })
    flash("Configuración financiera guardada.", "success")
    return redirect(url_for("analisis_financiero", obra=id_obra))


@app.route("/analisis-financiero/egresos", methods=["POST"])
@login_required
@permiso_requerido("analisis_financiero", "editar")
def analisis_financiero_egresos():
    """DESACTIVADO — los egresos ahora se calculan automáticamente desde las requisiciones."""
    id_obra = int(request.form.get("id_obra", 0))
    flash("Los egresos ahora se calculan automáticamente desde las requisiciones pagadas.", "info")
    return redirect(url_for("analisis_financiero", obra=id_obra))


@app.route("/analisis-financiero/celda")
@login_required
@permiso_requerido("analisis_financiero", "leer")
def analisis_financiero_celda():
    """API JSON — devuelve las partidas que componen una celda (obra+semana+rubro)."""
    id_obra    = request.args.get("obra", type=int)
    semana_num = request.args.get("semana", type=int, default=0)
    rubro_clave= request.args.get("rubro", "")
    if not id_obra or not rubro_clave:
        return jsonify({"ok": False, "error": "Parámetros incompletos"}), 400

    partidas = db.get_partidas_egreso_celda(id_obra, semana_num, rubro_clave)
    datos = []
    for p in (partidas or []):
        datos.append({
            "id":          p.get("id"),
            "requisicion": p.get("semana") or "",
            "proveedor":   p.get("proveedor") or "—",
            "concepto":    p.get("concepto") or "—",
            "codigo_cc":   p.get("codigo_cc") or "—",
            "desc_cc":     p.get("desc_cc") or "",
            "monto":       float(p.get("monto_autorizado") or 0),
            "fecha_pago":  str(p.get("fecha_pago") or ""),
        })
    return jsonify({"ok": True, "partidas": datos})


@app.route("/analisis-financiero/ingresos", methods=["POST"])
@login_required
@permiso_requerido("analisis_financiero", "editar")
def analisis_financiero_ingresos():
    """Guarda ingresos de una semana."""
    f = request.form
    id_obra = int(f["id_obra"])
    semana = int(f["numero_semana"])
    db.guardar_ingresos_semana(id_obra, semana, {
        "inversion": f.get("inversion", 0),
        "anticipo": f.get("anticipo", 0),
        "importe_estimado": f.get("importe_estimado", 0),
        "devolucion_fondo_garantia": f.get("devolucion_fondo_garantia", 0),
        "devolucion_apoyos": f.get("devolucion_apoyos", 0),
        "amortizacion_anticipo": f.get("amortizacion_anticipo", 0),
        "retencion_fondo_garantia": f.get("retencion_fondo_garantia", 0),
        "retencion_extra": f.get("retencion_extra", 0),
        "importe_liquido_pagado": f.get("importe_liquido_pagado", 0),
    })
    flash(f"Ingresos semana {semana} guardados.", "success")
    return redirect(url_for("analisis_financiero", obra=id_obra))


# ══════════════════════════════════════════════════════════════════
#  LIQUIDACIÓN DE OBRA (Cierre financiero)
# ══════════════════════════════════════════════════════════════════

@app.route("/liquidacion-obra")
@login_required
@permiso_requerido("liquidacion_obra", "leer")
def liquidacion_obra():
    """Vista: Liquidación de obra (cierre financiero)."""
    user = get_current_user()
    obras = db.get_obras()
    id_obra = request.args.get("obra", type=int)
    liquidacion = None
    obra_data = None
    beneficio = 0
    pct_beneficio = 0

    if id_obra:
        obra_data = db.get_obra(id_obra)
        liquidacion = db.get_liquidacion_obra(id_obra)

        if not liquidacion:
            # Auto-calcular desde datos existentes
            auto = db.calcular_liquidacion_automatica(id_obra)
            liquidacion = auto
            liquidacion["cliente"] = ""
            liquidacion["no_proyecto"] = ""
            liquidacion["fecha"] = None
            liquidacion["observaciones"] = ""
        else:
            liquidacion = dict(liquidacion)

        presup = float(liquidacion.get("presupuesto_contratado") or 0)
        real = float(liquidacion.get("importe_real") or 0)
        beneficio = presup - real
        pct_beneficio = round((beneficio / presup * 100), 2) if presup > 0 else 0

    return render_template("liquidacion_obra.html", user=user, obras=obras,
                           id_obra=id_obra, liquidacion=liquidacion, obra_data=obra_data,
                           beneficio=beneficio, pct_beneficio=pct_beneficio)


@app.route("/liquidacion-obra/guardar", methods=["POST"])
@login_required
@permiso_requerido("liquidacion_obra", "editar")
def liquidacion_obra_guardar():
    """Guarda la liquidación de una obra."""
    f = request.form
    id_obra = int(f["id_obra"])
    db.guardar_liquidacion_obra(id_obra, {
        "cliente": f.get("cliente", "").strip(),
        "no_proyecto": f.get("no_proyecto", "").strip(),
        "fecha": f.get("fecha") or None,
        "presupuesto_contratado": f.get("presupuesto_contratado", 0),
        "importe_real": f.get("importe_real", 0),
        "total_aportaciones": f.get("total_aportaciones", 0),
        "mano_obra": f.get("mano_obra", 0),
        "materiales": f.get("materiales", 0),
        "equipo_seguridad": f.get("equipo_seguridad", 0),
        "herramienta_equipo": f.get("herramienta_equipo", 0),
        "impuestos": f.get("impuestos", 0),
        "indirectos": f.get("indirectos", 0),
        "observaciones": f.get("observaciones", ""),
    })
    flash("Liquidación de obra guardada.", "success")
    return redirect(url_for("liquidacion_obra", obra=id_obra))


@app.route("/liquidacion-obra/recalcular", methods=["POST"])
@login_required
@permiso_requerido("liquidacion_obra", "editar")
def liquidacion_obra_recalcular():
    """Recalcula la liquidación desde los módulos existentes."""
    id_obra = int(request.form["id_obra"])
    auto = db.calcular_liquidacion_automatica(id_obra)
    # Mantener cliente/proyecto/fecha de la liquidación existente
    liq = db.get_liquidacion_obra(id_obra)
    auto["cliente"] = liq["cliente"] if liq else ""
    auto["no_proyecto"] = liq["no_proyecto"] if liq else ""
    auto["fecha"] = liq["fecha"] if liq else None
    auto["observaciones"] = liq["observaciones"] if liq else ""
    db.guardar_liquidacion_obra(id_obra, auto)
    flash("Liquidación recalculada desde datos del sistema.", "success")
    return redirect(url_for("liquidacion_obra", obra=id_obra))


# ══════════════════════════════════════════════════════════════════
#  CONTROL DE INGRESOS
# ══════════════════════════════════════════════════════════════════

@app.route("/control-ingresos")
@login_required
@permiso_requerido("control_ingresos", "leer")
def control_ingresos():
    """Vista principal: Control de Ingresos."""
    user = get_current_user()
    obras = db.get_obras()
    id_obra = request.args.get("obra", type=int)
    estatus = request.args.get("estatus", "")
    search = request.args.get("q", "")

    registros = db.get_control_ingresos(id_obra=id_obra, estatus=estatus or None, search=search or None)
    totales = db.get_totales_ingresos(id_obra=id_obra)
    egresos_pagados = db.get_egresos_pagados_obra(id_obra=id_obra)
    totales_egresos = db.get_totales_egresos_pagados(id_obra=id_obra)

    return render_template("control_ingresos.html", user=user, obras=obras,
                           registros=registros, totales=totales,
                           egresos_pagados=egresos_pagados,
                           totales_egresos=totales_egresos,
                           id_obra=id_obra, filtro_estatus=estatus, search=search)


@app.route("/control-ingresos/agregar", methods=["POST"])
@login_required
@permiso_requerido("control_ingresos", "crear")
def control_ingresos_agregar():
    """Agrega un registro de ingreso."""
    f = request.form
    db.crear_ingreso({
        "id_obra": int(f["id_obra"]) if f.get("id_obra") else None,
        "descripcion": f["descripcion"],
        "tipo_ingreso": f.get("tipo_ingreso", "").strip(),
        "no_factura": f.get("no_factura", "").strip(),
        "fecha_tramite": f.get("fecha_tramite") or None,
        "estatus": f.get("estatus", "pendiente"),
        "importe": f.get("importe", 0),
        "deduccion_retencion": f.get("deduccion_retencion", 0),
        "iva": f.get("iva", 0),
        "aportaciones_despues_iva": f.get("aportaciones_despues_iva", 0),
        "liquido_pagado": f.get("liquido_pagado", 0),
        "observaciones": f.get("observaciones", ""),
        "creado_por": session.get("user_id"),
    })
    flash("Ingreso registrado.", "success")
    return redirect(url_for("control_ingresos", obra=f.get("id_obra", "")))


@app.route("/control-ingresos/<int:iid>/editar", methods=["POST"])
@login_required
@permiso_requerido("control_ingresos", "editar")
def control_ingresos_editar(iid):
    """Edita un registro de ingreso."""
    f = request.form
    db.actualizar_ingreso(iid, {
        "id_obra": int(f["id_obra"]) if f.get("id_obra") else None,
        "descripcion": f["descripcion"],
        "tipo_ingreso": f.get("tipo_ingreso", "").strip(),
        "no_factura": f.get("no_factura", "").strip(),
        "fecha_tramite": f.get("fecha_tramite") or None,
        "estatus": f.get("estatus", "pendiente"),
        "importe": f.get("importe", 0),
        "deduccion_retencion": f.get("deduccion_retencion", 0),
        "iva": f.get("iva", 0),
        "aportaciones_despues_iva": f.get("aportaciones_despues_iva", 0),
        "liquido_pagado": f.get("liquido_pagado", 0),
        "observaciones": f.get("observaciones", ""),
    })
    flash("Ingreso actualizado.", "success")
    return redirect(url_for("control_ingresos", obra=f.get("id_obra", "")))


@app.route("/control-ingresos/<int:iid>/eliminar", methods=["POST"])
@login_required
@permiso_requerido("control_ingresos", "editar")
def control_ingresos_eliminar(iid):
    """Elimina un registro de ingreso."""
    db.eliminar_ingreso(iid)
    flash("Ingreso eliminado.", "success")
    return redirect(url_for("control_ingresos"))


@app.route("/requisiciones/codigos-costo")
@login_required
@permiso_requerido("codigos_costo", "leer")
def codigos_costo():
    user = get_current_user()
    rol = session.get("user_rol", "cliente")
    search = request.args.get("q", "")
    lista = db.get_codigos_costo(search=search or None)
    if rol == "admin":
        puede_crear = True
        puede_editar = True
    else:
        obras_crear = db.get_obras_permitidas(user["id"], "codigos_costo", "crear")
        obras_editar = db.get_obras_permitidas(user["id"], "codigos_costo", "editar")
        puede_crear = bool(obras_crear)
        puede_editar = bool(obras_editar)
    return render_template("codigos_costo.html", user=user, codigos=lista, search=search,
                           puede_crear=puede_crear, puede_editar=puede_editar)


@app.route("/requisiciones/codigos-costo/importar", methods=["GET", "POST"])
@login_required
@permiso_requerido("codigos_costo", "crear")
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


@app.route("/requisiciones/codigos-costo/nuevo", methods=["GET", "POST"])
@login_required
@permiso_requerido("codigos_costo", "crear")
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


@app.route("/requisiciones/codigos-costo/<int:cid>/editar", methods=["GET", "POST"])
@login_required
@permiso_requerido("codigos_costo", "editar")
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


@app.route("/requisiciones/codigos-costo/<int:cid>/toggle", methods=["POST"])
@login_required
@permiso_requerido("codigos_costo", "editar")
def codigo_costo_toggle(cid):
    db.execute("UPDATE codigos_costo SET activo = NOT activo WHERE id=%s", (cid,))
    flash("Estado actualizado.", "success")
    return redirect(url_for("codigos_costo"))


@app.route("/requisiciones/codigos-costo/crear-ajax", methods=["POST"])
@login_required
@permiso_requerido("codigos_costo", "crear")
def codigo_costo_crear_ajax():
    """Crea un código de costo via AJAX desde el formulario de requisición."""
    from flask import jsonify
    f = request.form
    n1 = f.get("nivel1", "").strip() or None
    n2 = f.get("nivel2", "").strip() or None
    n3 = f.get("nivel3", "").strip() or None
    n4 = f.get("nivel4", "").strip() or None
    n5 = f.get("nivel5", "").strip() or None
    desc = f.get("descripcion", "").strip()
    tipo = f.get("tipo_costo", "").strip() or None
    if not desc:
        return jsonify({"ok": False, "error": "Descripción obligatoria"})
    niveles = [n for n in (n1, n2, n3, n4, n5) if n]
    if not niveles:
        return jsonify({"ok": False, "error": "Al menos un nivel es obligatorio"})
    codigo = "-".join(niveles)
    cid = db.upsert_codigo_costo(codigo, desc, n1, n2, n3, n4, n5, tipo)
    return jsonify({"ok": True, "id": cid, "codigo": codigo, "descripcion": desc})


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
    usuarios = db.get_usuarios()
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
    return render_template("analisis_compra_form.html", user=user, obras=obras, usuarios=usuarios)


@app.route("/analisis-compra/<int:aid>")
@login_required
@permiso_requerido("analisis_compra", "leer")
def analisis_compra_detalle(aid):
    analisis = db.get_analisis(aid)
    if not analisis:
        abort(404)
    user = get_current_user()
    cotizaciones = db.get_cotizaciones_analisis(aid)
    proveedores = db.get_proveedores()

    import decimal as _decimal
    def _cot_jsonable(v):
        if isinstance(v, _decimal.Decimal):
            return float(v)
        if isinstance(v, (datetime, date)):
            return str(v)
        return v
    cotizaciones_json = []
    for c in cotizaciones:
        cd = {k: _cot_jsonable(v) for k, v in c.items() if k != "items"}
        cd["items"] = [{k: _cot_jsonable(v) for k, v in it.items()} for it in c.get("items", [])]
        cotizaciones_json.append(cd)

    return render_template("analisis_compra_detalle.html", user=user, analisis=analisis,
                           cotizaciones=cotizaciones, proveedores=proveedores,
                           cotizaciones_json=cotizaciones_json)


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


@app.route("/analisis-compra/<int:aid>/cotizacion/<int:cid>/editar", methods=["POST"])
@login_required
@permiso_requerido("analisis_compra", "editar")
def analisis_compra_cotizacion_editar(aid, cid):
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
    db.actualizar_cotizacion_analisis(cid, f["proveedor"].strip(), f.get("numero_cotizacion") or None,
                                       f.get("fecha_visita") or None, f.get("observaciones") or None, items)
    flash("Cotización actualizada.", "success")
    return redirect(url_for("analisis_compra_detalle", aid=aid))


@app.route("/analisis-compra/<int:aid>/cotizacion/<int:cid>/eliminar", methods=["POST"])
@login_required
@permiso_requerido("analisis_compra", "eliminar")
def analisis_compra_cotizacion_eliminar(aid, cid):
    db.eliminar_cotizacion_analisis(cid)
    flash("Cotización eliminada.", "success")
    return redirect(url_for("analisis_compra_detalle", aid=aid))


@app.route("/analisis-compra/<int:aid>/vista-previa")
@login_required
@permiso_requerido("analisis_compra", "leer")
def analisis_compra_vista_previa(aid):
    analisis = db.get_analisis(aid)
    if not analisis:
        abort(404)
    user = get_current_user()
    cotizaciones = db.get_cotizaciones_analisis(aid)
    return render_template("analisis_compra_vista_previa.html", user=user, analisis=analisis,
                           cotizaciones=cotizaciones)


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
    _tipo_analisis = "3 - Materiales"
    numero = db.get_siguiente_numero_oc(analisis["id_obra"], tipo_pedido=_tipo_analisis)
    datos = {
        "numero_pedido": numero, "folio": str(numero), "fecha": hoy_str(),
        "tipo_pedido": _tipo_analisis, "id_obra": analisis["id_obra"],
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
#  CONTROL DE AVANCE FÍSICO Y FINANCIERO
# ══════════════════════════════════════════════════════════════════

@app.route("/avance-fisico")
@login_required
@permiso_requerido("avance_fisico", "leer")
def avance_fisico():
    """Vista principal: selección de obra y resumen de avance.
    Todos los campos derivados (%, importes, diferencias, estatus)
    se calculan automáticamente basados en la semana actual del contrato."""
    user = get_current_user()
    obras = db.get_obras()
    id_obra = request.args.get("obra", "todas")
    semana = request.args.get("semana", "")
    tramo_filtro = request.args.get("tramo", "")

    catalogo = []
    kpis = None
    semanas = []
    programa_semana = []
    parametros = None
    resumen_tramos = []
    semana_actual = None

    if id_obra == "todas":
        # Consolidar todas las obras
        todos_conceptos = []
        total_contratado = 0
        total_ejercido = 0
        total_programado = 0
        total_estimado = 0
        total_tramos = set()
        for ob in obras:
            cat_ob = db.get_avance_catalogo(ob["id"])
            todos_conceptos.extend(cat_ob)
            kpis_ob = db.get_avance_kpis(ob["id"])
            if kpis_ob:
                total_contratado += float(kpis_ob.get("importe_contratado") or 0)
                total_ejercido += float(kpis_ob.get("importe_real") or 0)
                total_programado += float(kpis_ob.get("importe_programado") or 0)
                total_estimado += float(kpis_ob.get("importe_estimado") or 0)
                for c in cat_ob:
                    if c.get("tramo"):
                        total_tramos.add(c["tramo"])
        catalogo = todos_conceptos
        if catalogo:
            kpis = {
                "total_conceptos": len(catalogo),
                "total_tramos": len(total_tramos),
                "importe_contratado": total_contratado,
                "importe_real": total_ejercido,
                "importe_programado": total_programado,
                "importe_estimado": total_estimado,
                "semanas_programa": 0,
                "semana_actual": None,
            }
        # Filtrar por tramo si se seleccionó
        if tramo_filtro:
            catalogo = [c for c in catalogo if c.get("tramo") == tramo_filtro]
        tramos = sorted(total_tramos)
    elif id_obra:
        id_obra = int(id_obra)
        # Si el usuario seleccionó una semana, usarla como corte del programado
        semana_corte = int(semana) if semana else None
        kpis = db.get_avance_kpis(id_obra, semana_corte=semana_corte)
        semana_actual = int(kpis["semana_actual"]) if kpis and kpis.get("semana_actual") else None
        # Semana del calendario (misma lógica que combustible: semana 32, 33, etc.)
        semana_calendario = db.calcular_semana_combustible(date.today())
        catalogo = db.get_avance_catalogo(id_obra, semana_corte=semana_corte)
        semanas = db.get_avance_semanas_disponibles(id_obra)
        parametros = db.get_avance_parametros(id_obra)
        resumen_tramos = db.get_avance_resumen_tramos(id_obra, semana_corte=semana_corte)
        if semana:
            programa_semana = db.get_avance_programa_semana(id_obra, int(semana))
        # Filtrar catálogo por tramo si se seleccionó
        if tramo_filtro:
            catalogo = [c for c in catalogo if c["tramo"] == tramo_filtro]
        # Lista de tramos únicos para el filtro
        tramos = list(dict.fromkeys(c["tramo"] for c in db.get_avance_catalogo(id_obra) if c.get("tramo")))
    else:
        tramos = []

    return render_template("avance_fisico.html", user=user, obras=obras,
                           id_obra=id_obra, catalogo=catalogo, kpis=kpis,
                           semanas=semanas, semana=semana, programa_semana=programa_semana,
                           parametros=parametros, resumen_tramos=resumen_tramos,
                           tramos=tramos, tramo_filtro=tramo_filtro,
                           semana_actual=semana_actual,
                           semana_calendario=semana_calendario if id_obra != "todas" else None)


@app.route("/avance-fisico/importar", methods=["GET", "POST"])
@login_required
@permiso_requerido("avance_fisico", "crear")
def avance_fisico_importar():
    """Importa Excel de Control de Avance Físico y Financiero."""
    user = get_current_user()
    obras = db.get_obras()
    if request.method == "GET":
        return render_template("avance_fisico_importar.html", user=user, obras=obras)

    from openpyxl import load_workbook
    archivo = request.files.get("archivo")
    id_obra = request.form.get("id_obra")
    if not archivo or not archivo.filename:
        flash("Selecciona un archivo Excel.", "danger")
        return redirect(url_for("avance_fisico_importar"))
    if not id_obra:
        flash("Selecciona una obra.", "danger")
        return redirect(url_for("avance_fisico_importar"))
    try:
        wb = load_workbook(archivo, data_only=True)
        conceptos, semanas = db.importar_avance_excel(wb, int(id_obra))
    except Exception as e:
        flash(f"Error al importar: {e}", "danger")
        return redirect(url_for("avance_fisico_importar"))
    flash(f"Importación exitosa: {conceptos} conceptos, {semanas} registros semanales.", "success")
    return redirect(url_for("avance_fisico", obra=id_obra))


@app.route("/avance-fisico/registrar", methods=["POST"])
@login_required
@permiso_requerido("avance_fisico", "editar")
def avance_fisico_registrar():
    """Registra avance real de un concepto. Permite múltiples registros
    (acumulativos). El importe se calcula automáticamente desde el P.U."""
    user = get_current_user()
    f = request.form
    id_catalogo = int(f["id_catalogo"])
    id_obra = int(f["id_obra"])
    semana = int(f.get("semana") or 0) if f.get("semana") else None
    fecha = f.get("fecha") or hoy_str()
    cantidad = float(f.get("cantidad_real") or 0)

    if cantidad <= 0:
        flash("La cantidad debe ser mayor a 0.", "danger")
        return redirect(url_for("avance_fisico", obra=id_obra, semana=semana or ""))

    # Validar que no exceda la cantidad contratada
    cat = db.query("SELECT cantidad_contratada, precio_unitario FROM avance_catalogo WHERE id=%s",
                   (id_catalogo,), one=True)
    if cat:
        ya_registrado = db.query("SELECT COALESCE(SUM(cantidad_real),0) AS total FROM avance_real WHERE id_catalogo=%s",
                                 (id_catalogo,), one=True)
        acumulado = float(ya_registrado["total"]) if ya_registrado else 0
        if acumulado + cantidad > float(cat["cantidad_contratada"]) * 1.1:  # Tolerancia del 10%
            flash(f"La cantidad acumulada ({acumulado + cantidad:.2f}) excede la contratada ({cat['cantidad_contratada']}) por más del 10%.", "warning")

    obs = f.get("observaciones") or None
    db.registrar_avance_real(id_catalogo, id_obra, semana, fecha, cantidad, obs, user["id"])
    flash("Avance real registrado correctamente.", "success")
    return redirect(url_for("avance_fisico", obra=id_obra, semana=semana or ""))


@app.route("/avance-fisico/agregar-concepto", methods=["POST"])
@login_required
@permiso_requerido("avance_fisico", "crear")
def avance_fisico_agregar_concepto():
    """Agrega un concepto manualmente al catálogo de avance."""
    f = request.form
    id_obra = int(f.get("id_obra") or f.get("id_obra_modal") or 0)
    if not id_obra:
        flash("Selecciona una obra.", "danger")
        return redirect(url_for("avance_fisico"))
    item_id = int(f["item_id"])
    tramo = f["tramo"].strip()
    codigo = f["codigo"].strip()
    concepto = f["concepto"].strip()
    unidad = f["unidad"].strip()
    cantidad = float(f.get("cantidad_contratada") or 0)
    pu = float(f.get("precio_unitario") or 0)
    importe = round(cantidad * pu, 2)
    # Verificar si ya existe
    existente = db.query("SELECT id FROM avance_catalogo WHERE id_obra=%s AND item_id=%s", (id_obra, item_id), one=True)
    if existente:
        db.execute("""UPDATE avance_catalogo SET tramo=%s, codigo=%s, concepto=%s, unidad=%s,
                      cantidad_contratada=%s, precio_unitario=%s, importe_contratado=%s WHERE id=%s""",
                   (tramo, codigo, concepto, unidad, cantidad, pu, importe, existente["id"]))
        flash(f"Concepto #{item_id} actualizado.", "success")
    else:
        db.execute("""INSERT INTO avance_catalogo (id_obra, item_id, tramo, codigo, concepto, unidad, cantidad_contratada, precio_unitario, importe_contratado)
                      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                   (id_obra, item_id, tramo, codigo, concepto, unidad, cantidad, pu, importe))
        flash(f"Concepto #{item_id} agregado.", "success")
    return redirect(url_for("avance_fisico", obra=id_obra))


@app.route("/avance-fisico/parametros", methods=["POST"])
@login_required
@permiso_requerido("avance_fisico", "editar")
def avance_fisico_parametros():
    """Guarda/actualiza los parámetros del contrato (contrato, fechas, duración)."""
    f = request.form
    id_obra = int(f["id_obra"])
    contrato = f.get("contrato", "").strip()
    fecha_inicio = f.get("fecha_inicio") or None
    fecha_fin = f.get("fecha_fin") or None
    duracion = int(f.get("duracion_dias") or 0) if f.get("duracion_dias") else None

    existing = db.query("SELECT id FROM avance_parametros WHERE id_obra=%s", (id_obra,), one=True)
    if existing:
        db.execute("""UPDATE avance_parametros SET contrato=%s, fecha_inicio=%s, fecha_fin=%s, duracion_dias=%s
                      WHERE id_obra=%s""", (contrato, fecha_inicio, fecha_fin, duracion, id_obra))
    else:
        db.execute("""INSERT INTO avance_parametros (id_obra, contrato, fecha_inicio, fecha_fin, duracion_dias)
                      VALUES (%s, %s, %s, %s, %s)""", (id_obra, contrato, fecha_inicio, fecha_fin, duracion))
    flash("Parámetros del contrato actualizados.", "success")
    return redirect(url_for("avance_fisico", obra=id_obra))


@app.route("/avance-fisico/estimado", methods=["POST"])
@login_required
@permiso_requerido("avance_fisico", "editar")
def avance_fisico_estimado():
    """Registra/actualiza la cantidad estimada (proyección) de un concepto.
    El estimado es un dato manual que se almacena directamente en avance_catalogo.cantidad_estimada.
    Todos los campos derivados (importe_estimado, %fisico_estimado, %financiero_estimado)
    se calculan automáticamente al consultar."""
    f = request.form
    id_obra = int(f["id_obra"])
    id_catalogo = int(f["id_catalogo"])
    cantidad_estimada = float(f.get("cantidad_estimada") or 0)

    db.execute("UPDATE avance_catalogo SET cantidad_estimada=%s WHERE id=%s AND id_obra=%s",
               (cantidad_estimada, id_catalogo, id_obra))
    flash("Avance estimado actualizado.", "success")
    semana = f.get("semana") or ""
    return redirect(url_for("avance_fisico", obra=id_obra, semana=semana))


@app.route("/avance-fisico/captura", methods=["GET", "POST"])
@login_required
@permiso_requerido("avance_captura", "editar")
def avance_fisico_captura():
    """Vista de captura mensual de Avance Físico (pestaña 'Avance Físico' del Excel).
    Grid editable: concepto × mes, con columnas Real y Estimada por cada mes.
    Al guardar, actualiza avance_real y avance_catalogo.cantidad_estimada."""
    user = get_current_user()
    obras = db.get_obras()
    id_obra = request.args.get("obra") or request.form.get("id_obra")

    if not id_obra:
        return render_template("avance_fisico_captura.html", user=user, obras=obras,
                               id_obra=None, meses=[], catalogo=[], parametros=None)

    id_obra = int(id_obra)
    parametros = db.get_avance_parametros(id_obra)
    meses = db.get_meses_contrato(id_obra)

    if request.method == "POST" and meses:
        # Procesar el formulario: recoger todos los valores de la grilla
        datos = []
        catalogo_ids = request.form.getlist("catalogo_ids")
        for cid in catalogo_ids:
            cid = int(cid)
            for m in meses:
                real_key = f"real_{cid}_{m['num']}"
                est_key = f"est_{cid}_{m['num']}"
                real_val = request.form.get(real_key, "").strip()
                est_val = request.form.get(est_key, "").strip()
                datos.append({
                    "id_catalogo": cid,
                    "mes_num": m["num"],
                    "fecha_inicio_mes": m["fecha_inicio"],
                    "fecha_fin_mes": m["fecha_fin"],
                    "real": float(real_val) if real_val else 0,
                    "estimada": float(est_val) if est_val else 0,
                })
        db.guardar_avance_captura_mensual(id_obra, datos, user["id"])
        flash("Avance físico guardado correctamente.", "success")
        return redirect(url_for("avance_fisico_captura", obra=id_obra))

    # GET: mostrar la grilla
    catalogo = db.get_avance_captura_mensual(id_obra, meses) if meses else []

    return render_template("avance_fisico_captura.html", user=user, obras=obras,
                           id_obra=id_obra, meses=meses, catalogo=catalogo,
                           parametros=parametros)


@app.route("/avance-fisico/meses", methods=["POST"])
@login_required
@permiso_requerido("avance_captura", "editar")
def avance_fisico_agregar_mes():
    """Agrega o actualiza un mes en la configuración de captura de la obra."""
    f = request.form
    id_obra = int(f["id_obra"])
    num = int(f["num_mes"])
    label = f.get("label_mes", "").strip() or f"Mes {num}"
    fecha_inicio = f.get("fecha_inicio_mes")
    fecha_fin = f.get("fecha_fin_mes")
    if not fecha_inicio or not fecha_fin:
        flash("Las fechas de inicio y fin del mes son obligatorias.", "danger")
        return redirect(url_for("avance_fisico_captura", obra=id_obra))
    db.agregar_mes_avance(id_obra, num, label, fecha_inicio, fecha_fin)
    flash(f"Mes {num} ({label}) configurado.", "success")
    return redirect(url_for("avance_fisico_captura", obra=id_obra))


@app.route("/avance-fisico/meses/eliminar", methods=["POST"])
@login_required
@permiso_requerido("avance_captura", "editar")
def avance_fisico_eliminar_mes():
    """Elimina un mes de la configuración de captura."""
    f = request.form
    id_obra = int(f["id_obra"])
    num = int(f["num_mes"])
    db.eliminar_mes_avance(id_obra, num)
    flash(f"Mes {num} eliminado.", "success")
    return redirect(url_for("avance_fisico_captura", obra=id_obra))


# ══════════════════════════════════════════════════════════════════
#  CONTROL DE ESTIMACIONES Y AJUSTES DE COSTOS
# ══════════════════════════════════════════════════════════════════

@app.route("/estimaciones")
@login_required
@permiso_requerido("estimaciones", "leer")
def estimaciones():
    """Vista principal: listado de obras con estimaciones."""
    user = get_current_user()
    obras_est = db.get_estimaciones_obras()
    return render_template("estimaciones.html", user=user, obras_est=obras_est)


@app.route("/estimaciones/<int:eid>")
@login_required
@permiso_requerido("estimaciones", "leer")
def estimacion_detalle(eid):
    """Detalle de estimaciones de una obra."""
    user = get_current_user()
    est = db.get_estimacion_obra(eid)
    if not est:
        abort(404)
    periodos = db.get_periodos_estimacion(eid)
    ajustes = db.get_ajustes_estimacion(eid)
    documentos = db.get_documentos_estimacion(eid)
    return render_template("estimacion_detalle.html", user=user, est=est,
                           periodos=periodos, ajustes=ajustes, documentos=documentos)


@app.route("/estimaciones/nueva", methods=["GET", "POST"])
@login_required
@permiso_requerido("estimaciones", "crear")
def estimacion_nueva():
    """Crear registro de estimación para una obra."""
    user = get_current_user()
    obras = db.get_obras()
    if request.method == "POST":
        f = request.form
        datos = {
            "id_obra": int(f["id_obra"]) if f.get("id_obra") else None,
            "identificacion_esma": f.get("identificacion_esma") or None,
            "contrato": f.get("contrato") or None,
            "descripcion": f.get("descripcion") or None,
            "dependencia": f.get("dependencia") or None,
            "fecha_inicio": f.get("fecha_inicio") or None,
            "fecha_fin": f.get("fecha_fin") or None,
            "duracion_dias": int(f["duracion_dias"]) if f.get("duracion_dias") else None,
            "superintendente": f.get("superintendente") or None,
            "tipo_ajuste": f.get("tipo_ajuste") or None,
            "estimaciones_tipo": f.get("estimaciones_tipo") or "Quincenal",
            "monto_contratado": float(f.get("monto_contratado") or 0),
            "monto_cobrado": float(f.get("monto_cobrado") or 0),
            "observaciones": f.get("observaciones") or None,
            "auxiliar": f.get("auxiliar") or None,
        }
        eid = db.crear_estimacion_obra(datos)
        flash("Obra registrada en estimaciones.", "success")
        return redirect(url_for("estimacion_detalle", eid=eid))
    return render_template("estimacion_form.html", user=user, obras=obras, est=None)


@app.route("/estimaciones/<int:eid>/periodo", methods=["POST"])
@login_required
@permiso_requerido("estimaciones", "editar")
def estimacion_agregar_periodo(eid):
    """Agrega un periodo/estimación a una obra."""
    f = request.form
    numero = int(f.get("numero") or 0)
    periodo_label = f.get("periodo_label") or None
    monto = float(f.get("monto") or 0)
    db.crear_periodo_estimacion(eid, numero, periodo_label, monto)
    # Recalcular cobrado sumando todos los periodos
    total_cobrado = db.query("SELECT COALESCE(SUM(monto),0) AS t FROM estimaciones_periodos WHERE id_estimacion_obra=%s",
                             (eid,), one=True)["t"]
    db.actualizar_montos_estimacion(eid, float(total_cobrado))
    flash(f"Estimación #{numero} agregada.", "success")
    return redirect(url_for("estimacion_detalle", eid=eid))


@app.route("/estimaciones/<int:eid>/ajuste", methods=["POST"])
@login_required
@permiso_requerido("estimaciones", "editar")
def estimacion_agregar_ajuste(eid):
    """Agrega fecha de ajuste de costos."""
    f = request.form
    mes = f.get("mes") or ""
    fecha_pub = f.get("fecha_publicacion") or None
    fecha_lim = f.get("fecha_limite") or None
    monto = float(f.get("monto") or 0)
    db.crear_ajuste_costo(eid, mes, fecha_pub, fecha_lim, monto)
    flash(f"Ajuste de costos ({mes}) agregado.", "success")
    return redirect(url_for("estimacion_detalle", eid=eid))


@app.route("/estimaciones/importar", methods=["POST"])
@login_required
@permiso_requerido("estimaciones", "crear")
def estimaciones_importar():
    """Importa obras con estimaciones desde Excel formato ESMA."""
    from openpyxl import load_workbook
    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        flash("Selecciona un archivo.", "danger")
        return redirect(url_for("estimaciones"))
    try:
        wb = load_workbook(archivo, data_only=True)
    except Exception as e:
        flash(f"Error al leer archivo: {e}", "danger")
        return redirect(url_for("estimaciones"))

    # Buscar hoja de estimaciones
    ws = None
    for sheet in wb.worksheets:
        if "estimacion" in sheet.title.lower():
            ws = sheet
            break
    if not ws:
        ws = wb.worksheets[0]

    count = 0
    for row in ws.iter_rows(min_row=3, values_only=True):
        if not row or len(row) < 14:
            continue
        # Columnas: 0=#, 1=Director, 2=Identificacion, 3=Contrato, 4=Descripcion,
        # 5=Dependencia, 6=Inicio, 7=Fin, 8=Duracion, 9=Superintendente, 10=BESOP,
        # 11=TipoAjuste, 12=FechaEntrega, 13=TipoEst, 14=Monto
        num = row[0]
        if not num or not str(num).strip().replace('.', '').isdigit():
            continue
        identificacion = str(row[2] or "").strip()
        if not identificacion:
            continue
        contrato = str(row[3] or "").strip() or None
        descripcion = str(row[4] or "").strip() or None
        dependencia = str(row[5] or "").strip() or None
        fecha_inicio = row[6]
        fecha_fin = row[7]
        duracion = None
        try:
            duracion = int(float(str(row[8]))) if row[8] else None
        except (ValueError, TypeError):
            pass
        superintendente = str(row[9] or "").strip() or None
        tipo_ajuste = str(row[11] or "").strip() or None
        tipo_est = str(row[13] or "").strip() or "Quincenal"
        monto = 0
        try:
            monto = float(str(row[14]).replace("$", "").replace(",", "")) if row[14] else 0
        except (ValueError, TypeError):
            pass

        if hasattr(fecha_inicio, 'strftime'):
            fecha_inicio = fecha_inicio.strftime("%Y-%m-%d")
        else:
            fecha_inicio = None
        if hasattr(fecha_fin, 'strftime'):
            fecha_fin = fecha_fin.strftime("%Y-%m-%d")
        else:
            fecha_fin = None

        datos = {
            "id_obra": None,
            "identificacion_esma": identificacion,
            "contrato": contrato,
            "descripcion": descripcion,
            "dependencia": dependencia,
            "fecha_inicio": fecha_inicio,
            "fecha_fin": fecha_fin,
            "duracion_dias": duracion,
            "superintendente": superintendente,
            "tipo_ajuste": tipo_ajuste,
            "estimaciones_tipo": tipo_est,
            "monto_contratado": monto,
            "monto_cobrado": 0,
            "observaciones": None,
            "auxiliar": None,
        }
        db.crear_estimacion_obra(datos)
        count += 1

    flash(f"Importación completada: {count} obras registradas.", "success")
    return redirect(url_for("estimaciones"))


# ── Editar / Eliminar periodos de estimación ──────────────────────

@app.route("/estimaciones/<int:eid>/periodo/<int:pid>/editar", methods=["POST"])
@login_required
@permiso_requerido("estimaciones", "editar")
def estimacion_editar_periodo(eid, pid):
    """Edita un periodo de estimación."""
    f = request.form
    numero = int(f.get("numero") or 0)
    periodo_label = f.get("periodo_label") or None
    monto = float(f.get("monto") or 0)
    estatus = f.get("estatus") or "pendiente"
    db.editar_periodo_estimacion(pid, numero, periodo_label, monto, estatus)
    # Recalcular totales
    total_cobrado = db.query("SELECT COALESCE(SUM(monto),0) AS t FROM estimaciones_periodos WHERE id_estimacion_obra=%s",
                             (eid,), one=True)["t"]
    db.actualizar_montos_estimacion(eid, float(total_cobrado))
    flash(f"Estimación #{numero} actualizada.", "success")
    return redirect(url_for("estimacion_detalle", eid=eid))


@app.route("/estimaciones/<int:eid>/periodo/<int:pid>/eliminar", methods=["POST"])
@login_required
@permiso_requerido("estimaciones", "editar")
def estimacion_eliminar_periodo(eid, pid):
    """Elimina un periodo de estimación."""
    db.eliminar_periodo_estimacion(pid)
    # Recalcular totales
    total_cobrado = db.query("SELECT COALESCE(SUM(monto),0) AS t FROM estimaciones_periodos WHERE id_estimacion_obra=%s",
                             (eid,), one=True)["t"]
    db.actualizar_montos_estimacion(eid, float(total_cobrado))
    flash("Periodo eliminado.", "success")
    return redirect(url_for("estimacion_detalle", eid=eid))


@app.route("/estimaciones/<int:eid>/periodo/<int:pid>/toggle-cobro", methods=["POST"])
@login_required
@permiso_requerido("estimaciones", "editar")
def estimacion_toggle_periodo_cobro(eid, pid):
    """Cambia estatus cobrado/pendiente de un periodo."""
    nuevo_estatus = request.form.get("estatus") or "pendiente"
    db.toggle_periodo_cobrado(pid, nuevo_estatus)
    # Recalcular totales (solo suma los cobrados)
    total_cobrado = db.query(
        "SELECT COALESCE(SUM(monto),0) AS t FROM estimaciones_periodos WHERE id_estimacion_obra=%s AND estatus='cobrada'",
        (eid,), one=True)["t"]
    db.actualizar_montos_estimacion(eid, float(total_cobrado))
    flash(f"Estatus actualizado a: {nuevo_estatus}", "success")
    return redirect(url_for("estimacion_detalle", eid=eid))


# ── Editar / Eliminar ajustes de costos ───────────────────────────

@app.route("/estimaciones/<int:eid>/ajuste/<int:aid>/editar", methods=["POST"])
@login_required
@permiso_requerido("estimaciones", "editar")
def estimacion_editar_ajuste(eid, aid):
    """Edita un ajuste de costos."""
    f = request.form
    mes = f.get("mes") or ""
    fecha_pub = f.get("fecha_publicacion") or None
    fecha_lim = f.get("fecha_limite") or None
    monto = float(f.get("monto") or 0)
    estatus = f.get("estatus") or "pendiente"
    cobrado = 1 if f.get("cobrado") else 0
    db.editar_ajuste_costo(aid, mes, fecha_pub, fecha_lim, monto, estatus, cobrado)
    flash(f"Ajuste de costos ({mes}) actualizado.", "success")
    return redirect(url_for("estimacion_detalle", eid=eid))


@app.route("/estimaciones/<int:eid>/ajuste/<int:aid>/eliminar", methods=["POST"])
@login_required
@permiso_requerido("estimaciones", "editar")
def estimacion_eliminar_ajuste(eid, aid):
    """Elimina un ajuste de costos."""
    db.eliminar_ajuste_costo(aid)
    flash("Ajuste eliminado.", "success")
    return redirect(url_for("estimacion_detalle", eid=eid))


@app.route("/estimaciones/<int:eid>/ajuste/<int:aid>/toggle-cobro", methods=["POST"])
@login_required
@permiso_requerido("estimaciones", "editar")
def estimacion_toggle_ajuste_cobro(eid, aid):
    """Cambia estatus cobrado de un ajuste."""
    cobrado = 1 if request.form.get("cobrado") == "1" else 0
    db.toggle_ajuste_cobrado(aid, cobrado)
    flash("Estatus de cobro actualizado.", "success")
    return redirect(url_for("estimacion_detalle", eid=eid))


# ── Documentos de Estimaciones ────────────────────────────────────

@app.route("/estimaciones/<int:eid>/documento/subir", methods=["POST"])
@login_required
@permiso_requerido("estimaciones", "crear")
def estimacion_subir_documento(eid):
    """Sube un documento adjunto a la estimación."""
    import uuid
    user = get_current_user()
    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        flash("Selecciona un archivo.", "danger")
        return redirect(url_for("estimacion_detalle", eid=eid))
    nombre_original = archivo.filename
    ext = nombre_original.rsplit(".", 1)[-1] if "." in nombre_original else ""
    nombre_archivo = f"est_{eid}_{uuid.uuid4().hex[:8]}.{ext}" if ext else f"est_{eid}_{uuid.uuid4().hex[:8]}"
    tipo = request.form.get("tipo") or "General"
    descripcion = request.form.get("descripcion") or None
    # Guardar archivo
    upload_dir = os.path.join(app.root_path, "uploads", "estimaciones")
    os.makedirs(upload_dir, exist_ok=True)
    archivo.save(os.path.join(upload_dir, nombre_archivo))
    db.crear_documento_estimacion(eid, nombre_original, nombre_archivo, tipo, descripcion, user["id"])
    flash(f"Documento '{nombre_original}' subido.", "success")
    return redirect(url_for("estimacion_detalle", eid=eid))


@app.route("/estimaciones/documento/<int:did>/descargar")
@login_required
@permiso_requerido("estimaciones", "leer")
def estimacion_descargar_documento(did):
    """Descarga un documento adjunto."""
    doc = db.query("SELECT * FROM estimaciones_documentos WHERE id=%s", (did,), one=True)
    if not doc:
        abort(404)
    upload_dir = os.path.join(app.root_path, "uploads", "estimaciones")
    return send_from_directory(upload_dir, doc["nombre_archivo"],
                               as_attachment=True, download_name=doc["nombre_original"])


@app.route("/estimaciones/<int:eid>/documento/<int:did>/eliminar", methods=["POST"])
@login_required
@permiso_requerido("estimaciones", "editar")
def estimacion_eliminar_documento(eid, did):
    """Elimina un documento adjunto."""
    doc = db.eliminar_documento_estimacion(did)
    if doc:
        ruta = os.path.join(app.root_path, "uploads", "estimaciones", doc["nombre_archivo"])
        if os.path.exists(ruta):
            os.remove(ruta)
    flash("Documento eliminado.", "success")
    return redirect(url_for("estimacion_detalle", eid=eid))


# ── Curva S - API JSON ────────────────────────────────────────────

@app.route("/api/curva-s/<int:id_obra>")
@login_required
def api_curva_s(id_obra):
    """Retorna datos JSON para gráfica de Curva S.
    Programado acumulado y real acumulado por semana (calculados automáticamente)."""
    datos = db.get_curva_s_data(id_obra)
    # Calcular acumulado real
    acum_real = 0
    resultado = []
    for row in datos:
        acum_real += float(row["imp_real_sem"] or 0)
        resultado.append({
            "semana": row["semana"],
            "fecha": str(row["fecha_inicio"]) if row["fecha_inicio"] else f"Sem {row['semana']}",
            "programado_acum": float(row["imp_acumulado_programado"] or 0),
            "real_acum": acum_real,
            "programado_sem": float(row["imp_programado_sem"] or 0),
            "real_sem": float(row["imp_real_sem"] or 0),
        })
    return jsonify(resultado)


# ── Exportar Excel — Avance Físico ────────────────────────────────

@app.route("/avance-fisico/exportar")
@login_required
@permiso_requerido("avance_fisico", "leer")
def avance_fisico_exportar():
    """Exporta el avance físico y financiero de una obra a Excel."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from io import BytesIO

    id_obra = request.args.get("obra")
    if not id_obra:
        flash("Selecciona una obra.", "danger")
        return redirect(url_for("avance_fisico"))
    id_obra = int(id_obra)

    catalogo = db.get_avance_catalogo(id_obra)
    kpis = db.get_avance_kpis(id_obra)
    obra = db.query("SELECT nombre FROM obras WHERE id=%s", (id_obra,), one=True)
    nombre_obra = obra["nombre"] if obra else f"Obra {id_obra}"

    wb = Workbook()
    ws = wb.active
    ws.title = "Avance Fisico-Financiero"

    # Estilos
    header_font = Font(bold=True, size=10, color="FFFFFF")
    header_fill = PatternFill(start_color="2E3B55", end_color="2E3B55", fill_type="solid")
    border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin")
    )

    # Título
    ws.append([f"Control de Avance Físico y Financiero — {nombre_obra}"])
    ws.merge_cells("A1:O1")
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([])

    # KPIs
    ws.append(["Conceptos:", kpis["total_conceptos"], "", "Tramos:", kpis["total_tramos"], "",
               "Contratado:", float(kpis["importe_contratado"]), "", "Programado:", float(kpis["importe_programado"]),
               "", "Real:", float(kpis["importe_real"])])
    ws.append([])

    # Encabezados
    headers = ["No.", "Tramo", "Código", "Concepto", "Unidad", "Cant. Contratada",
               "P.U. ($)", "Importe Contratado ($)", "% Prog.", "Importe Prog. ($)",
               "% Real", "Cant. Real", "Importe Real ($)", "Dif. Financiera ($)", "Dif. %", "Estatus"]
    ws.append(headers)
    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=5, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
        cell.border = border

    # Datos (campos derivados vienen pre-calculados del query)
    for c in catalogo:
        ws.append([
            c["item_id"], c["tramo"], c["codigo"], c["concepto"], c["unidad"],
            float(c["cantidad_contratada"]), float(c["precio_unitario"]), float(c["importe_contratado"]),
            float(c["pct_fisico_programado"]), float(c["importe_programado_total"]),
            float(c["pct_fisico_real"]), float(c["cantidad_real_total"]), float(c["importe_real_total"]),
            float(c["diferencia_financiera"]), float(c["diferencia_fisica_pct"]),
            c["estatus"]
        ])

    # Ajustar anchos
    for col in ws.columns:
        valid_cells = [cell for cell in col if not isinstance(cell, type(None)) and hasattr(cell, 'column_letter')]
        if not valid_cells:
            continue
        max_length = max(len(str(cell.value or "")) for cell in valid_cells)
        ws.column_dimensions[valid_cells[0].column_letter].width = min(max_length + 2, 40)

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output, download_name=f"Avance_Fisico_{nombre_obra}.xlsx",
                     as_attachment=True, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ── Exportar Excel — Estimaciones ─────────────────────────────────

@app.route("/estimaciones/exportar")
@login_required
@permiso_requerido("estimaciones", "leer")
def estimaciones_exportar():
    """Exporta todas las estimaciones a Excel."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill
    from io import BytesIO

    obras_est = db.get_estimaciones_obras()

    wb = Workbook()
    ws = wb.active
    ws.title = "Estimaciones"

    header_font = Font(bold=True, size=10, color="FFFFFF")
    header_fill = PatternFill(start_color="2E3B55", end_color="2E3B55", fill_type="solid")

    ws.append(["Control de Estimaciones y Ajustes de Costos — Grupo ESMA"])
    ws.merge_cells("A1:L1")
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([])

    headers = ["#", "Identificación", "Contrato", "Dependencia", "Inicio", "Fin",
               "Superintendente", "Tipo Est.", "Monto Contratado", "Cobrado", "Faltante", "% Avance"]
    ws.append(headers)
    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=3, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", wrap_text=True)

    for i, e in enumerate(obras_est, 1):
        ws.append([
            i, e.get("identificacion_esma") or e.get("obra_nombre") or "—",
            e.get("contrato") or "—", e.get("dependencia") or "—",
            str(e.get("fecha_inicio") or ""), str(e.get("fecha_fin") or ""),
            e.get("superintendente") or "—", e.get("estimaciones_tipo") or "—",
            float(e.get("monto_contratado") or 0), float(e.get("monto_cobrado") or 0),
            float(e.get("monto_faltante") or 0), float(e.get("pct_avance") or 0)
        ])

    for col in ws.columns:
        valid_cells = [c for c in col if hasattr(c, 'column_letter')]
        if not valid_cells:
            continue
        max_length = max(len(str(c.value or "")) for c in valid_cells)
        ws.column_dimensions[valid_cells[0].column_letter].width = min(max_length + 2, 40)

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output, download_name="Estimaciones_ESMA.xlsx",
                     as_attachment=True, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/estimaciones/<int:eid>/exportar")
@login_required
@permiso_requerido("estimaciones", "leer")
def estimacion_detalle_exportar(eid):
    """Exporta detalle de una estimación (periodos + ajustes) a Excel."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from io import BytesIO

    est = db.get_estimacion_obra(eid)
    if not est:
        abort(404)
    periodos = db.get_periodos_estimacion(eid)
    ajustes = db.get_ajustes_estimacion(eid)

    wb = Workbook()
    # Hoja Periodos
    ws = wb.active
    ws.title = "Periodos"
    header_font = Font(bold=True, size=10, color="FFFFFF")
    header_fill = PatternFill(start_color="2E3B55", end_color="2E3B55", fill_type="solid")

    ws.append([f"Estimaciones — {est.get('identificacion_esma') or est.get('obra_nombre') or 'Obra'}"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([f"Contrato: {est.get('contrato') or '—'}   |   Monto: ${float(est.get('monto_contratado') or 0):,.2f}"])
    ws.append([])

    headers_p = ["# Est.", "Periodo", "Monto ($)", "Estatus"]
    ws.append(headers_p)
    for col_idx in range(1, len(headers_p) + 1):
        cell = ws.cell(row=4, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill

    for p in periodos:
        ws.append([p.get("numero_estimacion"), p.get("periodo_label") or "—",
                   float(p.get("monto") or 0), p.get("estatus") or "—"])

    # Hoja Ajustes
    ws2 = wb.create_sheet("Ajustes de Costos")
    ws2.append(["Ajustes de Costos"])
    ws2["A1"].font = Font(bold=True, size=13)
    ws2.append([])
    headers_a = ["Mes", "Publicación INEGI", "Fecha Límite", "Monto ($)", "Cobrado", "Estatus"]
    ws2.append(headers_a)
    for col_idx in range(1, len(headers_a) + 1):
        cell = ws2.cell(row=3, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill

    for a in ajustes:
        ws2.append([a.get("mes"), str(a.get("fecha_publicacion") or "—"),
                    str(a.get("fecha_limite") or "—"), float(a.get("monto") or 0),
                    "Sí" if a.get("cobrado") else "No", a.get("estatus") or "—"])

    for sheet in wb.worksheets:
        for col in sheet.columns:
            valid_cells = [c for c in col if hasattr(c, 'column_letter')]
            if not valid_cells:
                continue
            max_length = max(len(str(c.value or "")) for c in valid_cells)
            sheet.column_dimensions[valid_cells[0].column_letter].width = min(max_length + 2, 35)

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    nombre = est.get("identificacion_esma") or "Obra"
    return send_file(output, download_name=f"Estimacion_{nombre}.xlsx",
                     as_attachment=True, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


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
            "nombre_empleado_pago": (f.get("nombre_empleado_pago") or "").strip() or None,
        }
        # Validar CFDI obligatorio en partidas deducibles antes de crear
        if partidas_indices:
            faltantes = []
            for idx in partidas_indices.split(","):
                idx = idx.strip()
                if not idx:
                    continue
                if int(f.get(f"partida_tipo_{idx}", "1")) == 1:
                    cfdi_key = f"partida_cfdi_{idx}"
                    arc = request.files.get(cfdi_key)
                    if not arc or not arc.filename:
                        concepto = f.get(f"partida_concepto_{idx}") or f"partida #{idx}"
                        faltantes.append(concepto)
            if faltantes:
                flash(
                    f"CFDI requerido: adjunta el comprobante fiscal de las siguientes partidas deducibles: "
                    + ", ".join(f'"{c}"' for c in faltantes),
                    "danger"
                )
                return redirect(request.url)

        cid = db.crear_comprobacion_caja_chica(datos)
        # Procesar partidas dinámicas (deducibles y no deducibles)
        if partidas_indices:
            cfdi_folder = CFDI_FOLDER
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
            "nombre_empleado_pago": (f.get("nombre_empleado_pago") or "").strip() or None,
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
                cfdi_folder = CFDI_FOLDER
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
        ruta = os.path.join(CFDI_FOLDER, partida["archivo_cfdi"])
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
        ruta_vieja = os.path.join(CFDI_FOLDER, partida["archivo_cfdi"])
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
def caja_chica_aprobar(cid):
    user = get_current_user()
    db.aprobar_comprobacion_caja_chica(cid, user["id"])
    flash("Comprobación aprobada.", "success")
    return redirect(url_for("caja_chica_detalle", cid=cid))


@app.route("/caja-chica/<int:cid>/rechazar", methods=["POST"])
@login_required
@permiso_requerido("caja_chica", "editar")
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
    codigos_costo = db.get_codigos_costo()
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
            "empresa": f.get("empresa") or None,
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
            "id_codigo_costo": int(f["id_codigo_costo"]) if f.get("id_codigo_costo") else None,
            "creado_por": session["user_id"],
        }
        cid = db.crear_contrato(datos)
        flash(f"Contrato '{datos['numero']}' registrado.", "success")
        return redirect(url_for("contrato_detalle", cid=cid))
    return render_template("contrato_form.html", user=user, obras=obras, codigos_costo=codigos_costo, c=None, accion="Nuevo")


@app.route("/contratos/<int:cid>/editar", methods=["GET", "POST"])
@login_required
@permiso_requerido("contratos", "editar")
def contrato_editar(cid):
    contrato = db.get_contrato(cid)
    if not contrato:
        abort(404)
    user = get_current_user()
    obras = db.get_obras()
    codigos_costo = db.get_codigos_costo()
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
            "empresa": f.get("empresa") or None,
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
            "id_codigo_costo": int(f["id_codigo_costo"]) if f.get("id_codigo_costo") else None,
        }
        sets = ", ".join(f"{k}=%({k})s" for k in datos)
        datos["_id"] = cid
        db.execute(f"UPDATE contratos SET {sets} WHERE id=%(_id)s", datos)
        flash("Contrato actualizado.", "success")
        return redirect(url_for("contrato_detalle", cid=cid))
    return render_template("contrato_form.html", user=user, obras=obras, codigos_costo=codigos_costo, c=contrato, accion="Editar")


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
    # Badge de pendientes en el menú Proveedores (registros públicos + órdenes CC por autorizar)
    nav_prov = {"prov": 0, "cc": 0, "total": 0}
    if "user_id" in session and user_perms.get("proveedores", {}).get("editar"):
        try:
            nav_prov = db.contar_pendientes_nav_proveedores()
        except Exception:
            nav_prov = {"prov": 0, "cc": 0, "total": 0}
    def puede_editar_obra(obra_id):
        return obra_permitida(obra_id)

    def puede_crear_obra():
        return session.get("user_rol") == "admin"

    return {"kpis_nav": kpis_nav, "user_perms": user_perms, "nav_prov": nav_prov,
            "puede_editar_obra": puede_editar_obra, "puede_crear_obra": puede_crear_obra,
            "chat_no_leidos": db.get_total_no_leidos(session["user_id"]) if "user_id" in session else 0}

# Inicializar tabla de roles custom al arrancar
try:
    db._init_tabla_roles_custom()
except Exception as _e:
    print(f"[WARN] No se pudo inicializar roles_custom: {_e}")

# Inicializar tabla de permisos por usuario/obra al arrancar
try:
    db._init_tabla_permisos_usuario_obra()
except Exception as _e:
    print(f"[WARN] No se pudo inicializar permisos_usuario_obra: {_e}")

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

# Migración: campo movil en usuarios
try:
    db._init_columna_movil_usuarios()
except Exception as _e:
    print(f"[WARN] No se pudo agregar columna movil a usuarios: {_e}")

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

# Migración: campos horas_diarias y turno en empleados
try:
    db.execute_ddl("ALTER TABLE empleados ADD COLUMN horas_diarias DECIMAL(4,2) DEFAULT 8 COMMENT 'Hrs jornada: 8 diurno, 7 nocturno, manual' AFTER salario_semanal")
except Exception:
    pass
try:
    db.execute_ddl("ALTER TABLE empleados ADD COLUMN turno VARCHAR(20) DEFAULT 'Diurno' COMMENT 'Diurno/Nocturno/Mixto' AFTER horas_diarias")
except Exception:
    pass

# Migración: nuevos campos de nómina (devengado, descuentos, monto empresa, validado por)
for col_sql in [
    "ALTER TABLE nomina ADD COLUMN sueldo_semanal DECIMAL(10,2) DEFAULT 0 AFTER salario_base",
    "ALTER TABLE nomina ADD COLUMN devengado DECIMAL(10,2) DEFAULT 0 AFTER bonos",
    "ALTER TABLE nomina ADD COLUMN descuento_isr DECIMAL(10,2) DEFAULT 0 AFTER devengado",
    "ALTER TABLE nomina ADD COLUMN descuento_imss DECIMAL(10,2) DEFAULT 0 AFTER descuento_isr",
    "ALTER TABLE nomina ADD COLUMN descuento_infonavit DECIMAL(10,2) DEFAULT 0 AFTER descuento_imss",
    "ALTER TABLE nomina ADD COLUMN otros_descuentos DECIMAL(10,2) DEFAULT 0 AFTER descuento_infonavit",
    "ALTER TABLE nomina ADD COLUMN descripcion_otros_desc VARCHAR(255) DEFAULT NULL AFTER otros_descuentos",
    "ALTER TABLE nomina ADD COLUMN total_descuentos DECIMAL(10,2) DEFAULT 0 AFTER descripcion_otros_desc",
    "ALTER TABLE nomina ADD COLUMN monto_empresa DECIMAL(10,2) DEFAULT 0 AFTER total_pagar",
    "ALTER TABLE nomina ADD COLUMN validado_por INT DEFAULT NULL AFTER monto_empresa",
    "ALTER TABLE nomina ADD COLUMN nombre_validador VARCHAR(150) DEFAULT NULL AFTER validado_por",
    "ALTER TABLE nomina ADD COLUMN fecha_validacion DATETIME DEFAULT NULL AFTER nombre_validador",
]:
    try:
        db.execute_ddl(col_sql)
    except Exception:
        pass

# Migración: campos frente y autoriza_extras en asistencia
try:
    db.execute_ddl("ALTER TABLE asistencia ADD COLUMN frente VARCHAR(100) DEFAULT NULL COMMENT 'Frente de obra donde se registra' AFTER id_obra")
except Exception:
    pass
try:
    db.execute_ddl("ALTER TABLE asistencia ADD COLUMN autoriza_extras VARCHAR(150) DEFAULT NULL COMMENT 'Quien autoriza horas extras' AFTER horas_extra")
except Exception:
    pass

# Migración: coordenadas GPS en escaneos_qr
try:
    db.execute_ddl("ALTER TABLE escaneos_qr ADD COLUMN lat DECIMAL(10,7) DEFAULT NULL COMMENT 'Latitud GPS' AFTER foto_evidencia")
except Exception:
    pass
try:
    db.execute_ddl("ALTER TABLE escaneos_qr ADD COLUMN lng DECIMAL(10,7) DEFAULT NULL COMMENT 'Longitud GPS' AFTER lat")
except Exception:
    pass
try:
    db.execute_ddl("ALTER TABLE escaneos_qr ADD COLUMN accuracy DECIMAL(8,2) DEFAULT NULL COMMENT 'Precision GPS en metros' AFTER lng")
except Exception:
    pass

# Inicializar tablas de Requisiciones al arrancar
try:
    db._init_tabla_requisiciones()
except Exception as _e:
    print(f"[WARN] No se pudo inicializar tablas Requisiciones: {_e}")

# Migración: id_codigo_costo en requisicion_partidas
try:
    db.execute_ddl("ALTER TABLE requisicion_partidas ADD COLUMN id_codigo_costo INT DEFAULT NULL COMMENT 'Liga a catalogo codigos_costo' AFTER id_requisicion")
except Exception:
    pass
try:
    db.execute_ddl("ALTER TABLE requisicion_partidas ADD INDEX idx_codigo_costo (id_codigo_costo)")
except Exception:
    pass

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

# Migración: obras.descripcion y obras.link_drive
try:
    db.execute_ddl("ALTER TABLE obras ADD COLUMN descripcion TEXT DEFAULT NULL COMMENT 'Descripcion de la obra' AFTER nombre")
except Exception:
    pass
try:
    db.execute_ddl("ALTER TABLE obras ADD COLUMN numero_contrato VARCHAR(200) DEFAULT NULL COMMENT 'Numero de contrato' AFTER nombre")
except Exception:
    pass
try:
    db.execute_ddl("ALTER TABLE obras ADD COLUMN link_drive VARCHAR(500) DEFAULT NULL COMMENT 'Link carpeta Google Drive' AFTER estado")
except Exception:
    pass

# Migración: maquinas.foto
try:
    db._init_columna_foto_maquina()
except Exception as _e:
    print(f"[WARN] No se pudo migrar columna foto de maquinas: {_e}")

# Auditoría: crear tabla historial_actividades si no existe
try:
    db._init_tabla_historial_actividades()
except Exception as _e:
    print(f"[WARN] No se pudo inicializar historial_actividades: {_e}")

# Migración: reportes_combustible.tipo_combustible
try:
    db._init_columna_tipo_combustible()
except Exception as _e:
    print(f"[WARN] No se pudo migrar tipo_combustible: {_e}")

# Migración: eliminar clave única (codigo_eco, fecha) para permitir
# varias cargas del mismo equipo en la misma fecha.
try:
    db._init_drop_uk_eco_fecha()
except Exception as _e:
    print(f"[WARN] No se pudo eliminar uk_eco_fecha: {_e}")

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
    
except Exception as _e:
    print(f"[WARN] No se pudo inicializar reportes_obra: {_e}")

# Inicializar tabla de Proveedores al arrancar
try:
    db._init_tabla_proveedores()
except Exception as _e:
    print(f"[WARN] No se pudo inicializar proveedores: {_e}")

# Migración: campo tipo_producto_servicio en proveedores
try:
    db.execute_ddl("ALTER TABLE proveedores ADD COLUMN tipo_producto_servicio VARCHAR(255) DEFAULT NULL COMMENT 'Descripcion del producto o servicio que ofrece' AFTER tipo_proveedor")
except Exception:
    pass

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

# Migración: agregar columna id_codigo_costo a contratos
try:
    db.execute_ddl("ALTER TABLE contratos ADD COLUMN id_codigo_costo INT DEFAULT NULL AFTER id_obra")
except Exception:
    pass

# Inicializar tablas de Control de Avance Físico y Financiero al arrancar
try:
    db._init_tabla_avance_fisico()
except Exception as _e:
    print(f"[WARN] No se pudo inicializar avance_fisico: {_e}")

# Migración: agregar columna cantidad_estimada a avance_catalogo (si no existe)
try:
    db.execute_ddl("ALTER TABLE avance_catalogo ADD COLUMN cantidad_estimada DECIMAL(14,3) DEFAULT 0 COMMENT 'Avance fisico estimado (proyeccion)' AFTER importe_contratado")
except Exception:
    pass

# Migración: columnas completas en planta_produccion (estructura ESMA completa)
for _col_sql in [
    "ALTER TABLE planta_produccion ADD COLUMN lts_m3 DECIMAL(8,2) DEFAULT NULL AFTER vol_m3",
    "ALTER TABLE planta_produccion ADD COLUMN asf_cons DECIMAL(10,2) DEFAULT NULL AFTER asf_desc",
    "ALTER TABLE planta_produccion ADD COLUMN asf_kg DECIMAL(10,2) DEFAULT NULL AFTER asf_final",
    "ALTER TABLE planta_produccion ADD COLUMN alt_cons DECIMAL(10,2) DEFAULT NULL AFTER alt_final",
    "ALTER TABLE planta_produccion ADD COLUMN alt_lts_m3 DECIMAL(8,2) DEFAULT NULL AFTER alt_cons",
    "ALTER TABLE planta_produccion ADD COLUMN vol_compacto DECIMAL(10,2) DEFAULT NULL AFTER alt_lts_m3",
    "ALTER TABLE planta_produccion ADD COLUMN vol_acumulado DECIMAL(12,2) DEFAULT NULL AFTER vol_compacto",
    "ALTER TABLE planta_produccion ADD COLUMN abundamiento DECIMAL(6,3) DEFAULT NULL AFTER vol_acumulado",
    "ALTER TABLE planta_produccion ADD COLUMN emu_lts_m2 DECIMAL(8,3) DEFAULT NULL AFTER abundamiento",
    "ALTER TABLE planta_produccion ADD COLUMN emu_cons DECIMAL(10,2) DEFAULT NULL AFTER emu_desc",
    "ALTER TABLE planta_produccion ADD COLUMN grava_carpeta_ini DECIMAL(10,2) DEFAULT NULL AFTER emu_final",
    "ALTER TABLE planta_produccion ADD COLUMN grava_carpeta_recib DECIMAL(10,2) DEFAULT NULL AFTER grava_carpeta_ini",
    "ALTER TABLE planta_produccion ADD COLUMN grava_carpeta_cons DECIMAL(10,2) DEFAULT NULL AFTER grava_carpeta_recib",
    "ALTER TABLE planta_produccion ADD COLUMN grava_carpeta_final DECIMAL(10,2) DEFAULT NULL AFTER grava_carpeta_cons",
    "ALTER TABLE planta_produccion ADD COLUMN arena_cons DECIMAL(10,2) DEFAULT NULL AFTER arena_recib",
    "ALTER TABLE planta_produccion ADD COLUMN arena_final DECIMAL(10,2) DEFAULT NULL AFTER arena_cons",
    "ALTER TABLE planta_produccion ADD COLUMN grava_normal_ini DECIMAL(10,2) DEFAULT NULL AFTER arena_final",
    "ALTER TABLE planta_produccion ADD COLUMN grava_normal_recib DECIMAL(10,2) DEFAULT NULL AFTER grava_normal_ini",
    "ALTER TABLE planta_produccion ADD COLUMN grava_normal_cons DECIMAL(10,2) DEFAULT NULL AFTER grava_normal_recib",
    "ALTER TABLE planta_produccion ADD COLUMN grava_normal_final DECIMAL(10,2) DEFAULT NULL AFTER grava_normal_cons",
    "ALTER TABLE planta_produccion ADD COLUMN grava_sello_ini DECIMAL(10,2) DEFAULT NULL AFTER grava_normal_final",
    "ALTER TABLE planta_produccion ADD COLUMN grava_sello_recib DECIMAL(10,2) DEFAULT NULL AFTER grava_sello_ini",
    "ALTER TABLE planta_produccion ADD COLUMN grava_sello_cons DECIMAL(10,2) DEFAULT NULL AFTER grava_sello_recib",
    "ALTER TABLE planta_produccion ADD COLUMN grava_sello_final DECIMAL(10,2) DEFAULT NULL AFTER grava_sello_cons",
    "ALTER TABLE planta_produccion ADD COLUMN grava_medio_ini DECIMAL(10,2) DEFAULT NULL AFTER grava_sello_final",
    "ALTER TABLE planta_produccion ADD COLUMN grava_medio_recib DECIMAL(10,2) DEFAULT NULL AFTER grava_medio_ini",
    "ALTER TABLE planta_produccion ADD COLUMN grava_medio_cons DECIMAL(10,2) DEFAULT NULL AFTER grava_medio_recib",
    "ALTER TABLE planta_produccion ADD COLUMN grava_medio_final DECIMAL(10,2) DEFAULT NULL AFTER grava_medio_cons",
]:
    try:
        db.execute_ddl(_col_sql)
    except Exception:
        pass

# Inicializar tablas de Estimaciones y Ajustes de Costos
try:
    db._init_tabla_estimaciones()
except Exception as _e:
    print(f"[WARN] No se pudo inicializar estimaciones: {_e}")

# Migración: campo monto y cobrado en ajustes_costos
try:
    db.execute_ddl("ALTER TABLE ajustes_costos ADD COLUMN monto DECIMAL(14,2) DEFAULT 0 COMMENT 'Monto del ajuste' AFTER fecha_limite")
except Exception:
    pass
try:
    db.execute_ddl("ALTER TABLE ajustes_costos ADD COLUMN cobrado TINYINT(1) DEFAULT 0 COMMENT '1=cobrado, 0=no cobrado' AFTER monto")
except Exception:
    pass

# Inicializar tablas de Chat
try:
    db._init_tabla_chat()
except Exception as _e:
    print(f"[WARN] No se pudo inicializar chat: {_e}")

# Inicializar tabla de vehículos
try:
    db._init_tabla_vehiculos()
except Exception as _e:
    print(f"[WARN] No se pudo inicializar vehiculos: {_e}")

# Inicializar tabla de fotos de evidencia de obra
try:
    db._init_tabla_foto_evidencia_obra()
except Exception as _e:
    print(f"[WARN] No se pudo inicializar foto_evidencia_obra: {_e}")

# ══════════════════════════════════════════════════════════════════
#  CHAT INTERNO — Mensajería entre usuarios
# ══════════════════════════════════════════════════════════════════

@app.route("/chat/test-email")
@login_required
def chat_test_email():
    """Prueba de envío de email — visita esta URL para verificar que SMTP funciona."""
    user = get_current_user()
    email_dest = user.get("email") or SMTP_FROM_EMAIL
    ok = enviar_email(email_dest, "Prueba de correo — AUCOTRACK Plataforma",
                      "<h2>Correo de prueba</h2><p>Si ves esto, el SMTP funciona correctamente.</p>",
                      cuerpo_texto="Correo de prueba - SMTP funciona")
    if ok:
        flash(f"Correo de prueba enviado a {email_dest}. Revisa tu bandeja.", "success")
    else:
        flash("ERROR: No se pudo enviar. Revisa el log del servidor.", "danger")
    return redirect(url_for("chat"))


@app.route("/chat")
@login_required
def chat():
    user = get_current_user()
    conversaciones = db.get_conversaciones_usuario(user["id"])
    usuarios = db.get_usuarios()
    return render_template("chat.html", user=user, conversaciones=conversaciones, usuarios=usuarios)


@app.route("/chat/conversacion/<int:cid>")
@login_required
def chat_conversacion(cid):
    user = get_current_user()
    if not db.es_participante(cid, user["id"]):
        flash("No tienes acceso a esa conversación.", "danger")
        return redirect(url_for("chat"))
    mensajes = db.get_mensajes_conversacion(cid, limit=100)
    db.marcar_conversacion_leida(cid, user["id"])
    participantes = db.get_participantes_conversacion(cid)
    conversaciones = db.get_conversaciones_usuario(user["id"])
    usuarios = db.get_usuarios()
    return render_template("chat.html", user=user, conversaciones=conversaciones,
                           usuarios=usuarios, mensajes=list(reversed(mensajes)),
                           conversacion_activa=cid, participantes=participantes)


@app.route("/chat/nueva/<int:uid>")
@login_required
def chat_nueva_directa(uid):
    """Inicia o abre conversacion directa con otro usuario."""
    user = get_current_user()
    cid = db.get_o_crear_conversacion_directa(user["id"], uid)
    return redirect(url_for("chat_conversacion", cid=cid))


@app.route("/chat/grupo", methods=["POST"])
@login_required
def chat_crear_grupo():
    user = get_current_user()
    titulo = request.form.get("titulo", "Grupo")
    participantes = request.form.getlist("participantes[]")
    ids = [int(p) for p in participantes if p]
    if user["id"] not in ids:
        ids.append(user["id"])
    if len(ids) < 2:
        flash("Selecciona al menos un participante.", "danger")
        return redirect(url_for("chat"))
    cid = db.crear_conversacion_grupo(titulo, ids, user["id"])
    flash(f"Grupo '{titulo}' creado.", "success")
    return redirect(url_for("chat_conversacion", cid=cid))


@app.route("/chat/enviar/<int:cid>", methods=["POST"])
@login_required
def chat_enviar(cid):
    user = get_current_user()
    if not db.es_participante(cid, user["id"]):
        abort(403)
    contenido = request.form.get("contenido", "").strip()
    archivo = request.files.get("archivo")
    archivo_nombre = None
    archivo_original = None
    archivo_tipo = None
    if archivo and archivo.filename:
        import time
        ext = archivo.filename.rsplit(".", 1)[-1] if "." in archivo.filename else ""
        archivo_nombre = f"chat_{cid}_{int(time.time())}_{user['id']}.{ext}"
        archivo.save(os.path.join(CHAT_FOLDER, archivo_nombre))
        archivo_original = archivo.filename
        archivo_tipo = archivo.content_type
    if not contenido and not archivo_nombre:
        return redirect(url_for("chat_conversacion", cid=cid))
    mid = db.enviar_mensaje(cid, user["id"], contenido, archivo_nombre, archivo_original, archivo_tipo)
    # Emitir via Socket.IO a la sala de la conversacion
    socketio.emit("nuevo_mensaje", {
        "id_conversacion": cid,
        "id_mensaje": mid,
        "autor": user["nombre"],
        "contenido": contenido,
        "archivo": archivo_original,
        "fecha": datetime.now().strftime("%H:%M")
    }, room=f"chat_{cid}")

    # ── Enviar notificación por email a los demás participantes ──
    participantes = db.get_participantes_conversacion(cid)
    adjunto_path = os.path.join(CHAT_FOLDER, archivo_nombre) if archivo_nombre else None
    print(f"[CHAT-EMAIL] Conversacion {cid}: {len(participantes)} participantes, remitente id={user['id']}")
    for p in participantes:
        if p["id"] == user["id"]:
            print(f"[CHAT-EMAIL]   Saltando remitente: {p['nombre']} (id={p['id']})")
            continue  # No notificar al que envió
        email_dest = p.get("email")
        if not email_dest:
            print(f"[CHAT-EMAIL]   {p['nombre']} (id={p['id']}) — SIN EMAIL, no se notifica")
            continue
        print(f"[CHAT-EMAIL]   Enviando email a: {email_dest} ({p['nombre']})")
        asunto = f"[ESMA-Chat-{cid}] Nuevo mensaje de {user['nombre']}"
        cuerpo_html = f"""
        <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px">
          <div style="background:#2E3192;color:#fff;padding:14px 20px;border-radius:8px 8px 0 0">
            <strong>ESMA — Chat Interno</strong>
          </div>
          <div style="background:#f8f9fa;border:1px solid #e0e0e0;border-top:none;padding:20px;border-radius:0 0 8px 8px">
            <p style="margin:0 0 8px;color:#666;font-size:12px">Mensaje de <strong>{user['nombre']}</strong></p>
            <div style="background:#fff;border:1px solid #ddd;border-radius:8px;padding:14px;margin-bottom:12px">
              {f'<p style="margin:0;font-size:14px">{contenido}</p>' if contenido else ''}
              {f'<p style="margin:8px 0 0;font-size:12px;color:#2E3192">📎 Archivo adjunto: {archivo_original}</p>' if archivo_original else ''}
            </div>
            <a href="https://telemetriaesma.duckdns.org/chat/conversacion/{cid}"
               style="display:inline-block;background:#2E3192;color:#fff;padding:8px 18px;border-radius:6px;text-decoration:none;font-size:13px">
              Ver en la plataforma
            </a>
            <p style="margin:16px 0 0;font-size:11px;color:#999">
              Puedes responder a este correo directamente y tu mensaje aparecerá en la plataforma ESMA.
            </p>
          </div>
        </div>"""
        enviar_email(email_dest, asunto, cuerpo_html,
                     cuerpo_texto=f"Mensaje de {user['nombre']}:\n\n{contenido or '(archivo adjunto)'}\n\n---\nResponde a este correo y tu mensaje aparecerá en la plataforma ESMA.\n[ESMA-Chat-{cid}]",
                     adjunto_path=adjunto_path, adjunto_nombre=archivo_original,
                     headers={"X-ESMA-CID": str(cid), "Reply-To": SMTP_FROM_EMAIL})

    # ── Si hay destinatarios externos (email directo), enviar también ──
    email_externo = request.form.get("email_externo", "").strip()
    # También detectar si es conversación con email externo (título "✉ email@...")
    conv = db.query("SELECT titulo FROM chat_conversaciones WHERE id=%s", (cid,), one=True)
    
    if conv and (conv.get("titulo") or "").startswith("✉ "):

        email_externo_conv = conv["titulo"][2:].strip()
        if email_externo_conv and "@" in email_externo_conv and email_externo_conv != email_externo:
            # Enviar al email externo de la conversación
            asunto_ext = f"Mensaje de {user['nombre']} — {SMTP_FROM_NAME}"
            cuerpo_ext = f"""
            <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px">
              <div style="background:#2E3192;color:#fff;padding:14px 20px;border-radius:8px 8px 0 0">
                <strong>{SMTP_FROM_NAME}</strong>
              </div>
              <div style="background:#f8f9fa;border:1px solid #e0e0e0;border-top:none;padding:20px;border-radius:0 0 8px 8px">
                <p style="margin:0 0 8px;color:#666;font-size:12px">Mensaje de <strong>{user['nombre']}</strong> ({user.get('email','')})</p>
                <div style="background:#fff;border:1px solid #ddd;border-radius:8px;padding:14px;margin-bottom:12px">
                  {f'<p style="margin:0;font-size:14px">{contenido}</p>' if contenido else ''}
                  {f'<p style="margin:8px 0 0;font-size:12px;color:#2E3192">📎 Archivo adjunto: {archivo_original}</p>' if archivo_original else ''}
                </div>
                <p style="margin:0;font-size:11px;color:#999">
                  Puedes responder a este correo directamente.<br>
                  Enviado desde la plataforma ESMA.
                </p>
              </div>
            </div>"""
            enviar_email(email_externo_conv, asunto_ext, cuerpo_ext,
                         cuerpo_texto=f"Mensaje de {user['nombre']}:\n\n{contenido or '(archivo adjunto)'}",
                         adjunto_path=adjunto_path, adjunto_nombre=archivo_original,
                         headers={"X-ESMA-CID": str(cid), "Reply-To": SMTP_FROM_EMAIL})

    if email_externo and "@" in email_externo:
        asunto_ext = f"Mensaje de {user['nombre']} — {SMTP_FROM_NAME}"
        cuerpo_ext = f"""
        <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px">
          <div style="background:#2E3192;color:#fff;padding:14px 20px;border-radius:8px 8px 0 0">
            <strong>{SMTP_FROM_NAME}</strong>
          </div>
          <div style="background:#f8f9fa;border:1px solid #e0e0e0;border-top:none;padding:20px;border-radius:0 0 8px 8px">
            <p style="margin:0 0 8px;color:#666;font-size:12px">Mensaje de <strong>{user['nombre']}</strong> ({user.get('email','')})</p>
            <div style="background:#fff;border:1px solid #ddd;border-radius:8px;padding:14px;margin-bottom:12px">
              {f'<p style="margin:0;font-size:14px">{contenido}</p>' if contenido else ''}
              {f'<p style="margin:8px 0 0;font-size:12px;color:#2E3192">📎 Archivo adjunto: {archivo_original}</p>' if archivo_original else ''}
            </div>
            <p style="margin:0;font-size:11px;color:#999">
              Este mensaje fue enviado desde la plataforma ESMA.<br>
              Para responder, contacta a: {user.get('email','')}
            </p>
          </div>
        </div>"""
        enviar_email(email_externo, asunto_ext, cuerpo_ext,
                     cuerpo_texto=f"Mensaje de {user['nombre']}:\n\n{contenido or '(archivo adjunto)'}",
                     adjunto_path=adjunto_path, adjunto_nombre=archivo_original)

    return redirect(url_for("chat_conversacion", cid=cid))


@app.route("/chat/enviar-email", methods=["POST"])
@login_required
def chat_enviar_email_externo():
    """Envía un correo a un destinatario externo (no registrado) desde el chat."""
    user = get_current_user()
    email_dest = request.form.get("email_destino", "").strip()
    asunto = request.form.get("asunto", "").strip() or f"Mensaje de {user['nombre']} — {SMTP_FROM_NAME}"
    contenido = request.form.get("contenido", "").strip()
    archivo = request.files.get("archivo")

    if not email_dest or "@" not in email_dest:
        flash("Ingresa un correo electrónico válido.", "danger")
        return redirect(url_for("chat"))
    if not contenido and not (archivo and archivo.filename):
        flash("Escribe un mensaje o adjunta un archivo.", "danger")
        return redirect(url_for("chat"))

    # Guardar archivo si hay
    adjunto_path = None
    adjunto_nombre = None
    if archivo and archivo.filename:
        import time
        ext = archivo.filename.rsplit(".", 1)[-1] if "." in archivo.filename else ""
        archivo_nombre = f"chat_ext_{int(time.time())}_{user['id']}.{ext}"
        adjunto_path = os.path.join(CHAT_FOLDER, archivo_nombre)
        archivo.save(adjunto_path)
        adjunto_nombre = archivo.filename

    cuerpo_html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px">
      <div style="background:#2E3192;color:#fff;padding:14px 20px;border-radius:8px 8px 0 0">
        <strong>{SMTP_FROM_NAME}</strong>
      </div>
      <div style="background:#f8f9fa;border:1px solid #e0e0e0;border-top:none;padding:20px;border-radius:0 0 8px 8px">
        <p style="margin:0 0 8px;color:#666;font-size:12px">De: <strong>{user['nombre']}</strong> ({user.get('email','')})</p>
        <div style="background:#fff;border:1px solid #ddd;border-radius:8px;padding:14px;margin-bottom:12px">
          <p style="margin:0;font-size:14px;white-space:pre-wrap">{contenido}</p>
          {f'<p style="margin:8px 0 0;font-size:12px;color:#2E3192">📎 Archivo adjunto: {adjunto_nombre}</p>' if adjunto_nombre else ''}
        </div>
        <p style="margin:0;font-size:11px;color:#999">
          Para responder, contacta a: {user.get('email','')}<br>
          Enviado desde la plataforma ESMA.
        </p>
      </div>
    </div>"""

    ok = enviar_email(email_dest, asunto, cuerpo_html,
                      cuerpo_texto=f"De: {user['nombre']} ({user.get('email','')})\n\n{contenido}",
                      adjunto_path=adjunto_path, adjunto_nombre=adjunto_nombre)
    if ok:
        # Guardar en historial del chat como conversación con el email externo
        # Buscar si ya existe conversación PROPIA del usuario con este email externo
        conv_existente = db.query("""
            SELECT id FROM chat_conversaciones WHERE titulo=%s AND es_grupo=0 AND creado_por=%s
        """, (f"✉ {email_dest}", user["id"]), one=True)
        if conv_existente:
            cid = conv_existente["id"]
        else:
            cid = db.execute("""
                INSERT INTO chat_conversaciones (titulo, es_grupo, creado_por) VALUES (%s, 0, %s)
            """, (f"✉ {email_dest}", user["id"]))
            db.execute("INSERT INTO chat_participantes (id_conversacion, id_usuario) VALUES (%s, %s)",
                       (cid, user["id"]))
        # Guardar el mensaje enviado
        mensaje_texto = f"[Email a: {email_dest}]\n{f'Asunto: {asunto}' if asunto else ''}\n\n{contenido}"
        archivo_db = os.path.basename(adjunto_path) if adjunto_path else None
        db.enviar_mensaje(cid, user["id"], mensaje_texto.strip(), archivo_db, adjunto_nombre, None)
        flash(f"Correo enviado a {email_dest}", "success")
        return redirect(url_for("chat_conversacion", cid=cid))
    else:
        flash("Error: SMTP no configurado. Revisa las variables en .env", "danger")
    return redirect(url_for("chat"))


@app.route("/chat/api/mensajes/<int:cid>")
@login_required
def chat_api_mensajes(cid):
    """API JSON para polling o carga de mensajes."""
    user = get_current_user()
    if not db.es_participante(cid, user["id"]):
        return jsonify([])
    mensajes = db.get_mensajes_conversacion(cid, limit=50)
    db.marcar_conversacion_leida(cid, user["id"])
    return jsonify([{
        "id": m["id"],
        "autor": m["autor_nombre"],
        "contenido": m["contenido"],
        "archivo": m["archivo_original"],
        "archivo_url": f"/uploads/{m['archivo']}" if m["archivo"] else None,
        "archivo_tipo": m["archivo_tipo"],
        "fecha": m["creado_en"].strftime("%d/%m %H:%M") if m["creado_en"] else "",
        "es_mio": m["id_usuario"] == user["id"]
    } for m in reversed(mensajes)])


# ── Socket.IO events para chat ──
@socketio.on("join_chat")
def handle_join_chat(data):
    from flask_socketio import join_room
    cid = data.get("id_conversacion")
    if cid:
        join_room(f"chat_{cid}")


@socketio.on("leave_chat")
def handle_leave_chat(data):
    from flask_socketio import leave_room
    cid = data.get("id_conversacion")
    if cid:
        leave_room(f"chat_{cid}")



# ══════════════════════════════════════════════════════════════════
#  CÁMARAS — Módulo de streaming MJPEG para equipos
# ══════════════════════════════════════════════════════════════════
try:
    from cameras import generate_mjpeg, get_snapshot
    _CAMERAS_OK = True
except ImportError:
    _CAMERAS_OK = False

# Inicializar tabla al arrancar
try:
    db._init_tabla_camaras()
except Exception as _e:
    print(f"[WARN] No se pudo inicializar tabla camaras: {_e}")


# ══════════════════════════════════════════════════════════════════
#  VEHÍCULOS
# ══════════════════════════════════════════════════════════════════

@app.route("/vehiculos")
@login_required
@permiso_requerido("equipos", "leer")
def vehiculos():
    search = request.args.get("q", "")
    obra   = request.args.get("obra", "")
    lista  = db.get_vehiculos(search or None, obra or None)
    obras  = db.get_obras()
    user   = get_current_user()
    return render_template("vehiculos.html", vehiculos=lista, obras=obras,
                           search=search, obra=obra, user=user)


@app.route("/vehiculos/nuevo", methods=["GET", "POST"])
@login_required
@permiso_requerido("equipos", "crear")
def vehiculo_nuevo():
    obras = db.get_obras()
    user  = get_current_user()
    if request.method == "POST":
        f = request.form
        placa = (f.get("placa") or "").strip().upper()
        serie = (f.get("serie") or "").strip()
        conflictos = db.vehiculo_existe(serie=serie, placa=placa)
        if conflictos:
            for c in conflictos:
                flash(c, "danger")
            return render_template("vehiculo_form.html", veh=None, obras=obras,
                                   user=user, accion="Nuevo")
        db.crear_vehiculo({
            "placa":     placa,
            "serie":     serie or None,
            "marca":     f.get("marca", "").strip() or None,
            "modelo":    f.get("modelo", "").strip() or None,
            "anio":      f.get("anio") or None,
            "cilindros": f.get("cilindros") or None,
            "id_obra":   f.get("id_obra") or None,
        })
        flash(f"Vehículo {placa} creado correctamente.", "success")
        db.registrar_actividad(
            accion="crear", ip=get_client_ip(),
            id_usuario=session.get("user_id"), nombre=session.get("user_nombre"),
            email=session.get("user_email"), rol=session.get("user_rol"),
            modulo="equipos", descripcion=f"Creó vehículo placa={placa}",
            objeto_id=placa, objeto_tipo="vehiculo",
            metodo="POST", ruta=request.path,
            user_agent=request.headers.get("User-Agent", "")[:300],
            **get_geo_ip(get_client_ip()),
        )
        return redirect(url_for("vehiculos"))
    return render_template("vehiculo_form.html", veh=None, obras=obras,
                           user=user, accion="Nuevo")


@app.route("/vehiculos/<int:vid>")
@login_required
@permiso_requerido("equipos", "leer")
def vehiculo_detalle(vid):
    veh = db.get_vehiculo(vid)
    if not veh:
        abort(404)
    user = get_current_user()
    return render_template("vehiculo_detalle.html", veh=veh, user=user)


@app.route("/vehiculos/<int:vid>/editar", methods=["GET", "POST"])
@login_required
@permiso_requerido("equipos", "editar")
def vehiculo_editar(vid):
    veh  = db.get_vehiculo(vid)
    if not veh:
        abort(404)
    obras = db.get_obras()
    user  = get_current_user()
    if request.method == "POST":
        f = request.form
        placa = (f.get("placa") or "").strip().upper()
        serie = (f.get("serie") or "").strip()
        conflictos = db.vehiculo_existe(serie=serie, placa=placa, excluir_id=vid)
        if conflictos:
            for c in conflictos:
                flash(c, "danger")
            return render_template("vehiculo_form.html", veh=veh, obras=obras,
                                   user=user, accion="Editar")
        db.actualizar_vehiculo({
            "id_vehiculo": vid,
            "placa":       placa,
            "serie":       serie or None,
            "marca":       f.get("marca", "").strip() or None,
            "modelo":      f.get("modelo", "").strip() or None,
            "anio":        f.get("anio") or None,
            "cilindros":   f.get("cilindros") or None,
            "id_obra":     f.get("id_obra") or None,
        })
        flash("Vehículo actualizado correctamente.", "success")
        db.registrar_actividad(
            accion="editar", ip=get_client_ip(),
            id_usuario=session.get("user_id"), nombre=session.get("user_nombre"),
            email=session.get("user_email"), rol=session.get("user_rol"),
            modulo="equipos", descripcion=f"Editó vehículo id={vid} placa={placa}",
            objeto_id=str(vid), objeto_tipo="vehiculo",
            metodo="POST", ruta=request.path,
            user_agent=request.headers.get("User-Agent", "")[:300],
            **get_geo_ip(get_client_ip()),
        )
        return redirect(url_for("vehiculo_detalle", vid=vid))
    return render_template("vehiculo_form.html", veh=veh, obras=obras,
                           user=user, accion="Editar")


@app.route("/vehiculos/<int:vid>/eliminar", methods=["POST"])
@login_required
@permiso_requerido("equipos", "eliminar")
def vehiculo_eliminar(vid):
    veh = db.get_vehiculo(vid)
    if not veh:
        abort(404)
    db.eliminar_vehiculo(vid)
    flash(f"Vehículo {veh.get('placa', vid)} eliminado.", "success")
    return redirect(url_for("vehiculos"))


@app.route("/vehiculos/exportar")
@login_required
@permiso_requerido("equipos", "leer")
def vehiculos_exportar_excel():
    """Descarga la lista completa de vehículos como Excel."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from io import BytesIO

    q     = request.args.get("q", "")
    obra  = request.args.get("obra", "")
    lista = db.get_vehiculos(q or None, obra or None)

    wb = Workbook()
    ws = wb.active
    ws.title = "Vehículos"

    HEADERS = ["Marca", "Modelo", "Año", "Cilindros", "Serie", "Placa", "Obra"]
    ws.append(HEADERS)
    for cell in ws[1]:
        cell.font      = Font(bold=True, color="FFFFFF")
        cell.fill      = PatternFill("solid", fgColor="004694")
        cell.alignment = Alignment(horizontal="center")

    for v in lista:
        ws.append([
            v.get("marca")      or "",
            v.get("modelo")     or "",
            v.get("anio")       or "",
            v.get("cilindros")  or "",
            v.get("serie")      or "",
            v.get("placa")      or "",
            v.get("obra_nombre") or "",
        ])

    # Ajustar ancho de columnas
    for col in ws.columns:
        mx = max((len(str(c.value or "")) for c in col), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(mx + 4, 40)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True,
                     download_name="vehiculos.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/vehiculos/importar", methods=["POST"])
@login_required
@permiso_requerido("equipos", "crear")
def vehiculos_importar_excel():
    """Importa vehículos desde un archivo Excel.
    Columnas esperadas (en cualquier orden):
    MARCA  MODELO  AÑO  CILINDROS  SERIE  PLACA  OBRA
    Los vehículos con PLACA o SERIE ya existentes se omiten.
    """
    from openpyxl import load_workbook

    archivo = request.files.get("archivo_excel")
    if not archivo or not archivo.filename:
        flash("No se seleccionó ningún archivo.", "danger")
        return redirect(url_for("vehiculos"))

    try:
        wb = load_workbook(archivo, data_only=True)
    except Exception as e:
        flash(f"Error al leer el archivo Excel: {e}", "danger")
        return redirect(url_for("vehiculos"))

    ws = wb.active

    # Leer encabezados de la primera fila (insensible a mayúsculas/espacios)
    headers = []
    for cell in ws[1]:
        val = str(cell.value or "").strip().upper()
        headers.append(val)

    # Mapeo normalizado de nombres de columna a claves internas
    COL_MAP = {
        "MARCA": "marca", "MODELO": "modelo",
        "AÑO": "anio", "ANO": "anio", "YEAR": "anio",
        "CILINDROS": "cilindros", "CIL": "cilindros",
        "SERIE": "serie", "VIN": "serie",
        "PLACA": "placa",
        "OBRA": "obra_nombre",
    }
    col_index = {}
    for i, h in enumerate(headers):
        if h in COL_MAP:
            col_index[COL_MAP[h]] = i

    if "placa" not in col_index:
        flash("El archivo no contiene la columna PLACA (obligatoria).", "danger")
        return redirect(url_for("vehiculos"))

    # Cargar obras para resolver nombre → id
    obras_list = db.get_obras()
    obras_map  = {o["nombre"].strip().upper(): o["id"] for o in obras_list}

    creados = omitidos = errores = 0

    for row in ws.iter_rows(min_row=2, values_only=True):
        if not any(row):
            continue

        def col(key, default=""):
            idx = col_index.get(key)
            if idx is None:
                return default
            val = row[idx]
            return str(val).strip() if val is not None else default

        placa = col("placa").upper()
        serie = col("serie") or None

        if not placa:
            continue

        # Verificar duplicados
        conflictos = db.vehiculo_existe(serie=serie, placa=placa)
        if conflictos:
            omitidos += 1
            continue

        # Resolver obra por nombre
        obra_txt = col("obra_nombre").strip().upper()
        id_obra  = obras_map.get(obra_txt) if obra_txt else None

        # Año y cilindros como enteros
        try:
            anio = int(float(col("anio"))) if col("anio") else None
        except (ValueError, TypeError):
            anio = None
        try:
            cilindros = int(float(col("cilindros"))) if col("cilindros") else None
        except (ValueError, TypeError):
            cilindros = None

        try:
            db.crear_vehiculo({
                "placa":     placa,
                "serie":     serie,
                "marca":     col("marca") or None,
                "modelo":    col("modelo") or None,
                "anio":      anio,
                "cilindros": cilindros,
                "id_obra":   id_obra,
            })
            creados += 1
        except Exception:
            errores += 1

    msg = f"Importación completada: {creados} creado(s)"
    if omitidos:
        msg += f", {omitidos} omitido(s) por placa/serie duplicada"
    if errores:
        msg += f", {errores} error(es)"
    flash(msg, "success" if creados > 0 else "warning")
    return redirect(url_for("vehiculos"))


@app.route("/camaras")
@login_required
@permiso_requerido("equipos", "leer")
def camaras():
    """Lista todas las cámaras registradas, filtrable por obra/equipo."""
    user = get_current_user()
    obra_filtro = request.args.get("obra", "")
    eco_filtro  = request.args.get("eco", "")
    obras       = db.get_obras()
    maquinas    = db.get_maquinas()
    lista       = db.get_camaras(
        id_obra=int(obra_filtro) if obra_filtro else None,
        eco=eco_filtro or None,
        solo_activas=False,
    )
    return render_template("camaras.html", user=user, camaras=lista,
                           obras=obras, maquinas=maquinas,
                           obra_filtro=obra_filtro, eco_filtro=eco_filtro)


@app.route("/camaras/nueva", methods=["GET", "POST"])
@login_required
@permiso_requerido("equipos", "editar")
def camara_nueva():
    user     = get_current_user()
    obras    = db.get_obras()
    maquinas = db.get_maquinas()
    if request.method == "POST":
        f = request.form
        datos = {
            "nombre":      (f.get("nombre") or "").strip(),
            "eco":         (f.get("eco") or "").strip().upper() or None,
            "id_obra":     int(f["id_obra"]) if f.get("id_obra") else None,
            "url_stream":  (f.get("url_stream") or "").strip(),
            "descripcion": f.get("descripcion") or None,
            "activa":      1 if f.get("activa") else 0,
            "creado_por":  session["user_id"],
        }
        if not datos["nombre"] or not datos["url_stream"]:
            flash("Nombre y URL del stream son obligatorios.", "danger")
            return render_template("camara_form.html", user=user, cam=None,
                                   obras=obras, maquinas=maquinas)
        db.crear_camara(datos)
        flash(f"Cámara «{datos['nombre']}» registrada.", "success")
        return redirect(url_for("camaras"))
    return render_template("camara_form.html", user=user, cam=None,
                           obras=obras, maquinas=maquinas)


@app.route("/camaras/<int:cam_id>/editar", methods=["GET", "POST"])
@login_required
@permiso_requerido("equipos", "editar")
def camara_editar(cam_id):
    cam      = db.get_camara(cam_id)
    if not cam:
        abort(404)
    user     = get_current_user()
    obras    = db.get_obras()
    maquinas = db.get_maquinas()
    if request.method == "POST":
        f = request.form
        datos = {
            "nombre":      (f.get("nombre") or "").strip(),
            "eco":         (f.get("eco") or "").strip().upper() or None,
            "id_obra":     int(f["id_obra"]) if f.get("id_obra") else None,
            "url_stream":  (f.get("url_stream") or "").strip(),
            "descripcion": f.get("descripcion") or None,
            "activa":      1 if f.get("activa") else 0,
        }
        db.actualizar_camara(cam_id, datos)
        flash("Cámara actualizada.", "success")
        return redirect(url_for("camaras"))
    return render_template("camara_form.html", user=user, cam=cam,
                           obras=obras, maquinas=maquinas)


@app.route("/camaras/<int:cam_id>/toggle", methods=["POST"])
@login_required
@permiso_requerido("equipos", "editar")
def camara_toggle(cam_id):
    db.toggle_camara_activa(cam_id)
    flash("Estado de la cámara actualizado.", "success")
    return redirect(request.referrer or url_for("camaras"))


@app.route("/camaras/<int:cam_id>/eliminar", methods=["POST"])
@login_required
@permiso_requerido("equipos", "eliminar")
def camara_eliminar(cam_id):
    db.eliminar_camara(cam_id)
    flash("Cámara eliminada.", "success")
    return redirect(url_for("camaras"))


@app.route("/camaras/stream/<int:cam_id>")
@login_required
def camara_stream(cam_id):
    """Endpoint MJPEG — devuelve el stream continuo de la cámara."""
    if not _CAMERAS_OK:
        abort(503)
    cam = db.get_camara(cam_id)
    if not cam or not cam["activa"]:
        abort(404)
    # El stream es bloqueante; no aplicar rate-limiter estándar aquí
    from flask import Response as _Resp
    return _Resp(
        generate_mjpeg(cam_id, cam["url_stream"]),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate",
                 "X-Accel-Buffering": "no"},   # evita que Nginx almacene el buffer
    )


@app.route("/camaras/snapshot/<int:cam_id>")
@login_required
def camara_snapshot(cam_id):
    """Devuelve un JPEG estático (para thumbnails o previsualización)."""
    if not _CAMERAS_OK:
        abort(503)
    cam = db.get_camara(cam_id)
    if not cam or not cam["activa"]:
        abort(404)
    from flask import Response as _Resp
    frame = get_snapshot(cam_id, cam["url_stream"])
    return _Resp(frame, mimetype="image/jpeg",
                 headers={"Cache-Control": "no-cache"})


@app.route("/api/camaras/<eco>")
@login_required
def api_camaras_eco(eco):
    """Devuelve JSON con las cámaras activas de un equipo (para carga dinámica)."""
    cams = db.get_camaras(eco=eco.upper(), solo_activas=True)
    return jsonify([{
        "id":          c["id"],
        "nombre":      c["nombre"],
        "descripcion": c.get("descripcion") or "",
        "stream_url":  url_for("camara_stream", cam_id=c["id"]),
        "snapshot_url": url_for("camara_snapshot", cam_id=c["id"]),
    } for c in cams])


if __name__ == "__main__":
    print("="*50)
    print("  GRUPO ESMA — Plataforma de Telemetría")
    print("  http://localhost:5000")
    print("="*50)
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)
