"""CAPEX — cálculo de TC desde cero (ni hojas de ingeniería ni acta lo declaran). Puerto de
la cola de la rama TC en construirPropuestaEquipos (Codigo.gs líneas 4371-4552): primero los
casos de transformador COMPARTIDO en BT (factor Fx > totalizador > mantener el actual), y si
no es compartido, tabla/fórmula CREG > Factor Fx > certificado de calibración > TC ya
instalado > rendirse.
"""

from core.services.deteccion_equipos import describir_condicion_actual
from core.services.catalogo_capex import candidatos_por_categoria_alcance, parsear_tc
from core.services.resolucion_tc_tp import buscar_candidatos_tc
from core.services.tablas_creg import calcular_ratio_tc_por_corriente, calcular_relacion_tc_esperada_por_capacidad, etiqueta_nivel_para_tc


def resolver_tc_calculo(ctx: dict, propuesta: list[dict], alertas: list[str], actual_tc: dict | None) -> None:
    spec = ctx["spec"]
    if ctx["es_compartido_bt"]:
        if spec.get("factor_fx"):
            _tc_por_factor_fx(ctx, propuesta, actual_tc, spec["factor_fx"], compartido=True)
        elif isinstance(spec.get("totalizador_amperios"), (int, float)):
            _tc_por_totalizador(ctx, propuesta, actual_tc)
        else:
            _tc_compartido_sin_base(ctx, propuesta, alertas, actual_tc)
        return
    _tc_no_compartido(ctx, propuesta, alertas, actual_tc)


def _tc_por_factor_fx(ctx: dict, propuesta: list[dict], actual_tc: dict | None, factor_fx: float, compartido: bool) -> None:
    ratio = f"{round(factor_fx * 5)}/5"
    candidatos = buscar_candidatos_tc(ctx["catalogo"], ratio, ctx["ubicacion"], ctx["kv_clase_tc"], 5, ctx["spec"].get("montaje_tc"), ctx["preferir_con_cable"])
    if candidatos:
        ctx["marcar_si_con_cable"](candidatos[0])
    prefijo = "Transformador compartido: calculado" if compartido else "No se pudo calcular por capacidad/nivel de tensión (faltan en el acta) — se usó"
    razon = f'{prefijo} desde el Factor de medida (Fx={factor_fx}) de la hoja maestra{"/BD telemedida" if not compartido else ""} — TC {ratio} (factor = primario/5).'
    if actual_tc:
        razon += f" Actual en Metabase: {describir_condicion_actual(actual_tc)}."
    propuesta.append({
        "grupo": "TC", "cantidad": ctx["elementos"], "tipo": "Transformador de corriente", "razon": razon,
        "sku": candidatos[0]["sku"] if candidatos else None, "costo_estimado": candidatos[0]["costo"] if candidatos else None,
        "alternativas": candidatos[1:], "requiere_confirmacion": True,
    })


def _tc_por_totalizador(ctx: dict, propuesta: list[dict], actual_tc: dict | None) -> None:
    amperios = ctx["spec"]["totalizador_amperios"]
    ratio = calcular_ratio_tc_por_corriente(amperios)
    candidatos = buscar_candidatos_tc(ctx["catalogo"], ratio, ctx["ubicacion"], ctx["kv_clase_tc"], 5, ctx["spec"].get("montaje_tc"), ctx["preferir_con_cable"])
    if candidatos:
        ctx["marcar_si_con_cable"](candidatos[0])
    razon = f"Transformador compartido: calculado desde el totalizador de este cliente ({amperios}A, según el acta) — TC {ratio}."
    if actual_tc:
        razon += f" Actual en Metabase: {describir_condicion_actual(actual_tc)}."
    propuesta.append({
        "grupo": "TC", "cantidad": ctx["elementos"], "tipo": "Transformador de corriente", "razon": razon,
        "sku": candidatos[0]["sku"] if candidatos else None, "costo_estimado": candidatos[0]["costo"] if candidatos else None,
        "alternativas": candidatos[1:], "requiere_confirmacion": True,
    })


