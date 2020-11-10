#!/usr/bin/env python
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

"""A simple command-line script that sends commands to
the low-level controller (Operation Manager).

Must be connected to a low-level port on the Operation Manger.
At this time the only available port is for the hand-held device,
but Tekniker plans to make an additional port available for our CSC.

Warning: this should not be used while the CSC is running.

For more information:

tma_commander.py --help
"""

import argparse
import asyncio
import logging
import sys
import traceback

from lsst.ts import salobj
from lsst.ts import MTMount

logging.basicConfig()


async def stdin_generator():
    """Thanks to http://blog.mathieu-leplatre.info
    """
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(loop=loop)
    reader_protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: reader_protocol, sys.stdin)
    while True:
        line = await reader.readline()
        if not line:  # EOF.
            break
        yield line.decode("utf-8").strip()


def print_connected(descr, communicator):
    """Print state of a connection.

    Parameters
    ----------
    descr : `str`
        Brief description, such as "TMA commander".
    communicator : `Communicator`
        Communicator
    """

    def connected_str(connected):
        return "connected" if connected else "disconnected"

    print(
        f"{descr}: "
        f"client {connected_str(communicator.client_connected)}, "
        f"server {connected_str(communicator.server_connected)}"
    )


class Commander:
    """Command a Tekniker Operation Manager.

    Read commands from a user on the command line
    and send them to the low-level controller (Operation Manager).

    Warning: this is only intended as a short-term hack.
    It will be deleted once MTMountCsc has been shown to work
    with the Operation Manager.

    Parameters
    ----------
    host : `str`
        IP address of the operation manager.
    log_level : `int`
        Logging level.
    simulate : `bool`
        Run in simulation mode?
        If True then ``host`` is ignored.
    """

    def __init__(self, host, log_level, simulate):
        self.log = logging.getLogger()
        self.log.setLevel(log_level)

        self.done_task = asyncio.Future()
        self.read_loop_task = salobj.make_done_future()

        self.simulator = None
        if simulate:
            host = salobj.LOCAL_HOST
            self.simulator = MTMount.mock.Controller(
                command_port=MTMount.CSC_COMMAND_PORT, log=self.log
            )

        self.communicator = MTMount.Communicator(
            name="tma_commander",
            client_host=host,
            client_port=MTMount.CSC_COMMAND_PORT,
            server_host=None,
            # Tekniker uses repy port = command port + 1
            server_port=MTMount.CSC_COMMAND_PORT + 1,
            log=self.log,
            read_replies=True,
            connect=True,
            connect_callback=self.connect_callback,
        )
        self.command_loop_task = asyncio.create_task(self.command_loop())
        self.command_dict = dict(
            az_power=MTMount.commands.AzimuthAxisPower,
            az_reset_alarm=MTMount.commands.AzimuthAxisResetAlarm,
            safety_reset=MTMount.commands.SafetyReset,
            ask_for_command=MTMount.commands.AskForCommand,
            ccw_drive_enable=MTMount.commands.CameraCableWrapDriveEnable,
            ccw_enable_tracking=MTMount.commands.CameraCableWrapEnableTracking,
            ccw_move=MTMount.commands.CameraCableWrapMove,
            ccw_power=MTMount.commands.CameraCableWrapPower,
            ccw_reset_alarm=MTMount.commands.CameraCableWrapResetAlarm,
            ccw_stop=MTMount.commands.CameraCableWrapStop,
            ccw_track=MTMount.commands.CameraCableWrapTrack,
            el_power=MTMount.commands.ElevationAxisPower,
            el_reset_alarm=MTMount.commands.ElevationAxisResetAlarm,
            mc_deploy=MTMount.commands.MirrorCoversDeploy,
            mc_power=MTMount.commands.MirrorCoversPower,
            mc_reset_alarm=MTMount.commands.MirrorCoversResetAlarm,
            mc_retract=MTMount.commands.MirrorCoversRetract,
            mcl_move_all=MTMount.commands.MirrorCoverLocksMoveAll,
            mcl_power=MTMount.commands.MirrorCoverLocksPower,
            mcl_reset_alarm=MTMount.commands.MirrorCoverLocksResetAlarm,
            mps_power=MTMount.commands.MainPowerSupplyPower,
            mps_reset_alarm=MTMount.commands.MainPowerSupplyResetAlarm,
            oss_power=MTMount.commands.OilSupplySystemPower,
            oss_reset_alarm=MTMount.commands.OilSupplySystemResetAlarm,
            tec_power=MTMount.commands.TopEndChillerPower,
            tec_reset_alarm=MTMount.commands.TopEndChillerResetAlarm,
        )
        self.help_text = f"""Send commands to the telescope mount assemply.

TMA Commands (omit the tai argument, if shown):
{self.get_command_help()}

Other commands:
exit  # Exit from this commander
help  # Print this help
"""

    async def close(self):
        """Shut down this TMA commander."""
        try:
            self.read_loop_task.cancel()
            self.command_loop_task.cancel()
            if self.simulator is not None:
                await self.simulator.close()
            await self.communicator.close()
            self.done_task.set_result(None)
        except Exception as e:
            self.done_task.set_exception(e)

    def get_command_help(self):
        """Get help for all commands in self.command_dict, as a single string.
        """
        help_strs = [
            f"{cmd_name} {self.get_argument_names(cmd_name)}"
            for cmd_name in self.command_dict
        ]
        return "\n".join(help_strs)

    def get_argument_names(self, cmd_name):
        """Get the argument names from a command, for printing help.

        Parameters
        ----------
        cmd_name : `str`
            The command name, as the key in self.command_dict.
        """
        # Get FieldInfos for the command arguments (if any) from the
        # command class, and use that to generate a list of argument names.
        CommandClass = self.command_dict[cmd_name]
        arg_infos = CommandClass.field_infos[MTMount.commands.NUM_HEADER_FIELDS :]
        return " ".join(arg_info.name for arg_info in arg_infos)

    async def handle_command(self, cmd_name, args):
        """Parse arguments and issue a command.

        Parameters
        ----------
        cmd_name : `str`
            Command name.
        args : `List` [`str`]
            Arguments, as strings.

        Raises
        ------
        ValueError
            If ``args`` are not valid.
        """
        try:
            CommandClass = self.command_dict[cmd_name]
        except KeyError:
            raise ValueError(f"Unrecognized command {cmd_name}")
        # Get FieldInfos for the command arguments (if any) from the
        # command class, and use them to cast and validate the arguments.
        arg_infos = CommandClass.field_infos[MTMount.commands.NUM_HEADER_FIELDS :]
        # If the final argument for the command is TAI time,
        # then set it to the current time.
        has_tai_argument = arg_infos and arg_infos[-1].name == "tai"
        if has_tai_argument:
            arg_infos = arg_infos[0:-1]
        if len(args) != len(arg_infos):
            raise ValueError(
                f"Command {cmd_name} needs {len(arg_infos)} arguments, but got {len(args)}"
            )
        kwargs = {
            info.name: info.value_from_str(arg) for arg, info in zip(args, arg_infos)
        }
        if has_tai_argument:
            kwargs["tai"] = salobj.current_tai()

        cmd = CommandClass(**kwargs)
        await self.communicator.write(cmd)

    async def read_loop(self):
        """Read replies from the operations manager.
        """
        try:
            await self.communicator.connect_task
            while True:
                read_message = await self.communicator.read()
                print(f"read {read_message}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"tma_commander read loop failed with {e!r}")

    def connect_callback(self, communicator):
        """Callback function for changes in communicator connection state.

        Parameters
        ----------
        communicator : `MTMount.Communicator`
            The communicator whose connection state has changed.
        """
        print_connected(descr="TMA commander", communicator=communicator)
        if communicator.connected:
            self.read_loop_task = asyncio.create_task(self.read_loop())

    async def command_loop(self):
        """Read commands from the user and send them to the operations manager.
        """
        try:
            print("Waiting to connect to the operation manager")
            await self.communicator.connect_task
            print(f"\n{self.help_text}")
            async for line in salobj.stream_as_generator(stream=sys.stdin):
                line = line.strip()
                # Strip trailing comment, if any.
                if "#" in line:
                    line = line.split("#", maxsplit=1)[0].strip()
                if not line:
                    continue
                tokens = line.split()
                cmd_name = tokens[0]
                args = tokens[1:]
                try:
                    if cmd_name == "exit":
                        break
                    elif cmd_name == "help":
                        print(self.help_text)
                    else:
                        await self.handle_command(cmd_name, args)
                except Exception as e:
                    print(f"Command {cmd_name} failed: {e}")
                    print(traceback.format_exc())
                    continue
        finally:
            await self.close()


async def amain():
    """Parse command-line arguments and run the TMA commander.
    """
    parser = argparse.ArgumentParser("Send commands to Tekniker's TMA")
    parser.add_argument(
        "--host", default="127.0.0.1", help="TMA operation manager IP address."
    )
    parser.add_argument(
        "--log-level",
        type=int,
        default=logging.INFO,
        help="Log level (DEBUG=10, INFO=20, WARNING=30).",
    )
    parser.add_argument(
        "-s", "--simulate", action="store_true", help="Run in simuation mode?"
    )
    namespace = parser.parse_args()
    commander = Commander(
        host=namespace.host, log_level=namespace.log_level, simulate=namespace.simulate,
    )
    await commander.done_task


asyncio.run(amain())
