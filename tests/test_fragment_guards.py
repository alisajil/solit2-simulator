"""I3: every function decorated with `st.fragment` or `st.dialog` must start with the
session guard (after its docstring, if it has one): `if not auth.guard_fragment(): return`.

A fragment or dialog reruns without passing through the login gate, and Streamlit keeps
a session's stored fragments and dialogs even after a full run the gate stopped -- so a
session that has ended can otherwise still keep rendering, or acting on, one of these
that it registered earlier. This is an AST walk rather than a runtime check, so it also
catches a new fragment or dialog nobody has written a render test for yet.
"""
import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = REPO_ROOT / "app"
_GUARDED_DECORATORS = {"fragment", "dialog"}


def _decorator_name(node: ast.expr) -> str | None:
    """'fragment' or 'dialog' for a bare `@st.fragment` or a called `@st.dialog(...)`;
    None for anything else."""
    target = node.func if isinstance(node, ast.Call) else node
    if (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
            and target.value.id == "st" and target.attr in _GUARDED_DECORATORS):
        return target.attr
    return None


def _is_guard_statement(stmt: ast.stmt) -> bool:
    """Exactly `if not auth.guard_fragment(): return`, with no other body and no else."""
    if not isinstance(stmt, ast.If) or stmt.orelse:
        return False
    test = stmt.test
    if not (isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)):
        return False
    call = test.operand
    if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name) and call.func.value.id == "auth"
            and call.func.attr == "guard_fragment"):
        return False
    return (len(stmt.body) == 1 and isinstance(stmt.body[0], ast.Return)
            and stmt.body[0].value is None)


def _first_statement_after_docstring(body: list[ast.stmt]) -> ast.stmt | None:
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    return body[0] if body else None


def _guarded_functions() -> list[tuple[Path, ast.FunctionDef | ast.AsyncFunctionDef]]:
    found = []
    for path in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if any(_decorator_name(dec) for dec in node.decorator_list):
                found.append((path, node))
    return found


def test_every_fragment_and_dialog_starts_with_the_session_guard():
    offences = []
    for path, node in _guarded_functions():
        first = _first_statement_after_docstring(node.body)
        if first is None or not _is_guard_statement(first):
            offences.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}: {node.name}")
    assert not offences, (
        "every st.fragment/st.dialog function must start with "
        "`if not auth.guard_fragment(): return`:\n  " + "\n  ".join(offences))


def test_the_scan_found_more_than_a_couple_of_guarded_functions():
    """A guard on the guard: an empty or tiny list would make the test above vacuous."""
    assert len(_guarded_functions()) >= 6
