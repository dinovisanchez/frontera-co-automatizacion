"""CAPEX — filas de TP y Medidor de la propuesta de equipos. Puerto de las ramas
`if (tipoMedida === 'indirecta' && faltan.tp)` y `if (faltan.medidor)` de
construirPropuestaEquipos (Codigo.gs líneas 4570-4639). TP solo aplica en Indirecta (MT) —
Semidirecta no tiene TP, solo TC.
"""

from core.services.deteccion_equipos import describir_condicion_actual
from core.services.propuesta_equipos_contexto import cantidad_medidor_bloque
from core.services.resolucion_tc_tp import buscar_candidatos_medidor, buscar_candidatos_tp, resolver_tp_desde_hojas


def resolver_propuesta_tp(ctx: dict, propuesta: list[dict], alertas: list[str]) -> None:
    if ctx["diagnostico"]["tipo_medida_final"] != "indirecta":
        return
    actual_tp = ctx["equipos_actuales"].get("tp")
    nivel = ctx["diagnostico"]["nivel_tension"]
    primario_tp = 34500 if nivel == "34.5kV" else (11400 if nivel == "11.4kV" else 13200)
    resuelto = resolver_tp_desde_hojas(ctx["norm_indirectas"], ctx["nt_cambio"], ctx["catalogo"], ctx["ubicacion"], primario_tp)

    if resuelto:
        texto_original = resuelto.get("texto_original")
        propuesta.append({
            # Mismo criterio que TC: el número de fases del acta manda sobre la "Cantidad" de
            # la hoja (Dinovi, 2026-09-22) — la hoja es solo respaldo si el acta no dice nada.
            "grupo": "TP", "cantidad": ctx["elementos"] or resuelto.get("cantidad"), "tipo": "Transformador de potencial",
            "razon": f'Según "{resuelto["fuente"]}" (ya calculado para este CO)' + (f': "{texto_original}"' if texto_original else "") + ".",
            "sku": resuelto["item"]["sku"], "costo_estimado": resuelto["item"]["costo"], "alternativas": [], "requiere_confirmacion": False,
        })
        return

    candidatos = buscar_candidatos_tp(ctx["catalogo"], primario_tp, ctx["ubicacion"])
    razon = f'Nivel MT {nivel or f"{primario_tp}V asumido"}, burden 5VA, relación fase-neutro estándar{", " + ctx["ubicacion"] if ctx["ubicacion"] else ""}'
    if actual_tp:
        razon += f" — actual en Metabase: {describir_condicion_actual(actual_tp)}"
    propuesta.append({
        "grupo": "TP", "cantidad": ctx["elementos"], "tipo": "Transformador de potencial", "razon": razon,
        "sku": candidatos[0]["sku"] if candidatos else None, "costo_estimado": candidatos[0]["costo"] if candidatos else None,
        "alternativas": candidatos[1:], "requiere_confirmacion": not candidatos,
    })
    if not candidatos:
        alertas.append(f"No encontré un TP exacto en el catálogo para {primario_tp}V — revisa candidatos manualmente.")


def resolver_propuesta_medidor(ctx: dict, propuesta: list[dict]) -> None:
    actual_medidor = ctx["equipos_actuales"].get("medidor")
    cantidad = cantidad_medidor_bloque(ctx)
    nota_duplicado = " (medida principal + respaldo, capacidad > 1000 kVA)" if cantidad == 2 else ""
    if ctx["medidor_nt"]:
        propuesta.append({
            "grupo": "Medidor", "cantidad": cantidad, "tipo": "Medidor",
            "razon": f'Según "{ctx["medidor_fuente"]}" (ya calculado por ingeniería para este CO): "{ctx["medidor_texto"]}".' + nota_duplicado + (f" Actual en Metabase: {describir_condicion_actual(actual_medidor)}." if actual_medidor else ""),
            "sku": ctx["medidor_nt"]["sku"], "costo_estimado": ctx["medidor_nt"]["costo"], "alternativas": [], "requiere_confirmacion": False,
        })
        return

    tipo_medida = ctx["diagnostico"]["tipo_medida_final"]
    fases_medidor = ctx["fases_medidor"]
    candidatos = buscar_candidatos_medidor([i for i in ctx["catalogo"] if i["categoria"] == "Medidor"], tipo_medida, fases_medidor)
    propuesta.append({
        "grupo": "Medidor", "cantidad": cantidad, "tipo": "Medidor",
        "razon": f"Sugerido según el tipo de medida ({tipo_medida}) y número de fases ({fases_medidor}) — confirma la variante exacta o elige otra de la lista." + nota_duplicado + (f" Actual en Metabase: {describir_condicion_actual(actual_medidor)}." if actual_medidor else ""),
        "sku": candidatos[0]["sku"] if candidatos else None, "costo_estimado": candidatos[0]["costo"] if candidatos else None,
        "alternativas": candidatos[1:], "requiere_confirmacion": True,
    })
