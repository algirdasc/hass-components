import asyncio
import logging
import time
import broadlink
from datetime import timedelta
from datetime import datetime
from socket import timeout
from typing import List, Optional

from .pid_controller import PIDArduino, PIDAutotune

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
    PRESET_ECO,
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
DEFAULT_DIFFERENCE = 100
DEFAULT_PWM = 300
DEFAULT_KP = 100
DEFAULT_KI = 40
DEFAULT_KD = 60
DEFAULT_AUTOTUNE = ''
DEFAULT_NOISEBAND = 0.5
DEFAULT_CHECK_INTERVAL = timedelta(minutes=5)
DEFAULT_USE_EXTERNAL_TEMP = True

CONF_HOST = 'host'
CONF_MAC = 'mac'
CONF_CHECK_INTERVAL = 'check_interval'
CONF_USE_EXTERNAL_TEMP = 'use_external_temp'
CONF_SCHEDULE = 'schedule'
CONF_DIFFERENCE = 'difference'
CONF_KP = 'kp'
CONF_KI = 'ki'
CONF_KD = 'kd'
CONF_PWM = 'pwm'
CONF_AUTOTUNE = 'autotune'
CONF_NOISEBAND = 'noiseband'

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
    vol.Required(CONF_CHECK_INTERVAL): vol.All(cv.time_period, cv.positive_timedelta),

    vol.Optional(CONF_SCHEDULE, default=DEFAULT_SCHEDULE): vol.Coerce(int),
    vol.Optional(CONF_USE_EXTERNAL_TEMP, default=DEFAULT_USE_EXTERNAL_TEMP): cv.boolean,

    vol.Optional(CONF_DIFFERENCE, default=DEFAULT_DIFFERENCE): vol.Coerce(float),
    vol.Optional(CONF_KP, default=DEFAULT_KP): vol.Coerce(float),
    vol.Optional(CONF_KI, default=DEFAULT_KI): vol.Coerce(float),
    vol.Optional(CONF_KD, default=DEFAULT_KD): vol.Coerce(float),
    vol.Optional(CONF_PWM, default=DEFAULT_PWM): vol.Coerce(float),
    vol.Optional(CONF_AUTOTUNE, default=DEFAULT_AUTOTUNE): cv.string,
    vol.Optional(CONF_NOISEBAND, default=DEFAULT_NOISEBAND): vol.Coerce(float)
})


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the generic thermostat platform."""
    async_add_entities([BroadlinkPIDThermostat(hass, config)])


class BroadlinkPIDThermostat(ClimateDevice, RestoreEntity):

    pid_autotune = None

    def __init__(self, hass, config):
        self.hass = hass
        self._name = config.get(CONF_NAME)
        self._host = config.get(CONF_HOST)
        self._port = 80
        self._mac = bytes.fromhex(''.join(reversed(config.get(CONF_MAC).split(':'))))
        self._use_external_temp = config.get(CONF_USE_EXTERNAL_TEMP)
        self._time_changed = time.time()
        self._pid = {
            'difference': config.get(CONF_DIFFERENCE),
            'autotune': config.get(CONF_AUTOTUNE),
            'noiseband': config.get(CONF_NOISEBAND),
            'out_min': 0,
            'out_max': config.get(CONF_DIFFERENCE),
            'kp': config.get(CONF_KP),
            'ki': config.get(CONF_KI),
            'kd': config.get(CONF_KD),
            'pwm': config.get(CONF_PWM)
        }

        self._min_temp = DEFAULT_MIN_TEMP
        self._max_temp = DEFAULT_MAX_TEMP

        self._preset_mode = None
        self._pid_target_temp = 10
        self._check_interval = config.get(CONF_CHECK_INTERVAL)

        self._thermostat_loop_mode = config.get(CONF_SCHEDULE)
        self._thermostat_current_action = None
        self._thermostat_current_mode = None
        self._thermostat_current_temp = None
        self._thermostat_target_temp = None

        self._last_on_mode = None

        async_track_time_interval(hass, self.async_check_pid_output, self._check_interval)

    def thermostat(self):
        return broadlink.gendevice(0x4EAD, (self._host, self._port), self._mac)

    def thermostat_get_sensor(self):
        """Get sensor to use"""
        if self._use_external_temp is True:
            return BROADLINK_SENSOR_EXTERNAL
        else:
            return BROADLINK_SENSOR_INTERNAL

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
                    self._thermostat_current_mode = HVAC_MODE_OFF
                else:
                    if data["auto_mode"] == BROADLINK_MODE_AUTO:
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
        return [PRESET_ECO, PRESET_NONE]

    @property
    def current_temperature(self) -> Optional[float]:
        """Return the current temperature."""
        return self._thermostat_current_temp

    @property
    def target_temperature(self) -> Optional[float]:
        """Return the temperature we try to reach."""
        if self._preset_mode == PRESET_ECO:
            return self._pid_target_temp
        else:
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
            'kp': self._pid['kp'],
            'ki': self._pid['ki'],
            'kd': self._pid['kd'],
            'last_on_mode': self._last_on_mode,
            'pid_target_temp': self._pid_target_temp
        }

    async def async_added_to_hass(self) -> None:
        """Run when entity about to added."""
        await super().async_added_to_hass()

        # Set thermostat time
        self.thermostat_set_time()

        # Restore
        last_state = await self.async_get_last_state()

        if last_state is not None:
            # self._hvac_mode = last_state.state
            # self._target_temp = last_state.attributes['temperature']
            self._preset_mode = last_state.attributes['preset_mode']

            if 'last_on_mode' in last_state.attributes:
                self._last_on_mode = last_state.attributes['last_on_mode']

            if 'pid_target_temp' in last_state.attributes:
                self._pid_target_temp = last_state.attributes['pid_target_temp']

        # Init PID controllers
        if self._pid['autotune']:
            self.pid_autotune = PIDAutotune(
                self._pid_target_temp,
                sampletime=self._check_interval.seconds,
                lookback=self._check_interval.seconds,
                out_step=self._pid['difference'],
                out_min=self._pid['out_min'],
                out_max=self._pid['out_max'],
                noiseband=self._pid['difference']
            )

    async def async_set_temperature(self, **kwargs) -> None:
        """Set new target temperature."""
        if kwargs.get(ATTR_TEMPERATURE) is not None:
            target_temp = float(kwargs.get(ATTR_TEMPERATURE))
            if self._preset_mode == PRESET_ECO:
                self._pid_target_temp = target_temp
                self.pid_control_heating()
            else:
                try:
                    device = self.thermostat()
                    if device.auth():
                        # device.set_power(BROADLINK_POWER_ON)
                        device.set_mode(BROADLINK_MODE_MANUAL, self._thermostat_loop_mode, self.thermostat_get_sensor())
                        device.set_temp(target_temp)
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
                    self._last_on_mode = hvac_mode
                    device.set_power(BROADLINK_POWER_ON)
                    if self._preset_mode == PRESET_NONE:
                        if hvac_mode == HVAC_MODE_AUTO:
                            device.set_mode(BROADLINK_MODE_AUTO, self._thermostat_loop_mode,
                                            self.thermostat_get_sensor())
                        elif hvac_mode == HVAC_MODE_HEAT:
                            device.set_mode(BROADLINK_MODE_MANUAL, self._thermostat_loop_mode,
                                            self.thermostat_get_sensor())
        except timeout:
            _LOGGER.error("Thermostat %s set_hvac_mode timeout", self._name)

        await self.async_update_ha_state()

    async def async_set_preset_mode(self, preset_mode) -> None:
        """Set new preset mode."""
        self._preset_mode = preset_mode
        await self.async_update_ha_state()

    async def async_turn_off(self) -> None:
        """Turn thermostat off"""
        await self.async_set_hvac_mode(HVAC_MODE_OFF)

    async def async_turn_on(self) -> None:
        """Turn thermostat on"""
        if self._last_on_operation is not None:
            await self.async_set_hvac_mode(self._last_on_mode)
        else:
            await self.async_set_hvac_mode(HVAC_MODE_AUTO)

    async def async_update(self) -> None:
        """Get thermostat info"""
        self.thermostat_read_status()

    async def async_check_pid_output(self, check_time):
        """Call at constant intervals for keep-alive purposes"""
        if self._thermostat_current_mode == HVAC_MODE_OFF:
            return

        if self._preset_mode == PRESET_ECO:
            self.pid_control_heating()

    ##################
    #### PID PART ####
    ##################

    def pid_controller_init(self):
        """Init PID controller with current params"""
        return PIDArduino(
            self._check_interval.seconds,
            kp=self._pid['kp'], ki=self._pid['ki'], kd=self._pid['kd'],
            out_min=self._pid['out_min'], out_max=self._pid['out_max']
        )

    def pid_control_heating(self):
        """Control PID heating"""
        if self._thermostat_current_temp is None:
            return

        _LOGGER.error("pid={0}".format(self._pid))

        if self._pid['autotune'] and self.pid_autotune.run(self._thermostat_current_temp):
            params = self.pid_autotune.get_pid_parameters(self._pid['autotune'])

            self._pid['kp'] = params.Kp
            self._pid['ki'] = params.Ki
            self._pid['kd'] = params.Kd

            _LOGGER.error('pid_autotune_output={0}'.format(self.pid_autotune.output))

        pid_controller = self.pid_controller_init()
        control_output = pid_controller.calc(self._thermostat_current_temp, self._pid_target_temp)

        _LOGGER.error('pid_controller_output={0}'.format(control_output))

        # Do some controlling
        self.pid_set_control_value(control_output)

    def pid_set_control_value(self, control_output):
        """Set output value for heater"""
        if control_output == self._pid['difference'] or control_output == -self._pid['difference']:
            self.start_heating()
            self._time_changed = time.time()
        elif control_output > 0:
            self.pwm_switch(
                self._pwm * control_output / self._pid['out_max'],
                self._pwm * (self._pid['out_max'] - control_output) / self._pid['out_max'],
                time.time() - self._time_changed
            )
        elif control_output < 0:
            self.pwm_switch(
                self._pwm * control_output / self._pid['out_min'],
                self._pwm * self._pid['out_min'] / self._control_output,
                time.time() - self._time_changed
            )
        else:
            self.stop_heating()
            self._time_changed = time.time()

    def pwm_switch(self, time_on, time_off, time_passed):
        """Turn off and on the heater proportionally to control value."""
        if self._thermostat_current_action == CURRENT_HVAC_HEAT:
            if time_on < time_passed:
                self.stop_heating()
                self._time_changed = time.time()
            else:
                _LOGGER.info("Thermostat %s turns off in %s sec", self._name, int(time_on - time_passed))
        else:
            if time_off < time_passed:
                self.start_heating()
                self._time_changed = time.time()
            else:
                _LOGGER.info("Thermostat %s turns on in %s sec", self._name, int(time_off - time_passed))

    def start_heating(self):
        """Turn heater on (set max heating temp)"""
        temp_to_heat = self._max_temp

        # check if already heating
        if self._thermostat_target_temp >= temp_to_heat and self._thermostat_current_action == CURRENT_HVAC_HEAT:
            return

        try:
            device = self.thermostat()
            if device.auth():
                device.set_power(BROADLINK_POWER_ON)
                device.set_mode(BROADLINK_MODE_MANUAL, self._thermostat_loop_mode, self.thermostat_get_sensor())
                device.set_temp(float(temp_to_heat))

                self.async_update_ha_state()
        except timeout:
            _LOGGER.error("Thermostat %s start_heating timeout", self._name)

    def stop_heating(self):
        """Turn heater off (set min heating temp)"""
        temp_to_idle = self._min_temp

        # check if already idling
        if self._thermostat_target_temp <= temp_to_idle and self._thermostat_current_action == CURRENT_HVAC_IDLE:
            return

        try:
            device = self.thermostat()
            if device.auth():
                device.set_power(BROADLINK_POWER_ON)
                device.set_mode(BROADLINK_MODE_MANUAL, self._thermostat_loop_mode, self.thermostat_get_sensor())
                device.set_temp(float(temp_to_idle))

                self.async_update_ha_state()
        except timeout:
            _LOGGER.error("Thermostat %s stop_heating timeout", self._name)
