"""
Restyle Controller - handles PPT/PDF restyle endpoints
"""
import os
import logging
from datetime import datetime
from pathlib import Path

from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename

from models import db, Project, Page, Task
from services.restyle_service import RestyleService
from services.ai_service_manager import get_ai_service
from services.task_manager import task_manager, restyle_images_task
from utils import success_response, error_response, not_found, bad_request, parse_page_ids_from_body, get_filtered_pages

logger = logging.getLogger(__name__)

restyle_bp = Blueprint('restyle', __name__, url_prefix='/api/projects')

ALLOWED_SOURCE_EXTENSIONS = {'pptx', 'ppt', 'pdf'}
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'bmp'}
MAX_SOURCE_FILE_SIZE = 50 * 1024 * 1024  # 50MB
MAX_STYLE_REFS = 5


def _allowed_source_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_SOURCE_EXTENSIONS


def _allowed_image_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS

def _safe_filename_with_original_ext(filename: str, default_stem: str) -> str:
    """
    Build a filesystem-safe filename while preserving original extension.

    secure_filename may strip non-ASCII stems (e.g. Chinese), which can
    accidentally remove the dot and extension from the final saved filename.
    """
    source_path = Path(filename)
    ext = source_path.suffix.lower()
    safe_stem = secure_filename(source_path.stem)
    if not safe_stem:
        safe_stem = default_stem
    return f"{safe_stem}{ext}"


@restyle_bp.route('/restyle', methods=['POST'])
def create_restyle_project():
    """
    POST /api/projects/restyle - Create a restyle project

    Multipart form data:
    - source_file: File (PPT/PDF) — required
    - style_refs: File[] (1-N style reference images) — required
    - restyle_prompt: str (optional custom restyle prompt)

    Flow:
    1. Save source file
    2. Convert source file to per-page PNG images
    3. Save style reference images
    4. Create Project + Pages in DB
    5. Return project with original slide previews
    """
    try:
        # Validate source file
        if 'source_file' not in request.files:
            return bad_request("source_file is required")

        source_file = request.files['source_file']
        if not source_file.filename or not _allowed_source_file(source_file.filename):
            return bad_request(f"Invalid source file. Supported: {', '.join(ALLOWED_SOURCE_EXTENSIONS)}")

        # Validate style refs
        style_refs = request.files.getlist('style_refs')
        if not style_refs or len(style_refs) == 0:
            return bad_request("At least one style reference image is required")
        if len(style_refs) > MAX_STYLE_REFS:
            return bad_request(f"Maximum {MAX_STYLE_REFS} style reference images allowed")

        for ref in style_refs:
            if not ref.filename or not _allowed_image_file(ref.filename):
                return bad_request(f"Invalid style reference image: {ref.filename}")

        restyle_prompt = request.form.get('restyle_prompt', '').strip()

        # Use source filename (without extension) as project name
        source_name = Path(source_file.filename).stem or 'Restyle Project'

        # Create project
        project = Project(
            creation_type='restyle',
            idea_prompt=source_name,
            restyle_prompt=restyle_prompt if restyle_prompt else None,
            status='DRAFT'
        )
        db.session.add(project)
        db.session.flush()  # Get project ID

        from services import FileService
        file_service = FileService(current_app.config['UPLOAD_FOLDER'])

        # Save source file
        project_dir = file_service._get_project_dir(project.id)
        source_dir = project_dir / 'source'
        source_dir.mkdir(exist_ok=True, parents=True)

        source_filename = _safe_filename_with_original_ext(
            source_file.filename,
            default_stem='source_file'
        )
        source_path = source_dir / source_filename
        source_file.save(str(source_path))
        project.source_file_path = source_path.relative_to(file_service.upload_folder).as_posix()

        logger.info(f"📁 Source file saved: {source_path} ({os.path.getsize(str(source_path)) / 1024:.1f} KB)")

        # Save style reference images
        style_ref_dir = project_dir / 'style_refs'
        style_ref_dir.mkdir(exist_ok=True, parents=True)

        style_ref_paths = []
        for i, ref in enumerate(style_refs):
            ref_ext = Path(ref.filename).suffix.lower().lstrip('.')
            if ref_ext not in ALLOWED_IMAGE_EXTENSIONS:
                ref_ext = 'png'
            saved_name = f"style_ref_{i + 1}.{ref_ext}"
            ref_path = style_ref_dir / saved_name
            ref.save(str(ref_path))
            rel_path = ref_path.relative_to(file_service.upload_folder).as_posix()
            style_ref_paths.append(rel_path)
            logger.info(f"🎨 Style ref {i + 1}/{len(style_refs)} saved: {ref_path} ({os.path.getsize(str(ref_path)) / 1024:.1f} KB)")

        project.set_style_ref_image_paths(style_ref_paths)

        # Convert source file to images
        restyle_service = RestyleService()
        pages_dir = file_service._get_pages_dir(project.id)
        originals_dir = str(pages_dir / 'originals')
        os.makedirs(originals_dir, exist_ok=True)

        logger.info(f"📄 Converting source file to images: {source_filename}")
        slide_images = restyle_service.convert_to_images(str(source_path), originals_dir)
        logger.info(f"✅ Converted {len(slide_images)} pages from {source_filename}")

        # Create Page records
        pages_list = []
        for i, img_path in enumerate(slide_images):
            rel_path = os.path.relpath(img_path, str(file_service.upload_folder))
            page = Page(
                project_id=project.id,
                order_index=i,
                original_slide_image_path=rel_path,
                status='DRAFT'
            )
            # Set minimal outline content (page number as title)
            page.set_outline_content({
                'title': f'Slide {i + 1}',
                'points': []
            })
            db.session.add(page)
            pages_list.append(page)

        project.status = 'SLIDES_EXTRACTED'
        project.updated_at = datetime.utcnow()
        db.session.commit()

        logger.info(f"✅ Restyle project created: id={project.id}, name='{source_name}', pages={len(pages_list)}, style_refs={len(style_refs)}, prompt={'yes' if restyle_prompt else 'no'}")

        return success_response({
            'project_id': project.id,
            'creation_type': 'restyle',
            'status': project.status,
            'pages': [page.to_dict() for page in pages_list],
            'total_pages': len(pages_list)
        }, status_code=201)

    except Exception as e:
        db.session.rollback()
        logger.error(f"create_restyle_project failed: {str(e)}", exc_info=True)
        return error_response('SERVER_ERROR', str(e), 500)


