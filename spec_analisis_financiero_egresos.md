# Spec: Egresos del Análisis Financiero calculados desde Requisiciones

**Estado:** Listo para implementar  
**Fecha:** 2026-10-23  
**Proyecto:** maquinaria_web (Grupo ESMA)

---

## Contexto y problema actual

El Análisis Financiero (`/analisis-financiero?obra=N`) muestra egresos en 7 renglones
que se capturan **a mano** por semana en `analisis_financiero_egresos`. Esto se desacopla
de las requisiciones reales, genera doble captura y puede tener inconsistencias.

Las requisiciones ya registran **qué se pagó, cuánto y cuándo** en `requisicion_partidas`:
- `monto_autorizado` → siempre en **pesos mexicanos** (aunque `cantidad`/`unidad` sean m³, ton, etc.)
- `estatus_pago = 'pagado'` → confirmación de que el gasto se realizó
- `fecha_pago` → fecha real del pago (para asignarlo a la semana correcta)
- `id_codigo_costo` → liga el gasto a una familia del catálogo (1–7)

**Objetivo:** los egresos deben calcularse **en vivo** desde `requisicion_partidas`
donde `estatus_pago = 'pagado'`, usando `monto_autorizado` como monto en pesos.

---

## Reglas de negocio

### Fuente de datos
- Tabla: `requisicion_partidas` JOIN `requisiciones`
- Filtro: `requisicion_partidas.estatus_pago = 'pagado'`
- Monto: **`requisicion_partidas.monto_autorizado`** (siempre pesos)
- Obra: `requisiciones.id_obra`

### Asignación a semana
```
numero_semana = (fecha_pago - analisis_financiero_config.fecha_inicio).days // 7 + 1
```
- Si `fecha_inicio` es NULL en config → mostrar nota "configura fecha de inicio"
- Pagos con semana < 1 o > semanas_proyecto → van a fila **"Fuera de rango"** (visible, no descartados)

### Resolución de rubro por código de costo
1. Tomar `id_codigo_costo` de la partida (respaldo: `id_codigo_costo` de la cabecera `requisiciones`)
2. Si ninguno → rubro = **"sin_clasificar"**
3. Si hay código, obtener `codigos_costo.codigo` (ej. `"4-06-001"`)
4. Buscar prefijo más largo en `codigo_rubro(prefijo, rubro_clave)`:
   - Intenta `"4-06-001"` → si no existe, intenta `"4-06"` → si no, intenta `"4"`
   - Primera coincidencia gana

### Tabla nueva: `analisis_rubros`
Define los renglones del análisis (reemplaza los 7 hardcodeados):

```sql
CREATE TABLE analisis_rubros (
    id      INT AUTO_INCREMENT PRIMARY KEY,
    clave   VARCHAR(40) NOT NULL UNIQUE,       -- 'equipo', 'materiales', etc.
    etiqueta VARCHAR(120) NOT NULL,             -- texto en pantalla
    seccion ENUM('DIRECTO','INDIRECTO') NOT NULL,
    orden   SMALLINT NOT NULL DEFAULT 0,        -- orden de aparición dentro de sección
    activo  TINYINT(1) NOT NULL DEFAULT 1
);
```

Agregar o renombrar un concepto = INSERT/UPDATE en esta tabla, sin tocar código.

### Tabla nueva: `codigo_rubro`
Mapeo de prefijos de código de costo a clave de rubro:

```sql
CREATE TABLE codigo_rubro (
    id       INT AUTO_INCREMENT PRIMARY KEY,
    prefijo  VARCHAR(30) NOT NULL UNIQUE,  -- '1', '4-06', '6-01', etc.
    rubro_clave VARCHAR(40) NOT NULL       -- FK lógica a analisis_rubros.clave
);
```

### Datos semilla para `analisis_rubros`

| clave | etiqueta | sección | orden |
|---|---|---|---|
| equipo | Equipo, Herramienta y Maquinaria | DIRECTO | 1 |
| combustibles | Combustibles | DIRECTO | 2 |
| materiales | Materiales | DIRECTO | 3 |
| subcontratos | Subcontratos | DIRECTO | 4 |
| mano_obra | Mano de Obra | DIRECTO | 5 |
| acarreos | Acarreos | DIRECTO | 6 |
| pagos_imss | Pagos IMSS | INDIRECTO | 1 |
| nomina | Costo de Nómina | INDIRECTO | 2 |
| indirectos_campo | Indirectos de Campo | INDIRECTO | 3 |
| indirectos_oficina | Indirectos de Oficina | INDIRECTO | 4 |
| sin_clasificar | Sin clasificar | INDIRECTO | 99 |

### Datos semilla para `codigo_rubro`

