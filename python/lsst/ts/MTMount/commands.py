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

__all__ = [
    "NUM_HEADER_FIELDS",
    "AckOnlyCommandCodes",
    "Command",
    "AzimuthAxisDriveEnable",
    "AzimuthAxisDriveReset",
    "AzimuthAxisEnableTracking",
    "AzimuthAxisHome",
    "AzimuthAxisMove",
    "AzimuthAxisPower",
    "AzimuthAxisResetAlarm",
    "AzimuthAxisStop",
    "AzimuthAxisTrack",
    "BothAxesMove",
    "BothAxesStop",
    "BothAxesTrack",
    "CameraCableWrapDriveEnable",
    "CameraCableWrapDriveReset",
    "CameraCableWrapEnableTracking",
    "CameraCableWrapMove",
    "CameraCableWrapPower",
    "CameraCableWrapResetAlarm",
    "CameraCableWrapStop",
    "CameraCableWrapTrack",
    "Disable",
    "Enable",
    "ElevationAxisDriveEnable",
    "ElevationAxisDriveReset",
    "ElevationAxisEnableTracking",
    "ElevationAxisHome",
    "ElevationAxisMove",
    "ElevationAxisPower",
    "ElevationAxisResetAlarm",
    "ElevationAxisStop",
    "ElevationAxisTrack",
    "MainPowerSupplyPower",
    "MainPowerSupplyResetAlarm",
    "MirrorCoverLocksMoveAll",
    "MirrorCoverLocksPower",
    "MirrorCoverLocksResetAlarm",
    "MirrorCoverLocksStop",
    "MirrorCoversDeploy",
    "MirrorCoversRetract",
    "MirrorCoversPower",
    "MirrorCoversResetAlarm",
    "MirrorCoversStop",
    "OilSupplySystemPower",
    "OilSupplySystemPowerCooling",
    "OilSupplySystemPowerMainPump",
    "OilSupplySystemPowerOil",
    "OilSupplySystemResetAlarm",
    "TopEndChillerPower",
    "TopEndChillerResetAlarm",
    "TopEndChillerTrackAmbient",
    "AskForCommands",
    "SafetyReset",
    "Commands",
    "CommandDict",
    "parse_command",
]

from lsst.ts import salobj
from . import base_message
from . import enums
from . import field_info
from . import utils

MAX_SEQUENCE_ID = (1 << 31) - 1

# Number of required fields, before the optional arguments start
NUM_HEADER_FIELDS = 4


# Command that are done when ACK is received
AckOnlyCommandCodes = set(
    (
        enums.CommandCode.BOTH_AXES_TRACK,
        enums.CommandCode.AZIMUTH_AXIS_TRACK,
        enums.CommandCode.ELEVATION_AXIS_TRACK,
        enums.CommandCode.AZIMUTH_CABLE_WRAP_TRACK,
        enums.CommandCode.CAMERA_CABLE_WRAP_TRACK,
    )
)


class Command(base_message.BaseMessage):
    """Base class for commands.

    Set sequence_id to an incrementing integer (that eventually
    wraps around), by default.
    """

    sequence_id_generator = salobj.index_generator(imax=MAX_SEQUENCE_ID)

    def __init__(self, **kwargs):
        if kwargs.get("sequence_id") is None:
            kwargs["sequence_id"] = next(self.sequence_id_generator)
        return super().__init__(**kwargs)


def make_command_doc(cls):
    """Make and attach a doc string to a command class.
    """
    param_strings = []
    for finfo in cls.field_infos:
        param_doc = utils.wrap_parameter_doc(finfo.doc)
        is_optional = finfo.default is not None or finfo.name == "sequence_id"
        optional_str = ", optional" if is_optional else ""
        param_strings.append(
            f"{finfo.name} : `{finfo.dtype.__name__}{optional_str}`\n{param_doc}"
        )
    param_block = "\n".join(param_strings)
    cls.__doc__ = f"""{cls.__name__} command.

Parameters
----------
{param_block}
"""


