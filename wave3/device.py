"""libusb transport for the Wave:3 vendor control interface.

Control transfers only, on endpoint 0. Interface 3 is never claimed and
no kernel driver is detached, so the audio streams are never interrupted.
"""

import ctypes
import ctypes.util
import threading
from dataclasses import dataclass, field as dc_field

from . import protocol as p

LIBUSB_ERROR_ACCESS = -3
LIBUSB_ERROR_NO_DEVICE = -4


def _load():
    lib = ctypes.CDLL(ctypes.util.find_library("usb-1.0") or "libusb-1.0.so.0")
    lib.libusb_init.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
    lib.libusb_init.restype = ctypes.c_int
    lib.libusb_exit.argtypes = [ctypes.c_void_p]
    lib.libusb_open_device_with_vid_pid.argtypes = [
        ctypes.c_void_p, ctypes.c_uint16, ctypes.c_uint16
    ]
    lib.libusb_open_device_with_vid_pid.restype = ctypes.c_void_p
    lib.libusb_close.argtypes = [ctypes.c_void_p]
    lib.libusb_close.restype = None
    lib.libusb_control_transfer.argtypes = [
        ctypes.c_void_p, ctypes.c_uint8, ctypes.c_uint8,
        ctypes.c_uint16, ctypes.c_uint16,
        ctypes.POINTER(ctypes.c_ubyte), ctypes.c_uint16, ctypes.c_uint,
    ]
    lib.libusb_control_transfer.restype = ctypes.c_int
    return lib


_lib = _load()
_ctx = ctypes.c_void_p()
_lib.libusb_init(ctypes.byref(_ctx))


class DeviceError(RuntimeError):
    pass


class PermissionError_(DeviceError):
    pass


class GuardViolation(DeviceError):
    """A write disturbed bytes outside the field it targeted.

    Raised only after the original block has been written back. Carries
    the evidence so the caller can report exactly which offsets moved.
    """

    def __init__(self, field, offenders, before, expected, actual, rolled_back):
        self.field = field
        self.offenders = offenders
        self.before = bytes(before)
        self.expected = bytes(expected)
        self.actual = bytes(actual)
        self.rolled_back = rolled_back
        detail = ", ".join(
            f"[{i}] {before[i]:02x} -> {actual[i]:02x}" for i in offenders
        )
        state = "reverted" if rolled_back else "REVERT FAILED"
        super().__init__(f"write to {field.path} disturbed {detail}; {state}")


@dataclass
class WriteResult:
    field: object
    before: bytes
    actual: bytes
    normalized: list = dc_field(default_factory=list)

    @property
    def changed(self):
        return self.before != self.actual


class Wave3:
    def __init__(self):
        self._handle = None
        self._lock = threading.Lock()
        self._txn = threading.RLock()

    @property
    def connected(self):
        return self._handle is not None

    def open(self):
        handle = _lib.libusb_open_device_with_vid_pid(_ctx, p.VENDOR_ID, p.PRODUCT_ID)
        if not handle:
            raise DeviceError("Wave:3 not found on USB")
        self._handle = handle

    def close(self):
        if self._handle:
            _lib.libusb_close(self._handle)
            self._handle = None

    def _read(self, selector, length):
        buf = (ctypes.c_ubyte * length)()
        with self._lock:
            n = _lib.libusb_control_transfer(
                self._handle, p.RT_CLASS_IN, p.BREQUEST_READ,
                selector, p.WINDEX, buf, length, 1000,
            )
        if n == LIBUSB_ERROR_ACCESS:
            raise PermissionError_("permission denied on USB device")
        if n == LIBUSB_ERROR_NO_DEVICE:
            raise DeviceError("device disconnected")
        if n < 0:
            raise DeviceError(f"control read failed (libusb {n})")
        return bytearray(buf[:n])

    def _write(self, selector, data):
        payload = bytes(data)
        buf = (ctypes.c_ubyte * len(payload))(*payload)
        with self._lock:
            n = _lib.libusb_control_transfer(
                self._handle, p.RT_CLASS_OUT, p.BREQUEST_WRITE,
                selector, p.WINDEX, buf, len(payload), 1000,
            )
        if n == LIBUSB_ERROR_ACCESS:
            raise PermissionError_("permission denied on USB device")
        if n < 0:
            raise DeviceError(f"control write failed (libusb {n})")

    def read_config(self):
        return self._read(p.SEL_CONFIG, p.CONFIG_LEN)

    def write_config(self, block):
        if len(block) != p.CONFIG_LEN:
            raise ValueError(f"config block must be {p.CONFIG_LEN} bytes")
        self._write(p.SEL_CONFIG, block)

    def read_status(self):
        return p.decode_status(self._read(p.SEL_STATUS, p.STATUS_LEN))

    def read_version(self):
        return p.decode_version(self._read(p.SEL_VERSION, 64))

    def set_field(self, field, value):
        """Read-modify-write one field, then prove nothing else moved.

        The field map for offsets 5, 6, 9, 10, 12, 13, 14 and 15 comes from
        static analysis rather than observation, so every write is treated
        as a transaction: read back, compare against the intended block, and
        restore the original if any byte outside the target field changed.

        Bytes inside the target field are allowed to differ from what was
        requested; firmware clamps and quantises (direct_monitor steps by 5,
        gain by its detent size). Those are reported as normalisation.
        """
        with self._txn:
            before = self.read_config()
            expected = p.encode_field(field, before, value)
            if expected == before:
                return WriteResult(field, bytes(before), bytes(before))

            self.write_config(expected)
            actual = self.read_config()

            own = set(range(field.offset, field.offset + field.size))
            offenders = [
                i for i in range(p.CONFIG_LEN)
                if actual[i] != expected[i] and i not in own
            ]

            if offenders:
                rolled_back = False
                try:
                    self.write_config(before)
                    rolled_back = self.read_config() == before
                except DeviceError:
                    rolled_back = False
                raise GuardViolation(field, offenders, before, expected, actual, rolled_back)

            normalized = [i for i in sorted(own) if actual[i] != expected[i]]
            return WriteResult(field, bytes(before), bytes(actual), normalized)
