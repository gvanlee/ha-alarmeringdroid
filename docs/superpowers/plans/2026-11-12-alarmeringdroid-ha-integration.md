# AlarmeringDroid P2000 Home Assistant Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A HACS-installable Home Assistant custom integration (`alarmeringdroid`) that polls the AlarmeringDroid `api2` JSON API per user-defined search, exposes a "most recent message" sensor, fires an `alarmeringdroid_message` event per new P2000 message, and ships a notify blueprint.

**Architecture:** Pure-Python core with no HA imports (`api.py` HTTP client, `models.py` parsing, `search.py` input normalization + request building, `tracker.py` dedupe/cursor/client-side filtering) wrapped by thin HA layers (`zone.py`, `coordinator.py`, `config_flow.py`, `sensor.py`, `__init__.py`). One config entry = one search = one `DataUpdateCoordinator` = one device with one sensor.

**Tech Stack:** Python 3.13+, Home Assistant custom integration APIs (config flow, options flow, `DataUpdateCoordinator`, issue registry), aiohttp via HA shared session, `pytest-homeassistant-custom-component`, GitHub Actions (hassfest, HACS action).

**Spec:** `docs/superpowers/specs/2026-11-12-alarmeringdroid-ha-integration-design.md` — read it before starting any task. Section numbers below (e.g. "spec 6.5.3a") refer to it.

## Global Constraints

- Server is off-limits: never propose or make changes to `api2.php` / `modFind.php` on alarmeringdroid.nl.
- Domain `alarmeringdroid`; display name `AlarmeringDroid P2000`; repo `ha-alarmeringdroid` at `/opt/Sites/ha-alarmeringdroid`.
- Base URL constant `https://www.alarmeringdroid.nl/api2` in `const.py`; not a user option.
- Message URL pattern: `https://www.alarmeringdroid.nl/toonmelding/<id>` (verified in site source `htdocs/toonmelding.php`; works for parent and child IDs).
- Header `User-Agent: HA-AlarmeringDroid/<manifest version>` on every request; request timeout 15 s; use `async_get_clientsession(hass)`.
- Scan interval: default 60 s, minimum 15 s (enforced in schema *and* clamped at runtime), back-off doubles per consecutive failure up to 600 s, resets on success.
- First poll after setup/reload is silent (no events). First poll is delayed by a random 0–10 s, run in a background task, not blocking entry setup.
- Fixed zone/postcode radius: `straal: 5`. All locations go in one `postcode` array. Never send `postcode4`, `freesearch`, or `prio1` (see Task 3 note).
- `limit: 30` on every `find`.
- Sensor state max 255 chars; full text in `melding` attribute.
- Event name `alarmeringdroid_message`.
- `iot_class: cloud_polling`, `integration_type: service`, `config_flow: true`, version `0.1.0`.
- Minimum HA version `2026.5.0` in `hacs.json` (verify that release exists on PyPI at build time; if not, use the newest `YYYY.M.0` release that is ≥ 5 months old).
- License: MIT. Copyright holder: the repo owner (git user name).
- Translations in English (`strings.json`, `translations/en.json`) and Dutch (`translations/nl.json`). Keys identical across files.
- No real network calls in tests; all HTTP mocked.

## Review Focus

1. **Zone is the only location and its postcode is unresolved** — integration must not send a `find` without any location filter (that would return a nationwide firehose); the poll fails with `UpdateFailed` instead. Pinned in Task 7.
2. **Missing/garbage field values** (`""`, `null`, `"0"` for lat/lon, empty `grip`, empty `datum`/`tijd`, `29-02`) — parse without raising; lat/lon → `None`, grip → `0`, unparsable time → poll time. Pinned in Task 2.
3. **HTTP 200 with non-JSON or empty body** (PHP warning page, empty response when the filter JSON is rejected) — `ApiResponseError`, entity unavailable, back-off; no traceback spam. Pinned in Task 5.
4. **Same message ID twice in one response** (capcode join duplicates, lifeliner UNION overlap, child returned both standalone and nested) — exactly one event. Pinned in Task 2 (flatten dedupes) and Task 4.
5. **Message text longer than 255 chars or with newlines** — sensor state truncated to 255, attribute keeps full text; no `ValueError` from HA state length check. Pinned in Task 9.

---

## File Structure

```
ha-alarmeringdroid/
  custom_components/alarmeringdroid/
    __init__.py        # setup/unload entry, reload on options change      (Task 9)
    manifest.json                                                           (Task 1)
    const.py           # all constants, lookup tables, config keys         (Task 1)
    models.py          # Message dataclass, parsing, flatten, timestamps   (Task 2)
    search.py          # SearchConfig, input normalization, find filter    (Task 3)
    tracker.py         # cursor, seen IDs, prio threads, client filters    (Task 4)
    api.py             # async HTTP client, errors                         (Task 5)
    zone.py            # zone → postcode resolution, repair issues          (Task 6)
    coordinator.py     # polling, priming, events, back-off                 (Task 7)
    config_flow.py     # config + options flow                              (Task 8)
    sensor.py          # most-recent-message sensor                         (Task 9)
    strings.json, translations/en.json, translations/nl.json               (Task 8, extended in 6/9)
  blueprints/automation/alarmeringdroid/notify_p2000.yaml                   (Task 10)
  tests/
    conftest.py, fixtures/*.json                                            (Task 1, 5)
    test_models.py, test_search.py, test_tracker.py, test_api.py,
    test_zone.py, test_coordinator.py, test_config_flow.py, test_sensor.py
  .github/workflows/validate.yml, tests.yml                                 (Task 1)
  hacs.json, README.md, LICENSE, pyproject.toml, requirements_test.txt, .gitignore (Task 1, 10)
```

