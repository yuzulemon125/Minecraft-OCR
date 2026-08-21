from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys
import zipfile

from PIL import Image


DEFAULT_MEMBER = "assets/minecraft/textures/font/ascii.png"
DEFAULT_OUTPUT = "data/fonts/java_default_ascii/ascii.png"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract Minecraft Java default ASCII font from a client JAR"
    )
    parser.add_argument(
        "jar",
        help="path to the vanilla Minecraft client JAR",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"output PNG path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--member",
        default=DEFAULT_MEMBER,
        help=f"path inside the JAR (default: {DEFAULT_MEMBER})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing output file",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    jar_path = Path(args.jar).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    if not jar_path.is_file():
        print(f"error: JAR not found: {jar_path}", file=sys.stderr)
        return 2
    if output_path.exists() and not args.force:
        print(
            f"error: output already exists: {output_path}\n"
            "Use --force to overwrite it.",
            file=sys.stderr,
        )
        return 2

    try:
        with zipfile.ZipFile(jar_path) as archive:
            names = set(archive.namelist())
            if args.member not in names:
                similar = sorted(
                    name for name in names
                    if name.endswith("/ascii.png") or "textures/font" in name
                )
                print(
                    f"error: {args.member} was not found in {jar_path}",
                    file=sys.stderr,
                )
                if similar:
                    print("Font-like entries found:", file=sys.stderr)
                    for name in similar[:30]:
                        print(f"  {name}", file=sys.stderr)
                else:
                    print(
                        "This may be a loader/mod JAR rather than the vanilla client JAR.",
                        file=sys.stderr,
                    )
                return 2

            output_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(args.member) as src, output_path.open("wb") as dst:
                shutil.copyfileobj(src, dst)

        with Image.open(output_path) as image:
            width, height = image.size
            mode = image.mode

        print(f"extracted: {output_path}")
        print(f"source: {jar_path}")
        print(f"member: {args.member}")
        print(f"image: {width}x{height}, mode={mode}")

        if (width, height) != (128, 128):
            print(
                "warning: the supplied profile expects a 128x128 atlas "
                "(16x16 cells, 8x8 pixels each).",
                file=sys.stderr,
            )
            print(
                "Edit profiles/java_default_ascii.json if this atlas uses "
                "a different layout.",
                file=sys.stderr,
            )
        return 0
    except zipfile.BadZipFile:
        print(f"error: not a valid ZIP/JAR file: {jar_path}", file=sys.stderr)
        return 2
    except Exception as exc:
        if output_path.exists():
            output_path.unlink(missing_ok=True)
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
