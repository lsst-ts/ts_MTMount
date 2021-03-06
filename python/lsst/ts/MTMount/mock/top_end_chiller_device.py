# This file is part of ts_MTMount.
#
# Developed for Vera Rubin Observatory.
# This product includes software developed by the LSST Project
# (https://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

__all__ = ["TopEndChillerDevice"]

from .. import enums
from .base_device import BaseDevice


class TopEndChillerDevice(BaseDevice):
    """Top end chiller.

    Parameters
    ----------
    controller : `MockController`
        Mock controller.
    """

    def __init__(self, controller):
        # I am guessing that the top end chiller will track ambient
        # when turned on, but I don't know.
        self.track_ambient = True
        self.temperature = 0
        super().__init__(
            controller=controller, device_id=enums.DeviceId.TOP_END_CHILLER
        )

    def do_track_ambient(self, command):
        if not self.power_on:
            raise RuntimeError("Device not powered on.")
        self.track_ambient = command.on
        self.temperature = command.temperature
