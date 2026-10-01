"""Windows Core Audio (MMDevice API) through ctypes COM calls — no extra packages.

What this module can do, and nothing more:

* list input (capture) and output (render) endpoints with name, state and format;
* read the default device for each role;
* read and change an endpoint's master volume and mute;
* make an endpoint the default device. Windows has no documented API for this, so
  :meth:`CoreAudio.set_default` uses the ``IPolicyConfig`` interface that the Windows
  Sound control panel itself uses, then reads the default back to confirm it took
  effect. If it didn't, the caller is told so (and can open Sound settings).

It does not route audio between apps, apply effects or change per-app audio.
All calls run on the UI thread (COM is already initialised there by Qt).
"""

from __future__ import annotations

import ctypes
import logging
import struct
import sys
import uuid
from ctypes import POINTER, Structure, Union, byref, c_float, c_ubyte, c_ulong, c_ushort, c_void_p, c_wchar_p
from dataclasses import dataclass

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

RENDER, CAPTURE = 0, 1
CONSOLE, MULTIMEDIA, COMMUNICATIONS = 0, 1, 2
STATE_ACTIVE, STATE_DISABLED, STATE_NOTPRESENT, STATE_UNPLUGGED = 0x1, 0x2, 0x4, 0x8
STATE_ALL = 0xF
STATE_TEXT = {STATE_ACTIVE: "Ready", STATE_DISABLED: "Disabled in Windows", STATE_NOTPRESENT: "Not present",
              STATE_UNPLUGGED: "Unplugged"}
CLSCTX_ALL = 23
STGM_READ = 0
VT_LPWSTR, VT_BLOB = 31, 65
E_NOTFOUND = -2147023728  # 0x80070490


class AudioUnavailable(RuntimeError):
    """Core Audio could not be used (not Windows, or COM refused)."""


class GUID(Structure):
    _fields_ = [("Data1", c_ulong), ("Data2", c_ushort), ("Data3", c_ushort), ("Data4", c_ubyte * 8)]


def make_guid(text: str) -> GUID:
    u = uuid.UUID(text)
    g = GUID()
    g.Data1, g.Data2, g.Data3 = u.time_low, u.time_mid, u.time_hi_version
    for i, b in enumerate(u.bytes[8:]):
        g.Data4[i] = b
    return g


class PROPERTYKEY(Structure):
    _fields_ = [("fmtid", GUID), ("pid", c_ulong)]


class BLOB(Structure):
    _fields_ = [("cbSize", c_ulong), ("pBlobData", POINTER(c_ubyte))]


class _PVUnion(Union):
    _fields_ = [("pwszVal", c_wchar_p), ("blob", BLOB), ("ulVal", c_ulong), ("pad", c_ubyte * 16)]


class PROPVARIANT(Structure):
    _fields_ = [("vt", c_ushort), ("r1", c_ushort), ("r2", c_ushort), ("r3", c_ushort), ("u", _PVUnion)]


def _pkey(fmtid: str, pid: int) -> PROPERTYKEY:
    key = PROPERTYKEY()
    key.fmtid = make_guid(fmtid)
    key.pid = pid
    return key


CLSID_MMDeviceEnumerator = make_guid("BCDE0395-E52F-467C-8E3D-C4579291692E")
IID_IMMDeviceEnumerator = make_guid("A95664D2-9614-4F35-A746-DE8DB63617E6")
IID_IAudioEndpointVolume = make_guid("5CDF2C82-841E-4546-9722-0CF74078229A")
CLSID_PolicyConfigClient = make_guid("870AF99C-171D-4F9E-AF0D-E63DF40C2BC9")
IID_IPolicyConfig = make_guid("F8679F50-850A-41CF-9C72-430F290290C8")
PKEY_Device_FriendlyName = _pkey("A45C254E-DF1C-4EFD-8020-67D146A850E0", 14)
PKEY_Device_DeviceDesc = _pkey("A45C254E-DF1C-4EFD-8020-67D146A850E0", 2)
PKEY_DeviceInterface_FriendlyName = _pkey("026E516E-B814-414B-83CD-856D6FEF4822", 2)
PKEY_AudioEngine_DeviceFormat = _pkey("F19F064D-082C-4E27-BC73-6882A1BB8E4C", 0)


