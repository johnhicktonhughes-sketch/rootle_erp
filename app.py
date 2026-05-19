from flask import Flask, jsonify

from config import Config
from database import db
from routes.crm import crm_bp


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)

    app.register_blueprint(crm_bp, url_prefix="/api")

    @app.route("/")
    def index():
        return jsonify({"service": "rootle_erp", "status": "ok"})

    return app


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        db.create_all()
    app.run(debug=True, host="0.0.0.0")
