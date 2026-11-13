# AlarmeringDroid P2000 for Home Assistant

*Nederlands:* Deze integratie toont P2000-meldingen (brandweer, politie, ambulance, KNRM en Lifeliner) uit [alarmeringdroid.nl](https://www.alarmeringdroid.nl) in Home Assistant. Je maakt één of meer zoekopdrachten (regio, postcode met 5 km straal, capcode, zone), krijgt per zoekopdracht een sensor met de laatste melding en een event voor elke nieuwe melding. Een kant-en-klare blueprint stuurt die meldingen als notificatie naar je telefoon.

---

A Home Assistant custom integration that follows P2000 pager messages (fire brigade, police, ambulance, KNRM and Lifeliner helicopters) via the AlarmeringDroid API. Each configured search gives you a sensor with the most recent matching message and fires an event for every new message, so you can build notifications and automations on top of it.

**Attention: Messages are in Dutch only and only from Dutch services, so mostly useless from abroad**

## Installation

### HACS (custom repository)

1. In HACS open the menu (three dots) and choose **Custom repositories**.
2. Add `https://github.com/gvanlee/ha-alarmeringdroid` with type **Integration**.
3. Install **AlarmeringDroid P2000** and restart Home Assistant.

### Manual

Copy the folder `custom_components/alarmeringdroid` into the `custom_components` folder of your Home Assistant configuration and restart.

## Adding a search

Go to **Settings > Devices & services > Add integration > AlarmeringDroid P2000**. You can add as many searches as you like; each one becomes its own device.

| Field | Meaning |
|---|---|
| Name | Name of the search, used for the device and entity names (e.g. "Home 5 km"). |
| Regios | One or more P2000 regios. |
| Services | Police, fire brigade, ambulance, KNRM, Lifeliner. Empty means all. |
| Postcodes | Comma separated, `1234AB` or `1234`. Matches within a 5 km radius. |
| Capcodes | Comma separated, 6 to 9 digits. |
| Zone | A Home Assistant zone; its center is converted to a postcode and used with a 5 km radius. |
| Priority 1 only | Only report priority 1 messages. |
| All Lifeliner messages | Also report every Lifeliner message nationwide, in any regio. |
| Update interval | Seconds between checks (default 60, minimum 15). |

Rules:

- At least one of regio, postcode, capcode or zone is required.
- All filters combine with AND: a message must match every filled-in filter. Within one filter (for example two regios) any value matches. Postcodes and the zone count together as one location filter.
- The one exception is **All Lifeliner messages**, which adds nationwide Lifeliner messages on top of the other filters.
- **Priority 1 only** follows the incident: if a priority 1 message is reported, later follow-up messages in the same incident thread are reported too.
- The first check after Home Assistant starts, after adding a search, or after changing its filters is silent: the sensor is filled but no events are fired, so you never get a burst of old messages.
- You can change all settings except the name later via **Configure** on the integration.

### Polling and fair use

AlarmeringDroid is a free service run by volunteers. The interval is never lower than 15 seconds and defaults to 60 seconds. Please keep it as high as is reasonable for you and do not create many near-identical searches. On errors the integration backs off automatically (up to 10 minutes).

## Entities

Each search has one sensor, **Most recent message** ("Laatste melding" in Dutch). Its entity ID is based on the name in the language Home Assistant used when the search was added: `sensor.<name>_most_recent_message` in English, `sensor.<name>_laatste_melding` in Dutch. Check **Settings > Devices & services > Entities** for the exact ID. Its state is the readable message text (`text`, at most 255 characters, unknown until a message is seen); the full data is in the attributes. The sensor is unavailable while the API cannot be reached.

## Event

For every new message the event `alarmeringdroid_message` is fired. Its data contains the sensor attributes plus a few extra keys:

| Key | Description |
|---|---|
| `entry_id` | Config entry ID of the search that matched. |
| `search_name` | Name of that search. |
| `is_followup` | `true` when the message is a follow-up in an existing incident. |
| `incident_prio1` | `true` when the message or its incident thread is priority 1 (also for priority 0 follow-ups of a priority 1 incident). |
| `id` | Message ID. |
| `melding` | Raw P2000 message text as sent to the pagers. |
| `tekstmelding` | Readable version of the message made by alarmeringdroid.nl (e.g. "Ambulance met gepaste spoed naar Boterdorpseweg, Bergschenhoek"), when available. |
| `text` | `tekstmelding` when available, otherwise `melding`. Use this one in notifications. |
| `dienst`, `dienst_id` | Service name and number (1 Politie, 2 Brandweer, 3 Ambulance, 4 KNRM, 5 Lifeliner). |
| `regio`, `regio_id` | Regio name and number. |
| `plaats`, `postcode`, `straat` | Place, postcode and street, when known. |
| `timestamp` | Time of the message (ISO 8601). |
| `prio1` | `true` for priority 1. |
| `grip` | GRIP level (number). |
| `brandinfo` | Fire brigade extra information, when present. |
| `details` | Short summary of fire type and size (e.g. "Type: Binnenbrand-Middelgroot"), when present. |
| `capcodes` | List of `{capcode, omschrijving}`. |
| `parent_id` | ID of the first message of the incident, for follow-ups. |
| `url` | Link to the message on alarmeringdroid.nl. |
| `latitude`, `longitude` | Location, only when known. |

## Blueprint: notification on your phone

[![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fgvanlee%2Fha-alarmeringdroid%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Falarmeringdroid%2Fnotify_p2000.yaml)

The blueprint "P2000 message → notification" sends a notification via the Home Assistant Companion app. Inputs:

- **Search**: which search to react to (empty = all).
- **Device to notify**: a mobile app device.
- **Only priority 1**: default off. Follows the incident (`incident_prio1`), so follow-ups of a priority 1 incident are notified too.
- **Include follow-ups**: default on.

The title is "service – place", the message is the full text, and tapping the notification opens the message on alarmeringdroid.nl.

## Example: dashboard card

```yaml
type: markdown
title: Latest P2000
content: >
  {% set s = 'sensor.home_5_km_most_recent_message' %}
  {% if state_attr(s, 'timestamp') %}
  **{{ state_attr(s, 'dienst') }}** – {{ state_attr(s, 'plaats') }}
  ({{ as_timestamp(state_attr(s, 'timestamp')) | timestamp_custom('%d-%m %H:%M') }})

  {{ states(s) }}
  {% else %}
  No messages yet.
  {% endif %}
```

Replace the entity ID with the one of your search.

## Example: manual automation on the event

```yaml
alias: Flash lights on priority 1 near home
triggers:
  - trigger: event
    event_type: alarmeringdroid_message
    event_data:
      search_name: Home 5 km
conditions:
  - condition: template
    value_template: "{{ trigger.event.data.prio1 }}"
actions:
  - action: light.turn_on
    target:
      entity_id: light.hallway
    data:
      flash: long
  - action: persistent_notification.create
    data:
      title: "{{ trigger.event.data.dienst }} - {{ trigger.event.data.plaats }}"
      message: "{{ trigger.event.data.text }}"
```

## Data source

All data comes from [alarmeringdroid.nl](https://www.alarmeringdroid.nl). This integration is an independent project and is not affiliated with the Dutch emergency services. P2000 messages can be incomplete or delayed; do not rely on this integration for anything safety critical.

## License

See [LICENSE](LICENSE).
