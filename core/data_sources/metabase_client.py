"""Cliente de Metabase (Card 82534, "Quinquenales Smith") — reemplaza filasMetabasePorCo().

Mismo enfoque que Codigo.gs (líneas 707-749): NO se filtra del lado del servidor. Dos
intentos previos en el original (MBQL crudo y SQL nativo vía /api/dataset) fallaron con
errores de formato específicos de esa instancia de Metabase — por eso se sigue usando
/api/card/:id/query/csv sin parámetros y se filtra el CSV completo por bia_code en memoria.

Si en algún momento se confirma que un endpoint parametrizado (bia_code + contrato) sí
funciona en la instancia real, esto se puede reemplazar — ver nota de "contrato" pendiente
en operator_resolver.py.
"""

import csv
import io
import time
from dataclasses import dataclass

import requests

from config.settings import MetabaseConfig
from core.utils import normalizar_codigo

CSV_CACHE_TTL_SEG = 300  # igual que METABASE_CSV_CACHE_TTL_SEG en Codigo.gs (línea 654)
MAX_REINTENTOS = 3
BACKOFF_BASE_SEG = 1.5


class MetabaseAuthError(RuntimeError):
    """401/403 — credenciales inválidas. Error crítico, distinto de 'operador no determinado'."""


class MetabaseRateLimitError(RuntimeError):
    """429 — límite de tasa. Error crítico, distinto de 'operador no determinado'."""


@dataclass
class _CacheEntry:
    filas: list[dict]
    expira_en: float


# Caché a nivel de MÓDULO, no de instancia (Dinovi, 2026-09-24: "Comparación Masiva" de ~400 CO
# hace cientos de invocaciones de Vercel — una por acta/paso — y cada una crea un MetabaseClient
# nuevo vía construir_dependencias(); con el caché en self, esa instancia nueva siempre partía
# con self._cache=None y volvía a descargar el CSV completo (34 mil filas) en CADA paso. Vercel
# reutiliza el mismo contenedor/proceso para invocaciones seguidas (mismo patrón que una Lambda
# tibia) — un caché a nivel de módulo sí sobrevive entre esas invocaciones y corta la mayoría de
# esas descargas repetidas, sin tocar el resto del flujo ni el TTL de 5 min ya existente.
_cache_global: _CacheEntry | None = None


class MetabaseClient:
    def __init__(self, cfg: MetabaseConfig):
        self._cfg = cfg

    def _descargar_csv_con_reintentos(self) -> str:
        url = f"{self._cfg.url}/api/card/{self._cfg.card_id}/query/csv"
        headers = {"x-api-key": self._cfg.api_key}
        ultimo_error: Exception | None = None

        for intento in range(1, MAX_REINTENTOS + 1):
            try:
                resp = requests.post(url, headers=headers, timeout=60)
            except requests.RequestException as e:
                ultimo_error = e
                time.sleep(BACKOFF_BASE_SEG * (2 ** (intento - 1)))
                continue

            if resp.status_code == 200:
                return resp.text
            if resp.status_code in (401, 403):
                raise MetabaseAuthError(f"Metabase respondió HTTP {resp.status_code} (credenciales inválidas).")
            if resp.status_code == 429:
                raise MetabaseRateLimitError("Metabase respondió HTTP 429 (rate limit).")

            ultimo_error = RuntimeError(f"Metabase respondió HTTP {resp.status_code}: {resp.text[:300]}")
            if intento < MAX_REINTENTOS:
                time.sleep(BACKOFF_BASE_SEG * (2 ** (intento - 1)))

        raise ultimo_error or RuntimeError("Metabase: fallo desconocido tras reintentos.")

    def _csv_cacheado(self) -> list[dict]:
        global _cache_global
        ahora = time.monotonic()
        if _cache_global and _cache_global.expira_en > ahora:
            return _cache_global.filas

        texto = self._descargar_csv_con_reintentos()
        lector = csv.DictReader(io.StringIO(texto))
        if "bia_code" not in (lector.fieldnames or []):
            raise RuntimeError(
                f'La columna "bia_code" no está en el CSV de Metabase (columnas: {lector.fieldnames}).'
            )
        filas = list(lector)
        _cache_global = _CacheEntry(filas=filas, expira_en=ahora + CSV_CACHE_TTL_SEG)
        return filas

    def filas_por_co(self, co: str) -> list[dict]:
        """Equivalente a filasMetabasePorCo(co) — filtra el CSV completo por bia_code."""
        return [f for f in self._csv_cacheado() if normalizar_codigo(f.get("bia_code", "")) == co]


def get_metabase_client(cfg: MetabaseConfig) -> MetabaseClient:
    return MetabaseClient(cfg)
