# Pleos Vehicle Data for Home Assistant

A read-only Home Assistant integration for Hyundai, Kia and Genesis cars in Europe, using the Pleos Vehicle Data API. It's a stop-gap for owners whose Kia/Hyundai Connect integration (kia_uvo) no longer works.

It shows the car's status in Home Assistant: battery and charging, range, doors and locks, warning lights, tyre pressures, climate and location. It can't send commands to the car.

> Not affiliated with Hyundai, Kia, Genesis or Pleos. Use of the Pleos API is subject to Pleos's terms. See [Before you use it](#before-you-use-it).

## Requirements

- Home Assistant 2025.1 or newer
- A car supported by the Pleos Vehicle Data API, in Europe
- A **My Vehicle Data API key** from Pleos Playground (see below)

## Getting your API key

1. Sign in to [Pleos Playground](https://pleos.ai/playground).
2. Open the account menu and choose **My Vehicle Data API**. This menu only appears for users in Europe.
3. Choose your manufacturer's tab (Hyundai, Kia or Genesis), tick both agreement boxes, and click **Get API Key**.
4. Sign in with your car manufacturer's account (for example, Hyundai Bluelink) when prompted.
5. Copy the **Client ID** and **Client Secret** from the issued key screen. Pleos also sends an email confirming the key.

Only one key can exist per manufacturer. Reissuing a key invalidates tokens issued with the old one. Revoking it blocks all access.

Use the **My Vehicle Data API** values only. The SDK / app-project credentials from the App Market Console are a different credential and won't work here.

## Installation

### Through HACS (custom repository)

1. In HACS, open **Integrations → ⋮ → Custom repositories**.
2. Add `https://github.com/Thrasher2020/hyundai-pleos-europe-ha` as an **Integration**.
3. Find **Pleos Vehicle Data** in HACS and install it.
4. Restart Home Assistant.

### Manual

1. Copy `custom_components/pleos_vehicle/` into your Home Assistant `custom_components/` folder.
2. Restart Home Assistant.

## Setup

1. Go to **Settings → Devices & services → Add integration** and search for **Pleos Vehicle Data**.
2. Choose your **Brand**.
3. Enter your **Client ID** and **Client secret**.
4. Set your car's **Fuel tank capacity** and **Battery capacity**. The tank capacity is used to work out fuel economy, and defaults to 42 L (the NX4 Tucson plug-in hybrid). The battery capacity is used to work out electric economy, and defaults to 60 kWh (a typical mid-size pure-EV battery). Change either later with the entry's **Configure** button.

Every vehicle shared with the key appears as its own device. The device is named after the vehicle's nickname in Pleos, or its VIN if no nickname is set. You can rename the device in Home Assistant.

If Pleos rejects the credentials later, Home Assistant shows a re-authentication prompt.

## Entities

Data is polled from Pleos every 15 minutes.

| Platform | Entities |
|---|---|
| Sensor | VIN, odometer, fuel level and fuel range (petrol and hybrid cars only), fuel economy (last tank, today and average), EV range, EV battery level, electric economy (last charge, today and average), estimated charge duration, charge target (AC and DC), outside and set temperature, tyre pressure (four wheels), last updated, location last updated |
| Binary sensor | Locked (on = unlocked), per-door lock and open states, bonnet, boot, sunroof, EV charging, plugged in, engine (ignition), air conditioner, defrost, steering wheel heater, seat heaters, and the warning lights Pleos reports (low fuel, smart key battery, washer fluid, brake fluid, oil level, tyre pressure, headlamp, rear lamp and turn signal faults) |
| Device tracker | Location (GPS) |

Some values are only available for some models. A sensor can show "unknown" if Pleos doesn't return that field for your car.

**Units.** The distance sensors — odometer, fuel range and EV range — show the unit your car reports (for example, miles in the UK), rather than Home Assistant converting them to your configured length unit. This keeps them matching the car's own display.

**Fuel economy.** Pleos does not report fuel economy, so the integration works it out from the odometer and the fuel level: the distance driven between updates, and the fuel used, taken from how far the level has fallen and your tank capacity. Three sensors are provided:

- **Fuel Economy (Last Tank)** — restarts at each refill, so it reports the tank you are on now.
- **Fuel Economy (Today)** — restarts at midnight (Home Assistant's time zone), so it reports today's driving.
- **Fuel Economy (Average)** — everything driven since the integration first started tracking.

They read **mpg** (UK gallons) for a car that displays miles, and **L/100km** for a car that displays kilometres. They begin as "unknown" and fill in once the car has uploaded a change in both the odometer and the fuel level. The fuel level is a whole percentage and the car only uploads occasionally, so a single tank takes a while to settle; the average is the steadier figure. The daily figure is the roughest: 1% of a 42 L tank is 0.42 L, so a short day's drive can be well off. It goes back to "unknown" at midnight, and driving counts on the day the car uploaded it. On a plug-in hybrid this is petrol economy only — electric miles push it up, because electricity is not counted.

Change the tank and battery capacities with the entry's **Configure** button. A corrected value affects the figures from that point on, not the ones already accumulated.

**Electric economy.** Pleos does not report electric economy either, so it is worked out the same way as fuel economy but from the odometer and the battery level: the distance driven between updates, and the energy used, taken from how far the state of charge has fallen and your battery capacity. Three sensors are provided:

- **EV Economy (Last Charge)** — restarts at each recharge, so it reports the charge you are on now.
- **EV Economy (Today)** — restarts at midnight (Home Assistant's time zone), so it reports today's driving.
- **EV Economy (Average)** — everything driven since the integration first started tracking.

They read **mi/kWh** for a car that displays miles, and **kWh/100km** for a car that displays kilometres. They begin as "unknown" and fill in once the car has uploaded a change in both the odometer and the battery level. The daily figure is the roughest, for the same reason as fuel: 1% of a 60 kWh battery is 0.6 kWh. It goes back to "unknown" at midnight, and driving counts on the day the car uploaded it. On a plug-in hybrid this is electric economy only — petrol miles push it up, because fuel is not counted. A pure EV has no fuel level, so its fuel economy sensors stay "unknown" while the electric ones work normally.

## Services

### `pleos_vehicle.refresh`

Fetches the latest data from Pleos now, instead of waiting for the next 15-minute update.

Pleos returns the copy of the car's data it already holds, which is updated when the car uploads to Hyundai. This service can't make the car send new data. The `Last Updated At` sensor shows how old the data is.

## Limitations

- **Read-only.** Pleos's Vehicle Data API has no commands. You can't lock or unlock the car, start climate or charging, or open windows from this integration.
- **Europe only**, according to Pleos.
- **Not every car reports every field.** Window positions, battery health and service data aren't part of this API. Fuel level and fuel range come from the petrol or hybrid engine, so pure EVs show them as unknown.
- **Plug-in hybrids report two range entries of the same type.** Pleos labels both as `PHEV` with no `EV` entry, so the integration treats the larger as the petrol range and the smaller as the electric range.
- **Data is as current as the car's last upload to Hyundai.**

## Migrating from kia_uvo

Entity names follow the vehicle's device name, so an entity named `tucson_ev_battery_level` keeps its ID if the device is named Tucson. Some entities changed type or were removed:

- `lock.*_door_lock` → `binary_sensor.*_locked`. This is read-only, and its "on" means unlocked.
- Seat sensors → seat heater binary sensors.
- Car battery level, back window heater, and kia_uvo's force-update and lock/climate services have no equivalent. Fuel level and fuel range are now available for petrol and hybrid cars. Update any automations or dashboards that use them.

## Security

- Your Client ID and Client Secret are stored in Home Assistant's config entry. They aren't written to YAML or to this repository.
- The integration only makes read requests to `https://api.pleos.ai/v1`.
- Don't post your Client Secret in issues or logs. If it's exposed, reissue the key from Pleos Playground.

## Before you use it

Pleos's terms restrict how the API can be used. In particular, they limit use to the application approved by Pleos and don't allow providing the API to third parties through an application. Check those terms, and consider asking Pleos for permission before publishing or distributing this integration more widely.

This project is provided as-is, without warranty. Check that you can see the data you need before relying on it for anything safety-related, such as alerts about your car being unlocked.

## Development and bugs

Open an issue at https://github.com/Thrasher2020/hyundai-pleos-europe-ha/issues. Please include your Home Assistant version, the brand, and any error text from the log, but **not** your Client ID or Secret.

## Licence

MIT. See [LICENSE](LICENSE).
