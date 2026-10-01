"""Comparación de configuraciones (modelo + esfuerzo) de la extracción de actas — Dinovi, 2026-10-01:
"bajar el precio con calidad igual o mejor". Sin forma de medir la calidad, cambiar de modelo o de
esfuerzo es una apuesta; esto la convierte en una prueba: la MISMA acta (mismo texto OCR, mismo
prompt, mismo código de producción) se extrae con la configuración actual y con las candidatas, y se
comparan los 12 campos técnicos y lo que costó cada una.

Ojo con lo que NO dice: la configuración actual es la REFERENCIA, no la verdad. Una diferencia puede
ser un error de la candidata… o un error de la actual que la candidata corrige. Por eso la
herramienta solo muestra las diferencias (y qué configuración dejó el campo vacío) para que una
persona las revise contra el acta; no decide por sí sola.

Cada candidata corre en su propio hilo para que una acta se compare en el tiempo de una sola llamada
(la función de Vercel tiene 60 s). Los registros de consumo se devuelven al llamador y se guardan
después, en secuencia, para no compartir el cliente de Sheets entre hilos.
"""

import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from config.settings import AnthropicConfig
from core.data_sources.llm_client import AnthropicClient
from core.services.acta_analyzer import MetadatosActa, analizar_acta_desde_texto
from core.services.consumo import costo_usd
from core.services.tarifa_calculator import normalizar_texto_opex
from core.validators.alcance_schema import CAMPOS_ESQUEMA_ACTA

ID_ACTUAL = "actual"

# Candidatas ofrecidas (modelo, esfuerzo). Haiku 4.5 queda fuera a propósito: no acepta `effort`.
CONFIGS_CANDIDATAS = {
    "opus-5-5-medio": {"modelo": "claude-opus-5-5", "esfuerzo": "medium", "nombre": "Opus 5.5 · esfuerzo medio"},
    "opus-5-5-bajo": {"modelo": "claude-opus-5-5", "esfuerzo": "low", "nombre": "Opus 5.5 · esfuerzo bajo"},
    "sonnet-5-5-medio": {"modelo": "claude-sonnet-5-5", "esfuerzo": "medium", "nombre": "Sonnet 5.5 · esfuerzo medio"},
    "sonnet-5-5-bajo": {"modelo": "claude-sonnet-5-5", "esfuerzo": "low", "nombre": "Sonnet 5.5 · esfuerzo bajo"},
    "opus-5-bajo": {"modelo": "claude-opus-5", "esfuerzo": "low", "nombre": "Opus 5 · esfuerzo bajo"},
}
MAX_CANDIDATAS = 3

# observaciones y supuestos son texto libre: siempre difieren en la redacción, así que no cuentan
# como acuerdo/desacuerdo (los 12 campos técnicos sí).
CAMPOS_COMPARADOS = tuple(c for c in CAMPOS_ESQUEMA_ACTA if c not in ("observaciones", "supuestos"))

_PATRON_NUMERO = re.compile(r"^-?\d+([.,]\d+)?$")


def _formatear_numero(n: float) -> str:
    return ("%.3f" % n).rstrip("0").rstrip(".")


def normalizar_valor(v) -> str | None:
    """Forma canónica para decidir si dos valores "dicen lo mismo" (75 == "75.0", mayúsculas,
    acentos y orden de listas no cuentan). None / "" / [] son todos "vacío"."""
    if v is None or v == "" or v == []:
        return None
    if isinstance(v, bool):
        return "si" if v else "no"
    if isinstance(v, (int, float)):
        return _formatear_numero(float(v))
    if isinstance(v, (list, tuple)):
        partes = sorted(p for p in (normalizar_valor(x) for x in v) if p)
        return "|".join(partes) or None
    if isinstance(v, dict):
        return "|".join(f"{k}={normalizar_valor(x)}" for k, x in sorted(v.items()) if normalizar_valor(x)) or None
    texto = str(v).strip()
    if _PATRON_NUMERO.match(texto):
        return _formatear_numero(float(texto.replace(",", ".")))
    return normalizar_texto_opex(texto) or None


