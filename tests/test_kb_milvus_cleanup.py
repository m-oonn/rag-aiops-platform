"""删除 KB 时 Milvus 向量清理测试。"""

from unittest.mock import patch, MagicMock

from src.api.routers.knowledge_base import delete_knowledge_base
from src.database.models import KnowledgeBase


class TestKBMilvusCleanup:
    """验证删除知识库时会清理 Milvus 中的向量。"""

    def test_delete_kb_calls_milvus_cleanup(self, db, test_user):
        """删除 KB 应调用 vector_db 按 kb_id 删除向量。"""
        kb = KnowledgeBase(
            name="Test KB",
            kb_uid="test-uid",
            owner_id=test_user.id,
        )
        db.add(kb)
        db.commit()
        db.refresh(kb)

        with patch("src.api.routers.knowledge_base.vector_db_client") as mock_client:
            delete_knowledge_base(kb.id, test_user, db)

            mock_client.delete_by_kb_id.assert_called_once_with(kb.id)
