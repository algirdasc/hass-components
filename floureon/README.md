More info about PID: https://github.com/fabiannydegger/custom_components

Required parameters:
```
- platform: floureon
  host: <thermostat ip / hostname>
  mac: <thermostat mac address>
  target_temp: <default target temperature>
  away_temp: <away temperature>
  name: <thermostat name>
  check_interval: <time period> for calculating PID control output
```
Optional parameters:
```
  schedule: <integer> [0, 1 or 2]
  use_external_temp: <boolean> use external temperature sensor for temperature calculation  
  initial_operation_mode: <string> - values: eco, auto, 'off', manual'
  difference: <integer> Analog output offset
  kp: <float> PID parameter, p controll value.
  ki: <float> PID parameter, i controll value.
  kd: <float> PID parameter, d controll value.
  pwm: <integer> PWM time in seconds
  autotune: <string> Choose a string for autotune settings - "ziegler-nichols", "tyreus-luyben", "ciancone-marlin", "pessen-integral", "some-overshoot", "no-overshoot", "brewing"
```
Example:
```
- platform: floureon
  name: livingroom_floor
  mac: 78:0f:77:00:00:00
  host: 192.168.0.1
  away_temp: 10
  target_temp: 23
  autotune: "some-overshoot"
  initial_operation_mode: eco
  ki: 5.476
  kp: 8.488
  kd: 8.771
  pwm: 300
  check_interval:
    seconds: 30
  scan_interval:
    seconds: 15
```
