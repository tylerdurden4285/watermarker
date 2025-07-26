#!/usr/bin/env python3
"""
FastAPI application for the Watermarker service.
"""
import os
import uuid
import time
import json
from enum import Enum
from datetime import datetime, timedelta
from fastapi import FastAPI, File, UploadFile, HTTPException, Depends, Header, status, BackgroundTasks
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path
import uvicorn
from typing import List, Optional, Dict, Any
import shutil
import asyncio
from pydantic import BaseModel, Field
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory task store
tasks_db = {}

# Task statuses
class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"

# Task model
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
    
    def to_dict(self):
        return {
            "task_id": self.task_id,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result": self.result,
            "error": self.error,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries
        }

# Task manager
class TaskManager:
    @staticmethod
    def create_task(max_retries: int = 3, retry_delay: int = 5) -> Task:
        task_id = str(uuid.uuid4())
        task = Task(
            task_id=task_id,
            max_retries=max_retries,
            retry_delay=retry_delay
        )
        tasks_db[task_id] = task
        return task
        
    @staticmethod
    def get_task(task_id: str) -> Optional[Task]:
        return tasks_db.get(task_id)
        
    @staticmethod
    def update_task_status(task_id: str, status: TaskStatus, **kwargs):
        if task_id in tasks_db:
            task = tasks_db[task_id]
            task.status = status
            
            if status == TaskStatus.PROCESSING and not task.started_at:
                task.started_at = datetime.utcnow()
            elif status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
                task.completed_at = datetime.utcnow()
                
            for key, value in kwargs.items():
                if hasattr(task, key):
                    setattr(task, key, value)
                    
            return task
        return None
        
    @staticmethod
    def cleanup_old_tasks(hours: int = 24):
        """Remove completed/failed tasks older than specified hours"""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        to_delete = []
        
        for task_id, task in tasks_db.items():
            if task.completed_at and task.completed_at < cutoff:
                to_delete.append(task_id)
                
        for task_id in to_delete:
            del tasks_db[task_id]
            
        return len(to_delete)

from watermarker.core.watermark import (
    apply_watermark, 
    process_files, 
    load_config, 
    WatermarkError,
    VALID_EXTENSIONS
)

# Background task processing
async def process_watermark_task(
    task_id: str,
    input_path: str,
    watermark_text: str,
    position: str,
    config: Dict[str, Any],
    retry_count: int = 0
):
    """Background task to process watermarking with retry logic"""
    task = TaskManager.get_task(task_id)
    if not task:
        return
        
    try:
        TaskManager.update_task_status(task_id, TaskStatus.PROCESSING)
        
        # Apply watermark
        output_path = apply_watermark(
            input_path=input_path,
            watermark_text=watermark_text,
            position=position,
            config=config
        )
        
        # Update task status
        TaskManager.update_task_status(
            task_id=task_id,
            status=TaskStatus.COMPLETED,
            result={"output_path": output_path}
        )
        
        logger.info(f"Task {task_id} completed successfully")
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error in task {task_id}: {error_msg}")
        
        # Check if we should retry
        if retry_count < task.max_retries:
            retry_delay = task.retry_delay * (2 ** retry_count)  # Exponential backoff
            logger.info(f"Retrying task {task_id} in {retry_delay} seconds (attempt {retry_count + 1}/{task.max_retries})")
            
            TaskManager.update_task_status(
                task_id=task_id,
                status=TaskStatus.RETRYING,
                error=error_msg,
                retry_count=retry_count + 1
            )
            
            # Schedule retry
            await asyncio.sleep(retry_delay)
            await process_watermark_task(
                task_id=task_id,
                input_path=input_path,
                watermark_text=watermark_text,
                position=position,
                config=config,
                retry_count=retry_count + 1
            )
        else:
            # Max retries reached, mark as failed
            TaskManager.update_task_status(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error=error_msg,
                retry_count=retry_count
            )

