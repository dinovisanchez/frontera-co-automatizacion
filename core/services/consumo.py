"""Registro y resumen del CONSUMO de la API de Claude (Dinovi, 2026-10-01: "quiero saber cuánto
gasto y bajarlo sin perder calidad" — la app no medía nada, así que todo costo era un estimado).

Cada llamada a Claude deja UNA fila en la pestaña "PyConsumo" de la hoja de Alcances (tokens de
entrada / caché / salida / razonamiento, intentos, segundos, costo estimado en USD, y a qué CO y
tipo de llamada corresponde). `resumir()` convierte esas filas en los números que importan:
costo medio por CO, tasa de aciertos del caché, respuestas cortadas, reintentos, etc.

El registro es "mejor esfuerzo": NUNCA debe romper ni retrasar una extracción. Por eso no usa
`con_reintento_sheets` (un 429 de Sheets reintentaría con esperas de hasta 14 s dentro de una
función de 60 s) y cualquier error se traga y se deja en el log de Vercel.
"""

import statistics
import sys
from collections import Counter, defaultdict

from config.settings import PRECIOS_USD_POR_MTOK
from core.data_sources.sheets_client import SheetsClient, con_reintento_sheets

SHEET_CONSUMO = "PyConsumo"

COLUMNAS = [
    "fecha_utc", "co", "tipo", "origen", "acta", "modelo", "esfuerzo",
    "entrada", "escritura_cache", "lectura_cache", "salida", "razonamiento",
    "stop_reason", "intentos", "fallidos", "segundos", "costo_usd", "resultado", "error", "request_id",
]
_COLUMNAS_NUMERICAS = {
    "entrada", "escritura_cache", "lectura_cache", "salida", "razonamiento", "intentos", "fallidos", "segundos", "costo_usd",
}


def costo_usd(modelo: str | None, entrada: int, escritura_cache: int, lectura_cache: int, salida: int) -> float | None:
    """Costo estimado de UNA llamada, o None si el modelo no está en PRECIOS_USD_POR_MTOK."""
    precios = PRECIOS_USD_POR_MTOK.get(modelo or "")
    if precios is None:
        return None
    return (
        entrada * precios["entrada"] + escritura_cache * precios["escritura_cache"]
        + lectura_cache * precios["lectura_cache"] + salida * precios["salida"]
    ) / 1_000_000


def fila_desde_registro(registro: dict) -> list:
    """Ordena un registro (el dict que arma llm_client) según COLUMNAS y le calcula el costo."""
    costo = costo_usd(
        registro.get("modelo"), registro.get("entrada") or 0, registro.get("escritura_cache") or 0,
        registro.get("lectura_cache") or 0, registro.get("salida") or 0,
    )
    completo = {**registro, "costo_usd": round(costo, 6) if costo is not None else ""}
    return ["" if completo.get(c) is None else completo.get(c) for c in COLUMNAS]


class ConsumoStore:
    def __init__(self, sheets: SheetsClient):
        self._sheets = sheets

    def _hoja(self):
        try:
            return self._sheets.hoja_por_nombre(SHEET_CONSUMO)
        except RuntimeError:
            hoja = self._sheets.crear_hoja(SHEET_CONSUMO, filas=5000, columnas=len(COLUMNAS))
            hoja.update([COLUMNAS], range_name="A1")
            return hoja

    def registrar(self, registro: dict) -> None:
        try:
            # table_range="A1": sin rango Sheets "busca una tabla" y puede insertar corrido (mismo
            # bug real que ya se corrigió en lote_store.crear_lote y acta_cache.guardar).
            self._hoja().append_row(fila_desde_registro(registro), value_input_option="RAW", table_range="A1")
        except Exception as e:  # noqa: BLE001 — medir nunca debe romper la extracción
            print(f"[consumo] no se pudo registrar el uso: {e}", file=sys.stderr)

    def leer(self, desde: str | None = None) -> list[dict]:
        """Todas las filas como dicts (números ya convertidos). `desde`: 'YYYY-MM-DD' (UTC)."""
        valores = con_reintento_sheets(self._hoja().get_all_values)
        registros = []
        for fila in valores[1:]:
            if not fila or not fila[0]:
                continue
            reg = {}
            for i, col in enumerate(COLUMNAS):
                v = fila[i] if i < len(fila) else ""
                if col in _COLUMNAS_NUMERICAS:
                    try:
                        v = float(v) if v != "" else None
                    except ValueError:
                        v = None
                reg[col] = v
            if desde and reg["fecha_utc"] < desde:
                continue
            registros.append(reg)
        return registros


def get_consumo_store(sheets: SheetsClient) -> ConsumoStore:
    return ConsumoStore(sheets)


def _media(valores: list[float]) -> float | None:
    return round(sum(valores) / len(valores), 6) if valores else None


def _p90(valores: list[float]) -> float | None:
    if not valores:
        return None
    ordenados = sorted(valores)
    return ordenados[min(len(ordenados) - 1, int(len(ordenados) * 0.9))]


