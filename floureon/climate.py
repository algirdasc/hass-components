import logging
import time
from datetime import timedelta
from datetime import datetime
from socket import timeout

import custom_components.broadlink.pid_controller as pid_controller
import broadlink

import voluptuous as vol

from homeassistant.components.climate import ClimateDevice, PLATFORM_SCHEMA

from homeassistant.components.climate.const import (
    STATE_ECO,
    STATE_MANUAL,
    STATE_IDLE,
    STATE_HEAT,
    STATE_AUTO,
    SUPPORT_OPERATION_MODE,
    SUPPORT_AWAY_MODE,
    SUPPORT_TARGET_TEMPERATURE,
    DEFAULT_MIN_TEMP,
    DEFAULT_MAX_TEMP
)

from homeassistant.const import (
    PRECISION_HALVES,
    STATE_ON,
    STATE_OFF,
    STATE_UNKNOWN,
    ATTR_TEMPERATURE,
    CONF_NAME
)

from homeassistant.helpers.event import (
    async_track_time_interval
)

import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

REQUIREMENTS = ['broadlink==0.9.0']

DEFAULT_USE_EXTERNAL_TEMP = True
DEFAULT_INITIAL_OPERATION_MODE = STATE_ECO
DEFAULT_SCHEDULE = 1
DEFAULT_DIFFERENCE = 100
DEFAULT_PWM = 300
DEFAULT_KP = 100
DEFAULT_KI = 40
DEFAULT_KD = 60
DEFAULT_AUTOTUNE = 'none'
DEFAULT_NOISEBAND = 0.5
DEFAULT_CHECK_INTERVAL = timedelta(minutes=5)

