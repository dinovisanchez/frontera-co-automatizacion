"""Regla de selección: UNA acta por CO — la INFR exitosa; si no hay, la más reciente exitosa."""

import pytest

from core.services import alcance_combiner as ac
from core.services.alcance_combiner import motivo_sin_acta, preparar_actas_pendientes, seleccionar_acta, seleccionar_actas_ordenadas

OK = "Cierre Exitoso"


def fila(tipo, fecha, estado=OK, url=None, **extra):
    return {"bia_code": "CO1", "service_type_id": tipo, "fecha_visita": fecha, "act_pdf_url": url or f"https://x/{tipo}-{fecha}.pdf", "estado_visita": estado, **extra}


def test_prefiere_la_infr_exitosa_aunque_haya_actas_mas_recientes():
    filas = [fila("VIPE", "2026-05-01"), fila("INFR", "2025-01-01"), fila("NOTE", "2026-03-01")]

    assert seleccionar_acta(filas)["service_type_id"] == "INFR"


def test_con_varias_infr_exitosas_toma_la_mas_reciente():
    filas = [fila("INFR", "2025-01-01"), fila("INFR", "2026-02-01"), fila("INFR", "2024-01-01")]

    assert seleccionar_acta(filas)["fecha_visita"] == "2026-02-01"


def test_una_infr_que_no_fue_exitosa_se_ignora():
    filas = [fila("INFR", "2026-06-01", estado="Cierre Fallido"), fila("VIPE", "2026-01-01"), fila("NOTE", "2026-03-01")]

    elegida = seleccionar_acta(filas)

    assert (elegida["service_type_id"], elegida["fecha_visita"]) == ("NOTE", "2026-03-01")  # la exitosa más reciente


def test_sin_infr_toma_la_exitosa_mas_reciente_de_cualquier_tipo():
    filas = [fila("VIPE", "2026-01-01"), fila("INST", "2026-04-01"), fila("NOTE", "2026-02-01"), fila("VIPE", "2026-09-01", estado="Cierre Fallido")]

    assert seleccionar_acta(filas)["service_type_id"] == "INST"


def test_ninguna_exitosa_no_hay_acta():
    filas = [fila("INFR", "2026-01-01", estado="Cierre Fallido"), fila("VIPE", "2026-02-01", estado="")]

    assert seleccionar_acta(filas) is None
    assert preparar_actas_pendientes("CO1", filas) == []


def test_el_estado_se_compara_sin_importar_mayusculas_acentos_ni_espacios():
    for estado in ("cierre exitoso", "CIERRE EXITOSO", "  Cierre   Exitoso ", "Cierre Éxitoso"):
        assert seleccionar_acta([fila("VIPE", "2026-01-01", estado=estado)]) is not None, estado
    for estado in ("Exitoso", "Cierre No Exitoso", None):
        assert seleccionar_acta([fila("VIPE", "2026-01-01", estado=estado)]) is None, estado


def test_solo_cuentan_los_tipos_de_acta_con_pdf():
    filas = [fila("XXXX", "2026-09-01"), {**fila("VIPE", "2026-08-01"), "act_pdf_url": ""}, fila("NOTE", "2026-01-01")]  # tipo ajeno / sin PDF

    assert seleccionar_acta(filas)["service_type_id"] == "NOTE"


def test_la_cola_va_en_orden_de_preferencia_infr_primero_y_luego_por_fecha():
    filas = [
        fila("VIPE", "2026-09-01"), fila("INFR", "2024-01-01"), fila("NOTE", "2026-03-01"),
        fila("INFR", "2025-06-01"), fila("INFR", "2026-05-01", estado="Cierre Fallido"),  # esta no cuenta: no fue exitosa
    ]

    cola = preparar_actas_pendientes("CO1", filas)

    assert [(a["service_type_id"], a["fecha_visita"]) for a in cola] == [("INFR", "2025-06-01"), ("INFR", "2024-01-01"), ("VIPE", "2026-09-01")]


def test_la_cola_tiene_un_tope_de_candidatas_y_no_repite_urls():
    filas = [fila("INFR", f"2026-0{m}-01") for m in range(1, 6)] + [fila("VIPE", "2026-09-01", url="https://x/misma.pdf"), fila("NOTE", "2026-10-01", url="https://x/misma.pdf")]

    cola = preparar_actas_pendientes("CO1", filas)

    assert len(cola) == ac.MAX_ACTAS_A_ESCANEAR == 3
    urls = [a["act_pdf_url"] for a in seleccionar_actas_ordenadas(filas)]
    assert len(urls) == len(set(urls))
    assert [a["service_type_id"] for a in seleccionar_actas_ordenadas(filas)].count("NOTE") == 1  # la fila más reciente de la URL repetida


