#!/usr/bin/env python3

import os
import sys
import subprocess
import argparse
import shutil
import re
from dotenv import load_dotenv

# --- Helper Functions ---

def get_env_var(key, default):
    """Gets an environment variable, stripping whitespace and quotes."""
    value = os.getenv(key, default)
    if value is None:
        return default
    return str(value).strip().strip('\'"')

def is_valid_hex_color(color_string):
    """Checks if a string is a valid 6-digit hex color code."""
    if not color_string:
        return False
    return re.match(r'^[0-9a-fA-F]{6}$', color_string) is not None

def escape_ffmpeg_text(text):
    """Escapes text for use in an ffmpeg drawtext filter."""
    if not text:
        return ''
    return str(text).replace('\\', '\\\\').replace("'", "'\\\\''").replace(':', '\\\\:')

# --- Constants ---
VALID_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.mp4', '.mkv', '.mov', '.avi', '.webm')
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff')
SUFFIX = '_watermarked'

def load_config():
    """Load and validate configuration from environment variables."""
    # Load environment variables from .env file
    load_dotenv()
    
    try:
        config = {
            'output_folder': get_env_var('OUTPUT_FOLDER', ''),
            'padding': int(get_env_var('PADDING', '10')),
            'font_color': get_env_var('FONT_COLOR', 'FFFFFF'),
            'border_color': get_env_var('BORDER_COLOR', 'FFC0CB'),
            'border_thickness': int(get_env_var('BORDER_THICKNESS', '3')),
            'font_size': int(get_env_var('FONT_SIZE', '48')),
            'video_quality': int(get_env_var('VIDEO_QUALITY', '18')),
            'image_quality': int(get_env_var('IMAGE_QUALITY', '2')),
            'font_file': get_env_var('FONT_FILE', "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
        }
        
        # Validate hex colors
        if not is_valid_hex_color(config['font_color']):
            print(f"Error: Invalid FONT_COLOR '{config['font_color']}' in .env file. It must be a 6-digit hex code.", file=sys.stderr)
            return None
            
        if not is_valid_hex_color(config['border_color']):
            print(f"Error: Invalid BORDER_COLOR '{config['border_color']}' in .env file. It must be a 6-digit hex code.", file=sys.stderr)
            return None
            
        return config
        
    except ValueError as e:
        print(f"Error: Invalid number in .env file: {str(e)}", file=sys.stderr)
        return None

def is_valid_hex_color(color_string):
    """Checks if a string is a valid 6-digit hex color code."""
    return re.match(r'^[0-9a-fA-F]{6}$', color_string) is not None

def escape_ffmpeg_text(text):
    """Escapes text for use in an ffmpeg drawtext filter."""
    # Escape single quotes, backslashes, and colons
    return text.replace('\\', '\\\\').replace("'", "'\\''").replace(':', '\\:')

def main():
    """
    Parses arguments and runs the watermarking process on images and videos.
    """
    # --- Argument Parsing (happens before any other checks) ---
    parser = argparse.ArgumentParser(
        description="Adds a text watermark to image and video files using ffmpeg. Reads settings from a .env file.",
        epilog="Example: python3 watermark.py \"My Watermark\" *.jpg *.mp4"
    )
    parser.add_argument("text", help="The watermark text to apply.")
    parser.add_argument("files", nargs='+', help="One or more image/video files to watermark.")
    
    # Add position arguments (mutually exclusive group)
    position_group = parser.add_mutually_exclusive_group()
    position_group.add_argument('--top-left', action='store_true', help='Place watermark in top-left corner (default)')
    position_group.add_argument('--top-right', action='store_true', help='Place watermark in top-right corner')
    position_group.add_argument('--bottom-left', action='store_true', help='Place watermark in bottom-left corner')
    position_group.add_argument('--bottom-right', action='store_true', help='Place watermark in bottom-right corner')
    position_group.add_argument('--center', action='store_true', help='Center the watermark')
    
    # Add --help flag that works without any arguments
    if '--help' in sys.argv or '-h' in sys.argv:
        parser.print_help()
        return
        
    # --- Check for required tools ---
    if not shutil.which('ffmpeg'):
        print("Error: ffmpeg is not installed or not in your system's PATH.", file=sys.stderr)
        sys.exit(1)
        
    # --- Load configuration ---
    config = load_config()
    if config is None:
        sys.exit(1)
        
    # --- Validate font file ---
    if not os.path.isfile(config['font_file']):
        print(f"Error: Font file not found at '{config['font_file']}'.", file=sys.stderr)
        print("Please update the FONT_FILE variable in your .env file.", file=sys.stderr)
        sys.exit(1)

    # --- Create Output Directory if Specified ---
    if config['output_folder']:
        try:
            os.makedirs(config['output_folder'], exist_ok=True)
            print(f"Output will be saved to folder: '{config['output_folder']}'")
        except OSError as e:
            print(f"Error: Could not create directory '{config['output_folder']}'. Reason: {e}", file=sys.stderr)
            sys.exit(1)

    # --- Process command line arguments ---
    args = parser.parse_args()
    watermark_text = escape_ffmpeg_text(args.text)

    # --- File Validation --- 
    valid_files = []
    skipped_files = []
    for f in args.files:
        if os.path.isfile(f) and f.lower().endswith(VALID_EXTENSIONS) and SUFFIX not in os.path.basename(f):
            valid_files.append(f)
        else:
            skipped_files.append(f)

    if skipped_files:
        print(f"\nSkipping {len(skipped_files)} file(s) (invalid type, already processed, or do not exist):")
        for f in skipped_files:
            print(f"- {f}")
    
    if not valid_files:
        print("\nNo valid files to process. Exiting.")
        sys.exit(0)

    print("\nStarting watermark process...")
    print("---")

    for file_path in valid_files:
        try:
            # --- Construct Output Path ---
            base_filename = os.path.basename(file_path)
            name, ext = os.path.splitext(base_filename)
            
            # Get current timestamp in format DD-MM-HH-MM-SS
            from datetime import datetime
            timestamp = datetime.now().strftime("%d-%m-%H-%M-%S")
            
            # Create output filename with timestamp
            output_filename = f"{name}{SUFFIX}_{timestamp}{ext}"

            # If output_folder is set, use it; otherwise, use the current directory '.'
            output_dir = config['output_folder'] if config['output_folder'] else '.'
            output_path = os.path.join(output_dir, output_filename)

            print(f"Processing: '{file_path}' -> '{output_path}'")

            # In Windows, ffmpeg requires the font file path to be escaped
            escaped_font_path = config['font_file'].replace('\\', '/')
            
            # Get video/image dimensions using ffprobe
            probe_cmd = [
                'ffprobe',
                '-v', 'error',
                '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height',
                '-of', 'csv=p=0',
                file_path
            ]
            
            try:
                result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
                width, height = map(int, result.stdout.strip().split(','))
            except (subprocess.CalledProcessError, ValueError) as e:
                print(f"Warning: Could not get dimensions for {file_path}, using default position. Error: {e}")
                width, height = 1920, 1080  # Default dimensions if probe fails
            
            # Calculate position based on arguments (default is top-left)
            if args.top_right:
                x = f"w-text_w-{config['padding']}"  # Right edge - text width - padding
                y = config['padding']
            elif args.bottom_left:
                x = config['padding']
                y = f"h-text_h-{config['padding']}"  # Bottom edge - text height - padding
            elif args.bottom_right:
                x = f"w-text_w-{config['padding']}"  # Right edge - text width - padding
                y = f"h-text_h-{config['padding']}"  # Bottom edge - text height - padding
            elif args.center:
                x = f"(w-text_w)/2"  # Center horizontally
                y = f"(h-text_h)/2"  # Center vertically
            else:  # Default: top-left
                x = config['padding']
                y = config['padding']

            ffmpeg_cmd = [
                'ffmpeg',
                '-i', file_path,
                '-vf', (
                    f"drawtext="
                    f"fontfile='{escaped_font_path}':"
                    f"text='{watermark_text}':"
                    f"x={x}:y={y}:"
                    f"fontsize={config['font_size']}:"
                    f"fontcolor=0x{config['font_color']}:"
                    f"borderw={config['border_thickness']}:bordercolor=0x{config['border_color']}:"
                    f"shadowcolor=0x808080:shadowx=3:shadowy=3"
                ),
            ]

            # --- Apply Quality Settings ---
            is_image = file_path.lower().endswith(IMAGE_EXTENSIONS)
            if is_image:
                # For images, especially JPEG, -q:v controls quality.
                ffmpeg_cmd.extend(['-q:v', str(config['image_quality'])])
            else:
                # For videos, -crf controls quality. Audio is copied.
                ffmpeg_cmd.extend(['-crf', str(config['video_quality']), '-c:a', 'copy'])

            # Add overwrite flag and output path
            ffmpeg_cmd.extend(['-y', output_path])

            # Set capture_output=False to show ffmpeg's progress bar, which is useful for long video encodes.
            # Note: When False, stdout/stderr are not captured, so error messages will print directly to the console.
            process = subprocess.run(ffmpeg_cmd, check=True, capture_output=False, text=True)
            print(f"Success: Created '{output_path}'")

        except subprocess.CalledProcessError:
            # Error is now printed directly by ffmpeg because capture_output=False
            print(f"\nFailure: ffmpeg encountered an error with '{file_path}'. See the output above for details.", file=sys.stderr)
        except Exception as e:
            print(f"An unexpected error occurred with '{file_path}': {e}", file=sys.stderr)
        finally:
            print("---")

    print("All tasks complete.")

if __name__ == "__main__":
    main()
