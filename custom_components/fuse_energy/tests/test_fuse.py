"""Logic tests for the fuse_energy integration, run without Home Assistant."""
from __future__ import annotations

import ast
import asyncio
import json
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

# Resolved from this file, NOT hard-coded to /config. An absolute path happened
# to work on the machine this was written on, but it silently imported whatever
# copy of the integration was installed there rather than the one next to these
# tests -- so a checkout elsewhere (CI, or anyone who clones the repo) could not
# run them at all, and a local run was not testing the working tree.
_TESTS = Path(__file__).resolve().parent
_CUSTOM_COMPONENTS = _TESTS.parent.parent

sys.path.insert(0, str(_TESTS))
import hastubs  # noqa: F401  (installs the stub modules)

sys.path.insert(0, str(_CUSTOM_COMPONENTS))

from fuse_energy.api import Bar, _parse_chart  # noqa: E402
from fuse_energy import sensor as fuse_sensor  # noqa: E402
from fuse_energy.coordinator import (  # noqa: E402
    FuseData,
    _in_progress,
    _settled,
    _summarise,
)
from fuse_energy import statistics as fuse_stats  # noqa: E402
from fuse_energy.auth import (  # noqa: E402
    FuseAuthError,
    FuseAuthFlow,
    FuseAuthTransient,
    FuseSmsNotSent,
)
from fuse_energy.const import WEB_APP_VERSION  # noqa: E402
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
snap = _summarise(make_bars([1, 2, 3]), [], today)["ELEC_IMPORT"]
check("snapshot today total", round(snap.today_kwh, 6), 6.0)
check("snapshot last hour", snap.last_hour_kwh, 3.0)
check("snapshot last hour time", iso(snap.last_hour_start), "2026-01-15T11:00Z")
check("no current hour without one", snap.current_hour_kwh, None)


# --- 16b. The hour still being metered ---------------------------------------
def live_bar(kwh, supply="ELEC_IMPORT", realised=True):
    """The bar covering 12:00, i.e. the hour in progress in these fixtures."""
    return Bar(supply_type=supply, start=datetime(2026, 1, 15, 12, tzinfo=UTC),
               kwh=Decimal(str(kwh)), cost_gbp=Decimal("0.05"),
               is_realised=realised)


snap = _summarise(make_bars([1, 2, 3]), [live_bar("0.4")], today)["ELEC_IMPORT"]
check("current hour value", snap.current_hour_kwh, 0.4)
check("current hour cost", snap.current_hour_cost, 0.05)
check("current hour time", iso(snap.current_hour_start), "2026-01-15T12:00Z")
# "Today so far" counts it, which is what keeps the figure level with the
# Fuse app; the settled last-hour reading is left alone.
check("current hour counted in today", round(snap.today_kwh, 6), 6.4)
check("current hour cost counted in today", round(snap.today_cost, 6), 0.35)
check("current hour not the last hour", snap.last_hour_kwh, 3.0)

# Closing the hour must not double-count it: the settled bar replaces the
# partial one rather than adding to it. _settled and _in_progress are disjoint,
# so the same hour can never arrive down both paths at once.
closed = make_bars([1, 2, 3]) + [Bar(supply_type="ELEC_IMPORT",
                                     start=datetime(2026, 1, 15, 12, tzinfo=UTC),
                                     kwh=Decimal("0.9"), cost_gbp=Decimal("0.10"),
                                     is_realised=True)]
check("closed hour counted once",
      round(_summarise(closed, [], today)["ELEC_IMPORT"].today_kwh, 6), 6.9)

# FORECASTED means Fuse has no readings for the hour yet, so there is nothing
# to show -- a prediction rendered as a live figure would be worse than blank.
snap = _summarise(
    make_bars([1, 2, 3]), [live_bar("0.4", realised=False)], today
)["ELEC_IMPORT"]
check("forecast hour is not current", snap.current_hour_kwh, None)

# A supply whose first bar of the day is the one in progress still gets a
# snapshot, otherwise its entities would stay unavailable until 01:00.
snaps = _summarise([], [live_bar("0.4", supply="GAS")], today)
check("in-progress-only supply appears", sorted(snaps), ["GAS"])
check("in-progress-only current hour", snaps["GAS"].current_hour_kwh, 0.4)
check("in-progress-only has no last hour", snaps["GAS"].last_hour_kwh, None)
check("in-progress-only today counts it", snaps["GAS"].today_kwh, 0.4)

