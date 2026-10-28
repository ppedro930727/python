#!/usr/bin/env python3
"""Script auxiliar para enviar correos via SMTP.
Se ejecuta como subproceso independiente para evitar conflictos con gevent/eventlet.
Recibe los datos del correo via JSON en stdin."""
import sys, json, os, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

def main():
    data = json.loads(sys.stdin.read())
    host = data["host"]
    port = int(data["port"])
    user = data["user"]
    password = data["password"]
    from_name = data["from_name"]
    from_email = data["from_email"]
    destinatario = data["destinatario"]
    asunto = data["asunto"]
    cuerpo_html = data["cuerpo_html"]
    cuerpo_texto = data.get("cuerpo_texto", "")
    adjunto_path = data.get("adjunto_path")
    adjunto_nombre = data.get("adjunto_nombre")
    headers = data.get("headers", {})

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = f"{from_name} <{from_email}>"
        msg["To"] = destinatario
        msg["Subject"] = asunto

        # Headers personalizados (Reply-To, X-ESMA-CID, etc.)
        for hdr_name, hdr_value in headers.items():
            msg[hdr_name] = str(hdr_value)

        if cuerpo_texto:
            msg.attach(MIMEText(cuerpo_texto, "plain", "utf-8"))
        msg.attach(MIMEText(cuerpo_html, "html", "utf-8"))

        if adjunto_path and os.path.exists(adjunto_path):
            with open(adjunto_path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
                encoders.encode_base64(part)
                nombre = adjunto_nombre or os.path.basename(adjunto_path)
                part.add_header("Content-Disposition", f'attachment; filename="{nombre}"')
                msg.attach(part)

        server = smtplib.SMTP(host, port, timeout=30)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(user, password)
        server.sendmail(from_email, [destinatario], msg.as_string())
        server.quit()
        print(f"OK: Enviado a {destinatario}")
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
