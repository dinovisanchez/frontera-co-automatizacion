"""OPEX — resuelve el operador de red (OR) de un CO. Orden: hoja "Data" (origen) -> Metabase
Card 82534 -> pendiente de revisión manual.

⚠️ La ruta de Metabase está BLOQUEADA a propósito (ver README, sección "Pendiente: parámetro
'contrato'"): Codigo.gs nunca envía "contrato" como parámetro de consulta a la Card 82534 —
solo lo recibe como columna del resultado (línea 626-630) — y dos intentos previos de que esa
instancia de Metabase filtrara del lado del servidor fallaron (línea 707-716). No hay ninguna
fuente en el código original de dónde saldría "contrato" por CO. Mientras eso no se confirme,
_or_desde_metabase() levanta MetabaseFallbackPendiente en vez de adivinar, y
resolver_operador_red() la convierte en un resultado "pendiente_manual" — el sistema sigue
funcionando, solo avisa que ese CO necesita que alguien confirme el operador a mano.
"""

from dataclasses import dataclass

from config.settings import FILA_INICIO_HOJA_ORIGEN, GID_HOJA_ORIGEN, MetabaseConfig
from core.data_sources.sheets_client import SheetsClient
from core.utils import normalizar_codigo

FUENTE_HOJA_ORIGEN = "hoja_origen"
FUENTE_METABASE = "metabase"
FUENTE_PENDIENTE_MANUAL = "pendiente_manual"


class MetabaseFallbackPendiente(RuntimeError):
    """Se lanza mientras el parámetro 'contrato' de la Card 82534 no esté confirmado."""


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


def _or_desde_metabase(cfg: MetabaseConfig, co: str) -> str | None:
    raise MetabaseFallbackPendiente(
        f'No se puede resolver el operador de "{co}" vía Metabase: falta confirmar de dónde '
        'sale el parámetro "contrato" por CO para la Card 82534 (ver docstring de este módulo).'
    )


def resolver_operador_red(sheets: SheetsClient, metabase_cfg: MetabaseConfig | None, co_raw: str) -> ResultadoOperador:
    co = normalizar_codigo(co_raw)

    or_hoja = _or_desde_hoja_origen(sheets, co)
    if or_hoja:
        return ResultadoOperador(co=co, or_raw=or_hoja, fuente=FUENTE_HOJA_ORIGEN)

    if metabase_cfg:
        try:
            or_metabase = _or_desde_metabase(metabase_cfg, co)
            if or_metabase:
                return ResultadoOperador(co=co, or_raw=or_metabase, fuente=FUENTE_METABASE)
        except MetabaseFallbackPendiente as e:
            return ResultadoOperador(co=co, or_raw=None, fuente=FUENTE_PENDIENTE_MANUAL, motivo=str(e))

    return ResultadoOperador(
        co=co, or_raw=None, fuente=FUENTE_PENDIENTE_MANUAL,
        motivo=f'"{co}" no tiene operador de red en la hoja "Data" y no hay Metabase configurado — revisión manual.',
    )
