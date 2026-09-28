import pathlib
import re

from odoo.addons.odoo_mcp import tools
from odoo.tests import BaseCase

REPO = pathlib.Path(__file__).resolve().parents[2]
SECTIONS = (
    'Prerequisites', 'API key', 'Endpoint URL', 'Smoke test', 'Client configuration',
    'Cloudflare Access', 'Tools', 'Limits', 'Limitations', 'Troubleshooting',
)


def read(name):
    path = REPO / name
    if not path.exists():
        raise FileNotFoundError(path)
    return path.read_text()


def documented_tools(readme):
    section = readme.split('### Tools', 1)[1].split('\n### ', 1)[0]
    return re.findall(r'^\| `([a-z_]+)` \|', section, re.MULTILINE)


class TestDocs(BaseCase):

    def setUp(self):
        super().setUp()
        try:
            self.readme = read('README.md')
        except FileNotFoundError:
            self.skipTest("README.md is not shipped with the addon")

    def test_required_sections(self):
        self.assertIn('## Connecting an MCP client', self.readme)
        for section in SECTIONS:
            self.assertIn(f'### {section}', self.readme, section)

    def test_tool_table_matches_registry(self):
        self.assertEqual(sorted(documented_tools(self.readme)), [tool['name'] for tool in tools.list_tools()])

    def test_table_parser_detects_drift(self):
        drifted = self.readme.replace('| `unlink` |', '| `unlink_all` |')
        self.assertNotEqual(sorted(documented_tools(drifted)), [tool['name'] for tool in tools.list_tools()])

    def test_status_is_current(self):
        self.assertNotIn('Pre-implementation scaffold', self.readme)
        self.assertIn('[Connecting an MCP client](#connecting-an-mcp-client)', self.readme)

    def test_no_secrets_or_private_hosts(self):
        for name in ('README.md', 'CLAUDE.md'):
            text = read(name)
            self.assertIsNone(re.search(r'[0-9a-f]{32,}', text), name)
            self.assertIsNone(re.search(r'razs\.dev', text), name)
            self.assertIsNone(re.search(r'Bearer (?!<api-key>|\$\{)\S{16,}', text), name)

    def test_claude_md_lists_the_surface(self):
        claude = read('CLAUDE.md')
        for tool in tools.list_tools():
            self.assertIn(f"`{tool['name']}`", claude)
        self.assertIn('resolve_model', claude)
