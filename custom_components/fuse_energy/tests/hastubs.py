"""Minimal stand-ins for the Home Assistant APIs fuse_energy imports.

Home Assistant is not installed in this sandbox, so these exist purely to let
the integration's own modules import and run. Each stub mirrors the real
signature that was verified against the 2026.9.2 tag.
"""
from __future__ import annotations

import sys
import types
from enum import IntEnum
from typing import Any, Generic, TypeVar


def _module(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


T = TypeVar("T")

# --- homeassistant.core / const / exceptions ---
core = _module("homeassistant.core")
class HomeAssistant: ...
core.HomeAssistant = HomeAssistant
core.callback = lambda fn: fn

const = _module("homeassistant.const")
class Platform(str):
    SENSOR = "sensor"
class UnitOfEnergy:
    KILO_WATT_HOUR = "kWh"
const.Platform = Platform
const.UnitOfEnergy = UnitOfEnergy

exceptions = _module("homeassistant.exceptions")
class ConfigEntryAuthFailed(Exception): ...
class HomeAssistantError(Exception): ...
exceptions.ConfigEntryAuthFailed = ConfigEntryAuthFailed
exceptions.HomeAssistantError = HomeAssistantError

ha = _module("homeassistant")
ha.core = core

# --- config entries ---
ce = _module("homeassistant.config_entries")
class ConfigEntry(Generic[T]):
    def __init__(self, data: dict | None = None) -> None:
        self.data = data or {}
        self.runtime_data: Any = None
class ConfigFlow: 
    def __init_subclass__(cls, **kw): ...
class ConfigFlowResult(dict): ...
ce.ConfigEntry = ConfigEntry
ce.ConfigFlow = ConfigFlow
ce.ConfigFlowResult = ConfigFlowResult

# --- helpers ---
helpers = _module("homeassistant.helpers")
ac = _module("homeassistant.helpers.aiohttp_client")
ac.async_get_clientsession = lambda hass: None

uc = _module("homeassistant.helpers.update_coordinator")
class UpdateFailed(Exception): ...
class DataUpdateCoordinator(Generic[T]):
    def __init__(self, hass, logger, *, name=None, update_interval=None):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.data: Any = None
        self.last_update_success = True
class CoordinatorEntity(Generic[T]):
    def __init__(self, coordinator): self.coordinator = coordinator
uc.UpdateFailed = UpdateFailed
uc.DataUpdateCoordinator = DataUpdateCoordinator
uc.CoordinatorEntity = CoordinatorEntity

# --- recorder ---
_module("homeassistant.components")
rec = _module("homeassistant.components.recorder")

class _Recorder:
    async def async_add_executor_job(self, func, *args):
        return func(*args)
rec.get_instance = lambda hass: _Recorder()

models = _module("homeassistant.components.recorder.models")
class StatisticMeanType(IntEnum):
    NONE = 0
    ARITHMETIC = 1
    CIRCULAR = 2
models.StatisticMeanType = StatisticMeanType
models.StatisticData = dict
models.StatisticMetaData = dict

stats = _module("homeassistant.components.recorder.statistics")
# Tests swap these out; defaults keep an unconfigured import harmless.
stats.WRITES = []
def _add_external(hass, metadata, rows):
    stats.WRITES.append((metadata, list(rows)))
stats.async_add_external_statistics = _add_external
stats.get_last_statistics = lambda *a, **k: {}
stats.statistics_during_period = lambda *a, **k: {}

# aiohttp belongs to Home Assistant, not to us: the integration declares no
# requirements and uses the ClientSession that HA hands it. On a machine with HA
# installed the real package is already importable and is left alone; on a bare
# checkout (CI, or a contributor who has only cloned the repo) these stand-ins
# let the modules import. The tests never make a request -- ClientTimeout is
# constructed at import time and the rest are only type annotations.
try:  # pragma: no cover - depends on the environment, not the code under test
    import aiohttp  # noqa: F401
except ModuleNotFoundError:
    aio = _module("aiohttp")

    class ClientError(Exception):
        """Stand-in for aiohttp.ClientError."""

    class ClientTimeout:
        def __init__(self, total: float | None = None, **kw: Any) -> None:
            self.total = total

    class ClientSession:
        """Annotation-only stand-in; the suite never opens a session."""

    class ClientResponse:
        """Annotation-only stand-in."""

    aio.ClientError = ClientError
    aio.ClientTimeout = ClientTimeout
    aio.ClientSession = ClientSession
    aio.ClientResponse = ClientResponse