| prefijo | rubro_clave |
|---|---|
| 1 | equipo |
| 2 | combustibles |
| 3 | materiales |
| 4 | subcontratos |
| 4-06 | mano_obra |
| 5 | acarreos |
| 6-01 | pagos_imss |
| 6-02 | pagos_imss |
| 6-03 | nomina |
| 6-04 | nomina |
| 7-01 | indirectos_campo |
| 7-02 | indirectos_campo |
| 7-06 | indirectos_campo |
| 7-07 | indirectos_campo |
| 7-08 | indirectos_campo |
| 7-09 | indirectos_campo |
| 7-11 | indirectos_campo |
| 7-12 | indirectos_campo |
| 7-13 | indirectos_campo |
| 7-14 | indirectos_campo |
| 7-15 | indirectos_campo |
| 7-16 | indirectos_campo |
| 7-18 | indirectos_campo |
| 7-20 | indirectos_campo |
| 7-03 | indirectos_oficina |
| 7-04 | indirectos_oficina |
| 7-05 | indirectos_oficina |
| 7-10 | indirectos_oficina |
| 7-17 | indirectos_oficina |
| 7-19 | indirectos_oficina |
| 7 | indirectos_campo |

> Nota: `7` como fallback captura cualquier código de familia 7 no mapeado específicamente → campo.

---

## Correcciones menores previas (requisicion_detalle.html)

1. **`step="00"` → `step="0.01"`** en input `monto_autorizado_{{ p.id }}` (pestaña Autorizar)
2. **Comilla faltante** en `<thead style="...#004694)>` de pestaña Sin IMSS → agregar `"` antes del `>`
3. **`value="None"`**: si `p.monto_autorizado` es None, el input muestra el texto "None" → cambiar a `value="{{ p.monto_autorizado or '' }}"`
4. **Validación servidor**: en `requisicion_pago_partida`, si `estatus_pago == 'pagado'`, exigir que `fecha_pago` no sea vacía (flash de error si falta)
5. **Protección montos pagados**: en `requisicion_autorizar_montos` y `requisicion_editar_autorizado`, no permitir cambiar `monto_autorizado` de partidas con `estatus_pago = 'pagado'` (flash de advertencia)

---

## Preguntas abiertas (NO decidir, registrar y dejar para el usuario)

**A) Nómina (pestañas IMSS, Sin IMSS, Finiquitos)**  
Las tablas `nomina_imss`, `nomina_sin_imss`, `finiquitos` no tienen `estatus_pago` ni `fecha_pago`.  
En la versión 1, los egresos de nómina desde estas tablas quedan en **cero** hasta definir el modelo de pago.  
Propuesta futura: agregar `estatus_pago` y `fecha_pago` a esas tablas; `IMSS Total Real → 6-01`, comisión IMSS `→ 6-02`, Sin IMSS `→ 6-03`, Finiquitos `→ 6-04`.  
**Confirmar antes de crear columnas.**

**B) Campo `categoria` en `requisicion_partidas`**  
Valores observados: 'Administración', 'Otros', categorías de nómina.  
¿Algún valor de `categoria` representa nómina ya registrada en `nomina_imss`/`nomina_sin_imss`?  
Si sí, habría doble conteo al sumar partidas Y nóminas. Verificar antes de activar nóminas.

**C) Código `7-21`**  
El catálogo actual llega hasta `7-20-001` (171 registros). No existe `7-21`.  
¿Es un código que se agregará? Si sí, ¿a qué rubro pertenece?

---

## Arquitectura técnica

### Cálculo en vivo (sin caché)
`get_resumen_analisis_financiero` se reemplaza por una nueva versión que:
1. Obtiene las partidas pagadas de la obra con un solo JOIN:
   ```sql
   SELECT p.monto_autorizado, p.fecha_pago,
          COALESCE(p.id_codigo_costo, r.id_codigo_costo) AS id_cc,
          cc.codigo AS codigo_cc
   FROM requisicion_partidas p
   JOIN requisiciones r ON r.id = p.id_requisicion
   LEFT JOIN codigos_costo cc ON cc.id = COALESCE(p.id_codigo_costo, r.id_codigo_costo)
   WHERE r.id_obra = %s AND p.estatus_pago = 'pagado'
   ```
2. Para cada partida: resuelve rubro por prefijo más largo contra `codigo_rubro`
3. Calcula número de semana desde `fecha_pago` y `fecha_inicio` de config
4. Acumula en dict `{semana: {rubro_clave: total}}`
5. Construye el resultado con los rubros definidos en `analisis_rubros`

### Compatibilidad con ingresos
Los ingresos (`analisis_financiero_ingresos`) **NO se tocan**. La sección de ingresos sigue siendo captura manual.

