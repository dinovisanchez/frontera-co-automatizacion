"""Configuración vía variables de entorno — sin defaults inventados.

Equivalente a PropertiesService.getScriptProperties() en Codigo.gs: si falta una variable
requerida, se lanza un error explícito en vez de asumir un valor (mismo criterio que
getMetabaseConfig() / ANTHROPIC_API_KEY en el original).
"""

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    pass


def _requerida(nombre: str) -> str:
    valor = os.environ.get(nombre)
    if not valor:
        raise ConfigError(f'Falta configurar la variable de entorno "{nombre}".')
    return valor


@dataclass(frozen=True)
class AnthropicConfig:
    api_key: str
    # Valores EXACTOS confirmados en Codigo.gs (bodyClaudeActa/bodyClaudeActaTexto, líneas
    # 3395-3422) — no elegir otros por defecto. output_config.effort, no "temperature": el
    # código original no usa temperature en ninguna llamada de este motor.
    model: str = "claude-opus-5"
    max_tokens: int = 2000
    effort: str = "medium"


@dataclass(frozen=True)
class MetabaseConfig:
    url: str
    api_key: str
    card_id: str


@dataclass(frozen=True)
class GoogleSheetsConfig:
    service_account_json: str  # contenido JSON completo de la cuenta de servicio, no una ruta
    alcance_sheet_id: str


def cargar_anthropic_config() -> AnthropicConfig:
    return AnthropicConfig(api_key=_requerida("ANTHROPIC_API_KEY"))


def cargar_metabase_config() -> MetabaseConfig:
    return MetabaseConfig(
        url=_requerida("METABASE_URL").rstrip("/"),
        api_key=_requerida("METABASE_API_KEY"),
        card_id=_requerida("METABASE_CARD_ID"),
    )


def cargar_sheets_config() -> GoogleSheetsConfig:
    return GoogleSheetsConfig(
        service_account_json=_requerida("GOOGLE_SERVICE_ACCOUNT_JSON"),
        alcance_sheet_id=_requerida("ALCANCE_SHEET_ID"),
    )


# Nombres/posiciones de hoja confirmados en Codigo.gs — mismos valores, no se leen de env
# porque no son secretos ni cambian entre entornos (dev/prod usan la misma hoja de trabajo).
SHEET_REF_TARIFARIO = "ref_tarifario"
SHEET_CONSOLIDADO = "Consolidado"
SHEET_EQUIPOS = "Equipos"
SHEET_REF_CAPEX = "ref_capex"

# Hoja de "origen" (cliente/OR/maniobra por CO) — la misma que Dinovi confirmó como la hoja
# "Data": en Codigo.gs se referencia por GID, no por nombre (ALCANCE_GID_ORIGEN = 1682501029,
# ALCANCE_FILA_INICIO_ORIGEN = 4). Se preserva igual acá: sheets_client debe resolver la
# pestaña por gid, no por nombre, para no depender de que alguien no la renombre.
GID_HOJA_ORIGEN = 1682501029
FILA_INICIO_HOJA_ORIGEN = 4
