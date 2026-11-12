"""Tests for constants and manifest consistency."""

import json
from pathlib import Path

from custom_components.alarmeringdroid.const import (
    DEFAULT_SCAN_INTERVAL,
    DIENSTEN,
    DOMAIN,
    MIN_SCAN_INTERVAL,
    REGIOS,
)

ROOT = Path(__file__).parent.parent


def test_manifest_matches_const():
    manifest = json.loads(
        (ROOT / "custom_components/alarmeringdroid/manifest.json").read_text()
    )
    assert manifest["domain"] == DOMAIN
    assert manifest["iot_class"] == "cloud_polling"
    assert manifest["config_flow"] is True
    assert manifest["integration_type"] == "service"
    assert manifest["version"] == "0.1.0"


def test_tables():
    assert 0 not in REGIOS and REGIOS[9] == "Kennemerland" and len(REGIOS) == 25
    assert set(DIENSTEN) == {1, 2, 3, 4, 5}
    assert MIN_SCAN_INTERVAL == 15 and DEFAULT_SCAN_INTERVAL == 60


def test_manifest_after_dependencies_and_key_order():
    manifest = json.loads(
        (ROOT / "custom_components/alarmeringdroid/manifest.json").read_text()
    )
    assert manifest["after_dependencies"] == ["zone"]
    keys = list(manifest)
    assert keys[:2] == ["domain", "name"]
    assert keys[2:] == sorted(keys[2:])
