"""guardar_filas_opex con una hoja falsa — sin Google Sheets real. Verifica dónde se escriben el
Carro canasta (columna H) y el Descargo (columna I), y que la fila siguiente no herede el valor
fijo por la copia A:M."""

from core.services.guardar_opex import guardar_filas_opex

MONTAJE_TCS_EXT = "Montaje  TCs MT (1–3) – exterior"
MONTAJE_TPS_EXT = "Montaje  TPs MT (1–3) – exterior"
MONTAJE_TCS_INT = "Montaje  TCs MT (1–3) – interior"
INSTALACION = "Instalación indirecta exterior: medidor + BP + módem + toma 110V (sin Montaje TCs/TPs MT)"
FORMULA_H = "=IFERROR(G2*0;0)"
FORMULA_I = "=IFERROR(VLOOKUP(C2;Q:R;2;0);0)"

CARRO = 4_500_000
DESCARGO = 8_000_000
DESCARGO_ENEL = 12_000_000


FORMULA_K = "=IFERROR(VLOOKUP(B2;Z:AA;2;0);0)"


class HojaFalsa:
    url = "https://docs.google.com/spreadsheets/d/x/edit#gid=1"

    def __init__(self, col_a: list, col_h: list, col_i: list | None = None, col_k: list | None = None, ciudades: dict | None = None):
        self.col_a, self.col_h = col_a, col_h
        # Por defecto la columna I tiene su fórmula en todas las filas de datos.
        self.col_i = col_i if col_i is not None else ["Descargo"] + [FORMULA_I] * (len(col_a) - 1)
        # K (Desplazamiento) también, salvo que el test diga otra cosa.
        self.col_k = col_k if col_k is not None else ["Desplazamiento"] + [FORMULA_K] * (len(col_a) - 1)
        # La "fórmula" de B: la ciudad que la hoja calcula para el CO escrito en A de esa fila (por defecto Bogotá).
        self.ciudades = ciudades if ciudades is not None else {}
        self._co_en_fila: dict[int, str] = {}
        self.escrituras: list[tuple[str, list]] = []  # (rango, valores)

    def col_values(self, col, value_render_option=None):
        assert col in (1, 8, 9, 11)
        if col in (8, 9, 11):
            assert value_render_option == "FORMULA"  # hay que ver la fórmula, no el valor calculado
        return list({1: self.col_a, 8: self.col_h, 9: self.col_i, 11: self.col_k}[col])

    def _registrar(self, rango, valores):
        self.escrituras.append((rango, valores))
        if rango.startswith("A") and ":" not in rango:  # aprende qué CO quedó en cada fila para "calcular" B
            self._co_en_fila[int(rango[1:])] = valores[0][0]

    def update(self, *args, range_name=None, **kwargs):
        if isinstance(args[0], str):  # estilo viejo: update("A5:E5", valores)
            rango, valores = args[0], args[1]
        else:
            valores, rango = args[0], range_name
        self._registrar(rango, valores)

    def batch_update(self, data, **kwargs):
        for d in data:
            self._registrar(d["range"], d["values"])

    def get(self, rango):
        assert rango.startswith("B")
        co = self._co_en_fila.get(int(rango[1:]))
        ciudad = self.ciudades.get(co, "Bogotá")
        return [[ciudad]] if ciudad is not None else []


class SheetsFalso:
    def __init__(self, hoja):
        self.hoja = hoja
        self.copias: list[dict] = []

    def hoja_por_nombre(self, nombre):
        assert nombre == "OPEX"
        return self.hoja

    def copiar_fila(self, hoja, fila_origen, fila_destino, num_columnas, col_inicio=0):
        self.copias.append({"origen": fila_origen, "destino": fila_destino, "num_columnas": num_columnas, "col_inicio": col_inicio})


def _hoja_con_un_co_previo(h_ultima_fila=FORMULA_H, i_ultima_fila=FORMULA_I):
    # Fila 1 = encabezado; filas 2-3 = un CO anterior. H e I tienen fórmula (salvo lo que se indique).
    return HojaFalsa(
        col_a=["CO", "CO0000000001", "CO0000000001"],
        col_h=["Carro canasta", FORMULA_H, h_ultima_fila],
        col_i=["Descargo", FORMULA_I, i_ultima_fila],
    )


