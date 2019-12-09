# Your support
<a href="https://www.buymeacoffee.com/Ua0JwY9" target="_blank"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy Me A Coffee" style="height: 41px !important;width: 174px !important;box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;-webkit-box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;" ></a>

# Intro
Component for controlling Floureon or other chinese-based WiFi smart thermostat (Beok and others). Climate component will have 3 modes: "auto" (in which will used thermostat's internal schedule), "heat (which is "manual" mode) and "off". Also, while in "heat" mode it is possible to use preset "away". Changing mode to other than "heat" will set preset to "none". 

If you want to use custom or more advanced controll, you should use switch component and generic thermostat in Home Assistant instead. See below for configuration.

# Configuration as a Climate
Required parameters:
```
- platform: floureon
  host: <thermostat ip / hostname>
  mac: <thermostat mac address>
  name: <thermostat name>  
```
Optional parameters:
```
  schedule: <integer>
```
  _0 - Schedule 1234567_
  _1 - Schedule 123456,7_
  _2 - Schedule 12345,67_
```
  use_external_temp: <boolean>
``` 
  _Set to true if you want to use thermostat`s external temperature sensor for temperature calculation_
```
Example:
```
climate:
  platform: floureon
  name: livingroom_floor
  mac: 78:0f:77:00:00:00
  host: 192.168.0.1
  use_external_temp: false
```

# Configuration as a Switch
Required parameters:
```
- platform: floureon
  host: <thermostat ip / hostname>
  mac: <thermostat mac address>
  name: <thermostat name>  
```
Optional parameters:
```
  turn_off_mode: <string>
```  
  _min_temp - thermostat will be turned off by setting minimum temperature available, 
  turn_off - thermostat will by turned off completely_  
```
  turn_on_mode: <string, float>
```  
  _max_temp - thermostat will be turned on by setting maximum temperature available,  
  float (ex. 20.0 - *must be set to float, meaning that dot zero / dot five part is mandatory!*) - thermostat will be turned on by setting desired temperature_
```
Example:
```
switch:
  platform: floureon
  name: livingroom_floor
  mac: 78:0f:77:00:00:00
  host: 192.168.0.1
  turn_off_mode: min_temp
  turn_on_mode: 23.5
```
