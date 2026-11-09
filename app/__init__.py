"""
app/__init__.py - Application Factory

Initializes the Flask application with configuration, teardown database handlers,
registers blueprints, and configures JSON error handlers.
"""

import os
from typing import Any, Dict, Optional
from flask import Flask, jsonify

from app.config import Config, config_by_name
from app.database import init_app as init_db_app


def create_app(test_config: Optional[Dict[str, Any]] = None, config_name: str = "default") -> Flask:
    """
    Flask Application Factory pattern.

    Args:
        test_config: Optional dictionary of configuration overrides.
        config_name: Configuration profile name ('development', 'testing', 'production', 'default').

    Returns:
        Configured Flask application instance.
    """
    app = Flask(__name__, instance_relative_config=True)

    # 1. Load base configuration object
    cfg_class = config_by_name.get(config_name, Config)
    app.config.from_object(cfg_class)
    app.url_map.merge_slashes = False

    # 2. Apply explicit configuration overrides if provided (e.g. testing)
    if test_config:
        app.config.update(test_config)

    # 3. Register database lifecycle teardown hooks
    init_db_app(app)

    # 4. Register API Blueprint
    from app.routes.api import api_bp
    app.register_blueprint(api_bp)

    # 5. Register views and backup blueprints
    from app.routes.views import views_bp
    app.register_blueprint(views_bp)

    from app.routes.backup_routes import backup_bp
    app.register_blueprint(backup_bp)

    # 6. Register JSON error handlers for consistent REST responses
    @app.errorhandler(400)
    def bad_request(error):
        message = getattr(error, "description", "Bad Request")
        return jsonify({"error": message, "status_code": 400}), 400

    @app.errorhandler(404)
    def not_found(error):
        message = getattr(error, "description", "Not Found")
        return jsonify({"error": message, "status_code": 404}), 404

    @app.errorhandler(405)
    def method_not_allowed(error):
        message = getattr(error, "description", "Method Not Allowed")
        return jsonify({"error": message, "status_code": 405}), 405

    @app.errorhandler(422)
    def unprocessable_entity(error):
        message = getattr(error, "description", "Unprocessable Entity")
        return jsonify({"error": message, "status_code": 422}), 422

    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({"error": "Internal Server Error", "status_code": 500}), 500

    # 7. Start automated 25-second background time updater
    if not app.config.get("TESTING"):
        try:
            from app.background_updater import start_background_updater
            start_background_updater(interval_seconds=25)
        except Exception:
            pass

    return app