---

### Task 1: Repo scaffold, constants, CI

**Files:**
- Create: everything under "Task 1" above, plus `custom_components/alarmeringdroid/__init__.py` as an empty-module placeholder (real content in Task 9), `tests/__init__.py`, `tests/test_const.py`.

**Interfaces:**
- Produces (`const.py`):
  - `DOMAIN = "alarmeringdroid"`, `NAME = "AlarmeringDroid P2000"`, `BASE_URL`, `MESSAGE_URL = "https://www.alarmeringdroid.nl/toonmelding/{id}"`
  - `DEFAULT_SCAN_INTERVAL = 60`, `MIN_SCAN_INTERVAL = 15`, `MAX_BACKOFF = 600`, `REQUEST_TIMEOUT = 15`, `STAGGER_MAX = 10`, `RADIUS_KM = 5`, `FIND_LIMIT = 30`, `SEEN_MAX = 1000`, `STATE_MAX_LEN = 255`
  - `EVENT_MESSAGE = "alarmeringdroid_message"`
  - `REGIOS: dict[int, str]` — spec 6.4 without 0. `DIENSTEN: dict[int, str]` — `{1: "Politie", 2: "Brandweer", 3: "Ambulance", 4: "KNRM", 5: "Lifeliner"}`. `DIENST_LIFELINER = 5`.
  - `DIENST_ICONS: dict[int, str]` — `{1: "mdi:police-badge", 2: "mdi:fire-truck", 3: "mdi:ambulance", 4: "mdi:lifebuoy", 5: "mdi:helicopter"}`, `DEFAULT_ICON = "mdi:alarm-light"`
  - Config keys: `CONF_NAME="name"`, `CONF_REGIOS="regios"`, `CONF_DIENSTEN="diensten"`, `CONF_POSTCODES="postcodes"`, `CONF_CAPCODES="capcodes"`, `CONF_ZONE="zone"`, `CONF_PRIO1_ONLY="prio1_only"`, `CONF_ALL_LIFELINERS="all_lifeliners"`, `CONF_SCAN_INTERVAL="scan_interval"`

- [ ] **Step 1: Ask the owner for their GitHub username** (needed for `codeowners`, `documentation`, `issue_tracker` in `manifest.json`). Do not guess it.
- [ ] **Step 2: `git init`** in `/opt/Sites/ha-alarmeringdroid`, branch `main`. The spec file already exists in `docs/superpowers/specs/`; this plan in `docs/superpowers/plans/`.
- [ ] **Step 3: Write `tests/test_const.py`**

```python
def test_manifest_matches_const():
    manifest = json.loads((ROOT / "custom_components/alarmeringdroid/manifest.json").read_text())
    assert manifest["domain"] == DOMAIN
    assert manifest["iot_class"] == "cloud_polling"
    assert manifest["config_flow"] is True
    assert manifest["integration_type"] == "service"
    assert manifest["version"] == "0.1.0"

def test_tables():
    assert 0 not in REGIOS and REGIOS[9] == "Kennemerland" and len(REGIOS) == 25
    assert set(DIENSTEN) == {1, 2, 3, 4, 5}
    assert MIN_SCAN_INTERVAL == 15 and DEFAULT_SCAN_INTERVAL == 60
```

- [ ] **Step 4: Run** `pytest tests/test_const.py -v` — Expected: FAIL (import error).
- [ ] **Step 5: Create** `const.py`, `manifest.json` (`requirements: []`, `dependencies: []`, keys sorted as hassfest requires: domain, name first then alphabetical), `hacs.json` (`{"name": "AlarmeringDroid P2000", "homeassistant": "2026.5.0", "render_readme": true}`), `pyproject.toml` (`[tool.pytest.ini_options] asyncio_mode = "auto"`, `testpaths = ["tests"]`), `requirements_test.txt` (`pytest-homeassistant-custom-component==<latest>`; its bundled HA must be ≥ the `hacs.json` minimum), `tests/conftest.py` with an autouse fixture enabling `enable_custom_integrations`, `.gitignore` (Python + `.venv`), `LICENSE` (MIT).
- [ ] **Step 6: Create CI.** `validate.yml`: on push/PR, jobs `hassfest` (`home-assistant/actions/hassfest@master`) and `hacs` (`hacs/action@main`, `category: integration`, `ignore: brands` — brand icon is submitted to home-assistant/brands later, see Task 10). `tests.yml`: Python 3.13, `pip install -r requirements_test.txt`, `pytest`.
- [ ] **Step 7: Run** `python -m venv .venv && .venv/bin/pip install -r requirements_test.txt && .venv/bin/pytest tests/test_const.py -v` — Expected: 2 passed.
- [ ] **Step 8: Commit** `chore: scaffold integration repo, constants and CI` (include spec + plan).

---

### Task 2: Message model and parsing

