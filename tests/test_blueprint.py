"""Tests for the notification blueprint."""

from pathlib import Path

from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.blueprint import models
from homeassistant.util.yaml import loader

BLUEPRINT = (
    Path(__file__).parent.parent
    / "blueprints/automation/alarmeringdroid/notify_p2000.yaml"
)


def test_blueprint_valid():
    data = loader.load_yaml(str(BLUEPRINT))
    blueprint = models.Blueprint(
        data,
        path=str(BLUEPRINT),
        expected_domain="automation",
        schema=AUTOMATION_BLUEPRINT_SCHEMA,
    )
    assert blueprint.domain == "automation"
    assert {"search", "notify_device", "only_prio1", "include_followups"} <= set(
        blueprint.inputs
    )
    assert data["blueprint"]["source_url"].endswith("notify_p2000.yaml")
    assert data["triggers"][0]["event_type"] == "alarmeringdroid_message"
