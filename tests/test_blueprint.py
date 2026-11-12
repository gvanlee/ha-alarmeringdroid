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


def test_blueprint_conditions():
    data = loader.load_yaml(str(BLUEPRINT))
    templates = [c["value_template"] for c in data["conditions"]]
    # A cleared search selector may yield null instead of "".
    assert any("not search or" in t for t in templates)
    assert not any("search == ''" in t for t in templates)
    # Prio-1 filter follows the incident, not just the single message.
    assert any("trigger.event.data.incident_prio1" in t for t in templates)
    assert not any("trigger.event.data.prio1" in t for t in templates)