def _tc_compartido_sin_base(ctx: dict, propuesta: list[dict], alertas: list[str], actual_tc: dict | None) -> None:
    kva = ctx["diagnostico"]["kva"]
    pista_conductor = f' El acta menciona el conductor de este cliente ({ctx["spec"]["conductor_calibre"]}) — puede usarse para estimar la carga por ampacidad, pero este motor no calcula esa tabla automáticamente.' if ctx["spec"].get("conductor_calibre") else ""
    if not actual_tc:
        alertas.append(f'⚠ Transformador compartido y no hay TC previo registrado en Metabase — no se puede calcular el tamaño por la capacidad total del transformador (compartida entre varios usuarios). Indica manualmente la relación según el Factor Fx, el totalizador o el conductor de este cliente.{pista_conductor}')
        return
    info_actual = parsear_tc(str(actual_tc.get("sku") or ""))
    candidatos = buscar_candidatos_tc(ctx["catalogo"], info_actual["ratio"], info_actual["ubicacion"] or ctx["ubicacion"], ctx["kv_clase_tc"], info_actual["burden"], ctx["spec"].get("montaje_tc"), ctx["preferir_con_cable"]) if info_actual["ratio"] else []
    if candidatos:
        ctx["marcar_si_con_cable"](candidatos[0])
    alertas.append(f'⚠ Transformador compartido: no se recalcula el TC por la capacidad total ({f"{kva} kVA" if kva is not None else "?"} es del transformador, no de este cliente). Sin Factor Fx ni totalizador de este cliente, se propone mantener la MISMA relación ya instalada — {describir_condicion_actual(actual_tc)}.{pista_conductor}')
    propuesta.append({
        "grupo": "TC", "cantidad": ctx["elementos"], "tipo": "Transformador de corriente",
        "razon": f'Transformador compartido, sin Factor Fx ni totalizador de este cliente para recalcular el tamaño — se propone mantener la misma relación ya instalada{f" ({info_actual['ratio']})" if info_actual["ratio"] else ""}. Actual en Metabase: {describir_condicion_actual(actual_tc)}.{pista_conductor}',
        "sku": candidatos[0]["sku"] if candidatos else None, "costo_estimado": candidatos[0]["costo"] if candidatos else None,
        "alternativas": candidatos[1:] if candidatos else candidatos_por_categoria_alcance(ctx["catalogo"], "tc"),
        "requiere_confirmacion": True,
    })


