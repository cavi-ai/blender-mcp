"""Refresh or verify the pinned shared schema helper from a Substance MCP checkout."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / 'src/cavi_blender_mcp/_vendor'
SOURCE = 'src/cavi_substance_mcp/core/schema.py'


def sync(source=None, check=False):
    module = VENDOR / 'schema.py'
    origin = VENDOR / 'schema.origin.json'
    raw = (Path(source) / SOURCE).read_bytes() if source else module.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    expected = {'repository': 'https://github.com/cavi-ai/substance-mcp',
                'path': SOURCE, 'sha256': digest}
    if check:
        if module.read_bytes() != raw or json.loads(origin.read_text()) != expected:
            raise ValueError('Shared protocol source differs from its pinned origin')
    else:
        if source is None:
            raise ValueError('Pass the canonical Substance MCP checkout to refresh')
        module.write_bytes(raw)
        origin.write_text(json.dumps(expected, indent=2) + '\n')
    return expected


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', nargs='?', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    print(json.dumps(sync(args.source, args.check)))
