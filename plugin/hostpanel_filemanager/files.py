import os
import shutil
import logging
import subprocess
import zipfile
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from auth import User
from deps import get_current_user
from modules.audit.logger import log_action
from routers.files import _safe_path

router = APIRouter(prefix="/cpanelapi/filemanager", tags=["FileManager"])
logger = logging.getLogger(__name__)


class RenameRequest(BaseModel):
    path: str
    new_name: str


class ZipRequest(BaseModel):
    paths: list[str]
    archive_name: str


class UnzipRequest(BaseModel):
    archive_path: str
    dest_dir: str


class MoveRequest(BaseModel):
    paths: list[str]
    dest_dir: str


class CopyRequest(BaseModel):
    paths: list[str]
    dest_dir: str


class ChmodRequest(BaseModel):
    path: str
    mode: int


@router.post("/rename")
async def rename_path(req: RenameRequest, current_user: User = Depends(get_current_user)):
    p = _safe_path(req.path, current_user)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Source path not found.")
    
    # Target path in the same parent directory
    target = p.parent / req.new_name
    _safe_path(str(target), current_user)  # validate target path
    
    if target.exists():
        raise HTTPException(status_code=409, detail="Destination name already exists.")
        
    try:
        shutil.move(str(p), str(target))
        log_action(current_user.username, "file.rename", str(p), f"→ {req.new_name}")
        return {"message": f"Renamed to {req.new_name}"}
    except Exception as e:
        logger.error(f"Rename failed: {e}")
        raise HTTPException(status_code=500, detail=f"Rename failed: {str(e)}")


@router.post("/zip")
async def zip_path(req: ZipRequest, current_user: User = Depends(get_current_user)):
    if not req.paths:
        raise HTTPException(status_code=400, detail="No paths provided.")

    srcs = [_safe_path(p, current_user) for p in req.paths]
    for src in srcs:
        if not src.exists():
            raise HTTPException(status_code=404, detail=f"Path not found: {src.name}")

    archive_name = req.archive_name.strip()
    if not archive_name.lower().endswith(".zip"):
        archive_name += ".zip"

    dest = srcs[0].parent / archive_name
    _safe_path(str(dest), current_user)

    tmp = Path(f"/tmp/_hpzip_{archive_name}")
    try:
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for src in srcs:
                if src.is_dir():
                    for root, _, files in os.walk(src):
                        for file in files:
                            filepath = os.path.join(root, file)
                            arcname = os.path.relpath(filepath, src.parent)
                            zipf.write(filepath, arcname)
                else:
                    zipf.write(src, src.name)
        # Move to destination — use sudo tee since dest dir may not be writable by API user
        try:
            tmp.rename(dest)
        except OSError:
            with open(tmp, 'rb') as f:
                r = subprocess.run(["sudo", "-n", "tee", str(dest)], stdin=f, stdout=subprocess.DEVNULL, check=False)
            if r.returncode != 0:
                raise PermissionError(f"sudo tee failed writing {dest}")
            tmp.unlink(missing_ok=True)
        log_action(current_user.username, "file.zip", archive_name, f"{len(req.paths)} item(s)")
        return {"message": f"Created archive {archive_name}"}
    except Exception as e:
        tmp.unlink(missing_ok=True)
        logger.error(f"Zip failed: {e}")
        raise HTTPException(status_code=500, detail=f"Zip compression failed: {str(e)}")


