# Watermarker

A powerful tool for adding text watermarks to images and videos, available as both a command-line interface (CLI) and a FastAPI web service. Built with Python and FFmpeg.

## 🌟 Features

- **Dual Interface**: Use as a CLI tool or a REST API
- **Batch Processing**: Process multiple files in one go
- **Flexible Positioning**: Place watermarks in any corner or center
- **Customizable**: Control font, size, color, and border of watermarks
- **Background Processing**: Long-running tasks are handled asynchronously
- **Progress Tracking**: Monitor task progress via API
- **Retry Mechanism**: Automatic retries for failed operations
- **Format Support**: Works with common image and video formats
- **Secure**: API key authentication for web service

## 🚀 Quick Start

### Prerequisites

- Python 3.8+
- FFmpeg (for video processing)

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/watermarker.git
   cd watermarker
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Install FFmpeg (if not already installed):
   ```bash
   # Ubuntu/Debian
   sudo apt-get update && sudo apt-get install -y ffmpeg
   
   # macOS
   brew install ffmpeg
   
   # Windows (using Chocolatey)
   choco install ffmpeg
   ```

4. Configure the application by copying and editing the example `.env` file:
   ```bash
   cp .env.example .env
   # Edit .env with your preferred settings
   ```

## ⚙️ Configuration

Edit the `.env` file to customize the application:

```ini
# --- Watermark Settings ---
PADDING=10                     # Padding from edges in pixels
FONT_COLOR=FFC0CB              # Hex color code (without #)
FONT_SIZE=46                   # Font size in points
BORDER_COLOR=000000            # Border color (hex)
BORDER_THICKNESS=2             # Border thickness in pixels
OUTPUT_FOLDER=./output         # Where to save watermarked files
FONT_FILE=/path/to/font.ttf    # Path to TTF font file

# --- API Settings ---
API_PORT=8000                  # Port for the web server
API_KEY=your-secure-api-key    # Change this to a secure key
UPLOAD_FOLDER=./uploads        # Where to store uploaded files
MAX_UPLOAD_SIZE_MB=1024        # Max file size in MB (1GB)
```

## 💻 Command Line Usage

### Basic Commands

```bash
# Add watermark to a single file
python -m watermarker "YOUR TEXT" image.jpg

# Process multiple files
python -m watermarker "COPYRIGHT" *.jpg *.png

# Specify output directory
python -m watermarker "CONFIDENTIAL" file.jpg --output-dir ./watermarked

# Adjust quality (1-100)
python -m watermarker "DRAFT" video.mp4 --quality 85
```

### Position Options

```bash
# Position the watermark (default: bottom-right)
python -m watermarker "TOP LEFT" file.jpg --top-left
python -m watermarker "TOP RIGHT" file.jpg --top-right
python -m watermarker "BOTTOM LEFT" file.jpg --bottom-left
python -m watermarker "BOTTOM RIGHT" file.jpg --bottom-right
python -m watermarker "CENTER" file.jpg --center
```

## 🌐 Web API Usage

### Start the API Server

```bash
# Start the API server
python -m watermarker serve
```

The API will be available at `http://localhost:8000` with interactive documentation at `http://localhost:8000/docs`.

### API Endpoints

#### 1. Upload and Watermark

Upload a file and apply a watermark in one request.

```http
POST /api/v1/watermark/upload
Content-Type: multipart/form-data
X-API-Key: your-api-key

file: [binary file data]
text: Your Watermark Text
position: bottom-right  # Optional, default: bottom-right
```

Example with cURL:

```bash
curl -X POST "http://localhost:8000/api/v1/watermark/upload" \
  -H "X-API-Key: your-api-key" \
  -F "file=@/path/to/your/image.jpg" \
  -F "text=SAMPLE_WATERMARK" \
  -F "position=center"
```

#### 2. Batch Processing

Process multiple files by their paths.

```http
POST /api/v1/watermark/batch
Content-Type: application/json
X-API-Key: your-api-key

{
    "file_paths": [
        "/path/to/file1.jpg",
        "/path/to/file2.png"
    ],
    "text": "Your Watermark Text",
    "position": "bottom-right"
}
```

#### 3. Check Task Status

```http
GET /api/v1/tasks/{task_id}
X-API-Key: your-api-key
```

#### 4. Health Check

```http
GET /health
```

### API Response Examples

**Successful Upload Response (202 Accepted):**
```json
{
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "processing",
    "status_url": "/api/v1/tasks/550e8400-e29b-41d4-a716-446655440000"
}
```

**Task Status Response:**
The `result` object includes a `progress` field showing completion percentage.
```json
{
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "completed",
    "created_at": "2025-01-01T12:00:00Z",
    "started_at": "2025-01-01T12:00:01Z",
    "completed_at": "2025-01-01T12:00:05Z",
    "result": {
        "output_path": "/output/watermarked_image_12345.jpg",
        "progress": 100
    },
    "error": null,
    "retry_count": 0,
    "max_retries": 3
}
```

## 🧪 Testing

Run the test suite with:

```bash
# Install test dependencies
pip install -r requirements-dev.txt

# Run tests
pytest
```

## 🛠 Development

### Project Structure

```
watermarker/
├── core/            # Core functionality
│   └── watermark.py # Watermarking logic
├── tasks/           # Background task helpers
├── api.py           # FastAPI application
├── cli.py           # CLI entry point
├── examples/        # Example scripts
├── tests/           # Test files
├── .env             # Configuration
├── requirements.txt       # Production dependencies
└── requirements-dev.txt   # Development dependencies
```

### Adding New Features

1. Create a feature branch:
   ```bash
   git checkout -b feature/new-feature
   ```

2. Make your changes and write tests

3. Run tests and linters:
   ```bash
   pytest
   black .
   isort .
   mypy .
   pylint watermarker/
   ```

4. Commit and push your changes

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Built with [FastAPI](https://fastapi.tiangolo.com/)
- Powered by [FFmpeg](https://ffmpeg.org/)
- Inspired by the need for simple, effective media watermarking
