# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from testinfra.modules.base import Module
from testinfra.utils import cached_property
import re


class BlockDevice(Module):
    """Information for block device.

    Should be used with sudo or under root.

    If device is not a block device, RuntimeError is raised.
    """

    @property
    def _data(self):
        raise NotImplementedError

    def __init__(self, device):
        self.device = device
        super().__init__()

    @property
    def is_partition(self):
        """Return True if the device is a partition.

        >>> host.block_device("/dev/sda1").is_partition
        True

        >>> host.block_device("/dev/sda").is_partition
        False


        """
        return self._data["start_sector"] > 0

    @property
    def size(self):
        """Return size if the device in bytes.

        >>> host.block_device("/dev/sda1").size
        512110190592

        """
        return self._data["size"]

    @property
    def sector_size(self):
        """Return sector size for the device in bytes.

        >>> host.block_device("/dev/sda1").sector_size
        512
        """
        return self._data["sector_size"]

    @property
    def block_size(self):
        """Return block size for the device in bytes.

        >>> host.block_device("/dev/sda").block_size
        4096
        """
        return self._data["block_size"]

    @property
    def start_sector(self):
        """Return start sector of the device on the underlying device.

           Usually the value is zero for full devices and is non-zero
           for partitions.

        >>> host.block_device("/dev/sda1").start_sector
        2048

        >>> host.block_device("/dev/md0").start_sector
        0
        """
        return self._data["sector_size"]

    @property
    def is_writable(self):
        """Return True if device is writable (have no RO status)

        >>> host.block_device("/dev/sda").is_writable
        True

        >>> host.block_device("/dev/loop1").is_writable
        False
        """
        mode = self._data["rw_mode"]
        if mode == "rw":
            return True
        if mode == "ro":
            return False
        raise ValueError("Unexpected value for rw: {}".format(mode))

    @property
    def ra(self):
        """Return Read Ahead for the device in 512-bytes sectors.

        >>> host.block_device("/dev/sda").ra
        256
        """
        return self._data["read_ahead"]

    @property
    def zoned(self):
        """Return Zoned Block Device flag

        >>> host.block_device("/dev/sda").zoned
        True
        """
        return "none" != self._data["zoned_type"]

    @property
    def zoned_type(self):
        """Return Zoned Block Device type

        >>> host.block_device("/dev/sda").zoned_type
        host-managed
        """
        return self._data["zoned_type"]

    def get_zoned_param(self, param_name):
        """Return Zoned Block Device related parameter

         >>> host.block_device("/dev/sda").get_zoned_param[chunk_sectors]
        """
        if param_name in [ "type", "chunk_sectors", "nr_zones", "zone_append_max_bytes", "max_open_zones", "max_active_zones" ]:
            return self._data[ "zoned_%s" % param_name ]
        else:
            return None

    def kernel_version_ge (self, major_wanted, minor_wanted):
        """Check if Linux version is greater or equal; TODO: Move to Host.

         >>> host.block_device("/dev/sda").kernel_version_ge(5, 15)
         True
        """
        kernel = self._host.sysctl("kernel.osrelease") # "ex. 5.15.0-52-generic"
        (major, minor) = re.findall(r'^(\d+)\.(\d+)\.', kernel)[0]
        return (int(major) >= major_wanted) and (int(minor) >= minor_wanted)

    @classmethod
    def get_module_class(cls, host):
        if host.system_info.type == "linux":
            return LinuxBlockDevice
        raise NotImplementedError

    def __repr__(self):
        return "<BlockDevice(path={})>".format(self.device)


class LinuxBlockDevice(BlockDevice):
    @cached_property
    def _data(self):
        header = ["RO", "RA", "SSZ", "BSZ", "StartSec", "Size", "Device"]
        command = "blockdev  --report %s"
        blockdev = self.run(command, self.device)
        if blockdev.rc != 0 or blockdev.stderr:
            raise RuntimeError("Failed to gather data: {}".format(blockdev.stderr))
        output = blockdev.stdout.splitlines()
        if len(output) < 2:
            raise RuntimeError("No data from {}".format(self.device))
        if output[0].split() != header:
            raise RuntimeError("Unknown output of blockdev: {}".format(output[0]))
        fields = output[1].split()
        zoned_type = "none"
        zoned_chunk_sectors = "none"
        zoned_nr_zones = "none"
        zoned_zone_append_max_bytes = "none"
        zoned_cmd = "cat %s"
        cmd_args = "/sys/block/%s/queue/zoned" % self.device
        try:
            zoned_type = self.check_output(zoned_cmd, cmd_args)
        except AttributeError as error:
            zoned_type = "none"
        if zoned_type:
            cmd_args = "/sys/block/%s/queue/chunk_sectors" % self.device
            try:
                zoned_chunk_sectors = self.check_output(zoned_cmd, cmd_args)
            except AttributeError as error:
                pass
            if self.kernel_version_ge(4, 20):
                try:
                    cmd_args = "/sys/block/%s/queue/nr_zones" % self.device
                    zoned_nr_zones = self.check_output(zoned_cmd, cmd_args)
                except AttributeError as error:
                    pass
            if self.kernel_version_ge(5, 8):
                try:
                    cmd_args = "/sys/block/%s/queue/zone_append_max_bytes" % self.device
                    zoned_zone_append_max_bytes = self.check_output(zoned_cmd, cmd_args)
                except AttributeError as error:
                    pass
            if self.kernel_version_ge(5, 9):
                try:
                    cmd_args = "/sys/block/%s/queue/max_open_zones" % self.device
                    zoned_max_open_zones = self.check_output(zoned_cmd, cmd_args)
                except AttributeError as error:
                    pass
                try:
                    cmd_args = "/sys/block/%s/queue/max_active_zones" % self.device
                    zoned_max_active_zones = self.check_output(zoned_cmd, cmd_args)
                except AttributeError as error:
                    pass
        return {
            "rw_mode": str(fields[0]),
            "read_ahead": int(fields[1]),
            "sector_size": int(fields[2]),
            "block_size": int(fields[3]),
            "start_sector": int(fields[4]),
            "size": int(fields[5]),
            "zoned_type": str(zoned_type),
            "zoned_chunk_sectors": str(zoned_chunk_sectors),
            "zoned_nr_zones": str(zoned_nr_zones),
            "zone_append_max_bytes": str(zoned_zone_append_max_bytes),
            "max_open_zones": str(zoned_max_open_zones),
            "max_actives_zones": str(zoned_max_active_zones),
        }
