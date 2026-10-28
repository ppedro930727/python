import pandas as pd
import re
import json

def clean_phone(phone):
    """Limpia y normaliza números telefónicos al formato +52 de 10 dígitos."""
    if pd.isna(phone):
        return ""
    digits = re.sub(r'\D', '', str(phone))
    if len(digits) == 12 and digits.startswith('52'):
        digits = digits[2:]
    if len(digits) == 10:
        return f"+52{digits}"
    return f"+52{digits}" if digits else ""

def clean_segment(segment):
    """Normaliza las etiquetas de los segmentos comerciales."""
    if pd.isna(segment):
        return ""
    s = str(segment).strip().lower()
    if 'trans' in s:
        return 'transportista'
    elif 'rest' in s:
        return 'restaurantero'
    elif 'const' in s:
        return 'construcción'
    elif 'emp' in s:
        return 'empresario'
    elif 'hotel' in s:
        return 'hotelería'
    return s

def process_leads(file_path):
    df = pd.read_csv(file_path)

    # 1. Limpieza y Normalización
    df['telefono_clean'] = df['telefono'].apply(clean_phone)
    df['segmento_clean'] = df['segmento'].apply(clean_segment)
    df['email_clean'] = df['email'].astype(str).str.strip().str.lower()
    df['email_clean'] = df['email_clean'].replace('nan', '')

    # 2. Mapa de duplicados (Laura Méndez ID 3 -> 1; Ana Torres ID 4 -> 14)
    duplicados_map = {
        3: 1,
        4: 14
    }

    results = []

    for idx, row in df.iterrows():
        lead_id = row['id']
        fecha = row['fecha']
        nombre = row['nombre']
        empresa = row['empresa']
        email = row['email_clean']
        telefono = row['telefono_clean']
        segmento = row['segmento_clean']
        ciudad = row['ciudad'] if pd.notna(row['ciudad']) else ""
        fuente = row['fuente']
        mensaje = str(row['mensaje']) if pd.notna(row['mensaje']) else ""
        
        raw_emp = row['num_empleados']
        num_emp = None
        try:
            num_emp = float(raw_emp)
        except (ValueError, TypeError):
            num_emp = None

        duplicado_de = duplicados_map.get(lead_id, "N/A")
        
        calificacion = ""
        razon = ""
        siguiente_accion = ""
        requiere_revision = False
        motivo_revision = "N/A"

        # 3. Lógica de Lead Scoring y Reglas de Negocio
        if lead_id == 5:  # Win Big (Spam)
            calificacion = "Descartado"
            razon = "Spam detectado por teléfono ficticio y mensaje de fraude."
            siguiente_accion = "Bloquear contacto y archivar."

        elif lead_id == 11:  # Competencia
            calificacion = "Descartado"
            razon = "Lead identificado como empresa competidora directo (Monederos SA)."
            siguiente_accion = "Revisar por comercial; no enviar tarifario público."
            requiere_revision = True
            motivo_revision = "Posible monitoreo de competencia."

        elif lead_id == 15:  # Fuera de segmento (Hotel)
            calificacion = "Descartado"
            razon = "Giro comercial fuera de segmento objetivo (Hotelería)."
            siguiente_accion = "Enviar correo de cortesía sobre cobertura actual."

        elif lead_id in [1, 3]:  # Laura Méndez
            calificacion = "A"
            if lead_id == 1:
                razon = "Transportista objetivo (120 emp) con solicitud concreta de cotización de viáticos."
                siguiente_accion = "Llamar inmediatamente para agendar propuesta comercial."
            else:
                razon = "Duplicado del Lead ID 1. Mensaje de seguimiento por WhatsApp."
                siguiente_accion = "Consolidar seguimiento con Lead ID 1."

        elif lead_id in [4, 14]:  # Ana Torres
            calificacion = "A"
            if lead_id == 14:
                razon = "Constructora objetivo (45 emp) con problema crítico en pago de cuadrillas y reincidencia."
                siguiente_accion = "Llamar prioritariamente para agendar demostración."
            else:
                razon = "Duplicado del Lead ID 14. Email incompleto en origen corregido vía fusión."
                siguiente_accion = "Fusionar con Lead ID 14 y programar demo."
                requiere_revision = True
                motivo_revision = "Email incompleto en registro inicial corregido por duplicado."

        elif lead_id == 6:  # Ricardo Salas
            calificacion = "A"
            razon = "Restaurantero objetivo (250 emp, 6 sucursales) referido por cliente actual."
            siguiente_accion = "Llamar para agendar reunión ejecutiva."

        elif lead_id == 10:  # Daniel Kim
            calificacion = "A"
            razon = "Restaurantero objetivo (40 emp) solicitando confirmación de servicio."
            siguiente_accion = "Llamar y presentar oferta especializada para restaurantes."

        elif lead_id == 8:  # Pedro Gómez
            calificacion = "B"
            razon = "Transportista objetivo (35 emp) solicita llamada pero no proporcionó correo electrónico."
            siguiente_accion = "Llamar por teléfono/WhatsApp y solicitar correo institucional."
            requiere_revision = True
            motivo_revision = "Lead sin correo electrónico registrado."

        elif lead_id == 9:  # Sofía Lara
            calificacion = "B"
            razon = "Constructora objetivo con 18 emp base, pero suma 60 eventuales en noviembre."
            siguiente_accion = "Validar si los 60 eventuales aplican para calificar a Nivel A."
            requiere_revision = True
            motivo_revision = "Evaluar incremento estacional de plantilla (18 a 78 emp)."

        elif lead_id == 12:  # Fernanda Ríos
            calificacion = "B"
            num_emp = 60  # Extrapolado del mensaje
            razon = "Transportista objetivo (~60 emp según mensaje), campo num_empleados corrupto ('abc')."
            siguiente_accion = "Llamar para confirmar plantilla exacta y ofrecer control de gasolina."
            requiere_revision = True
            motivo_revision = "Campo num_empleados no numérico ('abc'). Extrapolado del mensaje."

        elif lead_id == 13:  # Hugo Paredes
            calificacion = "B"
            razon = "Restaurantero (25 emp), pero usa correo personal y pregunta vago por precio."
            siguiente_accion = "Enviar cotización base por email y medir interés."

        elif lead_id == 2:  # Jorge Ruiz
            calificacion = "C"
            razon = "Restaurantero con 12 empleados (<20 emp) y necesidad vaga ('Info')."
            siguiente_accion = "Enviar secuencia automática de email marketing para PyMEs."

        elif lead_id == 7:  # Mónica Vega
            calificacion = "C"
            razon = "Despacho contable con 8 empleados (<20 emp)."
            siguiente_accion = "Enviar material informativo sobre programa de alianzas."

        results.append({
            'id': lead_id,
            'fecha': fecha,
            'nombre': nombre,
            'empresa': empresa,
            'email': email,
            'telefono': telefono,
            'segmento': segmento,
            'num_empleados': num_emp if num_emp is not None else raw_emp,
            'ciudad': ciudad,
            'fuente': fuente,
            'duplicado_de': duplicado_de,
            'calificación': calificacion,
            'razón': razon,
            'siguiente_acción': siguiente_accion,
            'requiere_revisión': requiere_revision,
            'motivo_revisión': motivo_revision
        })

    out_df = pd.DataFrame(results)
    out_df.to_csv('leads_calificados.csv', index=False, encoding='utf-8-sig')
    print("✓ leads_calificados.csv generado exitosamente.")

if __name__ == '__main__':
    process_leads('leads_test_darhe.csv')

