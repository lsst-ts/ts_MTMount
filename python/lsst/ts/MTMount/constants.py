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


# For reference and testing against Tekniker simulators.
# Reply ports are one larger.
EUI_COMMAND_PORT = 60005
HHD_COMMAND_PORT = 40005
# CSC TCP/IP default configuration
# Update this when Tekniker adds a dedicated pair of ports for the CSC.
CSC_COMMAND_PORT = HHD_COMMAND_PORT

# We probably don't need this, because -1 means "all drives".
MIRROR_COVER_DRIVES = (0, 1, 2, 3)
