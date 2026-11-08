"""
app/routes/views.py - Web Dashboard View Routes

Renders the responsive HTML5 web dashboard for real-time water level
monitoring, 15-day analytics, day-to-day comparison, and backup management.
"""

from flask import Blueprint, render_template

views_bp = Blueprint("views", __name__)


@views_bp.route("/")
@views_bp.route("/login")
def index():
    """
    Renders the primary web dashboard single page application.
    """
    return render_template("index.html")