def test_la_primera_candidata_es_la_acta_que_se_lee():
    filas = [fila("VIPE", "2026-01-01"), fila("INFR", "2025-01-01"), fila("NOTE", "2026-03-01")]

    assert preparar_actas_pendientes("CO1", filas)[0] == seleccionar_acta(filas)
    assert seleccionar_acta(filas)["service_type_id"] == "INFR"


def test_si_la_columna_no_existe_falla_con_el_motivo_en_vez_de_dejar_el_co_sin_actas():
    filas = [{"bia_code": "CO1", "service_type_id": "INFR", "fecha_visita": "2026-01-01", "act_pdf_url": "https://x/a.pdf"}]

    with pytest.raises(RuntimeError, match='no trae la columna "estado_visita"'):
        seleccionar_acta(filas)


def test_co_sin_filas_de_acta_no_dispara_el_error_de_columna():
    assert seleccionar_acta([]) is None
    assert seleccionar_acta([{"bia_code": "CO1", "service_type_id": "XXXX", "act_pdf_url": "https://x/a.pdf"}]) is None


def test_motivo_cuando_no_hay_ninguna_acta():
    assert motivo_sin_acta("CO1", []).startswith('"CO1" no tiene ninguna acta')


def test_motivo_cuando_hay_actas_pero_ninguna_exitosa_muestra_los_estados_reales():
    filas = [fila("INFR", "2026-01-01", estado="Cierre Fallido"), fila("VIPE", "2026-02-01", estado="Reprogramada"), fila("NOTE", "2026-03-01", estado=None)]

    motivo = motivo_sin_acta("CO1", filas)

    assert motivo.startswith('"CO1" no tiene ninguna acta')  # el frontend reconoce este prefijo para pasar a modo "sin actas"
    assert "3 fila(s)" in motivo and "Cierre Fallido" in motivo and "Reprogramada" in motivo and "(vacío)" in motivo


# ------------------------------------------------- el flujo de producción lee UNA sola acta

JSON_PARCIAL = '```json\n{"tipo_medida_actual": "semidirecta", "nivel_tension": 1, "capacidad_instalada_kva": 75}\n```'  # sin relacion_tc
JSON_VACIO = '```json\n{"tipo_medida_actual": null}\n```'


def _entorno(monkeypatch, respuestas, descargas=None, ocr_ok=True):
    """Claude simulado (`respuestas` por llamada, en orden), descargas por URL y OCR. Devuelve la lista de
    textos enviados a Claude y la de URLs descargadas."""
    from config.settings import AnthropicConfig
    from core.data_sources.llm_client import AnthropicClient
    from core.services.acta_downloader import ResultadoDescarga
    from core.services.acta_ocr import OcrResultado

    enviados, descargadas, cola = [], [], list(respuestas)

    class LlmFalso(AnthropicClient):
        def __init__(self):
            super().__init__(AnthropicConfig(api_key="fake"))

        def enviar(self, body):
            enviados.append(body["messages"][0]["content"][0]["text"])
            return cola.pop(0)

    def descargar(url):
        descargadas.append(url)
        return (descargas or {}).get(url) or ResultadoDescarga(ok=True, bytes_pdf=b"%PDF")

    monkeypatch.setattr(ac.acta_downloader, "descargar_pdf_acta", descargar)
    monkeypatch.setattr(ac.acta_ocr, "ocr_texto_desde_bytes", lambda b, cfg: OcrResultado(ok=ocr_ok, texto="texto" if ocr_ok else None, motivo_fallo=None if ocr_ok else "OCR caído"))
    return LlmFalso(), enviados, descargadas


def _job(filas):
    from core.services.job_store import EstadoJob

    return EstadoJob(co="CO1", estado="en_progreso", actas_pendientes=preparar_actas_pendientes("CO1", filas))


