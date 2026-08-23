from __future__ import annotations

import os

from flask import Flask, g, jsonify
from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from .auth import ensure_csrf_token
from .models import Base

load_dotenv()


def _database_url(config: dict) -> str:
    url = config.get("DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        if config.get("TESTING"):
            return "sqlite+pysqlite:///:memory:"
        raise RuntimeError("DATABASE_URL is required")
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url.removeprefix("postgres://")
    elif url.startswith("postgresql://") and "+psycopg" not in url:
        url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_mapping(
        SECRET_KEY=os.getenv("SESSION_SECRET", ""),
        ACTION_BEARER_TOKEN=os.getenv("ACTION_BEARER_TOKEN", ""),
        WEB_PASSWORD_HASH=os.getenv("WEB_PASSWORD_HASH", ""),
        DATABASE_URL=os.getenv("DATABASE_URL", ""),
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "true").lower() == "true",
        AUTO_CREATE_SCHEMA=os.getenv("AUTO_CREATE_SCHEMA", "false").lower() == "true",
    )
    if test_config:
        app.config.update(test_config)
    if not app.config["SECRET_KEY"]:
        if app.config.get("TESTING"):
            app.config["SECRET_KEY"] = "test-only-secret"
        else:
            raise RuntimeError("SESSION_SECRET is required")

    url = _database_url(app.config)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app.extensions["db_engine"] = engine
    app.extensions["db_session_factory"] = factory

    if app.config.get("TESTING") or app.config.get("AUTO_CREATE_SCHEMA"):
        Base.metadata.create_all(engine)

    @app.before_request
    def _open_session():
        g.db = factory()

    @app.teardown_request
    def _close_session(error=None):
        db = g.pop("db", None)
        if db is not None:
            if error:
                db.rollback()
            db.close()

    @app.context_processor
    def _template_context():
        return {"csrf_token": ensure_csrf_token()}

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "service": "xiaxia-watch-house"})

    from .routes_action import action_bp
    from .routes_web import web_bp

    app.register_blueprint(web_bp)
    app.register_blueprint(action_bp)
    return app
