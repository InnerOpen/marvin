"""`task dev:generate` must be a no-op: the generated schema re-exports are the committed ones."""

import importlib.util
from pathlib import Path

import pytest

GENERATOR = Path(__file__).resolve().parents[1] / "src" / "dev" / "code_generation" / "gen_py_schema_exports.py"

spec = importlib.util.spec_from_file_location("gen_py_schema_exports", GENERATOR)
assert spec and spec.loader
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)

PACKAGES = gen.generated_packages()


def test_generator_owns_some_packages():
    assert PACKAGES, "no schema package opens with the generated-file header"


@pytest.mark.parametrize("package", PACKAGES, ids=lambda p: p.name)
def test_schema_exports_match_generator(package: Path):
    committed = (package / "__init__.py").read_text()
    assert committed == gen.render(package), f"run `task dev:generate` to refresh schemas/{package.name}/__init__.py"