**Files:**
- Create: `custom_components/alarmeringdroid/models.py`, `tests/test_models.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Message`: `id: int`, `parent_id: int | None`, `melding: str`, `dienst: str`, `dienst_id: int`, `regio: str`, `regio_id: int`, `plaats: str`, `postcode: str | None`, `straat: str | None`, `timestamp: datetime` (aware, Europe/Amsterdam), `prio1: bool`, `grip: int`, `brandinfo: str | None`, `capcodes: tuple[tuple[str, str], ...]` (capcode, omschrijving), `latitude: float | None`, `longitude: float | None`
    - property `thread_id -> int` = `parent_id or id`
    - property `is_followup -> bool` = `parent_id is not None`
    - property `url -> str` = `MESSAGE_URL.format(id=self.id)`
    - `as_attributes() -> dict[str, Any]` — keys exactly: `id, melding, dienst, dienst_id, regio, regio_id, plaats, postcode, straat, timestamp` (ISO string)`, prio1, grip, brandinfo, capcodes` (list of `{"capcode", "omschrijving"}`)`, parent_id, url, latitude, longitude`; `latitude`/`longitude` omitted when `None`.
  - `parse_timestamp(datum: str | None, tijd: str | None, now: datetime) -> datetime`
  - `parse_message(raw: dict, parent_id: int | None, now: datetime) -> Message`
  - `flatten_meldingen(raw: list[dict], now: datetime) -> list[Message]` — parent + its `subitems` (children get `parent_id=parent.id`), unique by `id` (first occurrence wins), sorted ascending by `id`.

Parsing rules (spec 6.3, 6.5.5): every raw value may be a string, `""` or `None`. `id`, `dienstid`, `regioid`, `grip` → int, fallback 0 (`id` must be present; raise `ValueError` if not). `prio1` true only for `"1"`/`1`. `lat`/`lon` → float, `None` when empty/unparsable/`0`. `plaats`: strip a leading `"<postcode>  "` prefix (regex `^\d{4}[A-Z]{2}\s+`), then strip. Empty strings → `None` for `postcode`, `straat`, `brandinfo`. Timestamp: first `HH:MM` in `tijd`; year = `now.year`; if result > `now + 1 day` use `now.year - 1`; if the date is invalid in that year (29-02), try previous years down to 4 back; if `datum`/`tijd` unparsable return `now`.

- [ ] **Step 1: Write failing tests** in `tests/test_models.py`, using the spec's example message (spec 6.3 / api2 doc: id 3642436 with child 3642467). Tests and key assertions:
  - `test_parse_basic`: `id == 3642436`, `dienst_id == 3`, `regio == "Kennemerland"`, `latitude == 52.31263`, `prio1 is False`, `capcodes[0] == ("0126183", "Ambulance VZA Hoofddorp 183")`.
  - `test_flatten_parent_with_subitems`: returns `[3642436, 3642467]` in that order; child `parent_id == 3642436`, `is_followup is True`; parent `is_followup is False`.
  - `test_flatten_dedupes_ids`: raw list with the same message twice plus a parent whose subitem also appears standalone → each id once.
  - `test_plaats_prefix_stripped`: `"2134AB  Hoofddorp"` → `"Hoofddorp"`.
  - `test_garbage_values`: `lat=""`, `lon=None`, `grip=""`, `straat=""` → `latitude is None`, `grip == 0`, `straat is None`; `lat="0"` → `None`.
  - `test_timestamp_parent_range`: `datum="02-07"`, `tijd="14:03 - 14:08"`, now 2026-07-02 15:00 → 2026-07-02 14:03 Europe/Amsterdam.
  - `test_timestamp_new_year`: `datum="31-12"`, `tijd="23:59"`, now 2027-01-01 00:01 → year 2026.
  - `test_timestamp_garbage`: `datum=""` → equals `now`.
  - `test_timestamp_leap_day`: `datum="29-02"`, now 2027-03-01 → 2024-02-29.
  - `test_as_attributes`: no `latitude` key when `None`; `url == "https://www.alarmeringdroid.nl/toonmelding/3642436"`; `timestamp` is ISO string.
- [ ] **Step 2: Run** `pytest tests/test_models.py -v` — Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `models.py` per the interfaces and rules above. Use `zoneinfo.ZoneInfo("Europe/Amsterdam")`.
- [ ] **Step 4: Run** `pytest tests/test_models.py -v` — Expected: all pass.
- [ ] **Step 5: Commit** `feat: message model, parsing and thread flattening`

---

### Task 3: Search config, input normalization, find-filter builder

**Files:**
- Create: `custom_components/alarmeringdroid/search.py`, `tests/test_search.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class SearchConfig`: `name: str`, `regios: tuple[int, ...]`, `diensten: tuple[int, ...]`, `postcodes: tuple[str, ...]`, `capcodes: tuple[str, ...]`, `zone: str | None`, `prio1_only: bool`, `all_lifeliners: bool`, `scan_interval: int`
    - `@classmethod from_entry_data(name: str, options: Mapping[str, Any]) -> SearchConfig` — missing keys → empty/False/default; `scan_interval = max(MIN_SCAN_INTERVAL, value)`.
    - property `has_location -> bool` — any of regios, postcodes, capcodes, zone.
  - `normalize_postcodes(text: str) -> tuple[str, ...]` — split on `,`, strip, remove inner whitespace, uppercase, must match `^[1-9]\d{3}([A-Z]{2})?$`, dedupe keeping order; raises `ValueError("invalid_postcode")`. Empty/whitespace input → `()`.
  - `normalize_capcodes(text: str) -> tuple[str, ...]` — split on `,`, strip, must match `^\d{6,9}$`, keep as strings (leading zeros kept), dedupe; raises `ValueError("invalid_capcode")`.
  - `build_find_filter(config: SearchConfig, zone_postcode: str | None, minid: int | None) -> dict[str, Any]`

