"""Background task utilities for watermark processing."""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..core.watermark import apply_watermark

logger = logging.getLogger(__name__)

# In-memory task store
_tasks_db: Dict[str, "Task"] = {}


class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


class Task(BaseModel):
    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    retry_delay: int = 5  # seconds

    def to_dict(self) -> Dict[str, Any]:

        return {
            "task_id": self.task_id,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,

            "result": self.result,

            "error": self.error,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
        }


class TaskManager:
    @staticmethod
    def create_task(max_retries: int = 3, retry_delay: int = 5) -> Task:
        task_id = str(uuid.uuid4())
        task = Task(task_id=task_id, max_retries=max_retries, retry_delay=retry_delay)
        _tasks_db[task_id] = task
        return task

    @staticmethod
    def get_task(task_id: str) -> Optional[Task]:
        return _tasks_db.get(task_id)

    @staticmethod
    def update_task_status(task_id: str, status: TaskStatus, **kwargs) -> Optional[Task]:
        task = _tasks_db.get(task_id)
        if not task:
            return None

        task.status = status
        if status == TaskStatus.PROCESSING and not task.started_at:
            task.started_at = datetime.utcnow()
        elif status in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
            task.completed_at = datetime.utcnow()

        for key, value in kwargs.items():
            if hasattr(task, key):
                setattr(task, key, value)
        return task

    @staticmethod
    def cleanup_old_tasks(hours: int = 24) -> int:
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        to_delete = [tid for tid, t in _tasks_db.items() if t.completed_at and t.completed_at < cutoff]
        for tid in to_delete:
            del _tasks_db[tid]
        return len(to_delete)


async def process_watermark_task(
    task_id: str,
    input_path: str,
    watermark_text: str,
    position: str,
    config: Dict[str, Any],
    retry_count: int = 0,
) -> None:
    task = TaskManager.get_task(task_id)
    if not task:
        return

    try:
        TaskManager.update_task_status(task_id, TaskStatus.PROCESSING)
        output_path = apply_watermark(input_path, watermark_text, position=position, config=config)
        TaskManager.update_task_status(
            task_id, TaskStatus.COMPLETED, result={"output_path": output_path}

        )
        logger.info("Task %s completed successfully", task_id)
    except Exception as exc:
        err = str(exc)
        logger.error("Error in task %s: %s", task_id, err)
        if retry_count < task.max_retries:
            delay = task.retry_delay * (2 ** retry_count)
            logger.info("Retrying task %s in %s seconds", task_id, delay)
            TaskManager.update_task_status(
                task_id, TaskStatus.RETRYING, error=err, retry_count=retry_count + 1
            )
            await asyncio.sleep(delay)
            await process_watermark_task(
                task_id, input_path, watermark_text, position, config, retry_count + 1
            )
        else:
            TaskManager.update_task_status(
                task_id, TaskStatus.FAILED, error=err, retry_count=retry_count
            )


async def process_batch_task(
    task_id: str,
    file_paths: List[str],
    watermark_text: str,
    position: str,
    config: Dict[str, Any],
) -> None:
    task = TaskManager.get_task(task_id)
    if not task:
        return

    try:
        TaskManager.update_task_status(
            task_id,
            TaskStatus.PROCESSING,
            result={"total_files": len(file_paths), "processed": [], "skipped": [], "progress": 0},
        )

        processed: List[tuple[str, str]] = []
        skipped: List[tuple[str, str]] = []
        for idx, file_path in enumerate(file_paths, 1):
            try:
                output = apply_watermark(file_path, watermark_text, position=position, config=config)
                processed.append((file_path, output))
            except Exception as exc:
                logger.error("Error processing %s: %s", file_path, exc)
                skipped.append((file_path, str(exc)))

            progress = int((idx / len(file_paths)) * 100)
            TaskManager.update_task_status(
                task_id,
                TaskStatus.PROCESSING,
                result={
                    "total_files": len(file_paths),
                    "processed": [{"input": p[0], "output": p[1]} for p in processed],
                    "skipped": [{"file": s[0], "reason": s[1]} for s in skipped],
                    "progress": progress,
                },
            )

        TaskManager.update_task_status(
            task_id,
            TaskStatus.COMPLETED,
            result={
                "total_files": len(file_paths),
                "processed": [{"input": p[0], "output": p[1]} for p in processed],
                "skipped": [{"file": s[0], "reason": s[1]} for s in skipped],
                "progress": 100,
            },
        )
    except Exception as exc:
        err = str(exc)
        logger.error("Error in batch task %s: %s", task_id, err)
        TaskManager.update_task_status(
            task_id,
            TaskStatus.FAILED,
            error=err,
            result={
                "total_files": len(file_paths),
                "processed": [{"input": p[0], "output": p[1]} for p in processed] if 'processed' in locals() else [],
                "skipped": [{"file": s[0], "reason": s[1]} for s in skipped] if 'skipped' in locals() else [],
                "progress": progress if 'progress' in locals() else 0,
            },
        )
