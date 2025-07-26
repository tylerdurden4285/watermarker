#!/usr/bin/env python3
"""
Example script demonstrating how to use the Watermarker API
"""
import os
import sys
import requests
from pathlib import Path
from typing import Optional

class WatermarkerClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.headers = {'X-API-Key': self.api_key}
    
    def upload_and_watermark(
        self,
        file_path: str,
        text: str = "WATERMARK",
        position: str = "bottom-right"
    ) -> Optional[dict]:
        """Upload a file and apply watermark"""
        url = f"{self.base_url}/api/v1/watermark/upload"
        
        try:
            with open(file_path, 'rb') as f:
                files = {'file': (os.path.basename(file_path), f, 'application/octet-stream')}
                data = {'text': text, 'position': position}
                
                response = requests.post(
                    url,
                    files=files,
                    data=data,
                    headers=self.headers
                )
                
                if response.status_code == 202:
                    return response.json()
                else:
                    print(f"Error: {response.status_code} - {response.text}")
                    return None
                    
        except Exception as e:
            print(f"Error uploading file: {str(e)}")
            return None
    
    def get_task_status(self, task_id: str) -> Optional[dict]:
        """Get the status of a background task"""
        url = f"{self.base_url}/api/v1/tasks/{task_id}"
        
        try:
            response = requests.get(url, headers=self.headers)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Error: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"Error getting task status: {str(e)}")
            return None

def main():
    # Configuration - Update these values to match your setup
    API_URL = "http://localhost:8000"
    API_KEY = "your-secure-api-key-here"
    
    # File to process - Update this to point to a real file
    FILE_TO_PROCESS = "path/to/your/image.jpg"
    
    # Create client
    client = WatermarkerClient(API_URL, API_KEY)
    
    # Upload and watermark the file
    print(f"Uploading and watermarking {FILE_TO_PROCESS}...")
    result = client.upload_and_watermark(
        file_path=FILE_TO_PROCESS,
        text="SAMPLE_WATERMARK",
        position="bottom-right"
    )
    
    if not result:
        print("Failed to start watermarking task")
        return
    
    task_id = result.get('task_id')
    print(f"Task started with ID: {task_id}")
    print(f"Check status at: {API_URL}/api/v1/tasks/{task_id}")
    
    # Wait for task to complete
    print("\nWaiting for task to complete...")
    while True:
        task = client.get_task_status(task_id)
        if not task:
            print("Error getting task status")
            break
            
        status = task.get('status')
        print(f"Status: {status}")
        
        if status in ['completed', 'failed']:
            if status == 'completed':
                print("\n✓ Watermarking completed successfully!")
                print(f"Output file: {task.get('result', {}).get('output_path')}")
            else:
                print(f"\n✗ Watermarking failed: {task.get('error', 'Unknown error')}")
            break
            
        # Wait before polling again
        import time
        time.sleep(2)

if __name__ == "__main__":
    main()