`build_find_filter` rules (spec 7.1 location handling): include a key only when non-empty/true. `regios: list[int]`, `diensten: list[int]`, `postcode: list[str]` = typed postcodes + zone postcode (deduped), and `straal: RADIUS_KM` whenever `postcode` is present, `capcodes: list[str]`, `lifeliners: 1` when `all_lifeliners`, `minid` when not `None`, always `limit: FIND_LIMIT`.
**Never send `prio1`:** the server applies `prio1 = 1` to the matched row, which would hide prio1=0 follow-ups of a prio-1 thread — contradicting the owner's "prio-1 follows the thread" decision (spec 6.5.3). Prio-1 is filtered client-side only (Task 4).

- [ ] **Step 1: Write failing tests** in `tests/test_search.py`:
  - `test_normalize_postcodes`: `"1234 ab, 5678,1234AB"` → `("1234AB", "5678")`; `"0123AB"` and `"12345"` and `"1234A"` raise `ValueError`.
  - `test_normalize_capcodes`: `" 0126183 ,1404932"` → `("0126183", "1404932")`; `"12a456"` raises.
  - `test_from_entry_clamps_interval`: options `{scan_interval: 5}` → `15`; missing → `60`.
  - `test_filter_locations_or_ed`: postcodes `("1234AB", "5678")` + zone postcode `"2011AB"` → `postcode == ["1234AB", "5678", "2011AB"]`, `straal == 5`, `"postcode4" not in result`.
  - `test_filter_never_sends_prio1_or_freesearch`: `prio1_only=True` → `"prio1" not in result`, `"freesearch" not in result`.
  - `test_filter_minimal`: regios `(9,)`, minid `None` → exactly `{"regios": [9], "limit": 30}`.
  - `test_filter_lifeliners_and_minid`: → `lifeliners == 1`, `minid == 123`.
  - `test_capcodes_are_strings`: `capcodes == ["0126183"]`.
- [ ] **Step 2: Run** `pytest tests/test_search.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** `search.py`.
- [ ] **Step 4: Run** `pytest tests/test_search.py -v` — Expected: all pass.
- [ ] **Step 5: Commit** `feat: search config, input normalization and find filter`

---

### Task 4: Tracker — cursor, dedupe, thread and client-side filters

**Files:**
- Create: `custom_components/alarmeringdroid/tracker.py`, `tests/test_tracker.py`

**Interfaces:**
- Consumes: `Message` (Task 2), `SearchConfig` (Task 3).
- Produces: `class Tracker`:
  - `__init__(self, config: SearchConfig)`
  - attribute `cursor: int | None` (None until primed)
  - `prime(self, messages: list[Message]) -> Message | None` — silent: marks all seen, registers prio threads, sets cursor to max id; returns newest message that passes client filters (for the sensor), or `None`.
  - `process(self, messages: list[Message]) -> list[Message]` — returns accepted new messages ascending by id; updates state.
  - `advance(self, high_id: int | None) -> None` — `cursor = max(cursor, high_id)` when `high_id` not None; never decreases.
  - `matches(self, message: Message) -> bool` — client-side filter only (no dedupe).

Algorithm for `process` (spec 6.5.2, 6.5.3, 6.5.3a):
```
prev = self.cursor
for m in messages (ascending id):
    if m.prio1: prio_threads.add(m.thread_id)          # always, also for old/seen ones
for m in messages:
    if m.id in seen or (prev is not None and m.id <= prev): continue
    mark seen
    if matches(m): accepted.append(m)
cursor = max(prev, max ids)
```
`matches`: dienst check — if `config.diensten` and `m.dienst_id not in diensten` → reject, **unless** `config.all_lifeliners and m.dienst_id == DIENST_LIFELINER`. Regio check — same pattern and same lifeliner exception. Prio — if `config.prio1_only` and not (`m.prio1` or `m.thread_id in prio_threads`) → reject. `seen` and `prio_threads` are bounded to `SEEN_MAX` (insertion-ordered; evict oldest).

- [ ] **Step 1: Write failing tests** in `tests/test_tracker.py` (build `Message`s with a small helper `msg(id, parent=None, dienst=3, regio=9, prio1=False)`):
  - `test_prime_is_silent_and_sets_cursor`: prime `[10, 11]` → returns msg 11, `cursor == 11`; `process([10, 11])` → `[]`.
  - `test_new_message_once`: after prime, `process([12])` → `[12]`; `process([12])` again → `[]`.
  - `test_followup_returned_as_parent`: prime `[10]`; `process([10, 13(parent=10)])` → `[13]`.
  - `test_old_parent_never_fires`: prime `[50]`; `process([5, 51(parent=5)])` → `[51]` (5 is below cursor).
  - `test_thread_child_other_dienst_dropped`: config diensten `(3,)`; `process([parent 60 dienst 3, child 61 dienst 2])` → `[]` for 61, still marked seen.
  - `test_prio_follows_thread`: prio1_only; prime with `70(prio1=True)`; `process([70, 71(parent=70, prio1=False)])` → `[71]`; unrelated `72(prio1=False)` → rejected.
  - `test_lifeliner_toggle`: regios `(9,)`, diensten `(2,)`, all_lifeliners → `msg(80, dienst=5, regio=1)` accepted; same with toggle off → rejected.
  - `test_duplicate_ids_in_one_response`: `process([90, 90])` → `[90]`.
  - `test_advance_never_decreases`: cursor 100, `advance(None)` → 100, `advance(50)` → 100, `advance(150)` → 150.
  - `test_seen_bounded`: process 1500 ids → `len(seen) <= 1000`.
- [ ] **Step 2: Run** `pytest tests/test_tracker.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** `tracker.py`.
- [ ] **Step 4: Run** `pytest tests/test_tracker.py -v` — Expected: all pass.
- [ ] **Step 5: Commit** `feat: tracker with dedupe, thread rules and client-side filters`

