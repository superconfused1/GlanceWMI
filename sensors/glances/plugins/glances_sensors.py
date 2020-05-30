# -*- coding: utf-8 -*-
#
# This file is part of Glances.
#
# Copyright (C) 2019 Nicolargo <nicolas@nicolargo.com>
#
# Glances is free software; you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Glances is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

"""Sensors plugin."""

import psutil
import warnings
import wmi

from glances.logger import logger
from glances.compat import iteritems, to_fahrenheit
from glances.timer import Counter
from glances.plugins.sensors.glances_batpercent import Plugin as BatPercentPlugin
from glances.plugins.sensors.glances_hddtemp import Plugin as HddTempPlugin
from glances.plugins.glances_plugin import GlancesPlugin

SENSOR_TEMP_UNIT = 'C'
SENSOR_FAN_UNIT = 'R'


class Plugin(GlancesPlugin):
    """Glances sensors plugin.

    The stats list includes both sensors and hard disks stats, if any.
    The sensors are already grouped by chip type and then sorted by name.
    The hard disks are already sorted by name.
    """

    def __init__(self, args=None, config=None):
        """Init the plugin."""
        super(Plugin, self).__init__(args=args,
                                     config=config,
                                     stats_init_value=[])

        start_duration = Counter()

        # Init the sensor class
        start_duration.reset()
        self.glancesgrabsensors = GlancesGrabSensors()
        logger.debug("Generic sensor plugin init duration: {} seconds".format(start_duration.get()))

        # Instance for the HDDTemp Plugin in order to display the hard disks
        # temperatures
        start_duration.reset()
        self.hddtemp_plugin = HddTempPlugin(args=args, config=config)
        logger.debug("HDDTemp sensor plugin init duration: {} seconds".format(start_duration.get()))

        # Instance for the BatPercent in order to display the batteries
        # capacities
        start_duration.reset()
        self.batpercent_plugin = BatPercentPlugin(args=args, config=config)
        logger.debug("Battery sensor plugin init duration: {} seconds".format(start_duration.get()))

        # We want to display the stat in the curse interface
        self.display_curse = True

    def get_key(self):
        """Return the key of the list."""
        return 'label'

    @GlancesPlugin._check_decorator
    @GlancesPlugin._log_result_decorator
    def update(self):
        """Update sensors stats using the input method."""
        # Init new stats
        stats = self.get_init_value()

        if self.input_method == 'local':
            # Update stats using the dedicated lib
            stats = []
            # Get the temperature
            try:
                temperature = self.__set_type(self.glancesgrabsensors.get('temperature_core'),
                                              'temperature_core')
            except Exception as e:
                logger.error("Cannot grab sensors temperatures (%s)" % e)
            else:
                # Append temperature
                stats.extend(temperature)
            # Get the FAN speed
            try:
                fan_speed = self.__set_type(self.glancesgrabsensors.get('fan_speed'),
                                            'fan_speed')
            except Exception as e:
                logger.error("Cannot grab FAN speed (%s)" % e)
            else:
                # Append FAN speed
                stats.extend(fan_speed)
            # Update HDDtemp stats
            try:
                hddtemp = self.__set_type(self.hddtemp_plugin.update(),
                                          'temperature_hdd')
            except Exception as e:
                logger.error("Cannot grab HDD temperature (%s)" % e)
            else:
                # Append HDD temperature
                stats.extend(hddtemp)
            # Update batteries stats
            try:
                batpercent = self.__set_type(self.batpercent_plugin.update(),
                                             'battery')
            except Exception as e:
                logger.error("Cannot grab battery percent (%s)" % e)
            else:
                # Append Batteries %
                stats.extend(batpercent)

        elif self.input_method == 'snmp':
            # Update stats using SNMP
            # No standard:
            # http://www.net-snmp.org/wiki/index.php/Net-SNMP_and_lm-sensors_on_Ubuntu_10.04

            pass

        # Set the alias for each stat
        for stat in stats:
            alias = self.has_alias(stat["label"].lower())
            if alias:
                stat["label"] = alias

        # Update the stats
        self.stats = stats

        return self.stats

    def __set_type(self, stats, sensor_type):
        """Set the plugin type.

        4 types of stats is possible in the sensors plugin:
        - Core temperature: 'temperature_core'
        - Fan speed: 'fan_speed'
        - HDD temperature: 'temperature_hdd'
        - Battery capacity: 'battery'
        """
        for i in stats:
            # Set the sensors type
            i.update({'type': sensor_type})
            # also add the key name
            i.update({'key': self.get_key()})

        return stats

    def update_views(self):
        """Update stats views."""
        # Call the father's method
        super(Plugin, self).update_views()

        # Add specifics informations
        # Alert
        for i in self.stats:
            if not i['value']:
                continue
            if i['type'] == 'battery':
                self.views[i[self.get_key()]]['value']['decoration'] = self.get_alert(100 - i['value'], header=i['type'])
            else:
                self.views[i[self.get_key()]]['value']['decoration'] = self.get_alert(i['value'], header=i['type'])

    def msg_curse(self, args=None, max_width=None):
        """Return the dict to display in the curse interface."""
        # Init the return message
        ret = []

        # Only process if stats exist and display plugin enable...
        if not self.stats or self.is_disable():
            return ret

        # Max size for the interface name
        name_max_width = max_width - 12

        # Header
        msg = '{:{width}}'.format('SENSORS', width=name_max_width)
        ret.append(self.curse_add_line(msg, "TITLE"))

        # Stats
        for i in self.stats:
            # Do not display anything if no battery are detected
            if i['type'] == 'battery' and i['value'] == []:
                continue
            # New line
            ret.append(self.curse_new_line())
            msg = '{:{width}}'.format(i["label"][:name_max_width],
                                      width=name_max_width)
            ret.append(self.curse_add_line(msg))
            if i['value'] in (b'ERR', b'SLP', b'UNK', b'NOS'):
                msg = '{:>13}'.format(i['value'])
                ret.append(self.curse_add_line(
                    msg, self.get_views(item=i[self.get_key()],
                                        key='value',
                                        option='decoration')))
            else:
                if (args.fahrenheit and i['type'] != 'battery' and
                        i['type'] != 'fan_speed'):
                    value = to_fahrenheit(i['value'])
                    unit = 'F'
                else:
                    value = i['value']
                    unit = i['unit']
                try:
                    msg = '{:>13.0f}{}'.format(value, unit)
                    ret.append(self.curse_add_line(
                        msg, self.get_views(item=i[self.get_key()],
                                            key='value',
                                            option='decoration')))
                except (TypeError, ValueError):
                    pass

        return ret


