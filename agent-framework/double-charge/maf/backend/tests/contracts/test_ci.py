import importlib.util
import inspect
from pathlib import Path
from urllib.parse import urlsplit

import yaml

LANE = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "azure.yaml").exists() and (parent / "pyproject.toml").exists()
)


def test_ci_postgres_configuration_matches_integration_guard(monkeypatch):
    workflow = yaml.safe_load(
        (LANE.parents[2] / ".github" / "workflows" / "maf.yml").read_text()
    )
    job = workflow["jobs"]["test"]
    postgres = job["services"]["postgres"]
    database_url = job["env"]["TEST_DATABASE_URL"]
    parsed = urlsplit(database_url)
    assert job["env"]["DATABASE_URL"] == database_url
    assert parsed.username == postgres["env"]["POSTGRES_USER"]
    assert parsed.password == postgres["env"]["POSTGRES_PASSWORD"]
    assert parsed.path == "/" + postgres["env"]["POSTGRES_DB"]
    assert f"{parsed.port}:5432" in postgres["ports"]
    assert f"-U {parsed.username}" in postgres["options"]
    assert f"-d {postgres['env']['POSTGRES_DB']}" in postgres["options"]

    path = LANE / "backend" / "tests" / "integration" / "conftest.py"
    spec = importlib.util.spec_from_file_location("maf_ci_integration_contract", path)
    assert spec is not None and spec.loader is not None
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    monkeypatch.setenv("TEST_DATABASE_URL", database_url)
    assert inspect.unwrap(fixtures.database_url)() == database_url
