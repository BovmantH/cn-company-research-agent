from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BLUEPRINT = """services:
  - type: web
    name: cn-company-research-agent
    runtime: docker
    plan: free
    region: singapore
    dockerfilePath: ./Dockerfile
    healthCheckPath: /health
    autoDeployTrigger: commit
"""


def test_render_blueprint_declares_single_free_docker_service() -> None:
    blueprint = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert blueprint == EXPECTED_BLUEPRINT


def test_render_blueprint_does_not_declare_secrets() -> None:
    blueprint = (ROOT / "render.yaml").read_text(encoding="utf-8")
    forbidden = ("envVars:", "secretFiles:", "MONGODB_URI", "API_KEY", "TOKEN")
    assert all(value not in blueprint for value in forbidden)


def test_dockerfile_uses_platform_port_and_public_bind_address() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "--host 0.0.0.0" in dockerfile
    assert "--port ${PORT:-8000}" in dockerfile
