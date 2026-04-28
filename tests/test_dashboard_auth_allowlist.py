import ast
from pathlib import Path


def _dashboard_public_paths() -> set[str]:
    """Read the literal auth allowlist without importing Flask dependencies."""
    source = Path("dashboard/command_center.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "_DASH_PUBLIC_PATHS" for t in node.targets)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "frozenset"
        ):
            return set(ast.literal_eval(node.value.args[0]))
    raise AssertionError("_DASH_PUBLIC_PATHS not found")


def test_setup_credential_mutation_endpoints_require_dashboard_auth():
    public_paths = _dashboard_public_paths()

    assert "/setup" in public_paths
    assert "/api/setup/status" in public_paths
    assert "/api/setup/save_keys" not in public_paths
    assert "/api/setup/test_connection" not in public_paths
