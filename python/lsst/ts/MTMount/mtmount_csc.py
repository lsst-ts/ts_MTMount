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

__all__ = ["MTMountCsc"]

import asyncio
import pathlib

from lsst.ts import salobj
from . import command_futures
from . import commands
from . import constants
from . import enums
from . import replies
from . import communicator
from . import __version__

# Extra time to wait for commands to be done (sec)
TIMEOUT_BUFFER = 5

# Maximum time (second) between rotator application telemetry topics,
# beyond which rotator velocity will not be estimated.
MAX_ROTATOR_APPLICATION_GAP = 1.0

NOT_SUPPORTED_MESSAGE = (
    "Not supported in this camera-cable-wrap-only version of the CSC"
)


class MTMountCsc(salobj.ConfigurableCsc):
    """MTMount CSC

    Parameters
    ----------
    initial_state : `salobj.State` or `int`, optional
        The initial state of the CSC. This is provided for unit testing,
        as real CSCs should start up in `lsst.ts.salobj.StateSTANDBY`,
        the default.
    simulation_mode : `int`, optional
        Simulation mode.
    mock_command_port : `int`, optional
        Port for mock controller TCP/IP interface. If `None` then use the
        port specified by the configuration. Only used in simulation mode.
    run_mock_controller : `bool`, optional
        Run the mock controller? Ignored unless ``simulation_mode == 1``.
        This is used by unit tests which run the mock controller
        themselves in order to monitor the effect of commands.
        This is necessary because the mock controller provides
        very little feedback as to what it is doing.

    Raises
    ------
    salobj.ExpectedError
        If initial_state or simulation_mode is invalid.

    Notes
    -----
    **Simulation Modes**

    Supported simulation modes:

    * 0: regular operation
    * 1: simulation mode: start a mock TCP/IP controller and talk to it

    **Error Codes**

    See `CscErrorCode`
    """

    valid_simulation_modes = (0, 1)
    version = __version__

    def __init__(
        self,
        config_dir=None,
        initial_state=salobj.State.STANDBY,
        simulation_mode=0,
        mock_command_port=None,
        run_mock_controller=True,
    ):
        schema_path = (
            pathlib.Path(__file__).resolve().parents[4] / "schema" / "MTMount.yaml"
        )
        self.mock_command_port = (
            mock_command_port
            if mock_command_port is not None
            else constants.CSC_COMMAND_PORT
        )
        self.run_mock_controller = run_mock_controller
        self.communicator = None
        # Subprocess running the mock controller
        self.mock_controller_process = None
        # Dict of command sequence-id: (ack_task, done_task).
        # ack_task is set to the timeout (sec) when command is acknowledged.
        # done_task is set to to None when the command is done.
        # Both are set to exceptions if the command fails.
        self.command_dict = dict()

        self.command_lock = asyncio.Lock()

        # Task that waits while connecting to the TCP/IP controller.
        self.connect_task = salobj.make_done_future()

        # Task to track enabling and disabling
        self.enable_task = salobj.make_done_future()
        self.disable_task = salobj.make_done_future()
        self.enabled_state = enums.EnabledState.DISABLED

        # Task for self.camera_cable_wrap_loop
        self.camera_cable_wrap_task = salobj.make_done_future()

        # Task for self.read_loop
        self.read_loop_task = salobj.make_done_future()

        # Most recent Rotator Application telemetry sample,
        # or None if camera cable wrap not tracking.
        self.prev_rot_application = None

        # CCW - Rotator synchronization limits.
        # The goto limit is the distance between the CCW and the Rotator demand
        # position after which the CCW will blindly go to the demand, as long
        # as the distance between the ccw and rot are less then half the max
        # limit.
        # The max limit is the maximum distance allowed between CCW and
        # Rotator.
        # The slew limit is the distance between CCW - Rotator where CCW will
        # enter "slew" mode, and start following the position of the Rotator.
        # The track limit is the distance between CCW - Rotator at which they
        # are considered in synchronization and CCW will follow the Rotator
        # demand.
        # TODO: Make these configuration parameters (DM-25941).
        self.ccw_rot_sync_limit_goto = 7.5
        self.ccw_rot_sync_limit_max = 2.0
        self.ccw_rot_sync_limit_slew = 0.25
        self.ccw_rot_sync_limit_track = 0.125

        # Is CCW in catchup mode? This is True if CCW is enabled and the
        # distance between CCW and Rotator goes beyond ccw_rot_sync_limit_slew.
        # It will remain True until the distance is smaller then
        # ccw_rot_sync_limit_track.
        self.catch_up_mode = False

        # Should the CSC be connected?
        # Used to decide whether disconnecting sends the CSC to a Fault state.
        # Set True when fully connected and False just before
        # intentionally disconnecting.
        self.should_be_connected = False

        super().__init__(
            name="NewMTMount",
            index=0,
            schema_path=schema_path,
            config_dir=config_dir,
            initial_state=initial_state,
            simulation_mode=simulation_mode,
        )

        self.rotator = salobj.Remote(
            domain=self.domain, name="Rotator", include=["Application"]
        )

        self.mtmount = salobj.Remote(
            domain=self.domain, name="MTMount", include=["Camera_Cable_Wrap"]
        )

    @property
    def connected(self):
        if self.communicator is None:
            return False
        return self.communicator.connected

    @staticmethod
    def get_config_pkg():
        return "ts_config_mttcs"

    async def close_tasks(self):
        """Shut down pending tasks. Called by `close`."""
        await super().close_tasks()
        if self.mock_controller_process is not None:
            self.mock_controller_process.terminate()
        await self.close_communication()

    async def get_ccw_demand(self):
        """Get CCW tracking command data.

        The method will get the position of the CCW and of the Rotator and
        compute an optimum demand for the CCW. It takes into account how far
        CCW and Rotator are from each other and also how far they both are
        from the demand position.

        Returns
        -------
        desired_position : `float`
            CCW tracking command position (in degrees).
        desired_velocity : `float`
            CCW tracking command velocity (in degrees).
        desired_tai : `float`
            CCW tracking command time (TAI unix seconds).
            This will be config.camera_cable_wrap_advance_time
            seconds in the future.
        """

        rot_data = await self.rotator.tel_Application.next(flush=True)
        ccw_data = await self.mtmount.tel_Camera_Cable_Wrap.aget()

        if self.prev_rot_application is not None:
            dt = rot_data.private_sndStamp - self.prev_rot_application.private_sndStamp
            # Estimate velocity if GAP between last rotator data and current
            # data is smaller then MAX_ROTATOR_APPLICATION_GAP, else set
            # velocity to zero.
            rotator_velocity = (
                (rot_data.Position - self.prev_rot_application.Position) / dt
                if dt < MAX_ROTATOR_APPLICATION_GAP
                else 0.0
            )
        else:
            rotator_velocity = 0.0

        self.prev_rot_application = rot_data

        ccw_angle = ccw_data.CCW_Camera_Position

        # distance between ccw and rotator position
        distance_ccw_rot = ccw_angle - rot_data.Position

        # distance between ccw and rotator demand
        distance_ccw_rot_demand = ccw_angle - rot_data.Demand

        # distance between rotator position and demand
        distance_rot_demand = rot_data.Position - rot_data.Demand

        if (
            not self.catch_up_mode
            and abs(distance_ccw_rot) < self.ccw_rot_sync_limit_slew
        ) or (
            abs(distance_ccw_rot_demand) < self.ccw_rot_sync_limit_goto
            and abs(distance_ccw_rot) < self.ccw_rot_sync_limit_max / 2.0
        ):
            # CCW and Rotator synchronized or in the goto limit and CCW-Rotator
            # Close enough. Follow demand.
            self.catch_up_mode = False
            demand_position = rot_data.Demand
            demand_velocity = 0.0
        else:
            if not self.catch_up_mode:
                self.catch_up_mode = True
                self.log.info("Rotator and CCW out of sync. Going into catchup mode.")
            else:
                # Switch off catch_up_mode only when ccw-rot in the "track"
                # limit.
                self.catch_up_mode = (
                    abs(distance_ccw_rot) > self.ccw_rot_sync_limit_track
                )

            # If CCW ahead of Rotator, set velocity to zero, otherwise, use
            # Rotator velocity.
            demand_velocity = (
                rotator_velocity
                if abs(distance_ccw_rot_demand) > abs(distance_rot_demand)
                else 0.0
            )
            demand_position = rot_data.Position

        # Adjust demand position for desired time.
        # Demand position and velocity were based on the most recent
        # rotator telemetry data sample.
        demand_tai = salobj.current_tai() + self.config.camera_cable_wrap_advance_time
        delta_t = demand_tai - rot_data.private_sndStamp
        adjusted_demand_position = demand_position + demand_velocity * delta_t

        return (adjusted_demand_position, demand_velocity, demand_tai)

    async def close_communication(self):
        """Close and delete the communicator, if present.
        """
        self.should_be_connected = False
        if self.communicator is not None:
            await self.communicator.close()
            self.communicator = None

    async def connect(self):
        """Connect to the low-level controller.

        Start the mock controller, if simulating.
        """
        self.log.debug("Connect to the low-level controller")
        if self.config is None:
            raise RuntimeError("Not yet configured")
        if self.connected:
            raise RuntimeError("Already connected")
        if self.simulation_mode:
            client_host = salobj.LOCAL_HOST
            server_host = salobj.LOCAL_HOST
            command_port = self.mock_command_port
        else:
            client_host = self.config.host
            server_host = None
            command_port = constants.CSC_COMMAND_PORT
        if self.communicator is None:
            self.communicator = communicator.Communicator(
                name="communicator",
                client_host=client_host,
                client_port=command_port,
                server_host=server_host,
                # Tekniker uses repy port = command port + 1
                server_port=command_port + 1,
                log=self.log,
                read_replies=True,
                connect=False,
                connect_callback=self.connect_callback,
            )
        try:
            self.log.info("Connecting to the low-level controller")
            await asyncio.wait_for(
                self.communicator.connect(), timeout=self.config.connection_timeout
            )
            self.should_be_connected = True
            self.read_loop_task = asyncio.create_task(self.read_loop())
            self.log.debug("Connected to the low-level controller")
        except Exception as e:
            err_msg = "Could not connect to the low-level controller "
            f"at client_host={client_host}, command_port={command_port}"
            self.log.exception(err_msg)
            self.fault(
                code=enums.CscErrorCode.COULD_NOT_CONNECT, report=f"{err_msg}: {e}"
            )
            return

    def connect_callback(self, communicator):
        self.evt_connected.set_put(
            command=communicator.client_connected, replies=communicator.server_connected
        )
        if self.should_be_connected and not communicator.connected:
            self.should_be_connected = False
            self.fault(
                code=enums.CscErrorCode.CONNECTION_LOST,
                report="Lost connection to low-level controller",
            )

    async def enable_devices(self):
        self.log.info("Enable devices")
        self.disable_task.cancel()
        self.enabled_state = enums.EnabledState.ENABLING
        try:
            enable_commands = [
                commands.AskForCommand(commander=3),
                # commands.TopEndChillerResetAlarm(),
                # commands.MainPowerSupplyResetAlarm(),
                # commands.MirrorCoverLocksResetAlarm(),
                # commands.MirrorCoversResetAlarm(),
                # commands.AzimuthAxisResetAlarm(),
                # commands.ElevationAxisResetAlarm(),
                # commands.CameraCableWrapResetAlarm(),
                # commands.TopEndChillerPower(on=True),
                # commands.TopEndChillerTrackAmbient(on=True, temperature=0),
                # commands.MainPowerSupplyPower(on=True),
                # commands.OilSupplySystemPower(on=True),
                # commands.AzimuthAxisPower(on=True),
                # commands.ElevationAxisPower(on=True),
                # commands.CameraCableWrapPower(on=True),
                # commands.CameraCableWrapEnableTracking(on=True),
            ]
            await self.send_commands(*enable_commands)
            self.enabled_state = enums.EnabledState.ENABLED
        except Exception as e:
            self.enabled_state = enums.EnabledState.ENABLE_FAILED
            err_msg = "Failed to enable one or more devices"
            self.log.exception(err_msg)
            self.fault(
                code=enums.CscErrorCode.ACTUATOR_ENABLE_ERROR, report=f"{err_msg}: {e}",
            )
        # if self.camera_cable_wrap_task.done():
        #     self.camera_cable_wrap_task = asyncio.create_task(
        #         self.camera_cable_wrap_loop()
        #     )

    async def disable_devices(self):
        self.log.info("Disable devices")
        self.enable_task.cancel()
        if self.enabled_state in (
            enums.EnabledState.DISABLING,
            enums.EnabledState.DISABLED,
            enums.EnabledState.DISABLE_FAILED,
        ):
            return
        if not self.connected:
            self.enabled_state = enums.EnabledState.DISABLED
        else:
            self.enabled_state = enums.EnabledState.DISABLING
            try:
                disable_commands = [
                    # commands.BothAxesStop(),
                    # commands.CameraCableWrapStop(),
                    # commands.AzimuthAxisPower(on=False),
                    # commands.ElevationAxisPower(on=False),
                    # commands.CameraCableWrapPower(on=False),
                    commands.AskForCommand(commander=2),
                ]
                await self.send_commands(*disable_commands)
                self.enabled_state = enums.EnabledState.DISABLED
            except Exception as e:
                self.enabled_state = enums.EnabledState.DISABLE_FAILED
                err_msg = "Failed to disable one or more devices"
                self.log.exception(err_msg)
                self.fault(
                    code=enums.CscErrorCode.ACTUATOR_DISABLE_ERROR,
                    report=f"{err_msg}: {e}",
                )

    async def handle_summary_state(self):
        if self.disabled_or_enabled:
            if not self.connected:
                self.connect_task.cancel()
                self.connect_task = asyncio.create_task(self.connect())
                await self.connect_task

            if self.enabled_state is not enums.EnabledState.ENABLED:
                self.enable_task.cancel()
                self.enable_task = asyncio.create_task(self.enable_devices())
                await self.enable_task
        else:
            self.evt_axesInPosition.set_put(azimuth=False, elevation=False)
            if self.enabled_state is not enums.EnabledState.DISABLED:
                self.disable_task.cancel()
                self.disable_task = asyncio.create_task(self.disable_devices())
                await self.disable_task
            await self.close_communication()

    async def send_command(self, command, do_lock=True):
        """Send a command to the operation manager
        and add it to command_dict.

        Parameters
        ----------
        command : `Command`
            Command to send.
        do_lock : `bool`, optional
            Lock the port while using it?
            Specify False for emergency commands
            or if being called by send_commands.

        Returns
        -------
        command_futures : `command_futures.CommandFutures`
            Futures that monitor the command.
        """
        try:
            if do_lock:
                async with self.command_lock:
                    return await self._basic_send_command(command=command)
            else:
                return await self._basic_send_command(command=command)
        except ConnectionResetError:
            raise
        except Exception:
            self.log.exception(f"Failed to send command {command}")
            raise

    async def _basic_send_command(self, command):
        """Implementation of send_command. Ignores the command lock.
        """
        if not self.connected:
            raise salobj.ExpectedError("Not connected to the low-level controller.")
        if command.sequence_id in self.command_dict:
            raise RuntimeError(
                f"Bug! Duplicate sequence_id {command.sequence_id} in command_dict"
            )
        futures = command_futures.CommandFutures()
        self.command_dict[command.sequence_id] = futures
        await self.communicator.write(command)
        await asyncio.wait_for(futures.ack, self.config.ack_timeout)
        if command.command_code in commands.AckOnlyCommandCodes:
            # This command only receives an Ack; mark it done.
            futures.done.set_result(None)
        else:
            try:
                await asyncio.wait_for(
                    futures.done, timeout=futures.timeout + TIMEOUT_BUFFER
                )
            except asyncio.TimeoutError:
                raise asyncio.TimeoutError(
                    f"Timed out after {futures.timeout + TIMEOUT_BUFFER} seconds "
                    f"waiting for the Done reply to {command}"
                )
        return futures

    async def send_commands(self, *commands, do_lock=True):
        """Run a set of operation manager commands.

        Parameters
        ----------
        commands : `List` [``Command``]
            Commands to send. The sequence_id attribute is set.
        do_lock : `bool`, optional
            Lock the port while using it?
            Specify False for emergency commands.

        Returns
        -------
        futures_list : `List` [`CommandFutures`]
            Command future for each command.
        """
        futures_list = []
        try:
            if do_lock:
                async with self.command_lock:
                    for command in commands:
                        futures_list.append(
                            await self.send_command(command, do_lock=False)
                        )
            else:
                for command in commands:
                    futures_list.append(await self.send_command(command, do_lock=False))
            return futures_list
        except ConnectionResetError:
            for future in futures_list:
                future.setnoack("Connection lost")
            raise
        except Exception as e:
            self.log.exception("send_commands failed")
            for future in futures_list:
                future.setnoack(f"send_commands failed: {e}")
            raise

    async def camera_cable_wrap_loop(self):
        self.log.info("Camera cable wrap control begins")
        try:
            while True:
                (
                    demand_position,
                    demand_velocity,
                    demand_tai,
                ) = await self.get_ccw_demand()

                # Move at maximum velocity, acceleration and jerk
                command = commands.CameraCableWrapMove(
                    position=demand_position, velocity=3.5, acceleration=1.0, jerk=7.0,
                )

                # This will block until complete
                await self.send_command(command)

        except asyncio.CancelledError:
            self.log.info("Camera cable wrap control ends")
        except Exception:
            self.log.exception("Camera cable wrap control failed")
        finally:
            self.last_rotator_position = None
            self.last_rotator_time = None

    async def configure(self, config):
        self.config = config

    async def read_loop(self):
        """Read and process replies from the low-level controller.
        """
        self.log.debug("Read loop begins")
        while self.should_be_connected and self.connected:
            try:
                reply = await self.communicator.read()
                if isinstance(reply, replies.AckReply):
                    # Command acknowledged. Set timeout but leave
                    # futures in command_dict.
                    futures = self.command_dict.get(reply.sequence_id, None)
                    if futures is None:
                        self.log.warning(
                            f"Got Ack for non-existent command {reply.sequence_id}"
                        )
                        continue
                    futures.setack(reply.timeout_ms / 100.0)
                elif isinstance(reply, replies.NoAckReply):
                    # Command failed. Pop the command_dict entry
                    # and report failure.
                    futures = self.command_dict.pop(reply.sequence_id, None)
                    if futures is None:
                        self.log.warning(
                            f"Got NoAck for non-existent command {reply.sequence_id}"
                        )
                        continue
                    futures.setnoack(reply.explanation)
                elif isinstance(reply, replies.DoneReply):
                    futures = self.command_dict.pop(reply.sequence_id, None)
                    if futures is None:
                        self.log.warning(
                            f"Got Done for non-existent command {reply.sequence_id}"
                        )
                        continue
                    futures.setdone()
                elif isinstance(reply, replies.WarningReply):
                    self.evt_warning.set_put(
                        code=reply.code,
                        active=reply.active,
                        text="\n".join(reply.extra_data),
                        force_output=True,
                    )
                elif isinstance(reply, replies.ErrorReply):
                    self.evt_error.set_put(
                        code=reply.code,
                        latched=reply.on,
                        active=reply.active,
                        text="\n".join(reply.extra_data),
                        force_output=True,
                    )
                elif isinstance(reply, replies.OnStateInfoReply):
                    self.log.debug(f"Ignoring OnStateInfo reply: {reply}")
                elif isinstance(reply, replies.InPositionReply):
                    if reply.what == 0:
                        self.evt_axesInPosition.set_put(azimuth=reply.in_position)
                    elif reply.what == 1:
                        self.evt_axesInPosition.set_put(elevation=reply.in_position)
                    else:
                        self.log.warning(
                            f"Unrecognized what={reply.what} in InPositionReply"
                        )
                else:
                    self.log.warning(f"Ignoring unrecognized reply: {reply}")
            except asyncio.CancelledError:
                return
            except Exception as e:
                if self.should_be_connected:
                    if self.connected:
                        err_msg = "Read loop failed; possibly a bug"
                        self.log.exception(err_msg)
                        self.fault(
                            code=enums.CscErrorCode.INTERNAL_ERROR,
                            report=f"{err_msg}: {e}",
                        )
                    else:
                        self.fault(
                            code=enums.CscErrorCode.CONNECTION_LOST,
                            report="Connection lost to low-level controller (noticed in read_loop)",
                        )
        self.log.debug("Read loop ends")

    async def start(self):
        await super().start()

        if self.simulation_mode == 1 and self.run_mock_controller:
            self.log.debug("Starting the mock controller")
            try:
                self.mock_controller_process = await asyncio.create_subprocess_exec(
                    "run_mock_tma.py",
                    f"--command-port={self.mock_command_port}",
                    "--noreconnect",
                )
            except Exception:
                self.log.exception("Could not start the mock controller")

        self.log.debug("Waiting for the Rotator remote to start")
        await self.rotator.start_task
        self.log.debug("Started")

    async def do_clearError(self, data):
        self.assert_enabled()
        raise salobj.ExpectedError("Not yet implemented")

    async def do_closeMirrorCovers(self, data):
        self.assert_enabled()
        raise salobj.ExpectedError(NOT_SUPPORTED_MESSAGE)
        # Deploy the mirror cover locks/guides.
        await self.send_commands(
            commands.MirrorCoverLocksPower(on=True),
            commands.MirrorCoverLocksMoveAll(deploy=True),
            commands.MirrorCoverLocksPower(on=False),
        )
        # Deploy the mirror covers.
        await self.send_commands(
            commands.MirrorCoversPower(on=True),
            commands.MirrorCoversDeploy(),
            commands.MirrorCoversPower(on=False),
        )

    async def do_openMirrorCovers(self, data):
        self.assert_enabled()
        raise salobj.ExpectedError(NOT_SUPPORTED_MESSAGE)
        # Retract the mirror covers.
        await self.send_commands(
            commands.MirrorCoversPower(on=True),
            commands.MirrorCoversRetract(),
            commands.MirrorCoversPower(on=False),
        )
        # Retract the mirror cover locks/guides.
        await self.send_commands(
            commands.MirrorCoverLocksPower(on=True),
            commands.MirrorCoverLocksMoveAll(deploy=False),
            commands.MirrorCoverLocksPower(on=False),
        )

    async def do_disableCameraCableWrapTracking(self, data):
        self.assert_enabled()
        self.camera_cable_wrap_task.cancel()
        # await self.send_command(commands.CameraCableWrapEnableTracking(on=False))

    async def do_enableCameraCableWrapTracking(self, data):
        self.assert_enabled()
        # await self.send_command(commands.CameraCableWrapEnableTracking(on=True))
        if self.camera_cable_wrap_task.done():
            self.camera_cable_wrap_task = asyncio.create_task(
                self.camera_cable_wrap_loop()
            )

    async def do_moveToTarget(self, data):
        self.assert_enabled()
        raise salobj.ExpectedError(NOT_SUPPORTED_MESSAGE)
        await self.send_command(
            commands.BothAxesMove(azimuth=data.azimuth, elevation=data.elevation,),
        )

    async def do_trackTarget(self, data):
        self.assert_enabled()
        raise salobj.ExpectedError(NOT_SUPPORTED_MESSAGE)
        await self.send_command(
            commands.BothAxesTrack(
                azimuth=data.azimuth,
                azimuth_velocity=data.azimuthVelocity,
                elevation=data.elevation,
                elevation_velocity=data.elevationVelocity,
                tai=data.taiTime,
            ),
        )
        self.evt_target.set_put(
            azimuth=data.azimuth,
            elevation=data.elevation,
            azimuthVelocity=data.azimuthVelocity,
            elevationVelocity=data.elevationVelocity,
            taiTime=data.taiTime,
            trackId=data.trackId,
            tracksys=data.tracksys,
            radesys=data.radesys,
            force_output=True,
        )

    async def do_startTracking(self, data):
        self.assert_enabled()
        raise salobj.ExpectedError(NOT_SUPPORTED_MESSAGE)
        # TODO DM-24783 remove this if block once Tekniker's TMA code
        # supports the xAxisEnableTracking commands.
        if self.simulation_mode == 0:
            self.log.info(
                "Ignoring the startTracking command "
                "because Tekniker's code does not yet support it"
            )
            return
        await self.send_commands(
            commands.ElevationAxisEnableTracking(on=True),
            commands.AzimuthAxisEnableTracking(on=True),
        )

    async def do_stop(self, data):
        self.assert_enabled()
        await self.send_commands(
            commands.BothAxesStop(), commands.CameraCableWrapStop(), do_lock=False,
        )

    async def do_stopTracking(self, data):
        self.assert_enabled()
        raise salobj.ExpectedError(NOT_SUPPORTED_MESSAGE)
        # TODO DM-24783 remove this if block once Tekniker's TMA code
        # supports the xAxisEnableTracking commands.
        if self.simulation_mode == 0:
            self.log.info(
                "Issuing BothAxesStop instead of disabling tracking "
                "because Tekniker's code does not yet support the latter"
            )
            await self.send_command(commands.BothAxesStop(),)
        else:
            await self.send_commands(
                commands.ElevationAxisEnableTracking(on=False),
                commands.AzimuthAxisEnableTracking(on=False),
            )
