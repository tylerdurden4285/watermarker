import os
import re
import subprocess
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Union

# --- Constants ---
VALID_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.mp4', '.mkv', '.mov', '.avi', '.webm')
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff')
SUFFIX = '_watermarked'

class WatermarkError(Exception):
    """Custom exception for watermark-related errors."""
    pass

def get_env_var(key: str, default: str) -> str:
    """Get an environment variable, stripping whitespace and quotes."""
    value = os.getenv(key, default)
    if value is None:
        return default
    return str(value).strip().strip('\'"')

def is_valid_hex_color(color_string: str) -> bool:
    """Check if a string is a valid 6-digit hex color code."""
    if not color_string:
        return False
    return re.match(r'^[0-9a-fA-F]{6}$', color_string) is not None

def escape_ffmpeg_text(text: str) -> str:
    """Escape text for use in an ffmpeg drawtext filter."""
    if not text:
        return ''
    return str(text).replace('\\', '\\\\').replace("'", "'\\\\''").replace(':', '\\\\:')

def verify_ffmpeg() -> None:
    """Ensure ffmpeg command is available."""
    if shutil.which('ffmpeg') is None:
        raise WatermarkError(
            "FFmpeg executable not found. Install FFmpeg and ensure it is in your PATH."
        )

def load_config() -> Dict:
    """Load and validate configuration from environment variables."""
    config = {
        'output_folder': get_env_var('OUTPUT_FOLDER', ''),
        'padding': int(get_env_var('PADDING', '0')),
        'font_color': get_env_var('FONT_COLOR', 'FFC0CB'),
        'border_color': get_env_var('BORDER_COLOR', 'FFFFFF'),
        'border_thickness': int(get_env_var('BORDER_THICKNESS', '2')),
        'font_size': int(get_env_var('FONT_SIZE', '46')),
        'video_quality': int(get_env_var('VIDEO_QUALITY', '18')),
        'image_quality': int(get_env_var('IMAGE_QUALITY', '2')),
        'font_file': get_env_var('FONT_FILE', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
        'upload_folder': get_env_var('UPLOAD_FOLDER', './uploads'),
        'max_upload_size': int(get_env_var('MAX_UPLOAD_SIZE_MB', '1024')) * 1024 * 1024  # Convert MB to bytes
    }
    
    # Create upload folder if it doesn't exist
    os.makedirs(config['upload_folder'], exist_ok=True)
    
    # Create output folder if specified
    if config['output_folder']:
        os.makedirs(config['output_folder'], exist_ok=True)
    
    # Validate hex colors
    if not is_valid_hex_color(config['font_color']):
        raise ValueError(f"Invalid FONT_COLOR '{config['font_color']}'. Must be a 6-digit hex code.")
    
    if not is_valid_hex_color(config['border_color']):
        raise ValueError(f"Invalid BORDER_COLOR '{config['border_color']}'. Must be a 6-digit hex code.")
    
    return config

def get_dimensions(file_path: str) -> Tuple[int, int]:
    """Get width and height of a video or image file using ffprobe."""
    try:
        verify_ffmpeg()
        probe_cmd = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            '-of', 'csv=p=0',
            file_path
        ]
        result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
        return tuple(map(int, result.stdout.strip().split(',')))
    except (subprocess.CalledProcessError, ValueError) as e:
        raise WatermarkError(f"Could not get dimensions for {file_path}: {str(e)}")


def get_video_duration(file_path: str) -> float:
    """Return the duration of a video file in seconds using ffprobe."""
    try:
        verify_ffmpeg()
        probe_cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            file_path,
        ]
        result = subprocess.run(
            probe_cmd, capture_output=True, text=True, check=True
        )
        return float(result.stdout.strip())
    except subprocess.CalledProcessError as e:
        raise WatermarkError(
            f"Could not get duration for {file_path}: {e.stderr}"
        ) from e
    except ValueError as e:
        raise WatermarkError(
            f"Could not parse duration for {file_path}: {e}"
        ) from e

