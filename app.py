import hmac

from flask import Flask, Response, jsonify, request

from api_docs import DOCS_HTML, OPENAPI_SPEC, SWAGGER_UI_HTML
from config import Config
from database import db
from routes.crm import crm_bp


def _request_api_key():
    bearer_prefix = "Bearer "
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith(bearer_prefix):
        return auth_header[len(bearer_prefix) :].strip()

    return request.headers.get("X-API-Key", "").strip()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)

    app.register_blueprint(crm_bp, url_prefix="/api")

    @app.before_request
    def require_api_key():
        if request.method == "OPTIONS" or not request.path.startswith("/api/"):
            return None

        if request.path == "/api/webhooks/attio":
            return None

        expected_key = app.config.get("ROOTLE_API_KEY")
        if not expected_key:
            return None

        provided_key = _request_api_key()
        if provided_key and hmac.compare_digest(provided_key, expected_key):
            return None

        return (
            jsonify(
                {
                    "error": "unauthorized",
                    "message": "A valid API key is required.",
                }
            ),
            401,
        )

    @app.after_request
    def add_cors_headers(response):
        origin = request.headers.get("Origin")
        allowed_origins = app.config.get("CORS_ALLOWED_ORIGINS", [])
        if origin in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = (
                "Content-Type, Authorization, X-API-Key"
            )
            response.headers["Access-Control-Allow-Methods"] = (
                "GET, POST, PATCH, DELETE, OPTIONS"
            )
        return response

    @app.route("/")
    def index():
        return jsonify({"service": "rootle_erp", "status": "ok"})

    @app.route("/docs")
    def docs():
        return Response(SWAGGER_UI_HTML, mimetype="text/html")

    @app.route("/docs/reference")
    def docs_reference():
        return Response(DOCS_HTML, mimetype="text/html")

    @app.route("/openapi.json")
    def openapi():
        return jsonify(OPENAPI_SPEC)

    return app


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        db.create_all()
    app.run(debug=False, host="0.0.0.0")