---

### Task 5: API client

**Files:**
- Create: `custom_components/alarmeringdroid/api.py`, `tests/test_api.py`, `tests/fixtures/find_thread.json`, `tests/fixtures/find_empty.json`, `tests/fixtures/find_high_id_null.json`, `tests/fixtures/postcode_found.json`, `tests/fixtures/postcode_missing.json`

**Interfaces:**
- Produces:
  - `class ApiError(Exception)`; `class ApiConnectionError(ApiError)`; `class ApiResponseError(ApiError)`
  - `@dataclass(frozen=True) class FindResult`: `meldingen: list[dict[str, Any]]`, `high_id: int | None`
  - `class AlarmeringDroidClient`:
    - `__init__(self, session: aiohttp.ClientSession, user_agent: str, base_url: str = BASE_URL)`
    - `async find(self, filter_: dict[str, Any]) -> FindResult` — GET `f"{base_url}/find/{quote(json.dumps(filter_, separators=(',', ':')), safe='')}/JSON"`
    - `async lookup_postcode(self, lat: float, lon: float) -> str | None` — GET `f"{base_url}/postcode/{lat:.5f}/{lon:.5f}"`; returns uppercase `postcode` or `None` when absent/empty.

Rules: timeout `REQUEST_TIMEOUT`; header `User-Agent`. `aiohttp.ClientError`, `TimeoutError`, or status ≠ 200 → `ApiConnectionError` (message includes status). Read body with `await resp.text()` then `json.loads` (server may not send a JSON content type); empty body, invalid JSON, non-dict, or `find` response without a `meldingen` list → `ApiResponseError`. `high_id`: int from int or numeric string, else `None`. Ignore any `sql` key.

- [ ] **Step 1: Capture fixtures from the live API (one request each, by hand):**
  `curl -sA "HA-AlarmeringDroid/0.1.0" "https://www.alarmeringdroid.nl/api2/find/$(python3 -c 'import json,urllib.parse;print(urllib.parse.quote(json.dumps({"regios":[9],"limit":5},separators=(",",":")),safe=""))')/JSON"` and `curl -s .../api2/postcode/52.37000/4.89000`. Trim to keep one parent-with-subitems message (if none present, hand-build `find_thread.json` from the spec 6.3 example), and write `find_empty.json` (`{"meldingen":[],"high_id":null,"prev_high_id":-1}`), `find_high_id_null.json`, `postcode_missing.json` (`{"sql":"select ..."}`). Also verify with one request that a `capcodes` filter returns results (owner confirmed it works; note the result in the commit message).
- [ ] **Step 2: Write failing tests** in `tests/test_api.py` using `aioclient_mock` (from pytest-homeassistant-custom-component) or `aioresponses`:
  - `test_find_url_and_headers`: filter `{"regios":[9],"limit":30}` → requested URL path ends with `/find/%7B%22regios%22%3A%5B9%5D%2C%22limit%22%3A30%7D/JSON`; `User-Agent` header present.
  - `test_find_parses`: `find_thread.json` → `len(meldingen) >= 1`, `high_id` is int.
  - `test_find_high_id_null`: → `high_id is None`.
  - `test_find_non_json`: 200 with `"<br />\n<b>Warning</b>..."` → raises `ApiResponseError`.
  - `test_find_empty_body`: 200 with `""` → `ApiResponseError`.
  - `test_find_http_error`: 503 → `ApiConnectionError`; timeout → `ApiConnectionError`.
  - `test_lookup_postcode`: found → `"1012AB"`-style value; missing → `None`; URL ends `/postcode/52.37000/4.89000`.
- [ ] **Step 3: Run** `pytest tests/test_api.py -v` — Expected: FAIL.
- [ ] **Step 4: Implement** `api.py`.
- [ ] **Step 5: Run** `pytest tests/test_api.py -v` — Expected: all pass.
- [ ] **Step 6: Commit** `feat: async api2 client with error mapping and fixtures`

---

### Task 6: Zone resolver and repair issues