### La ruta `analisis_financiero_egresos`
Se **comenta** (redirect a analisis_financiero con mensaje explicativo). No se borra.  
La función `db.guardar_egresos_semana` tampoco se borra.

### Modal de egresos en el template
Se elimina del template el formulario de captura de egresos. El modal de ingresos permanece.

### Celda clickeable
Al hacer clic en una celda de egreso, abre un panel/modal con las partidas que la componen:
- Columnas: Requisición (semana), Proveedor, Concepto, Código de costo, Monto, Fecha pago

---

## Tareas de implementación

### Tarea 1 — Correcciones menores en requisicion_detalle.html y rutas
**Archivos:** `templates/requisicion_detalle.html`, `app.py`  
**Cómo probar:** Abrir una requisición aprobada, intentar ingresar centavos en "Autorizar montos" — debe aceptarlos. En pestaña Sin IMSS, el thead debe tener fondo azul. Intentar marcar como pagada sin fecha → debe rechazarse con flash.

### Tarea 2 — Script SQL de migración (tablas y semilla)
**Archivo nuevo:** `migracion_analisis_rubros.sql`  
Contenido:
- `CREATE TABLE IF NOT EXISTS analisis_rubros (...)`
- `CREATE TABLE IF NOT EXISTS codigo_rubro (...)`
- `INSERT` de los datos semilla de ambas tablas
- Comentarios `-- CONFIRMAR` en los prefijos de nómina (6-xx) hasta resolución del punto abierto A

**Cómo probar:** Ejecutar en MySQL, verificar con `SELECT * FROM analisis_rubros ORDER BY seccion, orden` y `SELECT * FROM codigo_rubro ORDER BY prefijo`.

### Tarea 3 — Funciones en database.py
**Archivo:** `database.py`  
Nuevas funciones:
- `_init_tablas_analisis_rubros()` — CREATE IF NOT EXISTS (se llama al arrancar)
- `get_analisis_rubros()` — SELECT activo=1 ORDER BY seccion, orden
- `get_codigo_rubro_map()` — devuelve dict `{prefijo: rubro_clave}` ordenado por len(prefijo) DESC para búsqueda por prefijo más largo
- `resolver_rubro(codigo_cc, mapa_rubros)` — dado un string de código, busca prefijo más largo
- `get_egresos_desde_requisiciones(id_obra)` — función principal: devuelve `{semana_num: {rubro_clave: float}}` + lista de partidas fuera de rango
- `get_partidas_egreso_celda(id_obra, semana_num, rubro_clave)` — para el detalle de celda clickeable
- Reemplazar `get_resumen_analisis_financiero(id_obra)` para usar los egresos calculados

**Cómo probar:** En la consola Python:
```python
import database as db
m = db.get_codigo_rubro_map()
print(db.resolver_rubro("4-06-001", m))  # → 'mano_obra'
print(db.resolver_rubro("4-01-002", m))  # → 'subcontratos'
print(db.resolver_rubro("9-99", m))      # → 'sin_clasificar'
```

### Tarea 4 — Template analisis_financiero.html
**Archivo:** `templates/analisis_financiero.html`  
Cambios:
- Reemplazar los 7 bloques `<tr>` hardcodeados de egresos por un loop sobre `rubros_directos` y `rubros_indirectos` (pasados desde la ruta)
- Cada celda con `onclick="verDetalleCelda(obra_id, semana_num, 'rubro_clave')"` 
- Agregar fila "Fuera de rango" si hay pagos fuera del calendario
- Agregar fila "Sin clasificar" si hay partidas sin código de costo
- Eliminar el modal/formulario de captura de egresos (conservar el de ingresos)
- Agregar modal de detalle de celda (tabla con partidas)
- Nueva ruta `GET /analisis-financiero/celda?obra=N&semana=N&rubro=X` que responde JSON con las partidas

**Cómo probar:** Con al menos 1 partida pagada con `fecha_pago` y `id_codigo_costo` asignado, abrir `/analisis-financiero?obra=N`. Debe aparecer el monto en la semana y rubro correctos. Clic en la celda → modal con el detalle de la partida.

### Tarea 5 — Nómina (PENDIENTE, no implementar aún)
Queda bloqueada por las preguntas abiertas A y B.  
Cuando se resuelvan, se agrega en tarea separada.

---

## Lo que NO cambia

- Tabla `analisis_financiero_egresos` — se conserva (no se borra)
- Función `guardar_egresos_semana` — se conserva (no se borra)
- Ingresos — sin cambios
- Permisos `@permiso_requerido` — sin cambios
- Estilos y columnas sticky del template — se mantienen
- Toda la lógica de requisiciones (partidas, aprobación, arrastres, nóminas)
