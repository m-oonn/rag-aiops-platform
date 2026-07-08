from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Body
from typing import List, Optional
from src.services.storage import storage_service
from src.utils.logger import logger
from src.api.dependencies import get_current_user
from src.database.models import User
from pydantic import BaseModel

router = APIRouter()


class BatchDeleteRequest(BaseModel):
    object_names: List[str]


# 安全最佳实践: 所有 object_name 强制添加用户隔离前缀，防止 IDOR
# 用户 A 的文件存储为 "user_{A_id}/..."，用户 B 无法访问
def _user_prefix(user: User) -> str:
    """生成用户专属的存储前缀。"""
    return f"user_{user.id}"


def _safe_object_name(object_name: str, user: User) -> str:
    """将用户提供的 object_name 限制在当前用户命名空间内。

    安全最佳实践: 防止 IDOR，确保用户只能访问自己的文件。
    传入的 object_name 可能是裸文件名或带前缀，统一规范化为 user_{id}/...
    """
    prefix = _user_prefix(user)
    # 移除路径穿越尝试
    object_name = object_name.replace("..", "").lstrip("/")
    # 如果用户已带前缀，不重复添加
    if object_name.startswith(f"{prefix}/"):
        return object_name
    # 移除可能的其他 user_ 前缀，防止伪造
    if object_name.startswith("user_"):
        parts = object_name.split("/", 1)
        if len(parts) > 1:
            object_name = parts[1]
    return f"{prefix}/{object_name}"


@router.get("/files")
async def list_files(
    prefix: str = "", sort_by: str = "last_modified", order: str = "desc",
    search_query: str = "", current_user: User = Depends(get_current_user),
):
    """List files in the MinIO bucket.

    安全最佳实践: 只列出当前用户命名空间下的文件。
    """
    try:
        # 强制使用用户前缀，忽略用户传入的越权 prefix
        user_prefix = _user_prefix(current_user)
        full_prefix = f"{user_prefix}/{prefix}" if prefix else f"{user_prefix}/"
        files = storage_service.list_files(full_prefix, sort_by, order, search_query)
        return {"files": files}
    except Exception as e:
        logger.error(f"Error listing files: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/download/{object_name:path}")
async def download_file(object_name: str, current_user: User = Depends(get_current_user)):
    """Download a file from MinIO.

    安全最佳实践: 验证 object_name 属于当前用户命名空间。
    """
    try:
        safe_name = _safe_object_name(object_name, current_user)
        response = storage_service.get_file_stream(safe_name)
        if not response:
            raise HTTPException(status_code=404, detail="File not found")

        from fastapi.responses import StreamingResponse
        import urllib.parse

        def iterfile():
            try:
                for data in response.stream(32*1024):
                    yield data
            finally:
                response.close()
                response.release_conn()

        filename = object_name.split('/')[-1]
        # Handle unicode filename for Content-Disposition
        encoded_filename = urllib.parse.quote(filename)

        return StreamingResponse(
            iterfile(),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"}
        )
    except Exception as e:
        logger.error(f"Error downloading file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/preview/{object_name:path}")
async def preview_file(object_name: str, current_user: User = Depends(get_current_user)):
    """Preview a file from MinIO (inline).

    安全最佳实践: 验证 object_name 属于当前用户命名空间。
    """
    try:
        import tempfile
        import os
        from src.utils.preview_utils import get_preview_response

        safe_name = _safe_object_name(object_name, current_user)
        response = storage_service.get_file_stream(safe_name)
        if not response:
            raise HTTPException(status_code=404, detail="File not found")

        suffix = os.path.splitext(object_name)[1]
        if not suffix:
            suffix = ".txt"

        # Create temp file
        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)

        try:
            with open(tmp_path, 'wb') as f:
                for chunk in response.stream(32*1024):
                    f.write(chunk)
        finally:
            response.close()
            response.release_conn()

        # Get preview response
        return get_preview_response(tmp_path, suffix.lstrip('.'))

    except Exception as e:
        logger.error(f"Error previewing file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...), prefix: str = "",
    current_user: User = Depends(get_current_user),
):
    """Upload a file to MinIO.

    安全最佳实践: 文件存储在用户专属命名空间 user_{id}/ 下，防止 IDOR。
    """
    try:
        content = await file.read()
        # 安全最佳实践: 文件名净化，防止路径穿越
        safe_filename = file.filename.replace("..", "").replace("/", "_").lstrip("\\")
        if not safe_filename:
            raise HTTPException(status_code=400, detail="Invalid filename")
        user_prefix = _user_prefix(current_user)
        # 组合完整的 object_name: user_{id}/{prefix}/{filename}
        parts = [user_prefix]
        if prefix:
            # 净化 prefix
            safe_prefix = prefix.replace("..", "").lstrip("/")
            if safe_prefix:
                parts.append(safe_prefix)
        parts.append(safe_filename)
        object_name = "/".join(parts)
        storage_service.upload_file(object_name, content, file.content_type)
        return {"message": "File uploaded successfully", "object_name": object_name}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/batch-delete")
async def batch_delete_files(
    request: BatchDeleteRequest, current_user: User = Depends(get_current_user),
):
    """Batch delete files from MinIO.

    安全最佳实践: 只删除当前用户命名空间下的文件。
    """
    try:
        # 安全最佳实践: 对每个 object_name 应用用户前缀
        safe_names = [_safe_object_name(name, current_user) for name in request.object_names]
        storage_service.batch_delete_files(safe_names)
        return {"message": f"Deleted {len(safe_names)} files"}
    except Exception as e:
        logger.error(f"Error batch deleting files: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/url/{object_name:path}")
async def get_file_url(object_name: str, current_user: User = Depends(get_current_user)):
    """Get a presigned URL for a file.

    安全最佳实践: 验证 object_name 属于当前用户命名空间。
    """
    safe_name = _safe_object_name(object_name, current_user)
    url = storage_service.get_file_url(safe_name)
    if not url:
        raise HTTPException(status_code=404, detail="File not found or error generating URL")
    return {"url": url}
