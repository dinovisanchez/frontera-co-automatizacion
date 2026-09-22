"""CAPEX — resuelve la fila de TC de la propuesta de equipos. Puerto de la rama
`if (faltan.tc && tipoMedida !== 'directa')` de construirPropuestaEquipos (Codigo.gs líneas
4257-4552) — la parte más compleja e iterada del motor original, con más historial de bugs
reales corregidos que cualquier otra sección.

Orden de prioridad: EPM+compartido (mantener tal cual) > hojas de ingeniería
(Normalizaciones_Indirectas/Data cambio NT) > lo que declare el acta (con cruce contra la
capacidad instalada) > cálculo desde cero (ver propuesta_tc_calculo.py).
"""

from core.services.catalogo_capex import normalizar_decimales, parsear_tc
from core.services.deteccion_equipos import describir_condicion_actual
from core.services.hojas_ingenieria import extraer_ratio_de_texto
from core.services.propuesta_tc_calculo import resolver_tc_calculo
from core.services.resolucion_tc_tp import buscar_candidatos_tc, es_or_epm, resolver_tc_desde_hojas
from core.services.tablas_creg import calcular_relacion_tc_esperada_por_capacidad, etiqueta_nivel_para_tc


def resolver_propuesta_tc(ctx: dict, propuesta: list[dict], alertas: list[str]) -> None:
    """`ctx` trae todo lo que ya calculó el orquestador: spec, diagnostico, catalogo,
    equiposActuales, ntCambio, normIndirectas, relacionCertificadaTC, or, ubicacion,
    kvClaseTC, nivelTieneTablaOficial, esCompartidoBT, elementos, preferirConCable, y el
    callback `marcar_si_con_cable` (para que Cable señal no se duplique si el TC ya lo trae).
    """
    actual_tc = ctx["equipos_actuales"].get("tc")

    if ctx["es_compartido_bt"] and es_or_epm(ctx["or"]) and actual_tc:
        alertas.append(f'⚠ OR EPM + transformador compartido: EPM exige mantener el mismo TC ya instalado, no se recalcula ni se reemplaza — {describir_condicion_actual(actual_tc)}.')
        return

    resuelto = resolver_tc_desde_hojas(ctx["norm_indirectas"], ctx["nt_cambio"], ctx["catalogo"], ctx["ubicacion"], ctx["kv_clase_tc"], alertas)
    if resuelto:
        ctx["marcar_si_con_cable"](resuelto["item"])
        spec_relacion_tc = ctx["spec"].get("relacion_tc")
        if spec_relacion_tc and resuelto["item"].get("tc") and resuelto["item"]["tc"]["ratio"]:
            ratio_acta_cmp = extraer_ratio_de_texto(normalizar_decimales(spec_relacion_tc)) or normalizar_decimales(spec_relacion_tc)
            if ratio_acta_cmp != resuelto["item"]["tc"]["ratio"]:
                alertas.append(f'⚠️ El acta declara TC "{spec_relacion_tc}" pero "{resuelto["fuente"]}" dice "{resuelto["item"]["tc"]["ratio"]}" — se usó la de la hoja (más confiable, calculada por ingeniería), pero confirma cuál es la correcta antes de guardar; la diferencia puede ser grande.')
        texto_original = resuelto.get("texto_original")
        propuesta.append({
            "grupo": "TC", "cantidad": resuelto.get("cantidad") or ctx["elementos"], "tipo": "Transformador de corriente",
            "razon": f'Según "{resuelto["fuente"]}" (ya calculado para este CO)' + (f': "{texto_original}"' if texto_original else "") + ".",
            "sku": resuelto["item"]["sku"], "costo_estimado": resuelto["item"]["costo"], "alternativas": [], "requiere_confirmacion": False,
        })
        return

    if ctx["spec"].get("relacion_tc"):
        _resolver_tc_declarado_por_acta(ctx, propuesta, alertas, actual_tc)
        return

    resolver_tc_calculo(ctx, propuesta, alertas, actual_tc)


