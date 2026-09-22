"""Tablas oficiales CREG 038/2014 / NTC 5019 para dimensionar TC — puerto de Codigo.gs
líneas 2069-2114 y las funciones de cálculo asociadas (3886-3973).

Las tablas de reclasificación de medida (TABLA1_UMBRAL_BT, UMBRAL_INDIRECTA_KVA,
UMBRAL_RECLASIFICACION_EXCLUSIVO_KVA) ya viven en clasificador_medida.py — este módulo es
específico de TC (relación de transformación), un problema distinto.
"""

# Tabla 6 (NTC 5019 / CREG 038-2014) — relación TC para Semidirecta, por nivel BT y kVA.
TABLA6_TC_SEMIDIRECTA = {
    "120/208": [
        {"min": 28, "max": 43, "ratio": "100/5"}, {"min": 44, "max": 65, "ratio": "150/5"}, {"min": 66, "max": 86, "ratio": "200/5"},
        {"min": 87, "max": 129, "ratio": "300/5"}, {"min": 130, "max": 162, "ratio": "400/5"}, {"min": 163, "max": 194, "ratio": "500/5"},
        {"min": 195, "max": 259, "ratio": "600/5"}, {"min": 260, "max": 324, "ratio": "800/5"}, {"min": 325, "max": 389, "ratio": "1000/5"},
        {"min": 390, "max": 467, "ratio": "1200/5"}, {"min": 468, "max": 648, "ratio": "1600/5"},
    ],
    "127/220": [
        {"min": 30, "max": 45, "ratio": "100/5"}, {"min": 46, "max": 68, "ratio": "150/5"}, {"min": 69, "max": 91, "ratio": "200/5"},
        {"min": 92, "max": 137, "ratio": "300/5"}, {"min": 138, "max": 182, "ratio": "400/5"}, {"min": 183, "max": 228, "ratio": "500/5"},
        {"min": 229, "max": 274, "ratio": "600/5"}, {"min": 275, "max": 365, "ratio": "800/5"}, {"min": 366, "max": 457, "ratio": "1000/5"},
        {"min": 458, "max": 548, "ratio": "1200/5"}, {"min": 549, "max": 731, "ratio": "1600/5"},
    ],
    "254/440": [
        {"min": 60, "max": 91, "ratio": "100/5"}, {"min": 92, "max": 137, "ratio": "150/5"}, {"min": 138, "max": 183, "ratio": "200/5"},
        {"min": 184, "max": 274, "ratio": "300/5"}, {"min": 275, "max": 365, "ratio": "400/5"}, {"min": 366, "max": 457, "ratio": "500/5"},
        {"min": 458, "max": 548, "ratio": "600/5"}, {"min": 549, "max": 731, "ratio": "800/5"}, {"min": 732, "max": 914, "ratio": "1000/5"},
        {"min": 915, "max": 1097, "ratio": "1200/5"}, {"min": 1098, "max": 1463, "ratio": "1600/5"},
    ],
    "120/240": [
        {"min": 19, "max": 28, "ratio": "100/5"}, {"min": 29, "max": 43, "ratio": "150/5"}, {"min": 44, "max": 57, "ratio": "200/5"},
        {"min": 58, "max": 86, "ratio": "300/5"}, {"min": 87, "max": 108, "ratio": "400/5"}, {"min": 109, "max": 129, "ratio": "500/5"},
        {"min": 130, "max": 172, "ratio": "600/5"}, {"min": 173, "max": 216, "ratio": "800/5"}, {"min": 217, "max": 259, "ratio": "1000/5"},
        {"min": 260, "max": 311, "ratio": "1200/5"}, {"min": 312, "max": 438, "ratio": "1600/5"},
    ],
}

