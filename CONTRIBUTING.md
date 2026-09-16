# Contributing

Thanks for taking an interest. This is a small integration with a clear scope,
so contributions of almost any size are easy to land.

## Ways to help

Reporting a bug is genuinely useful here. Fuse's API is private and
undocumented, and it has been mapped from observed traffic on a handful of
accounts — so a payload shape nobody has seen is a real finding, not a nuisance.
A diagnostics download (below) usually contains everything needed.

Other things that help:

- **Tariff and supply shapes we have not seen.** Economy 7, export-only,
  multi-meter properties, prepayment.
- **Documentation.** If a step in the README did not match what you saw, say so.
- **Code.** Bug fixes and small, focused features.

## Reporting a bug

Please include:

1. Home Assistant version, and the integration version from
   `custom_components/fuse_energy/manifest.json`.
2. **Diagnostics**: Settings → Devices & Services → Fuse Energy → *Download
   diagnostics*. This is safe to attach — it contains a sample of your raw
   hourly bars, and deliberately excludes tokens and your phone number.
3. Debug logs, if the problem is not visible in diagnostics:

   ```yaml
   logger:
     logs:
       custom_components.fuse_energy: debug
   ```

Please do **not** paste tokens, the contents of `.storage/core.config_entries`,
or your phone number into an issue. Nothing here needs them to reproduce a
problem.

## Development

No Home Assistant installation is needed to work on the parsing, DST and
statistics logic — the test suite stubs the parts of HA it touches:

```sh
git clone https://github.com/yakupafsin/fuse-energy-ha
cd fuse-energy-ha/custom_components/fuse_energy
python3 tests/test_fuse.py
```

It prints one line per case and exits non-zero on failure. The same suite runs
in CI on every push and pull request, alongside Home Assistant's `hassfest` and
HACS validation.

To run your branch against a real Home Assistant, copy
`custom_components/fuse_energy/` into your HA `config/custom_components/` and
restart.

## Pull requests

- **Add a test** for anything that parses or converts. That is where the bugs
  live, and the suite runs without HA, so there is no setup cost.
- **Keep commits focused.** One change per PR is much easier to review.
- **Explain why, not just what.** The existing comments record why a decision
  was made; please match that. The reasoning is the expensive part to
  reconstruct later.
- Match the surrounding style. There is no formatter config to fight with.

## Scope

This integration reads consumption and cost from Fuse and writes long-term
statistics. Deliberately out of scope:

- Anything that writes to a Fuse account.
- Tariff or billing prediction. The data is hourly consumption; forecasting on
  top of it belongs in a template sensor or a separate integration.

If you are unsure whether something fits, open an issue before writing code.

## A note on the API

Fuse has not published this API and has not endorsed this project. It can change
without notice, and has. If a change breaks the integration, a PR that updates
the parser is very welcome — please include a redacted sample of the new payload
shape so the fix can be tested.
