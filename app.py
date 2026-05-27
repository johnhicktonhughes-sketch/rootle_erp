from flask import Flask, jsonify, request

from config import Config
from database import db
from routes.crm import crm_bp


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)

    app.register_blueprint(crm_bp, url_prefix="/api")

    @app.after_request
    def add_cors_headers(response):
        origin = request.headers.get("Origin")
        allowed_origins = app.config.get("CORS_ALLOWED_ORIGINS", [])
        if origin in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, OPTIONS"
        return response

    @app.route("/")
    def index():
        return jsonify({"service": "rootle_erp", "status": "ok"})

    return app


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        db.create_all()
    app.run(debug=True, host="0.0.0.0")
