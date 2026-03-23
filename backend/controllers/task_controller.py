"""Task controller for owner-scoped global task status."""

from flask import Blueprint

from models import Task
from utils import not_found, success_response, get_current_user_id, require_auth


task_bp = Blueprint('tasks', __name__, url_prefix='/api/tasks')


@task_bp.route('/<task_id>', methods=['GET'])
@require_auth
def get_task_status(task_id: str):
    current_user_id = get_current_user_id()
    task = Task.query.filter_by(id=task_id, owner_id=current_user_id).first()
    if not task:
        return not_found('Task')
    return success_response(task.to_dict())
