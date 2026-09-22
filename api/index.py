"""Entrypoint único que Vercel usa para servir todos los endpoints.

Vercel detecta Flask como "framework" cuando ve varios `app = Flask(__name__)`
en /api/*.py, y en ese modo espera UNA sola app (ver [tool.vercel] en
pyproject.toml). Por eso cada archivo de api/ expone un Blueprint en vez de
su propia app, y este archivo los registra todos aquí.
"""

from flask import Flask, jsonify

from api.actas_start import bp as actas_start_bp
from api.actas_status import bp as actas_status_bp
from api.actas_step import bp as actas_step_bp
from api.analizar_alcance import bp as analizar_alcance_bp
from api.cron_reintentos import bp as cron_reintentos_bp
from api.opex_resolver import bp as opex_resolver_bp

app = Flask(__name__)
app.register_blueprint(actas_start_bp)
app.register_blueprint(actas_step_bp)
app.register_blueprint(actas_status_bp)
app.register_blueprint(opex_resolver_bp)
app.register_blueprint(cron_reintentos_bp)
app.register_blueprint(analizar_alcance_bp)


@app.get("/")
def estado():
    """No es un frontend, solo evita el 404 confuso al abrir la raíz en el navegador."""
    return jsonify({
        "estado": "ok",
        "servicio": "Frontera CO - Automatización (CAPEX/OPEX)",
        "endpoints": [
            "POST /api/actas_start",
            "POST /api/actas_step",
            "GET /api/actas_status?co=...",
            "POST /api/analizar_alcance",
            "POST /api/opex_resolver",
            "GET /api/cron_reintentos",
        ],
    })
