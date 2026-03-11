from enum import Enum

from vedbus import VeDbusItemExport
import dbus


class VregLinkItem(VeDbusItemExport):
    def __init__(self, *args, getvreg=None, setvreg=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.getvreg = getvreg
        self.setvreg = setvreg

    @dbus.service.method('com.victronenergy.VregLink',
                         in_signature='q', out_signature='qay')
    def GetVreg(self, regid):
        return self.getvreg(int(regid))

    @dbus.service.method('com.victronenergy.VregLink',
                         in_signature='qay', out_signature='qay')
    def SetVreg(self, regid, data):
        return self.setvreg(int(regid), bytes(data))


class GenericReg(Enum):
    OK = 0x0000

class BluettiReg(Enum):
    DC_MONITOR_MODE = 0xEEB8
    VE_REG_BATTERY_CAPACITY = 0x1000
    VE_REG_CHARGED_VOLTAGE = 0x1001
    VE_REG_PEUKERT_COEFFICIENT = 0x1005