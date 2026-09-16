"""Logic tests for the fuse_energy integration, run without Home Assistant."""
from __future__ import annotations

import asyncio
import sys
from datetime import UTC, date, datetime
from decimal import Decimal

sys.path.insert(0, "/config/custom_components/fuse_energy/tests")
import hastubs  # noqa: F401  (installs the stub modules)

sys.path.insert(0, "/config/custom_components")

from fuse_energy.api import Bar, _parse_chart  # noqa: E402
from fuse_energy.coordinator import _summarise  # noqa: E402
from fuse_energy import statistics as fuse_stats  # noqa: E402
from homeassistant.components.recorder import statistics as stat_stub  # noqa: E402

PASS, FAIL = [], []


def check(name, got, want):
    if got == want:
        PASS.append(name)
    else:
        FAIL.append(f"{name}\n      got:  {got!r}\n      want: {want!r}")


def bar_payload(y, m, d, hour, kwh, cost, supply="ELEC_IMPORT", kind="REALISED", extra=None):
    bar = {
        "index": {"year": y, "month": m, "day": d, "hour": hour},
        "kWh": kwh,
        "money": {"amount": cost},
        "type": kind,
    }
    if extra:
        bar.update(extra)
    return bar


def chart(supplies):
    return {"supplies": [{"supply_type": s, "bars": [{"bar": b} for b in bars]}
                         for s, bars in supplies]}


def iso(dt):
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%MZ")


# --- 1. British Summer Time: local 13:00 is 12:00 UTC -------------------------
bars = _parse_chart(chart([("ELEC_IMPORT", [bar_payload(2026, 7, 15, 13, 0.5, 0.12)])]),
                    date(2026, 7, 15))
check("BST hour 13 -> 12:00Z", iso(bars[0].start), "2026-07-15T12:00Z")

# --- 2. Greenwich Mean Time: local 13:00 is 13:00 UTC ------------------------
bars = _parse_chart(chart([("ELEC_IMPORT", [bar_payload(2026, 1, 15, 13, 0.5, 0.12)])]),
                    date(2026, 1, 15))
check("GMT hour 13 -> 13:00Z", iso(bars[0].start), "2026-01-15T13:00Z")

# --- 3. The clock-back day: local 01:00 happens twice -------------------------
# 25 Oct 2026, 02:00 BST becomes 01:00 GMT. Two bars share index hour 1 and
# must resolve to two distinct instants, an hour apart.
bars = _parse_chart(
    chart([("ELEC_IMPORT", [
        bar_payload(2026, 10, 25, 0, 0.1, 0.01),
        bar_payload(2026, 10, 25, 1, 0.2, 0.02),   # first pass, still BST
        bar_payload(2026, 10, 25, 1, 0.3, 0.03),   # second pass, now GMT
        bar_payload(2026, 10, 25, 2, 0.4, 0.04),
    ])]),
    date(2026, 10, 25),
)
check("clock-back yields 4 bars", len(bars), 4)
check("clock-back instants distinct", [iso(b.start) for b in bars],
      ["2026-10-24T23:00Z", "2026-10-25T00:00Z", "2026-10-25T01:00Z", "2026-10-25T02:00Z"])
check("clock-back values preserved", [str(b.kwh) for b in bars],
      ["0.1", "0.2", "0.3", "0.4"])

# --- 4. Every supply type comes through, not just electricity import ---------
bars = _parse_chart(
    chart([
        ("ELEC_IMPORT", [bar_payload(2026, 1, 15, 9, 1.0, 0.30)]),
        ("GAS",         [bar_payload(2026, 1, 15, 9, 4.0, 0.24)]),
        ("ELEC_EXPORT", [bar_payload(2026, 1, 15, 9, 0.7, 0.10)]),
    ]),
    date(2026, 1, 15),
)
check("all supplies parsed", sorted({b.supply_type for b in bars}),
      ["ELEC_EXPORT", "ELEC_IMPORT", "GAS"])

# --- 5. Bars belonging to a neighbouring day are discarded -------------------
bars = _parse_chart(
    chart([("ELEC_IMPORT", [
        bar_payload(2026, 1, 14, 23, 9.9, 9.9),   # yesterday, padding
        bar_payload(2026, 1, 15, 0, 1.0, 0.1),
    ])]),
    date(2026, 1, 15),
)
check("adjacent day filtered out", [str(b.kwh) for b in bars], ["1.0"])

# --- 6. An explicit timestamp wins over the calendar index -------------------
bars = _parse_chart(
    chart([("ELEC_IMPORT", [
        bar_payload(2026, 1, 15, 9, 1.0, 0.1, extra={"start": "2026-01-15T09:00:00Z"}),
    ])]),
    date(2026, 1, 15),
)
check("explicit timestamp honoured", iso(bars[0].start), "2026-01-15T09:00Z")

# --- 7. Forecast vs settled --------------------------------------------------
bars = _parse_chart(
    chart([("ELEC_IMPORT", [
        bar_payload(2026, 1, 15, 9, 1.0, 0.1, kind="REALISED"),
        bar_payload(2026, 1, 15, 10, 2.0, 0.2, kind="FORECAST"),
    ])]),
    date(2026, 1, 15),
)
check("realised flag read", [b.is_realised for b in bars], [True, False])

# --- 8. Malformed bars are skipped, not fatal --------------------------------
bars = _parse_chart(
    {"supplies": [{"supply_type": "ELEC_IMPORT", "bars": [
        {"bar": {"index": {"year": 2026, "month": 1, "day": 15, "hour": 9}}},   # no kWh
        {"bar": {"index": {"year": 2026, "month": 1, "day": 15}, "kWh": 1,
                 "money": {"amount": 1}}},                                      # no hour
        {"bar": bar_payload(2026, 1, 15, 11, 1.0, 0.1)},                         # good
    ]}]},
    date(2026, 1, 15),
)
check("malformed bars skipped", len(bars), 1)


