"""Construcción de los clientes concretos a partir de las variables de entorno — un solo
lugar para que los endpoints de /api no dupliquen la carga de config en cada archivo.
"""

from dataclasses import dataclass

from config.settings import cargar_anthropic_config, cargar_metabase_config, cargar_sheets_config
from core.data_sources.llm_client import AnthropicClient
from core.data_sources.metabase_client import MetabaseClient
from core.data_sources.sheets_client import SheetsClient
from core.services.job_store import JobStore


@dataclass
class Dependencias:
    sheets: SheetsClient
    llm: AnthropicClient
    metabase: MetabaseClient | None
    jobs: JobStore
    drive_cfg: object  # GoogleSheetsConfig — acta_ocr.py lo reutiliza para las credenciales de Drive


def construir_dependencias(requiere_metabase: bool = True) -> Dependencias:
    sheets_cfg = cargar_sheets_config()
    sheets = SheetsClient(sheets_cfg)
    llm = AnthropicClient(cargar_anthropic_config())

    metabase = None
    try:
        metabase = MetabaseClient(cargar_metabase_config())
    except Exception:
        if requiere_metabase:
            raise

    return Dependencias(sheets=sheets, llm=llm, metabase=metabase, jobs=JobStore(sheets), drive_cfg=sheets_cfg)
