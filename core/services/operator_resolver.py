"""OPEX — resuelve el operador de red (OR) de un CO. Orden: hoja "Data" (origen) -> acta más
reciente en Metabase (Card 82534) -> pendiente de revisión manual.

El OR NO es una columna de la Card 82534 (confirmado, Codigo.gs línea 626-630 y por Dinovi,
2026-09-21) — vive DENTRO del texto del acta, igual que la relación de TC/TP certificada.
Por eso el fallback no consulta Metabase por el dato directamente: usa Metabase solo para
encontrar el `act_pdf_url` de la acta más reciente del CO (mismo filtro que usa CAPEX,
TIPOS_ACTA_ALCANCE), descarga ese PDF, y le hace una pregunta puntual y barata a Claude
(or_extractor.py) — NO corre la extracción completa de 14 campos solo para esto.
"""

from dataclasses import dataclass

from config.settings import FILA_INICIO_HOJA_ORIGEN, GID_HOJA_ORIGEN
from core.data_sources.llm_client import AnthropicClient
from core.data_sources.metabase_client import MetabaseClient
from core.data_sources.sheets_client import SheetsClient
from core.prompts.acta_extraction_prompt import TIPOS_ACTA_ALCANCE
from core.services import acta_downloader, or_extractor
from core.utils import normalizar_codigo

FUENTE_HOJA_ORIGEN = "hoja_origen"
FUENTE_ACTA_PDF = "acta_pdf"
FUENTE_PENDIENTE_MANUAL = "pendiente_manual"


@dataclass
class ResultadoOperador:
    co: str
    or_raw: str | None
    fuente: str
    motivo: str | None = None


def _or_desde_hoja_origen(sheets: SheetsClient, co: str) -> str | None:
    """Puerto de leerFilasOrigenAlcance (Codigo.gs líneas 2879-2897): columna C = OR,
    a partir de la fila FILA_INICIO_HOJA_ORIGEN, en la hoja identificada por GID_HOJA_ORIGEN
    (la misma que Dinovi confirmó como "Data").
    """
    hoja = sheets.hoja_por_gid(GID_HOJA_ORIGEN)
    ultima_fila = hoja.row_count
    if ultima_fila < FILA_INICIO_HOJA_ORIGEN:
        return None
    filas = sheets.leer_rango(hoja, FILA_INICIO_HOJA_ORIGEN, 1, ultima_fila - FILA_INICIO_HOJA_ORIGEN + 1, 7)
    for fila in filas:
        if normalizar_codigo(fila[0]) == co and (fila[2] or "").strip():
            return fila[2].strip()
    return None


def _acta_pdf_mas_reciente(metabase: MetabaseClient, co: str) -> str | None:
    filas = [
        f for f in metabase.filas_por_co(co)
        if (f.get("service_type_id") or "").upper() in TIPOS_ACTA_ALCANCE and f.get("act_pdf_url")
    ]
    if not filas:
        return None
    return max(filas, key=lambda f: f.get("fecha_visita") or "")["act_pdf_url"]


def _or_desde_acta_pdf(metabase: MetabaseClient, llm: AnthropicClient, co: str) -> str | None:
    url = _acta_pdf_mas_reciente(metabase, co)
    if not url:
        return None
    descarga = acta_downloader.descargar_pdf_acta(url)
    if not descarga.ok:
        return None
    return or_extractor.extraer_or_desde_pdf(descarga.bytes_pdf, llm)


def resolver_operador_red(
    sheets: SheetsClient, metabase: MetabaseClient | None, llm: AnthropicClient | None, co_raw: str
) -> ResultadoOperador:
    co = normalizar_codigo(co_raw)

    or_hoja = _or_desde_hoja_origen(sheets, co)
    if or_hoja:
        return ResultadoOperador(co=co, or_raw=or_hoja, fuente=FUENTE_HOJA_ORIGEN)

    if metabase and llm:
        try:
            or_acta = _or_desde_acta_pdf(metabase, llm, co)
            if or_acta:
                return ResultadoOperador(co=co, or_raw=or_acta, fuente=FUENTE_ACTA_PDF)
        except Exception as e:  # noqa: BLE001 — un fallo de Metabase/LLM acá no debe tumbar la resolución, cae a manual
            return ResultadoOperador(
                co=co, or_raw=None, fuente=FUENTE_PENDIENTE_MANUAL,
                motivo=f'"{co}" no tiene OR en la hoja "Data" y falló la lectura del acta ({e}) — revisión manual.',
            )

    return ResultadoOperador(
        co=co, or_raw=None, fuente=FUENTE_PENDIENTE_MANUAL,
        motivo=f'"{co}" no tiene operador de red en la hoja "Data" ni se pudo extraer de ninguna acta — revisión manual.',
    )