**Files:**
- Create: `custom_components/alarmeringdroid/zone.py`, `tests/test_zone.py`
- Modify: `strings.json` / `translations/*.json` — add `issues.zone_no_postcode` and `issues.zone_missing` (created in Task 8 if not yet present; create the files here with just `issues` if Task 8 hasn't run).

**Interfaces:**
- Consumes: `AlarmeringDroidClient.lookup_postcode` (Task 5).
- Produces:
  - `class ZoneNotFound(Exception)`
  - `async def lookup_zone_postcode(hass: HomeAssistant, client: AlarmeringDroidClient, entity_id: str) -> str | None` — reads `latitude`/`longitude` attributes; raises `ZoneNotFound` if state missing or attributes absent; `ApiError` propagates.
  - `class ZoneResolver`:
    - `__init__(self, hass, client, entry_id: str, search_name: str, entity_id: str)`
    - attribute `postcode: str | None`
    - `async async_resolve(self) -> None` — on success set `postcode`, delete both issues; on `None` result create issue `zone_no_postcode`, keep previous `postcode`; on `ZoneNotFound` create issue `zone_missing`, keep previous; on `ApiError` log warning, keep previous, no issue.
    - `async_start(self) -> Callable[[], None]` — `async_track_state_change_event` on the zone; re-resolve only when `latitude`/`longitude` changed or state was removed. Returns unsubscribe.

Issue IDs: `f"zone_no_postcode_{entry_id}"`, `f"zone_missing_{entry_id}"`; `is_fixable=False`, `severity=IssueSeverity.WARNING`, `translation_key` `zone_no_postcode` / `zone_missing`, placeholders `{"search": search_name, "zone": entity_id}`. EN text for `zone_no_postcode`: "The center of {zone} (search “{search}”) is not near a known postcode. Move the zone center or add a postcode to the search. The last known postcode is still used." NL equivalent.

- [ ] **Step 1: Write failing tests** in `tests/test_zone.py` (`hass` fixture, `hass.states.async_set("zone.home", "0", {"latitude": 52.37, "longitude": 4.89})`, client mocked with `AsyncMock`):
  - `test_resolve_success`: `postcode == "1012AB"`, no issues in `ir.async_get(hass)`.
  - `test_resolve_no_postcode_creates_issue_keeps_last`: first success, then lookup returns `None` → `postcode == "1012AB"`, issue `zone_no_postcode_<entry>` exists.
  - `test_zone_missing`: no state → issue `zone_missing_<entry>`.
  - `test_reresolve_only_on_coordinate_change`: after `async_start`, set same coords with other attribute changed → lookup called once total; change latitude → twice.
- [ ] **Step 2: Run** `pytest tests/test_zone.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** `zone.py` and add the issue strings.
- [ ] **Step 4: Run** `pytest tests/test_zone.py -v` — Expected: all pass.
- [ ] **Step 5: Commit** `feat: zone to postcode resolver with repair issues`

---

### Task 7: Coordinator — polling, priming, events, back-off

**Files:**
- Create: `custom_components/alarmeringdroid/coordinator.py`, `tests/test_coordinator.py`

**Interfaces:**
- Consumes: `SearchConfig`, `build_find_filter` (Task 3), `Tracker` (Task 4), `flatten_meldingen` (Task 2), `AlarmeringDroidClient`, `ApiError` (Task 5), `ZoneResolver` (Task 6).
- Produces: `class AlarmeringDroidCoordinator(DataUpdateCoordinator[Message | None])`:
  - `__init__(self, hass, entry: ConfigEntry, client: AlarmeringDroidClient, config: SearchConfig, zone: ZoneResolver | None)` — `update_interval = timedelta(seconds=config.scan_interval)`, `name = f"{DOMAIN} {config.name}"`.
  - `async _async_update_data(self) -> Message | None`
  - `async async_start(self) -> None` — sleeps `random.uniform(0, STAGGER_MAX)` then `await self.async_refresh()`; called by `__init__.py` via `entry.async_create_background_task`.

`_async_update_data` behaviour:
1. `zone_pc = zone.postcode if zone else None`. If `zone` is set and `zone_pc is None` and the config has no regios, postcodes or capcodes → raise `UpdateFailed("zone postcode not resolved")` **without any HTTP request** (Review Focus 1).
2. `minid = tracker.cursor` (None before priming). Call `client.find(build_find_filter(config, zone_pc, minid))`.
3. On `ApiError`: `failures += 1`; `update_interval = timedelta(seconds=min(config.scan_interval * 2 ** failures, MAX_BACKOFF))`; raise `UpdateFailed`. On success: `failures = 0`, interval back to `config.scan_interval`.
4. `messages = flatten_meldingen(result.meldingen, dt_util.now())`.
5. Not primed: `latest = tracker.prime(messages)`; return `latest`. (No events.)
6. Primed: `new = tracker.process(messages)`; `tracker.advance(result.high_id)`; for each `m` in `new` fire `EVENT_MESSAGE` with `{"entry_id": entry.entry_id, "search_name": config.name, "is_followup": m.is_followup, **m.as_attributes()}`; return `new[-1]` if `new` else `self.data`.

- [ ] **Step 1: Write failing tests** in `tests/test_coordinator.py` (mock client with `AsyncMock` returning `FindResult` built from the Task 5 fixtures; capture events with `async_capture_events(hass, EVENT_MESSAGE)`):
  - `test_first_poll_silent`: first refresh → `data` is newest message, 0 events, `find` called without `minid`.
  - `test_second_poll_fires_events`: second refresh with one new message → 1 event; event data has `entry_id`, `search_name`, `is_followup is False`, `melding`; `find` called with `minid == previous max id`.
  - `test_followup_event`: second response = parent (seen) + new child → 1 event, `is_followup is True`, `parent_id == parent.id`; `data.id == child.id`.
  - `test_no_new_keeps_data`: second poll empty → `data` unchanged, 0 events.
  - `test_backoff`: `find` raises `ApiConnectionError` 3× → `update_interval` 120, 240, 480 s (base 60); 4th and 5th failure capped at 600; success → 60; `last_update_success is False` during failures.
  - `test_zone_unresolved_no_request`: zone-only config, resolver `postcode None` → refresh fails, `find` never called.
  - `test_cursor_advances_to_high_id`: response `high_id` 999 above max message id → next call uses `minid == 999`.
- [ ] **Step 2: Run** `pytest tests/test_coordinator.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** `coordinator.py`.
- [ ] **Step 4: Run** `pytest tests/test_coordinator.py -v` — Expected: all pass.
- [ ] **Step 5: Commit** `feat: polling coordinator with silent priming, events and back-off`

---

### Task 8: Config flow and options flow

**Files:**
- Create: `custom_components/alarmeringdroid/config_flow.py`, `tests/test_config_flow.py`, `strings.json`, `translations/en.json`, `translations/nl.json` (merge with Task 6 `issues` keys)

**Interfaces:**
- Consumes: `normalize_postcodes`, `normalize_capcodes`, `SearchConfig`, `build_find_filter` (Task 3); `lookup_zone_postcode`, `ZoneNotFound` (Task 6); `AlarmeringDroidClient`, `ApiError` (Task 5).
- Produces:
  - `class AlarmeringDroidConfigFlow(ConfigFlow, domain=DOMAIN)` with steps `user` (name) → `filters` → `interval`; `async_get_options_flow` returns `AlarmeringDroidOptionsFlow`.
  - `class AlarmeringDroidOptionsFlow(OptionsFlow)` with single step `init` containing all filter fields + interval, prefilled from `entry.options`.
  - `async def async_validate_filters(hass, user_input: dict) -> tuple[dict[str, Any], dict[str, str]]` — returns `(options, errors)`; options use the `CONF_*` keys with normalized values (`regios`/`diensten` as `list[int]`, `postcodes`/`capcodes` as `list[str]`, `zone` as `str | None`).
  - Entry: `title = name`, `data = {CONF_NAME: name}`, `options = {...all other keys...}`.

Fields (`filters` step and options): `regios` `SelectSelector(multiple, options=[{"value": str(id), "label": name}] from REGIOS)`; `diensten` same from DIENSTEN; `postcodes` text; `capcodes` text; `zone` `EntitySelector(domain="zone")` optional; `prio1_only` bool default False; `all_lifeliners` bool default False. `interval` step / options: `scan_interval` `NumberSelector(min=15, max=3600, step=1, unit "s")` default 60, schema `vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL))`.

Errors (field key → error key): `postcodes` → `invalid_postcode`; `capcodes` → `invalid_capcode`; `zone` → `zone_not_found` / `zone_no_postcode`; `base` → `no_location_filter` (none of regios/postcodes/capcodes/zone), `cannot_connect` (test `find` failed). Validation order: format errors → location rule → zone lookup → one test `find` with `minid=None`. Only proceed to `interval` step when no errors.

Step descriptions must state (EN; NL equivalent): "All filters combine: a message must match every filled-in filter. Within one filter (e.g. two regios) any value matches. Postcodes and the zone use a 5 km radius and count as one location filter." `all_lifeliners` label: "All Lifeliner messages, nationwide (any regio)".

- [ ] **Step 1: Write failing tests** in `tests/test_config_flow.py` (patch `AlarmeringDroidClient.find` / `lookup_postcode`; patch `async_setup_entry` to return True):
  - `test_full_flow_creates_entry`: name "Thuis" → filters `{regios: ["9"], postcodes: "1234 ab"}` → interval 60 → `type == CREATE_ENTRY`, `title == "Thuis"`, `data == {"name": "Thuis"}`, `options["regios"] == [9]`, `options["postcodes"] == ["1234AB"]`, `options["scan_interval"] == 60`.
  - `test_no_location_filter`: only diensten → `errors == {"base": "no_location_filter"}`.
  - `test_invalid_postcode` / `test_invalid_capcode`: field-level errors.
  - `test_zone_without_postcode`: zone set, lookup → `None` → `errors == {"zone": "zone_no_postcode"}`.
  - `test_cannot_connect`: `find` raises `ApiConnectionError` → `{"base": "cannot_connect"}`.
  - `test_interval_below_min_rejected`: 10 → schema error (`InvalidData` / `vol.Invalid`).
  - `test_options_flow_updates`: options flow init → submit new regios → `entry.options` updated.
  - `test_translations_have_same_keys`: recursive key sets of `strings.json`, `translations/en.json`, `translations/nl.json` are equal.
- [ ] **Step 2: Run** `pytest tests/test_config_flow.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** `config_flow.py`, `strings.json`, `translations/en.json` (copy of strings with resolved text), `translations/nl.json`.
- [ ] **Step 4: Run** `pytest tests/test_config_flow.py -v` — Expected: all pass.
- [ ] **Step 5: Commit** `feat: config and options flow with validation and translations`

---

### Task 9: Entry setup and sensor

**Files:**
- Modify: `custom_components/alarmeringdroid/__init__.py` (replace placeholder)
- Create: `custom_components/alarmeringdroid/sensor.py`, `tests/test_sensor.py`, `tests/test_init.py`
- Modify: `strings.json` / translations — `entity.sensor.most_recent_message.name`: EN "Most recent message", NL "Laatste melding".

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `__init__.py`: `PLATFORMS = [Platform.SENSOR]`; `type AlarmeringDroidConfigEntry = ConfigEntry[AlarmeringDroidCoordinator]`; `async_setup_entry` builds `SearchConfig.from_entry_data(entry.data[CONF_NAME], entry.options)`, client with `User-Agent` from `(await async_get_integration(hass, DOMAIN)).version`, optional `ZoneResolver` (`await async_resolve()`, `entry.async_on_unload(resolver.async_start())`), coordinator stored in `entry.runtime_data`, forwards platforms, starts `entry.async_create_background_task(hass, coordinator.async_start(), "alarmeringdroid_first_poll")`, registers `entry.add_update_listener` that reloads the entry. `async_unload_entry` unloads platforms.
  - `sensor.py`: `class MostRecentMessageSensor(CoordinatorEntity[AlarmeringDroidCoordinator], SensorEntity)` — `_attr_has_entity_name = True`, `_attr_translation_key = "most_recent_message"`, `unique_id = f"{entry.entry_id}_most_recent_message"`, `DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name=config.name, manufacturer="AlarmeringDroid", entry_type=DeviceEntryType.SERVICE)`. `native_value` = `data.melding[:STATE_MAX_LEN]` or `None`; `extra_state_attributes` = `data.as_attributes()` or `{}`; `icon` = `DIENST_ICONS.get(data.dienst_id, DEFAULT_ICON)`.

- [ ] **Step 1: Write failing tests**:
  - `tests/test_init.py::test_setup_and_unload`: `MockConfigEntry` with options, `find` patched → `ConfigEntryState.LOADED`; sensor entity exists with state `unknown` before first poll completes; unload → `NOT_LOADED`.
  - `tests/test_init.py::test_options_change_reloads`: update options → entry reloaded (setup called twice).
  - `tests/test_sensor.py::test_state_and_attributes`: after first poll (call `coordinator.async_refresh()` directly), state equals message text, attributes include `dienst`, `url`, `latitude`.
  - `tests/test_sensor.py::test_long_text_truncated`: 300-char text with newlines → `len(state) == 255`, `attributes["melding"]` length 300.
  - `tests/test_sensor.py::test_icon_by_dienst`: dienst 2 → `mdi:fire-truck`.
  - `tests/test_sensor.py::test_unavailable_on_api_error`: `find` raises → state `unavailable`.
- [ ] **Step 2: Run** `pytest tests/test_init.py tests/test_sensor.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** `__init__.py` and `sensor.py`.
- [ ] **Step 4: Run** `pytest -v` (whole suite) — Expected: all pass.
- [ ] **Step 5: Commit** `feat: entry setup and most-recent-message sensor`