def _resolver_tc_declarado_por_acta(ctx: dict, propuesta: list[dict], alertas: list[str], actual_tc: dict | None) -> None:
    spec, diagnostico, catalogo = ctx["spec"], ctx["diagnostico"], ctx["catalogo"]
    ubicacion, kv_clase_tc, elementos = ctx["ubicacion"], ctx["kv_clase_tc"], ctx["elementos"]
    ratio_acta = extraer_ratio_de_texto(normalizar_decimales(spec["relacion_tc"])) or normalizar_decimales(spec["relacion_tc"])

    ya_coincide_acta_tc = False
    # No aplica en reclasificado (Art.19 BT->MT): que el TC ya instalado coincida con lo que
    # decía el acta de la BAJA tensión anterior no dice nada sobre si sirve para MT.
    if not diagnostico["reclasificado"] and actual_tc and actual_tc.get("sku") and actual_tc["certificado_conformidad"] is not False:
        parsed_actual = parsear_tc(actual_tc["sku"])
        if parsed_actual["ratio"] == ratio_acta and (not ubicacion or not parsed_actual["ubicacion"] or parsed_actual["ubicacion"] == ubicacion):
            ya_coincide_acta_tc = True

    kva = diagnostico["kva"]
    calc_cmp_acta = calcular_relacion_tc_esperada_por_capacidad(diagnostico["tipo_medida_final"], diagnostico["nivel_tension"], kva, ctx["nivel_tiene_tabla_oficial"]) if (kva is not None and not ctx["es_compartido_bt"]) else {"relacion": None, "por_formula": False}
    hay_desacuerdo_capacidad = bool(calc_cmp_acta["relacion"] and calc_cmp_acta["relacion"] != ratio_acta)
    usar_calculado = hay_desacuerdo_capacidad and (not calc_cmp_acta["por_formula"] or diagnostico["reclasificado"])

    candidatos_acta_tc = buscar_candidatos_tc(catalogo, ratio_acta, ubicacion, kv_clase_tc, 5, spec.get("montaje_tc"), ctx["preferir_con_cable"])
    candidatos_por_capacidad = buscar_candidatos_tc(catalogo, calc_cmp_acta["relacion"], ubicacion, kv_clase_tc, 5, spec.get("montaje_tc"), ctx["preferir_con_cable"]) if hay_desacuerdo_capacidad else []
    usar_calculado = usar_calculado and bool(candidatos_por_capacidad)
    candidatos_principales = candidatos_por_capacidad if usar_calculado else candidatos_acta_tc
    candidatos_secundarios = candidatos_acta_tc if usar_calculado else candidatos_por_capacidad

    if candidatos_principales:
        ctx["marcar_si_con_cable"](candidatos_principales[0])
    explicacion_capacidad = ""
    if calc_cmp_acta["relacion"]:
        etiqueta = etiqueta_nivel_para_tc(diagnostico["tipo_medida_final"], diagnostico["nivel_tension"])
        fuente_calc = " (fórmula genérica Ib=kVA/(kV×√3), sin tabla oficial para este nivel)" if calc_cmp_acta["por_formula"] else " (Tabla CREG)"
        explicacion_capacidad = f' — según la capacidad instalada ({kva} kVA, {etiqueta}) correspondería {calc_cmp_acta["relacion"]}{fuente_calc}.'

    if usar_calculado:
        if diagnostico["reclasificado"]:
            razon = f'⚠️ El acta declara TC "{spec["relacion_tc"]}", pero ese valor es del esquema anterior en BAJA tensión (antes de la reclasificación a Indirecta/MT por Art.19) — no aplica al nuevo punto de medición en MT.{explicacion_capacidad} Se usa el valor calculado para MT; el del acta queda solo como referencia de lo que había antes.'
        else:
            razon = f'⚠️ El acta declara TC "{spec["relacion_tc"]}"{explicacion_capacidad} Se sugiere el valor de la Tabla CREG (más confiable que un número transcrito del acta); el del acta queda como alternativa. Confirma si la capacidad es realmente de este cliente (compartido) o si el TC instalado es de un totalizador/transformador más grande.'
    else:
        razon = f'El acta declara directamente la relación del TC: "{spec["relacion_tc"]}".'
        if spec.get("montaje_tc"):
            if ctx["preferir_con_cable"]:
                razon += f' El acta declara montaje "{spec["montaje_tc"]}" (lo ya instalado), pero EMCALI exige TC tipo cable — se prioriza esa variante sobre el montaje declarado.'
            else:
                razon += f' Montaje: {spec["montaje_tc"]}.'
        if hay_desacuerdo_capacidad:
            if calc_cmp_acta["por_formula"]:
                razon += explicacion_capacidad + " Al ser fórmula genérica (no tabla oficial), NO se usa para pisar el valor del acta — queda como alternativa a revisar."
            else:
                razon += explicacion_capacidad + " No encontré ese valor calculado en el catálogo, se deja el del acta — confírmalo."
    if actual_tc:
        razon += f" Actual en Metabase: {describir_condicion_actual(actual_tc)}."
    if ya_coincide_acta_tc:
        razon += " ⚠ El TC ya instalado tiene esta misma relación y conformidad — confirma si el problema real es otro (soportes de instalación, bornera, conductor, etc.) antes de comprar uno nuevo."

    propuesta.append({
        "grupo": "TC", "cantidad": elementos, "tipo": "Transformador de corriente", "razon": razon,
        "sku": candidatos_principales[0]["sku"] if candidatos_principales else None,
        "costo_estimado": candidatos_principales[0]["costo"] if candidatos_principales else None,
        "alternativas": candidatos_principales[1:] + candidatos_secundarios,
        "requiere_confirmacion": not candidatos_principales or ya_coincide_acta_tc or hay_desacuerdo_capacidad,
    })
    if not candidatos_principales:
        extra = f' ("{calc_cmp_acta["relacion"]}")' if calc_cmp_acta["relacion"] else ""
        alertas.append(f'No encontré en el catálogo ni el TC del acta ("{spec["relacion_tc"]}") ni el calculado por capacidad{extra} — revisa candidatos manualmente.')