async def process_batch_task(
    task_id: str,
    file_paths: List[str],
    watermark_text: str,
    position: str,
    config: Dict[str, Any]
):
    """Background task to process multiple files with progress tracking"""
    task = TaskManager.get_task(task_id)
    if not task:
        return

    try:
        TaskManager.update_task_status(
            task_id=task_id,
            status=TaskStatus.PROCESSING,
            result={
                "total_files": len(file_paths),
                "processed": [],
                "skipped": [],
                "progress": 0
            }
        )

        processed_count = 0
        processed = []
        skipped = []

        for file_path in file_paths:
            try:
                # Process each file
                output_path = apply_watermark(
                    input_path=file_path,
                    watermark_text=watermark_text,
                    position=position,
                    config=config
                )
                processed.append((file_path, output_path))
            except Exception as e:
                logger.error(f"Error processing {file_path}: {str(e)}")
                skipped.append((file_path, str(e)))
            
            # Update progress
            processed_count += 1
            progress = int((processed_count / len(file_paths)) * 100)
            
            TaskManager.update_task_status(
                task_id=task_id,
                status=TaskStatus.PROCESSING,
                result={
                    "total_files": len(file_paths),
                    "processed": [{"input": p[0], "output": p[1]} for p in processed],
                    "skipped": [{"file": s[0], "reason": s[1]} for s in skipped],
                    "progress": progress
                }
            )

        # Mark as completed
        TaskManager.update_task_status(
            task_id=task_id,
            status=TaskStatus.COMPLETED,
            result={
                "total_files": len(file_paths),
                "processed": [{"input": p[0], "output": p[1]} for p in processed],
                "skipped": [{"file": s[0], "reason": s[1]} for s in skipped],
                "progress": 100
            }
        )

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error in batch task {task_id}: {error_msg}")
        TaskManager.update_task_status(
            task_id=task_id,
            status=TaskStatus.FAILED,
            error=error_msg,
            result={
                "total_files": len(file_paths),
                "processed": [{"input": p[0], "output": p[1]} for p in processed] if 'processed' in locals() else [],
                "skipped": [{"file": s[0], "reason": s[1]} for s in skipped] if 'skipped' in locals() else [],
                "progress": progress if 'progress' in locals() else 0
            }
        )

# Load configuration
config = load_config()

# Create uploads directory if it doesn't exist
os.makedirs(config['upload_folder'], exist_ok=True)

# Initialize FastAPI app
app = FastAPI(
    title="Watermarker API",
    description="API for adding watermarks to images and videos",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Key Authentication
API_KEY = os.getenv('API_KEY')
api_key_header = APIKeyHeader(name="X-API-Key")

def get_api_key(api_key: str = Depends(api_key_header)) -> str:
    if not API_KEY or api_key == API_KEY:
        return api_key
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API Key"
    )

# Helper function to save uploaded file
def save_upload_file(upload_file: UploadFile, destination: Path) -> str:
    try:
        # Create a unique filename to avoid collisions
        file_extension = Path(upload_file.filename).suffix.lower()
        if file_extension not in VALID_EXTENSIONS:
            raise ValueError(f"Unsupported file type: {file_extension}")
            
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        file_path = destination / unique_filename
        
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(upload_file.file, buffer)
            
        return str(file_path)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error saving file: {str(e)}"
        )

# Task Management Endpoints
@app.get("/api/v1/tasks/{task_id}", response_model=dict)
async def get_task_status(task_id: str):
    """Get the status of a background task"""
    task = TaskManager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return task.to_dict()

# Watermarking Endpoints
@app.post("/api/v1/watermark/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_and_watermark(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    text: str = "WATERMARK",
    position: str = "bottom-right",
    api_key: str = Depends(get_api_key),
):
    """
    Upload a file and apply a watermark asynchronously.
    
    - **file**: The image or video file to watermark
    - **text**: The watermark text to apply
    - **position**: Position of the watermark (top-left, top-right, bottom-left, bottom-right, center)
    
    Returns:
        Task ID for tracking the watermarking process
    """
    try:
        # Validate position
        valid_positions = ['top-left', 'top-right', 'bottom-left', 'bottom-right', 'center']
        if position not in valid_positions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid position. Must be one of: {', '.join(valid_positions)}"
            )
        
        # Save uploaded file
        upload_dir = Path(config['upload_folder'])
        input_path = save_upload_file(file, upload_dir)
        
        # Create task
        task = TaskManager.create_task()
        
        # Start background task
        background_tasks.add_task(
            process_watermark_task,
            task_id=task.task_id,
            input_path=input_path,
            watermark_text=text,
            position=position,
            config=config
        )
        
        return {
            "task_id": task.task_id, 
            "status": "processing", 
            "status_url": f"/api/v1/tasks/{task.task_id}"
        }
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error in upload_and_watermark: {error_msg}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred: {error_msg}"
        )