def comparar_specs(actual: dict | None, candidata: dict | None) -> dict:
    """Estado de cada campo técnico de `candidata` frente a `actual` (la referencia):
    igual | diferente | solo_actual (la candidata lo dejó vacío) | solo_candidata (la actual lo dejó
    vacío) | sin_resultado (la candidata no devolvió nada)."""
    campos = {}
    conteo = {"igual": 0, "diferente": 0, "solo_actual": 0, "solo_candidata": 0, "sin_resultado": 0}
    for campo in CAMPOS_COMPARADOS:
        va = (actual or {}).get(campo)
        vc = (candidata or {}).get(campo)
        if candidata is None:
            estado = "sin_resultado"
        else:
            na, nc = normalizar_valor(va), normalizar_valor(vc)
            if na == nc:
                estado = "igual"
            elif na is None:
                estado = "solo_candidata"
            elif nc is None:
                estado = "solo_actual"
            else:
                estado = "diferente"
        conteo[estado] += 1
        if estado != "igual":
            campos[campo] = {"estado": estado, "actual": va, "candidata": vc}
    return {"coinciden": conteo["igual"], "total": len(CAMPOS_COMPARADOS), "conteo": conteo, "diferencias": campos}


def _extraer(meta: MetadatosActa, texto_ocr: str, cfg: AnthropicConfig, config_id: str) -> dict:
    """Corre la extracción de producción (analizar_acta_desde_texto) con `cfg` sobre el texto dado."""
    registros: list[dict] = []
    llm = AnthropicClient(cfg)
    llm.registrador = registros.append
    llm.contexto = {"origen": "comparacion"}
    inicio = time.monotonic()
    spec, error = None, None
    try:
        respuesta = analizar_acta_desde_texto(meta, texto_ocr, llm)
        spec = respuesta.spec
        if spec is None:
            error = "La respuesta no trajo un JSON válido."
    except Exception as e:  # noqa: BLE001 — una configuración que falla es un RESULTADO de la comparación, no un error de la herramienta
        error = str(e)[:300]

    ok = [r for r in registros if r.get("resultado") == "ok"]
    tokens = {
        k: int(sum(r.get(k) or 0 for r in ok)) for k in ("entrada", "escritura_cache", "lectura_cache", "salida", "razonamiento")
    }
    costo = sum(costo_usd(cfg.model, r.get("entrada") or 0, r.get("escritura_cache") or 0, r.get("lectura_cache") or 0, r.get("salida") or 0) or 0 for r in ok)
    return {
        "id": config_id, "modelo": cfg.model, "esfuerzo": cfg.effort,
        "ok": spec is not None, "error": error, "spec": spec,
        "segundos": round(time.monotonic() - inicio, 1), "tokens": tokens, "costo_usd": round(costo, 6),
        "stop_reason": ok[0].get("stop_reason") if ok else None, "registros": registros,
    }


def comparar_acta_texto(meta: MetadatosActa, texto_ocr: str, cfg_actual: AnthropicConfig, ids_candidatas: list[str]) -> dict:
    """La configuración actual + cada candidata, en paralelo, sobre el MISMO texto de acta."""
    configs = [(ID_ACTUAL, cfg_actual)]
    for cid in ids_candidatas:
        c = CONFIGS_CANDIDATAS[cid]
        configs.append((cid, replace(cfg_actual, model=c["modelo"], effort=c["esfuerzo"])))

    with ThreadPoolExecutor(max_workers=len(configs)) as pool:
        resultados = list(pool.map(lambda par: _extraer(meta, texto_ocr, par[1], par[0]), configs))

    actual = resultados[0]
    comparaciones = {r["id"]: comparar_specs(actual["spec"], r["spec"]) for r in resultados[1:]}
    return {"configuraciones": resultados, "comparaciones": comparaciones}
