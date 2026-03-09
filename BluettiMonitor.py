#!/usr/bin/env python

"""
Created by mebitek in 2025.

Inspired by:
 - https://github.com/Waldmensch1/venus.dbus-tasmota-inverter (base code)
 - https://github.com/Marv2190/venus.dbus-MqttToGridMeter (Inspiration)
 - https://github.com/victronenergy/velib_python/blob/master/dbusdummyservice.py (Template)


This code and its documentation can be found on: https://github.com/mebitek/TasmotaInverter
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


# add the path to our own packages for import
sys.path.insert(1, "/data/SetupHelper/velib_python")

from vedbus import VeDbusService, VeDbusItemImport
from gi.repository import GLib

from bluetti_config import BluettiConfig
from vreg_link_item import VregLinkItem, InverterReg, GenericReg


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

    def get_mode_and_state(self):
        # /Mode  <- Switch position: 1=Charger only,2=Inverter only;3=On;4=Off;5=Low Power/Eco;
        #           251=Passthrough;252=Standby;253=Hibernate
        # /State <- 0=Off; 1=Low Power; 2=Fault; 9=Inverting

        if self.state == "Offline":
            return 4, 0
        if self.status == "ON":
            if self.power > 15:
                return 2, 9
            else:
                return 5, 1
        else:
            return 4, 0


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
        self.bluetti = Bluetti(config.get_device_mac(), config.get_device_type(), 0, 0, 0, 0, 0)

        # dbus service
        self._dbusservice = VeDbusService(servicename, register=False)
        self._paths = paths

        vregtype = lambda *args, **kwargs: VregLinkItem(
            *args, **kwargs, getvreg=self.vreglink_get, setvreg=self.vreglink_set
        )

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
        self._dbusservice.add_path("/ProductId", 41197)
        self._dbusservice.add_path("/ProductName", productname)
        self._dbusservice.add_path("/DeviceName", productname)
        self._dbusservice.add_path("/FirmwareVersion", 0x0137)
        self._dbusservice.add_path("/HardwareVersion", 8)
        self._dbusservice.add_path("/Connected", 1)
        self._dbusservice.add_path("/Serial", config.get_serial())

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

            logging.debug("* * * MAC %s", self.bluetti.mac)
            logging.debug("* * * TYPE %s", self.bluetti.type)

            if self.bluetti.last_update is None or datetime.now() > self.bluetti.last_update + timedelta(
                    minutes=self.config.get_interval()):

                output = subprocess.run(['bluetti-read', '-m', self.bluetti.mac, "-t", self.bluetti.type],
                                capture_output=True, text=True)


                lines = output.stdout.splitlines();                 
                for line in lines:
                    if "FieldName.BATTERY_SOC" in line:
                        soc = int(line.split(":")[1].strip().replace("%", ""))
                        logging.debug("* * * BATTERY SOC %s", soc)
                        self._dbusservice["/Soc"] = soc
                    if "FieldName.DC_OUTPUT_POWER" in line:
                        power = int(line.split(":")[1].strip().replace("W", ""))
                        logging.debug("* * * POWER %s", power)
                        self._dbusservice["/Dc/0/Power"] = power

                self.bluetti.last_update = datetime.now()
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
            "/Dc/0/Temperature": {"initial": 0},
            "/Soc": {"initial": 0},
             "/UpdateIndex": {"initial": 0},

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
