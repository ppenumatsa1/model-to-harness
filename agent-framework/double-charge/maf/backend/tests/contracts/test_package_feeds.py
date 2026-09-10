import tomllib
from pathlib import Path

LANE = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "azure.yaml").exists() and (parent / "pyproject.toml").exists()
)


def test_python_uses_approved_default_feed():
    project = tomllib.loads((LANE / "pyproject.toml").read_text())
    defaults = [index for index in project["tool"]["uv"]["index"] if index.get("default")]
    assert len(defaults) == 1
    assert defaults[0]["url"] == "https://packagefeedproxy.microsoft.io/pypi/simple/"


def test_frontend_build_loads_approved_npm_feed():
    npmrc = (LANE / "frontend" / ".npmrc").read_text()
    assert npmrc.strip() == "registry=https://packagefeedproxy.microsoft.io/npm/"
    dockerfile = (LANE / "infra" / "app" / "frontend.Dockerfile").read_text()
    assert dockerfile.index("frontend/.npmrc") < dockerfile.index("RUN npm ci")


def test_hosted_install_declares_approved_python_feed():
    requirements = (
        LANE / "infra" / "foundry-hosted" / "agent" / "requirements.txt"
    ).read_text().splitlines()
    assert [line for line in requirements if line.startswith("--index-url")] == [
        "--index-url https://packagefeedproxy.microsoft.io/pypi/simple/"
    ]
