"""Casos de las 3 reglas de dominio (9a/9b/9d del encargo) + el caso real CO0500004018.

CO0500004018 es un caso de EXTRACCIÓN (el LLM no debía poner "13.2kV" cuando el acta solo
decía "nivel 1"/"en poste"/"transformador compartido") — ese comportamiento del prompt no es
testeable acá sin invocar al modelo real. Lo que SÍ es testeable, y es la salvaguarda real
contra que ese bug reaparezca en la capa de clasificación: si nivel_tension llega en None
(como debería, para esa acta) y el transformador es compartido, clasificar_tipo_medida NUNCA
debe reclasificar a indirecta ni forzar un nivel MT — debe dejar el tipo de medida tal como
estaba en el acta.
"""

from core.services.clasificador_medida import clasificar_tipo_medida


def test_co0500004018_no_reclasifica_sin_evidencia_de_mt(spec_vacio):
    spec = {**spec_vacio, "nivel_tension": None, "trafo_uso": "compartido", "tipo_medida_actual": "semidirecta", "capacidad_instalada_kva": 300}
    resultado = clasificar_tipo_medida(spec, nt_cambio=None, norm_indirectas=False, or_real="AFINIA")

    assert resultado.tipo_medida_final == "semidirecta"
    assert resultado.reclasificado is False
    assert resultado.nivel_tension is None  # nunca se fuerza a 13.2kV/11.4kV sin evidencia


def test_regla_9a_mt_reconocido_es_siempre_indirecta_exclusivo(spec_vacio):
    spec = {**spec_vacio, "nivel_tension": "13.2kV", "trafo_uso": "compartido", "tipo_medida_actual": "semidirecta"}
    resultado = clasificar_tipo_medida(spec, nt_cambio=None, norm_indirectas=False, or_real="EMCALI")

    assert resultado.tipo_medida_final == "indirecta"
    assert resultado.uso_transformador == "exclusivo"
    assert resultado.reclasificado is True  # semidirecta -> indirecta


def test_regla_9a_nivel_mt_por_defecto_segun_or(spec_vacio):
    """Afinia/Air-e/Caribe -> 11.4kV; el resto -> 13.2kV (Codigo.gs línea 3626-3629)."""
    spec = {**spec_vacio, "nivel_tension": None, "capacidad_instalada_kva": 300, "tipo_medida_actual": "indirecta", "trafo_uso": "exclusivo"}

    resultado_afinia = clasificar_tipo_medida(spec, nt_cambio=None, norm_indirectas=False, or_real="AFINIA CARIBE_MAR")
    assert resultado_afinia.nivel_tension == "11.4kV"

    resultado_emcali = clasificar_tipo_medida(spec, nt_cambio=None, norm_indirectas=False, or_real="EMCALI")
    assert resultado_emcali.nivel_tension == "13.2kV"


def test_regla_9b_compartido_no_reclasifica_por_capacidad_total(spec_vacio):
    """La capacidad de un transformador COMPARTIDO es de TODOS los usuarios, no de este
    cliente — ni el umbral de >225kVA ni Tabla 1 pueden aplicarse sobre ese número."""
    spec = {**spec_vacio, "nivel_tension": "120/208", "trafo_uso": "compartido", "capacidad_instalada_kva": 500, "tipo_medida_actual": "directa"}
    resultado = clasificar_tipo_medida(spec, nt_cambio=None, norm_indirectas=False, or_real="ENEL")

    assert resultado.tipo_medida_final == "directa"  # se mantiene, pese a los 500 kVA
    assert resultado.reclasificado is False


def test_regla_9b_exclusivo_bt_bajo_piso_no_reclasifica(spec_vacio):
    """Transformador EXCLUSIVO pero por debajo del piso de 15kVA: no aplica Art.19."""
    spec = {**spec_vacio, "nivel_tension": "120/208", "trafo_uso": "exclusivo", "capacidad_instalada_kva": 10, "tipo_medida_actual": "directa"}
    resultado = clasificar_tipo_medida(spec, nt_cambio=None, norm_indirectas=False, or_real="ESSA")

    assert resultado.tipo_medida_final == "directa"
    assert resultado.reclasificado is False


def test_regla_9b_exclusivo_bt_sobre_piso_si_reclasifica(spec_vacio):
    spec = {**spec_vacio, "nivel_tension": "120/208", "trafo_uso": "exclusivo", "capacidad_instalada_kva": 30, "tipo_medida_actual": "directa"}
    resultado = clasificar_tipo_medida(spec, nt_cambio=None, norm_indirectas=False, or_real="ESSA")

    assert resultado.tipo_medida_final == "indirecta"
    assert resultado.reclasificado is True


def test_clasificacion_nunca_se_degrada(spec_vacio):
    """Si ya está en un nivel más alto que el que exigiría Tabla 1 hoy, se mantiene (nunca
    baja de semidirecta a directa solo porque la capacidad actual sea menor)."""
    spec = {**spec_vacio, "nivel_tension": "120/208", "trafo_uso": None, "capacidad_instalada_kva": 5, "tipo_medida_actual": "semidirecta"}
    resultado = clasificar_tipo_medida(spec, nt_cambio=None, norm_indirectas=False, or_real="ESSA")

    assert resultado.tipo_medida_final == "semidirecta"