def make_command_field_infos(command_code, parameters=()):
    """Make field_infos for a command.

    Parameters
    ----------
    command_code : `CommandCode`
        Command code.
    parameters : `List` [`FieldInfo`], optional
        Field information for command parameters, if any.
    """
    for param in parameters:
        if not isinstance(param, field_info.BaseFieldInfo):
            raise ValueError(
                f"parameters={parameters} is not a sequence of field_info.BaseFieldInfo"
            )
    return (
        field_info.IntFieldInfo(
            name="sequence_id",
            doc="Sequence number; used to identify replies to this command.",
        ),
        field_info.CommandCodeFieldInfo(command_code),
        field_info.SourceFieldInfo(what="command"),
        field_info.TimestampFieldInfo(),
    ) + tuple(parameters)


_TrackingParameters = (
    field_info.FloatFieldInfo(name="position", doc="Target position (deg) at tai"),
    field_info.FloatFieldInfo(name="velocity", doc="Target velocity (deg/sec) at tai"),
    field_info.FloatFieldInfo(
        name="tai", doc="Target TAI time for position and velocity (unix seconds)",
    ),
)

_MoveParameters = (
    field_info.FloatFieldInfo(name="position", doc="Target position (deg)."),
    field_info.FloatFieldInfo(
        name="velocity",
        default=0,
        doc="Maximum velocity; 0 for the default value (deg/second).",
    ),
    field_info.FloatFieldInfo(
        name="acceleration",
        default=0,
        doc="Maximum acceleration; 0 for the default value (deg/second2).",
    ),
    field_info.FloatFieldInfo(
        name="jerk",
        default=0,
        doc="Maximum jerk; 0 for the default value (deg/second3).",
    ),
)

_OnOffParameters = (
    field_info.BoolFieldInfo(name="on", doc="Turn on (True) or off (False)"),
)

"""
Supported elevation and azimuth axis commands:

* <AXIS>_AXIS_POWER
* <AXIS>_AXIS_STOP
* <AXIS>_AXIS_MOVE
* <AXIS>_AXIS_TRACK

Other elevation and azimuth axis commands:

* <AXIS>_AXIS_MOVE_VELOCITY
* <AXIS>_AXIS_HOME
* <AXIS>_AXIS_RESET_ALARM
"""

class AskForCommand(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.ASK_FOR_COMMAND,
        (
            field_info.IntFieldInfo(
                name="commander", doc="Which commander to request ownership for? 2 = EUI, 3 = HDD", default=2
            ),
        ),
    )
    print(field_infos)

class SafetyReset(Command):
    field_infos = make_command_field_infos(enums.CommandCode.SAFETY_RESET,)

class AzimuthAxisDriveEnable(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.AZIMUTH_AXIS_DRIVE_ENABLE,
        (
            (
                field_info.IntFieldInfo(
                    name="drive", doc="Drive index: one of -1 (all), ?", default=-1
                ),
            )
            + _OnOffParameters
        ),
    )


class AzimuthAxisDriveReset(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.AZIMUTH_AXIS_DRIVE_RESET,
        (
            field_info.IntFieldInfo(
                name="drive", doc="Drive index: one of -1 (all), ?", default=-1
            ),
        ),
    )


class AzimuthAxisEnableTracking(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.AZIMUTH_AXIS_ENABLE_TRACKING, _OnOffParameters
    )


class AzimuthAxisHome(Command):
    field_infos = make_command_field_infos(enums.CommandCode.AZIMUTH_AXIS_HOME,)


class AzimuthAxisMove(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.AZIMUTH_AXIS_MOVE, _MoveParameters
    )


class AzimuthAxisPower(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.AZIMUTH_AXIS_POWER, _OnOffParameters
    )


class AzimuthAxisResetAlarm(Command):
    field_infos = make_command_field_infos(enums.CommandCode.AZIMUTH_AXIS_RESET_ALARM,)


class AzimuthAxisStop(Command):
    field_infos = make_command_field_infos(enums.CommandCode.AZIMUTH_AXIS_STOP)


class AzimuthAxisTrack(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.AZIMUTH_AXIS_TRACK, _TrackingParameters
    )


