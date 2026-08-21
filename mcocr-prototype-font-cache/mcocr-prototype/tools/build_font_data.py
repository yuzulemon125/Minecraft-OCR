from __future__ import annotations

import argparse
from pathlib import Path
import json
import sys

# Allow execution as: python tools/build_font_data.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mcocr.profile import load_source_profile, save_compiled_profile


def resolve_from_config(config_path: Path, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = (config_path.parent / path).resolve()
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile a source font atlas into runtime-ready OCR data"
    )
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--profile", default=None, help="source profile JSON override")
    parser.add_argument("--output", default=None, help="compiled .npz output override")
    args = parser.parse_args()

    try:
        config_path = Path(args.config).resolve()
        with config_path.open("r", encoding="utf-8") as f:
            config = json.load(f)

        source_path = resolve_from_config(
            config_path, args.profile or config["source_profile"]
        )
        output_path = resolve_from_config(
            config_path, args.output or config["font_data"]
        )

        profile = load_source_profile(source_path)
        save_compiled_profile(profile, output_path)
        print(f"built: {output_path}")
        print(f"profile: {profile.name}")
        print(f"glyphs: {len(profile.glyphs)}")
        print(f"cell: {profile.cell_width}x{profile.cell_height}")
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
