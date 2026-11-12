"""Constants for the AlarmeringDroid P2000 integration."""

DOMAIN = "alarmeringdroid"
NAME = "AlarmeringDroid P2000"

BASE_URL = "https://www.alarmeringdroid.nl/api2"
MESSAGE_URL = "https://www.alarmeringdroid.nl/toonmelding/{id}"

DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 15
MAX_BACKOFF = 600
REQUEST_TIMEOUT = 15
STAGGER_MAX = 10
RADIUS_KM = 5
FIND_LIMIT = 30
SEEN_MAX = 1000
STATE_MAX_LEN = 255

EVENT_MESSAGE = "alarmeringdroid_message"

CONF_NAME = "name"
CONF_REGIOS = "regios"
CONF_DIENSTEN = "diensten"
CONF_POSTCODES = "postcodes"
CONF_CAPCODES = "capcodes"
CONF_ZONE = "zone"
CONF_ZONE_POSTCODE = "zone_postcode"
CONF_PRIO1_ONLY = "prio1_only"
CONF_ALL_LIFELINERS = "all_lifeliners"
CONF_SCAN_INTERVAL = "scan_interval"

REGIOS: dict[int, str] = {
    1: "Amsterdam-Amstelland",
    2: "Groningen",
    3: "Noord- en Oost Gelderland",
    4: "Zaanstreek-Waterland",
    5: "Hollands Midden",
    6: "Brabant Noord",
    7: "Friesland",
    8: "Gelderland-Midden",
    9: "Kennemerland",
    10: "Rotterdam-Rijnmond",
    11: "Brabant Zuid-Oost",
    12: "Drenthe",
    13: "Gelderland-Zuid",
    14: "Zuid-Holland Zuid",
    15: "Limburg-Noord",
    17: "IJsselland",
    18: "Utrecht",
    19: "Gooi en Vechtstreek",
    20: "Zeeland",
    21: "Limburg-Zuid",
    23: "Twente",
    24: "Noord-Holland Noord",
    25: "Haaglanden",
    26: "Midden- en West Brabant",
    27: "Flevoland",
}

DIENSTEN: dict[int, str] = {
    1: "Politie",
    2: "Brandweer",
    3: "Ambulance",
    4: "KNRM",
    5: "Lifeliner",
}
DIENST_LIFELINER = 5

DIENST_ICONS: dict[int, str] = {
    1: "mdi:police-badge",
    2: "mdi:fire-truck",
    3: "mdi:ambulance",
    4: "mdi:lifebuoy",
    5: "mdi:helicopter",
}
DEFAULT_ICON = "mdi:alarm-light"
