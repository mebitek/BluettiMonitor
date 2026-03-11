#!/usr/bin/env python

"""
Created by mebitek in 2026.

Inspired by:
 - https://github.com/victronenergy/velib_python/blob/master/dbusdummyservice.py (Template)


This code and its documentation can be found on: https://github.com/mebitek/BluettiMonitor
Used https://github.com/victronenergy/velib_python/blob/master/dbusdummyservice.py as basis for this service.
Reading information from Tasmota SENSOR MQTT and puts the info on dbus as inverter.

"""

import os
import sys
import json
import logging
import dbus
import requests
import _thread as thread
import subprocess
from datetime import datetime, timedelta
import utils


# add the path to our own packages for import
sys.path.insert(1, "/data/SetupHelper/velib_python")

from vedbus import VeDbusService, VeDbusItemImport
from gi.repository import GLib
from vreg_link_item import VregLinkItem, GenericReg, BluettiReg

from bluetti_config import BluettiConfig


class Bluetti:
    def __init__(self, mac, _type, soc, voltage, current, power, temperature):
        self.mac = mac
        self.type = _type
        self.voltage = voltage
        self.current = current
        self.power = power
        self.temperature = temperature
        self.soc = soc
        self.last_update = None

class BluettiMonitorService:
    def __init__(
        self,
        servicename,
        deviceinstance,
        paths,
        productname="Bluetti",
        connection="MQTT",
        config=None,
    ):

        self.config = config or BluettiConfig()

        # bluetti class
        self.bluetti = Bluetti(config.get_device_mac(), config.get_device_type(), 0, 12.8, 0, 0, 0)
        logging.debug("* * * MAC %s", self.bluetti.mac)
        logging.debug("* * * TYPE %s", self.bluetti.type)

        # dbus service
        self._dbusservice = VeDbusService(servicename, register=False)
        self._paths = paths

        vregtype = lambda *args, **kwargs: VregLinkItem(*args, **kwargs, getvreg=self.vreg_link_get, setvreg=self.vreg_link_set)

        logging.debug("%s /DeviceInstance = %d" % (servicename, deviceinstance))

        productname = "Bluetti " + config.get_device_type()
        logging.debug("* * * Product name is %s", productname)

        # Create the management objects, as specified in the ccgx dbus-api document
        self._dbusservice.add_path("/Mgmt/ProcessName", __file__)
        self._dbusservice.add_path("/Mgmt/ProcessVersion", config.get_version())
        self._dbusservice.add_path("/Mgmt/Connection", connection)

        # Create the mandatory objects
        self._dbusservice.add_path("/DeviceInstance", deviceinstance)
        # value used in ac_sensor_bridge.cpp of dbus-cgwacs
        self._dbusservice.add_path("/ProductId", 0xA383)
        self._dbusservice.add_path("/ProductName", productname)
        self._dbusservice.add_path("/DeviceName", productname)
        self._dbusservice.add_path("/FirmwareVersion", 0x0419)
        self._dbusservice.add_path("/HardwareVersion", 8)
        self._dbusservice.add_path("/Connected", 1)
        self._dbusservice.add_path("/Serial", config.get_serial())

        self._dbusservice.add_path('/Devices/0/CustomName', productname)
        self._dbusservice.add_path('/Devices/0/DeviceInstance', deviceinstance)
        self._dbusservice.add_path('/Devices/0/FirmwareVersion', 0x0419)
        self._dbusservice.add_path('/Devices/0/ProductId', 0xA383)
        self._dbusservice.add_path('/Devices/0/ProductName', productname)
        self._dbusservice.add_path('/Devices/0/ServiceName', servicename)
        self._dbusservice.add_path('/Devices/0/Serial', config.get_serial())
        self._dbusservice.add_path('/Devices/0/VregLink', None, itemtype=vregtype)

        for path, settings in self._paths.items():
            self._dbusservice.add_path(
                path,
                settings["initial"],
                writeable=True,
                onchangecallback=self._handlechangedvalue,
            )

        self._dbusservice.register()
        GLib.timeout_add(1000, self._update)

    def _update(self):

        try:

            if self.bluetti.last_update is None or datetime.now() > self.bluetti.last_update + timedelta(
                    minutes=self.config.get_interval()):

                output = subprocess.run(['bluetti-read', '-m', self.bluetti.mac, "-t", self.bluetti.type],
                                capture_output=True, text=True)


                in_power_dc = None
                in_power_ac = None 
                in_voltage_dc = None
                power = self.config.get_standby_current() # round standy consumpiton
                lines = output.stdout.splitlines();       

                        
                for line in lines:
                    if "FieldName.BATTERY_SOC" in line:
                        soc = int(line.split(":")[1].strip().replace("%", ""))
                        
                        self._dbusservice["/Soc"] = soc
                        self.bluetti.soc = soc

                        if self.bluetti.soc < 20:
                            logging.debug("* * * Set turbo mode")
                            subprocess.run(['bluetti-write', '-m', self.bluetti.mac, "-t", self.bluetti.type, '-v', '2', 'ctrl_charging_mode'])
                        elif self.bluetti.soc > 80:
                            logging.debug("* * * Set silent mode")
                            subprocess.run(['bluetti-write', '-m', self.bluetti.mac, "-t", self.bluetti.type, '-v', '1', 'ctrl_charging_mode'])

                        else:
                            logging.debug("* * * Set normal mode")
                            subprocess.run(['bluetti-write', '-m', self.bluetti.mac, "-t", self.bluetti.type, '-v', '0', 'ctrl_charging_mode'])


                    if "FieldName.DC_OUTPUT_POWER" in line:
                        power = int(line.split(":")[1].strip().replace("W", "")) + power
                        self.bluetti.power = power + (power/100) #add parasite power consumpiton
                    
                    if "FieldName.AC_INPUT_POWER" in line:
                        in_power_ac = int(line.split(":")[1].strip().replace("W", ""))

                    if "FieldName.DC_INPUT_POWER" in line:
                        in_power_dc = int(line.split(":")[1].strip().replace("W", ""))
                    if "FieldName.DC_INPUT_VOLTAGE" in line: 
                        in_voltage_dc = float(line.split(":")[1].strip().replace("V", ""))

            
                if self.bluetti.soc == 100:
                    self.bluetti.voltage = 13.6
                elif self.bluetti.soc == 99:
                    self.bluetti.voltage = 13.4
                elif self.bluetti.soc > 90 and self.bluetti.soc < 99:
                    self.bluetti.voltage = 13.3
                elif self.bluetti.soc > 70 and self.bluetti.soc < 90:
                    self.bluetti.voltage = 13.2
                elif self.bluetti.soc > 40 and self.bluetti.soc < 70:
                    self.bluetti.voltage = 13.1
                elif self.bluetti.soc > 30 and self.bluetti.soc < 40:
                    self.bluetti.voltage = 13.0
                elif self.bluetti.soc > 20 and self.bluetti.soc < 30:
                    self.bluetti.voltage = 12.9
                elif self.bluetti.soc > 17 and self.bluetti.soc < 20:
                    self.bluetti.voltage = 12.8
                elif self.bluetti.soc > 14 and self.bluetti.soc < 17:
                    self.bluetti.voltage = 12.5
                elif self.bluetti.soc > 9 and self.bluetti.soc < 14:
                    self.bluetti.voltage = 12.0
                elif self.bluetti.soc > 0 and self.bluetti.soc < 9:
                    self.bluetti.voltage = 10.0


                self.bluetti.last_update = datetime.now()

                self._dbusservice["/Dc/0/Voltage"] = self.bluetti.voltage  
                current = 0
                if self.bluetti.power > 0:
                    self._dbusservice["/Dc/0/Power"] = -power
                    current = -(self.bluetti.power / self.bluetti.voltage)


                if in_power_dc and in_voltage_dc:
                    power = -power + in_power_dc
                    self._dbusservice["/Dc/0/Power"] = power
                    current = (in_power_dc / in_voltage_dc) + current

                if in_power_ac:
                    power = power + in_power_ac
                    self._dbusservice["/Dc/0/Power"] = power
                    current = current + (in_power_ac/14.6)
                
                self._dbusservice["/Dc/0/Current"] = current
                self.bluetti.current = current

                # time_to_go = self.remaining_time_seconds(self.bluetti.soc, self.bluetti.current)
                # self._dbusservice["/TimeToGo"] = time_to_go

                logging.debug("* * * BATTERY SOC %s", self.bluetti.soc)
                logging.debug("* * * BATTERY VOLTAGE %s", self.bluetti.voltage)
                logging.debug("* * * CURRENT %s", self.bluetti.current)
                logging.debug("* * * DC POWER %s", power)


            else:
                logging.debug("* * * Skip Interval")

           
        except Exception:
            logging.exception("Exception while getting bluetti status")

        index = self._dbusservice["/UpdateIndex"] + 1  # increment index
        if index > 255:  # maximum value of the index
            index = 0  # overflow from 255 to 0
        self._dbusservice["/UpdateIndex"] = index
        return True


    def _handlechangedvalue(self, path, value):
        logging.debug("someone else updated %s to %s" % (path, value))
        return True  # accept the change

    @staticmethod
    def vreg_link_get(reg_id):
        if reg_id == BluettiReg.DC_MONITOR_MODE.value:
            return GenericReg.OK.value, [0xFE]
        elif reg_id == BluettiReg.VE_REG_BATTERY_CAPACITY.value:
            battery_capacity = float(self.config.get_battery_capacity())
            return GenericReg.OK.value, utils.convert_decimal(battery_capacity)
        elif reg_id == BluettiReg.VE_REG_CHARGED_VOLTAGE.value:
            return GenericReg.OK.value, utils.convert_decimal(1.36)
        elif reg_id == BluettiReg.VE_REG_PEUKERT_COEFFICIENT.value:
            return GenericReg.OK.value, utils.convert_decimal(1.01)
        elif reg_id == BluettiReg.VE_REG_CHARGE_DETECTION_TIME.value:
            return GenericReg.OK.value, utils.convert_decimal(0.03)
        elif reg_id == BluettiReg.VE_REG_CHARGE_EFFICIENCY.value:
            return GenericReg.OK.value, utils.convert_decimal(0.98)
        elif reg_id == BluettiReg.VE_REG_CURRENT_THRESHOLD.value:
            return GenericReg.OK.value, utils.convert_decimal(0.1)
        elif reg_id == BluettiReg.VE_REG_BAT_TAIL_CURRENT.value:
            return GenericReg.OK.value, utils.convert_decimal(0.02)
        else:
            logging.debug("GET REG_ID %s" % regid)
            return GenericReg.OK.value, []


    @staticmethod
    def vreg_link_set(reg_id, data):
        return GenericReg.OK.value, data

    # def remaining_time_seconds(self, soc, current_a):

    #     MIN_CURRENT = 0.1 

    #     if current_a >= -MIN_CURRENT:
    #         return 864000 

    #     remaining_ah = self.config.get_battery_capacity() * (soc / 100.0)

    #     hours = remaining_ah / abs(current_a)

    #     seconds = int(hours * 3600)

    #     return seconds

def main():
    config = BluettiConfig()

    # set logging level to include info level entries
    level = logging.INFO
    if config.get_debug():
        level = logging.DEBUG
    logging.basicConfig(level=level)
    logging.info(">>>>>>>>>>>>>>>> Bluetti Monitor Starting <<<<<<<<<<<<<<<<")

    thread.daemon = True  # allow the program to quit

    from dbus.mainloop.glib import DBusGMainLoop

    # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
    DBusGMainLoop(set_as_default=True)

    pvac_output = BluettiMonitorService(
        servicename="com.victronenergy.battery.bluetti",
        deviceinstance=295,
        paths={
            "/Dc/0/Voltage": {"initial": 0},
            "/Dc/0/Current": {"initial": 0},
            "/Dc/0/Power": {"initial": 0},
            "/Soc": {"initial": 0},
            "/UpdateIndex": {"initial": 0},
            "/Capacity": {"initial": config.get_battery_capacity()},
            "/Settings/MonitorMode": {"initial": 0},

        },
        config=config,
    )

    logging.info(
        "Connected to dbus, and switching over to GLib.MainLoop() (= event based)"
    )
    mainloop = GLib.MainLoop()
    mainloop.run()


if __name__ == "__main__":
    main()