---

### Task 10: Blueprint, README, release readiness

**Files:**
- Create: `blueprints/automation/alarmeringdroid/notify_p2000.yaml`, `README.md`, `tests/test_blueprint.py`

**Interfaces:**
- Consumes: event `alarmeringdroid_message` data keys (Task 7).

Blueprint: `name: "P2000 message → notification"`, `domain: automation`, `source_url` pointing to the file on GitHub. Inputs: `search` (`config_entry` selector, `integration: alarmeringdroid`, default `""` = all searches), `notify_device` (`device` selector, `integration: mobile_app`), `only_prio1` (boolean, default false), `include_followups` (boolean, default true). Trigger: `platform: event`, `event_type: alarmeringdroid_message`. Conditions (template): search empty or `trigger.event.data.entry_id == search`; not `only_prio1` or `trigger.event.data.prio1`; `include_followups` or not `trigger.event.data.is_followup`. Action: device action `domain: mobile_app`, `type: notify`, `title: "{{ trigger.event.data.dienst }} – {{ trigger.event.data.plaats }}"`, `message: "{{ trigger.event.data.melding }}"`, `data: {url: "{{ trigger.event.data.url }}", clickAction: "{{ trigger.event.data.url }}"}`. `mode: queued`, `max: 10`.

README (English, short Dutch intro paragraph at top): what it does; install via HACS custom repository + manual install; adding a search (fields, AND-ing rule, 5 km radius, lifeliner toggle, prio-1 follows thread); entities and event data table; blueprint import button (`my.home-assistant.io/redirect/blueprint_import`); example dashboard card YAML (entities/markdown card showing `state` + `timestamp` + `plaats`); polling limits (15 s min, 60 s default) and fair-use note; data source credit + link to alarmeringdroid.nl.

