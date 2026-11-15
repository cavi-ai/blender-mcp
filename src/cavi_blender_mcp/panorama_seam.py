"""Make a 2:1 panorama wrap horizontally: fade its last band into its first, then restore the original size."""

import sys

from PIL import Image


def wrap(source, band):
    """The panorama without its last ``band`` columns, whose pixels fade into the first ``band`` instead, so the
    right edge continues into the left; resized back to the source size."""
    image = source.convert("RGB")
    width, height = image.size
    if not 0 < band < width // 2:
        raise ValueError("The seam band must be narrower than half the panorama")
    mask = Image.new("L", (band, 1))
    mask.putdata([round((index + 0.5) / band * 255) for index in range(band)])
    left = image.crop((0, 0, band, height))
    right = image.crop((width - band, 0, width, height))
    wrapped = image.crop((0, 0, width - band, height))
    wrapped.paste(Image.composite(left, right, mask.resize((band, height), Image.NEAREST)), (0, 0))
    return wrapped.resize((width, height), Image.LANCZOS)


if __name__ == "__main__":
    with Image.open(sys.argv[1]) as raw:
        wrap(raw, int(sys.argv[3])).save(sys.argv[2], format="PNG")
