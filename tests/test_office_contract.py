"""Schema-level safety guarantee does not require database access."""

from pathlib import Path

import yaml


def test_office_contract_locked_goal_excerpt_null_only():
    path = Path(__file__).resolve().parents[1] / "contracts/openapi/office-v1.yaml"
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert spec["info"]["version"] == "1.2.0"
    assert spec["components"]["schemas"]["ActivePlan"]["properties"]["goal_excerpt"][
        "type"
    ] == "null"
    assert set(spec["paths"]) == {
        "/console/office/api/v1/summary",
        "/console/office/api/v1/agents",
        "/console/office/api/v1/agents/{public_id}",
        "/console/office/api/v1/events",
        "/console/office/portraits/{public_id}",
    }
    assert all(list(item) == ["get"] for item in spec["paths"].values())
