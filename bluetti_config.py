import configparser
import logging
import os
import shutil


class BluettiConfig:
    def __init__(self):
        self.config = configparser.ConfigParser()
        config_file = "%s/../conf/bluetti_config.ini" % (
            os.path.dirname(os.path.realpath(__file__))
        )
        if not os.path.exists(config_file):
            sample_config_file = "%s/config.sample.ini" % (
                os.path.dirname(os.path.realpath(__file__))
            )
            shutil.copy(sample_config_file, config_file)
        self.config.read(
            "%s/../conf/bluetti_config.ini"
            % (os.path.dirname(os.path.realpath(__file__)))
        )

    def get_device_mac(self):
        return self.config.get("Setup", "Mac", fallback="XX:XX:XX:XX:XX")

    def get_device_type(self):
        return self.config.get("Setup", "Type", fallback="EB3A")

    def get_serial(self):
        return self.config.get("Setup", "Serial", fallback="XXXXXXXX")

    def get_interval(self):
        interval = int(self.config.get("Setup", "Interval", fallback=10))
        if interval == 0:
            return 1
        else:
            return interval

    def get_standby_power(self):
        return float(self.config.get("Setup", "StandbyPower", fallback=3)) 

    def get_fix_quantize_power(self):
        return float(self.config.get("Setup", "FixQuantizePower", fallback=5)) 

    def get_battery_capacity(self):
        return float(self.config.get("Setup", "BatteryCapacity", fallback=268.8)) 

    def get_low_soc_alarm_set(self):
        return int(self.config.get("Setup", "LowSocAlarmSet", fallback=30)) 

    def get_low_soc_alarm_clear(self):
        return int(self.config.get("Setup", "LowSocAlarmClear", fallback=50)) 



    def get_debug(self):
        val = self.config.get("Setup", "debug", fallback=False)
        if val == "true":
            return True
        else:
            return False

    def write_to_config(self, value, path, key):
        logging.debug("Writing config file %s %s " % (path, key))
        self.config[path][key] = str(value)
        with open(
            "%s/../conf/bluetti_config.ini"
            % (os.path.dirname(os.path.realpath(__file__))),
            "w",
        ) as configfile:
            self.config.write(configfile)

    @staticmethod
    def get_version():
        with open(
            "%s/version" % (os.path.dirname(os.path.realpath(__file__))), "r"
        ) as file:
            return file.read()
