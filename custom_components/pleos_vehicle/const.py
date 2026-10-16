"""Constants for the Pleos Vehicle Data integration."""

from datetime import timedelta

DOMAIN = "pleos_vehicle"

API_BASE_URL = "https://api.pleos.ai/v1"
REQUEST_TIMEOUT = 30

BRANDS = {"hyundai": "Hyundai", "kia": "Kia", "genesis": "Genesis"}
DEFAULT_BRAND = "hyundai"

CONF_BRAND = "brand"
CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_VEHICLES = "vehicles"
CONF_TANK_CAPACITY = "tank_capacity"
CONF_BATTERY_CAPACITY = "battery_capacity"

# The Pleos API reports the fuel level as a percentage and never reports the
# litres burned, so a tank size is needed to turn a drop in the level into a
# volume. 42 L is the figure for the NX4 Tucson plug-in hybrid (11.1 US gal).
DEFAULT_TANK_CAPACITY = 42.0
MIN_TANK_CAPACITY = 1.0
MAX_TANK_CAPACITY = 200.0
TANK_CAPACITY_STEP = 0.5

# The Pleos API reports the battery state of charge as a percentage and never
# reports the kilowatt-hours used, so a battery size is needed to turn a drop
# into an energy. 60 kWh is a typical mid-size pure-EV battery.
DEFAULT_BATTERY_CAPACITY = 60.0
MIN_BATTERY_CAPACITY = 5.0
MAX_BATTERY_CAPACITY = 250.0
BATTERY_CAPACITY_STEP = 0.5

# A fuel level or battery level rise of at least this many percentage points is
# a refuel or recharge rather than rounding noise. Either one starts a new
# window.
LEVEL_RISE = 3.0

# A larger odometer jump between two updates is a unit change or a replaced
# instrument cluster, not distance driven, so it is not counted.
MAX_ODOMETER_STEP = 1000.0

LITRES_PER_UK_GALLON = 4.54609

# Keys the coordinator adds to each vehicle's data for the fuel and electric
# economy sensors to read.
KEY_FUEL_ECONOMY = "fuel_economy"
KEY_FUEL_ECONOMY_AVERAGE = "fuel_economy_average"
KEY_FUEL_ECONOMY_TODAY = "fuel_economy_today"
KEY_FUEL_ECONOMY_UNIT = "fuel_economy_unit"
KEY_ELECTRIC_ECONOMY = "electric_economy"
KEY_ELECTRIC_ECONOMY_AVERAGE = "electric_economy_average"
KEY_ELECTRIC_ECONOMY_TODAY = "electric_economy_today"
KEY_ELECTRIC_ECONOMY_UNIT = "electric_economy_unit"

# When the coordinator last fetched this vehicle's data from Pleos.
KEY_LAST_POLLED = "last_polled"

# Version of the store holding the fuel economy accumulators.
STORAGE_VERSION = 1

SCAN_INTERVAL = timedelta(minutes=15)

SERVICE_REFRESH = "refresh"