def _tc_no_compartido(ctx: dict, propuesta: list[dict], alertas: list[str], actual_tc: dict | None) -> None:
    spec, diagnostico = ctx["spec"], ctx["diagnostico"]
    tipo_medida, nivel, kva = diagnostico["tipo_medida_final"], diagnostico["nivel_tension"], diagnostico["kva"]
    calc = calcular_relacion_tc_esperada_por_capacidad(tipo_medida, nivel, kva, ctx["nivel_tiene_tabla_oficial"])
    relacion_tc, relacion_por_formula = calc["relacion"], calc["por_formula"]

    ya_coincide = False
    if actual_tc and actual_tc.get("sku") and relacion_tc:
        parsed_actual = parsear_tc(actual_tc["sku"])
        if parsed_actual["ratio"] == relacion_tc and (not ctx["ubicacion"] or not parsed_actual["ubicacion"] or parsed_actual["ubicacion"] == ctx["ubicacion"]):
            ya_coincide = True

    capacidad_marcada_incierta = ctx["dictamen"].get("capacidadIncierta") is True
    usar_factor_sobre_capacidad = capacidad_marcada_incierta and bool(spec.get("factor_fx"))

    if relacion_tc and not usar_factor_sobre_capacidad:
        candidatos = buscar_candidatos_tc(ctx["catalogo"], relacion_tc, ctx["ubicacion"], ctx["kv_clase_tc"], 5, spec.get("montaje_tc"), ctx["preferir_con_cable"])
        if candidatos:
            ctx["marcar_si_con_cable"](candidatos[0])
        etiqueta = etiqueta_nivel_para_tc(tipo_medida, nivel)
        base = (f"Relación calculada por fórmula (Ib=kVA/(kV×√3)) {relacion_tc} — {etiqueta} no tiene tabla oficial propia en este motor, se usó el redondeo a relación normalizada más cercana." if relacion_por_formula else f"Relación calculada {relacion_tc} (Tabla CREG)")
        razon = f'{base} ({kva if kva is not None else "?"} kVA, {etiqueta}, burden 5VA{", " + ctx["ubicacion"] if ctx["ubicacion"] else ""})'
        if actual_tc:
            razon += f" — actual en Metabase: {describir_condicion_actual(actual_tc)}"
        if ya_coincide:
            razon += " ⚠ El TC ya instalado coincide con esta relación — confirma si el problema real es otro (certificado, soportes de instalación, conductor, etc.) antes de comprar uno nuevo."
        propuesta.append({
            "grupo": "TC", "cantidad": ctx["elementos"], "tipo": "Transformador de corriente", "razon": razon,
            "sku": candidatos[0]["sku"] if candidatos else None, "costo_estimado": candidatos[0]["costo"] if candidatos else None,
            "alternativas": candidatos[1:], "requiere_confirmacion": (not candidatos) or relacion_por_formula or ya_coincide,
        })
        if not candidatos:
            alertas.append(f'No encontré un TC exacto en el catálogo para {relacion_tc}{" " + ctx["ubicacion"] if ctx["ubicacion"] else ""} — revisa candidatos manualmente.')
        if relacion_por_formula:
            alertas.append(f'⚠ {nivel or "este nivel MT"} no tiene tabla oficial cargada en este motor — el TC se calculó por fórmula genérica, confírmalo contra la norma real del operador de red antes de guardar.')
        return

    if spec.get("factor_fx"):
        _tc_factor_fx_general(ctx, propuesta, alertas, actual_tc, relacion_tc, usar_factor_sobre_capacidad, kva)
        return

    if ctx["relacion_certificada_tc"]:
        _tc_desde_certificado(ctx, propuesta, alertas, actual_tc)
        return

    if actual_tc and actual_tc.get("sku") and parsear_tc(actual_tc["sku"])["ratio"]:
        _tc_mantener_actual_ultimo_recurso(ctx, propuesta, alertas, actual_tc)
        return

    alertas.append("No pude calcular la relación de TC (falta capacidad instalada o nivel de tensión en el acta, el CO no está en Normalizaciones_Indirectas ni Data cambio NT, y no hay certificado de calibración legible del TC instalado). Complétalo manualmente." + (f" Ya hay un TC instalado: {describir_condicion_actual(actual_tc)}." if actual_tc else ""))


def _tc_factor_fx_general(ctx: dict, propuesta: list[dict], alertas: list[str], actual_tc: dict | None, relacion_tc: str | None, usar_factor_sobre_capacidad: bool, kva: float | None) -> None:
    factor_fx = ctx["spec"]["factor_fx"]
    ratio = f"{round(factor_fx * 5)}/5"
    candidatos = buscar_candidatos_tc(ctx["catalogo"], ratio, ctx["ubicacion"], ctx["kv_clase_tc"], 5, ctx["spec"].get("montaje_tc"), ctx["preferir_con_cable"])
    if candidatos:
        ctx["marcar_si_con_cable"](candidatos[0])
    candidatos_descartada = buscar_candidatos_tc(ctx["catalogo"], relacion_tc, ctx["ubicacion"], ctx["kv_clase_tc"], 5, ctx["spec"].get("montaje_tc"), ctx["preferir_con_cable"]) if usar_factor_sobre_capacidad else []
    prefijo = f'⚠️ Lovable marcó la capacidad automática del transformador como NO correcta — no se usó para calcular el TC. Se usó en su lugar el Factor de medida (Fx={factor_fx}) de la hoja maestra/BD telemedida, que es la relación real ya usada para facturar' if usar_factor_sobre_capacidad else f'No se pudo calcular por capacidad/nivel de tensión (faltan en el acta) — se usó el Factor de medida (Fx={factor_fx}) de la hoja maestra/BD telemedida'
    razon = f"{prefijo}: TC {ratio} (factor = primario/5)."
    if usar_factor_sobre_capacidad:
        razon += f" Con la capacidad marcada ({kva} kVA) habría dado {relacion_tc} — se deja como alternativa, confirma cuál es la correcta."
    if actual_tc:
        razon += f" Actual en Metabase: {describir_condicion_actual(actual_tc)}."
    propuesta.append({
        "grupo": "TC", "cantidad": ctx["elementos"], "tipo": "Transformador de corriente", "razon": razon,
        "sku": candidatos[0]["sku"] if candidatos else None, "costo_estimado": candidatos[0]["costo"] if candidatos else None,
        "alternativas": candidatos[1:] + candidatos_descartada, "requiere_confirmacion": True,
    })
    if not candidatos:
        alertas.append(f'El Factor Fx de la hoja maestra da TC {ratio}, pero no encontré ese ítem exacto en el catálogo — revisa candidatos manualmente.')


