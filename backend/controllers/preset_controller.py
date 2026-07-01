"""
Preset Controller - exposes canonical runtime preset metadata and assets.
"""

import logging

from flask import Blueprint, send_file

from services.style_preset_service import (
    StylePresetError,
    get_style_preset,
    list_style_presets,
)
from utils import error_response, success_response, require_auth_response

logger = logging.getLogger(__name__)

preset_bp = Blueprint("presets", __name__, url_prefix="/api/presets")


@preset_bp.before_request
def _preset_auth_guard():
    return require_auth_response()


@preset_bp.route("", methods=["GET"])
def list_presets():
    try:
        return success_response(
            {"presets": [preset.to_dict() for preset in list_style_presets()]}
        )
    except Exception as exc:
        logger.error("list_presets failed: %s", exc, exc_info=True)
        return error_response("SERVER_ERROR", str(exc), 500)


@preset_bp.route("/<preset_id>/image", methods=["GET"])
def serve_preset_image(preset_id):
    try:
        preset = get_style_preset(preset_id)
        return send_file(preset.base_image_path, mimetype="image/png")
    except StylePresetError as exc:
        return error_response("INVALID_STYLE_PRESET", str(exc), 400)
    except Exception as exc:
        logger.error("serve_preset_image failed: %s", exc, exc_info=True)
        return error_response("SERVER_ERROR", str(exc), 500)
