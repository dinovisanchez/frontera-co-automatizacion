"""CAPEX — orquestador de la propuesta de equipos. Puerto de construirPropuestaEquipos
(Codigo.gs líneas 4054-4767): a partir del diagnóstico (clasificador_medida) + spec (acta) +
el veredicto de Lovable, arma las filas a guardar en "Equipos" y las alertas que requieren
decisión humana.

`dictamen` es el mismo JSON que ya arma Index.html en el original:
{"clasificacion": "cumple"|"recuperable"|"normalizacion", "secciones": {...ya auto-detectadas
por deteccion_equipos.detectar_secciones_deficientes + lo forzado a mano}, ...}
"""

from core.services.catalogo_capex import candidatos_por_categoria_alcance
from core.services.deteccion_equipos import describir_condicion_actual, inferir_categoria_desde_texto
from core.services.propuesta_bloque_celda_cable import resolver_propuesta_bloque, resolver_propuesta_cable, resolver_propuesta_celda
from core.services.propuesta_equipos_contexto import _armar_contexto
from core.services.propuesta_tc import resolver_propuesta_tc
from core.services.propuesta_tp_medidor import resolver_propuesta_medidor, resolver_propuesta_tp

_ETIQUETA_GRUPO_A_CATEGORIA_ACTUAL = {"TC": "tc", "TP": "tp", "Medidor": "medidor"}


def construir_propuesta_equipos(
    diagnostico: dict, spec: dict, catalogo: list[dict], equipos_existentes: list[dict],
    dictamen: dict, equipos_actuales: dict, nt_cambio: dict | None, norm_indirectas: dict | None,
    relacion_certificada_tc: dict | None, relacion_certificada_tp: dict | None, or_real: str | None,
) -> dict:
    propuesta: list[dict] = []
    alertas: list[str] = []
    dictamen = dict(dictamen or {})
    equipos_actuales = equipos_actuales or {}

    if diagnostico["reclasificado"] and dictamen.get("clasificacion") != "normalizacion":
        alertas.append(f'⚠️ Lovable dice "{dictamen.get("clasificacion") or "sin clasificación"}", pero el motor de reglas CREG 038/2014 (Art.19) indica que esta frontera debe ser Indirecta (transformador de uso exclusivo en BT reclasifica a NT2, sin importar la capacidad) — Lovable evaluó completitud de equipos para el nivel de medida asumido, no si ese nivel es el correcto. Se genera el alcance completo de Indirecta; si el transformador en realidad es compartido, corrígelo en Lovable y vuelve a analizar.')
        dictamen["clasificacion"] = "normalizacion"

    burden_tc_desigual = bool((equipos_actuales.get("tc") or {}).get("burdenes_desiguales"))
    burden_tp_desigual = bool((equipos_actuales.get("tp") or {}).get("burdenes_desiguales"))
    if (burden_tc_desigual or burden_tp_desigual) and dictamen.get("clasificacion") != "normalizacion":
        etiqueta = ("TC" if burden_tc_desigual else "") + ("/" if burden_tc_desigual and burden_tp_desigual else "") + ("TP" if burden_tp_desigual else "")
        alertas.append(f'⚠️ Lovable dice "{dictamen.get("clasificacion") or "sin clasificación"}", pero los {etiqueta} instalados en la última visita (Metabase) no tienen el mismo burden (VA) entre sí — un set trifásico debe ser homogéneo, eso es un defecto real de diseño/instalación sin importar la clasificación de Lovable. Se genera el alcance completo de Normalización para revisar/cambiar el set.')
        dictamen["clasificacion"] = "normalizacion"

    if dictamen.get("clasificacion") == "recuperable":
        return _propuesta_recuperable(dictamen, catalogo)
    if dictamen.get("clasificacion") == "cumple":
        return {"propuesta": [], "alertas": ['✓ Lovable clasifica este CO como "Cumple" — no se requiere alcance de equipos.']}
    if dictamen.get("clasificacion") != "normalizacion":
        return {"propuesta": [], "alertas": ['No se indicó la clasificación de Lovable (Cumple / Recuperable / Normalización) para este CO — sin eso no se puede proponer nada con seguridad.']}

    ctx = _armar_contexto(diagnostico, spec, catalogo, dictamen, equipos_actuales, nt_cambio, norm_indirectas, relacion_certificada_tc, or_real)
    faltan = ctx["faltan"]

    if ctx["diagnostico"]["tipo_medida_final"] == "directa":
        alertas.append("Medida Directa: no requiere TC/TP/bloque de pruebas/celda por norma (solo aplican a semidirecta/indirecta) — el medidor sí se revisa.")
        _filas_anomalas_en_directa(equipos_actuales, propuesta)

    if faltan.get("tc") and ctx["diagnostico"]["tipo_medida_final"] != "directa":
        resolver_propuesta_tc(ctx, propuesta, alertas)
        _propagar_ubicacion_desde_tc(ctx, propuesta, catalogo)

    if faltan.get("tp"):
        resolver_propuesta_tp(ctx, propuesta, alertas)
    if faltan.get("bloque_pruebas"):
        resolver_propuesta_bloque(ctx, propuesta)
    if faltan.get("medidor"):
        resolver_propuesta_medidor(ctx, propuesta)
    if faltan.get("celda"):
        resolver_propuesta_celda(ctx, propuesta)
    if faltan.get("cable"):
        resolver_propuesta_cable(ctx, propuesta, alertas)

    if nt_cambio and nt_cambio.get("maniobra_nt2"):
        alertas.append(f'ℹ️ "Data cambio NT" trae un valor en MANIOBRA NT2: "{nt_cambio["maniobra_nt2"]}" (parece un costo estimado de la maniobra, no necesariamente texto para la columna Maniobra) — revísalo antes de usarlo.')
    if norm_indirectas and norm_indirectas.get("bornera"):
        cantidad = f' (cantidad {norm_indirectas["bornera_cantidad"]})' if norm_indirectas.get("bornera_cantidad") is not None else ""
        alertas.append(f'ℹ️ "Normalizaciones_Indirectas" indica bornera: "{norm_indirectas["bornera"]}"{cantidad} — no hay un SKU de "bornera" independiente en ref_capex; revisa si va incluido en la celda o hay que agregarlo al catálogo.')

    _anotar_recalibracion_y_burden(propuesta, equipos_actuales)
    return {"propuesta": propuesta, "alertas": alertas}


