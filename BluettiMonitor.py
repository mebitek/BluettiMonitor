#!/usr/bin/env python
"""
Created by mebitek in 2026.
Modified with threading support + Debug on DeviceName.
"""
import os
import sys
import json
import logging
import dbus
import requests
import threading
import time
import subprocess
from datetime import datetime, timedelta
import utils

sys.path.insert(1, "/data/SetupHelper/velib_python")
from vedbus import VeDbusService, VeDbusItemImport
from gi.repository import GLib
from vreg_link_item import VregLinkItem, GenericReg, BluettiReg
from settingsdevice import SettingsDevice
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
        connection="Bluetooth",
        config=None,
    ):
        self.config = config or BluettiConfig()
        self.bluetti = Bluetti(config.get_device_mac(), config.get_device_type(), 0, 12.8, 0, 0, 0)
        
        self._data_lock = threading.Lock()
        self._stop_thread = False

        logging.debug("* * * MAC %s", self.bluetti.mac)
        logging.debug("* * * TYPE %s", self.bluetti.type)
        
        self._dbusservice = VeDbusService(servicename, register=False)
        self._paths = paths
        
        vregtype = lambda *args, **kwargs: VregLinkItem(*args, **kwargs, getvreg=self.vreg_link_get, setvreg=self.vreg_link_set)
        
        logging.debug("%s /DeviceInstance = %d" % (servicename, deviceinstance))
        productname = "Bluetti " + config.get_device_type()
        
        self._dbusservice.add_path("/Mgmt/ProcessName", __file__)
        self._dbusservice.add_path("/Mgmt/ProcessVersion", config.get_version())
        self._dbusservice.add_path("/Mgmt/Connection", connection)
        
        self._dbusservice.add_path("/DeviceInstance", deviceinstance)
        self._dbusservice.add_path("/ProductId", 0xA383)
        self._dbusservice.add_path("/ProductName", productname)
        self._dbusservice.add_path("/DeviceName", productname) # Questo campo lo useremo per il debug
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
        
        # Avvio thread
        self._thread = threading.Thread(target=self._background_reader, daemon=True)
        self._thread.start()

        GLib.timeout_add(1000, self._update)

    def _background_reader(self):
        while not self._stop_thread:
            try:
                cmd = ['bluetti-read', '-m', self.bluetti.mac, "-t", self.bluetti.type]
                # Eseguiamo il comando
                output = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=20)

                # DEBUG VISIVO: Scriviamo l'output grezzo sul DeviceName
                # Limitiamo la lunghezza per non rompere il DBus
                debug_output = output.stdout.strip()[:50] 
                if not debug_output:
                    debug_output = "ERR:EMPTY_OUTPUT"
                # Se stderr ha roba, mostriamo quella
                if output.stderr:
                    debug_output = "ERR:" + output.stderr.strip()[:40]

                # Aggiorniamo il DeviceName con l'output grezzo per farti vedere cosa arriva
                # Usa _data_lock per sicurezza anche se qui è solo scrittura
                with self._data_lock:
                    self._dbusservice["/DeviceName"] = debug_output
                
                lines = output.stdout.splitlines()
                
                in_power_dc = None
                in_power_ac = None 
                in_voltage_dc = None
                # Prendiamo standby dalla config
                power = self.config.get_standby_current()
                current_soc = None
                
                for line in lines:
                    try:
                        if "FieldName.BATTERY_SOC" in line:
                            val = line.split(":")[1].strip().replace("%", "")
                            current_soc = int(val)
                            # Aggiorniamo il nome con il SOC per conferma lettura OK
                            with self._data_lock:
                                self._dbusservice["/DeviceName"] = f"OK SOC:{current_soc}%"

                            # Logica modalità
                            if current_soc < 20:
                                subprocess.run(['bluetti-write', '-m', self.bluetti.mac, "-t", self.bluetti.type, '-v', '2', 'ctrl_charging_mode'], timeout=5)
                            elif current_soc > 80:
                                subprocess.run(['bluetti-write', '-m', self.bluetti.mac, "-t", self.bluetti.type, '-v', '1', 'ctrl_charging_mode'], timeout=5)
                            else:
                                subprocess.run(['bluetti-write', '-m', self.bluetti.mac, "-t", self.bluetti.type, '-v', '0', 'ctrl_charging_mode'], timeout=5)

                        elif "FieldName.DC_OUTPUT_POWER" in line:
                            val = line.split(":")[1].strip().replace("W", "")
                            pwr = int(val)
                            power = power + pwr
                        
                        elif "FieldName.AC_INPUT_POWER" in line:
                            val = line.split(":")[1].strip().replace("W", "")
                            in_power_ac = int(val)
                        
                        elif "FieldName.DC_INPUT_POWER" in line:
                            val = line.split(":")[1].strip().replace("W", "")
                            in_power_dc = int(val)
                        
                        elif "FieldName.DC_INPUT_VOLTAGE" in line: 
                            val = line.split(":")[1].strip().replace("V", "")
                            in_voltage_dc = float(val)
                    except (ValueError, IndexError):
                        pass

                # Calcolo Voltage
                calc_voltage = 12.8
                if current_soc is not None:
                    if current_soc == 100: calc_voltage = 13.6
                    elif current_soc == 99: calc_voltage = 13.4
                    elif current_soc > 90: calc_voltage = 13.3
                    elif current_soc > 70: calc_voltage = 13.2
                    elif current_soc > 40: calc_voltage = 13.1
                    elif current_soc > 30: calc_voltage = 13.0
                    elif current_soc > 20: calc_voltage = 12.9
                    elif current_soc > 17: calc_voltage = 12.8
                    elif current_soc > 14: calc_voltage = 12.5
                    elif current_soc > 9: calc_voltage = 12.0
                    else: calc_voltage = 10.0
                
                # Calcolo Potenza e Corrente
                total_power = power + (power/100)
                current = 0
                if calc_voltage > 0:
                    if total_power > 0:
                        current = -(total_power / calc_voltage)
                    
                    if in_power_dc and in_voltage_dc:
                        in_current = in_power_dc / in_voltage_dc
                        current += in_current
                        total_power -= in_power_dc
                    
                    if in_power_ac:
                        current += (in_power_ac / 14.6)
                        total_power -= in_power_ac
                
                capacityAh = self.config.get_battery_capacity() / calc_voltage
                consumed = capacityAh * (100 - (current_soc if current_soc else 0)) / 100
                time_to_go = self.remaining_time_seconds(capacityAh, current_soc if current_soc else 0, current)

                with self._data_lock:
                    if current_soc is not None:
                        self.bluetti.soc = current_soc
                    self.bluetti.voltage = calc_voltage
                    self.bluetti.power = total_power
                    self.bluetti.current = current
                    self.bluetti.capacity = capacityAh
                    self.bluetti.consumed = consumed
                    self.bluetti.time_to_go = time_to_go

            except subprocess.TimeoutExpired:
                with self._data_lock:
                    self._dbusservice["/DeviceName"] = "ERR:TIMEOUT"
            except FileNotFoundError:
                 with self._data_lock:
                    self._dbusservice["/DeviceName"] = "ERR:CMD_NOT_FOUND"
            except Exception:
                with self._data_lock:
                    self._dbusservice["/DeviceName"] = "ERR:EXCEPTION"
            
            # Sleep
            try:
                interval_minutes = self.config.get_interval()
                sleep_seconds = interval_minutes * 60
                if sleep_seconds < 30: sleep_seconds = 60
            except:
                sleep_seconds = 60
            
            time.sleep(sleep_seconds)

    def _update(self):
        try:
            with self._data_lock:
                soc = self.bluetti.soc
                voltage = self.bluetti.voltage
                current = self.bluetti.current
                power = self.bluetti.power
                capacity = getattr(self.bluetti, 'capacity', 0)
                consumed = getattr(self.bluetti, 'consumed', 0)
                time_to_go = getattr(self.bluetti, 'time_to_go', 0)

            self._dbusservice["/Soc"] = soc
            self._dbusservice["/Dc/0/Voltage"] = voltage  
            self._dbusservice["/Dc/0/Current"] = current
            self._dbusservice["/Dc/0/Power"] = power
            self._dbusservice["/Capacity"] = capacity
            self._dbusservice["/ConsumedAmphours"] = consumed
            self._dbusservice["/TimeToGo"] = time_to_go

        except Exception:
            pass

        index = self._dbusservice["/UpdateIndex"] + 1
        if index > 255:
            index = 0
        self._dbusservice["/UpdateIndex"] = index
        
        return True

    def _handlechangedvalue(self, path, value):
        return True

    def calculate_capacity(self, voltage):
        capacityWh = self.config.get_battery_capacity()
        return capacityWh / voltage

    def vreg_link_get(self, reg_id):
        with self._data_lock:
            voltage = self.bluetti.voltage
        
        if reg_id == BluettiReg.DC_MONITOR_MODE.value:
            return GenericReg.OK.value, [0xFE]
        elif reg_id == BluettiReg.VE_REG_BATTERY_CAPACITY.value:
            capacityAh = float(self.calculate_capacity(voltage)/100)
            return GenericReg.OK.value, utils.convert_decimal(capacityAh)
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
        elif reg_id == BluettiReg.VE_REG_CHARGED_CURRENT.value:
            return GenericReg.OK.value, utils.convert_decimal(0.02)
        elif reg_id == BluettiReg.VE_REG_TTG_DELTA_T.value:
            return GenericReg.OK.value, utils.convert_decimal(3)
        else:
            return GenericReg.OK.value, []

    @staticmethod
    def vreg_link_set(reg_id, data):
        return GenericReg.OK.value, data

    def remaining_time_seconds(self, capacity, soc, current_a):
        MIN_CURRENT = 0.1 
        if current_a >= -MIN_CURRENT:
            return 864000 
        remaining_ah = capacity * (soc / 100.0)
        hours = remaining_ah / abs(current_a)
        seconds = int(hours * 3600)
        return seconds

