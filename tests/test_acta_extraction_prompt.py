"""Test de integridad del prompt — no ejecuta el LLM, solo verifica que nadie haya reescrito
o recortado por accidente las frases que blindan las reglas de dominio (9a/9b/9c/9d). Si este
test falla, alguien editó el prompt: revisar el diff con mucho cuidado antes de aceptarlo.
"""

from core.prompts.acta_extraction_prompt import (
    ACTA_EXTRACTION_PROMPT_V1,
    ACTA_EXTRACTION_PROMPT_V2,
    CAMPOS_A_COMBINAR_ALCANCE,
)


def test_advertencia_nivel_tension_presente_verbatim():
    """Caso real CO0500004018 — estas frases son las que evitan que el LLM asuma MT sin evidencia."""
    assert "NUNCA pongas un valor de Media Tensión" in ACTA_EXTRACTION_PROMPT_V1
    assert '"Nivel 1/2/3/4"' in ACTA_EXTRACTION_PROMPT_V1
    assert "en poste" in ACTA_EXTRACTION_PROMPT_V1
    assert "red de baja tensión" in ACTA_EXTRACTION_PROMPT_V1
    assert "transformador compartido" in ACTA_EXTRACTION_PROMPT_V1
    assert "nunca asumas MT por default" in ACTA_EXTRACTION_PROMPT_V1


def test_regla_de_oro_no_inventar_presente():
    assert "NO lo inventes ni lo deduzcas de memoria general" in ACTA_EXTRACTION_PROMPT_V1
    assert "déjalo en null" in ACTA_EXTRACTION_PROMPT_V1


def test_regla_ubicacion_medida_presente():
    assert "Descripción ubicación de la celda" in ACTA_EXTRACTION_PROMPT_V1
    assert "poste a la intemperie = exterior" in ACTA_EXTRACTION_PROMPT_V1


def test_esquema_de_14_campos_completo():
    campos_esperados = [
        "tipo_medida_actual", "nivel_tension", "capacidad_instalada_kva", "trafo_uso",
        "ubicacion_medida", "elementos_medida", "relacion_tc", "relacion_tp", "montaje_tc",
        "totalizador_amperios", "conductor_calibre", "recuperable_por_cable", "observaciones", "supuestos",
    ]
    for campo in campos_esperados:
        assert f'"{campo}"' in ACTA_EXTRACTION_PROMPT_V1, f"falta el campo {campo} en el prompt"
    assert len(campos_esperados) == 14


def test_formato_de_respuesta_obligatorio_presente():
    assert "RESUMEN:" in ACTA_EXTRACTION_PROMPT_V1
    assert "ANALISIS_LISTO" in ACTA_EXTRACTION_PROMPT_V1


def test_v2_conserva_todo_el_texto_de_v1():
    """V2 debe ser V1 + la advertencia nueva, nunca reescribir lo ya calibrado."""
    assert ACTA_EXTRACTION_PROMPT_V1 in ACTA_EXTRACTION_PROMPT_V2 or set(ACTA_EXTRACTION_PROMPT_V1.split()).issubset(set(ACTA_EXTRACTION_PROMPT_V2.split()))


def test_v2_advertencia_red_de_media_tension_presente():
    """Caso real CO0200002425 — "Red de media tensión (kV)" describe la red que alimenta un
    transformador COMPARTIDO, no la conexión del cliente."""
    assert "Red de media tensión (kV)" in ACTA_EXTRACTION_PROMPT_V2
    assert "transformador de distribución compartido" in ACTA_EXTRACTION_PROMPT_V2
    assert "0,72 kV" in ACTA_EXTRACTION_PROMPT_V2
    assert "Red de media tensión (kV)" not in ACTA_EXTRACTION_PROMPT_V1  # confirma que es nueva en V2


def test_campos_a_combinar_no_incluye_los_bono():
    """relacion_tc/relacion_tp/montaje_tc/totalizador_amperios/conductor_calibre son "bono":
    no deben detener el escaneo de más actas por sí solos (Codigo.gs línea 3272-3281)."""
    for campo_bono in ("relacion_tc", "relacion_tp", "montaje_tc", "totalizador_amperios", "conductor_calibre"):
        assert campo_bono not in CAMPOS_A_COMBINAR_ALCANCE
