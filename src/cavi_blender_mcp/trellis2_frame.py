"""Frame an image for TRELLIS.2: transparent background, subject at most 512 pixels in a 512-pixel square."""

import sys
from pathlib import Path

from neural_worker import prepare_image


def frame(source):
    return prepare_image(source, background=None, extent=512)


if __name__ == "__main__":
    frame(Path(sys.argv[1])).save(sys.argv[2], format="PNG")
