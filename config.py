import os
from pathlib import Path

basedir = Path(__file__).resolve().parent

class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    if not SQLALCHEMY_DATABASE_URI:
        raise RuntimeError(
            "DATABASE_URL environment variable is required for PostgreSQL configuration"
        )

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JSON_SORT_KEYS = False
    JSONIFY_PRETTYPRINT_REGULAR = True
