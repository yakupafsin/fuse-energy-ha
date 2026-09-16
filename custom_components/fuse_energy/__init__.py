"""The Fuse Energy integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import FuseClient
from .auth import Tokens
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_DEVICE_ID,
    CONF_PREMISES_ID,
    CONF_REFRESH_TOKEN,
)
from .coordinator import FuseCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type FuseConfigEntry = ConfigEntry[FuseCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: FuseConfigEntry) -> bool:
    """Set up Fuse Energy from a config entry."""

    async def _persist_tokens(tokens: Tokens) -> None:
        """Store a rotated token pair.

        Fuse invalidates the old refresh token the moment it issues a new
        one, so losing this write costs the user a full re-authentication.
        """
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_ACCESS_TOKEN: tokens.access_token,
                CONF_REFRESH_TOKEN: tokens.refresh_token,
            },
        )

    client = FuseClient(
        async_get_clientsession(hass),
        device_id=entry.data[CONF_DEVICE_ID],
        tokens=Tokens(
            access_token=entry.data[CONF_ACCESS_TOKEN],
            refresh_token=entry.data[CONF_REFRESH_TOKEN],
        ),
        on_tokens_rotated=_persist_tokens,
    )

    coordinator = FuseCoordinator(
        hass, client, premises_id=entry.data[CONF_PREMISES_ID]
    )
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FuseConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