def _escrituras_col(hoja, letra):
    return [(r, v) for r, v in hoja.escrituras if r.startswith(letra) and not r.startswith("A")]


def _escrituras_rango(hoja, letra):
    return [(r, v) for r, v in hoja.escrituras if r.startswith(letra)]


def _restauraciones(sheets, col_inicio):
    return [(c["origen"], c["destino"]) for c in sheets.copias if c["col_inicio"] == col_inicio]


def _filas(*maniobras):
    return [{"maniobra": m, "cantidad": 1} for m in maniobras]


# ------------------------------------------------------------------ Carro canasta (H)

def test_sin_montaje_no_toca_h_ni_i():
    hoja = _hoja_con_un_co_previo()
    sheets = SheetsFalso(hoja)

    res = guardar_filas_opex(sheets, "CO0100002908", "AFINIA", _filas(INSTALACION, "Cambio de DPS (unidad)"))

    assert res["carro_canasta"] is None and res["descargo"] is None
    assert _escrituras_col(hoja, "H") == [] and _escrituras_col(hoja, "I") == []
    assert [c["col_inicio"] for c in sheets.copias] == [0, 0]  # solo las copias A:M de siempre
    assert [(c["origen"], c["destino"]) for c in sheets.copias] == [(3, 4), (4, 5)]


def test_montaje_exterior_escribe_el_carro_canasta_en_h_de_esa_fila():
    hoja = _hoja_con_un_co_previo()
    sheets = SheetsFalso(hoja)

    res = guardar_filas_opex(sheets, "CO0100002908", "AFINIA", _filas(INSTALACION, MONTAJE_TCS_EXT))

    # Filas nuevas: 4 (instalación) y 5 (montaje). Ambos valores fijos van SOLO en la 5.
    assert _escrituras_col(hoja, "H") == [("H5", [[CARRO]])]
    assert res["carro_canasta"] == {"fila": 5, "maniobra": MONTAJE_TCS_EXT, "valor": CARRO}
    assert res["guardadas"][1] == ["CO0100002908", "", "AFINIA", MONTAJE_TCS_EXT, 1]


def test_montaje_interior_no_lleva_carro_canasta_pero_si_descargo():
    hoja = _hoja_con_un_co_previo()
    sheets = SheetsFalso(hoja)

    res = guardar_filas_opex(sheets, "CO0100002908", "AFINIA", _filas(MONTAJE_TCS_INT))

    assert res["carro_canasta"] is None and _escrituras_col(hoja, "H") == []
    assert _escrituras_col(hoja, "I") == [("I4", [[DESCARGO]])]
    assert res["descargo"] == {"fila": 4, "maniobra": MONTAJE_TCS_INT, "valor": DESCARGO}


# ------------------------------------------------------------------ Descargo (I)

def test_descargo_es_de_8_millones_para_cualquier_or_que_no_sea_enel():
    for operador in ("AFINIA", "EMCALI", "AIRE", "ESSA", "CELSIA VALLE", "ELECTROHUILA", "OTROS_OR"):
        hoja = _hoja_con_un_co_previo()
        res = guardar_filas_opex(SheetsFalso(hoja), "CO0100002908", operador, _filas(MONTAJE_TCS_INT))
        assert res["descargo"]["valor"] == DESCARGO, operador
        assert _escrituras_col(hoja, "I") == [("I4", [[DESCARGO]])], operador


def test_descargo_es_de_12_millones_para_enel():
    hoja = _hoja_con_un_co_previo()

    res = guardar_filas_opex(SheetsFalso(hoja), "CO0100002908", "ENEL", _filas(MONTAJE_TCS_EXT))

    assert res["descargo"] == {"fila": 4, "maniobra": MONTAJE_TCS_EXT, "valor": DESCARGO_ENEL}
    assert _escrituras_col(hoja, "I") == [("I4", [[DESCARGO_ENEL]])]
    assert res["carro_canasta"]["valor"] == CARRO  # el carro canasta NO cambia con el OR


