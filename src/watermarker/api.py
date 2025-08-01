#!/usr/bin/env python3
"""FastAPI application for the Watermarker service."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
import uuid
import asyncio
from functools import partial
from pathlib import Path
from typing import Any, Dict, List

import uvicorn
from dotenv import load_dotenv, find_dotenv
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import APIKeyHeader, APIKeyQuery
from fastapi.responses import FileResponse

from .core.watermark import (
    VALID_EXTENSIONS,
    apply_watermark,
    get_video_duration,
    load_config,
    ensure_directory,
)
from .tasks.watermark import (
    TaskManager,
    TaskStatus,
    process_batch_task,
    process_watermark_task,
)

logger = logging.getLogger(__name__)

# Load environment variables from a .env file if present
load_dotenv(find_dotenv())

config = load_config()
ensure_directory(config["upload_folder"])

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

# Serve files from the configured output directory if provided
if config["output_folder"]:
    app.mount(
        "/output",
        StaticFiles(directory=config["output_folder"]),
        name="output",
    )

API_KEY = os.getenv("API_KEY")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
api_key_query = APIKeyQuery(name="authkey", auto_error=False)


def get_api_key(
    api_key_header_value: str | None = Depends(api_key_header),
    api_key_query_value: str | None = Depends(api_key_query),
) -> str:
    if not API_KEY:
        raise HTTPException(status_code=500, detail="API key not configured")

    provided_key = api_key_header_value or api_key_query_value

    if provided_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key",
        )

    return provided_key


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
    position: str = "top-left",
    font_file: str | None = None,
    font_size: int | None = None,
    padding: int | None = None,
    font_color: str | None = None,
    border_color: str | None = None,
    border_thickness: int | None = None,
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

    cfg = config.copy()
    if font_file:
        if os.path.isfile(font_file):
            cfg["font_file"] = font_file
        else:
            logger.warning(
                "Font file %s not found, using default %s", font_file, cfg["font_file"]
            )

    task = TaskManager.create_task()
    background_tasks.add_task(
        process_watermark_task,
        task_id=task.task_id,
        input_path=input_path,
        watermark_text=text,
        position=position,
        config=cfg,
        font_size=font_size,
        padding=padding,
        font_color=font_color,
        border_color=border_color,
        border_thickness=border_thickness,
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
    position: str = "top-left",
    font_file: str | None = None,
    font_size: int | None = None,
    padding: int | None = None,
    font_color: str | None = None,
    border_color: str | None = None,
    border_thickness: int | None = None,
    api_key: str = Depends(get_api_key),
):
    valid_positions = ["top-left", "top-right", "bottom-left", "bottom-right", "center"]
    if position not in valid_positions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid position. Must be one of: {', '.join(valid_positions)}",
        )

    cfg = config.copy()
    if font_file:
        if os.path.isfile(font_file):
            cfg["font_file"] = font_file
        else:
            logger.warning(
                "Font file %s not found, using default %s", font_file, cfg["font_file"]
            )

    task = TaskManager.create_task()
    background_tasks.add_task(
        process_batch_task,
        task_id=task.task_id,
        file_paths=file_paths,
        watermark_text=text,
        position=position,
        config=cfg,
        font_size=font_size,
        padding=padding,
        font_color=font_color,
        border_color=border_color,
        border_thickness=border_thickness,
    )

    return {
        "task_id": task.task_id,
        "status": "processing",
        "status_url": f"/api/v1/tasks/{task.task_id}",
        "message": f"Processing {len(file_paths)} files in the background",
    }


@app.post("/video-sample")
async def video_sample(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    text: str = "WATERMARK",
    position: str = "top-left",
    font_file: str | None = None,
    font_size: int | None = None,
    padding: int | None = None,
    font_color: str | None = None,
    border_color: str | None = None,
    border_thickness: int | None = None,
    api_key: str = Depends(get_api_key),
):
    """Return a watermarked frame from the midpoint of the uploaded video."""
    valid_positions = [
        "top-left",
        "top-right",
        "bottom-left",
        "bottom-right",
        "center",
    ]
    if position not in valid_positions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid position. Must be one of: {', '.join(valid_positions)}",
        )

    upload_dir = Path(config["upload_folder"])
    input_path = save_upload_file(file, upload_dir)

    cfg = config.copy()
    if font_file:
        if os.path.isfile(font_file):
            cfg["font_file"] = font_file
        else:
            logger.warning(
                "Font file %s not found, using default %s", font_file, cfg["font_file"]
            )

    try:
        duration = get_video_duration(input_path)
        timestamp = duration / 2

        frame_path = upload_dir / f"{uuid.uuid4()}.jpg"
        ffmpeg_cmd = [
            "ffmpeg",
            "-ss",
            str(timestamp),
            "-i",
            input_path,
            "-frames:v",
            "1",
            "-q:v",
            str(config["image_quality"]),
            "-y",
            str(frame_path),
        ]
        try:
            subprocess.run(ffmpeg_cmd, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as exc:
            logger.warning(
                "Frame grab failed at %s: %s; using first frame", timestamp, exc
            )
            fallback_cmd = [
                "ffmpeg",
                "-i",
                input_path,
                "-frames:v",
                "1",
                "-q:v",
                str(config["image_quality"]),
                "-y",
                str(frame_path),
            ]
            subprocess.run(fallback_cmd, capture_output=True, text=True, check=True)

        loop = asyncio.get_running_loop()
        output_path = await loop.run_in_executor(
            None,
            partial(
                apply_watermark,
                str(frame_path),
                text,
                position=position,
                config=cfg,
                font_size=font_size,
                padding=padding,
                font_color=font_color,
                border_color=border_color,
                border_thickness=border_thickness,
            ),
        )

    finally:
        background_tasks.add_task(os.remove, input_path)
        background_tasks.add_task(os.remove, frame_path)

    return FileResponse(output_path, media_type="image/jpeg")


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/auth-check")
async def auth_check(api_key: str = Depends(get_api_key)):
    """Verify that the provided API key is valid."""
    return {"authenticated": True}


def run_server() -> None:
    port = int(os.getenv("API_PORT", 8000))
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

    reload_flag = os.getenv("RELOAD", "false").lower() in {"1", "true", "yes"}

    uvicorn.run(
        "watermarker.api:app",
        host=host,
        port=port,
        reload=reload_flag,
        log_level="info",
    )
