# AlarmeringDroid P2000 — Home Assistant custom integration

Design document, 2026-11-12. Status: draft for approval.

## 1. Intent

AlarmeringDroid (alarmeringdroid.nl) aggregates Dutch P2000 pager dispatch messages (Politie,
Ambulance, Brandweer, KNRM, Lifeliner). The site's public JSON API, `api2`, is already used by the
AlarmeringDroid Android app.

This project builds a Home Assistant **custom integration** that polls `api2` and exposes P2000
messages inside Home Assistant so users can:

- show "most recent P2000 message" for a search on a dashboard, and
- get a phone notification for new messages, via a standard HA automation (event-triggered),
  with a ready-made blueprint so no YAML is needed.

It will be published on GitHub and installable via HACS, for any AlarmeringDroid user, not only
the author.

## 2. Goals

- Users define one or more **searches** through the HA UI. Each search is a separate config entry.
- Search filters supported:
  - **Regio(s)** — choose from the fixed regio list (section 6.4).
  - **Diensten** — any subset of Politie, Brandweer, Ambulance, KNRM, Lifeliner.
  - **Postcodes** — one or more full Dutch postcodes (`1234AB`) or 4-digit postcodes (`1234`).
  - **Capcodes** — one or more P2000 capcodes.
  - **Prio-1 only** — boolean (follows the thread, see 6.5.3).
  - **All lifeliners (any regio)** — boolean, off by default (see 7.1).
  - **HA zone** — any `zone.*` entity (e.g. `zone.home`). The zone's center lat/lon is converted to a
    postcode via the API, then searched with a fixed **5 km radius**.
- Each search exposes:
  - a sensor "most recent P2000 message",
  - an HA event `alarmeringdroid_message` per new message (including follow-ups).
- A blueprint: "P2000 message → notify target".
- Polling interval configurable per search: **default 60 s, minimum 15 s**.
- Follow-up messages for the same incident fire a new event and update "most recent".
- Dutch and English UI translations.
- HACS-compliant repo with CI validation and automated tests.

## 3. Non-goals

- **No changes to the server.** `htdocs/api2.php` and `php-bin/modFind.php` on alarmeringdroid.nl
  must not be modified — they serve the Android app and external systems. The integration works
  against the API exactly as it behaves today, including its quirks (section 6).
- No Supervisor add-on (Docker container). Custom integration only.
- The integration does not send notifications itself. It fires events; automations notify.
- No free-text search (`freesearch` is broken server-side, see 6.7).
- No `plaatsen`, `gemeenten`, `provincies`, `grip`, `klasses` filters in v1 (API supports some of
  them; not requested; `gemeenten`/`provincies` documented as buggy).
- No adjustable radius for zone searches in v1 (fixed 5 km).
- No separate `geo_location` entities.
- No history/log entity of past messages beyond what the HA recorder keeps for the sensor.

## 4. Anti-goals (failure even if it "works")

- Flooding users with events/notifications for old messages on HA startup or after config changes.
- Hammering the AlarmeringDroid server: polling below 15 s, retry storms during outages, or
  re-doing the zone→postcode lookup every poll.
- Missing follow-ups, or firing the same message twice.
- Any change that would require touching `api2.php`.

## 5. Constraints

- Integration domain: `alarmeringdroid`. Display name: "AlarmeringDroid P2000".
- GitHub repo name: `ha-alarmeringdroid`. Local path: `/opt/Sites/ha-alarmeringdroid`.
- Base URL: `https://www.alarmeringdroid.nl/api2`. Keep base URL a constant in `const.py` (not a
  user option).
- HTTP: use HA's shared aiohttp session (`async_get_clientsession`). Send a
  `User-Agent: HA-AlarmeringDroid/<version>` header so the site owner can identify and, if
  needed, rate-limit this traffic in server logs. Request timeout ~15 s.
- Async throughout; polling via `DataUpdateCoordinator`, one coordinator per config entry.
- Config via config flow + options flow (no YAML configuration).
- Must pass `hassfest` and the HACS validation action.
- `iot_class`: `cloud_polling`.
- Minimum HA version: builder's call — pick a recent stable release about 6 months old at build
  time and set it in `hacs.json`.

## 6. The API as it really behaves (read from server source; do not change server)

### 6.1 Endpoints

- **Find**: `GET /api2/find/<urlencoded JSON filter>/JSON`
  Response: `{"meldingen": [...], "high_id": <int|null>, "prev_high_id": <int>}`.
  (Older docs mention a `sql` field; ignore it if present.)
