from pathlib import Path

from flask import Flask, jsonify, send_from_directory
from flask_login import LoginManager

from backend.config import (
    AGENT_OUTPUT_FOLDER,
    CURSOR_MODEL,
    DISABLE_AUTH,
    MEMORY_FOLDER,
    RESUME_UPLOAD_FOLDER,
    UPLOAD_FOLDER,
)
from backend.services.cursor_llm import is_configured as cursor_llm_configured
from backend.models import User, db
from backend.services.db_migrate import migrate_db
from backend.services.dev_auth import auto_login_if_disabled, seed_demo_user_on_startup
from backend.routes.agents import agents_bp
from backend.routes.auth import auth_bp
from backend.routes.billing import billing_bp
from backend.routes.chat import chat_bp
from backend.routes.events import events_bp
from backend.routes.home import home_bp
from backend.routes.profile import profile_bp
from backend.routes.projects import projects_bp
from backend.routes.studio import studio_bp


def create_app(config_overrides: dict | None = None) -> Flask:
    app = Flask(__name__, static_folder="../frontend", static_url_path="")
    app.config.from_object("backend.config")
    if config_overrides:
        app.config.update(config_overrides)

    UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    RESUME_UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    AGENT_OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
    MEMORY_FOLDER.mkdir(parents=True, exist_ok=True)

    db.init_app(app)

    login_manager = LoginManager()
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    app.register_blueprint(auth_bp)
    app.register_blueprint(agents_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(home_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(studio_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(billing_bp)

    @app.before_request
    def _dev_auto_login():
        auto_login_if_disabled()

    @app.route("/api/config")
    def app_config():
        auth_disabled = app.config.get("DISABLE_AUTH", False)
        payload = {
            "auth_required": not auth_disabled,
            "auth_provider": "supabase" if (
                not auth_disabled
                and app.config.get("SUPABASE_URL")
                and app.config.get("SUPABASE_ANON_KEY")
            ) else "local",
        }
        if auth_disabled:
            from backend.services.dev_auth import DEMO_EMAIL, DEMO_PASSWORD
            payload["demo_login"] = {"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
        payload["llm"] = {
            "provider": "cursor",
            "model": CURSOR_MODEL,
            "configured": cursor_llm_configured(),
        }
        return jsonify(payload)

    @app.route("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.route("/<path:path>")
    def static_files(path):
        return send_from_directory(app.static_folder, path)

    with app.app_context():
        migrate_db()
        seed_demo_user_on_startup()

    return app


if __name__ == "__main__":
    create_app().run(debug=True, port=5000)
