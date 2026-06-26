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

    # Use a safe basename so archive_name can't escape /tmp/ via path traversal
    tmp = Path("/tmp") / f"_hpzip_{Path(archive_name).name}"
    try:
        parent_dir = srcs[0].parent
        rel_names = [src.name for src in srcs]

        # sudo zip reads user-owned files; runs from parent dir so archive entries are relative
        r = subprocess.run(
            ["sudo", "-n", "/usr/bin/zip", "-r", str(tmp)] + rel_names,
            cwd=str(parent_dir),
            capture_output=True, text=True, check=False,
        )
        if r.returncode != 0:
            raise PermissionError(r.stderr.strip() or r.stdout.strip())

        # Move the temp archive into the destination directory (also may be user-owned)
        r = subprocess.run(
            ["sudo", "-n", "/usr/bin/mv", str(tmp), str(dest)],
            capture_output=True, text=True, check=False,
        )
        if r.returncode != 0:
            raise PermissionError(f"Could not place archive: {r.stderr.strip()}")

        log_action(current_user.username, "file.zip", archive_name, f"{len(req.paths)} item(s)")
        return {"message": f"Created archive {archive_name}"}
    except Exception as e:
        subprocess.run(["/usr/bin/rm", "-f", str(tmp)], capture_output=True, check=False)
        logger.error(f"Zip failed: {e}")
        raise HTTPException(status_code=500, detail=f"Zip compression failed: {str(e)}")


@router.post("/unzip")
async def unzip_path(req: UnzipRequest, current_user: User = Depends(get_current_user)):
    archive = _safe_path(req.archive_path, current_user)
    if not archive.exists():
        raise HTTPException(status_code=404, detail="Archive not found.")

    dest_dir = _safe_path(req.dest_dir, current_user)

    try:
        # Zip Slip safety check — scan member names before extracting
        try:
            with zipfile.ZipFile(archive, 'r') as zipf:
                for info in zipf.infolist():
                    if info.filename.startswith('/') or '..' in info.filename.split('/'):
                        raise HTTPException(status_code=403, detail="Unsafe zip archive (path traversal detected).")
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid or corrupt zip file.")

        # Delegate extraction to the OS unzip command running as root so it can
        # write into user-owned directories without permission errors.
        # -o  overwrite existing files without prompting
        # -x  exclude macOS metadata (__MACOSX dirs and .DS_Store files)
        r = subprocess.run(
            ["sudo", "-n", "unzip", "-o", str(archive), "-d", str(dest_dir),
             "-x", "__MACOSX/*", "-x", "__MACOSX"],
            capture_output=True, text=True, check=False,
        )
        # unzip exit codes: 0=clean, 1=warnings-but-extracted, 2+=real error.
        # sudo -n also exits 1 when no NOPASSWD rule matches — check stdout for
        # actual extraction output to tell the two apart.
        extracted = any(k in r.stdout for k in ('inflating:', 'extracting:', 'creating:'))
        if r.returncode != 0 and not extracted:
            output = (r.stderr + "\n" + r.stdout).strip()
            raise PermissionError(f"unzip failed (exit {r.returncode}): {output}")

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
            r = subprocess.run(["sudo", "-n", "/usr/bin/mv", str(src), str(dest)], capture_output=True, check=False)
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
            r = subprocess.run(
                ["sudo", "-n", "/usr/bin/cp", "-rp", str(src), str(dest)],
                capture_output=True, text=True, check=False,
            )
            if r.returncode != 0:
                errors.append(f"{src.name}: permission denied (sudo: {r.stderr.strip()})")
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