@restyle_bp.route('/<project_id>/restyle/generate', methods=['POST'])
def restyle_generate(project_id):
    """
    POST /api/projects/{id}/restyle/generate - Start batch restyle

    Request body (optional):
    {
        "page_ids": ["id1", "id2"],  // specific pages, default: all
        "max_workers": 4
    }
    """
    try:
        project = Project.query.get(project_id)
        if not project:
            return not_found('Project')

        if project.creation_type != 'restyle':
            return bad_request("This endpoint is only for restyle type projects")

        data = request.get_json() or {}
        page_ids = data.get('page_ids')
        max_workers = data.get('max_workers', current_app.config.get('MAX_IMAGE_WORKERS', 4))

        # Get pages
        pages = get_filtered_pages(project_id, page_ids)
        if not pages:
            return bad_request("No pages found for project")

        # Create task
        task = Task(
            project_id=project_id,
            task_type='RESTYLE_IMAGES',
            status='PENDING'
        )
        task.set_progress({
            'total': len(pages),
            'completed': 0,
            'failed': 0
        })
        db.session.add(task)
        db.session.commit()

        # Get services
        ai_service = get_ai_service()
        from services import FileService
        file_service = FileService(current_app.config['UPLOAD_FOLDER'])

        app = current_app._get_current_object()

        # Submit background task
        task_manager.submit_task(
            task.id,
            restyle_images_task,
            project_id,
            ai_service,
            file_service,
            page_ids,
            max_workers,
            current_app.config['DEFAULT_ASPECT_RATIO'],
            current_app.config['DEFAULT_RESOLUTION'],
            app
        )

        project.status = 'GENERATING_IMAGES'
        db.session.commit()

        return success_response({
            'task_id': task.id,
            'status': 'GENERATING_IMAGES',
            'total_pages': len(pages)
        }, status_code=202)

    except Exception as e:
        db.session.rollback()
        logger.error(f"restyle_generate failed: {str(e)}", exc_info=True)
        return error_response('SERVER_ERROR', str(e), 500)


@restyle_bp.route('/<project_id>/pages/<page_id>/restyle/generate', methods=['POST'])
def restyle_single_page(project_id, page_id):
    """
    POST /api/projects/{id}/pages/{page_id}/restyle/generate - Restyle single page
    """
    try:
        project = Project.query.get(project_id)
        if not project:
            return not_found('Project')

        if project.creation_type != 'restyle':
            return bad_request("This endpoint is only for restyle type projects")

        page = Page.query.get(page_id)
        if not page or page.project_id != project_id:
            return not_found('Page')

        # Create task
        task = Task(
            project_id=project_id,
            task_type='RESTYLE_IMAGES',
            status='PENDING'
        )
        task.set_progress({
            'total': 1,
            'completed': 0,
            'failed': 0
        })
        db.session.add(task)
        db.session.commit()

        # Get services
        ai_service = get_ai_service()
        from services import FileService
        file_service = FileService(current_app.config['UPLOAD_FOLDER'])

        app = current_app._get_current_object()

        # Submit background task (single page)
        task_manager.submit_task(
            task.id,
            restyle_images_task,
            project_id,
            ai_service,
            file_service,
            [page_id],  # Single page
            1,  # max_workers
            current_app.config['DEFAULT_ASPECT_RATIO'],
            current_app.config['DEFAULT_RESOLUTION'],
            app
        )

        return success_response({
            'task_id': task.id,
            'status': 'GENERATING',
        }, status_code=202)

    except Exception as e:
        db.session.rollback()
        logger.error(f"restyle_single_page failed: {str(e)}", exc_info=True)
        return error_response('SERVER_ERROR', str(e), 500)