- **Postcode lookup**: `GET /api2/postcode/<lat>/<lon>`
  Response: `{"postcode": "1234AB", "postcode4": "1234", "plaats": "...", "gemeente": "...", ...,
  "sql": "..."}`. When nothing is found, `postcode` is absent.

Filter JSON keys used by this integration: `regios` (int[]), `diensten` (int[]), `postcode`
(string[], full), `postcode4` (string[]), `straal` (km, int), `capcodes` (int/string[]),
`prio1` (1), `minid` (int), `limit` (int).

### 6.2 Filters are AND-ed

All filters combine with AND. Regio + postcode = messages in that regio *and* near that postcode.
The config flow help text must say so plainly. Within one filter (e.g. two regios) it's OR.

### 6.3 Message object

All values are strings (or null). Key fields: `id`, `melding` (text), `dienstid`, `dienst`,
`regioid`, `regio`, `plaats` (may be prefixed with postcode and two spaces, e.g.
`"2134AB  Hoofddorp"`), `postcode`, `straat`, `datum` (`dd-mm`, no year), `tijd` (`HH:MM`, or
`HH:MM - HH:MM` on a parent with subitems), `lat`, `lon`, `prio1` (`"0"`/`"1"`), `grip`,
`brandinfo`, `capcodes` (`[{capcode, omschrijving}]`), `capstring`, optional `subitems`
(array of the same shape, newest first).

### 6.4 Lookup tables

Regios: 0 Onbekend, 1 Amsterdam-Amstelland, 2 Groningen, 3 Noord- en Oost Gelderland,
4 Zaanstreek-Waterland, 5 Hollands Midden, 6 Brabant Noord, 7 Friesland, 8 Gelderland-Midden,
9 Kennemerland, 10 Rotterdam-Rijnmond, 11 Brabant Zuid-Oost, 12 Drenthe, 13 Gelderland-Zuid,
14 Zuid-Holland Zuid, 15 Limburg-Noord, 17 IJsselland, 18 Utrecht, 19 Gooi en Vechtstreek,
20 Zeeland, 21 Limburg-Zuid, 23 Twente, 24 Noord-Holland Noord, 25 Haaglanden,
26 Midden- en West Brabant, 27 Flevoland. (Omit 0 from the picker.)

Diensten: 1 Politie, 2 Brandweer, 3 Ambulance, 4 KNRM, 5 Lifeliner.

### 6.5 Quirks the integration must handle

1. **Follow-ups come back as the parent.** When a follow-up message (child) matches, the API
   returns the *parent* message with all children nested in `subitems`. The parent's `id` is one
   already seen. The integration must flatten parent + subitems, keep a set of seen message IDs per
   entry, and fire one event per **unseen** ID. The newest unseen one becomes "most recent".
2. **`high_id` is not the max of the results.** It's the highest message ID nationwide in the last
   15 minutes, and `null` when there were none. Track the highest ID seen yourself (across parents
   and subitems) and send that as `minid`; use `high_id` only to advance the cursor when it's
   higher and not null. Caveat: because a follow-up's parent has an ID below `minid`, it is still
   returned (match is on the child row) — fine, dedupe handles it.
   Owner confirmed: postcode, lat/lon, capcode links and `idparent` are all written when the
   message is first stored. No look-back window needed; jumping the cursor to `high_id` is safe.
3. **`prio1` filter is dropped server-side when it's the only filter.** Always also filter
   client-side. **Owner decision:** prio-1-only follows the thread — a message passes when it is
   prio-1 itself *or* belongs to a thread (same parent) whose parent or any earlier message is
   prio-1. Follow-ups of a prio-1 incident therefore come through even with `prio1 = "0"`.
   Messages that fail client-side filters don't fire events and don't update the sensor.
   Consequence (my call, added during planning): **never send `prio1` to the server** — the
   server applies it to the matched row, which would hide prio1=0 follow-ups. Prio-1 is filtered
   client-side only.
3a. **Threads contain non-matching messages.** `toJsonArray()` returns the parent plus *every*
   child of that parent, without re-checking the filter. Rules (my call):
   - Fire events only for IDs **greater than the cursor as it was before this poll**. A parent
     older than the cursor (e.g. sent before the search existed) never fires.
   - Re-check `diensten` and `regios` client-side on each flattened message; drop mismatches.
   - Don't re-check postcode radius or capcodes client-side (can't exactly; same incident is
     assumed to be the same place).