# Tabla 8 (NTC 5019 / CREG 038-2014) — relación TC para Indirecta, por nivel MT y kVA.
# NOTA del original: extraída por OCR del manual EBSA; la fila 20/5 de 34.5kV se reconstruyó
# por patrón (el OCR devolvió un valor inconsistente) — verificar contra el PDF fuente si algo
# no cuadra.
TABLA8_TC_INDIRECTA = {
    "13.2kV": [
        {"min": 91, "max": 137, "ratio": "5/5"}, {"min": 138, "max": 274, "ratio": "10/5"}, {"min": 275, "max": 411, "ratio": "15/5"},
        {"min": 412, "max": 503, "ratio": "20/5"}, {"min": 504, "max": 617, "ratio": "25/5"}, {"min": 618, "max": 823, "ratio": "30/5"},
        {"min": 824, "max": 1029, "ratio": "40/5"}, {"min": 1030, "max": 1234, "ratio": "50/5"}, {"min": 1235, "max": 1554, "ratio": "60/5"},
        {"min": 1555, "max": 1829, "ratio": "75/5"}, {"min": 1830, "max": 2743, "ratio": "100/5"}, {"min": 2744, "max": 4115, "ratio": "150/5"},
        {"min": 4116, "max": 5144, "ratio": "200/5"},
    ],
    "34.5kV": [
        {"min": 239, "max": 358, "ratio": "5/5"}, {"min": 359, "max": 717, "ratio": "10/5"}, {"min": 718, "max": 1075, "ratio": "15/5"},
        {"min": 1076, "max": 1314, "ratio": "20/5"}, {"min": 1315, "max": 1613, "ratio": "25/5"}, {"min": 1614, "max": 2151, "ratio": "30/5"},
        {"min": 2152, "max": 2689, "ratio": "40/5"}, {"min": 2690, "max": 3226, "ratio": "50/5"}, {"min": 3227, "max": 4063, "ratio": "60/5"},
        {"min": 4064, "max": 4781, "ratio": "75/5"}, {"min": 4782, "max": 7170, "ratio": "100/5"}, {"min": 7171, "max": 10756, "ratio": "150/5"},
        {"min": 10757, "max": 13345, "ratio": "200/5"},
    ],
}

# Relaciones normalizadas de TC (NTC 5019) — respaldo cuando el nivel MT no tiene tabla oficial
# propia (hoy solo 13.2kV y 34.5kV la tienen). Cualquier otro nivel MT real (ej. 11.4kV,
# típico de Afinia/Caribe) cae aquí.
RATIOS_TC_NORMALIZADOS = [5, 10, 15, 20, 25, 30, 40, 50, 60, 75, 100, 150, 200, 300, 400, 600, 800, 1000, 1200, 1600]

_NIVELES_MT_RECONOCIDOS = {"13.2kV", "34.5kV", "11.4kV"}


def buscar_en_tabla_tc(tabla: list[dict] | None, kva: float | None) -> str | None:
    if not tabla or kva is None:
        return None
    for fila in tabla:
        if fila["min"] <= kva <= fila["max"]:
            return fila["ratio"]
    if tabla and kva > tabla[-1]["max"]:
        return tabla[-1]["ratio"]
    return None


def calcular_ratio_tc_por_formula(kva: float | None, kv_nivel: float | None) -> str | None:
    """Ib = kVA / (kV × √3), redondeado hacia arriba al normalizado más cercano."""
    if kva is None or not kv_nivel:
        return None
    ib = (kva * 1000) / (kv_nivel * 1000 * 3**0.5)
    for r in RATIOS_TC_NORMALIZADOS:
        if r >= ib:
            return f"{r}/5"
    return f"{RATIOS_TC_NORMALIZADOS[-1]}/5"


def calcular_ratio_tc_por_corriente(amperios: float | None) -> str | None:
    """Redondea una corriente conocida (ej. totalizador de este cliente en compartido) al TC
    normalizado más cercano por arriba, sin pasar por kVA/tensión."""
    if amperios is None:
        return None
    for r in RATIOS_TC_NORMALIZADOS:
        if r >= amperios:
            return f"{r}/5"
    return f"{RATIOS_TC_NORMALIZADOS[-1]}/5"


def kv_nominal_desde_nivel(nivel: str | None) -> float | None:
    import re

    m = re.search(r"(\d+(?:\.\d+)?)\s*kv", (nivel or "").lower())
    return float(m.group(1)) if m else None


def etiqueta_nivel_para_tc(tipo_medida: str | None, nivel: str | None) -> str:
    es_mt_reconocido = nivel in _NIVELES_MT_RECONOCIDOS
    if tipo_medida != "semidirecta" and not es_mt_reconocido:
        extra = f' ("{nivel}" es un nivel BT, no aplica al cálculo MT)' if nivel else ""
        return f"nivel MT no determinado{extra} — se asumió 13.2kV de referencia"
    return nivel or "?"


def calcular_relacion_tc_esperada_por_capacidad(
    tipo_medida: str, nivel: str | None, kva: float | None, nivel_tiene_tabla_oficial: bool
) -> dict:
    """Devuelve {"relacion": str|None, "por_formula": bool}."""
    if tipo_medida == "semidirecta":
        return {"relacion": buscar_en_tabla_tc(TABLA6_TC_SEMIDIRECTA.get(nivel), kva), "por_formula": False}
    if nivel_tiene_tabla_oficial:
        por_tabla = buscar_en_tabla_tc(TABLA8_TC_INDIRECTA.get(nivel), kva)
        if por_tabla:
            return {"relacion": por_tabla, "por_formula": False}
        # Tabla 8 oficial no cubre capacidades por debajo de su mínimo — se cae a la fórmula.
    relacion = calcular_ratio_tc_por_formula(kva, kv_nominal_desde_nivel(nivel) or 13.2)
    return {"relacion": relacion, "por_formula": bool(relacion)}
