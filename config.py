import os
from pathlib import Path

from dotenv import load_dotenv

basedir = Path(__file__).resolve().parent
load_dotenv(basedir / ".env")

class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    if not SQLALCHEMY_DATABASE_URI:
        raise RuntimeError(
            "DATABASE_URL environment variable is required for PostgreSQL configuration"
        )

    CORS_ALLOWED_ORIGINS = [
        origin.strip()
        for origin in os.getenv(
            "CORS_ALLOWED_ORIGINS",
            "https://rootle-analytics.lovable.app",
        ).split(",")
        if origin.strip()
    ]

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JSON_SORT_KEYS = False
    JSONIFY_PRETTYPRINT_REGULAR = True
    ROOTLE_API_KEY = os.getenv("ROOTLE_API_KEY") or os.getenv("API_KEY")
    ATTIO_WEBHOOK_SECRET = os.getenv("ATTIO_WEBHOOK_SECRET")
    ATTIO_VALUATION_REQUEST_OBJECT_ID = os.getenv("ATTIO_VALUATION_REQUEST_OBJECT_ID")