4. **Zone → postcode lookup only searches ±0.005° latitude (~550 m).** A zone centred in a rural
   area or on water may return no postcode. See 7.3.
5. **No year in timestamps.** Build `datetime` from `datum` + first `HH:MM` of `tijd` in
   `Europe/Amsterdam`, using the current year; if that lands more than a day in the future, use
   previous year (New Year rollover).
6. **Results capped by `limit`** (server default 30). Send `limit` explicitly (e.g. 30). If a poll
   returns exactly `limit` messages, accept that some may be missed; don't page.
7. `freesearch` uses MySQL `MATCH ... AGAINST` on a Postgres DB — broken; never send it.
8. Without `minid`, the server scans the last 90 days. Only the first poll per entry omits it.

## 7. Behaviour

### 7.1 Config flow (add a search)

Step 1 — **Name** of the search (used for device/entity names, e.g. "Thuis 5 km").

Step 2 — **Filters** (all optional, but at least one of regio / postcode / capcode / zone must be
set, to avoid a nationwide firehose):
- Regio(s): multi-select from 6.4.
- Diensten: multi-select; empty = all.
- Postcodes: text, comma-separated; accept `1234AB`, `1234 AB`, `1234`. Normalize to uppercase,
  no space.
- **Location handling (my call):** server-side, `postcode` and `postcode4` are separate AND-ed
  clauses, but with `straal` set both reduce to 4-digit precision via the `afstanden` table. So
  send **all** typed postcodes (6-char and 4-digit) **plus** the resolved zone postcode together
  in a single `postcode` array with `straal: 5`. They are then OR-ed. Never send `postcode4`.
  Radius is fixed 5 km for every location; no radius option.
- Capcodes: text, comma-separated digits; strip whitespace; store as strings. Owner confirmed the
  server-side capcode filter works today (used by the Android app); use it as is.
- **All lifeliners (any regio)**: boolean, default off. When on, send `lifeliners: 1`. Server
  then excludes Lifeliner (dienst 5) from the main query and adds *all* Lifeliner messages
  nationwide (filtered only by `minid`). Help text must say "nationwide". Client-side
  dienst/regio re-check (6.5.3a) must not drop these Lifeliner messages when the toggle is on.
- HA zone: entity selector limited to `zone` domain; optional.
- Prio-1 only: boolean.
- Show AND-ing help text (6.2).

Step 3 — **Polling interval**: seconds, default 60, min 15 (enforced by schema).

On submit: if a zone is chosen, resolve it to a postcode now (7.3). Do a test `find` call; on
network error show `cannot_connect`.

Options flow: edit everything except name. Changing filters resets the cursor/seen-IDs (7.2) and
re-resolves the zone postcode.

Unique ID: none required; duplicates allowed (two searches with the same filters are the user's
business).

### 7.2 Polling and dedupe

Per entry, the coordinator holds: `cursor` (highest ID seen), `seen_ids` (bounded set, e.g. last
1000), resolved zone postcode.

- **First poll** after setup, HA restart, or options change: call `find` without `minid` and
  `limit` 30. Record all returned IDs (flattened) as seen, set cursor, set "most recent" sensor to
  the newest message, **fire no events**.
- **Later polls**: call `find` with `minid = cursor`. Flatten parent + subitems. For each unseen
  ID above the pre-poll cursor, oldest first: apply client-side filters (6.5.3, 6.5.3a), fire `alarmeringdroid_message`, mark seen.
  Update sensor to newest new message. Advance cursor (6.5.2).
- Builder's call: whether to persist cursor/seen_ids via `Store` across restarts. If persisted,
  restarts don't need the "silent first poll" — but the silent-first-poll rule must still hold for
  new entries and filter changes. Either way, no burst of old events after restart.

### 7.3 Zone → postcode

- Read zone state attributes `latitude`/`longitude`.
- Call `/api2/postcode/<lat>/<lon>` (lat/lon formatted with `.` decimal, ~5 decimals).
- Use returned full `postcode` with `straal: 5`.
- If no postcode is found: in the config/options flow show error `zone_no_postcode` with text
  telling the user to move the zone center or use a typed postcode instead. At runtime (zone moved
  later), raise an HA **repair issue** and keep using the last good postcode.
- Re-resolve only on: entry setup, options change, and when the zone entity's lat/lon change
  (listen to state changes of that zone). Never per poll.
- If the zone entity is deleted, raise a repair issue; keep polling with last postcode.

### 7.4 Entities