@app.post("/api/v1/watermark/batch", status_code=status.HTTP_202_ACCEPTED)
async def watermark_batch(
    background_tasks: BackgroundTasks,
    file_paths: List[str],
    text: str,
    position: str = "bottom-right",
    api_key: str = Depends(get_api_key),
):
    """
    Apply watermark to multiple files asynchronously.
    
    - **file_paths**: List of file paths to process
    - **text**: The watermark text to apply
    - **position**: Position of the watermark (top-left, top-right, bottom-left, bottom-right, center)
    
    Returns:
        Task ID for tracking the batch processing
    """
    try:
        # Validate position
        valid_positions = ['top-left', 'top-right', 'bottom-left', 'bottom-right', 'center']
        if position not in valid_positions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid position. Must be one of: {', '.join(valid_positions)}"
            )
        
        # Create task
        task = TaskManager.create_task()
        
        # Start background task for batch processing
        background_tasks.add_task(
            process_batch_task,
            task_id=task.task_id,
            file_paths=file_paths,
            watermark_text=text,
            position=position,
            config=config
        )
        
        return {
            "task_id": task.task_id,
            "status": "processing",
            "status_url": f"/api/v1/tasks/{task.task_id}",
            "message": f"Processing {len(file_paths)} files in the background"
        }
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error in watermark_batch: {error_msg}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred: {error_msg}"
        )

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok"}

# CLI compatibility
if __name__ == "__main__":
    import argparse
    import sys
    
    # If run directly, check if it's a CLI command
    if len(sys.argv) > 1 and sys.argv[1] != "serve":
        # CLI mode
        from core.watermark import process_files as cli_process_files
        
        parser = argparse.ArgumentParser(
            description="Add a text watermark to image and video files using ffmpeg.",
            epilog='Example: python -m watermarker "WATERMARK" *.jpg --position bottom-right',
            formatter_class=argparse.RawDescriptionHelpFormatter
        )
        parser.add_argument("text", help="The watermark text to apply.")
        parser.add_argument("files", nargs="+", help="One or more image/video files to watermark.")
        
        position_group = parser.add_mutually_exclusive_group()
        position_group.add_argument('--top-left', action='store_const', const='top-left', 
                                 dest='position', help='Place watermark in top-left corner')
        position_group.add_argument('--top-right', action='store_const', const='top-right',
                                 dest='position', help='Place watermark in top-right corner')
        position_group.add_argument('--bottom-left', action='store_const', const='bottom-left',
                                 dest='position', help='Place watermark in bottom-left corner')
        position_group.add_argument('--bottom-right', action='store_const', const='bottom-right',
                                 dest='position', help='Place watermark in bottom-right corner (default)')
        position_group.add_argument('--center', action='store_const', const='center',
                                 dest='position', help='Center the watermark')
        parser.add_argument('--output-dir', type=str, default=None,
                         help='Custom output directory (default: from .env)')
        parser.add_argument('--quality', type=int, choices=range(1, 101), metavar='[1-100]',
                         help='Quality setting (1-100, higher is better)')
        parser.set_defaults(position='bottom-right')
        
        args = parser.parse_args()
        
        # Override config with CLI args if provided
        cli_config = config.copy()
        if args.output_dir:
            cli_config['output_folder'] = args.output_dir
        if args.quality:
            cli_config['image_quality'] = args.quality
            cli_config['video_quality'] = args.quality
        
        try:
            result = cli_process_files(
                files=args.files,
                watermark_text=args.text,
                position=args.position,
                config=cli_config
            )
            
            # Print results
            if result['processed']:
                print("\nSuccessfully processed:")
                for input_path, output_path in result['processed']:
                    print(f"- {input_path} -> {output_path}")
                    
            if result['skipped']:
                print("\nSkipped:")
                for path, reason in result['skipped']:
                    print(f"- {path}: {reason}")
                    
            # Return appropriate exit code
            sys.exit(0 if not result['skipped'] or result['processed'] else 1)
            
        except Exception as e:
            print(f"Error: {str(e)}", file=sys.stderr)
            sys.exit(1)
            
    else:
        # API mode
        import uvicorn
        import webbrowser
        import threading
        
        port = int(os.getenv('API_PORT', 8000))
        host = os.getenv('HOST', '0.0.0.0')
        
        # Start cleanup thread for old tasks
        def cleanup_loop():
            while True:
                try:
                    cleaned = TaskManager.cleanup_old_tasks(hours=24)  # Cleanup daily
                    if cleaned > 0:
                        logger.info(f"Cleaned up {cleaned} old tasks")
                except Exception as e:
                    logger.error(f"Error in cleanup task: {str(e)}")
                time.sleep(3600)  # Run hourly
        
        cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
        cleanup_thread.start()
        
        # Print startup info
        print("\n" + "="*60)
        print(f"{'Watermarker API':^60}")
        print("="*60)
        print(f"\nAPI running on: http://{host}:{port}")
        print(f"API Documentation: http://{host}:{port}/docs")
        print(f"Upload folder: {os.path.abspath(config['upload_folder'])}")
        print(f"Output folder: {os.path.abspath(config['output_folder'])}")
        print("\nUse Ctrl+C to stop\n")
        
        # Start the server
        uvicorn.run(
            "__main__:app",
            host=host,
            port=port,
            reload=True,
            log_level="info"
        )