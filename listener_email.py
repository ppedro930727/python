#!/usr/bin/env python3
"""
listener_email.py — Receptor de correos entrantes (IMAP)
Revisa la bandeja de Gmail cada 30 segundos.

Funcionalidad:
1. Si llega un reply a una notificación del chat interno (detectado por [ESMA-Chat-{cid}]
   en el asunto), inserta el mensaje en la conversación correspondiente con el usuario real.
2. Si llega un reply de un contacto externo con conversación activa (título "✉ email"),
   inserta el mensaje como mensaje externo.
3. Si llega un email de un remitente desconocido sin tag de conversación,
   crea una nueva conversación externa.

Ejecutar como servicio: python3 listener_email.py
"""
import imaplib
import email
from email.header import decode_header
import time
import os
import sys
import re

# Cargar .env
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

# Agregar el directorio al path para importar database
sys.path.insert(0, os.path.dirname(__file__))
import database as db

IMAP_HOST = os.environ.get("IMAP_HOST", "imap.g_mail.com")
IMAP_PORT = int(os.environ.get("IMAP_PORT", "993"))
IMAP_USER = os.environ.get("SMTP_USER", "")
IMAP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
CHECK_INTERVAL = int(os.environ.get("EMAIL_CHECK_INTERVAL", "30"))  # segundos

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads", "chat")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Regex para detectar tag de conversación en asunto o cuerpo
ESMA_CHAT_TAG_RE = re.compile(r'\[ESMA-Chat-(\d+)\]')


def decode_subject(msg):
    """Decodifica el asunto del email."""
    subject = msg.get("Subject", "")
    decoded = decode_header(subject)
    parts = []
    for part, charset in decoded:
        if isinstance(part, bytes):
            parts.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(part)
    return " ".join(parts)


def decode_from(msg):
    """Extrae el email del remitente."""
    from_header = msg.get("From", "")
    # Extraer email de "Nombre <email@domain.com>"
    match = re.search(r'<(.+?)>', from_header)
    if match:
        return match.group(1).lower()
    return from_header.strip().lower()


def get_body(msg):
    """Extrae el cuerpo del mensaje (texto plano preferido)."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition") or "")
            if content_type == "text/plain" and "attachment" not in disposition:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    body = payload.decode(charset, errors="replace")
                    break
        # Si no hay texto plano, intentar HTML
        if not body:
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        html = payload.decode(charset, errors="replace")
                        # Quitar tags HTML básico
                        body = re.sub(r'<[^>]+>', '', html)
                        body = body.strip()[:2000]
                        break
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            body = payload.decode(charset, errors="replace")

    # Limpiar quoted text (respuestas tienen el mensaje original abajo)
    lines = body.split("\n")
    clean_lines = []
    for line in lines:
        # Detectar inicio de mensaje citado
        if line.strip().startswith(">") or "wrote:" in line.lower() or "escribió:" in line.lower():
            break
        if "---------- Forwarded message" in line or "---------- Mensaje reenviado" in line:
            break
        if re.match(r'^El .+ escribió:$', line.strip()):
            break
        if re.match(r'^On .+ wrote:$', line.strip()):
            break
        # Detectar la firma de nuestro propio email (evitar capturar el tag al final)
        if line.strip() == "---":
            break
        if ESMA_CHAT_TAG_RE.search(line):
            break
        clean_lines.append(line)
    return "\n".join(clean_lines).strip()


def get_attachments(msg):
    """Extrae archivos adjuntos y los guarda en uploads/chat/."""
    attachments = []
    if not msg.is_multipart():
        return attachments
    for part in msg.walk():
        disposition = str(part.get("Content-Disposition") or "")
        if "attachment" in disposition:
            filename = part.get_filename()
            if filename:
                # Decodificar nombre
                decoded = decode_header(filename)
                if decoded[0][1]:
                    filename = decoded[0][0].decode(decoded[0][1], errors="replace")
                elif isinstance(decoded[0][0], bytes):
                    filename = decoded[0][0].decode("utf-8", errors="replace")
                else:
                    filename = decoded[0][0]
                # Guardar archivo
                safe_name = f"inbox_{int(time.time())}_{filename}"
                filepath = os.path.join(UPLOAD_FOLDER, safe_name)
                with open(filepath, "wb") as f:
                    f.write(part.get_payload(decode=True))
                attachments.append({"nombre_disco": safe_name, "nombre_original": filename})
    return attachments


def extract_conversation_id(msg, body_text):
    """
    Intenta extraer el ID de conversación del tag [ESMA-Chat-{cid}].
    Busca en: header X-ESMA-CID, asunto, y cuerpo del email.
    """
    # 1. Buscar header X-ESMA-CID (en caso de que el cliente lo preserve en reply)
    x_cid = msg.get("X-ESMA-CID")
    if x_cid:
        try:
            return int(x_cid)
        except (ValueError, TypeError):
            pass

    # 2. Buscar en el asunto (Re: [ESMA-Chat-5] Nuevo mensaje de...)
    subject = decode_subject(msg)
    match = ESMA_CHAT_TAG_RE.search(subject)
    if match:
        return int(match.group(1))

    # 3. Buscar en el In-Reply-To o References del email original
    # (Gmail suele mantener el subject original en replies)

    # 4. Buscar en el cuerpo completo (incluye texto citado con el tag)
    # Necesitamos el cuerpo SIN limpiar para buscar el tag
    raw_body = get_raw_body(msg)
    match = ESMA_CHAT_TAG_RE.search(raw_body)
    if match:
        return int(match.group(1))

    return None


def get_raw_body(msg):
    """Extrae el cuerpo completo sin limpiar quoted text (para buscar tags)."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition") or "")
            if content_type == "text/plain" and "attachment" not in disposition:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    body = payload.decode(charset, errors="replace")
                    break
        if not body:
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        html = payload.decode(charset, errors="replace")
                        body = re.sub(r'<[^>]+>', '', html)
                        break
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            body = payload.decode(charset, errors="replace")
    return body


