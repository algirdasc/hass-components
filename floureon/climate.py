import asyncio
import logging
import time
import broadlink
from datetime import timedelta
from datetime import datetime
from socket import timeout
from typing import List, Optional

import voluptuous as vol

from homeassistant.components.climate import ClimateDevice, PLATFORM_SCHEMA
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util.temperature import convert as convert_temperature
from homeassistant.components.climate.const import (
    HVAC_MODE_OFF,
    HVAC_MODE_HEAT,
    HVAC_MODE_AUTO,
    CURRENT_HVAC_OFF,
    CURRENT_HVAC_HEAT,
    CURRENT_HVAC_IDLE,
    PRESET_NONE,
    PRESET_AWAY,
    SUPPORT_TARGET_TEMPERATURE,
    SUPPORT_PRESET_MODE,
    DEFAULT_MIN_TEMP,
    DEFAULT_MAX_TEMP
)

from homeassistant.const import (
    PRECISION_HALVES,
    ATTR_TEMPERATURE,
    PRECISION_HALVES,
    TEMP_CELSIUS,
    CONF_NAME
)

from homeassistant.helpers.event import (
    async_track_time_interval
)

import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

DEFAULT_SCHEDULE = 1
DEFAULT_USE_EXTERNAL_TEMP = True

CONF_HOST = 'host'
CONF_MAC = 'mac'
CONF_USE_EXTERNAL_TEMP = 'use_external_temp'
CONF_SCHEDULE = 'schedule'

