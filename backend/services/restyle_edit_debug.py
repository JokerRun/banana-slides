"""
Restyle edit observability helpers.

Provides structured event logging and conditional request snapshot capture so
debugging drift/fallback issues does not require reproducing a live provider call.
"""

import hashlib
import json
import logging
from pathlib import Path

from PIL import Image


logger = logging.getLogger(__name__)


def log_restyle_edit_event(event_name, trace, payload):
    """Emit a searchable JSON log line for a restyle edit event."""
    logger.info(
        "restyle_edit_event %s",
        json.dumps(
            {
                'event_name': event_name,
                'trace': trace,
                'event': payload,
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ),
    )


def build_task_artifact_path_components():
    """Return the relative subdirectory used for task-scoped artifacts."""
    return ['task']


def build_page_artifact_path_components(*, page_number=None, page_id=None, version_number=None):
    """Return the relative subdirectory used for page/version-scoped artifacts."""
    page_label = page_id or 'unknown-page'
    if page_number is None:
        page_dir = f'page-unknown-{page_label}'
    else:
        page_dir = f'page-{int(page_number):03d}-{page_label}'

    components = ['pages', page_dir]
    if version_number is not None:
        components.append(f'version-{int(version_number):03d}')
    return components


def serialize_conversation_contents(contents):
    """Serialize provider-agnostic conversation contents without image bytes."""
    serialized = []
    for turn in contents:
        parts = []
        for part in turn.get('parts', []):
            if 'text' in part:
                parts.append({
                    'type': 'text',
                    'text': part['text'],
                    'text_len': len(part['text']),
                })
            elif 'image_path' in part:
                parts.append({
                    'type': 'image',
                    'image_path': part['image_path'],
                })
            else:
                parts.append(part)
        serialized.append({
            'role': turn.get('role'),
            'parts': parts,
        })
    return serialized


def enrich_image_manifest(image_manifest):
    """Attach stable file metadata to image manifest rows."""
    enriched = []
    for item in image_manifest:
        path = item.get('path')
        exists = bool(path) and Path(path).exists()
        metadata = {
            **item,
            'exists': exists,
        }
        if exists:
            metadata['sha256'] = _sha256_file(path)
            metadata['file_size'] = Path(path).stat().st_size
            width, height = _safe_image_size(path)
            metadata['width'] = width
            metadata['height'] = height
        else:
            metadata['sha256'] = None
            metadata['file_size'] = None
            metadata['width'] = None
            metadata['height'] = None
        enriched.append(metadata)
    return enriched


def maybe_write_debug_artifact(
    config,
    *,
    event_name,
    trace,
    payload,
    path_components=None,
    degraded_context=False,
    provider_fallback=False,
    error=False,
):
    """Write an event artifact when debug mode or a notable condition is active."""
    if not _should_capture(
        config,
        degraded_context=degraded_context,
        provider_fallback=provider_fallback,
        error=error,
    ):
        return None

    task_id = trace.get('task_id') or 'unknown-task'
    artifact_dir = Path(config.RESTYLE_EDIT_DEBUG_DIR) / task_id
    for component in path_components or []:
        artifact_dir = artifact_dir / component
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f'{event_name}.json'
    artifact_path.write_text(
        json.dumps(
            {
                'trace': trace,
                'event_name': event_name,
                'event': payload,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
    return str(artifact_path)


def _should_capture(config, *, degraded_context=False, provider_fallback=False, error=False):
    return any((
        getattr(config, 'DEBUG_RESTYLE_CONTEXT', False),
        degraded_context,
        provider_fallback,
        error,
    ))


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(8192), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_image_size(path):
    try:
        with Image.open(path) as image:
            return image.size
    except Exception:
        return None, None