def _suma(registros: list[dict], campo: str) -> float:
    return sum(r.get(campo) or 0 for r in registros)


def resumir(registros: list[dict]) -> dict:
    """Los números que importan para decidir cómo bajar el costo, a partir de las filas de PyConsumo."""
    ok = [r for r in registros if r.get("resultado") == "ok"]
    errores = [r for r in registros if r.get("resultado") != "ok"]

    entrada, escritura, lectura = _suma(ok, "entrada"), _suma(ok, "escritura_cache"), _suma(ok, "lectura_cache")
    salida, razonamiento = _suma(ok, "salida"), _suma(ok, "razonamiento")
    entrada_total = entrada + escritura + lectura
    costos_ok = [r["costo_usd"] for r in ok if r.get("costo_usd") is not None]

    por_tipo = {}
    for tipo in sorted({r.get("tipo") or "?" for r in ok}):
        grupo = [r for r in ok if (r.get("tipo") or "?") == tipo]
        por_tipo[tipo] = {
            "llamadas": len(grupo),
            "costo_total_usd": round(_suma(grupo, "costo_usd"), 4),
            "costo_medio_usd": _media([r["costo_usd"] for r in grupo if r.get("costo_usd") is not None]),
            "entrada_media": _media([(r.get("entrada") or 0) + (r.get("escritura_cache") or 0) + (r.get("lectura_cache") or 0) for r in grupo]),
            "salida_media": _media([r.get("salida") or 0 for r in grupo]),
            "segundos_medio": _media([r["segundos"] for r in grupo if r.get("segundos") is not None]),
        }

    por_config = defaultdict(list)
    for r in ok:
        por_config[f"{r.get('modelo') or '?'} · esfuerzo {r.get('esfuerzo') or '?'}"].append(r)
    por_configuracion = {
        k: {
            "llamadas": len(g), "costo_total_usd": round(_suma(g, "costo_usd"), 4),
            "costo_medio_usd": _media([r["costo_usd"] for r in g if r.get("costo_usd") is not None]),
            "salida_media": _media([r.get("salida") or 0 for r in g]),
        }
        for k, g in sorted(por_config.items())
    }

    costo_por_co = defaultdict(float)
    llamadas_por_co = Counter()
    for r in ok:
        if r.get("co"):
            costo_por_co[r["co"]] += r.get("costo_usd") or 0
            llamadas_por_co[r["co"]] += 1
    costo_medio_co = _media(list(costo_por_co.values()))

    por_origen = {}
    for origen in sorted({r.get("origen") or "?" for r in ok}):
        g = [r for r in ok if (r.get("origen") or "?") == origen]
        por_origen[origen] = {"llamadas": len(g), "costo_total_usd": round(_suma(g, "costo_usd"), 4)}

    truncadas = [r for r in ok if r.get("stop_reason") == "max_tokens"]
    con_reintentos = [r for r in registros if (r.get("intentos") or 1) > 1]
    fechas = sorted(r["fecha_utc"] for r in registros if r.get("fecha_utc"))

    return {
        "desde": fechas[0] if fechas else None,
        "hasta": fechas[-1] if fechas else None,
        "llamadas": len(registros),
        "llamadas_ok": len(ok),
        "llamadas_con_error": len(errores),
        "costo_total_usd": round(sum(costos_ok), 4),
        "costo_medio_por_llamada_usd": _media(costos_ok),
        "tokens": {"entrada": entrada, "escritura_cache": escritura, "lectura_cache": lectura, "salida": salida, "razonamiento": razonamiento},
        "cache_tasa_aciertos": round(lectura / entrada_total, 4) if entrada_total else None,
        "razonamiento_pct_de_salida": round(razonamiento / salida, 4) if salida else None,
        "por_tipo": por_tipo,
        "por_configuracion": por_configuracion,
        "por_origen": por_origen,
        "cos_distintos": len(costo_por_co),
        "costo_medio_por_co_usd": costo_medio_co,
        "costo_max_por_co_usd": round(max(costo_por_co.values()), 4) if costo_por_co else None,
        "llamadas_medias_por_co": _media(list(llamadas_por_co.values())),
        "proyeccion_usd": (
            {"100_cos": round(costo_medio_co * 100, 2), "400_cos": round(costo_medio_co * 400, 2)} if costo_medio_co is not None else None
        ),
        "respuestas_cortadas": {"cantidad": len(truncadas), "pct": round(len(truncadas) / len(ok), 4) if ok else None},
        "reintentos": {
            "llamadas_con_reintentos": len(con_reintentos),
            "pct": round(len(con_reintentos) / len(registros), 4) if registros else None,
            "intentos_fallidos_totales": int(_suma(registros, "fallidos")),
        },
        "segundos": {"medio": _media([r["segundos"] for r in ok if r.get("segundos") is not None]), "p90": _p90([r["segundos"] for r in ok if r.get("segundos") is not None])},
        "errores_por_tipo": dict(Counter(r.get("error") or "?" for r in errores)),
    }
