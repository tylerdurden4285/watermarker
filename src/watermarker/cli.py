#!/usr/bin/env python3
"""Command line interface for Watermarker."""
import argparse
import os
import sys
from typing import List
from tqdm import tqdm
from .core.watermark import load_config, process_files



def run_server() -> None:
    """Start the FastAPI server."""
    from .api import run_server

    run_server()


def parse_args(argv: List[str]) -> argparse.Namespace:
    if argv and argv[0] == "serve":
        return argparse.Namespace(command="serve")

    parser = argparse.ArgumentParser(
        description="Add a text watermark to image and video files using ffmpeg.",
        epilog="Example: watermarker \"TEXT\" file1.jpg file2.mp4 --center",
    )
    parser.add_argument("text", help="Watermark text to apply")
    parser.add_argument("files", nargs="+", help="Files to watermark")

    position_group = parser.add_mutually_exclusive_group()
    position_group.add_argument("--top-left", dest="position", action="store_const", const="top-left", help="Place watermark in top-left corner")
    position_group.add_argument("--top-right", dest="position", action="store_const", const="top-right", help="Place watermark in top-right corner")
    position_group.add_argument("--bottom-left", dest="position", action="store_const", const="bottom-left", help="Place watermark in bottom-left corner")
    position_group.add_argument("--bottom-right", dest="position", action="store_const", const="bottom-right", help="Place watermark in bottom-right corner (default)")
    position_group.add_argument("--center", dest="position", action="store_const", const="center", help="Center the watermark")
    parser.set_defaults(position="bottom-right")

    parser.add_argument("--output-dir", type=str, default=None, help="Custom output directory")
    parser.add_argument("--quality", type=int, choices=range(1, 101), metavar="[1-100]", help="Quality setting for output")

    return parser.parse_args(argv)


def cli_main(argv: List[str]) -> int:
    if argv and argv[0] == "serve":
        run_server()
        return 0

    args = parse_args(argv)
    config = load_config()
    if args.output_dir:
        config["output_folder"] = args.output_dir
    if args.quality:
        config["image_quality"] = args.quality
        config["video_quality"] = args.quality

    total_files = len(args.files)
    with tqdm(total=total_files, desc="Watermarking", unit="file") as progress:
        result = process_files(
            args.files,
            args.text,
            position=args.position,
            config=config,
            progress_callback=lambda _i, _t: progress.update(1),
        )

    if result["processed"]:
        for inp, out in result["processed"]:
            print(f"{inp} -> {out}")
    if result["skipped"]:
        for path, reason in result["skipped"]:
            print(f"Skipped {path}: {reason}", file=sys.stderr)

    return 0 if result["processed"] else 1


def main(argv: List[str] | None = None) -> None:
    sys.exit(cli_main(argv or sys.argv[1:]))