# --- 16c. Only elapsed hours are eligible for statistics ---------------------
# make_bars covers 09:00, 10:00 and 11:00; at 11:30 the 11:00 hour is still
# being metered, so statistics may see the first two and no more.
_bars = make_bars([1, 2, 3])
_now = datetime(2026, 1, 15, 11, 30, tzinfo=UTC)
check("in-progress hour withheld from statistics",
      [iso(b.start) for b in _settled(_bars, _now)],
      ["2026-01-15T09:00Z", "2026-01-15T10:00Z"])
check("in-progress hour identified",
      [iso(b.start) for b in _in_progress(_bars, _now)], ["2026-01-15T11:00Z"])
# On the hour boundary the hour that just closed is settled, not in progress.
_now = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
check("closed hour settles exactly on the boundary",
      len(_settled(_bars, _now)), 3)
check("nothing in progress on the boundary", _in_progress(_bars, _now), [])

# --- 17. Hourly cost comes from the 4dp breakdown, not the 2dp rounded field --
# The fixture values are one real hour from 2026-09-15; see _breakdown_total for
# why the 2dp field cannot be trusted.
def with_breakdown(bar, components):
    payload = chart([("ELEC_IMPORT", [bar])])
    payload["supplies"][0]["bars"][0]["breakdown"] = components
    return payload


def one_cost(payload):
    return _parse_chart(payload, date(2026, 9, 15))[0].cost_gbp


hour0 = bar_payload(2026, 9, 15, 0, 0.422, "0.12")
usage_and_standing = [
    {"name": "USAGE", "value": {"amount": "0.1086"}, "kWh": "0.422"},
    {"name": "STANDING", "value": {"amount": "0.0181"}, "kWh": None},
]
check("breakdown beats the rounded field",
      one_cost(with_breakdown(hour0, usage_and_standing)), Decimal("0.1267"))
# Every component, so a tariff that adds one stays correct with no code change.
check("all components are summed",
      one_cost(with_breakdown(hour0, usage_and_standing
                              + [{"name": "LEVY", "value": {"amount": "0.0050"}}])),
      Decimal("0.1317"))
check("falls back with no breakdown",
      one_cost(chart([("ELEC_IMPORT", [hour0])])), Decimal("0.12"))
check("falls back on an empty breakdown",
      one_cost(with_breakdown(hour0, [])), Decimal("0.12"))
check("falls back when components carry no amount",
      one_cost(with_breakdown(hour0, [{"name": "USAGE", "value": {}}])), Decimal("0.12"))
# A free hour is real data, and must not be mistaken for a missing breakdown --
# this is the whole reason the sum is distinguished from "nothing usable".
check("a zero-cost hour does not fall back",
      one_cost(with_breakdown(hour0, [{"name": "USAGE", "value": {"amount": "0"}}])),
      Decimal("0"))
check("skips malformed components",
      one_cost(with_breakdown(hour0, ["nonsense", usage_and_standing[0]])),
      Decimal("0.1086"))

# --- 18. The SMS dispatch reports errors that arrive with an HTTP 200 ---------
# tRPC puts application errors in the body and still answers 200. Checking only
# the status made a failed dispatch look like a success: the flow moved on to
# the code step and the user waited for a message that was never sent.


class _FakeResponse:
    def __init__(self, status, body):
        self.status, self._body = status, body

    async def json(self, **_kw):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


class _FakeSession:
    def __init__(self, body, status=200):
        self._body, self._status = body, status
        self.calls = []

    def post(self, url, **kw):
        self.calls.append((url, kw))
        return _FakeResponse(self._status, self._body)


def dispatch(body, status=200):
    """Run the SMS dispatch against a canned response.

    Returns (raised, session). `raised` is None when the dispatch was treated as
    successful, which is the case the original bug got wrong.
    """
    session = _FakeSession(body, status)
    flow = FuseAuthFlow(session, device_id="test-device")
    try:
        asyncio.run(flow._async_dispatch_sms("+447700900123"))
    except (FuseAuthError, FuseAuthTransient) as err:
        return err, session
    return None, session


