Minecraft Java Edition ASCII OCR prototype
================================================

Purpose
-------
This is a UI-free prototype for testing only the recognition logic.
It does not include Minecraft font data or sample screenshots.

Requirements
------------
- Python 3.11 or later
- Pillow
- NumPy

Install dependencies:

    python -m pip install -r requirements.txt

Directory layout
----------------

    mcocr-prototype/
      main.py
      config.json
      requirements.txt
      mcocr/
        __init__.py
        profile.py
        preprocess.py
        recognizer.py
      profiles/
        java_default_ascii.json
      data/
        fonts/
          java_default_ascii/
            ascii.png            <- PUT THE FONT ATLAS HERE
      samples/
        input.png                <- PUT A SCREENSHOT/CROP HERE

Font data placement
-------------------
Place the Minecraft Java ASCII font atlas at:

    data/fonts/java_default_ascii/ascii.png

The supplied profile assumes:

- 16 columns x 16 rows
- each cell is 8 x 8 pixels
- printable ASCII occupies code points 32 through 126
- cells are ordered from code point 0
- transparent or dark atlas background, bright/opaque glyphs

If the source image differs, edit:

    profiles/java_default_ascii.json

Examples:

1. Check configuration and font loading

    python main.py --check

2. Recognize an image

    python main.py samples/input.png

3. Override Minecraft GUI scale

    python main.py samples/input.png --gui-scale 4

4. Show diagnostic values on stderr

    python main.py samples/input.png --gui-scale 4 --verbose

5. Save only recognized text

    python main.py samples/input.png > result.txt

Python API
----------

    from mcocr import MinecraftOCR

    ocr = MinecraftOCR("config.json")
    result = ocr.recognize_file("samples/input.png", gui_scale=3)

    print(result.text)
    print(result.score)

Output policy
-------------
Normal CLI output writes only recognized text to stdout.
With --verbose, score/profile/mask/grid information is written to stderr.
No clipboard and no GUI are used.

config.json
-----------

profile
    Path to the font profile JSON.

gui_scale
    Minecraft GUI scale used by the screenshot. Can be overridden by CLI.

binarization.mode
    auto  : try luma masks and common color masks
    luma  : try bright/dark luma masks only
    color : use colors listed in binarization.colors

binarization.colors
    RGB colors, for example:

        "colors": [[255, 255, 255], [255, 255, 85]]

    Use this when automatic foreground detection is unstable.

binarization.color_tolerance
    Allowed RGB distance around configured/auto colors.

binarization.luma_threshold
    null means automatic Otsu threshold. An integer 0-255 fixes it.

recognition.block_occupancy_threshold
    Fraction of pixels in each GUI-scale block required to treat it as ink.

recognition.missing_pixel_weight
    Penalty for font pixels absent from the screenshot.

recognition.extra_pixel_weight
    Penalty for screenshot pixels absent from the font template.

recognition.max_cost_per_glyph
    Reject a glyph candidate if its normalized mismatch exceeds this value.

recognition.beam_width
    Number of partial line-recognition candidates retained.

Profile JSON
------------

atlas.path
    Font atlas image path, relative to the profile JSON.

atlas.columns / atlas.rows
    Number of cells in the atlas.

atlas.cell_width / atlas.cell_height
    Unscaled glyph-cell size.

atlas.mask_mode
    alpha : use alpha channel
    luma  : use bright pixels
    auto  : alpha if transparency exists, otherwise luma

mapping.first_codepoint
    Code point assigned to atlas cell 0.

mapping.include
    Inclusive code-point range to load. The supplied profile uses ASCII 32-126.

mapping.exclude
    Code points to skip.

advances.mode
    ink_right_plus_one : rightmost ink column plus one blank column
    fixed              : use advances.default for all glyphs

advances.space
    Width of an ASCII space at font scale 1.

advances.overrides
    Per-code-point width overrides, for example:

        "overrides": {
          "73": 4,
          "105": 2
        }

Prototype limitations
---------------------
- Java Edition only
- printable ASCII only
- standard horizontal GUI text
- no Japanese/Unicode handling
- no dictionary correction
- no bold/italic handling yet
- no perspective/3D text handling
- automatic foreground extraction is experimental
- recognition parameters will need tuning against real screenshots

The source data is intentionally separate from the code. Replacing the atlas or
editing the profile does not require modifying Python files.
