# Fuse Energy (custom integration)

Pulls hourly electricity, gas and export readings from
[Fuse Energy](https://www.fuseenergy.com/) (UK) into Home Assistant's Energy
dashboard.

Unofficial and unaffiliated with Fuse. It talks to the same private API the
Fuse mobile app uses, which can change without notice.

## What it creates

For **every supply on the property** -- import, export and gas alike, discovered
automatically rather than hard-coded:

| Kind | What it is |
| --- | --- |
| Long-term statistics | `fuse_energy:<supply>_energy_<premises>` (kWh) and `fuse_energy:<supply>_cost_<premises>` (GBP) |
| Sensors | last settled hour (kWh and cost), and today's running totals |

The **statistics** are what the Energy dashboard should use. The sensors are for
cards and automations.

## Setup

1. Restart Home Assistant so it picks up the new integration.
2. **Settings > Devices & Services > Add Integration > Fuse Energy**.
3. Enter the mobile number on your Fuse account, in international format
   (`+447700900123`), and then the code Fuse texts you. Fuse sometimes asks a
   couple of identity questions on top; the form adapts to whatever it asks.

Nothing appears for up to an hour after setup. Fuse publishes consumption on a
delay, and the integration deliberately refuses to import an hour until it has
fully elapsed.

## Wiring up the Energy dashboard

**Settings > Dashboards > Energy**, then:

- *Grid consumption* -> add `fuse_energy:elec_import_energy_...`, and attach
  `fuse_energy:elec_import_cost_...` as its cost.
- *Return to grid* -> `fuse_energy:elec_export_energy_...`, if you export.
- *Gas* -> `fuse_energy:gas_energy_...`, with the matching cost series.

Use the **statistics**, not the `today` sensors. Adding both counts everything
twice.

## How it behaves

- **Polls every 15 minutes.** Faster buys nothing: Fuse publishes hourly.
- **Backfills 30 days** on first run, then only re-reads what it needs.
- **Rewrites recent history every poll.** Fuse keeps revising an hour for some
  time after it closes, so recent hours are overwritten rather than trusted.
- **Skips the hour in progress.** Fuse reports it as though it were settled,
  with a value that keeps climbing.
- **Handles the October clock change.** Bars are stored as absolute instants, so
  the repeated 01:00 does not overwrite itself.
- **Re-authenticates when the session dies.** Home Assistant will prompt, and
  Fuse texts a fresh code.

## Troubleshooting

Turn on debug logging:

```yaml
logger:
  logs:
    custom_components.fuse_energy: debug
```

Then **Settings > Devices & Services > Fuse Energy > Download diagnostics** for a
sample of today's raw bars. Tokens and the phone number are redacted.

## Tests

The parsing, DST and statistics logic runs without Home Assistant installed:

```sh
python3 /config/custom_components/fuse_energy/tests/test_fuse.py
```

## Prior art

[simonsolts/fuse-homeassistant](https://github.com/simonsolts/fuse-homeassistant)
(AGPL-3.0) and [LionZXY/FuseEnergyApi](https://github.com/LionZXY/FuseEnergyApi)
independently mapped this API. No code was copied from either; the endpoint
shapes are theirs to credit.
