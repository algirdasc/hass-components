# Intro
Component for controlling Floureon or other chinese-based WiFi smart thermostat. Climate component will have 3 modes: "auto" (in which will used thermostat's internal schedule), "heat (which is "manual" mode) and "off". Also, while in "heat" mode it is possible to use preset "away". Changing mode to other than "heat" will set preset to "none". 

# Configuration
Required parameters:
```
- platform: floureon
  host: <thermostat ip / hostname>
  mac: <thermostat mac address>
  name: <thermostat name>  
```
Optional parameters:
```
  schedule: <integer> [0, 1 or 2]
  use_external_temp: <boolean> use external temperature sensor for temperature calculation    
```
Example:
```
- platform: floureon
  name: livingroom_floor
  mac: 78:0f:77:00:00:00
  host: 192.168.0.1
  use_external_temp: false
```