def _propuesta_recuperable(dictamen: dict, catalogo: list[dict]) -> dict:
    detalle = dictamen.get("detalleFaltante") or []
    if not detalle:
        return {"propuesta": [], "alertas": ['📄 Lovable clasifica este CO como "Recuperable" — falta un documento (no equipo). Revisa el detalle en Lovable.']}
    propuesta = []
    for d in detalle:
        cat = inferir_categoria_desde_texto(d)
        propuesta.append({
            "grupo": cat.capitalize() if cat else "Recuperable", "cantidad": 1, "tipo": cat or "",
            "razon": f'📄 Recuperable — falta: {d}. Por defecto es un documento (no requiere equipo nuevo) — deja el SKU vacío y excluye esta fila si solo vas a gestionar el documento; complétalo solo si de verdad decides reemplazar el equipo.',
            "sku": None, "costo_estimado": None, "alternativas": candidatos_por_categoria_alcance(catalogo, cat) if cat else [], "requiere_confirmacion": True,
        })
    return {"propuesta": propuesta, "alertas": []}


def _filas_anomalas_en_directa(equipos_actuales: dict, propuesta: list[dict]) -> None:
    """Directa "no necesita TC/TP" no es lo mismo que "no necesita nada": si Metabase muestra
    un TC/TP/bloque instalado en una medida que por norma no debería tenerlo, es una anomalía
    real que merece revisión, no silencio (Codigo.gs línea 4194-4211)."""
    for clave, grupo, tipo in (("tc", "TC", "Transformador de corriente"), ("tp", "TP", "Transformador de potencial"), ("bloque_pruebas", "Bloque de pruebas", "Bloque de prueba")):
        actual = equipos_actuales.get(clave)
        if not actual:
            continue
        propuesta.append({
            "grupo": grupo, "cantidad": 1, "tipo": tipo,
            "razon": f'⚠️ Hay un {grupo} instalado ({describir_condicion_actual(actual)}) aunque la medida es Directa (por norma no debería tener uno) — puede ser equipo de una celda/gabinete compartido con otros clientes, o que quedó de un esquema anterior. Confirma en Lovable/con el cliente si de verdad hace falta cambiarlo o retirarlo; deja el SKU vacío si solo aplica gestión documental.',
            "sku": None, "costo_estimado": None, "alternativas": [], "requiere_confirmacion": True,
        })


def _propagar_ubicacion_desde_tc(ctx: dict, propuesta: list[dict], catalogo: list[dict]) -> None:
    """Un TC y un TP de la misma frontera no pueden quedar en ubicaciones distintas — si la
    ubicación no vino explícita del acta, se reutiliza la del ítem de catálogo que ganó para TC."""
    if ctx["ubicacion"]:
        return
    ultimo_tc = next((f for f in reversed(propuesta) if f["grupo"] == "TC"), None)
    if ultimo_tc and ultimo_tc.get("sku"):
        item = next((i for i in catalogo if i["sku"] == ultimo_tc["sku"]), None)
        if item and item.get("tc") and item["tc"]["ubicacion"]:
            ctx["ubicacion"] = item["tc"]["ubicacion"]


def _anotar_recalibracion_y_burden(propuesta: list[dict], equipos_actuales: dict) -> None:
    for fila in propuesta:
        cat_actual = _ETIQUETA_GRUPO_A_CATEGORIA_ACTUAL.get(fila["grupo"])
        if not cat_actual:
            continue
        actual = equipos_actuales.get(cat_actual)
        if not actual:
            continue
        if actual["certificado_conformidad"] is True and actual.get("calibracion_vencida_al_instalar") is True:
            fila["razon"] += f' 🔧 Posible alternativa más económica: el equipo actual ya tiene conformidad, y su único problema documentado es que la calibración ya estaba vencida en la fecha de instalación ({describir_condicion_actual(actual)}) — antes de comprar uno nuevo, evalúa si aplica recalibración en sitio del mismo equipo en vez de reemplazo.'
        if actual.get("burdenes_desiguales") is True:
            fila["razon"] += f' ⚠️ Los {actual["num_unidades_instaladas"]} elementos {fila["grupo"]} instalados en la última visita no tienen el mismo burden entre sí ({" VA vs. ".join(str(b) for b in actual["burdenes_encontrados"])} VA) — en un set trifásico deben ser iguales; revisa/cambia el set completo, no solo el que calibre peor.'
