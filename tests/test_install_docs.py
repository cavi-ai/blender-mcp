import re
import tomllib
import unittest
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
PACKAGE = PROJECT["name"]
(SCRIPT,) = PROJECT["scripts"]
README = ROOT / "README.md"
INSTALL_GUIDE = ROOT / "docs/blender-mcp/source/pages/introduction/installation.md"


def first_block(text, heading):
    section = text[text.index(heading):]
    return re.search(r"```bash\n(.*?)```", section, re.DOTALL).group(1)


class PublishedRequirementsTest(unittest.TestCase):
    def test_mcp_requirement_stays_on_the_installed_major(self):
        # An unlocked install resolves the newest version the metadata allows.
        (requirement,) = [r for r in metadata.requires(PACKAGE) if re.match(r"mcp\b", r)]
        upper = int(re.search(r"<\s*(\d+)", requirement).group(1))
        installed_major = int(metadata.version("mcp").split(".")[0])
        self.assertEqual(upper, installed_major + 1, requirement)


class InstallDocsTest(unittest.TestCase):
    def test_readme_uses_the_current_source_environment(self):
        text = README.read_text()
        block = first_block(text, "## Install")
        self.assertIn("git clone https://github.com/cavi-ai/blender-mcp.git", block)
        self.assertIn("cd blender-mcp", block)
        self.assertIn("uv sync --locked", block)
        self.assertNotIn(f"uv tool install {PACKAGE}", block)
        self.assertIn(f'"command": "/absolute/path/to/blender-mcp/.venv/bin/{SCRIPT}"', text)
        self.assertIn(f".venv/bin/{SCRIPT} runtime start", text)
        self.assertIn(f".venv/bin/{SCRIPT} runtime status", text)
        self.assertNotIn(f'"command": "{SCRIPT}"', text)

    def test_published_guide_uses_the_installed_entry_point(self):
        text = INSTALL_GUIDE.read_text()
        block = first_block(text, "## Install the server")
        self.assertIn(f"uv tool install {PACKAGE}", block)
        self.assertNotIn("git clone", block)
        self.assertIn(f'"command": "{SCRIPT}"', text)
        self.assertNotIn("/path/to/blender-mcp/.venv", text)



if __name__ == "__main__":
    unittest.main()