def main():
    config = BluettiConfig()
    level = logging.INFO
    if config.get_debug():
        level = logging.DEBUG
    logging.basicConfig(level=level)
    
    logging.info(">>>>>>>>>>>>>>>> Bluetti Monitor Starting <<<<<<<<<<<<<<<<")
    
    from dbus.mainloop.glib import DBusGMainLoop
    DBusGMainLoop(set_as_default=True)
    
    capacityAh = config.get_battery_capacity() / 12.8
    
    pvac_output = BluettiMonitorService(
        servicename="com.victronenergy.battery.bluetti",
        deviceinstance=295,
        paths={
            "/Dc/0/Voltage": {"initial": 0},
            "/Dc/0/Current": {"initial": 0},
            "/Dc/0/Power": {"initial": 0},
            "/Soc": {"initial": 0},
            "/UpdateIndex": {"initial": 0},
            "/Capacity": {"initial": capacityAh},
            "/TimeToGo": {"initial": 0},
            "/ConsumedAmphours": {"initial": 0},
            "/Settings/MonitorMode": {"initial": 0},
            "/Info/MaxChargeCurrent": {"initial": 20},
            "/Info/MaxDischargeCurrent": {"initial": 20},
        },
        config=config,
    )
    
    logging.info("Connected to dbus, and switching over to GLib.MainLoop()")
    mainloop = GLib.MainLoop()
    mainloop.run()

if __name__ == "__main__":
    main()