class BothAxesMove(Command):
    """Move both axes to a specified position and stop."""

    field_infos = make_command_field_infos(
        enums.CommandCode.BOTH_AXES_MOVE,
        (
            field_info.FloatFieldInfo(name="azimuth", doc="Desired azimuth (deg)"),
            field_info.FloatFieldInfo(name="elevation", doc="Desired elevation (deg)"),
            field_info.FloatFieldInfo(
                name="azimuth_velocity",
                default=0,
                doc="Maximum azimuth velocity (0 for the default value) (deg)",
            ),
            field_info.FloatFieldInfo(
                name="elevation_velocity",
                default=0,
                doc="Maximum elevation velocity (0 for the default value) (deg)",
            ),
            field_info.IntFieldInfo(
                name="negate_azimuth",
                default=0,
                doc="If 0 accept azimuth as is; if -1 multiply azimuth by -1",
            ),
        ),
    )


class BothAxesStop(Command):
    """Stop both axes."""

    field_infos = make_command_field_infos(enums.CommandCode.BOTH_AXES_STOP)


class BothAxesTrack(Command):
    """Specify the tracking target for both axes."""

    field_infos = make_command_field_infos(
        enums.CommandCode.BOTH_AXES_TRACK,
        (
            field_info.FloatFieldInfo(
                name="azimuth", doc="Target azimuth at tai (deg)"
            ),
            field_info.FloatFieldInfo(
                name="elevation", doc="Target elevation at tai (deg)"
            ),
            field_info.FloatFieldInfo(
                name="azimuth_velocity", doc="Target azimuth velocity at tai (deg)",
            ),
            field_info.FloatFieldInfo(
                name="elevation_velocity", doc="Target elevation velocity at tai (deg)",
            ),
            field_info.IntFieldInfo(
                name="negate_azimuth",
                default=0,
                doc="If 0 accept azimuth as is; if -1 multiply azimuth by -1",
            ),
            field_info.FloatFieldInfo(
                name="tai",
                doc="Target TAI time for position and velocity (unix seconds)",
            ),
        ),
    )


class CameraCableWrapDriveEnable(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.CAMERA_CABLE_WRAP_DRIVE_ENABLE,
        (
            field_info.IntFieldInfo(
                name="drive",
                doc="Drive index; just one drive can be enabled, so enabling one disables the other",
            ),
        )
        + _OnOffParameters,
    )


class CameraCableWrapDriveReset(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.CAMERA_CABLE_WRAP_DRIVE_RESET,
        (field_info.IntFieldInfo(name="drive", doc="Drive index; one of -1=all, ?"),),
    )


class CameraCableWrapEnableTracking(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.CAMERA_CABLE_WRAP_ENABLE_TRACKING, _OnOffParameters
    )


class CameraCableWrapMove(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.CAMERA_CABLE_WRAP_MOVE, _MoveParameters
    )


class CameraCableWrapPower(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.CAMERA_CABLE_WRAP_POWER, _OnOffParameters
    )


class CameraCableWrapResetAlarm(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.CAMERA_CABLE_WRAP_RESET_ALARM,
    )


class CameraCableWrapStop(Command):
    field_infos = make_command_field_infos(enums.CommandCode.CAMERA_CABLE_WRAP_STOP)


class CameraCableWrapTrack(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.CAMERA_CABLE_WRAP_TRACK, _TrackingParameters
    )


class Disable(Command):
    field_infos = make_command_field_infos(enums.CommandCode.DISABLE,)


class Enable(Command):
    field_infos = make_command_field_infos(enums.CommandCode.ENABLE,)


class ElevationAxisDriveEnable(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.ELEVATION_AXIS_DRIVE_ENABLE,
        (
            (
                field_info.IntFieldInfo(
                    name="drive", doc="Drive index: one of -1 (all), ?", default=-1
                ),
            )
            + _OnOffParameters
        ),
    )


class ElevationAxisDriveReset(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.ELEVATION_AXIS_DRIVE_RESET,
        (
            field_info.IntFieldInfo(
                name="drive", doc="Drive index: one of -1 (all), ?", default=-1
            ),
        ),
    )