def test_descargo_una_sola_vez_por_co_aunque_haya_montaje_de_tc_y_de_tp():
    hoja = _hoja_con_un_co_previo()
    sheets = SheetsFalso(hoja)

    res = guardar_filas_opex(sheets, "CO0100002908", "AFINIA", _filas(MONTAJE_TCS_EXT, MONTAJE_TPS_EXT))

    assert _escrituras_col(hoja, "I") == [("I4", [[DESCARGO]])]
    assert res["descargo"]["fila"] == 4


def test_descargo_va_en_el_primer_montaje_aunque_el_carro_canasta_vaya_en_otro():
    # Primero un montaje INTERIOR (solo descargo) y después uno EXTERIOR (carro canasta; el descargo
    # ya se puso en la fila anterior). Cada columna elige su propia fila.
    hoja = _hoja_con_un_co_previo()

    res = guardar_filas_opex(SheetsFalso(hoja), "CO0100002908", "AFINIA", _filas(MONTAJE_TCS_INT, MONTAJE_TPS_EXT))

    assert res["descargo"]["fila"] == 4 and res["carro_canasta"]["fila"] == 5
    assert _escrituras_col(hoja, "I") == [("I4", [[DESCARGO]])]
    assert _escrituras_col(hoja, "H") == [("H5", [[CARRO]])]


# ------------------------------------------------------------------ Herencia de la fila anterior

def test_tc_y_tp_exterior_las_filas_siguientes_recuperan_las_formulas():
    hoja = _hoja_con_un_co_previo()
    sheets = SheetsFalso(hoja)

    guardar_filas_opex(sheets, "CO0100002908", "AFINIA", _filas(MONTAJE_TCS_EXT, MONTAJE_TPS_EXT))

    assert _escrituras_col(hoja, "H") == [("H4", [[CARRO]])]  # un solo carro canasta por CO
    # La fila 5 se copió desde la 4 (que ya tiene los valores fijos): se le restaura la fórmula de
    # cada columna desde la última fila con fórmula (la 3), copiando SOLO esa columna.
    assert _restauraciones(sheets, 7) == [(3, 5)]  # H = índices 7 a 8
    assert _restauraciones(sheets, 8) == [(3, 5)]  # I = índices 8 a 9
    assert {"origen": 3, "destino": 5, "num_columnas": 8, "col_inicio": 7} in sheets.copias
    assert {"origen": 3, "destino": 5, "num_columnas": 9, "col_inicio": 8} in sheets.copias


def test_el_co_siguiente_no_hereda_los_valores_fijos_del_co_anterior():
    # El CO previo terminó con carro canasta Y descargo fijos en su última fila (3); las fórmulas
    # siguen en la 2.
    hoja = _hoja_con_un_co_previo(h_ultima_fila=CARRO, i_ultima_fila=DESCARGO)
    sheets = SheetsFalso(hoja)

    res = guardar_filas_opex(sheets, "CO0100002908", "AFINIA", _filas(INSTALACION, "Cambio de DPS (unidad)"))

    assert res["carro_canasta"] is None and res["descargo"] is None
    assert _escrituras_col(hoja, "H") == [] and _escrituras_col(hoja, "I") == []
    # La fila 4 (copiada de la 3, con los valores fijos) recupera cada fórmula desde la fila 2. La
    # fila 5 se copia de la 4, que ya las tiene: no hace falta restaurar de nuevo.
    assert _restauraciones(sheets, 7) == [(2, 4)]
    assert _restauraciones(sheets, 8) == [(2, 4)]


def test_solo_se_restaura_la_columna_que_heredo_un_valor_fijo():
    # Solo el descargo quedó fijo en el CO anterior (p. ej. montaje interior): H no se toca.
    hoja = _hoja_con_un_co_previo(i_ultima_fila=DESCARGO)
    sheets = SheetsFalso(hoja)

    guardar_filas_opex(sheets, "CO0100002908", "AFINIA", _filas(INSTALACION))

    assert _restauraciones(sheets, 7) == []
    assert _restauraciones(sheets, 8) == [(2, 4)]


