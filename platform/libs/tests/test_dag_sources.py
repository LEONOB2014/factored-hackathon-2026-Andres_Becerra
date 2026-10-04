"""Static checks of the Airflow DAG sources (no Airflow needed, so they run in CI).

`@task.external_python` ships only the function's own source to the platform venv: names the function uses must be
defined inside it (parameters, local imports, assignments). A module-level import is not there at run time, and
the task fails with NameError only when it runs (compliance_triggers and monitoring_drift did, with `UTC`).
"""

from __future__ import annotations

import ast
import builtins
from pathlib import Path

import pytest

DAGS = Path(__file__).resolve().parents[2] / "airflow" / "dags"


def _is_external_python(fn: ast.FunctionDef) -> bool:
    for d in fn.decorator_list:
        target = d.func if isinstance(d, ast.Call) else d
        if isinstance(target, ast.Attribute) and target.attr == "external_python":
            return True
    return False


def _body_nodes(fn: ast.FunctionDef):
    """Nodes of the body only: decorators and defaults are evaluated in the DAG module, where names exist."""
    for stmt in fn.body:
        yield from ast.walk(stmt)


def _bound(fn: ast.FunctionDef) -> set[str]:
    names = {a.arg for a in [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]}
    names |= {a.arg for a in (fn.args.vararg, fn.args.kwarg) if a}
    for node in _body_nodes(fn):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del):
            names.add(node.id)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            names |= {(a.asname or a.name).split(".")[0] for a in node.names}
        elif (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
            and node is not fn
        ):
            names.add(node.name)
            if not isinstance(node, ast.ClassDef):
                names |= {
                    a.arg for a in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
                }
                names |= {a.arg for a in (node.args.vararg, node.args.kwarg) if a}
        elif isinstance(node, ast.Lambda):
            names |= {
                a.arg for a in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
            }
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
    return names


def _external_tasks():
    for path in sorted(DAGS.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.FunctionDef) and _is_external_python(node):
                yield pytest.param(node, id=f"{path.stem}.{node.name}")


@pytest.mark.parametrize("fn", list(_external_tasks()))
def test_external_python_tasks_define_every_name_they_use(fn: ast.FunctionDef):
    used = {
        n.id for n in _body_nodes(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
    }
    missing = used - _bound(fn) - set(dir(builtins))
    assert not missing, (
        f"not defined inside the task (module scope does not reach the venv): {sorted(missing)}"
    )


def test_the_check_finds_external_python_tasks():
    assert len(list(_external_tasks())) >= 15