# --- 9. Statistics: sums chain from zero on a first import -------------------
def make_bars(values, supply="ELEC_IMPORT"):
    return [
        Bar(supply_type=supply,
            start=datetime(2026, 1, 15, 9 + i, tzinfo=UTC),
            kwh=Decimal(str(v)), cost_gbp=Decimal("0.10"), is_realised=True)
        for i, v in enumerate(values)
    ]


def run_import(bars, last_stats=None, window=None):
    # statistics.py binds these names at import time, so the stubs have to be
    # swapped in its namespace rather than on the module they came from.
    stat_stub.WRITES.clear()
    fuse_stats.get_last_statistics = lambda *a, **k: last_stats or {}
    fuse_stats.statistics_during_period = lambda *a, **k: window or {}
    asyncio.run(fuse_stats.async_import_bars(None, "prem-1", bars))
    return {meta["statistic_id"]: rows for meta, rows in stat_stub.WRITES}


written = run_import(make_bars([1, 2, 3]))
energy = written["fuse_energy:elec_import_energy_prem_1"]
check("first import chains sums", [r["sum"] for r in energy], [1.0, 3.0, 6.0])
check("first import keeps states", [r["state"] for r in energy], [1.0, 2.0, 3.0])

# --- 10. Statistics: sums continue from the preceding row --------------------
anchor = {"fuse_energy:elec_import_energy_prem_1": [
    {"start": datetime(2026, 1, 15, 8, tzinfo=UTC).timestamp(), "sum": 10.0}
]}
written = run_import(make_bars([1, 2, 3]), last_stats=anchor)
energy = written["fuse_energy:elec_import_energy_prem_1"]
check("import resumes from anchor", [r["sum"] for r in energy], [11.0, 13.0, 16.0])

# --- 11. Statistics: rewriting an overlapping range re-anchors correctly -----
# The newest row on record sits inside the range being rewritten, so the
# anchor has to come from the window lookup instead.
latest_inside = {"fuse_energy:elec_import_energy_prem_1": [
    {"start": datetime(2026, 1, 15, 10, tzinfo=UTC).timestamp(), "sum": 99.0}
]}
preceding = {"fuse_energy:elec_import_energy_prem_1": [
    {"start": datetime(2026, 1, 15, 8, tzinfo=UTC).timestamp(), "sum": 5.0}
]}
written = run_import(make_bars([1, 2, 3]), last_stats=latest_inside, window=preceding)
energy = written["fuse_energy:elec_import_energy_prem_1"]
check("overlapping rewrite re-anchors", [r["sum"] for r in energy], [6.0, 8.0, 11.0])

# --- 12. Statistics: a duplicated hour must not double-count -----------------
dupes = make_bars([1, 2])
dupes.append(Bar(supply_type="ELEC_IMPORT", start=dupes[0].start,
                 kwh=Decimal("5"), cost_gbp=Decimal("0.1"), is_realised=True))
written = run_import(dupes)
energy = written["fuse_energy:elec_import_energy_prem_1"]
check("duplicate hour collapsed", len(energy), 2)
check("duplicate keeps later reading", [r["state"] for r in energy], [5.0, 2.0])

# --- 13. Statistics: metadata matches what HA 2026.9 requires ----------------
stat_stub.WRITES.clear()
fuse_stats.get_last_statistics = lambda *a, **k: {}
fuse_stats.statistics_during_period = lambda *a, **k: {}
asyncio.run(fuse_stats.async_import_bars(None, "prem-1", make_bars([1])))
meta_by_id = {m["statistic_id"]: m for m, _ in stat_stub.WRITES}
em = meta_by_id["fuse_energy:elec_import_energy_prem_1"]
cm = meta_by_id["fuse_energy:elec_import_cost_prem_1"]
check("energy mean_type is NONE", int(em["mean_type"]), 0)
check("energy unit_class", em["unit_class"], "energy")
check("energy unit", em["unit_of_measurement"], "kWh")
check("cost unit_class is None", cm["unit_class"], None)
check("cost unit", cm["unit_of_measurement"], "GBP")
check("has_mean removed", "has_mean" in em, False)
check("source matches domain", em["source"], "fuse_energy")

# --- 14. Statistics: forecast bars are never written -------------------------
forecast = [Bar(supply_type="ELEC_IMPORT", start=datetime(2026, 1, 15, 9, tzinfo=UTC),
                kwh=Decimal("1"), cost_gbp=Decimal("0.1"), is_realised=False)]
written = run_import(forecast)
check("forecast not written", written, {})

# --- 15. Gas gets its own series --------------------------------------------
written = run_import(make_bars([1, 2], supply="GAS"))
check("gas series ids", sorted(written),
      ["fuse_energy:gas_cost_prem_1", "fuse_energy:gas_energy_prem_1"])

# --- 16. Snapshot summary ----------------------------------------------------
today = date(2026, 1, 15)
snap = _summarise(make_bars([1, 2, 3]), today)["ELEC_IMPORT"]
check("snapshot today total", round(snap.today_kwh, 6), 6.0)
check("snapshot last hour", snap.last_hour_kwh, 3.0)
check("snapshot last hour time", iso(snap.last_hour_start), "2026-01-15T11:00Z")

# --- report ------------------------------------------------------------------
print(f"\n{len(PASS)} passed, {len(FAIL)} failed\n")
for name in PASS:
    print(f"  PASS  {name}")
for failure in FAIL:
    print(f"  FAIL  {failure}")
sys.exit(1 if FAIL else 0)