def test_sin_ninguna_formula_se_limpia_el_valor_heredado():
    hoja = HojaFalsa(
        col_a=["CO", "CO0000000001"], col_h=["Carro canasta", CARRO], col_i=["Descargo", DESCARGO],
    )
    sheets = SheetsFalso(hoja)

    guardar_filas_opex(sheets, "CO0100002908", "AFINIA", _filas(INSTALACION))

    assert _escrituras_col(hoja, "H") == [("H3", [[""]])]
    assert _escrituras_col(hoja, "I") == [("I3", [[""]])]
    assert all(c["col_inicio"] == 0 for c in sheets.copias)


def test_celda_vacia_en_la_fila_origen_no_se_toca():
    # Si la H/I de la fila anterior está vacía (no es un valor fijo) no hay nada que restaurar.
    hoja = HojaFalsa(
        col_a=["CO", "CO0000000001", "CO0000000001"],
        col_h=["Carro canasta", FORMULA_H, ""], col_i=["Descargo", FORMULA_I, ""],
    )
    sheets = SheetsFalso(hoja)

    guardar_filas_opex(sheets, "CO0100002908", "AFINIA", _filas(INSTALACION))

    assert _escrituras_col(hoja, "H") == [] and _escrituras_col(hoja, "I") == []
    assert [c["col_inicio"] for c in sheets.copias] == [0]


# ------------------------------------------------------------------ Desplazamiento (K) — un precio por ciudad

def test_b_ya_no_se_escribe_la_hoja_la_calcula_con_su_formula():
    hoja = _hoja_con_un_co_previo()

    guardar_filas_opex(SheetsFalso(hoja), "CO0100002908", "AFINIA", _filas(INSTALACION))

    assert _escrituras_rango(hoja, "B") == []  # antes se escribía "" y se borraba la fórmula de la ciudad
    assert _escrituras_rango(hoja, "A") == [("A4", [["CO0100002908"]])]
    assert _escrituras_rango(hoja, "C") == [("C4:E4", [["AFINIA", INSTALACION, 1]])]


def test_el_primer_co_de_una_ciudad_deja_el_precio_en_su_primera_fila_y_el_resto_de_filas_en_blanco():
    hoja = _hoja_con_un_co_previo()
    sheets = SheetsFalso(hoja)

    res = guardar_filas_opex(sheets, "CO0100002908", "AFINIA", _filas(INSTALACION, "Cambio de DPS (unidad)", "Otra maniobra"))

    # La fila 4 conserva la fórmula heredada; la 5 se limpia y la 6 (que se copia de la 5) ya hereda K vacía.
    assert _escrituras_rango(hoja, "K") == [("K5", [[""]])]
    assert res["desplazamiento"] == {"ciudad": "Bogotá", "aplicado": True, "fila": 4, "alerta": None}
    assert res["ciudades_con_desplazamiento"] == ["bogota"]


def test_un_co_de_una_ciudad_ya_cobrada_en_el_mismo_guardado_queda_sin_precio():
    # El CO anterior de esta tanda (Bogotá) terminó con K vacía en sus filas 4-5: la 5 es la última con datos.
    hoja = HojaFalsa(
        col_a=["CO", "CO0000000001", "CO0000000001", "CO0100000001", "CO0100000001"], col_h=["Carro canasta"] + [FORMULA_H] * 4,
        col_k=["Desplazamiento", FORMULA_K, FORMULA_K, FORMULA_K, ""],
    )
    sheets = SheetsFalso(hoja)

    res = guardar_filas_opex(sheets, "CO0100000002", "AFINIA", _filas(INSTALACION, "Cambio de DPS (unidad)"), ciudades_con_desplazamiento=["bogota"])

    assert res["desplazamiento"] == {"ciudad": "Bogotá", "aplicado": False, "fila": None, "alerta": None}
    assert _escrituras_rango(hoja, "K") == []  # la fila 5 ya tenía K vacía y se copia hacia abajo: no hay nada que borrar
    assert _restauraciones(sheets, 10) == []   # y tampoco se recupera la fórmula
    assert res["ciudades_con_desplazamiento"] == ["bogota"]


