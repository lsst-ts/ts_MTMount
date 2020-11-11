# This file is part of ts_MTMount.
#
# Developed for the LSST Data Management System.
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

__all__ = ["AxisDevice"]

import asyncio

from lsst.ts import salobj
from lsst.ts import simactuators
from .. import enums
from .. import limits
from .base_device import BaseDevice


class AxisDevice(BaseDevice):
    """Mock axis controller device.

    Suports all commands except MOVE_VELOCITY.

    Parameters
    ----------
    controller : `MockController`
        Mock controller.
    device_id : `DeviceId`
        Device ID. Must be one of:

        * enums.DeviceId.AZIMUTH_AXIS
        * enums.DeviceId.ELEVATION_AXIS
        * enums.DeviceId.CAMERA_CABLE_WRAP

    Notes
    -----
    There is no mock azimuth cable wrap because in the real system
    the azimuth axis takes care of that cable wrap, so `MTMountCsc`
    has no need to send commands to it.

    Turning on the device also enables it.
    """

    def __init__(self, controller, device_id):
        device_id = enums.DeviceId(device_id)
        device_limits = limits.LimitsDict[device_id].scaled()
        self.enabled = False
        self.tracking_enabled = False
        # Has a target position been specified?
        # Set True when tracking or moving point to point and False otherwise.
        self.has_target = False
        self.async_move = device_id != enums.DeviceId.CAMERA_CABLE_WRAP
        self.actuator = simactuators.TrackingActuator(
            min_position=device_limits.min_position,
            max_position=device_limits.max_position,
            max_velocity=device_limits.max_velocity,
            max_acceleration=device_limits.max_acceleration,
            dtmax_track=0.2,
        )
        self._monitor_move_task = asyncio.Future()
        self._monitor_move_task.set_result(None)
        super().__init__(controller=controller, device_id=device_id)

    @property
    def end_tai(self):
        """Get the end time of the current path, as TAI unix seconds.
        """
        return self.actuator.path[-1].tai

    def assert_enabled(self):
        """Raise `RuntimeError` if device is not fully enabled.

        To be fully enabled, the device must be on, no alarm present,
        and the drive enabled.
        """
        self.assert_on()
        if not self.enabled:
            raise RuntimeError("Not enabled")

    def assert_tracking_enabled(self, enabled):
        """Raise `RuntimeError` if tracking is or is not enabled.
        """
        if enabled:
            if not self.tracking_enabled:
                raise RuntimeError("Tracking not enabled")
        else:
            if self.tracking_enabled:
                raise RuntimeError("Tracking not disabled")

    async def close(self):
        await super().close()
        self._monitor_move_task.cancel()

    def monitor_move_command(self, command):
        """Return a task that is set done when the move is done.

        Parameters
        ----------
        command : `Command`
            Move command.

        Returns
        -------
        task : `asyncio.Task`
            A task that is set done when the move is done.
        """
        self._monitor_move_task.cancel()
        self._monitor_move_task = asyncio.create_task(self._monitor_move(command))
        return self._monitor_move_task

    async def _monitor_move(self, command):
        """Do most of the work for monitor_move_command.
        """
        # Provide some slop for non-monotonic clocks, which are
        # sometimes seen when running Docker on macOS.
        duration = 0.2 + self.end_tai - salobj.current_tai()
        await asyncio.sleep(duration)

    def supersede_move_command(self):
        """Report the current move command (if any) as superseded.
        """
        self._monitor_move_task.cancel()

    def abort(self):
        self.actuator.abort()
        self.actuator.stop()
        self.has_target = False

    def do_drive_enable(self, command):
        """Enable or disable the drive.

        Abort motion and disable tracking.
        """
        self.supersede_move_command()
        self.abort()
        self.tracking_enabled = False
        self.enabled = command.on

    def do_drive_reset(self, command):
        """Reset the drive.

        The power must be on.

        Abort motion, disable tracking, disable the drive.
        """
        self.assert_on()
        self.supersede_move_command()
        self.abort()
        self.tracking_enabled = False
        self.enabled = False

    def do_enable_tracking(self, command):
        """Enable or disable tracking mode.

        The drive must be enabled.
        """
        self.assert_enabled()
        self.supersede_move_command()
        self.actuator.stop()
        self.has_target = False
        self.tracking_enabled = command.on

    def do_home(self, command):
        """Home the actuator.

        The drive must be enabled and tracking must be disabled.

        For sake of doing something vaguely plausible,
        move to the mid-point of the position limits.
        """
        self.assert_enabled()
        position = (self.actuator.min_position + self.actuator.max_position) / 2
        return self.move_point_to_point(position=position, command=command)

    def do_move(self, command):
        """Set target position.

        The drive must be enabled and tracking must be disabled.

        Velocity and acceleration limits are not applied,
        because it is tricky to make sure the values are
        correctly restored when the move finishes,
        and the CSC doesn't support these parameters anyway.
        """
        self.assert_enabled()
        self.has_target = True
        return self.move_point_to_point(position=command.position, command=command)

    def do_move_velocity(self, command):
        raise NotImplementedError("Not implemented")

    def do_power(self, command):
        if not command.on:
            self.supersede_move_command()
            self.tracking_enabled = False
            self.actuator.stop()
        super().do_power(command)
        self.enabled = command.on

    def do_stop(self, command):
        """Stop the actuator.
        """
        self.assert_enabled()
        self.supersede_move_command()
        self.tracking_enabled = False
        self.actuator.stop()
        # I am not sure if this should clear the target.
        # It depends what the real controller reports for the "in position"
        # event when an axis is stopped.
        self.has_target = False

    def do_track(self, command):
        """Specify a tracking target position, velocity, and time.

        The drive must be enabled and tracking must be enabled.
        """
        self.assert_enabled()
        self.assert_tracking_enabled(True)
        self.supersede_move_command()
        self.actuator.set_target(
            tai=command.tai, position=command.position, velocity=command.velocity
        )
        self.has_target = True

    def move_point_to_point(self, position, command):
        """Move to the specified position.

        The drive must be enabled and tracking must be disabled.

        Parameters
        ----------
        position : `float`
            Desired position, in degrees.
        command : `Command`
            Command to monitor and report done.

        Returns
        -------
        duration : `float`
           Minimum duration of move (sec)
        """
        self.assert_enabled()
        self.assert_tracking_enabled(False)

        if self.async_move:
            self.supersede_move_command()
        elif not self._monitor_move_task.done():
            raise RuntimeError("Device busy executing move.")

        tai = salobj.current_tai()
        self.actuator.set_target(tai=tai, position=position, velocity=0)
        self.has_target = True
        self.monitor_move_command(command)
        timeout = self.end_tai - tai
        return timeout, self._monitor_move_task
