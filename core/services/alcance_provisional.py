"""Orquestador final del CAPEX — puerto de analizarAlcanceProvisional (Codigo.gs líneas
2564-2746): ata acta + hoja maestra + Data cambio NT + Normalizaciones_Indirectas +
certificado de calibración + clasificación + catálogo en una sola respuesta.

A diferencia del original, NO lee actas por dentro (eso ya lo hizo el job asíncrono de
actas_start.py/actas_step.py, una acta por invocación — ver README). `acta_resultado` es el
resultado YA COMBINADO de ese job (o None si se marcó "sin actas" o no hay ninguna).
"""

import re

from core.services.catalogo_capex import candidatos_por_categoria_alcance, obtener_catalogo_ref_capex
from core.services.certificado_extractor import extraer_ratio_de_certificado_calibracion
from core.services.clasificador_medida import NtCambio, clasificar_tipo_medida
from core.services.deteccion_equipos import detectar_secciones_deficientes, equipos_actuales_metabase, listar_equipos_por_estado
from core.services.hoja_origen_equipos import leer_equipos_existentes, leer_origen_alcance
from core.services.hojas_ingenieria import buscar_en_hoja_cambio_nt, buscar_en_hoja_maestra, buscar_en_hoja_normalizaciones_indirectas
from core.services.propuesta_equipos import construir_propuesta_equipos
from core.services.resolucion_tc_tp import inferir_ubicacion_por_or
from core.utils import normalizar_codigo


def _ubicacion_desde_nt_cambio(nt_cambio_raw: dict | None) -> str | None:
    """"Data cambio NT" trae el TC/TP que ingeniería YA calculó para el esquema MT nuevo de un
    CO reclasificado (Art.19) — su SKU declara "Interior"/"Exterior" explícitamente (ej. "TC
    5-10/5 Exterior..."). Es más confiable que un acta para este dato puntual, porque una acta
    puede describir el esquema BT viejo o ser de una visita sin relación con la reclasificación
    (confirmado por Dinovi, 2026-09-23, CO0800000230: el acta usada era una visita de falla de
    módem — nada que ver con la instalación MT — y traía "interior" mientras "Data cambio NT"
    ya tenía el TC/TP calculados como "Exterior"). "Normalizaciones_Indirectas" no sirve para
    esto: su columna "TC/TP relación" es solo el ratio ("10/5"), sin texto de ubicación.
    """
    if not nt_cambio_raw:
        return None
    for campo in ("sku_tcs", "sku_tps"):
        texto = nt_cambio_raw.get(campo) or ""
        if re.search(r"exterior", texto, re.I):
            return "exterior"
        if re.search(r"interior", texto, re.I):
            return "interior"
    return None


def _mezclar_hoja_maestra(spec: dict, maestro: dict | None, or_real: str | None) -> bool:
    """Rellena huecos del spec con la hoja maestra, pero NUNCA sobreescribe lo que una acta ya
    dijo explícitamente — una acta reciente puede reflejar un cambio que la hoja maestra
    todavía no tiene. tipo_medida_actual usa RATCHET (nunca degrada, ver clasificador_medida).

    Devuelve True si `trafo_uso` se rellenó DESDE la hoja maestra (no vino de ninguna acta) —
    el llamador lo usa para avisar cuando ese dato termina disparando una reclasificación a
    Indirecta sin que ninguna acta lo haya confirmado (ver CO0800000348, Dinovi 2026-09-23).
    """
    if not maestro:
        return False
    _rank = {"indirecta": 3, "semidirecta": 2, "directa": 1}.get

    if maestro.get("medida") and (_rank(maestro["medida"]) or 0) > (_rank(spec.get("tipo_medida_actual")) or 0):
        spec["tipo_medida_actual"] = maestro["medida"]
    if spec.get("capacidad_instalada_kva") is None and maestro.get("capacidad_transformador") is not None:
        spec["capacidad_instalada_kva"] = maestro["capacidad_transformador"]
    trafo_uso_desde_maestro = False
    if spec.get("trafo_uso") is None and maestro.get("propiedad_activos"):
        spec["trafo_uso"] = maestro["propiedad_activos"]
        trafo_uso_desde_maestro = True
    if spec.get("elementos_medida") is None and maestro.get("elementos") is not None:
        spec["elementos_medida"] = maestro["elementos"]
    if spec.get("fases_medidor") is None and maestro.get("fases") is not None:
        spec["fases_medidor"] = maestro["fases"]
    if spec.get("factor_fx") is None and isinstance(maestro.get("factor_fx"), (int, float)):
        spec["factor_fx"] = maestro["factor_fx"]
    return trafo_uso_desde_maestro


