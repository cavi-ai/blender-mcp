"""Frame an image for TripoSG: white background, subject at most 427 pixels in a 512-pixel square."""

import sys
from pathlib import Path

from neural_worker import prepare_image


def frame(source):
    return prepare_image(source, background=(255, 255, 255), extent=427)


if __name__ == "__main__":
    frame(Path(sys.argv[1])).save(sys.argv[2], format="PNG")