def _call(ptr: int, index: int, argtypes: tuple, *args):
    """Call method ``index`` of the COM interface at ``ptr`` (HRESULT failures raise OSError)."""
    vtable = ctypes.cast(c_void_p(ptr), POINTER(POINTER(c_void_p)))[0]
    proto = ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, *argtypes)
    return proto(vtable[index])(c_void_p(ptr), *args)


def _release(ptr: int | None) -> None:
    if ptr:
        vtable = ctypes.cast(c_void_p(ptr), POINTER(POINTER(c_void_p)))[0]
        ctypes.WINFUNCTYPE(c_ulong, c_void_p)(vtable[2])(c_void_p(ptr))


@dataclass
class AudioDevice:
    id: str
    name: str
    flow: int  # RENDER or CAPTURE
    state: int
    description: str = ""
    adapter: str = ""
    sample_rate: int = 0
    channels: int = 0
    bits: int = 0

    @property
    def active(self) -> bool:
        return self.state == STATE_ACTIVE

    @property
    def state_text(self) -> str:
        return STATE_TEXT.get(self.state, "Unknown")

    @property
    def format_text(self) -> str:
        if not self.sample_rate:
            return ""
        parts = [f"{self.sample_rate / 1000:g} kHz"]
        if self.bits:
            parts.append(f"{self.bits}-bit")
        if self.channels:
            parts.append({1: "mono", 2: "stereo"}.get(self.channels, f"{self.channels} channels"))
        return ", ".join(parts)


def parse_wave_format(data: bytes) -> tuple[int, int, int]:
    """(sample rate, channels, bits) from a WAVEFORMATEX / WAVEFORMATEXTENSIBLE blob."""
    if len(data) < 16:
        return 0, 0, 0
    tag, channels, rate, _avg, _align, bits = struct.unpack_from("<HHIIHH", data, 0)
    if tag == 0xFFFE and len(data) >= 20:  # WAVE_FORMAT_EXTENSIBLE: prefer the valid bits
        valid = struct.unpack_from("<H", data, 18)[0]
        bits = valid or bits
    return rate, channels, bits


