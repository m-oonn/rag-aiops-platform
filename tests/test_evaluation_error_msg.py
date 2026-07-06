"""评估任务错误信息持久化测试。"""

from sqlalchemy.orm import sessionmaker

from src.api.routers.evaluation import generate_dataset_task
from src.database.models import EvaluationTask


class TestEvaluationErrorMessage:
    """验证评估任务失败时 error_msg 写入 Task 表。"""

    def test_error_msg_persisted_to_task(self, db, engine):
        """当生成数据集无文档时，Task 的 error_msg 应被设置。"""
        task = EvaluationTask(
            name="test-eval",
            kb_id=None,
            config={"num_questions": 5, "mode": "kb"},
            status=0,
        )
        db.add(task)
        db.commit()
        task_id = task.id

        # 使用独立会话工厂，模拟 Celery 任务的行为
        SessionLocal = sessionmaker(bind=engine)

        def db_session_factory():
            return SessionLocal()

        generate_dataset_task(task_id, db_session_factory)

        # 用新会话查询结果
        with db_session_factory() as fresh_db:
            updated_task = (
                fresh_db.query(EvaluationTask)
                .filter(EvaluationTask.id == task_id)
                .first()
            )
            assert updated_task.status == 3
            assert updated_task.error_msg is not None
            assert "No documents found" in updated_task.error_msg