@router.post("/unzip")
async def unzip_path(req: UnzipRequest, current_user: User = Depends(get_current_user)):
    archive = _safe_path(req.archive_path, current_user)
    if not archive.exists():
        raise HTTPException(status_code=404, detail="Archive not found.")
    
    dest_dir = _safe_path(req.dest_dir, current_user)
    if not dest_dir.exists():
        dest_dir.mkdir(parents=True, exist_ok=True)
    elif not dest_dir.is_dir():
        raise HTTPException(status_code=400, detail="Destination must be a directory.")
        
    def _is_macos_junk(name: str) -> bool:
        parts = Path(name).parts
        return parts[0] in ("__MACOSX",) or Path(name).name in (".DS_Store", "._.DS_Store")

    try:
        with zipfile.ZipFile(archive, 'r') as zipf:
            members = [m for m in zipf.infolist() if not _is_macos_junk(m.filename)]

            # Zip Slip path traversal check on filtered members only
            for member in members:
                target_path = Path(os.path.realpath(dest_dir / member.filename))
                try:
                    target_path.relative_to(dest_dir)
                except ValueError:
                    raise HTTPException(status_code=403, detail="Unsafe zip archive (Zip Slip attempt detected).")

            # Try fast extractall first; fall back to sudo-based member-by-member
            # extraction when the dest_dir is owned by a different system user.
            try:
                zipf.extractall(dest_dir, members=[m.filename for m in members])
            except PermissionError:
                for member in members:
                    target_path = dest_dir / member.filename
                    if member.is_dir():
                        subprocess.run(
                            ["sudo", "-n", "mkdir", "-p", str(target_path)],
                            capture_output=True, check=False,
                        )
                    else:
                        # Create parent dir with sudo before writing
                        subprocess.run(
                            ["sudo", "-n", "mkdir", "-p", str(target_path.parent)],
                            capture_output=True, check=False,
                        )
                        data = zipf.read(member.filename)
                        r = subprocess.run(
                            ["sudo", "-n", "tee", str(target_path)],
                            input=data, capture_output=True, check=False,
                        )
                        if r.returncode != 0:
                            raise PermissionError(f"sudo tee failed for {member.filename}")

        log_action(current_user.username, "file.unzip", str(archive), f"→ {dest_dir.name}")
        return {"message": f"Extracted archive to {dest_dir.name}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unzip failed: {e}")
        raise HTTPException(status_code=500, detail=f"Zip extraction failed: {str(e)}")


@router.post("/move")
async def move_paths(req: MoveRequest, current_user: User = Depends(get_current_user)):
    if not req.paths:
        raise HTTPException(status_code=400, detail="No paths provided.")
    dest_dir = _safe_path(req.dest_dir, current_user)
    if not dest_dir.exists() or not dest_dir.is_dir():
        raise HTTPException(status_code=400, detail="Destination directory not found.")
    errors = []
    for raw_path in req.paths:
        src = _safe_path(raw_path, current_user)
        if not src.exists():
            errors.append(f"{src.name}: not found")
            continue
        dest = dest_dir / src.name
        if dest.exists():
            errors.append(f"{src.name}: destination already exists")
            continue
        try:
            shutil.move(str(src), str(dest))
        except PermissionError:
            r = subprocess.run(["sudo", "-n", "mv", str(src), str(dest)], capture_output=True, check=False)
            if r.returncode != 0:
                errors.append(f"{src.name}: permission denied")
    if errors:
        raise HTTPException(status_code=409, detail="; ".join(errors))
    log_action(current_user.username, "file.move", req.dest_dir, f"{len(req.paths)} item(s)")
    return {"message": f"Moved {len(req.paths)} item(s)"}


@router.post("/copy")
async def copy_paths(req: CopyRequest, current_user: User = Depends(get_current_user)):
    if not req.paths:
        raise HTTPException(status_code=400, detail="No paths provided.")
    dest_dir = _safe_path(req.dest_dir, current_user)
    if not dest_dir.exists() or not dest_dir.is_dir():
        raise HTTPException(status_code=400, detail="Destination directory not found.")
    errors = []
    for raw_path in req.paths:
        src = _safe_path(raw_path, current_user)
        if not src.exists():
            errors.append(f"{src.name}: not found")
            continue
        dest = dest_dir / src.name
        if dest.exists():
            stem = src.stem if not src.is_dir() else src.name
            suffix = src.suffix if not src.is_dir() else ''
            counter = 1
            while dest.exists():
                dest = dest_dir / f"{stem}_copy{counter}{suffix}"
                counter += 1
        try:
            if src.is_dir():
                shutil.copytree(str(src), str(dest))
            else:
                shutil.copy2(str(src), str(dest))
        except PermissionError:
            errors.append(f"{src.name}: permission denied")
    if errors:
        raise HTTPException(status_code=409, detail="; ".join(errors))
    log_action(current_user.username, "file.copy", req.dest_dir, f"{len(req.paths)} item(s)")
    return {"message": f"Copied {len(req.paths)} item(s)"}


@router.post("/chmod")
async def chmod_path(req: ChmodRequest, current_user: User = Depends(get_current_user)):
    if not (0 <= req.mode <= 0o7777):
        raise HTTPException(status_code=400, detail="Invalid mode value.")
    p = _safe_path(req.path, current_user)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Path not found.")
    try:
        p.chmod(req.mode)
    except PermissionError:
        r = subprocess.run(
            ["sudo", "-n", "/opt/hostpanel/bin/hp-chmod", oct(req.mode)[2:], str(p)],
            capture_output=True, check=False,
        )
        if r.returncode != 0:
            raise HTTPException(status_code=403, detail="Permission denied changing permissions.")
    log_action(current_user.username, "file.chmod", str(p), oct(req.mode))
    return {"message": "Permissions updated"}
