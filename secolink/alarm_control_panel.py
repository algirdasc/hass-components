import logging
import re
import sys
import socketserver
import threading
import asyncio
import datetime

import homeassistant.components.alarm_control_panel as alarm
from homeassistant.components.alarm_control_panel.const import (
    SUPPORT_ALARM_ARM_AWAY, SUPPORT_ALARM_ARM_HOME, SUPPORT_ALARM_ARM_NIGHT
)
from homeassistant.const import (     
    STATE_ALARM_ARMED_AWAY, STATE_ALARM_ARMED_HOME, STATE_ALARM_ARMED_NIGHT,
    STATE_ALARM_DISARMED, STATE_ALARM_TRIGGERED, STATE_UNKNOWN)

_LOGGER = logging.getLogger(__name__)

QUAL_OPEN = 1
QUAL_CLOSE = 3


def setup_platform(hass, config, add_devices, discovery_info=None):
    add_devices([SecolinkAlarm(
        hass, config
    )])


class SecolinkAlarm(alarm.AlarmControlPanel):

    def __init__(self, hass, config):
        self._name = str(config.get('name'))
        self._username = str(config.get('username', ''))
        self._password = str(config.get('password', ''))
        self._clientid = str(config.get('clientid', '0000'))
        self._listen_ip = str(config.get('listen_ip', '0.0.0.0'))
        self._listen_port = int(config.get('listen_port', 8125))

        self._last_heartbeat = None
        self._last_event_at = None
        self._last_event_type = None
        self._last_event_zone = None
        self._last_event_area = None
        self._last_event_qual = None
        self._changed_by = None
        self._state = STATE_UNKNOWN

        server = ThreadedTCPServer((self._listen_ip, self._listen_port), ThreadedTCPRequestHandler)
        server.secolink = self

        # Start a thread with the server -- that thread will then start one
        # more thread for each request
        server_thread = threading.Thread(target=server.serve_forever)

        # Exit the server thread when the main thread terminates
        server_thread.daemon = True
        server_thread.start()

    @property
    def should_poll(self):
        return False

    @property
    def name(self):
        return self._name

    @property
    def state(self):
        return self._state

    @property
    def code_format(self):
        return '^\d+{4,6}'

    @property
    def changed_by(self):
        return self._changed_by

    @property
    def supported_features(self):
        return SUPPORT_ALARM_ARM_AWAY | SUPPORT_ALARM_ARM_HOME | SUPPORT_ALARM_ARM_NIGHT

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        state_attr = {}

        state_attr['last_heartbeat'] = self._last_heartbeat
        state_attr['last_event_type'] = self._last_event_type
        state_attr['last_event_zone'] = self._last_event_zone
        state_attr['last_event_area'] = self._last_event_area
        state_attr['last_event_qual'] = self._last_event_qual
        state_attr['last_event_at'] = self._last_event_at

        return state_attr

    @asyncio.coroutine
    def async_alarm_disarm(self, code=None):
        """Send disarm command."""
        _LOGGER.debug("alarm_disarm: %s", code)
        if code:
            _LOGGER.debug("alarm_disarm: sending %s1", str(code))
            pass

    @asyncio.coroutine
    def async_alarm_arm_away(self, code=None):
        """Send arm away command."""
        _LOGGER.debug("alarm_arm_away: %s", code)
        if code:
            _LOGGER.debug("alarm_arm_away: sending %s2", str(code))
            pass

    @asyncio.coroutine
    def async_alarm_arm_home(self, code=None):
        """Send arm home command."""
        _LOGGER.debug("alarm_arm_home: %s", code)
        if code:
            _LOGGER.debug("alarm_arm_home: sending %s3", str(code))
            pass


class ThreadedTCPRequestHandler(socketserver.BaseRequestHandler):

    def handle(self):
        try:
            data = self.request.recv(32).strip()
            if not data:
                return

            data = data.decode('utf-8')
            match = re.match('^(.*?),(.*?),(\d{4}),18(\d)(\d{3})([A-F0-9]{2})(\d{3})$', data)
            if not match:
                _LOGGER.warning("Received unknown message from {0}: {1}".format(self.client_address[0], data))
                return

            event_username = match.group(1)
            event_password = match.group(2)
            event_clientid = match.group(3)

            if not event_username == self.server.secolink._username:
                _LOGGER.warning("Wrong username '{0}' from {1}".format(event_username, self.client_address[0]))
                return

            if not event_password == self.server.secolink._password:
                _LOGGER.warning("Wrong password '{0}' from {1}".format(event_password, self.client_address[0]))
                return

            if not event_clientid == self.server.secolink._clientid:
                _LOGGER.warning("Wrong Client ID '{0}' from {1}".format(event_clientid, self.client_address[0]))
                return

            self.request.send('ACK'.encode('utf-8'))

            event_qual = match.group(4)
            event_type = match.group(5)
            event_area = match.group(6)
            event_zone = match.group(7)

            _LOGGER.debug("Received event from {0}. Type: {1}, Area {2}, Zone {3}, Qualifier {4}".format(
                self.client_address[0], event_type, event_area, event_zone, event_qual))

            event_type = int(event_type)
            event_qual = int(event_qual)

            is_heartbeat = False
            if 100 <= event_type < 200:  # ALARMS
                self.server.secolink._state = STATE_ALARM_TRIGGERED
                self.server.secolink._changed_by = event_zone
            elif 400 <= event_type < 410:  # ARM / DISARM
                if event_qual == QUAL_OPEN:
                    self.server.secolink._state = STATE_ALARM_DISARMED
                    self.server.secolink._changed_by = event_zone
                elif event_qual == QUAL_CLOSE:
                    self.server.secolink._state = STATE_ALARM_ARMED_AWAY
                    self.server.secolink._changed_by = event_zone
            elif event_type == 441 and re.match(r'1\d\d', event_zone):  # STAY
                if event_qual == QUAL_OPEN:
                    self.server.secolink._state = STATE_ALARM_DISARMED
                    self.server.secolink._changed_by = event_zone
                elif event_qual == QUAL_CLOSE:
                    self.server.secolink._state = STATE_ALARM_ARMED_HOME
                    self.server.secolink._changed_by = event_zone
            elif event_type == 441 and re.match(r'2\d\d', event_zone):  # NIGHT
                if event_qual == QUAL_OPEN:
                    self.server.secolink._state = STATE_ALARM_DISARMED
                    self.server.secolink._changed_by = event_zone
                elif event_qual == QUAL_CLOSE:
                    self.server.secolink._state = STATE_ALARM_ARMED_NIGHT
                    self.server.secolink._changed_by = event_zone
            elif event_type == 602:  # HEARTBEAT
                self.server.secolink._last_heartbeat = datetime.datetime.now()
                is_heartbeat = True

            if is_heartbeat is not True:
                self.server.secolink._last_event_at = datetime.datetime.now()
                self.server.secolink._last_event_type = event_type
                self.server.secolink._last_event_area = event_area
                self.server.secolink._last_event_zone = event_zone
                self.server.secolink._last_event_qual = event_qual

            self.server.secolink.async_schedule_update_ha_state()

        except Exception as ex:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            _LOGGER.error("Error parsing CSV IP message from {0}".format(self.client_address[0]))
            _LOGGER.error("Error: {0}".format(str(ex)))
            _LOGGER.error("Line: {0}".format(exc_tb.tb_lineno))


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True
