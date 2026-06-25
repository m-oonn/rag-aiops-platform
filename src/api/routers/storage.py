from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Body
from typing import List, Optional
from src.services.storage import storage_service
from src.utils.logger import logger
from pydantic import BaseModel

router = APIRouter()

class BatchDeleteRequest(BaseModel):
    object_names: List[str]

@router.get("/files")
async def list_files(prefix: str = "", sort_by: str = "last_modified", order: str = "desc", search_query: str = ""):
    """List files in the MinIO bucket."""
    try:
        files = storage_service.list_files(prefix, sort_by, order, search_query)
        return {"files": files}
    except Exception as e:
        logger.error(f"Error listing files: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/download/{object_name:path}")
async def download_file(object_name: str):
    """Download a file from MinIO."""
    try:
        response = storage_service.get_file_stream(object_name)
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
async def preview_file(object_name: str):
    """Preview a file from MinIO (inline)."""
    try:
        import tempfile
        import os
        from src.utils.preview_utils import get_preview_response
        
        response = storage_service.get_file_stream(object_name)
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
async def upload_file(file: UploadFile = File(...), prefix: str = ""):
    """Upload a file to MinIO."""
    try:
        content = await file.read()
        object_name = f"{prefix}/{file.filename}" if prefix else file.filename
        storage_service.upload_file(object_name, content, file.content_type)
        return {"message": "File uploaded successfully", "object_name": object_name}
    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/batch-delete")
async def batch_delete_files(request: BatchDeleteRequest):
    """Batch delete files from MinIO."""
    try:
        storage_service.batch_delete_files(request.object_names)
        return {"message": f"Deleted {len(request.object_names)} files"}
    except Exception as e:
        logger.error(f"Error batch deleting files: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/url/{object_name:path}")
async def get_file_url(object_name: str):
    """Get a presigned URL for a file."""
    url = storage_service.get_file_url(object_name)
    if not url:
        raise HTTPException(status_code=404, detail="File not found or error generating URL")
    return {"url": url}
