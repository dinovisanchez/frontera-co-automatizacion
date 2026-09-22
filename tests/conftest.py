"""Fixtures compartidas — ningún test de este proyecto llama a Anthropic, Metabase o Google
Sheets reales (requisito del encargo de migración: mocks para LLM y Metabase)."""

import pytest


@pytest.fixture
def spec_vacio() -> dict:
    """Spec con las 14 llaves del esquema, todo en None — el punto de partida de "no inventar
    nada" que exige ALCANCE_EXTRACTION_PROMPT."""
    return {
        "tipo_medida_actual": None,
        "nivel_tension": None,
        "capacidad_instalada_kva": None,
        "trafo_uso": None,
        "ubicacion_medida": None,
        "elementos_medida": None,
        "relacion_tc": None,
        "relacion_tp": None,
        "montaje_tc": None,
        "totalizador_amperios": None,
        "conductor_calibre": None,
        "recuperable_por_cable": None,
        "observaciones": "",
        "supuestos": [],
    }
