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
    "BaseFieldInfo",
    "BoolFieldInfo",
    "EnumFieldInfo",
    "FixedEnumFieldInfo",
    "FloatFieldInfo",
    "IntFieldInfo",
    "StrFieldInfo",
    "TimestampFieldInfo",
    "CommandCodeFieldInfo",
    "ReplyCodeFieldInfo",
    "SourceFieldInfo",
]

import abc
import enum

import astropy.time

from . import constants
from . import enums

# Temporary hack until the CSC has a dedicated port.
if constants.CSC_COMMAND_PORT == constants.EUI_COMMAND_PORT:
    SOURCE_ID = enums.Source.EUI
elif constants.CSC_COMMAND_PORT == constants.HHD_COMMAND_PORT:
    SOURCE_ID = enums.Source.HHD
else:
    raise RuntimeError("Unknown constants.CSC_COMMAND_PORT; cannot set SOURCE_ID")


class BaseFieldInfo(metaclass=abc.ABCMeta):
    """Information about one field of a message.

    Parameters
    ----------
    name : `str`
        Name of field. Must be a valid Python identifier.
    doc : `str`
        Description of the field.
    default : ``any`` or `None`, optional
        Default value (using the native type of this FieldInfo).
        If `None` then this field must be specified
        when constructing a command or reply.
    dtype : ``class``
        Data type.
    """

    def __init__(self, name, doc, dtype, default=None):
        self.name = name
        self.doc = doc
        self.dtype = dtype
        self._default = default
        if default is not None:
            self.assert_value_ok(default)

    @property
    def default(self):
        return self._default

    def assert_value_ok(self, value):
        if not isinstance(value, self.dtype):
            raise ValueError(f"value={value!r} is not of type {self.dtype.__name__}")

    @abc.abstractmethod
    def value_from_str(self, strval):
        """Convert a string to a value of the correct type.

        Parameters
        ----------
        strval : `str`
            String representation of value.

        Returns
        -------
        value : ``any``
            The parsed value.

        Raises
        ------
        ValueError
            If the value cannot be parsed.
        """
        raise NotImplementedError()

    def str_from_value(self, value):
        """Return a string representation of the value.
        """
        return str(value)


class BoolFieldInfo(BaseFieldInfo):
    """A bool field with str representation "0"/"1".

    Parameters
    ----------
    name : `str`
        Name of field. Must be a valid Python identifier.
    doc : `str`
        Description of the field.
    default : ``any`` or `None`, optional
        Default value (using the native type of this FieldInfo).
        If `None` then this field must be specified
        when constructing a command or reply.
    """

    def __init__(self, name, doc, default=None):
        super().__init__(name=name, doc=doc, dtype=bool, default=default)

    def value_from_str(self, strval):
        return bool(int(strval))

    def str_from_value(self, value):
        return "1" if value else "0"


class EnumFieldInfo(BaseFieldInfo):
    """An enum field.

    Parameters
    ----------
    name : `str`
        Name of field. Must be a valid Python identifier.
    doc : `str`
        Description of the field.
    dtype : ``enum``
        Class of enum; any of the enum classes from the enum package is fine.
    default : ``dtype`` or `None`
        Default value.
        If `None` then this field must be specified
        when constructing a command or reply.
    """

    def __init__(self, name, doc, dtype, default=None):
        if not issubclass(dtype, enum.Enum):
            raise ValueError(f"dtype={dtype!r} must be an enum.Enum")
        super().__init__(name=name, doc=doc, dtype=dtype, default=default)

    def assert_value_ok(self, value):
        self.dtype(value)

    def value_from_str(self, strval):
        intval = int(strval)
        return self.dtype(intval)

    def str_from_value(self, value):
        return str(value.value)


class FixedEnumFieldInfo(EnumFieldInfo):
    """Information for an enum field that must be a given enum value.

    Parameters
    ----------
    name : `str`
        Name of field. Must be a valid Python identifier.
    default : `enum.Enum`
        The required enum value for this field.
    """

    def __init__(self, name, default):
        if not isinstance(default, enum.Enum):
            raise ValueError(f"default={default} is not an enum instance.")
        super().__init__(
            name=name,
            doc=f"{name} field with a fixed value: {default!r}",
            dtype=type(default),
            default=default,
        )

    def assert_value_ok(self, value):
        if value != self.default:
            raise ValueError(f"value={value!r} must be {self.default!r}")

    def value_from_str(self, strval):
        value = super().value_from_str(strval)
        self.assert_value_ok(value)
        return value


class FloatFieldInfo(BaseFieldInfo):
    """A float field.

    Parameters
    ----------
    name : `str`
        Name of field. Must be a valid Python identifier.
    doc : `str`
        Description of the field.
    default : ``any`` or `None`, optional
        Default value (using the native type of this FieldInfo).
        If `None` then this field must be specified
        when constructing a command or reply.
    """

    def __init__(self, name, doc, default=None):
        super().__init__(name=name, doc=doc, dtype=float, default=default)

    def assert_value_ok(self, value):
        if not (isinstance(value, float) or isinstance(value, int)):
            raise ValueError(f"value={value!r} is not a float or int")

    def value_from_str(self, strval):
        return float(strval)

    def str_from_value(self, value):
        return str(float(value))


