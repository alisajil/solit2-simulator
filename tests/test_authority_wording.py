"""Displayed text says "PMC / Authority's Engineer", not "AHJ".

The standard's own term ("authorities having jurisdiction") stays wherever the text
is a verbatim quotation of Annex 7, and the `ahj` JSON key and every identifier keep
their names: renaming those would break every saved design. Only text a person reads
is checked, so docstrings and comments are left to developers.
"""
import ast
import re
from pathlib import Path

from solit2.reports import labels

REPO_ROOT = Path(__file__).resolve().parent.parent
SCANNED = ("solit2", "app")
# "authorities having jurisdiction" (plural) is how Annex 7 words itself; a displayed
# quotation of it is left alone. The singular phrase is ours to translate.
ACRONYM = re.compile(r"\bAHJ\b")
SINGULAR = re.compile(r"authority having\s+jurisdiction", re.IGNORECASE)


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                ids.add(id(body[0].value))
    return ids


def _displayed_strings():
    for top in SCANNED:
        for path in sorted((REPO_ROOT / top).rglob("*.py")):
            tree = ast.parse(path.read_text())
            skip = _docstring_ids(tree)
            for node in ast.walk(tree):
                if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                        and id(node) not in skip):
                    yield path.relative_to(REPO_ROOT), node.lineno, node.value


def test_the_authority_is_named_once_and_in_the_indian_project_way():
    assert labels.AUTHORITY == "PMC / Authority's Engineer"


def test_no_displayed_text_says_ahj_or_authority_having_jurisdiction():
    offenders = [f"{path}:{line}: {text[:70]!r}"
                 for path, line, text in _displayed_strings()
                 if ACRONYM.search(text) or SINGULAR.search(text)]
    assert not offenders, "\n".join(offenders)


def test_the_check_would_catch_the_old_wording():
    assert ACRONYM.search("no AHJ limit set")
    assert SINGULAR.search("the authority having\n jurisdiction")
    assert not SINGULAR.search("defined by authorities having jurisdiction")