def test_el_job_lee_una_sola_acta_y_termina_aunque_falten_campos(monkeypatch):
    """Con varias actas disponibles (la vieja traería lo que falta) el job lee SOLO la INFR exitosa,
    termina en ese paso y deja vacío lo que esa acta no trae: así lo pidió Dinovi (2026-10-01)."""
    llm, enviados, descargadas = _entorno(monkeypatch, [JSON_PARCIAL])
    estado = _job([fila("VIPE", "2026-05-01"), fila("INFR", "2025-06-01"), fila("NOTE", "2024-01-01")])

    paso = ac.procesar_siguiente_acta(estado, llm, drive_cfg=None, sheets=None)

    assert paso.completo is True and len(enviados) == 1  # UNA llamada a Claude, no hasta 5
    assert len(descargadas) == 1 and "INFR" in enviados[0]
    assert [a["tipo"] for a in paso.estado.actas_usadas] == ["INFR"]
    assert paso.estado.spec_combinado.get("relacion_tc") is None  # lo que esa acta no trae queda vacío
    assert paso.estado.actas_pendientes == []  # las de respaldo no se tocan


def test_si_la_acta_elegida_no_se_puede_descargar_se_prueba_la_siguiente(monkeypatch):
    from core.services.acta_downloader import ResultadoDescarga

    invalido = ResultadoDescarga(ok=False, motivo_fallo="no es un PDF válido")
    llm, enviados, descargadas = _entorno(monkeypatch, [JSON_PARCIAL], descargas={"https://x/INFR-2025-06-01.pdf": invalido})
    estado = _job([fila("INFR", "2025-06-01"), fila("VIPE", "2026-05-01"), fila("NOTE", "2024-01-01")])

    paso1 = ac.procesar_siguiente_acta(estado, llm, drive_cfg=None, sheets=None)
    assert paso1.completo is False and enviados == []  # la falla fue técnica: ni siquiera se llamó a Claude

    paso2 = ac.procesar_siguiente_acta(estado, llm, drive_cfg=None, sheets=None)
    assert paso2.completo is True and len(enviados) == 1
    assert descargadas == ["https://x/INFR-2025-06-01.pdf", "https://x/VIPE-2026-05-01.pdf"]  # INFR falló → la siguiente en preferencia
    assert [a["tipo"] for a in estado.actas_usadas] == ["VIPE"] and "no es un PDF válido" in " ".join(estado.observaciones)
    assert estado.actas_pendientes == []  # la tercera candidata no se lee


def test_si_el_ocr_falla_y_no_hay_modo_imagen_se_prueba_la_siguiente(monkeypatch):
    llm, enviados, _ = _entorno(monkeypatch, [], ocr_ok=False)
    estado = _job([fila("INFR", "2025-06-01"), fila("VIPE", "2026-05-01")])

    paso = ac.procesar_siguiente_acta(estado, llm, drive_cfg=None, sheets=None, permitir_modo_imagen=False)

    assert paso.completo is False and len(estado.actas_pendientes) == 1 and enviados == []


def test_una_acta_sin_ningun_dato_util_se_trata_como_falla_y_se_prueba_la_siguiente(monkeypatch):
    llm, enviados, _ = _entorno(monkeypatch, [JSON_VACIO, JSON_PARCIAL])
    estado = _job([fila("INFR", "2025-06-01"), fila("VIPE", "2026-05-01")])

    paso1 = ac.procesar_siguiente_acta(estado, llm, drive_cfg=None, sheets=None)
    assert paso1.completo is False and estado.actas_usadas == []  # la vacía NO se registra como acta usada
    assert "ningún dato útil" in estado.observaciones[-1]

    paso2 = ac.procesar_siguiente_acta(estado, llm, drive_cfg=None, sheets=None)
    assert paso2.completo is True and [a["tipo"] for a in estado.actas_usadas] == ["VIPE"]


def test_si_ninguna_candidata_se_puede_leer_el_job_termina_sin_datos(monkeypatch):
    from core.services.acta_downloader import ResultadoDescarga

    mal = ResultadoDescarga(ok=False, motivo_fallo="57MB, muy grande incluso para OCR")
    llm, enviados, _ = _entorno(monkeypatch, [], descargas={"https://x/INFR-2025-06-01.pdf": mal, "https://x/VIPE-2026-05-01.pdf": mal})
    estado = _job([fila("INFR", "2025-06-01"), fila("VIPE", "2026-05-01")])

    assert ac.procesar_siguiente_acta(estado, llm, None, None).completo is False
    paso = ac.procesar_siguiente_acta(estado, llm, None, None)

    assert paso.completo is True and estado.spec_combinado == {} and estado.actas_usadas == [] and enviados == []
    assert len(estado.observaciones) == 2
