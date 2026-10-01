"""Entrypoint único que Vercel usa para servir todos los endpoints.

Vercel detecta Flask como "framework" cuando ve varios `app = Flask(__name__)`
en /api/*.py, y en ese modo espera UNA sola app (ver [tool.vercel] en
pyproject.toml). Por eso cada archivo de api/ expone un Blueprint en vez de
su propia app, y este archivo los registra todos aquí.
"""

from pathlib import Path

from flask import Flask, Response

from api.actas_start import bp as actas_start_bp
from api.actas_status import bp as actas_status_bp
from api.actas_step import bp as actas_step_bp
from api.analizar_alcance import bp as analizar_alcance_bp
from api.consumo_resumen import bp as consumo_resumen_bp
from api.cron_reintentos import bp as cron_reintentos_bp
from api.equipos_resumen import bp as equipos_resumen_bp
from api.guardar_alcance import bp as guardar_alcance_bp
from api.guardar_opex import bp as guardar_opex_bp
from api.lote_start import bp as lote_start_bp
from api.lote_status import bp as lote_status_bp
from api.lote_step import bp as lote_step_bp
from api.opex_resolver import bp as opex_resolver_bp

app = Flask(__name__)
app.register_blueprint(actas_start_bp)
app.register_blueprint(actas_step_bp)
app.register_blueprint(actas_status_bp)
app.register_blueprint(opex_resolver_bp)
app.register_blueprint(cron_reintentos_bp)
app.register_blueprint(analizar_alcance_bp)
app.register_blueprint(guardar_alcance_bp)
app.register_blueprint(guardar_opex_bp)
app.register_blueprint(lote_start_bp)
app.register_blueprint(lote_step_bp)
app.register_blueprint(lote_status_bp)
app.register_blueprint(equipos_resumen_bp)
app.register_blueprint(consumo_resumen_bp)

_FRONTEND_HTML = (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/")
def frontend():
    """Frontend de "Alcance Quinquenal" — portado de Index.html (Apps Script). Solo esta
    pestaña tiene backend Python: las otras 3 del original (Alcances/HV/Diagrama Unifilar)
    no se migraron todavía."""
    return Response(_FRONTEND_HTML, mimetype="text/html")
