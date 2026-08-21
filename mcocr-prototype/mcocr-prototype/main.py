from __future__ import annotations

import argparse
from pathlib import Path
import sys

from mcocr import MinecraftOCR


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Minecraft Java Edition ASCII OCR prototype"
    )
    parser.add_argument(
        "image",
        nargs="?",
        help="PNG screenshot or cropped text image",
    )
    parser.add_argument(
        "--config",
        default="config.json",
        help="configuration file (default: config.json)",
    )
    parser.add_argument(
        "--gui-scale",
        type=int,
        default=None,
        help="override gui_scale in config.json",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="write score and diagnostic information to stderr",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate configuration/font data without recognizing an image",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        ocr = MinecraftOCR(args.config)
        if args.check:
            for message in ocr.check():
                print(message)
            return 0

        if not args.image:
            print("error: image is required unless --check is used", file=sys.stderr)
            return 2

        result = ocr.recognize_file(args.image, gui_scale=args.gui_scale)
        # stdout is reserved for OCR text so it can be redirected to a file.
        if result.text:
            print(result.text)

        if args.verbose:
            print(f"score={result.score:.2f}", file=sys.stderr)
            print(f"profile={result.profile}", file=sys.stderr)
            print(f"mask={result.mask_name}", file=sys.stderr)
            print(
                f"grid_phase={result.grid_phase[0]},{result.grid_phase[1]}",
                file=sys.stderr,
            )
            print(f"lines={result.lines}", file=sys.stderr)

        return 0 if result.text else 1
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
