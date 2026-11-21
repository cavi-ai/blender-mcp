"""Make a 2:1 panorama wrap horizontally without resampling its longitude."""

import sys

from PIL import Image


def wrap(source, band):
    """Crossfade the last ``band`` columns into the first column and keep the source size.

    Column ``width - 1`` matches column 0. Columns before the band are unchanged, so
    horizontal pixels still span 360 degrees evenly.
    """
    image = source.convert("RGB")
    width, height = image.size
    if not 0 < band < width // 2:
        raise ValueError("The seam band must be narrower than half the panorama")
    right = image.crop((width - band, 0, width, height))
    edge = image.crop((0, 0, 1, height)).resize((band, height), Image.NEAREST)
    mask = Image.new("L", (band, 1))
    mask.putdata([round((index + 1) / band * 255) for index in range(band)])
    blended = Image.composite(edge, right, mask.resize((band, height), Image.NEAREST))
    image.paste(blended, (width - band, 0))
    return image


if __name__ == "__main__":
    with Image.open(sys.argv[1]) as raw:
        wrap(raw, int(sys.argv[3])).save(sys.argv[2], format="PNG")
