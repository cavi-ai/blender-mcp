"""Add a coincident disconnected quad to the rigged source fixture."""
import os
import runpy
from pathlib import Path

os.environ['CAVI_VERTEX_FIXTURE_DETACHED'] = '1'
runpy.run_path(str(Path(__file__).with_name('vertex_edit_fixture.py')))
