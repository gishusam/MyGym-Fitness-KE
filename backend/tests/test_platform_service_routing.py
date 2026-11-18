from __future__ import annotations

import tomllib
from pathlib import Path


def test_platform_api_has_a_dedicated_service_route() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    artifact_path = repo_root / "artifacts/api-server/.replit-artifact/artifact.toml"
    artifact = tomllib.loads(artifact_path.read_text(encoding="utf-8"))
    frontend_config = (repo_root / "artifacts/mygym-fitness-ke/vite.config.ts").read_text(
        encoding="utf-8"
    )

    platform_services = [
        service for service in artifact["services"]
        if service.get("paths") == ["/api/platform"]
    ]

    assert len(platform_services) == 1
    service = platform_services[0]
    assert service["localPort"] == 8083
    assert "backend.platform.app:app" in service["development"]["run"]
    assert "backend.platform.app:app" in service["production"]["run"]["args"]
    assert service["production"]["health"]["startup"]["path"] == "/api/platform/healthz"
    assert "'/api/platform':" in frontend_config
    assert "http://127.0.0.1:8083" in frontend_config
