"""
app/routes/__init__.py - Routes package initialization
"""

from app.routes.api import api_bp
from app.routes.views import views_bp
from app.routes.backup_routes import backup_bp

__all__ = ["api_bp", "views_bp", "backup_bp"]