BROADLINK_ACTIVE = 1
BROADLINK_IDLE = 0
BROADLINK_POWER_ON = 1
BROADLINK_POWER_OFF = 0
BROADLINK_MODE_AUTO = 1
BROADLINK_MODE_MANUAL = 0
BROADLINK_SENSOR_INTERNAL = 0
BROADLINK_SENSOR_EXTERNAL = 1
BROADLINK_SENSOR_BOTH = 2

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_HOST): cv.string,
    vol.Required(CONF_MAC): cv.string,
    vol.Required(CONF_NAME): cv.string,
    vol.Optional(CONF_SCHEDULE, default=DEFAULT_SCHEDULE): vol.Coerce(int),
    vol.Optional(CONF_USE_EXTERNAL_TEMP, default=DEFAULT_USE_EXTERNAL_TEMP): cv.boolean,
})


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the generic thermostat platform."""
    async_add_entities([BroadlinkThermostat(hass, config)])


class BroadlinkThermostat(ClimateDevice, RestoreEntity):

    def __init__(self, hass, config):
        self.hass = hass
        self._name = config.get(CONF_NAME)
        self._host = config.get(CONF_HOST)
        self._port = 80
        self._mac = bytes.fromhex(''.join(reversed(config.get(CONF_MAC).split(':'))))
        self._use_external_temp = config.get(CONF_USE_EXTERNAL_TEMP)

        self._min_temp = DEFAULT_MIN_TEMP
        self._max_temp = DEFAULT_MAX_TEMP
        self._away_temp = DEFAULT_MIN_TEMP
        self._manual_temp = DEFAULT_MIN_TEMP

        self._preset_mode = None

        self._thermostat_loop_mode = config.get(CONF_SCHEDULE)
        self._thermostat_current_action = None
        self._thermostat_current_mode = None
        self._thermostat_current_temp = None
        self._thermostat_target_temp = None

    def thermostat(self):
        return broadlink.gendevice(0x4EAD, (self._host, self._port), self._mac)

    def thermostat_get_sensor(self):
        """Get sensor to use"""
        return BROADLINK_SENSOR_EXTERNAL if self._use_external_temp is True else BROADLINK_SENSOR_INTERNAL

    def thermostat_set_time(self):
        """Set thermostat time"""
        try:
            device = self.thermostat()
            if device.auth():
                now = datetime.now()
                device.set_time(now.hour,
                                now.minute,
                                now.second,
                                now.weekday() + 1)
        except timeout:
            _LOGGER.error("Thermostat %s set_time timeout.", self._name)
        except Exception:
            _LOGGER.error("Thermostat %s set_time error.", self._name)

    def thermostat_read_status(self):
        """Read thermostat data"""
        try:
            device = self.thermostat()
            if device.auth():
                data = device.get_full_status()

                # Thermostat temperatures
                if self._use_external_temp is True:
                    self._thermostat_current_temp = data['external_temp']
                else:
                    self._thermostat_current_temp = data['room_temp']

                # self._hysteresis = int(data['dif'])
                self._min_temp = int(data['svl'])
                self._max_temp = int(data['svh'])
                self._thermostat_target_temp = data['thermostat_temp']

                # Thermostat modes & status
                if data["power"] == BROADLINK_POWER_OFF:
                    # Unset away mode
                    self._preset_mode = PRESET_NONE
                    self._thermostat_current_mode = HVAC_MODE_OFF
                else:
                    if data["auto_mode"] == BROADLINK_MODE_AUTO:
                        # Unset away mode
                        self._preset_mode = PRESET_NONE
                        self._thermostat_current_mode = HVAC_MODE_AUTO
                    elif data["auto_mode"] == BROADLINK_MODE_MANUAL:
                        self._thermostat_current_mode = HVAC_MODE_HEAT

                # Thermostat action
                if data["power"] == BROADLINK_POWER_ON and data["active"] == BROADLINK_ACTIVE:
                    self._thermostat_current_action = CURRENT_HVAC_HEAT
                elif data["power"] == BROADLINK_POWER_ON and data["active"] == BROADLINK_IDLE:
                    self._thermostat_current_action = CURRENT_HVAC_IDLE
                elif data["power"] == BROADLINK_POWER_OFF:
                    self._thermostat_current_action = CURRENT_HVAC_OFF
        except Exception:
            pass
            # _LOGGER.warning("Thermostat %s read_status timeout", self._name)

    @property
    def name(self) -> str:
        """Return thermostat name"""
        return self._name

    @property
    def precision(self) -> float:
        """Return the precision of the system."""
        return PRECISION_HALVES

    @property
    def temperature_unit(self) -> str:
        """Return the unit of measurement."""
        return TEMP_CELSIUS

    @property
    def hvac_mode(self) -> str:
        """Return hvac operation ie. heat, cool mode.
        Need to be one of HVAC_MODE_*.
        """
        return self._thermostat_current_mode

    @property
    def hvac_modes(self) -> List[str]:
        """Return the list of available hvac operation modes.
        Need to be a subset of HVAC_MODES.
        """
        return [HVAC_MODE_AUTO, HVAC_MODE_HEAT, HVAC_MODE_OFF]

    @property
    def hvac_action(self) -> Optional[str]:
        """Return the current running hvac operation if supported.
        Need to be one of CURRENT_HVAC_*.
        """
        return self._thermostat_current_action

    @property
    def preset_mode(self) -> Optional[str]:
        """Return the current preset mode, e.g., home, away, temp.
        Requires SUPPORT_PRESET_MODE.
        """
        return self._preset_mode

    @property
    def preset_modes(self) -> Optional[List[str]]:
        """Return a list of available preset modes.
        Requires SUPPORT_PRESET_MODE.
        """
        return [PRESET_AWAY, PRESET_NONE]

    @property
    def current_temperature(self) -> Optional[float]:
        """Return the current temperature."""
        return self._thermostat_current_temp

    @property
    def target_temperature(self) -> Optional[float]:
        """Return the temperature we try to reach."""
        return self._thermostat_target_temp

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return SUPPORT_TARGET_TEMPERATURE | SUPPORT_PRESET_MODE

    @property
    def min_temp(self) -> float:
        """Return the minimum temperature."""
        return convert_temperature(self._min_temp, TEMP_CELSIUS,
                                   self.temperature_unit)

    @property
    def max_temp(self) -> float:
        """Return the maximum temperature."""
        return convert_temperature(self._max_temp, TEMP_CELSIUS,
                                   self.temperature_unit)

    @property
    def device_state_attributes(self):
        """Return the attribute(s) of the sensor"""
        return {
            'away_temp': self._away_temp,
            'manual_temp': self._manual_temp
        }

    async def async_added_to_hass(self) -> None:
        """Run when entity about to added."""
        await super().async_added_to_hass()

        # Set thermostat time
        self.thermostat_set_time()

        # Restore
        last_state = await self.async_get_last_state()

        if last_state is not None:
            if 'away_temp' in last_state.attributes:
                self._away_temp = last_state.attributes['away_temp']
            if 'manual_temp' in last_state.attributes:
                self._manual_temp = last_state.attributes['manual_temp']                

    async def async_set_temperature(self, **kwargs) -> None:
        """Set new target temperature."""
        if kwargs.get(ATTR_TEMPERATURE) is not None:
            target_temp = float(kwargs.get(ATTR_TEMPERATURE))
            try:
                device = self.thermostat()
                if device.auth():
                    # device.set_power(BROADLINK_POWER_ON)
                    device.set_mode(BROADLINK_MODE_MANUAL, self._thermostat_loop_mode, self.thermostat_get_sensor())
                    device.set_temp(target_temp)        

                    # Save temperatures for future use
                    if self._preset_mode == PRESET_AWAY:
                        self._away_temp = target_temp
                    elif self._preset_mode == PRESET_NONE:
                        self._manual_temp = target_temp
            except timeout:
                _LOGGER.error("Thermostat %s set_temperature timeout", self._name)

        await self.async_update_ha_state()

    async def async_set_hvac_mode(self, hvac_mode) -> None:
        """Set operation mode."""
        try:
            device = self.thermostat()
            if device.auth():
                if hvac_mode == HVAC_MODE_OFF:
                    device.set_power(BROADLINK_POWER_OFF)
                else:
                    device.set_power(BROADLINK_POWER_ON)                    
                    if hvac_mode == HVAC_MODE_AUTO:
                        device.set_mode(BROADLINK_MODE_AUTO, self._thermostat_loop_mode, self.thermostat_get_sensor())
                    elif hvac_mode == HVAC_MODE_HEAT:
                        device.set_mode(BROADLINK_MODE_MANUAL, self._thermostat_loop_mode, self.thermostat_get_sensor())
        except timeout:
            _LOGGER.error("Thermostat %s set_hvac_mode timeout", self._name)

        await self.async_update_ha_state()

    async def async_set_preset_mode(self, preset_mode) -> None:
        """Set new preset mode."""
        self._preset_mode = preset_mode
                
        try:
            device = self.thermostat()
            if device.auth():
                device.set_power(BROADLINK_POWER_ON)
                device.set_mode(BROADLINK_MODE_MANUAL, self._thermostat_loop_mode, self.thermostat_get_sensor())
                if self._preset_mode == PRESET_AWAY:
                    device.set_temp(self._away_temp)  
                elif self._preset_mode == PRESET_NONE:
                    device.set_temp(self._manual_temp)
        except timeout:
            _LOGGER.error("Thermostat %s set_preset_mode timeout", self._name)

        await self.async_update_ha_state()

    async def async_turn_off(self) -> None:
        """Turn thermostat off"""
        await self.async_set_hvac_mode(HVAC_MODE_OFF)

    async def async_turn_on(self) -> None:
        """Turn thermostat on"""
        await self.async_set_hvac_mode(HVAC_MODE_AUTO)

    async def async_update(self) -> None:
        """Get thermostat info"""
        self.thermostat_read_status()
