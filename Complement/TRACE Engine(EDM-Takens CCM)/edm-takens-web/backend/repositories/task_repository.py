"""Filesystem-backed task/archive repository.

All direct knowledge of results/, archives/ and task zip layout lives here.
Routers and services should not assemble those paths themselves.
"""
import os
import shutil
import tempfile
import time
import zipfile

from core.locks import ARCHIVE_DIR, RESULTS_DIR, _PROJECT_ROOT
from services.file_management import _safe_task_path, _total_size_mb, _zip_task
from services.summary_builder import _task_summary


def list_task_summaries(limit: int = 50):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    tasks = []
    for name in os.listdir(RESULTS_DIR):
        task_dir = os.path.join(RESULTS_DIR, name)
        if not os.path.isdir(task_dir):
            continue
        summary = _task_summary(name)
        if summary is None:
            continue
        tasks.append({
            "task_id": summary["task_id"],
            "updated_at": summary["updated_at"],
            "images": summary["images"],
            "has_config": summary["config"] is not None,
            "config": summary["config"],
            "params": summary["params"],
        })
    tasks.sort(key=lambda item: item["updated_at"], reverse=True)
    return tasks[:limit]


def get_task_summary(task_id: str):
    task_dir = _safe_task_path(task_id, RESULTS_DIR)
    if not task_dir or not os.path.isdir(task_dir):
        return None
    return _task_summary(task_id)


def archive_task(task_id: str) -> str:
    task_dir = _safe_task_path(task_id, RESULTS_DIR)
    if not task_dir or not os.path.isdir(task_dir):
        raise FileNotFoundError(task_id)
    zip_path = _zip_task(task_id)
    shutil.rmtree(task_dir)
    return zip_path


def task_download_path(task_id: str) -> str:
    task_dir = _safe_task_path(task_id, RESULTS_DIR)
    if task_dir and os.path.isdir(task_dir):
        return _zip_task(task_id)
    zip_path = _safe_task_path(task_id + ".zip", ARCHIVE_DIR)
    if zip_path and os.path.exists(zip_path):
        return zip_path
    raise FileNotFoundError(task_id)


def delete_task(task_id: str):
    task_dir = _safe_task_path(task_id, RESULTS_DIR)
    zip_path = _safe_task_path(task_id + ".zip", ARCHIVE_DIR)
    deleted = {"result_dir": False, "zip": False}
    if task_dir and os.path.isdir(task_dir):
        shutil.rmtree(task_dir)
        deleted["result_dir"] = True
    if zip_path and os.path.exists(zip_path):
        os.remove(zip_path)
        deleted["zip"] = True
    if not any(deleted.values()):
        raise FileNotFoundError(task_id)
    return deleted


def cleanup_results(days: int, max_size_mb=None, dry_run: bool = False):
    cutoff = time.time() - days * 86400
    candidates = []
    for base_dir in (RESULTS_DIR, ARCHIVE_DIR):
        if not os.path.isdir(base_dir):
            continue
        for name in os.listdir(base_dir):
            path = os.path.join(base_dir, name)
            if os.path.isdir(path) or os.path.isfile(path):
                mtime = os.path.getmtime(path)
                if mtime < cutoff:
                    candidates.append({
                        "path": path,
                        "mtime": mtime,
                        "rel": os.path.relpath(path, _PROJECT_ROOT),
                    })

    removed = []
    for item in candidates:
        if not dry_run:
            try:
                if os.path.isdir(item["path"]):
                    shutil.rmtree(item["path"])
                else:
                    os.remove(item["path"])
            except Exception:
                continue
        removed.append(item["rel"])

    size_deleted = []
    if max_size_mb is not None and max_size_mb > 0:
        remaining = []
        for base_dir in (RESULTS_DIR, ARCHIVE_DIR):
            if not os.path.isdir(base_dir):
                continue
            for name in os.listdir(base_dir):
                path = os.path.join(base_dir, name)
                if os.path.isdir(path) or os.path.isfile(path):
                    remaining.append({
                        "path": path,
                        "mtime": os.path.getmtime(path),
                        "rel": os.path.relpath(path, _PROJECT_ROOT),
                    })
        current_mb = _total_size_mb([item["path"] for item in remaining])
        if current_mb > max_size_mb:
            remaining.sort(key=lambda item: item["mtime"])
            while remaining and current_mb > max_size_mb:
                item = remaining.pop(0)
                if not dry_run:
                    try:
                        if os.path.isdir(item["path"]):
                            shutil.rmtree(item["path"])
                        else:
                            os.remove(item["path"])
                    except Exception:
                        continue
                size_deleted.append(item["rel"])
                current_mb = _total_size_mb([item["path"] for item in remaining])

    return {
        "dry_run": dry_run,
        "days": days,
        "max_size_mb": max_size_mb,
        "removed": removed,
        "removed_count": len(removed),
        "size_deleted": size_deleted,
        "size_deleted_count": len(size_deleted),
    }


def build_batch_download(task_ids):
    fd, bundle_path = tempfile.mkstemp(suffix='.zip', prefix='edmtakens_batch_')
    os.close(fd)
    try:
        with zipfile.ZipFile(bundle_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for task_id in task_ids:
                zip_path = _safe_task_path(task_id + '.zip', ARCHIVE_DIR)
                task_dir = _safe_task_path(task_id, RESULTS_DIR)
                if zip_path and os.path.exists(zip_path):
                    zf.write(zip_path, arcname=f'{task_id}.zip')
                elif task_dir and os.path.isdir(task_dir):
                    for root_dir, _, files in os.walk(task_dir):
                        for fname in files:
                            fpath = os.path.join(root_dir, fname)
                            rel = os.path.relpath(fpath, task_dir)
                            zf.write(fpath, arcname=os.path.join(task_id, rel))
        return bundle_path
    except Exception:
        if os.path.exists(bundle_path):
            os.remove(bundle_path)
        raise


def batch_archive_or_delete(action, task_ids):
    results = []
    for task_id in task_ids:
        task_dir = _safe_task_path(task_id, RESULTS_DIR)
        zip_path = _safe_task_path(task_id + '.zip', ARCHIVE_DIR)
        entry = {'task_id': task_id, 'success': False, 'detail': ''}
        try:
            if action == 'archive':
                if not task_dir or not os.path.isdir(task_dir):
                    entry['detail'] = 'Task not found'
                else:
                    _zip_task(task_id)
                    shutil.rmtree(task_dir)
                    entry['success'] = True
                    entry['detail'] = 'archived'
            elif action == 'delete':
                deleted = []
                if task_dir and os.path.isdir(task_dir):
                    shutil.rmtree(task_dir)
                    deleted.append('result_dir')
                if zip_path and os.path.exists(zip_path):
                    os.remove(zip_path)
                    deleted.append('zip')
                if deleted:
                    entry['success'] = True
                    entry['detail'] = ','.join(deleted)
                else:
                    entry['detail'] = 'Task not found'
        except Exception as exc:
            entry['detail'] = str(exc)
        results.append(entry)
    return results
