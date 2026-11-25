"""Make a 2:1 panorama wrap horizontally without resampling its longitude; save it as PNG or EXR."""

import struct
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


def linear(code, white):
    """Scene-linear value of an 8-bit sRGB code; inverse Reinhard maps code 255 to ``white``."""
    encoded = code / 255
    decoded = encoded / 12.92 if encoded <= 0.04045 else ((encoded + 0.055) / 1.055) ** 2.4
    return decoded / (1 - decoded * (1 - 1 / white))


def attribute(name, kind, value):
    return b"%s\0%s\0" % (name, kind) + struct.pack("<i", len(value)) + value


def save_exr(image, path, white):
    """Write an RGB image as uncompressed scanline OpenEXR with half-float B, G and R channels."""
    width, height = image.size
    halves = [struct.pack("<e", linear(code, white)) for code in range(256)]
    low, high = bytes(half[0] for half in halves), bytes(half[1] for half in halves)
    planes = {}
    for name, band in zip((b"R", b"G", b"B"), image.convert("RGB").split(), strict=True):
        codes = band.tobytes()
        plane = bytearray(2 * len(codes))
        plane[0::2], plane[1::2] = codes.translate(low), codes.translate(high)
        planes[name] = plane
    window = struct.pack("<4i", 0, 0, width - 1, height - 1)
    channels = b"".join(name + b"\0" + struct.pack("<iB3x2i", 1, 0, 1, 1) for name in (b"B", b"G", b"R"))
    header = b"".join((
        b"\x76\x2f\x31\x01", struct.pack("<i", 2),
        attribute(b"channels", b"chlist", channels + b"\0"),
        attribute(b"compression", b"compression", b"\0"),
        attribute(b"dataWindow", b"box2i", window), attribute(b"displayWindow", b"box2i", window),
        attribute(b"lineOrder", b"lineOrder", b"\0"),
        attribute(b"pixelAspectRatio", b"float", struct.pack("<f", 1)),
        attribute(b"screenWindowCenter", b"v2f", struct.pack("<2f", 0, 0)),
        attribute(b"screenWindowWidth", b"float", struct.pack("<f", 1)), b"\0"))
    row = 6 * width
    first = len(header) + 8 * height
    offsets = struct.pack(f"<{height}Q", *(first + y * (8 + row) for y in range(height)))
    with open(path, "wb") as output:
        output.write(header + offsets)
        for y in range(height):
            output.write(struct.pack("<2i", y, row))
            for name in (b"B", b"G", b"R"):
                output.write(planes[name][2 * width * y:2 * width * (y + 1)])


if __name__ == "__main__":
    with Image.open(sys.argv[1]) as raw:
        wrapped = wrap(raw, int(sys.argv[3]))
    if sys.argv[2].lower().endswith(".exr"):
        save_exr(wrapped, sys.argv[2], float(sys.argv[4]))
    else:
        wrapped.save(sys.argv[2], format="PNG")
