"""Archive management routes."""
import mimetypes

from fastapi import APIRouter, Depends, HTTPException, Response

from core.auth import require_auth, require_auth_optional
from services import archive_service

router = APIRouter()


@router.get("/api/archives", dependencies=[Depends(require_auth_optional)])
def list_archives():
    return archive_service.list_archives()


@router.post("/api/archives/{task_id}/restore", dependencies=[Depends(require_auth)])
def restore_archive(task_id: str):
    try:
        path = archive_service.restore_archive(task_id)
        return {"task_id": task_id, "restored": True, "path": path}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Archive not found")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task_id")
    except FileExistsError:
        raise HTTPException(status_code=409, detail="Task directory already exists")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Restore failed: {exc}")


@router.get("/api/archives/{task_id}/preview", dependencies=[Depends(require_auth_optional)])
def preview_archive(task_id: str):
    try:
        return archive_service.preview_archive(task_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Archive not found")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Preview failed: {exc}")


@router.get("/api/archives/{task_id}/images/{filename}", dependencies=[Depends(require_auth_optional)])
def archive_image(task_id: str, filename: str):
    try:
        data = archive_service.read_archive_image(task_id, filename)
        media_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        return Response(content=data, media_type=media_type)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Archived image not found")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid image filename")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Archive image failed: {exc}")

@router.delete("/api/archives/{task_id}", dependencies=[Depends(require_auth)])
def delete_archive(task_id: str):
    try:
        return archive_service.delete_archive(task_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Archive not found")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Delete failed: {exc}")