class ElevationAxisEnableTracking(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.ELEVATION_AXIS_ENABLE_TRACKING, _OnOffParameters
    )


class ElevationAxisHome(Command):
    field_infos = make_command_field_infos(enums.CommandCode.ELEVATION_AXIS_HOME,)


class ElevationAxisMove(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.ELEVATION_AXIS_MOVE, _MoveParameters
    )


class ElevationAxisPower(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.ELEVATION_AXIS_POWER, _OnOffParameters
    )


class ElevationAxisResetAlarm(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.ELEVATION_AXIS_RESET_ALARM,
    )


class ElevationAxisStop(Command):
    field_infos = make_command_field_infos(enums.CommandCode.ELEVATION_AXIS_STOP)


class ElevationAxisTrack(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.ELEVATION_AXIS_TRACK, _TrackingParameters
    )


class MainPowerSupplyPower(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.MAIN_POWER_SUPPLY_POWER, _OnOffParameters
    )


class MainPowerSupplyResetAlarm(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.MAIN_POWER_SUPPLY_RESET_ALARM
    )


"""
Unsupported mirror cover locks commands:

* MIRROR_COVER_LOCKS_MOVE = 903
* MIRROR_COVER_LOCKS_MOVE_VELOCITY = 904
"""


class MirrorCoverLocksMoveAll(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.MIRROR_COVER_LOCKS_MOVE_ALL,
        (
            field_info.IntFieldInfo(
                name="drive", doc="Drive index: one of -1 (all), 0, 1, 2, 3", default=-1
            ),
            field_info.BoolFieldInfo(
                name="deploy", doc="Deploy (True) or retract (False)?"
            ),
        ),
    )


class MirrorCoverLocksPower(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.MIRROR_COVER_LOCKS_POWER,
        (
            field_info.IntFieldInfo(
                name="drive", doc="Drive index: one of -1 (all), 0, 1, 2, 3", default=-1
            ),
        )
        + _OnOffParameters,
    )


class MirrorCoverLocksResetAlarm(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.MIRROR_COVER_LOCKS_RESET_ALARM,
        (
            field_info.IntFieldInfo(
                name="drive", doc="Drive index: one of -1 (all), 0, 1, 2, 3", default=-1
            ),
        ),
    )


class MirrorCoverLocksStop(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.MIRROR_COVER_LOCKS_STOP,
        (
            field_info.IntFieldInfo(
                name="drive", doc="Drive index: one of -1 (all), 0, 1, 2, 3", default=-1
            ),
        ),
    )


"""
Unsupported mirror cover commands:

* MIRROR_COVERS_MOVE = 903
* MIRROR_COVERS_MOVE_VELOCITY = 904
"""


class MirrorCoversDeploy(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.MIRROR_COVERS_DEPLOY,
        (
            field_info.IntFieldInfo(
                name="drive", doc="Drive index: one of -1 (all), 0, 1, 2, 3", default=-1
            ),
        ),
    )


class MirrorCoversRetract(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.MIRROR_COVERS_RETRACT,
        (
            field_info.IntFieldInfo(
                name="drive", doc="Drive index: one of -1 (all), 0, 1, 2, 3", default=-1
            ),
        ),
    )


class MirrorCoversPower(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.MIRROR_COVERS_POWER,
        (
            field_info.IntFieldInfo(
                name="drive", doc="Drive index: one of -1 (all), 0, 1, 2, 3", default=-1
            ),
        )
        + _OnOffParameters,
    )


class MirrorCoversResetAlarm(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.MIRROR_COVERS_RESET_ALARM,
        (
            field_info.IntFieldInfo(
                name="drive", doc="Drive index: one of -1 (all), 0, 1, 2, 3", default=-1
            ),
        ),
    )


class MirrorCoversStop(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.MIRROR_COVERS_STOP,
        (
            field_info.IntFieldInfo(
                name="drive", doc="Drive index: one of -1 (all), 0, 1, 2, 3", default=-1
            ),
        ),
    )


class OilSupplySystemPower(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.OIL_SUPPLY_SYSTEM_POWER, _OnOffParameters,
    )