def find_user_by_email(sender_email):
    """Busca un usuario registrado por su email."""
    user = db.get_usuario_by_email(sender_email)
    return user


def find_conversation_by_email(sender_email):
    """Busca una conversación existente con el email externo (formato ✉ email)."""
    titulo = f"✉ {sender_email}"
    conv = db.query("SELECT id FROM chat_conversaciones WHERE titulo=%s", (titulo,), one=True)
    return conv["id"] if conv else None


def is_participant(cid, user_id):
    """Verifica si el usuario es participante de la conversación."""
    result = db.query(
        "SELECT 1 FROM chat_participantes WHERE id_conversacion=%s AND id_usuario=%s",
        (cid, user_id), one=True
    )
    return result is not None


def process_email(msg):
    """Procesa un email entrante y lo inserta en la conversación si corresponde."""
    sender = decode_from(msg)
    subject = decode_subject(msg)
    body = get_body(msg)
    attachments = get_attachments(msg)

    if not sender or sender == IMAP_USER.lower():
        return False  # Ignorar nuestros propios emails

    print(f"[INBOX] Procesando email de: {sender} | Asunto: {subject[:60]}")

    # ═══ CASO 1: Respuesta a notificación del chat interno ═══
    # Buscar tag [ESMA-Chat-{cid}] en asunto o cuerpo
    cid = extract_conversation_id(msg, body)

    if cid:
        # Es una respuesta a una notificación del chat interno
        user = find_user_by_email(sender)
        if user and is_participant(cid, user["id"]):
            # Usuario registrado y participante — insertar como su mensaje
            archivo_nombre = None
            archivo_original = None
            if attachments:
                archivo_nombre = attachments[0]["nombre_disco"]
                archivo_original = attachments[0]["nombre_original"]

            if not body and not archivo_nombre:
                print(f"[INBOX]   ⚠ Email de {sender} sin contenido útil, ignorando")
                return False

            db.enviar_mensaje(cid, user["id"], body, archivo_nombre, archivo_original, None)
            print(f"[INBOX]   ✓ Mensaje de {user['nombre']} insertado en conversacion {cid} (chat interno)")
            return True
        elif user:
            # Usuario registrado pero no participante — agregarlo y luego insertar
            db.execute(
                "INSERT IGNORE INTO chat_participantes (id_conversacion, id_usuario) VALUES (%s, %s)",
                (cid, user["id"])
            )
            archivo_nombre = None
            archivo_original = None
            if attachments:
                archivo_nombre = attachments[0]["nombre_disco"]
                archivo_original = attachments[0]["nombre_original"]

            if body or archivo_nombre:
                db.enviar_mensaje(cid, user["id"], body, archivo_nombre, archivo_original, None)
                print(f"[INBOX]   ✓ {user['nombre']} agregado a conversacion {cid} y mensaje insertado")
                return True
        else:
            # Email no registrado pero con tag de conversación — insertar como externo
            contenido = f"[Respuesta de: {sender}]\n{body}" if body else f"[Respuesta de: {sender}] (sin texto)"
            archivo_nombre = None
            archivo_original = None
            if attachments:
                archivo_nombre = attachments[0]["nombre_disco"]
                archivo_original = attachments[0]["nombre_original"]
            db.execute("""
                INSERT INTO chat_mensajes (id_conversacion, id_usuario, contenido, archivo, archivo_original, archivo_tipo)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (cid, 0, contenido.strip(), archivo_nombre, archivo_original, None))
            print(f"[INBOX]   ✓ Respuesta externa de {sender} insertada en conversacion {cid}")
            return True

    # ═══ CASO 2: Email sin tag — buscar conversación externa existente ═══
    cid = find_conversation_by_email(sender)
    if cid:
        contenido = f"[De: {sender}]\n"
        if subject:
            contenido += f"Asunto: {subject}\n\n"
        contenido += body if body else "(sin texto)"

        archivo_nombre = None
        archivo_original = None
        if attachments:
            archivo_nombre = attachments[0]["nombre_disco"]
            archivo_original = attachments[0]["nombre_original"]

        db.execute("""
            INSERT INTO chat_mensajes (id_conversacion, id_usuario, contenido, archivo, archivo_original, archivo_tipo)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (cid, 0, contenido.strip(), archivo_nombre, archivo_original, None))
        print(f"[INBOX]   ✓ Email externo de {sender} insertado en conversacion existente {cid}")
        return True

    # ═══ CASO 3: Email nuevo sin conversación — crear conversación externa ═══
    cid = db.execute("""
        INSERT INTO chat_conversaciones (titulo, es_grupo, creado_por) VALUES (%s, 0, NULL)
    """, (f"✉ {sender}",))
    # Agregar al admin como participante
    admin = db.query("SELECT id FROM usuarios WHERE rol='admin' LIMIT 1", one=True)
    if admin:
        db.execute("INSERT IGNORE INTO chat_participantes (id_conversacion, id_usuario) VALUES (%s, %s)",
                   (cid, admin["id"]))

    contenido = f"[De: {sender}]\n"
    if subject:
        contenido += f"Asunto: {subject}\n\n"
    contenido += body if body else "(sin texto)"

    archivo_nombre = None
    archivo_original = None
    if attachments:
        archivo_nombre = attachments[0]["nombre_disco"]
        archivo_original = attachments[0]["nombre_original"]

    db.execute("""
        INSERT INTO chat_mensajes (id_conversacion, id_usuario, contenido, archivo, archivo_original, archivo_tipo)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (cid, 0, contenido.strip(), archivo_nombre, archivo_original, None))
    print(f"[INBOX]   ✓ Nueva conversacion {cid} creada para {sender}")
    return True


def check_inbox():
    """Revisa la bandeja de entrada y procesa emails no leídos."""
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        mail.login(IMAP_USER, IMAP_PASSWORD)
        mail.select("INBOX")

        # Buscar emails no leídos
        status, messages = mail.search(None, "UNSEEN")
        if status != "OK" or not messages[0]:
            mail.logout()
            return 0

        email_ids = messages[0].split()
        processed = 0

        for eid in email_ids[-10:]:  # Procesar máximo 10 por ciclo
            status, msg_data = mail.fetch(eid, "(RFC822)")
            if status != "OK":
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            if process_email(msg):
                processed += 1
            # Marcar como leído siempre (para no reprocesar)
            mail.store(eid, "+FLAGS", "\\Seen")

        mail.logout()
        return processed
    except Exception as e:
        print(f"[INBOX] ✗ Error: {e}")
        return 0


def main():
    if not IMAP_USER or not IMAP_PASSWORD:
        print("[INBOX] ✗ SMTP_USER/PASSWORD no configurados. No se pueden recibir emails.")
        sys.exit(1)

    print(f"[INBOX] Listener iniciado — revisando {IMAP_USER} cada {CHECK_INTERVAL}s")
    print(f"[INBOX] IMAP: {IMAP_HOST}:{IMAP_PORT}")
    print(f"[INBOX] Detecta respuestas a chat interno por tag [ESMA-Chat-ID] en asunto/cuerpo")

    while True:
        try:
            n = check_inbox()
            if n > 0:
                print(f"[INBOX] {n} email(s) procesado(s)")
        except KeyboardInterrupt:
            print("\n[INBOX] Detenido")
            break
        except Exception as e:
            print(f"[INBOX] Error en ciclo: {e}")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
