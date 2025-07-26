#!/usr/bin/env python3
"""FastAPI application for the Watermarker service."""
from __future__ import annotations

import os
from dotenv import load_dotenv
import uuid
import threading
import time
from pathlib import Path
from typing import List, Dict, Any

from fastapi import (
    FastAPI,
    File,
    UploadFile,
    HTTPException,
    Depends,
    status,
    BackgroundTasks,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
import uvicorn
import shutil
import logging

from .core.watermark import apply_watermark, load_config, VALID_EXTENSIONS
from .tasks.watermark import (
    TaskManager,
    TaskStatus,
    process_watermark_task,
    process_batch_task,
)

logger = logging.getLogger(__name__)

# Load environment variables from a .env file if present
load_dotenv()

config = load_config()
os.makedirs(config["upload_folder"], exist_ok=True)

app = FastAPI(
    title="Watermarker API",
    description="API for adding watermarks to images and videos",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEY = os.getenv("API_KEY")
api_key_header = APIKeyHeader(name="X-API-Key")


def get_api_key(api_key: str = Depends(api_key_header)) -> str:
    if not API_KEY:
        raise HTTPException(status_code=500, detail="API key not configured")
    if api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key"
        )
    return api_key


def save_upload_file(upload_file: UploadFile, destination: Path) -> str:
    try:
        file_extension = Path(upload_file.filename).suffix.lower()
        if file_extension not in VALID_EXTENSIONS:
            raise ValueError(f"Unsupported file type: {file_extension}")

        unique_filename = f"{uuid.uuid4()}{file_extension}"
        file_path = destination / unique_filename

        with file_path.open("wb") as buffer:
            shutil.copyfileobj(upload_file.file, buffer)
            size = buffer.tell()

        if size > config["max_upload_size"]:
            file_path.unlink(missing_ok=True)
            raise HTTPException(status_code=413, detail="File too large")

        return str(file_path)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error saving file: {e}")


@app.get("/api/v1/tasks/{task_id}", response_model=dict)
async def get_task_status(task_id: str):
    task = TaskManager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.to_dict()


@app.post("/api/v1/watermark/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_and_watermark(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    text: str = "WATERMARK",
    position: str = "bottom-right",
    api_key: str = Depends(get_api_key),
):
    valid_positions = ["top-left", "top-right", "bottom-left", "bottom-right", "center"]
    if position not in valid_positions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid position. Must be one of: {', '.join(valid_positions)}",
        )

    upload_dir = Path(config["upload_folder"])
    input_path = save_upload_file(file, upload_dir)

    task = TaskManager.create_task()
    background_tasks.add_task(
        process_watermark_task,
        task_id=task.task_id,
        input_path=input_path,
        watermark_text=text,
        position=position,
        config=config,
    )

    return {
        "task_id": task.task_id,
        "status": "processing",
        "status_url": f"/api/v1/tasks/{task.task_id}",
    }


@app.post("/api/v1/watermark/batch", status_code=status.HTTP_202_ACCEPTED)
async def watermark_batch(
    background_tasks: BackgroundTasks,
    file_paths: List[str],
    text: str,
    position: str = "bottom-right",
    api_key: str = Depends(get_api_key),
):
    valid_positions = ["top-left", "top-right", "bottom-left", "bottom-right", "center"]
    if position not in valid_positions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid position. Must be one of: {', '.join(valid_positions)}",
        )

    task = TaskManager.create_task()
    background_tasks.add_task(
        process_batch_task,
        task_id=task.task_id,
        file_paths=file_paths,
        watermark_text=text,
        position=position,
        config=config,
    )

    return {
        "task_id": task.task_id,
        "status": "processing",
        "status_url": f"/api/v1/tasks/{task.task_id}",
        "message": f"Processing {len(file_paths)} files in the background",
    }


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/auth-check")
async def auth_check(api_key: str = Depends(get_api_key)):
    """Verify that the provided API key is valid."""
    return {"authenticated": True}



def run_server() -> None:
    port = int(os.getenv("PORT", os.getenv("API_PORT", 8000)))
    host = os.getenv("HOST", "0.0.0.0")

    def cleanup_loop() -> None:
        while True:
            try:
                cleaned = TaskManager.cleanup_old_tasks(hours=24)
                if cleaned > 0:
                    logger.info("Cleaned up %s old tasks", cleaned)
            except Exception as exc:
                logger.error("Error in cleanup task: %s", exc)
            time.sleep(3600)

    threading.Thread(target=cleanup_loop, daemon=True).start()

    print("\n" + "=" * 60)
    print(f"{'Watermarker API':^60}")
    print("=" * 60)
    print(f"\nAPI running on: http://{host}:{port}")
    print(f"API Documentation: http://{host}:{port}/docs")
    print(f"Upload folder: {os.path.abspath(config['upload_folder'])}")
    print(f"Output folder: {os.path.abspath(config['output_folder'])}")
    print("\nUse Ctrl+C to stop\n")

    uvicorn.run(
        "watermarker.api:app", host=host, port=port, reload=True, log_level="info"
    )