def test_una_ciudad_ya_cobrada_borra_la_k_heredada_de_la_fila_anterior():
    hoja = _hoja_con_un_co_previo()  # la última fila con datos (3) SÍ tiene fórmula en K

    res = guardar_filas_opex(SheetsFalso(hoja), "CO0100002908", "AFINIA", _filas(INSTALACION, "Otra maniobra"), ciudades_con_desplazamiento=["BOGOTA "])

    assert res["desplazamiento"]["aplicado"] is False and res["desplazamiento"]["fila"] is None
    assert _escrituras_rango(hoja, "K") == [("K4", [[""]])]  # solo la primera fila (la 5 hereda la K vacía de la 4)


def test_una_ciudad_nueva_recupera_la_formula_de_k_si_la_fila_anterior_quedo_en_blanco():
    hoja = HojaFalsa(
        col_a=["CO", "CO0000000001", "CO0100000001"], col_h=["Carro canasta"] + [FORMULA_H] * 2,
        col_k=["Desplazamiento", FORMULA_K, ""], ciudades={"CO0100000002": "Medellín"},
    )
    sheets = SheetsFalso(hoja)

    res = guardar_filas_opex(sheets, "CO0100000002", "EPM", _filas(INSTALACION), ciudades_con_desplazamiento=["bogota"])

    assert res["desplazamiento"] == {"ciudad": "Medellín", "aplicado": True, "fila": 4, "alerta": None}
    assert {"origen": 2, "destino": 4, "num_columnas": 11, "col_inicio": 10} in sheets.copias  # solo la columna K
    assert res["ciudades_con_desplazamiento"] == ["bogota", "medellin"]


def test_la_ciudad_se_compara_sin_importar_mayusculas_acentos_ni_espacios():
    from core.services.guardar_opex import clave_ciudad

    assert clave_ciudad("  BOGOTÁ  D.C.") == clave_ciudad("bogota d.c.") == "bogota d.c."
    assert clave_ciudad("#N/A") == "" and clave_ciudad(None) == "" and clave_ciudad("   ") == ""


def test_si_la_hoja_no_da_la_ciudad_no_se_toca_k_y_se_avisa():
    for ciudad in (None, "#N/A"):
        hoja = _hoja_con_un_co_previo()
        hoja.ciudades = {"CO0100002908": ciudad}

        res = guardar_filas_opex(SheetsFalso(hoja), "CO0100002908", "AFINIA", _filas(INSTALACION, "Otra maniobra"))

        assert _escrituras_rango(hoja, "K") == [], ciudad
        assert res["desplazamiento"]["aplicado"] is None and "ciudad" in res["desplazamiento"]["alerta"]
        assert res["ciudades_con_desplazamiento"] == []


def test_si_k_aun_no_tiene_formulas_no_se_hace_nada_con_el_desplazamiento():
    hoja = HojaFalsa(col_a=["CO", "CO0000000001"], col_h=["Carro canasta", FORMULA_H], col_k=["Desplazamiento", ""])
    sheets = SheetsFalso(hoja)

    res = guardar_filas_opex(sheets, "CO0100002908", "AFINIA", _filas(INSTALACION, "Otra maniobra"))

    assert res["desplazamiento"] is None and _escrituras_rango(hoja, "K") == []
    assert all(c["col_inicio"] != 10 for c in sheets.copias)


def test_el_endpoint_pasa_las_ciudades_ya_cobradas_y_devuelve_la_lista_actualizada(monkeypatch):
    from api import guardar_opex as api_guardar
    from api.index import app

    hoja = _hoja_con_un_co_previo()
    deps = type("Deps", (), {"sheets": SheetsFalso(hoja)})()
    monkeypatch.setattr(api_guardar, "construir_dependencias", lambda requiere_metabase=False: deps)

    resp = app.test_client().post("/api/guardar_opex", json={
        "co": "CO0100002908", "operador": "AFINIA", "filas": [{"maniobra": INSTALACION, "cantidad": 1}],
        "ciudades_con_desplazamiento": ["medellin", 5, None],  # lo que no sea texto se ignora
    })

    cuerpo = resp.get_json()
    assert resp.status_code == 200
    assert cuerpo["desplazamiento"]["aplicado"] is True and cuerpo["ciudadesConDesplazamiento"] == ["bogota", "medellin"]