class GlancesGrabSensors(object):
    """Get sensors stats."""

    def __init__(self):
        """Init sensors stats."""
        # Temperatures
        self.init_temp = False
        self.stemps = {}
        try:
            # psutil>=5.1.0, Linux-only
            #self.stemps = psutil.sensors_temperatures()
            w = wmi.WMI(namespace="root\\OpenHardwareMonitor")
            self.stemps = w.Sensor()[1]
        except AttributeError:
            logger.debug("Cannot grab temperatures. Platform not supported.")
        else:
            self.init_temp = True
            # Solve an issue #1203 concerning a RunTimeError warning message displayed
            # in the curses interface.
            warnings.filterwarnings("ignore")

        # Fans
        self.init_fan = False
        self.sfans = {}
        try:
            # psutil>=5.2.0, Linux-only
            self.sfans = psutil.sensors_fans()
        except AttributeError:
            logger.debug("Cannot grab fans speed. Platform not supported.")
        else:
            self.init_fan = True

        # !!! Disable Fan: High CPU consumption with psutil 5.2.0 or higher
        # Delete the two followings lines when corrected (https://github.com/giampaolo/psutil/issues/1199)
        # Correct and tested with PsUtil 5.6.1 (Ubuntu 18.04)
        # self.init_fan = False
        # logger.debug("Fan speed sensors disable (see https://github.com/giampaolo/psutil/issues/1199)")

        # Init the stats
        self.reset()

    def reset(self):
        """Reset/init the stats."""
        self.sensors_list = []

    def __update__(self):
        """Update the stats."""
        # Reset the list
        self.reset()

        if not self.init_temp:
            return self.sensors_list

        # Temperatures sensors
        self.sensors_list.extend(self.build_sensors_list(SENSOR_TEMP_UNIT))

        # Fans sensors
        self.sensors_list.extend(self.build_sensors_list(SENSOR_FAN_UNIT))

        return self.sensors_list

    def build_sensors_list(self, type):
        """Build the sensors list depending of the type.

        type: SENSOR_TEMP_UNIT or SENSOR_FAN_UNIT

        output: a list
        """
        ret = []
        if type == SENSOR_TEMP_UNIT and self.init_temp:
            input_list = self.stemps
            self.stemps = psutil.sensors_temperatures()
        elif type == SENSOR_FAN_UNIT and self.init_fan:
            input_list = self.sfans
            self.sfans = psutil.sensors_fans()
        else:
            return ret
        for chipname, chip in iteritems(input_list):
            i = 1
            for feature in chip:
                sensors_current = {}
                # Sensor name
                if feature.label == '':
                    sensors_current['label'] = chipname + ' ' + str(i)
                else:
                    sensors_current['label'] = feature.label
                # Fan speed and unit
                sensors_current['value'] = int(feature.current)
                sensors_current['unit'] = type
                # Add sensor to the list
                ret.append(sensors_current)
                i += 1
        return ret

    def get(self, sensor_type='temperature_core'):
        """Get sensors list."""
        self.__update__()
        if sensor_type == 'temperature_core':
            ret = [s for s in self.sensors_list if s['unit'] == SENSOR_TEMP_UNIT]
        elif sensor_type == 'fan_speed':
            ret = [s for s in self.sensors_list if s['unit'] == SENSOR_FAN_UNIT]
        else:
            # Unknown type
            logger.debug("Unknown sensor type %s" % sensor_type)
            ret = []
        return ret
