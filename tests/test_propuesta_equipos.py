"""construir_propuesta_equipos — no necesita Google Sheets/Metabase, recibe todo por
parámetro. Caso real CO0200002425 (2026-09-22): semidirecta, transformador compartido, TC ya
instalado (200/5, ventana interior) SIN certificado -> Lovable lo marca "Sin información" ->
condición: cambiarlo. Celda también "Sin información" pero sin match en el catálogo de
prueba (comportamiento correcto: cae a "sugerido por tipo de medida").
"""

from core.services.clasificador_medida import clasificar_tipo_medida
from core.services.propuesta_equipos import construir_propuesta_equipos

_CATALOGO = [
    {"sku": "TC 200/5 Ventana Interior C 0.5s B 5 VA T 0.72 kV", "categoria": "Transformador de corriente", "costo": 123000.0,
     "tc": {"ratio": "200/5", "ratio_range": {"min": 200.0, "max": 200.0}, "ubicacion": "interior", "burden": 5.0, "kv": 0.72, "con_cable": None, "montaje": "ventana"}},
]

_SPEC = {
    "tipo_medida_actual": "semidirecta", "nivel_tension": None, "capacidad_instalada_kva": 300,
    "trafo_uso": "compartido", "ubicacion_medida": "interior", "elementos_medida": 3,
    "relacion_tc": "200/5", "relacion_tp": None, "montaje_tc": "ventana",
    "totalizador_amperios": 200, "conductor_calibre": "1/0", "recuperable_por_cable": None,
    "observaciones": "", "supuestos": [],
}


def _diagnostico_dict():
    diag = clasificar_tipo_medida(_SPEC, nt_cambio=None, norm_indirectas=False, or_real="EMCALI CALI")
    return {
        "tipo_medida_actual": diag.tipo_medida_actual, "tipo_medida_final": diag.tipo_medida_final,
        "uso_transformador": diag.uso_transformador, "nivel_tension": diag.nivel_tension, "kva": diag.kva,
        "elementos": diag.elementos, "fases_medidor": None, "motivo": diag.motivo, "reclasificado": diag.reclasificado,
    }, diag


def test_co0200002425_propone_el_tc_correcto_sin_reclasificar():
    diagnostico, diag_obj = _diagnostico_dict()
    assert diag_obj.tipo_medida_final == "semidirecta"  # no reclasificado a indirecta (ver ACTA_EXTRACTION_PROMPT_V2)

    equipos_actuales = {
        "tc": {"sku": "TC 200/5 Ventana Interior C 0.5s B 5 VA T 0.72 kV", "marca": "ATEL", "serial": "1C68309",
               "estado_material": "Bueno", "certificado_conformidad": False, "vto_conformidad": None,
               "certificado_calibracion": False, "certificado_calibracion_url": None, "vto_calibracion": None,
               "calibracion_vencida": False, "calibracion_vencida_al_instalar": False, "fecha_visita": None},
        "medidor": None, "tp": None, "bloque_pruebas": None, "cable": None, "celda": None,
    }
    dictamen = {"clasificacion": "normalizacion", "secciones": {"medidor": False, "tc": True, "bloque_pruebas": False, "celda": True, "cable": False, "tp": False}}

    resultado = construir_propuesta_equipos(diagnostico, _SPEC, _CATALOGO, [], dictamen, equipos_actuales, None, None, None, None, "EMCALI CALI")

    filas_tc = [f for f in resultado["propuesta"] if f["grupo"] == "TC"]
    assert len(filas_tc) == 1
    assert filas_tc[0]["sku"] == "TC 200/5 Ventana Interior C 0.5s B 5 VA T 0.72 kV"
    assert filas_tc[0]["costo_estimado"] == 123000.0
    assert filas_tc[0]["cantidad"] == 3  # elementos_medida
    assert "SIN conformidad" in filas_tc[0]["razon"] and "SIN calibración" in filas_tc[0]["razon"]

    filas_celda = [f for f in resultado["propuesta"] if f["grupo"] == "Celda"]
    assert len(filas_celda) == 1
    assert filas_celda[0]["sku"] is None  # catálogo de prueba no trae ninguna celda -> queda para elegir a mano
    assert filas_celda[0]["requiere_confirmacion"] is True


def test_cumple_no_propone_nada():
    diagnostico, _ = _diagnostico_dict()
    resultado = construir_propuesta_equipos(diagnostico, _SPEC, _CATALOGO, [], {"clasificacion": "cumple"}, {}, None, None, None, None, "EMCALI")
    assert resultado["propuesta"] == []
    assert "Cumple" in resultado["alertas"][0]


def test_recuperable_solo_documento_no_equipo():
    diagnostico, _ = _diagnostico_dict()
    dictamen = {"clasificacion": "recuperable", "detalleFaltante": ["Celda de medida: falta conformidad (Carta)"]}
    resultado = construir_propuesta_equipos(diagnostico, _SPEC, _CATALOGO, [], dictamen, {}, None, None, None, None, "EMCALI")
    assert len(resultado["propuesta"]) == 1
    assert resultado["propuesta"][0]["sku"] is None
    assert resultado["propuesta"][0]["requiere_confirmacion"] is True


def test_reclasificado_ignora_cumple_de_lovable_y_genera_normalizacion():
    """CO0400004001 (caso real anterior): reclasificado a indirecta por Art.19 debe generar el
    alcance completo aunque Lovable diga "Cumple" bajo el esquema viejo."""
    spec = {**_SPEC, "nivel_tension": "13.2kV"}
    diag = clasificar_tipo_medida(spec, nt_cambio=None, norm_indirectas=False, or_real="EMCALI")
    assert diag.reclasificado is True
    diagnostico = {
        "tipo_medida_actual": diag.tipo_medida_actual, "tipo_medida_final": diag.tipo_medida_final,
        "uso_transformador": diag.uso_transformador, "nivel_tension": diag.nivel_tension, "kva": diag.kva,
        "elementos": diag.elementos, "fases_medidor": None, "motivo": diag.motivo, "reclasificado": diag.reclasificado,
    }
    resultado = construir_propuesta_equipos(diagnostico, spec, _CATALOGO, [], {"clasificacion": "cumple"}, {}, None, None, None, None, "EMCALI")
    assert any("Art.19" in a for a in resultado["alertas"])
    assert any(f["grupo"] == "TC" for f in resultado["propuesta"])
