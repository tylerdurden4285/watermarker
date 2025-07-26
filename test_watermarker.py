#!/usr/bin/env python3
"""
Test script for Watermarker CLI and API
"""
import os
import sys
import subprocess
import requests
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

import pytest

# Configuration
API_URL = "http://localhost:8000"
API_KEY = "your-secure-api-key-here"  # Should match your .env file
TEST_FILES = ["test1.jpg", "test2.png"]  # Add test files in the same directory


@pytest.fixture
def api_key() -> str:
    """Return the API key for test requests."""
    return os.getenv("API_KEY", API_KEY)

def run_cli_test():
    """Test the CLI interface"""
    print("\n=== Testing CLI Interface ===")
    
    # Create test files if they don't exist
    for filename in TEST_FILES:
        if not os.path.exists(filename):
            with open(filename, 'wb') as f:
                f.write(b"Dummy image data")
    
    # Test basic watermarking
    cmd = [
        sys.executable, "-m", "watermarker",
        "TEST_WATERMARK",
        *TEST_FILES,
        "--position", "bottom-right",
        "--quality", "90"
    ]
    
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0:
        print("✓ CLI test completed successfully")
        print(result.stdout)
    else:
        print("✗ CLI test failed")
        print(result.stderr)
    
    return result.returncode == 0

def test_api_health() -> bool:
    """Test API health check endpoint"""
    try:
        response = requests.get(f"{API_URL}/health")
        if response.status_code == 200:
            print("✓ API health check passed")
            return True
        print(f"✗ API health check failed: {response.status_code}")
        return False
    except Exception as e:
        print(f"✗ API health check error: {str(e)}")
        return False

def test_upload_file(api_key: str) -> Optional[str]:
    """Test file upload and watermarking via API"""
    print("\n=== Testing File Upload API ===")
    
    # Create a test file
    test_file = "test_upload.jpg"
    with open(test_file, 'wb') as f:
        f.write(b"Dummy image data")
    
    try:
        with open(test_file, 'rb') as f:
            files = {'file': (test_file, f, 'image/jpeg')}
            data = {
                'text': 'API_TEST',
                'position': 'center'
            }
            headers = {
                'X-API-Key': api_key
            }
            
            response = requests.post(
                f"{API_URL}/api/v1/watermark/upload",
                files=files,
                data=data,
                headers=headers
            )
            
            if response.status_code == 202:
                task_id = response.json().get('task_id')
                print(f"✓ Upload started. Task ID: {task_id}")
                return task_id
            else:
                print(f"✗ Upload failed: {response.status_code} - {response.text}")
                return None
                
    except Exception as e:
        print(f"✗ Upload error: {str(e)}")
        return None
    finally:
        # Clean up test file
        if os.path.exists(test_file):
            os.remove(test_file)

def check_task_status(task_id: str, api_key: str) -> bool:
    """Check the status of a background task"""
    print(f"\nChecking task status for {task_id}...")
    
    try:
        headers = {'X-API-Key': api_key}
        response = requests.get(
            f"{API_URL}/api/v1/tasks/{task_id}",
            headers=headers
        )
        
        if response.status_code == 200:
            task = response.json()
            print(f"Task status: {task.get('status')}")
            print(f"Progress: {task.get('result', {}).get('progress', 0)}%")
            
            if task.get('status') == 'completed':
                print("✓ Task completed successfully")
                return True
            elif task.get('status') in ['failed', 'error']:
                print(f"✗ Task failed: {task.get('error', 'Unknown error')}")
                return False
            
            # Task is still running
            return False
            
        else:
            print(f"✗ Failed to check task status: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        print(f"✗ Error checking task status: {str(e)}")
        return False

def wait_for_task_completion(task_id: str, api_key: str, timeout: int = 60) -> bool:
    """Wait for a task to complete with a timeout"""
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        status = check_task_status(task_id, api_key)
        if status is not None:  # Task completed or failed
            return status
        time.sleep(2)  # Poll every 2 seconds
    
    print("✗ Task timed out")
    return False

def main():
    """Run all tests"""
    print("=== Watermarker Test Script ===\n")
    
    # Check if API is running
    if not test_api_health():
        print("\nPlease start the API server first with: python -m watermarker serve")
        sys.exit(1)
    
    # Test CLI
    cli_success = run_cli_test()
    
    # Test API
    task_id = test_upload_file(API_KEY)
    
    # If upload started, wait for completion
    api_success = False
    if task_id:
        api_success = wait_for_task_completion(task_id, API_KEY)
    
    # Print summary
    print("\n=== Test Summary ===")
    print(f"CLI Test: {'PASSED' if cli_success else 'FAILED'}")
    print(f"API Test: {'PASSED' if api_success else 'FAILED'}")
    
    if cli_success and api_success:
        print("\n✓ All tests passed!")
        sys.exit(0)
    else:
        print("\n✗ Some tests failed")
        sys.exit(1)

if __name__ == "__main__":
    main()