def code_of(body, status=200):
    raised, _ = dispatch(body, status)
    if raised is None:
        return None
    return "transient" if isinstance(raised, FuseAuthTransient) else raised.code


rate_limited = {"result": {"data": {"error": {"errorCode": "rate_limited"}}}}

check("trpc error body raises",
      code_of({"result": {"data": {"error": {"errorCode": "incorrect_phone_number"}}}}),
      "incorrect_phone_number")
check("trpc error code is carried", code_of(rate_limited), "rate_limited")
check("clean 200 dispatches", code_of({"result": {"data": {}}}), None)
check("empty body dispatches", code_of({}), None)
# Most people's sign-in already worked, so the body check must only ever fire on
# a real errorCode. These are the shapes a success could plausibly take; any of
# them raising would break everyone to fix one person.
check("success flag dispatches", code_of({"result": {"data": {"success": True}}}), None)
check("null error dispatches", code_of({"result": {"data": {"error": None}}}), None)
check("empty error dispatches", code_of({"result": {"data": {"error": {}}}}), None)
check("null errorCode dispatches",
      code_of({"result": {"data": {"error": {"errorCode": None}}}}), None)
check("unrecognised body dispatches", code_of({"data": {"whatever": 1}}), None)
# The status-code paths, which the body check must not have displaced.
check("4xx raises with its code",
      code_of({"error": {"code": "bad_request"}}, 400), "bad_request")
check("5xx is transient", code_of({}, 503), "transient")
# An unexplained 4xx must not return quietly: with no code to report, the flow
# would advance to the code screen and wait for a message nobody sent.
check("4xx with no body still raises", code_of({}, 400), "http_400")

# The envelopes v0.1.2 did not look in. Each of these is a refusal arriving as
# HTTP 200, which is the exact shape of the original bug -- reading only
# result.data.error left the rest of them silent.
trpc = {"error": {"json": {"message": "Too soon", "code": -32600,
                           "data": {"code": "issue_otp_premature_retry"}}}}
check("top-level tRPC error on a 200 is caught",
      code_of(trpc), "issue_otp_premature_retry")
check("the numeric JSON-RPC code is not reported instead",
      code_of({"error": {"code": -32600, "data": {"code": "rate_limited"}}}),
      "rate_limited")
check("a batched tRPC error is caught", code_of([trpc]), "issue_otp_premature_retry")
check("superjson-wrapped result error is caught",
      code_of({"result": {"data": {"json": {"error": {"errorCode": "nope"}}}}}), "nope")
check("a bare string error is caught",
      code_of({"error": "issue_otp_premature_retry"}), "issue_otp_premature_retry")

# ...and the same shapes when they mean success, which is the half that must
# not regress: these bodies are what a working sign-in looks like.
check("batched success dispatches", code_of([{"result": {"data": {}}}]), None)
check("empty batch dispatches", code_of([]), None)
check("superjson success dispatches",
      code_of({"result": {"data": {"json": {"sent": True}}}}), None)
check("a body that merely mentions data dispatches",
      code_of({"result": {"data": {"code": "OK", "json": {"code": 200}}}}), None)

# A dispatch failure must be distinguishable from the first leg failing, or the
# config flow cannot say anything true about whose fault it was.
raised, sent = dispatch(rate_limited)
check("dispatch failure is FuseSmsNotSent", isinstance(raised, FuseSmsNotSent), True)

# The request itself: right endpoint, and the version header the gate reads.
url, kwargs = sent.calls[0]
check("dispatch hits phoneSignIn", url.endswith("/api/trpc/phoneSignIn"), True)
check("dispatch sends the version header",
      kwargs["headers"]["x-fuse-app-version"], WEB_APP_VERSION)
check("dispatch sends phone under 'phone'", kwargs["json"], {"phone": "+447700900123"})

# --- config flow error keys --------------------------------------------------
# Read the flow's source rather than importing it: config_flow pulls in
# voluptuous and the real config-entries machinery, neither of which the stubs
# carry. Parsing gets the same facts without that weight.
#
# What this guards is the mapping, not the wording. Naming an error key that has
# no translation makes Home Assistant show the user the raw key, and a refusal
# code is only ever reached by someone already stuck -- exactly when an
# unreadable message costs the most.
_FLOW = ast.parse((_CUSTOM_COMPONENTS / "fuse_energy" / "config_flow.py").read_text())