class IntFieldInfo(BaseFieldInfo):
    """An int field.

    Parameters
    ----------
    name : `str`
        Name of field. Must be a valid Python identifier.
    doc : `str`
        Description of the field.
    default : ``any`` or `None`, optional
        Default value (using the native type of this FieldInfo).
        If `None` then this field must be specified
        when constructing a command or reply.
    empty_is_default : `bool`
        If True then an empty value is treated as a default value
        (and the default must not be None).
        If False then an empty value is rejected as invalid.
    """

    def __init__(self, name, doc, default=None, empty_is_default=False):
        if empty_is_default and default is None:
            raise ValueError("Must specify a default if empty_is_default is True")
        self.empty_is_default = empty_is_default
        super().__init__(name=name, doc=doc, dtype=int, default=default)

    def value_from_str(self, strval):
        if strval == "":
            if self.empty_is_default:
                return self.default
            raise ValueError("Blank string and empty_is_default False")
        return int(strval)

    def str_from_value(self, value):
        return f"{int(value)}"


class StrFieldInfo(BaseFieldInfo):
    """A str field.

    Parameters
    ----------
    name : `str`
        Name of field. Must be a valid Python identifier.
    doc : `str`
        Description of the field.
    default : ``any`` or `None`, optional
        Default value (using the native type of this FieldInfo).
        If `None` then this field must be specified
        when constructing a command or reply.
    """

    def __init__(self, name, doc, default=None):
        super().__init__(name=name, doc=doc, dtype=str, default=default)

    def value_from_str(self, strval):
        return strval


class TimestampFieldInfo(BaseFieldInfo):
    """UTC timestamp field.

    The str representation is ISO-8601, with "T" between the date and time.
    For example: "2020-02-27T14:48:27.469". It will never have leap seconds
    (see notes).

    Parameters
    ----------
    name : `str`
        Name of field. Must be a valid Python identifier.
    doc : `str`, optional
        Description of the field.
    scale : `str`
        One of "tai" or "utc", where "utc" is an approximation
        without leap seconds (see notes).
    default : `True` or `None`
        If `True` then the current date is used as a default.
        If `None` then the date must be specified.

    Notes
    -----
    The time is not exactly UTC; it is a an approximation to UTC which has
    no leap seconds. On the day of a leap second the time time is uniformly
    stretched so there are the usual number of seconds in the day.
    Tekniker's code only uses UTC time for *unimportant* message timestamps,
    and this avoids the risk of passing Tekniker's code a timestamp value
    that it cannot handle.
    """

    def __init__(self):
        super().__init__(
            name="timestamp",
            doc="Time at which the message was sent.",
            dtype=astropy.time.Time,
            default=None,
        )

    @property
    def default(self):
        return astropy.time.Time.now()

    def assert_value_ok(self, value):
        if not isinstance(value, astropy.time.Time):
            raise ValueError(f"value={value!r} is not an astropy.time.Time")

    def value_from_str(self, strval):
        return astropy.time.Time(strval, scale="utc")

    def str_from_value(self, value):
        return value.isot


# Convenience versions of the fields above


class CommandCodeFieldInfo(FixedEnumFieldInfo):
    """Information for the ``command_code`` field of command.

    Parameters
    ----------
    default : `CommandCode`
        The command code for this command.
    """

    def __init__(self, default):
        enums.CommandCode(default)  # Check value.
        super().__init__(name="command_code", default=default)


class ReplyCodeFieldInfo(FixedEnumFieldInfo):
    """Information for the ``command_code`` field of reply.

    Parameters
    ----------
    default : `ReplyCode`
        The reply code for this reply.
    """

    def __init__(self, default):
        enums.ReplyCode(default)  # Check value.
        super().__init__(name="reply_code", default=default)


class SourceFieldInfo(EnumFieldInfo):
    """Information for the ``source`` field.

    Parameters
    ----------
    what : `str`
        Kind of message, e.g. "command" or "warning".
        Used as part of the doc string.
    """

    def __init__(self, what):
        super().__init__(
            name="source",
            doc=f"Source of the {what}; a `Source`",
            dtype=enums.Source,
            # TODO: change this when we have a value for the CSC
            default=SOURCE_ID,
        )


class SubsystemFieldInfo(StrFieldInfo):
    """Information for the ``subsystem`` field in Warnings and Errors.

    Parameters
    ----------
    what : `str`
        Kind of message, e.g. "error" or "warning".
    """

    def __init__(self, what):
        super().__init__(
            name="subsystem",
            doc=f"""Source of the {what}. The format is f"{{subsystem_id}}. {{details}}".""",
        )