class OilSupplySystemPowerCooling(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.OIL_SUPPLY_SYSTEM_POWER_COOLING, _OnOffParameters,
    )


class OilSupplySystemPowerMainPump(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.OIL_SUPPLY_SYSTEM_POWER_MAIN_PUMP, _OnOffParameters,
    )


class OilSupplySystemPowerOil(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.OIL_SUPPLY_SYSTEM_POWER_OIL, _OnOffParameters,
    )


class OilSupplySystemResetAlarm(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.OIL_SUPPLY_SYSTEM_RESET_ALARM,
    )


class TopEndChillerPower(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.TOP_END_CHILLER_POWER, _OnOffParameters,
    )


class TopEndChillerResetAlarm(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.TOP_END_CHILLER_RESET_ALARM,
    )


class TopEndChillerTrackAmbient(Command):
    field_infos = make_command_field_infos(
        enums.CommandCode.TOP_END_CHILLER_TRACK_AMBIENT,
        _OnOffParameters + (field_info.FloatFieldInfo(name="temperature", doc="???"),),
    )


Commands = (
    AzimuthAxisDriveEnable,
    AzimuthAxisDriveReset,
    AzimuthAxisEnableTracking,
    AzimuthAxisHome,
    AzimuthAxisMove,
    AzimuthAxisPower,
    AzimuthAxisResetAlarm,
    AzimuthAxisStop,
    AzimuthAxisTrack,
    BothAxesMove,
    BothAxesStop,
    BothAxesTrack,
    CameraCableWrapDriveEnable,
    CameraCableWrapDriveReset,
    CameraCableWrapEnableTracking,
    CameraCableWrapMove,
    CameraCableWrapPower,
    CameraCableWrapResetAlarm,
    CameraCableWrapStop,
    CameraCableWrapTrack,
    Disable,
    Enable,
    ElevationAxisDriveEnable,
    ElevationAxisDriveReset,
    ElevationAxisEnableTracking,
    ElevationAxisHome,
    ElevationAxisMove,
    ElevationAxisPower,
    ElevationAxisResetAlarm,
    ElevationAxisStop,
    ElevationAxisTrack,
    MainPowerSupplyPower,
    MainPowerSupplyResetAlarm,
    MirrorCoverLocksMoveAll,
    MirrorCoverLocksPower,
    MirrorCoverLocksResetAlarm,
    MirrorCoverLocksStop,
    MirrorCoversDeploy,
    MirrorCoversRetract,
    MirrorCoversPower,
    MirrorCoversResetAlarm,
    MirrorCoversStop,
    OilSupplySystemPower,
    OilSupplySystemPowerCooling,
    OilSupplySystemPowerMainPump,
    OilSupplySystemPowerOil,
    OilSupplySystemResetAlarm,
    TopEndChillerPower,
    TopEndChillerResetAlarm,
    TopEndChillerTrackAmbient,
)

for command in Commands:
    make_command_doc(command)


def _make_command_dict():
    """Make a dict of command_code: CommandClass from `Commands`.

    Check that no command codes are duplicated.
    """
    command_dict = {}
    for command in Commands:
        command_code = command.field_infos[1].default
        if command_code in command_dict:
            raise RuntimeError(
                "The command code appears twice: "
                f"once in {command_dict[command_code].__name__}; "
                f"and once in {command.__name__}"
            )
        command_dict[command_code] = command
    return command_dict


# Dict of CommandCode: CommandClass
CommandDict = _make_command_dict()


def parse_command(fields):
    """Return a Command from a bytes string.

    Parameters
    ----------
    fields : `List` [`str`]
        Fields from a read message.
        The fields should not be terminated with ``\n``.

    Raises
    ------
    ValueError
        If the data cannot be parsed.
    """
    if len(fields) < NUM_HEADER_FIELDS:
        raise ValueError(
            f"A command has at least {NUM_HEADER_FIELDS} fields; only got {len(fields)}"
        )
    command_code = enums.CommandCode(int(fields[1]))
    try:
        CommandClass = CommandDict[command_code]
    except ValueError:
        raise RuntimeError(f"Unsupported command_code={command_code}")
    return CommandClass.from_str_fields(fields)
