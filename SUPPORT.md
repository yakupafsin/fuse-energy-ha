# Getting help

## Where to go

| You want to | Go to |
| --- | --- |
| Ask how something works, or whether a setup is supported | [Discussions](https://github.com/yakupafsin/fuse-energy-ha/discussions) |
| Report something broken | [Open a bug report](https://github.com/yakupafsin/fuse-energy-ha/issues/new?template=bug_report.yml) |
| Suggest a change | [Open a feature request](https://github.com/yakupafsin/fuse-energy-ha/issues/new?template=feature_request.yml) |
| Report a security problem | [Privately](SECURITY.md) — not in a public issue |

## Before opening anything

Two things account for most reports:

**Nothing has appeared yet.** Give it an hour. Fuse publishes consumption on a
delay, and the integration refuses to import an hour until it has fully elapsed,
so a fresh install looks idle for a while.

**It stopped updating.** Check whether Home Assistant is asking you to
re-authenticate. Fuse sessions expire, and a new SMS code is needed.

The [README](README.md) covers both, along with wiring the statistics into the
Energy dashboard — the other common surprise is adding both the statistics and
the `today` sensors, which counts everything twice.

## What to include

A **diagnostics download** usually answers the question on its own: Settings →
Devices & Services → Fuse Energy → *Download diagnostics*. It contains a sample
of your raw hourly bars and deliberately excludes tokens and your phone number,
so it is safe to attach.

Please do not paste tokens, the contents of `.storage/core.config_entries`, or
your phone number. Nothing here needs them to reproduce a problem.

## A realistic expectation

This is an unofficial integration built on Fuse's private mobile API, maintained
by one person in their spare time. Fuse can change that API without notice, and
when they do, this breaks for everyone at once until the parser is updated — so
if several things stop working on the same day, that is the likely cause, and a
redacted sample of the new payload shape is the most useful thing you can bring.

There is no service-level promise here, and none is implied. If you need
guaranteed data from your supplier, their own app is the supported route.
