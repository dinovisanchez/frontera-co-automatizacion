"""CAPEX — filas de Bloque de pruebas, Celda y Cable. Puerto de construirPropuestaEquipos
(Codigo.gs líneas 4596-4730). Cantidad de cable es una regla fija por tipo de medida
(semidirecta=8, indirecta=13 señal+20 desnudo) salvo que una hoja de ingeniería ya traiga
cantidad calculada para este CO puntual.
"""

import re

from core.services.deteccion_equipos import describir_condicion_actual
from core.services.propuesta_equipos_contexto import cantidad_medidor_bloque
from core.services.resolucion_tc_tp import ordenar_candidatos_celda


def resolver_propuesta_bloque(ctx: dict, propuesta: list[dict]) -> None:
    if ctx["diagnostico"]["tipo_medida_final"] == "directa":
        return
    actual_bloque = ctx["equipos_actuales"].get("bloque_pruebas")
    bloque = ctx["bloque_nt"] or next((i for i in ctx["catalogo"] if i["categoria"] == "Bloque de prueba"), None)
    if ctx["bloque_nt"]:
        razon = f'Según "Data cambio NT": "{ctx["bloque_texto"]}".'
    elif ctx["bloque_texto"]:
        razon = f'"Data cambio NT" indica tipo "{ctx["bloque_texto"]}" — el catálogo (ref_capex) solo tiene un ítem genérico de Bloque de pruebas, no esa variante específica; verifica si aplica o hay que agregarla al catálogo.'
    else:
        razon = "Obligatorio en semidirecta/indirecta para operar cada señal de forma independiente (aclaración 3, CREG 038/2014)."
    cantidad = cantidad_medidor_bloque(ctx)
    if cantidad == 2:
        razon += " (medida principal + respaldo, capacidad > 1000 kVA)."
    if actual_bloque:
        razon += f" Actual en Metabase: {describir_condicion_actual(actual_bloque)}."
    propuesta.append({
        "grupo": "Bloque de pruebas", "cantidad": cantidad, "tipo": "Bloque de prueba", "razon": razon,
        "sku": bloque["sku"] if bloque else None, "costo_estimado": bloque["costo"] if bloque else None,
        "alternativas": [], "requiere_confirmacion": not ctx["bloque_nt"],
    })


def resolver_propuesta_celda(ctx: dict, propuesta: list[dict]) -> None:
    actual_celda = ctx["equipos_actuales"].get("celda")
    if ctx["celda_nt"]:
        propuesta.append({
            "grupo": "Celda", "cantidad": 1, "tipo": "Celda",
            "razon": f'Según "{ctx["celda_fuente"]}" (ya calculado para este CO): "{ctx["celda_texto"]}".' + (f" Actual en Metabase: {describir_condicion_actual(actual_celda)}." if actual_celda else ""),
            "sku": ctx["celda_nt"]["sku"], "costo_estimado": ctx["celda_nt"]["costo"], "alternativas": [], "requiere_confirmacion": False,
        })
        return

    tipo_medida = ctx["diagnostico"]["tipo_medida_final"]
    candidatos_crudos = [i for i in ctx["catalogo"] if "Celda" in i["categoria"] or re.search(r"caja|policarbonato", i["categoria"], re.I) or re.search(r"policarbonato", i["sku"], re.I)]
    candidatos = ordenar_candidatos_celda(candidatos_crudos, tipo_medida, ctx["celda_texto"])
    if ctx["celda_texto"]:
        razon = f'"{ctx["celda_fuente"]}" indica: "{ctx["celda_texto"]}" — no encontré un ítem con ese nombre exacto en el catálogo, se sugiere el más parecido a ese texto (si nada se parece, se usa el tipo de medida {tipo_medida} como respaldo).'
    elif tipo_medida == "directa":
        razon = "Sugerido según el tipo de medida (directa: gabinete/caja de policarbonato, no celda de MT ni TC) — confirma la variante exacta o elige otra de la lista."
    else:
        extra_tp = "+TP" if tipo_medida == "indirecta" else ""
        razon = f"Sugerido según el tipo de medida ({tipo_medida}: necesita medidor+TC{extra_tp}) — confirma la variante exacta o elige otra de la lista."
    if actual_celda:
        razon += f" Actual en Metabase: {describir_condicion_actual(actual_celda)}."
    propuesta.append({
        "grupo": "Celda", "cantidad": 1, "tipo": "Celda", "razon": razon,
        "sku": candidatos[0]["sku"] if candidatos else None, "costo_estimado": candidatos[0]["costo"] if candidatos else None,
        "alternativas": candidatos[1:], "requiere_confirmacion": True,
    })