One **device** per config entry (service-type device, name = search name, manufacturer
"AlarmeringDroid", entry type `service`).

**Sensor — "Laatste melding" / "Most recent message"** (`sensor.<search>_most_recent_message`)
- State: message text truncated to 255 chars. Before any message: unknown.
- Attributes: `id`, `melding` (full text), `dienst`, `dienst_id`, `regio`, `regio_id`, `plaats`
  (cleaned of postcode prefix), `postcode`, `straat`, `timestamp` (ISO, from 6.5.5), `prio1`
  (bool), `grip` (int), `brandinfo`, `capcodes` (list of `{capcode, omschrijving}`),
  `parent_id` (set when it's a follow-up), `latitude`, `longitude` (floats; omitted when empty
  — having these makes it show on the HA map card), `url` to the message on alarmeringdroid.nl if a
  stable URL pattern exists (builder to verify; else omit).
- Icon by dienst (e.g. `mdi:police-badge`, `mdi:fire-truck`, `mdi:ambulance`, `mdi:lifebuoy`,
  `mdi:helicopter`).

Builder's call: whether to add a diagnostic `binary_sensor` "API reachable" or rely on the
coordinator marking entities unavailable. Prefer the latter (simpler).

### 7.5 Event

`alarmeringdroid_message`, data:
`entry_id`, `search_name`, plus every sensor attribute above (same names, same normalization),
plus `is_followup` (bool).

### 7.6 Blueprint

`blueprints/automation/alarmeringdroid/notify_p2000.yaml`:
- Inputs: search (config entry selector filtered to integration `alarmeringdroid`, optional = all
  searches), notify target (device selector for `mobile_app` devices, or a notify service name),
  "only prio-1" toggle, "include follow-ups" toggle (default on).
- Trigger: event `alarmeringdroid_message`. Conditions per inputs.
- Action: notification with title `"<dienst> – <plaats>"` and message = `melding`; include
  `data.url` when present.

### 7.7 Errors and server friendliness

- Network error / timeout / non-200 / invalid JSON → `UpdateFailed`; entities go unavailable;
  coordinator retries at the normal interval. On consecutive failures, back off (double the
  interval up to 10 min), reset on success.
- HTTP 429 or 503 → same back-off.
- Never poll faster than 15 s, even if options are edited by hand.
- Stagger first poll per entry with a small random delay (0–10 s) so restarts of many HA instances
  don't hit at the same second.

## 8. Repo layout

```
ha-alarmeringdroid/
  custom_components/alarmeringdroid/
    __init__.py
    manifest.json
    const.py
    api.py            # thin async client, no HA imports
    coordinator.py
    config_flow.py
    sensor.py
    repairs.py        # optional, if repair flows used
    strings.json
    translations/en.json
    translations/nl.json
    icons.json
  blueprints/automation/alarmeringdroid/notify_p2000.yaml
  tests/              # pytest-homeassistant-custom-component; API mocked, no real calls
  .github/workflows/  # hassfest, HACS validation, pytest
  hacs.json
  README.md           # install via HACS custom repo, config, blueprint, AND-ing note, example
                      # dashboard card YAML
  LICENSE             # builder's call: MIT unless owner says otherwise
  docs/superpowers/specs/  # this document
```

## 9. Testing

- Unit tests for `api.py` against recorded JSON fixtures, including: parent with subitems,
  `high_id: null`, empty `meldingen`, missing `postcode` in lookup.
- Coordinator tests: silent first poll; new message fires one event; follow-up arriving as parent
  re-sent fires one event for the child only; same payload twice fires nothing; prio-1 client
  filter incl. follow-up of prio-1 thread with `prio1 = "0"` passing; thread child of another
  dienst dropped; old parent below cursor never fires; lifeliners toggle keeps out-of-regio
  Lifeliner messages; cursor never goes backwards; back-off on errors.
- Request-building tests: typed 6-char + 4-digit postcodes + zone postcode all land in one
  `postcode` array with `straal: 5`; `postcode4` never sent; capcodes sent as strings.
- Config flow tests: validation (empty filters rejected, interval < 15 rejected, bad postcode /
  capcode format), zone without postcode → error.
- Timestamp tests incl. New Year rollover.
- Capture a few real responses from the live API once (manually, low volume) to build fixtures.

## 10. Left to the builder

Marked "builder's call" above, plus: internal module structure beyond section 8, exact
translation wording, exact icons, test structure, CI details, release process (tags + GitHub
releases).