def analizar_alcance_provisional(sheets, llm, co_raw: str, dictamen: dict, acta_resultado: dict | None, filas_metabase_co: list[dict]) -> dict:
    co = normalizar_codigo(co_raw)
    origen = leer_origen_alcance(sheets, co)
    equipos = leer_equipos_existentes(sheets, co)
    equipos_actuales = equipos_actuales_metabase(filas_metabase_co)
    equipos_por_estado = listar_equipos_por_estado(filas_metabase_co)

    spec = dict(acta_resultado["spec"]) if acta_resultado else {}
    maestro = buscar_en_hoja_maestra(sheets, co)
    trafo_uso_desde_maestro = _mezclar_hoja_maestra(spec, maestro, origen["or"])

    nt_cambio_raw = buscar_en_hoja_cambio_nt(sheets, co)
    norm_indirectas = buscar_en_hoja_normalizaciones_indirectas(sheets, co)
    nt_cambio = NtCambio(capacidad_kva=nt_cambio_raw.get("capacidad_kva"), tipo_medida=(nt_cambio_raw.get("tipo_medida") or "").lower() or None) if nt_cambio_raw else None

    ubicacion_asumida_por_or = False
    ubicacion_previa_acta = spec.get("ubicacion_medida")
    ubicacion_nt = _ubicacion_desde_nt_cambio(nt_cambio_raw)
    ubicacion_sobrescrita_por_nt = bool(ubicacion_nt and ubicacion_previa_acta and ubicacion_previa_acta != ubicacion_nt)
    if ubicacion_nt:
        spec["ubicacion_medida"] = ubicacion_nt
    elif not spec.get("ubicacion_medida"):
        texto_obs = " ".join(acta_resultado["observaciones"]) if acta_resultado else ""
        ubicacion_inferida = inferir_ubicacion_por_or(origen["or"], texto_obs)
        if ubicacion_inferida:
            spec["ubicacion_medida"] = ubicacion_inferida
            ubicacion_asumida_por_or = True

    relacion_certificada_tc = relacion_certificada_tp = None
    sin_capacidad_ni_hojas = spec.get("capacidad_instalada_kva") is None and not (nt_cambio_raw and nt_cambio_raw.get("capacidad_kva") is not None)
    if sin_capacidad_ni_hojas:
        tc_actual, tp_actual = equipos_actuales.get("tc"), equipos_actuales.get("tp")
        if tc_actual and tc_actual.get("certificado_calibracion_url"):
            relacion_certificada_tc = extraer_ratio_de_certificado_calibracion(tc_actual["certificado_calibracion_url"], llm)
        if tp_actual and tp_actual.get("certificado_calibracion_url"):
            relacion_certificada_tp = extraer_ratio_de_certificado_calibracion(tp_actual["certificado_calibracion_url"], llm)

    trafo_compartido_confirmado = bool(dictamen.get("trafoCompartidoConfirmado"))
    diagnostico = clasificar_tipo_medida(spec, nt_cambio, bool(norm_indirectas), origen["or"], trafo_compartido_confirmado)
    if trafo_compartido_confirmado:
        spec["trafo_uso"] = "compartido"
    diagnostico_dict = {
        "tipo_medida_actual": diagnostico.tipo_medida_actual, "tipo_medida_final": diagnostico.tipo_medida_final,
        "uso_transformador": diagnostico.uso_transformador, "nivel_tension": diagnostico.nivel_tension,
        "kva": diagnostico.kva, "elementos": diagnostico.elementos, "fases_medidor": diagnostico.fases_medidor,
        "motivo": diagnostico.motivo, "reclasificado": diagnostico.reclasificado,
    }
    catalogo = obtener_catalogo_ref_capex(sheets)
    # Candidatos por categoría para el desplegable de "+ Agregar fila manual" del frontend
    # (Dinovi, 2026-09-23) — antes una fila manual (ej. Cable) no traía ningún SKU sugerido y
    # había que escribirlo a mano; ahora se le pasa la MISMA lista de candidatos que ya arma
    # candidatos_por_categoria_alcance para "Recuperable".
    catalogo_manual = {cat: candidatos_por_categoria_alcance(catalogo, cat) for cat in ("medidor", "tc", "tp", "bloque_pruebas", "cable", "celda")}

    hay_burden_desigual = bool((equipos_actuales.get("tc") or {}).get("burdenes_desiguales") or (equipos_actuales.get("tp") or {}).get("burdenes_desiguales"))
    if dictamen.get("clasificacion") == "normalizacion" or diagnostico.reclasificado or hay_burden_desigual:
        texto_obs_completo = " ".join(acta_resultado["observaciones"]) if acta_resultado else ""
        hay_acta_instalacion = bool(acta_resultado and acta_resultado.get("tiene_acta_instalacion"))
        secciones = detectar_secciones_deficientes(equipos_actuales, texto_obs_completo, hay_acta_instalacion)
        for cat, forzado in (dictamen.get("seccionesForzadas") or {}).items():
            if forzado:
                secciones[cat] = True
        dictamen = {**dictamen, "secciones": secciones}

    resultado = construir_propuesta_equipos(diagnostico_dict, spec, catalogo, equipos, dictamen, equipos_actuales, nt_cambio_raw, norm_indirectas, relacion_certificada_tc, relacion_certificada_tp, origen["or"])
    alertas = list(resultado["alertas"])

    if acta_resultado is None:
        alertas.insert(0, '⚠ Se omitió la lectura de actas para este CO (marcaste "no leer actas") — el alcance se armó solo con hoja maestra, "Data cambio NT"/"Normalizaciones_Indirectas" y lo instalado en Metabase. Puede faltar precisión que solo el acta trae (TC/TP declarados, ubicación exacta, observaciones de la visita); revisa con más cuidado antes de guardar.')
    if (dictamen.get("clasificacion") == "normalizacion" or diagnostico.reclasificado) and not (acta_resultado and acta_resultado.get("tiene_acta_instalacion")):
        alertas.insert(0, '⚠ No encontré acta de INSTALACIÓN (INST) para este CO — sin ella, Lovable no puede confirmar cumplimiento de medidor/TC/TP (un certificado vigente en Metabase puede ser de una recalibración posterior, no prueba que la instalación original cumplió el código de medida), así que este análisis marca bloque de pruebas/cable/celda para revisión por defecto (medidor/TC/TP se evalúan contra lo que sí haya en Metabase). Si sabes que alguna sí está bien, exclúyela en su fila.')
    if ubicacion_asumida_por_or:
        alertas.insert(0, f'⚠ Ninguna acta indicó interior/exterior — se asumió "{spec["ubicacion_medida"]}" por ser OR {origen["or"]}. Confirma que sea correcto (excepción: centros comerciales suelen ser interior).')
    if ubicacion_sobrescrita_por_nt:
        alertas.insert(0, f'⚠ El acta indicaba ubicación "{ubicacion_previa_acta}", pero "Data cambio NT" ya trae el TC/TP calculado como "{spec["ubicacion_medida"]}" para el esquema MT nuevo de este CO reclasificado — se usó el de "Data cambio NT" (más confiable para el punto de medición nuevo que un acta que puede describir el esquema viejo o ser de otra visita). Confirma que sea correcto.')
    if trafo_uso_desde_maestro and diagnostico.reclasificado and diagnostico.uso_transformador == "exclusivo":
        # CO0800000348 (Dinovi, 2026-09-23): reclasificó a Indirecta con trafo_uso="exclusivo"
        # tomado de la hoja maestra (ninguna acta lo confirmó — en este caso porque la acta
        # INFR pesaba 42MB y nunca se pudo leer), pero la acta/Lovable SÍ decían "compartido" —
        # Art.19 no aplica a un transformador compartido. No hay forma de saber cuál es
        # correcto sin leer la acta real, así que se avisa en vez de decidir en silencio.
        alertas.insert(0, '🔴 ATENCIÓN: esta reclasificación a Indirecta (Art.19) asume transformador de uso EXCLUSIVO tomado de la hoja MAESTRA — ninguna acta lo confirmó. Si el acta o Lovable dicen que el transformador es COMPARTIDO, esta reclasificación NO aplica (Art.19 es solo para exclusivo) y el alcance real es Normalización del esquema actual, no cambio de Nivel de Tensión. Verifica el acta antes de guardar.')
    if trafo_compartido_confirmado:
        alertas.insert(0, '✓ Marcaste el transformador como COMPARTIDO — no se aplicó la reclasificación a Indirecta por Art.19 aunque "Data cambio NT"/"Normalizaciones_Indirectas"/hoja maestra sugirieran lo contrario. El alcance se armó con el tipo de medida real del acta/Lovable.')
    elif (nt_cambio_raw or norm_indirectas) and diagnostico.uso_transformador == "compartido":
        # CO0500001172 (Dinovi, 2026-09-25): semidirecta con trafo_uso="compartido" YA
        # conocido (acta u hoja maestra) se estaba reclasificando a Indirecta igual solo por
        # estar en "Data cambio NT"/"Normalizaciones_Indirectas" — ahora clasificador_medida
        # detecta el compartido automáticamente sin necesitar el checkbox manual; este aviso es
        # el equivalente automático de la confirmación manual de arriba, para que quede visible
        # por qué NO se aplicó Art.19 pese a que el CO está en esa hoja.
        fuente = "Data cambio NT" if nt_cambio_raw else "Normalizaciones_Indirectas"
        alertas.insert(0, f'✓ El transformador ya consta como COMPARTIDO (acta/hoja maestra) — no se aplicó la reclasificación a Indirecta por Art.19 aunque el CO esté en "{fuente}". Revisa por qué esa hoja trae este CO si de verdad es compartido (puede ser un error de esa hoja).')
    if acta_resultado and acta_resultado.get("capacidades_encontradas"):
        vals = " vs. ".join(f'{c["valor"]} kVA ({c["etiqueta"]})' for c in acta_resultado["capacidades_encontradas"])
        alertas.insert(0, f"⚠ Las actas de este CO no coinciden en la capacidad instalada del transformador: {vals} — confirma cuál es la correcta antes de usar el TC/TP propuesto.")
    if acta_resultado and acta_resultado.get("relaciones_tc_encontradas"):
        vals = " vs. ".join(f'{c["valor"]} ({c["etiqueta"]})' for c in acta_resultado["relaciones_tc_encontradas"])
        alertas.insert(0, f"⚠ Las actas de este CO no coinciden en la relación del TC: {vals} — confirma cuál es la correcta antes de usar el TC propuesto.")

    return {
        "co": co, "cliente": origen["cliente"], "or": origen["or"], "maniobra": origen["maniobra"],
        "origen_encontrado": len(origen["filas"]) > 0, "equipos_existentes": equipos, "equipos_actuales": equipos_actuales,
        "equipos_por_estado": equipos_por_estado,
        "nt_cambio": nt_cambio_raw, "norm_indirectas": norm_indirectas, "maestro": maestro,
        "acta": acta_resultado, "spec": spec, "diagnostico": diagnostico_dict,
        "secciones": dictamen.get("secciones"), "propuesta": resultado["propuesta"], "alertas": alertas,
        "catalogo_manual": catalogo_manual,
    }