def _tc_desde_certificado(ctx: dict, propuesta: list[dict], alertas: list[str], actual_tc: dict | None) -> None:
    cert = ctx["relacion_certificada_tc"]
    candidatos = buscar_candidatos_tc(ctx["catalogo"], cert["relacion"], ctx["ubicacion"], ctx["kv_clase_tc"], 5, ctx["spec"].get("montaje_tc"), ctx["preferir_con_cable"])
    if candidatos:
        ctx["marcar_si_con_cable"](candidatos[0])
    razon = f'No se pudo determinar la capacidad instalada desde el acta — se usó la relación certificada en el certificado de calibración del TC instalado: {cert["relacion"]}' + (f' (clase {cert["clase"]})' if cert.get("clase") else "") + "."
    if actual_tc:
        razon += f" Actual en Metabase: {describir_condicion_actual(actual_tc)}."
    propuesta.append({
        "grupo": "TC", "cantidad": ctx["elementos"], "tipo": "Transformador de corriente", "razon": razon,
        "sku": candidatos[0]["sku"] if candidatos else None, "costo_estimado": candidatos[0]["costo"] if candidatos else None,
        "alternativas": candidatos[1:], "requiere_confirmacion": not candidatos,
    })
    if not candidatos:
        alertas.append(f'El certificado de calibración del TC dice relación {cert["relacion"]}, pero no encontré ese ítem exacto en el catálogo — revisa candidatos manualmente.')


def _tc_mantener_actual_ultimo_recurso(ctx: dict, propuesta: list[dict], alertas: list[str], actual_tc: dict) -> None:
    info = parsear_tc(actual_tc["sku"])
    candidatos = buscar_candidatos_tc(ctx["catalogo"], info["ratio"], info["ubicacion"] or ctx["ubicacion"], ctx["kv_clase_tc"], info["burden"], ctx["spec"].get("montaje_tc"), ctx["preferir_con_cable"])
    if candidatos:
        ctx["marcar_si_con_cable"](candidatos[0])
    propuesta.append({
        "grupo": "TC", "cantidad": ctx["elementos"], "tipo": "Transformador de corriente",
        "razon": f'No se pudo calcular la relación desde el acta (falta capacidad/nivel de tensión, no está en Normalizaciones_Indirectas/Data cambio NT, y el certificado de calibración no es legible) — se propone mantener la misma relación ya instalada ({info["ratio"]}), tomada del propio SKU en Metabase. Actual en Metabase: {describir_condicion_actual(actual_tc)}.',
        "sku": candidatos[0]["sku"] if candidatos else None, "costo_estimado": candidatos[0]["costo"] if candidatos else None,
        "alternativas": candidatos[1:], "requiere_confirmacion": True,
    })
    alertas.append(f'⚠ No pude calcular la relación de TC desde cero (falta capacidad/nivel en el acta, no está en las hojas, y el certificado de calibración no es legible) — se propuso mantener la misma relación ya instalada ({info["ratio"]}); confirma manualmente si es correcta.')
