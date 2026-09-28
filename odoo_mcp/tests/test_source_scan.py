import pathlib
import re

from odoo.tests import BaseCase

ADDON = pathlib.Path(__file__).resolve().parent.parent

# Escalation and arbitrary-execution primitives that must never appear in the
# addon's runtime code (CLAUDE.md: no implicit sudo, no eval/SQL/shell).
FORBIDDEN = re.compile(
    r'sudo\(|SUPERUSER_ID|with_user\(|with_env\(|\beval\(|safe_eval|\bexec\(|'
    r'subprocess|os\.system|\.execute\(|getattr\('
)


def runtime_sources():
    return [
        path for path in ADDON.rglob('*.py')
        if 'tests' not in path.relative_to(ADDON).parts
    ]


def find_forbidden(text):
    return FORBIDDEN.findall(text)


class TestSourceScan(BaseCase):

    def test_runtime_sources_are_clean(self):
        sources = runtime_sources()
        self.assertTrue(sources)
        for path in sources:
            self.assertEqual(find_forbidden(path.read_text()), [], str(path))

    def test_scan_detects_forbidden_tokens(self):
        for token in ('env.sudo()', 'SUPERUSER_ID', 'x.with_user(1)', 'eval(x)', 'safe_eval(x)',
                      'cr.execute(q)', 'subprocess.run', 'getattr(a, b)'):
            self.assertTrue(find_forbidden(token), token)


class TestModelAccessGoesThroughResolver(BaseCase):

    def test_tools_never_index_env_with_caller_supplied_names(self):
        # only tools/models.py (the resolver itself) may do `env[...]`
        for path in (ADDON / 'tools').glob('*.py'):
            if path.name == 'models.py':
                continue
            self.assertNotRegex(path.read_text(), r'env\[', str(path))
