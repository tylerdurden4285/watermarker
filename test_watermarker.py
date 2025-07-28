#!/usr/bin/env python3
"""
Test script for Watermarker CLI and API
"""
import os
import subprocess
import sys
import time
import shutil
from pathlib import Path

import pytest
import requests

# Configuration
API_URL = "http://localhost:8000"
API_KEY = "your-secure-api-key-here"  # Should match your .env file
TEST_FILES = ["test1.jpg", "test2.png"]  # Add test files in the same directory


# Start the FastAPI server in a background process for all API tests. The server
# is launched using the CLI's ``serve`` command and terminated once the test
# session finishes. A short sleep ensures the server is ready before requests.
@pytest.fixture(scope="session", autouse=True)
def start_server() -> None:
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(Path("src").absolute()))
    env.setdefault("API_KEY", API_KEY)

    proc = subprocess.Popen(
        [sys.executable, "-m", "watermarker", "serve"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2)
    try:
        yield
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture
def api_key() -> str:
    """Return the API key for test requests."""
    return os.getenv("API_KEY", API_KEY)


def run_cli() -> subprocess.CompletedProcess:
    """Run the CLI and return the completed process."""
    print("\n=== Testing CLI Interface ===")

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe not installed")

    # Create simple image files if they don't exist
    colors = ["red", "blue"]
    for filename, color in zip(TEST_FILES, colors):
        if not os.path.exists(filename):
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    f"color=c={color}:s=64x64",
                    "-frames:v",
                    "1",
                    filename,
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    # Test basic watermarking
    cmd = [
        sys.executable,
        "-m",
        "watermarker",
        "TEST_WATERMARK",
        *TEST_FILES,
        "--bottom-right",
        "--quality",
        "90",
    ]

    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(Path("src").absolute()))

    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)

    return result


def test_cli() -> None:
    """Ensure the CLI executes successfully."""
    result = run_cli()
    assert result.returncode == 0, result.stderr


def test_api_health() -> None:
    """Test API health check endpoint."""
    response = requests.get(f"{API_URL}/health")
    response.raise_for_status()
    assert response.status_code == 200


def test_upload_file(api_key: str) -> None:
    """Test file upload and watermarking via API."""
    print("\n=== Testing File Upload API ===")

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe not installed")

    # Create a small JPEG test file
    test_file = "test_upload.jpg"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=green:s=64x64",
            "-frames:v",
            "1",
            test_file,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        with open(test_file, "rb") as f:
            files = {"file": (test_file, f, "image/jpeg")}
            data = {"text": "API_TEST", "position": "center"}
            headers = {"X-API-Key": api_key}

            response = requests.post(
                f"{API_URL}/api/v1/watermark/upload",
                files=files,
                data=data,
                headers=headers,
            )
            response.raise_for_status()
            assert response.status_code == 202
            task_id = response.json().get("task_id")
            assert task_id is not None
            assert wait_for_task_completion(task_id, api_key)
            return

    except Exception as e:
        print(f"✗ Upload error: {str(e)}")
        raise
    finally:
        # Clean up test file
        if os.path.exists(test_file):
            os.remove(test_file)


def test_upload_file_query_param(api_key: str) -> None:
    """Test upload using the authkey query parameter."""

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe not installed")

    test_file = "test_upload_qp.jpg"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=yellow:s=64x64",
            "-frames:v",
            "1",
            test_file,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        with open(test_file, "rb") as f:
            files = {"file": (test_file, f, "image/jpeg")}
            data = {"text": "API_TEST", "position": "center"}

            response = requests.post(
                f"{API_URL}/api/v1/watermark/upload?authkey={api_key}",
                files=files,
                data=data,
            )
            response.raise_for_status()
            assert response.status_code == 202
            task_id = response.json().get("task_id")
            assert task_id is not None
            assert wait_for_task_completion(task_id, api_key)
            return
    finally:
        if os.path.exists(test_file):
            os.remove(test_file)


def test_upload_with_extra_args(api_key: str) -> None:
    """Ensure optional parameters are accepted for watermarking."""

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe not installed")

    test_file = "test_extra.jpg"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=purple:s=64x64",
            "-frames:v",
            "1",
            test_file,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        with open(test_file, "rb") as f:
            files = {"file": (test_file, f, "image/jpeg")}
            data = {
                "text": "EXTRA",
                "position": "center",
                "font_size": 20,
                "padding": 5,
                "font_color": "FF0000",
                "border_color": "00FF00",
                "border_thickness": 3,
            }
            headers = {"X-API-Key": api_key}

            response = requests.post(
                f"{API_URL}/api/v1/watermark/upload",
                files=files,
                data=data,
                headers=headers,
            )
            response.raise_for_status()
            assert response.status_code == 202
            task_id = response.json().get("task_id")
            assert task_id is not None
            assert wait_for_task_completion(task_id, api_key)
            return
    finally:
        if os.path.exists(test_file):
            os.remove(test_file)


def test_video_sample(api_key: str) -> None:
    """Upload a video to /video-sample and ensure JPEG bytes are returned."""

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe not installed")

    sample_video = "sample.mp4"
    # Create a small 1 second dummy video using ffmpeg
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=1:size=128x128:rate=1",
            sample_video,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        with open(sample_video, "rb") as f:
            files = {"file": (sample_video, f, "video/mp4")}
            headers = {"X-API-Key": api_key}
            data = {"font_file": "Nakana.otf"}

            response = requests.post(
                f"{API_URL}/video-sample",
                files=files,
                data=data,
                headers=headers,
            )
        response.raise_for_status()
        assert response.status_code == 200
        assert response.headers.get("content-type") == "image/jpeg"
        assert response.content.startswith(b"\xff\xd8")
    finally:
        if os.path.exists(sample_video):
            os.remove(sample_video)


def check_task_status(task_id: str, api_key: str) -> str:
    """Return the status of a background task."""
    print(f"\nChecking task status for {task_id}...")

    headers = {"X-API-Key": api_key}
    response = requests.get(
        f"{API_URL}/api/v1/tasks/{task_id}",
        headers=headers,
    )
    response.raise_for_status()

    task = response.json()
    status = task.get("status")
    print(f"Task status: {status}")
    print(f"Progress: {task.get('result', {}).get('progress', 0)}%")
    return status


def wait_for_task_completion(task_id: str, api_key: str, timeout: int = 60) -> bool:
    """Wait for a task to complete with a timeout."""
    start_time = time.time()

    while time.time() - start_time < timeout:
        status = check_task_status(task_id, api_key)
        if status == "completed":
            print("✓ Task completed successfully")
            return True
        if status in {"failed", "error"}:
            pytest.fail(f"Task {task_id} failed")
        time.sleep(2)

    pytest.fail("Task timed out")
    return False
