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

__all__ = ["Communicator"]

import asyncio

from . import client_server_pair
from . import commands
from . import replies


class Communicator(client_server_pair.ClientServerPair):
    r"""Read and write `BaseMessage`\ s using Tekniker's
    communication protocol.

    Data is written to the client socket
    and read from the (single) server socket.

    Parameters
    ----------
    name : `str`
        Name used for error messages.
    client_host : `str`
        IP address for the output client socket.
    client_port : `int`
        IP port for the output client socket.
    server_host : `str` or `None`
        IP address for the input socket server.
        If `None` then use all interfaces.
    server_port : `int`
        IP port for the input socket server.
        If 0 then use a random port.
    log : `logging.Logger`
        Logger.
    read_replies : `bool`
        If True then read replies, else read commands,
        on the server port.
    connect : `bool`, optional
        Connect the client at construction time?
        (The server automatically tries to connect.)
    connect_callback : callable, optional
        Synchronous function to call when a connection is made or dropped.

    Notes
    -----
    Tekniker's OperationManager software connects to each component
    (PXI, EUI and HHD) using two TCP/IP sockets:

    * A client socket for output; data is only written to this socket.
        For the PXI this is used to send commands.
        For EUI and HDD this is used to send replies.
    * A server socket for input; data is only read from this socket.
        For the PXI this is used to read replies.
        For EUI and HDD this is used to read commands.
    """

    def __init__(
        self,
        name,
        client_host,
        client_port,
        server_host,
        server_port,
        log,
        read_replies,
        connect=True,
        connect_callback=None,
    ):
        super().__init__(
            name=name,
            client_host=client_host,
            client_port=client_port,
            server_host=server_host,
            server_port=server_port,
            log=log,
            connect=connect,
            connect_callback=connect_callback,
        )
        self.monitor_client_writer_task = asyncio.Future()
        if read_replies:
            self.parse_read_fields = replies.parse_reply
        else:
            self.parse_read_fields = commands.parse_command

        # Lock write/drain to prevent calling drain while draining (an error).
        self.write_lock = asyncio.Lock()

    async def close(self):
        self.monitor_client_writer_task.cancel()
        await super().close()

    async def connect(self, port=None):
        await super().connect(port=port)
        self.monitor_client_writer_task = asyncio.create_task(
            self.monitor_client_reader()
        )

    async def read(self):
        """Read and return a message. Waits indefinitely.

        Returns
        -------
        message : `BaseMessage`
            The message read.

        Raises
        ------
        RuntimeError
            If not connected before reading begins.
        ConnectionResetError
            If the connection is lost while reading.
            This also calls ``connect_callback``.
        """
        if not self.server_connected:
            raise RuntimeError("Server not connected")
        try:
            read_bytes = await self.server_reader.readuntil(b"\r\n")
            read_str = read_bytes.decode(errors="ignore")[:-2]
        except asyncio.CancelledError:
            raise
        except ConnectionResetError:
            self.log.error(
                "Lost connection to the low-level controller (detected in read)"
            )
            self.call_connect_callback()
        except Exception:
            # Print details if the error is other than "connection lost"
            if self.connected:
                self.log.exception("Read failed")
            raise
        try:
            fields = read_str.split("\n")
            message = self.parse_read_fields(fields)
            self.log.debug("Read %s; bytes %s", message, read_bytes)
            return message
        except Exception:
            self.log.exception(f"Could not parse read data: {read_bytes}")
            raise

    async def write(self, message):
        """Write a message.

        Parameters
        ----------
        message : `BaseMessage`
            Message to write.

        Raises
        ------
        RuntimeError
            If not connected before writing.
        ConnectionResetError
            If the connection is lost while writing.
            This also calls ``connect_callback``.
        """
        if not self.client_connected:
            raise RuntimeError("Client not connected")
        message_bytes = message.encode()
        try:
            async with self.write_lock:
                self.log.debug("Write %s; bytes=%s", message, message_bytes)
                self.client_writer.write(message_bytes)
                await self.client_writer.drain()
        except ConnectionResetError:
            self.log.error(
                "Lost connection to the low-level controller (detected in write)"
            )
            self.call_connect_callback()
            raise
        except Exception:
            self.log.exception(f"Failed to write {message_bytes}")
            raise

    async def monitor_client_reader(self):
        """Monitor the client reader; if it closes then close the writer.
        """
        # We do not expect to read any data, but we may as well accept it
        # if some comes in.
        try:
            while True:
                data = await self.client_reader.read(1000)
                if self.client_reader.at_eof():
                    self.log.info("Client reader at eof; closing client")
                    break
                else:
                    self.log.warning(
                        f"Unexpected data {data!r} read from the client reader; "
                        "ignoring the data."
                    )
                    await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            pass
        except (ConnectionResetError, asyncio.IncompleteReadError):
            print("Client connection closed at the other end")
            pass
        except Exception as e:
            print(f"monitor_client_reader failed: {e!r}")

        await self.close_client()
        self.call_connect_callback()