class CoreAudio:
    def __init__(self) -> None:
        if not IS_WINDOWS:
            raise AudioUnavailable("Audio devices can only be managed on Windows.")
        self._ole32 = ctypes.windll.ole32
        self._ole32.CoInitializeEx(None, 0x2)  # already initialised by Qt on the UI thread: harmless
        self._enum = c_void_p()
        try:
            self._ole32.CoCreateInstance.restype = ctypes.HRESULT
            self._ole32.CoCreateInstance(byref(CLSID_MMDeviceEnumerator), None, CLSCTX_ALL,
                                         byref(IID_IMMDeviceEnumerator), byref(self._enum))
        except OSError as exc:
            raise AudioUnavailable(f"Windows audio service is not available ({exc}).") from None
        if not self._enum.value:
            raise AudioUnavailable("Windows audio service is not available.")

    def close(self) -> None:
        _release(self._enum.value)
        self._enum = c_void_p()

    # -- devices ------------------------------------------------------------------------
    def devices(self, flow: int, state_mask: int = STATE_ALL) -> list[AudioDevice]:
        collection = c_void_p()
        _call(self._enum.value, 3, (ctypes.c_int, c_ulong, POINTER(c_void_p)), flow, state_mask, byref(collection))
        out: list[AudioDevice] = []
        try:
            count = ctypes.c_uint()
            _call(collection.value, 3, (POINTER(ctypes.c_uint),), byref(count))
            for i in range(count.value):
                dev = c_void_p()
                _call(collection.value, 4, (ctypes.c_uint, POINTER(c_void_p)), i, byref(dev))
                try:
                    out.append(self._describe(dev.value, flow))
                except OSError:
                    log.debug("Skipping an audio endpoint that couldn't be read", exc_info=True)
                finally:
                    _release(dev.value)
        finally:
            _release(collection.value)
        return out

    def _device_id(self, dev: int) -> str:
        raw = c_void_p()
        _call(dev, 5, (POINTER(c_void_p),), byref(raw))
        try:
            return ctypes.wstring_at(raw.value)
        finally:
            self._ole32.CoTaskMemFree(raw)

    def _describe(self, dev: int, flow: int) -> AudioDevice:
        state = c_ulong()
        _call(dev, 6, (POINTER(c_ulong),), byref(state))
        device = AudioDevice(self._device_id(dev), "", flow, int(state.value))
        store = c_void_p()
        _call(dev, 4, (c_ulong, POINTER(c_void_p)), STGM_READ, byref(store))
        try:
            device.name = self._prop_text(store.value, PKEY_Device_FriendlyName) or "Audio device"
            device.description = self._prop_text(store.value, PKEY_Device_DeviceDesc)
            device.adapter = self._prop_text(store.value, PKEY_DeviceInterface_FriendlyName)
            blob = self._prop_blob(store.value, PKEY_AudioEngine_DeviceFormat)
            if blob:
                device.sample_rate, device.channels, device.bits = parse_wave_format(blob)
        finally:
            _release(store.value)
        return device

    def _prop(self, store: int, key: PROPERTYKEY) -> PROPVARIANT:
        pv = PROPVARIANT()
        _call(store, 5, (POINTER(PROPERTYKEY), POINTER(PROPVARIANT)), byref(key), byref(pv))
        return pv

    def _prop_text(self, store: int, key: PROPERTYKEY) -> str:
        try:
            pv = self._prop(store, key)
        except OSError:
            return ""
        try:
            return (pv.u.pwszVal or "") if pv.vt == VT_LPWSTR else ""
        finally:
            self._ole32.PropVariantClear(byref(pv))

    def _prop_blob(self, store: int, key: PROPERTYKEY) -> bytes:
        try:
            pv = self._prop(store, key)
        except OSError:
            return b""
        try:
            if pv.vt != VT_BLOB or not pv.u.blob.cbSize:
                return b""
            return ctypes.string_at(pv.u.blob.pBlobData, pv.u.blob.cbSize)
        finally:
            self._ole32.PropVariantClear(byref(pv))

    def default_id(self, flow: int, role: int = CONSOLE) -> str | None:
        dev = c_void_p()
        try:
            _call(self._enum.value, 4, (ctypes.c_int, ctypes.c_int, POINTER(c_void_p)), flow, role, byref(dev))
        except OSError:
            return None  # no default device of this kind
        try:
            return self._device_id(dev.value)
        finally:
            _release(dev.value)

    def _open(self, device_id: str) -> int:
        dev = c_void_p()
        _call(self._enum.value, 5, (c_wchar_p, POINTER(c_void_p)), device_id, byref(dev))
        return int(dev.value)

    # -- volume and mute ------------------------------------------------------------------
    def _volume(self, device_id: str) -> int:
        dev = self._open(device_id)
        try:
            vol = c_void_p()
            _call(dev, 3, (POINTER(GUID), c_ulong, c_void_p, POINTER(c_void_p)),
                  byref(IID_IAudioEndpointVolume), CLSCTX_ALL, None, byref(vol))
            return int(vol.value)
        finally:
            _release(dev)

    def get_volume(self, device_id: str) -> tuple[float, bool]:
        """(master volume 0..1, muted)."""
        vol = self._volume(device_id)
        try:
            level = c_float()
            _call(vol, 9, (POINTER(c_float),), byref(level))
            muted = ctypes.c_int()
            _call(vol, 15, (POINTER(ctypes.c_int),), byref(muted))
            return float(level.value), bool(muted.value)
        finally:
            _release(vol)

    def set_volume(self, device_id: str, level: float) -> None:
        vol = self._volume(device_id)
        try:
            _call(vol, 7, (c_float, c_void_p), c_float(max(0.0, min(1.0, level))), None)
        finally:
            _release(vol)

    def set_mute(self, device_id: str, muted: bool) -> None:
        vol = self._volume(device_id)
        try:
            _call(vol, 14, (ctypes.c_int, c_void_p), int(bool(muted)), None)
        finally:
            _release(vol)

    # -- default device ------------------------------------------------------------------
    def set_default(self, device_id: str, flow: int, roles: tuple[int, ...] = (CONSOLE, MULTIMEDIA)) -> bool:
        """Make ``device_id`` the default for ``roles``; returns True only if Windows confirms it."""
        policy = c_void_p()
        try:
            self._ole32.CoCreateInstance(byref(CLSID_PolicyConfigClient), None, CLSCTX_ALL,
                                         byref(IID_IPolicyConfig), byref(policy))
        except OSError:
            log.info("IPolicyConfig is not available on this Windows version")
            return False
        try:
            for role in roles:
                _call(policy.value, 13, (c_wchar_p, ctypes.c_int), device_id, role)
        except OSError:
            log.info("Windows refused to change the default audio device", exc_info=True)
            return False
        finally:
            _release(policy.value)
        return all(self.default_id(flow, role) == device_id for role in roles)