CONF_HOST = 'host'
CONF_MAC = 'mac'
CONF_CHECK_INTERVAL = 'check_interval'
CONF_SCHEDULE = 'schedule'
CONF_USE_EXTERNAL_TEMP = 'use_external_temp'
CONF_TARGET_TEMP = 'target_temp'
CONF_INITIAL_OPERATION_MODE = 'initial_operation_mode'
CONF_AWAY_TEMP = 'away_temp'
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
    vol.Required(CONF_TARGET_TEMP): vol.Coerce(float),
    vol.Required(CONF_AWAY_TEMP): vol.Coerce(float),
    vol.Required(CONF_NAME): cv.string,
    vol.Required(CONF_CHECK_INTERVAL): vol.All(cv.time_period, cv.positive_timedelta),

    vol.Optional(CONF_SCHEDULE, default=DEFAULT_SCHEDULE): vol.Coerce(int),
    vol.Optional(CONF_USE_EXTERNAL_TEMP, default=DEFAULT_USE_EXTERNAL_TEMP): cv.boolean,
    vol.Optional(CONF_INITIAL_OPERATION_MODE, default=DEFAULT_INITIAL_OPERATION_MODE): vol.In([STATE_ECO,
                                                                                               STATE_AUTO,
                                                                                               STATE_MANUAL,
                                                                                               STATE_OFF]),
    vol.Optional(CONF_DIFFERENCE, default=DEFAULT_DIFFERENCE): vol.Coerce(float),
    vol.Optional(CONF_KP, default=DEFAULT_KP): vol.Coerce(float),
    vol.Optional(CONF_KI, default=DEFAULT_KI): vol.Coerce(float),
    vol.Optional(CONF_KD, default=DEFAULT_KD): vol.Coerce(float),
    vol.Optional(CONF_PWM, default=DEFAULT_PWM): vol.Coerce(float),
    vol.Optional(CONF_AUTOTUNE, default=DEFAULT_AUTOTUNE): cv.string,
    vol.Optional(CONF_NOISEBAND, default=DEFAULT_NOISEBAND): vol.Coerce(float)
})


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the generic thermostat platform."""
    name = config.get(CONF_NAME)
    host = config.get(CONF_HOST)
    mac = config.get(CONF_MAC)
    use_external_temp = config.get(CONF_USE_EXTERNAL_TEMP)
    target_temp = config.get(CONF_TARGET_TEMP)
    check_interval = config.get(CONF_CHECK_INTERVAL)
    initial_operation_mode = config.get(CONF_INITIAL_OPERATION_MODE)
    difference = config.get(CONF_DIFFERENCE)
    away_temp = config.get(CONF_AWAY_TEMP)
    kp = config.get(CONF_KP)
    ki = config.get(CONF_KI)
    kd = config.get(CONF_KD)
    pwm = config.get(CONF_PWM)
    autotune = config.get(CONF_AUTOTUNE)
    noiseband = config.get(CONF_NOISEBAND)
    schedule = config.get(CONF_SCHEDULE)

    add_entities([BroadlinkPIDThermostat(
        hass, name, host, mac, use_external_temp, target_temp, check_interval, schedule,
        initial_operation_mode, difference, away_temp, kp, ki, kd, pwm, autotune, noiseband)])


class BroadlinkPIDThermostat(ClimateDevice):

    def __init__(self, hass, name, host, mac, use_external_temp, target_temp, check_interval, schedule,
                 initial_operation_mode, difference, away_temp, kp, ki, kd, pwm, autotune, noiseband):

        self.hass = hass
        self._name = name
        self._host = host
        self._port = 80
        self._mac = bytes.fromhex(''.join(reversed(mac.split(':'))))
        self._unit = hass.config.units.temperature_unit

        # Properties
        self._use_external_temp = use_external_temp
        self._target_temp = target_temp
        self._operation_list = [STATE_ECO, STATE_AUTO, STATE_MANUAL, STATE_OFF]
        self._current_operation = initial_operation_mode
        self._pre_away_target_temp = self._target_temp
        self._pre_away_operation = self._current_operation
        self._is_away = False
        self._away_temp = away_temp
        self._autotune = autotune
        self._kp = kp
        self._ki = ki
        self._kd = kd
        self._pwm = pwm
        self._control_output = None
        self._min_out = 0
        self._max_out = difference
        self._difference = difference
        self._time_changed = time.time()
        self._check_interval = check_interval

        if self._autotune != "none":
            self.pid_autotune = pid_controller.PIDAutotune(
                self._target_temp,
                sampletime=self._check_interval.seconds,
                out_step=difference,
                lookback=self._check_interval.seconds,
                out_min=self._min_out,
                out_max=self._max_out,
                noiseband=noiseband
            )
            _LOGGER.warning("Auto-tune will run with the next target temperature value you set."
                            "changes, submitted after doesn't have any effect until it's finished.")
        else:
            self.pid_controller = pid_controller.PIDArduino(
                self._check_interval.seconds, self._kp, self._ki, self._kd, out_min=self._min_out, out_max=self._max_out
            )

        # Thermostat properties
        self._thermostat_target_temp = None
        self._current_state = None
        self._current_temp = None
        self._external_temp = None
        self._internal_temp = None
        self._loop_mode = schedule
        self._hysteresis = None
        self._min_temp = DEFAULT_MIN_TEMP
        self._max_temp = DEFAULT_MAX_TEMP

        # Set thermostat time
        self.thermostat_set_time()

        # Read thermostat data
        self.thermostat_read_status()

        async_track_time_interval(hass, self.async_check_output, self._check_interval)

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
                device.set_time(now.hour, now.minute, now.second, now.weekday())
                _LOGGER.info("Thermostat %s set time to %s:%s:%s, weekday %s",
                             now.hour, now.minute, now.second, now.weekday())
        except timeout:
            _LOGGER.error("Thermostat %s set_time timeout", self._name)
        except Exception:
            _LOGGER.error("Thermostat %s set_time error", self._name)

    def thermostat_read_status(self):
        """Read thermostat data"""
        try:
            device = self.thermostat()
            if device.auth():
                data = device.get_full_status()

                if self._use_external_temp is True:
                    self._current_temp = data['external_temp']
                else:
                    self._current_temp = data['room_temp']

                self._external_temp = data['external_temp']
                self._internal_temp = data['room_temp']
                self._thermostat_target_temp = data['thermostat_temp']

                self._hysteresis = int(data['dif'])
                self._min_temp = int(data['svl'])
                self._max_temp = int(data['svh'])

                if data["power"] == BROADLINK_POWER_OFF:
                    self._current_state = STATE_OFF
                elif data["power"] == BROADLINK_POWER_ON and data["active"] == BROADLINK_ACTIVE:
                    self._current_state = STATE_HEAT
                elif data["power"] == BROADLINK_POWER_ON and data["active"] == BROADLINK_IDLE:
                    self._current_state = STATE_IDLE
                else:
                    self._current_state = STATE_UNKNOWN

                if not self._current_operation == STATE_ECO:
                    if data["power"] == BROADLINK_POWER_OFF:
                        self._current_operation = STATE_OFF
                    elif data["power"] == BROADLINK_POWER_ON and data["auto_mode"] == BROADLINK_MODE_AUTO:
                        self._current_operation = STATE_AUTO
                        self._target_temp = self._thermostat_target_temp
                    elif data["power"] == BROADLINK_POWER_ON and data["auto_mode"] == BROADLINK_MODE_MANUAL:
                        self._current_operation = STATE_MANUAL

        except timeout:
            _LOGGER.warning("Thermostat %s read_status timeout", self._name)

    @property
    def state(self):
        """Return the current state."""
        return self._current_state

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return SUPPORT_TARGET_TEMPERATURE | SUPPORT_OPERATION_MODE | SUPPORT_AWAY_MODE

    @property
    def should_poll(self):
        """Return the polling state."""
        return True

    @property
    def name(self):
        """Return the name of the thermostat."""
        return self._name

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return self._unit

    @property
    def current_temperature(self):
        """Return the sensor temperature."""
        return self._current_temp

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target_temp

    @property
    def current_operation(self):
        """Return current operation."""
        return self._current_operation

    @property
    def operation_list(self):
        """List of available operation modes."""
        return self._operation_list

    @property
    def is_away_mode_on(self):
        """Return if away mode is on."""
        return self._is_away

    @property
    def is_on(self):
        """Return true if the device is on."""
        return not self._current_operation == STATE_OFF

    @property
    def precision(self):
        """Return the precision of the system."""
        return PRECISION_HALVES

    @property
    def min_temp(self):
        """Return the minimum temperature."""
        return self._min_temp

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        return self._max_temp

    @property
    def device_state_attributes(self):
        """Return the attribute(s) of the sensor"""
        return {
            "thermostat_target_temp": self._thermostat_target_temp,
            "kp": self._kp,
            "ki": self._ki,
            "kd": self._kd
        }

    def set_temperature(self, **kwargs):
        """Set new target temperature."""
        if kwargs.get(ATTR_TEMPERATURE) is not None:
            self._target_temp = float(kwargs.get(ATTR_TEMPERATURE))
            # Set thermostat temperature if mode is set other than ECO
            if self._current_operation == STATE_ECO:
                self.pid_control_heating()
            else:
                try:
                    device = self.thermostat()
                    if device.auth():
                        device.set_power(BROADLINK_POWER_ON)
                        device.set_mode(BROADLINK_MODE_MANUAL, self._loop_mode, self.thermostat_get_sensor())
                        device.set_temp(self._target_temp)
                except timeout:
                    _LOGGER.error("Thermostat %s set_temperature timeout", self._name)

    def set_operation_mode(self, operation_mode):
        """Set operation mode."""
        self._current_operation = operation_mode
        if self._current_operation == STATE_ECO:
            self.pid_control_heating()
        else:
            try:
                device = self.thermostat()
                if device.auth():
                    if self._current_operation == STATE_OFF:
                        device.set_power(BROADLINK_POWER_OFF)
                    if self._current_operation == STATE_AUTO:
                        device.set_power(BROADLINK_POWER_ON)
                        device.set_mode(BROADLINK_MODE_AUTO, self._loop_mode, self.thermostat_get_sensor())
                    elif self._current_operation == STATE_MANUAL:
                        device.set_power(BROADLINK_POWER_ON)
                        device.set_mode(BROADLINK_MODE_MANUAL, self._loop_mode, self.thermostat_get_sensor())
                        device.set_temp(self._target_temp)
            except timeout:
                _LOGGER.error("Thermostat %s set_operation_mode timeout", self._name)

    def update(self):
        self.thermostat_read_status()

    def turn_away_mode_on(self):
        """Turn away mode on."""
        self._pre_away_target_temp = self._target_temp
        self._pre_away_operation = self._current_operation
        self._is_away = True
        self._target_temp = self._away_temp
        if self._current_operation == STATE_ECO:
            self.set_operation_mode(STATE_ECO)
        else:
            self.set_operation_mode(STATE_MANUAL)

    def turn_away_mode_off(self):
        """Turn away mode off."""
        self._is_away = False
        self._target_temp = self._pre_away_target_temp
        self.set_operation_mode(self._pre_away_operation)

    #############
    # PID Part #
    #############

    async def async_check_output(self, time):
        """Call at constant intervals for keep-alive purposes."""
        if self._current_operation == STATE_ECO:
            self.pid_control_heating()

    def pid_control_heating(self):
        """Run PID controller, optional auto-tune for faster integration"""
        self.pid_calculate_output()

    def start_heating(self):
        """Turn heater toggleable device on."""
        # temp_to_turn_on = self._current_temp + self._hysteresis + 0.5

        temp_to_turn_on = self._max_temp

        if self._thermostat_target_temp >= temp_to_turn_on and self._current_state == STATE_HEAT:
            return

        # TODO: gal perkelti self._time_changed? paziureti kaip originaliai yra, kada keiciasi time_changed

        try:
            device = self.thermostat()
            if device.auth():
                device.set_power(BROADLINK_POWER_ON)
                device.set_mode(BROADLINK_MODE_MANUAL, self._loop_mode, self.thermostat_get_sensor())
                device.set_temp(float(temp_to_turn_on))

                self.async_update_ha_state()

                _LOGGER.info("Setting thermostat %s temperature to %s (turn on)", self._name, temp_to_turn_on)
        except timeout:
            _LOGGER.error("Thermostat %s _heater_turn_on timeout", self._name)

    def stop_heating(self):
        """Turn heater toggleable device off."""
        # temp_to_turn_off = self._current_temp - self._hysteresis

        temp_to_turn_off = self._min_temp

        if self._thermostat_target_temp <= temp_to_turn_off and not self._current_state == STATE_HEAT:
            return

        try:
            device = self.thermostat()
            if device.auth():
                device.set_power(BROADLINK_POWER_ON)
                device.set_mode(BROADLINK_MODE_MANUAL, self._loop_mode, self.thermostat_get_sensor())
                device.set_temp(float(temp_to_turn_off))

                self.async_update_ha_state()

                _LOGGER.info("Setting thermostat %s temperature to %s (turn off)", self._name, temp_to_turn_off)
        except timeout:
            _LOGGER.error("Thermostat %s _heater_turn_off timeout", self._name)

    def pid_calculate_output(self):
        """Calculate control output and handle auto-tune"""

        if self._autotune != "none":

            if self.pid_autotune.run(self._current_temp):

                params = self.pid_autotune.get_pid_parameters(self._autotune)

                _LOGGER.info("%s", params)

                self._kp = params.Kp
                self._ki = params.Ki
                self._kd = params.Kd

                _LOGGER.info("Tuned Kd, Ki, Kd. "
                             "Smart thermostat now runs on PID Controller. %s,  %s,  %s",
                             self._kp, self._ki, self._kd)

                self.pid_controller = pid_controller.PIDArduino(
                    self._check_interval.seconds, self._kp, self._ki, self._kd, self._min_out, self._max_out, time.time
                )

                self._autotune = "none"

            self._control_output = self.pid_autotune.output
        else:
            self._control_output = self.pid_controller.calc(self._current_temp, self._target_temp)

        # _LOGGER.info("Thermostat %s obtained current control output: %s", self._name, self._control_output)

        self.pid_set_control_value()

    def pid_set_control_value(self):
        """Set output value for heater"""
        if self._control_output == self._difference or self._control_output == -self._difference:
            self.start_heating()
            self._time_changed = time.time()
        elif self._control_output > 0:
            self.pwm_switch(
                self._pwm * self._control_output / self._max_out,
                self._pwm * (self._max_out - self._control_output) / self._max_out,
                time.time() - self._time_changed
            )
        elif self._control_output < 0:
            self.pwm_switch(
                self._pwm * self._control_output / self._min_out,
                self._pwm * self._min_out / self._control_output,
                time.time() - self._time_changed
            )
        else:
            self.stop_heating()
            self._time_changed = time.time()

    def pwm_switch(self, time_on, time_off, time_passed):
        """turn off and on the heater proportionally to control value."""
        _LOGGER.debug("pwm_switch(%s) time_on=%s time_off=%s time_passed=%s co=%s",
                      self._name, int(time_on), int(time_off), int(time_passed), int(self._control_output))
        if self._current_state == STATE_HEAT:
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