- [ ] **Step 1: Write failing test** `tests/test_blueprint.py::test_blueprint_valid`: load YAML with HA's `yaml.loader` (supports `!input`), validate via `homeassistant.components.blueprint.models.Blueprint(data, expected_domain="automation")` — no exception; inputs `search`, `notify_device`, `only_prio1`, `include_followups` present.
- [ ] **Step 2: Run** `pytest tests/test_blueprint.py -v` — Expected: FAIL (file missing).
- [ ] **Step 3: Write** blueprint and README.
- [ ] **Step 4: Run** `pytest -v` — Expected: all pass.
- [ ] **Step 5: Manual smoke test in a real HA** (dev container or the owner's instance, copy `custom_components/alarmeringdroid`): add a search for the owner's home zone; confirm sensor fills within ~70 s, no events on startup, an event appears in Developer Tools → Events (`alarmeringdroid_message`) when a new message arrives, blueprint import works and a notification reaches the phone. Record the outcome in the commit message.
- [ ] **Step 6: Commit** `feat: notify blueprint and README`
- [ ] **Step 7: Report to the owner** the remaining publish steps (not done by the implementer): create GitHub repo `ha-alarmeringdroid`, push, confirm CI green, tag `v0.1.0` + GitHub release, submit icon/logo to `home-assistant/brands` (then drop `ignore: brands` in CI), optionally submit to the HACS default list.
