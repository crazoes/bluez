#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later

import dbus
import dbus.exceptions
import dbus.mainloop.glib
import dbus.service
import urllib.request

import array
from gi.repository import GLib
import sys
import subprocess
from random import randint

mainloop = None

BLUEZ_SERVICE_NAME = 'org.bluez'
GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
DBUS_OM_IFACE = 'org.freedesktop.DBus.ObjectManager'
DBUS_PROP_IFACE = 'org.freedesktop.DBus.Properties'

GATT_SERVICE_IFACE = 'org.bluez.GattService1'
GATT_CHRC_IFACE = 'org.bluez.GattCharacteristic1'
GATT_DESC_IFACE = 'org.bluez.GattDescriptor1'

class Application(dbus.service.Object):
    """
    GATT Application to register services and characteristics.
    """
    def __init__(self, bus):
        self.path = '/'
        self.services = []
        dbus.service.Object.__init__(self, bus, self.path)
        self.add_service(CustomService(bus, 0))

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_service(self, service):
        self.services.append(service)

    @dbus.service.method(DBUS_OM_IFACE, out_signature='a{oa{sa{sv}}}')
    def GetManagedObjects(self):
        response = {}
        print('GetManagedObjects')
        for service in self.services:
            response[service.get_path()] = service.get_properties()
            chrcs = service.get_characteristics()
            for chrc in chrcs:
                response[chrc.get_path()] = chrc.get_properties()
        return response

class Service(dbus.service.Object):
    """
    Generic GATT Service.
    """
    PATH_BASE = '/org/bluez/example/service'

    def __init__(self, bus, index, uuid, primary):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_SERVICE_IFACE: {
                'UUID': self.uuid,
                'Primary': self.primary,
                'Characteristics': dbus.Array(
                    self.get_characteristic_paths(),
                    signature='o'
                )
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_characteristic(self, characteristic):
        self.characteristics.append(characteristic)

    def get_characteristic_paths(self):
        return [chrc.get_path() for chrc in self.characteristics]

    def get_characteristics(self):
        return self.characteristics

class CustomService(Service):
    """
    Custom Service with GET and SET characteristics.
    """
    SERVICE_UUID = '12345678-1234-5678-1234-56789abcdef0'

    def __init__(self, bus, index):
        Service.__init__(self, bus, index, self.SERVICE_UUID, True)
        self.add_characteristic(GetSettingsCharacteristic(bus, 0, self))
        self.add_characteristic(SetSettingsCharacteristic(bus, 1, self))

class Characteristic(dbus.service.Object):
    """
    Generic GATT Characteristic.
    """
    def __init__(self, bus, index, uuid, flags, service):
        self.path = service.path + '/char' + str(index)
        self.bus = bus
        self.uuid = uuid
        self.service = service
        self.flags = flags
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_CHRC_IFACE: {
                'Service': self.service.get_path(),
                'UUID': self.uuid,
                'Flags': self.flags
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

class GetSettingsCharacteristic(Characteristic):
    CHAR_UUID = '12345678-1234-5678-1234-56789abcdef1'

    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, self.CHAR_UUID, ['read'], service)

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='', out_signature='ay')
    def ReadValue(self, options):
        url = "http://vcs1435.vcsrelay.com:81/cgi-bin/GetDeviceSettings"

        try:
            # Fetch data from the URL
            with urllib.request.urlopen(url) as response:
                data = response.read().decode("utf-8")

            print(f"Fetched Data: {data}")

            # Convert string to byte array (UTF-8 encoded)
            return list(data.encode('utf-8'))  # Returning as plain text

        except Exception as e:
            print(f"Error fetching data: {e}")
            return []

class SetSettingsCharacteristic(Characteristic):
    """
    Characteristic for SET settings (write operation).
    """
    CHAR_UUID = '12345678-1234-5678-1234-56789abcdef2'

    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, self.CHAR_UUID, ['write'], service)

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='aya{sv}')
    def WriteValue(self, value, options):
        # Convert received bytes to a hex string
        received_data = ' '.join(f"{byte:02X}" for byte in value)  # Converts 0x02 0x03 to "02 03"

        print(f"Received write request: {received_data}")

        cgi_script = "/home/shreeya/upwork/bluez/test/SetDeviceSettings"

        try:
            process = subprocess.run(
                ["bash", cgi_script], input=received_data, capture_output=True, text=True
            )
            print(f"CGI Output: {process.stdout}")
            if process.stderr:
                print(f"CGI Error: {process.stderr}")
        except Exception as e:
            print(f"Failed to execute CGI script: {e}")

def register_app_cb():
    print('GATT application registered')

def register_app_error_cb(error):
    print('Failed to register application:', error)
    mainloop.quit()

def find_adapter(bus):
    remote_om = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, '/'), DBUS_OM_IFACE)
    objects = remote_om.GetManagedObjects()
    for o, props in objects.items():
        if GATT_MANAGER_IFACE in props.keys():
            return o
    return None

def main():
    global mainloop
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    adapter = find_adapter(bus)
    if not adapter:
        print('GattManager1 interface not found')
        return
    service_manager = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, adapter), GATT_MANAGER_IFACE)
    app = Application(bus)
    mainloop = GLib.MainLoop()
    print('Registering GATT application...')
    service_manager.RegisterApplication(app.get_path(), {}, reply_handler=register_app_cb, error_handler=register_app_error_cb)
    mainloop.run()

if __name__ == '__main__':
    main()

