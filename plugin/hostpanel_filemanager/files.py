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
        logger.info(f"Renamed {p} -> {target}")
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

    try:
        with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for src in srcs:
                if src.is_dir():
                    for root, _, files in os.walk(src):
                        for file in files:
                            filepath = os.path.join(root, file)
                            arcname = os.path.relpath(filepath, src.parent)
                            zipf.write(filepath, arcname)
                else:
                    zipf.write(src, src.name)
        logger.info(f"Created archive: {dest}")
        return {"message": f"Created archive {archive_name}"}
    except Exception as e:
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
        
    try:
        with zipfile.ZipFile(archive, 'r') as zipf:
            # Zip Slip path traversal attack protection
            for member in zipf.infolist():
                # Resolve target path cleanly and safely
                target_path = Path(os.path.realpath(dest_dir / member.filename))
                # Raise 403 / escape check if it travels outside dest_dir
                try:
                    target_path.relative_to(dest_dir)
                except ValueError:
                    raise HTTPException(status_code=403, detail="Unsafe zip archive (Zip Slip attempt detected).")
            
            # If all paths are safe, perform extraction
            try:
                zipf.extractall(dest_dir)
            except PermissionError:
                # Fall back to member-by-member extraction via sudo tee / mkdir
                for member in zipf.infolist():
                    target_path = dest_dir / member.filename
                    if member.is_dir():
                        subprocess.run(
                            ["sudo", "-n", "mkdir", "-p", str(target_path)],
                            capture_output=True, check=False,
                        )
                    else:
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        data = zipf.read(member.filename)
                        r = subprocess.run(
                            ["sudo", "-n", "tee", str(target_path)],
                            input=data, capture_output=True, check=False,
                        )
                        if r.returncode != 0:
                            raise PermissionError(f"sudo tee failed for {member.filename}")
        logger.info(f"Extracted {archive} -> {dest_dir}")
        return {"message": f"Extracted archive to {dest_dir.name}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unzip failed: {e}")
        raise HTTPException(status_code=500, detail=f"Zip extraction failed: {str(e)}")
