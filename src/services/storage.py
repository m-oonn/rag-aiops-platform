from minio import Minio
from src.settings import settings
from src.utils.logger import logger
import io
import urllib3

# MinIO 未启动时,默认客户端会重试+backoff 累积约 30s 才失败,拖垮启动与请求。
# 用短超时 + 零重试的 http_client,让不可用场景快速失败并走降级。
_MINIO_TIMEOUT_SECONDS = 3
_FAST_FAIL_HTTP_CLIENT = urllib3.PoolManager(
    timeout=urllib3.Timeout(connect=_MINIO_TIMEOUT_SECONDS, read=_MINIO_TIMEOUT_SECONDS),
    retries=urllib3.Retry(total=0),
)


class StorageService:
    def __init__(self):
        self.client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
            http_client=_FAST_FAIL_HTTP_CLIENT,
        )
        self.bucket_name = settings.MINIO_BUCKET_NAME
        self._available = self._ensure_bucket()

    def _ensure_bucket(self) -> bool:
        """确保 bucket 存在;MinIO 不可用时降级(返回 False,不阻断启动)。"""
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
                logger.info(f"Created bucket: {self.bucket_name}")
            return True
        except Exception as e:
            logger.warning(f"MinIO 不可用({settings.MINIO_ENDPOINT}),文件存储降级: {e}")
            return False

    def upload_file(self, object_name: str, file_data: bytes, content_type: str = "application/octet-stream"):
        if not self._available:
            raise RuntimeError("MinIO 不可用,无法上传文件")
        try:
            self.client.put_object(
                self.bucket_name,
                object_name,
                io.BytesIO(file_data),
                len(file_data),
                content_type=content_type
            )
            logger.info(f"Uploaded {object_name} to MinIO")
            return True
        except Exception as e:
            logger.error(f"Failed to upload file to MinIO: {e}")
            raise e

    def list_files(self, prefix: str = "", sort_by: str = "last_modified", order: str = "desc", search_query: str = ""):
        if not self._available:
            return []
        try:
            # List all objects (recursive)
            objects = self.client.list_objects(self.bucket_name, prefix=prefix, recursive=True)
            
            file_list = []
            for obj in objects:
                # Filter by search_query (fuzzy match on object name)
                if search_query and search_query.lower() not in obj.object_name.lower():
                    continue
                    
                file_list.append({
                    "object_name": obj.object_name,
                    "size": obj.size,
                    "last_modified": obj.last_modified,
                    "etag": obj.etag
                })
            
            # Sort
            reverse = (order == "desc")
            if sort_by == "last_modified":
                file_list.sort(key=lambda x: x["last_modified"] or "", reverse=reverse)
            elif sort_by == "size":
                file_list.sort(key=lambda x: x["size"], reverse=reverse)
            else: # name
                file_list.sort(key=lambda x: x["object_name"], reverse=reverse)
                
            return file_list
        except Exception as e:
            logger.error(f"Failed to list files from MinIO: {e}")
            return []

    def get_file_stream(self, object_name: str):
        if not self._available:
            return None
        try:
            response = self.client.get_object(self.bucket_name, object_name)
            return response
        except Exception as e:
            logger.error(f"Failed to get file stream: {e}")
            return None

    def get_file_url(self, object_name: str):
        if not self._available:
            return None
        try:
            return self.client.presigned_get_object(self.bucket_name, object_name)
        except Exception as e:
            logger.error(f"Failed to get file URL: {e}")
            return None

    def delete_file(self, object_name: str):
        if not self._available:
            raise RuntimeError("MinIO 不可用,无法删除文件")
        try:
            self.client.remove_object(self.bucket_name, object_name)
            logger.info(f"Deleted {object_name} from MinIO")
            return True
        except Exception as e:
            logger.error(f"Failed to delete file from MinIO: {e}")
            raise e

    def batch_delete_files(self, object_names: list):
        if not self._available:
            raise RuntimeError("MinIO 不可用,无法删除文件")
        try:
            from minio.deleteobjects import DeleteObject
            delete_objects = [DeleteObject(name) for name in object_names]
            errors = self.client.remove_objects(self.bucket_name, delete_objects)
            for error in errors:
                logger.error(f"Error deleting object: {error}")
            logger.info(f"Batch deleted {len(object_names)} files from MinIO")
            return True
        except Exception as e:
            logger.error(f"Failed to batch delete files from MinIO: {e}")
            raise e

storage_service = StorageService()