def resolver_propuesta_cable(ctx: dict, propuesta: list[dict], alertas: list[str]) -> None:
    tipo_medida = ctx["diagnostico"]["tipo_medida_final"]
    if tipo_medida == "directa":
        return
    actual_cable = ctx["equipos_actuales"].get("cable")
    catalogo = ctx["catalogo"]
    cable_senal = next((i for i in catalogo if i["sku"] == "Cable señal"), None)
    cable_desnudo = next((i for i in catalogo if i["sku"] == "Cable de cobre desnudo"), None)
    norm_indirectas, nt_cambio = ctx["norm_indirectas"], ctx["nt_cambio"]
    cantidad_hoja = None
    fuente_cable = "regla fija"
    if norm_indirectas and isinstance(norm_indirectas.get("cable_cantidad"), (int, float)):
        cantidad_hoja, fuente_cable = norm_indirectas["cable_cantidad"], "Normalizaciones_Indirectas"
    elif nt_cambio and nt_cambio.get("metros_cable_control") is not None:
        cantidad_hoja, fuente_cable = nt_cambio["metros_cable_control"], "Data cambio NT"

    if ctx["_estado_cable"]["con_cable"]:
        alertas.append('ℹ️ El TC propuesto ya incluye el cable embebido ("con cable") — no se propone Cable señal aparte para no duplicarlo.')

    if tipo_medida == "semidirecta":
        metros = cantidad_hoja if cantidad_hoja is not None else 8
        if not ctx["_estado_cable"]["con_cable"]:
            razon = f"Semidirecta: {metros} metros de cable señal ({fuente_cable})."
            if actual_cable:
                razon += f" Actual en Metabase: {describir_condicion_actual(actual_cable)}."
            propuesta.append({"grupo": "Cable señal", "cantidad": metros, "tipo": "Cable", "razon": razon, "sku": cable_senal["sku"] if cable_senal else None, "costo_estimado": cable_senal["costo"] if cable_senal else None, "alternativas": [], "requiere_confirmacion": not cable_senal})
        return

    if tipo_medida == "indirecta":
        metros = cantidad_hoja if cantidad_hoja is not None else 13
        if not ctx["_estado_cable"]["con_cable"]:
            razon = f"Indirecta: {metros} unidades de cable señal ({fuente_cable})."
            if actual_cable:
                razon += f" Actual en Metabase: {describir_condicion_actual(actual_cable)}."
            propuesta.append({"grupo": "Cable señal", "cantidad": metros, "tipo": "Cable", "razon": razon, "sku": cable_senal["sku"] if cable_senal else None, "costo_estimado": cable_senal["costo"] if cable_senal else None, "alternativas": [], "requiere_confirmacion": not cable_senal})
        propuesta.append({"grupo": "Cable desnudo", "cantidad": 20, "tipo": "Cable", "razon": "Indirecta: 20 unidades de cable de cobre desnudo (regla fija).", "sku": cable_desnudo["sku"] if cable_desnudo else None, "costo_estimado": cable_desnudo["costo"] if cable_desnudo else None, "alternativas": [], "requiere_confirmacion": not cable_desnudo})
        return

    candidatos_cable = [i for i in catalogo if i["categoria"] == "Cables"]
    razon = "El tipo/cantidad de cable depende del tipo de medida (no determinado con certeza) — elige tú entre los candidatos."
    if actual_cable:
        razon += f" Actual en Metabase: {describir_condicion_actual(actual_cable)}."
    propuesta.append({"grupo": "Cable", "cantidad": 1, "tipo": "Cable", "razon": razon, "sku": None, "costo_estimado": None, "alternativas": candidatos_cable, "requiere_confirmacion": True})