def apply_watermark(
    input_path: str,
    watermark_text: str,
    output_path: Optional[str] = None,
    position: str = 'top-left',
    config: Optional[Dict] = None
) -> str:
    """
    Apply a watermark to a media file.
    
    Args:
        input_path: Path to the input file
        watermark_text: Text to use as watermark
        output_path: Optional output path (default: add _watermarked_timestamp to input filename)
        position: Position of the watermark ('top-left', 'top-right', 'bottom-left', 'bottom-right', 'center')
        config: Optional configuration dictionary (will load from env if not provided)
        
    Returns:
        Path to the watermarked file
    """
    try:
        verify_ffmpeg()
        # Load config if not provided
        if config is None:
            config = load_config()
        
        # Set default output path if not provided
        if output_path is None:
            input_path_obj = Path(input_path)
            timestamp = datetime.now().strftime("%d-%m-%H-%M-%S")
            output_filename = f"{input_path_obj.stem}{SUFFIX}_{timestamp}{input_path_obj.suffix}"
            output_path = str(Path(config['output_folder'] or input_path_obj.parent) / output_filename)
        
        # Ensure output directory exists
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        
        # Escape text and font path for ffmpeg
        escaped_text = escape_ffmpeg_text(watermark_text)
        escaped_font_path = config['font_file'].replace('\\', '/')
        
        # Get dimensions for positioning
        try:
            width, height = get_dimensions(input_path)
        except WatermarkError:
            # If we can't get dimensions, use a default position
            width, height = 1920, 1080
        
        # Calculate position
        if position == 'top-right':
            x = f"w-text_w-{config['padding']}"
            y = config['padding']
        elif position == 'bottom-left':
            x = config['padding']
            y = f"h-text_h-{config['padding']}"
        elif position == 'bottom-right':
            x = f"w-text_w-{config['padding']}"
            y = f"h-text_h-{config['padding']}"
        elif position == 'center':
            x = "(w-text_w)/2"
            y = "(h-text_h)/2"
        else:  # top-left (default)
            x = config['padding']
            y = config['padding']
        
        # Build ffmpeg command
        ffmpeg_cmd = [
            'ffmpeg',
            '-i', input_path,
            '-vf', (
                f"drawtext="
                f"fontfile='{escaped_font_path}':"
                f"text='{escaped_text}':"
                f"x={x}:y={y}:"
                f"fontsize={config['font_size']}:"
                f"fontcolor=0x{config['font_color']}:"
                f"borderw={config['border_thickness']}:bordercolor=0x{config['border_color']}:"
                f"shadowcolor=0x808080:shadowx=3:shadowy=3"
            ),
        ]
        
        # Add quality settings
        is_image = str(input_path).lower().endswith(IMAGE_EXTENSIONS)
        if is_image:
            ffmpeg_cmd.extend(['-q:v', str(config['image_quality'])])
        else:
            ffmpeg_cmd.extend(['-crf', str(config['video_quality']), '-c:a', 'copy'])
        
        # Add output path
        ffmpeg_cmd.extend(['-y', output_path])
        
        # Run ffmpeg
        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, check=True)
        
        if not os.path.exists(output_path):
            raise WatermarkError(f"Failed to create output file: {output_path}")
            
        return output_path
        
    except subprocess.CalledProcessError as e:
        error_msg = f"ffmpeg error: {e.stderr}" if e.stderr else "Unknown ffmpeg error"
        raise WatermarkError(f"Failed to apply watermark: {error_msg}")
    except Exception as e:
        raise WatermarkError(f"Error applying watermark: {str(e)}")

def process_files(
    files: List[str],
    watermark_text: str,
    position: str = 'top-left',
    config: Optional[Dict] = None
) -> Dict[str, Union[List[str], List[str]]]:
    """
    Process multiple files with the same watermark settings.
    
    Args:
        files: List of input file paths
        watermark_text: Text to use as watermark
        position: Position of the watermark
        config: Optional configuration dictionary
        
    Returns:
        Dictionary with 'processed' and 'skipped' file lists
    """
    if config is None:
        config = load_config()
    
    processed = []
    skipped = []
    
    for file_path in files:
        try:
            if not os.path.isfile(file_path):
                skipped.append((file_path, "File not found"))
                continue
                
            if not file_path.lower().endswith(VALID_EXTENSIONS):
                skipped.append((file_path, "Unsupported file type"))
                continue
                
            if SUFFIX in file_path:
                skipped.append((file_path, "Already watermarked"))
                continue
                
            output_path = apply_watermark(file_path, watermark_text, position=position, config=config)
            processed.append((file_path, output_path))
            
        except Exception as e:
            skipped.append((file_path, str(e)))
    
    return {
        'processed': processed,
        'skipped': skipped
    }