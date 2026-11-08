"""
app/routes/backup_routes.py - Backup REST API Routes

Provides endpoints to trigger manual database backups, inspect backup logs,
and securely download backup files with strict path traversal defenses.
"""

import os
from urllib.parse import unquote
from flask import Blueprint, current_app, jsonify, request, send_file
from werkzeug.utils import secure_filename

from app.config import Config
from app.models import get_backup_logs
from scripts.backup import run_backup

backup_bp = Blueprint("backup", __name__, url_prefix="/api/backup")


@backup_bp.route("/create", methods=["POST"])
def create_backup():
    """
    Triggers an on-demand database backup.
    Accepts JSON body: {"format": "both"|"json"|"csv"}.
    Returns HTTP 201 Created with backup metadata.
    """
    payload = request.get_json(silent=True) or {}
    file_format = payload.get("format", "both")

    if not isinstance(file_format, str) or file_format.lower() not in ("json", "csv", "both", "folder"):
        return jsonify({
            "error": "Invalid format parameter. Must be 'json', 'csv', 'both', or 'folder'",
            "status_code": 400
        }), 400

    file_format = file_format.lower()
    db_path = current_app.config.get("DATABASE_PATH", Config.DATABASE_PATH)
    output_dir = current_app.config.get("BACKUP_DIR", Config.BACKUP_DIR)

    try:
        if file_format == "folder":
            from app.retention import create_15_day_backup_snapshot
            result = create_15_day_backup_snapshot(backup_type="manual")
        else:
            result = run_backup(
                db_path=db_path,
                output_dir=output_dir,
                file_format=file_format,
                retention_days=45,
                backup_type="manual"
            )
        return jsonify({
            "status": "success",
            "message": "Backup created successfully",
            "filename": result.get("filename") or result.get("folder_name"),
            "backup": result,
            "status_code": 201
        }), 201
    except Exception as exc:
        return jsonify({
            "error": f"Failed to create backup: {str(exc)}",
            "status_code": 500
        }), 500


@backup_bp.route("/list", methods=["GET"])
def list_backups():
    """
    Retrieves past backup execution logs.
    Supports query parameter ?limit=50.
    """
    limit_raw = request.args.get("limit")
    limit = 50
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
            if limit <= 0:
                return jsonify({
                    "error": "limit parameter must be a positive integer",
                    "status_code": 400
                }), 400
        except ValueError:
            return jsonify({
                "error": "limit parameter must be an integer",
                "status_code": 400
            }), 400

    try:
        logs = get_backup_logs(limit=limit)
        return jsonify({
            "status": "success",
            "backups": logs,
            "count": len(logs)
        }), 200
    except Exception as exc:
        return jsonify({
            "error": f"Failed to list backups: {str(exc)}",
            "status_code": 500
        }), 500


@backup_bp.route("/download/", defaults={"filename": ""}, methods=["GET"])
@backup_bp.route("/download/<path:filename>", methods=["GET"])
def download_backup(filename: str):
    """
    Serves a backup archive for download with strict path traversal prevention.
    """
    if not filename:
        return jsonify({"error": "Missing filename parameter", "status_code": 404}), 404

    # Iteratively unquote to handle single and double url-encoding
    raw_name = filename
    for _ in range(3):
        decoded = unquote(raw_name)
        if decoded == raw_name:
            break
        raw_name = decoded

    # Traversal and null-byte detection
    if any(pattern in raw_name.lower() for pattern in ["\x00", "%00", "..", "/", "\\", ":"]):
        return jsonify({"error": "Invalid filename parameter: path traversal detected", "status_code": 400}), 400

    if os.path.isabs(raw_name) or os.path.basename(raw_name) != raw_name:
        return jsonify({"error": "Invalid filename parameter: absolute or path segment detected", "status_code": 400}), 400

    backup_dir = os.path.abspath(current_app.config.get("BACKUP_DIR", Config.BACKUP_DIR))
    safe_path = os.path.abspath(os.path.join(backup_dir, raw_name))

    # Verify path stays inside backup_dir
    if not safe_path.startswith(backup_dir + os.sep) and safe_path != backup_dir:
        return jsonify({"error": "Access denied: destination outside backup directory", "status_code": 400}), 400

    if not os.path.isfile(safe_path):
        return jsonify({"error": f"Backup file '{raw_name}' not found on disk", "status_code": 404}), 404

    return send_file(safe_path, as_attachment=True, download_name=raw_name)
