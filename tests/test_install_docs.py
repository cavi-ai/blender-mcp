import re
import tomllib
import unittest
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
PACKAGE = PROJECT["name"]
(SCRIPT,) = PROJECT["scripts"]
PAGES = {
    ROOT / "README.md": "## Install",
    ROOT / "docs/blender-mcp/source/pages/introduction/installation.md": "## Install the server",
}


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
    def test_install_starts_from_the_published_package(self):
        for page, heading in PAGES.items():
            block = first_block(page.read_text(), heading)
            with self.subTest(page=page.name):
                self.assertIn(f"uv tool install {PACKAGE}", block)
                self.assertNotIn("git clone", block)

    def test_clients_run_the_installed_entry_point(self):
        for page in PAGES:
            text = page.read_text()
            with self.subTest(page=page.name):
                self.assertIn(f'"command": "{SCRIPT}"', text)
                self.assertNotIn("/path/to/blender-mcp/.venv", text)


if __name__ == "__main__":
    unittest.main()
