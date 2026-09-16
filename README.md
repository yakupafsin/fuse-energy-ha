# Fuse Energy for Home Assistant

[![HACS: custom](https://img.shields.io/badge/HACS-custom-41BDF5.svg)](https://hacs.xyz/)
[![Tests](https://github.com/yakupafsin/fuse-energy-ha/actions/workflows/tests.yml/badge.svg)](https://github.com/yakupafsin/fuse-energy-ha/actions/workflows/tests.yml)
[![Validate](https://github.com/yakupafsin/fuse-energy-ha/actions/workflows/validate.yml/badge.svg)](https://github.com/yakupafsin/fuse-energy-ha/actions/workflows/validate.yml)
[![Release](https://img.shields.io/github/v/release/yakupafsin/fuse-energy-ha?display_name=tag&sort=semver)](https://github.com/yakupafsin/fuse-energy-ha/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.9%2B-41BDF5)

Pulls hourly electricity, gas and export readings from
[Fuse Energy](https://www.fuseenergy.com/) (UK) into Home Assistant's Energy
dashboard.

> [!IMPORTANT]
> Unofficial, and unaffiliated with Fuse. It talks to the same private API the
> Fuse mobile app uses, which can change without notice. Fuse has not endorsed
> this project.

## What it creates

For **every supply on the property** — import, export and gas alike, discovered
automatically rather than hard-coded:

| Kind | What it is |
| --- | --- |
| Long-term statistics | `fuse_energy:<supply>_energy_<premises>` (kWh) and `fuse_energy:<supply>_cost_<premises>` (GBP) |
| Sensors | last settled hour (kWh and cost), and today's running totals |

The **statistics** are what the Energy dashboard should use. The sensors are for
cards and automations.

## Requirements

- Home Assistant **2026.9 or newer** (the statistics metadata uses `mean_type`
  and `unit_class`, which replaced `has_mean`)
- A Fuse Energy account with a UK supply, and the mobile number it uses
- The `recorder` integration, which is enabled by default

## Installation

### HACS (recommended)

This is not yet in the HACS default list, so add it as a custom repository:

1. Open **HACS** → **Integrations**.
2. Top-right menu (⋮) → **Custom repositories**.
3. Repository: `https://github.com/yakupafsin/fuse-energy-ha`, Category:
   **Integration**. Click **Add**.
4. Search HACS for **Fuse Energy** and click **Download**.
5. **Restart Home Assistant.**

### Manual

1. Copy `custom_components/fuse_energy/` into your Home Assistant
   `config/custom_components/` directory, so you end up with
   `config/custom_components/fuse_energy/manifest.json`.
2. **Restart Home Assistant.**

## Setup

1. **Settings → Devices & Services → Add Integration → Fuse Energy**.
2. Enter the mobile number on your Fuse account, in international format
   (`+447700900123`), then the code Fuse texts you. Fuse sometimes asks a couple
   of identity questions on top; the form adapts to whatever it asks.

Nothing appears for up to an hour after setup. Fuse publishes consumption on a
delay, and the integration deliberately refuses to import an hour until it has
fully elapsed.

## Wiring up the Energy dashboard

**Settings → Dashboards → Energy**, then:

- *Grid consumption* → add `fuse_energy:elec_import_energy_…`, and attach
  `fuse_energy:elec_import_cost_…` as its cost.
- *Return to grid* → `fuse_energy:elec_export_energy_…`, if you export.
- *Gas* → `fuse_energy:gas_energy_…`, with the matching cost series.

> [!WARNING]
> Use the **statistics**, not the `today` sensors. Adding both counts
> everything twice.

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

**Nothing appeared after setup.** Expected for up to an hour — see Setup above.

**Statistics stopped updating.** Check whether the integration is asking you to
re-authenticate: Fuse sessions expire and a fresh SMS code is needed.

**Values look wrong in the Energy dashboard.** Check you added the statistics
and not the `today` sensors, and not both.

For anything else, turn on debug logging:

```yaml
logger:
  logs:
    custom_components.fuse_energy: debug
```

Then **Settings → Devices & Services → Fuse Energy → Download diagnostics** for
a sample of today's raw bars. Tokens and the phone number are excluded, so the
file is safe to attach to an issue.

## Contributing

Contributions are welcome — bug reports especially. Fuse's API is mapped from
observed traffic on a handful of accounts, so a payload shape nobody has seen is
a genuine finding.

See **[CONTRIBUTING.md](CONTRIBUTING.md)** for how to report a bug, run the
tests and open a pull request. By taking part you agree to the
[Code of Conduct](CODE_OF_CONDUCT.md). Security issues go
[privately](SECURITY.md), not into a public issue.

### Running the tests

The parsing, DST and statistics logic runs without Home Assistant installed:

```sh
cd custom_components/fuse_energy
python3 tests/test_fuse.py
```

28 cases, no dependencies. They run in CI on every push and pull request,
alongside `hassfest` and HACS validation.

## Prior art

[simonsolts/fuse-homeassistant](https://github.com/simonsolts/fuse-homeassistant)
(AGPL-3.0) and [LionZXY/FuseEnergyApi](https://github.com/LionZXY/FuseEnergyApi)
independently mapped this API. No code was copied from either; the endpoint
shapes are theirs to credit.

## License

[MIT](LICENSE) © Yakup Afsin
