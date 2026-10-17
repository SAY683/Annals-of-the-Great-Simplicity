"""Archive use cases."""
import os
import shutil
import tempfile

from core.locks import ARCHIVE_DIR
from repositories.task_repository import delete_task
from services.file_management import _safe_task_path
from services.history_service import lookup_summary_by_task_id
from services.summary_builder import _task_summary


def list_archives():
    archives = []
    if os.path.isdir(ARCHIVE_DIR):
        for name in os.listdir(ARCHIVE_DIR):
            if not name.lower().endswith('.zip'):
                continue
            path = os.path.join(ARCHIVE_DIR, name)
            if not os.path.isfile(path):
                continue
            archives.append({
                'task_id': name[:-4],
                'filename': name,
                'size_bytes': os.path.getsize(path),
                'updated_at': os.path.getmtime(path),
            })
    archives.sort(key=lambda item: item['updated_at'], reverse=True)
    return {'archives': archives}


def restore_archive(task_id: str):
    zip_path = _safe_task_path(task_id + '.zip', ARCHIVE_DIR)
    if not zip_path or not os.path.exists(zip_path):
        raise FileNotFoundError(task_id)
    from core.locks import RESULTS_DIR
    task_dir = _safe_task_path(task_id, RESULTS_DIR)
    if not task_dir:
        raise ValueError('Invalid task_id')
    if os.path.exists(task_dir):
        raise FileExistsError(task_id)
    shutil.unpack_archive(zip_path, task_dir, format='zip')
    return task_dir


def preview_archive(task_id: str):
    zip_path = _safe_task_path(task_id + '.zip', ARCHIVE_DIR)
    if not zip_path or not os.path.exists(zip_path):
        raise FileNotFoundError(task_id)
    tmp_dir = tempfile.mkdtemp(prefix='edmtakens_preview_')
    try:
        shutil.unpack_archive(zip_path, tmp_dir, format='zip')
        summary = _task_summary(task_id, task_dir=tmp_dir)
        if summary is None:
            raise RuntimeError('Preview build failed')
        return {
            'success': True,
            'task_id': task_id,
            'config': summary.get('config'),
            'params': summary.get('params'),
            'images': summary.get('images', []),
            'summary': lookup_summary_by_task_id(task_id),
            'task_updated': os.path.getmtime(zip_path),
        }
    finally:
        try:
            shutil.rmtree(tmp_dir)
        except Exception:
            pass


def delete_archive(task_id: str):
    zip_path = _safe_task_path(task_id + '.zip', ARCHIVE_DIR)
    if not zip_path or not os.path.exists(zip_path):
        raise FileNotFoundError(task_id)
    os.remove(zip_path)
    return {'task_id': task_id, 'deleted': True}