refusals = next(
    ast.literal_eval(node.value)
    for node in ast.walk(_FLOW)
    if isinstance(node, ast.AnnAssign)
    if getattr(node.target, "id", None) == "_SMS_REFUSALS"
)
check("premature retry gets its own message",
      refusals.get("issue_otp_premature_retry"), "sms_too_soon")
check("a rejected number is still blamed on the number",
      refusals.get("incorrect_phone_number"), "invalid_phone")

# Every key the flow can put in errors["base"], however it gets there.
assigned = {
    node.value.value
    for node in ast.walk(_FLOW)
    if isinstance(node, ast.Assign)
    for target in node.targets
    if isinstance(target, ast.Subscript)
    if getattr(target.value, "id", None) == "errors"
    if isinstance(node.value, ast.Constant)
    if isinstance(node.value.value, str)
}
used = assigned | set(refusals.values())
check("the flow sets error keys at all", len(used) >= 5, True)

for _name in ("strings.json", "translations/en.json"):
    _declared = set(
        json.loads((_CUSTOM_COMPONENTS / "fuse_energy" / _name).read_text())
        ["config"]["error"]
    )
    check(f"every error key is translated in {_name}", sorted(used - _declared), [])
    check(f"no unused error key in {_name}", sorted(_declared - used), [])

# --- 21. Sensor layer: what the entities actually publish --------------------
check("every reading has a sensor", sorted(d.key for d in fuse_sensor.SENSORS),
      ["current_hour_cost", "current_hour_energy", "last_hour_cost",
       "last_hour_energy", "today_cost", "today_energy"])

# The current-hour figures climb through the hour and Fuse revises them after
# it closes, so they must never be recorded as long-term statistics: that is
# statistics.py's job, from the settled bar, for the very same hour. A
# state_class here would have the two fighting over the same hour.
check("current-hour sensors are never recorded",
      [d.state_class for d in fuse_sensor.SENSORS
       if d.key.startswith("current_hour")], [None, None])


class _Coord:
    """Just enough coordinator for an entity to read itself off."""

    premises_id = "prem-1"

    def __init__(self, snapshot, ok=True):
        self.last_update_success = ok
        self.data = FuseData(premises_id="prem-1",
                             supplies={"ELEC_IMPORT": snapshot} if snapshot else {})


def entity(key, snapshot, ok=True):
    description = next(d for d in fuse_sensor.SENSORS if d.key == key)
    return fuse_sensor.FuseSensor(_Coord(snapshot, ok), "ELEC_IMPORT", description)


metered = _summarise(make_bars([1, 2, 3]), [live_bar("0.4")], today)["ELEC_IMPORT"]
settled_only = _summarise(make_bars([1, 2, 3]), [], today)["ELEC_IMPORT"]

check("current hour reported", entity("current_hour_energy", metered).native_value, 0.4)
check("current hour cost reported",
      entity("current_hour_cost", metered).native_value, 0.05)
check("current hour available", entity("current_hour_energy", metered).available, True)
# Fuse has not realised the hour: blank, rather than a zero that reads as
# "you used nothing this hour".
check("current hour unavailable while unknown",
      entity("current_hour_energy", settled_only).available, False)
check("settled readings unaffected",
      entity("last_hour_energy", settled_only).available, True)
check("a failed poll takes the entity down",
      entity("current_hour_energy", metered, ok=False).available, False)
check("current hour is named for the user",
      entity("current_hour_energy", metered)._attr_name, "Electricity current hour")

# Each entity timestamps the hour it actually describes.
check("current hour names its own hour",
      entity("current_hour_energy", metered).extra_state_attributes,
      {"current_hour_start": "2026-01-15T12:00:00+00:00",
       "supply_type": "ELEC_IMPORT"})
check("last hour keeps its existing attribute",
      entity("last_hour_energy", metered).extra_state_attributes,
      {"last_hour_start": "2026-01-15T11:00:00+00:00",
       "supply_type": "ELEC_IMPORT"})

# --- report ------------------------------------------------------------------
print(f"\n{len(PASS)} passed, {len(FAIL)} failed\n")
for name in PASS:
    print(f"  PASS  {name}")
for failure in FAIL:
    print(f"  FAIL  {failure}")
sys.exit(1 if FAIL else 0)
