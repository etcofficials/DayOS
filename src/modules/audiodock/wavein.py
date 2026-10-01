"""Microphone level meter and short test recordings through the winmm waveIn API.

Audio is captured only while the user has the meter or a test recording running.
Samples stay in memory: the meter keeps nothing, and a test recording (at most
:data:`MAX_TEST_SECONDS`) is held only until the user plays it back or leaves.
Nothing is written to disk or sent anywhere.
"""

from __future__ import annotations

import ctypes
import io
import logging
import math
import struct
import sys
import wave
from ctypes import POINTER, Structure, byref, c_char, c_uint, c_ulong, c_ushort, c_void_p
from ctypes import wintypes

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
RATE = 16000
BUFFER_MS = 50
BUFFERS = 8
MAX_TEST_SECONDS = 10
WAVE_MAPPER = 0xFFFFFFFF
WHDR_DONE = 0x1
CALLBACK_NULL = 0
DRV_QUERYFUNCTIONINSTANCEID = 0x0811
DRV_QUERYFUNCTIONINSTANCEIDSIZE = 0x0812
MMSYSERR_ALLOCATED = 4
MMSYSERR_BADDEVICEID = 2
MMSYSERR_NODRIVER = 6

ERRORS = {
    MMSYSERR_ALLOCATED: "The microphone is in use by another program that doesn't allow sharing.",
    MMSYSERR_BADDEVICEID: "That microphone is no longer available. Refresh the device list.",
    MMSYSERR_NODRIVER: "Windows has no working driver for that microphone.",
}


class WAVEFORMATEX(Structure):
    _pack_ = 1
    _fields_ = [("wFormatTag", c_ushort), ("nChannels", c_ushort), ("nSamplesPerSec", c_ulong),
                ("nAvgBytesPerSec", c_ulong), ("nBlockAlign", c_ushort), ("wBitsPerSample", c_ushort),
                ("cbSize", c_ushort)]


class WAVEHDR(Structure):
    _fields_ = [("lpData", POINTER(c_char)), ("dwBufferLength", c_ulong), ("dwBytesRecorded", c_ulong),
                ("dwUser", ctypes.c_size_t), ("dwFlags", c_ulong), ("dwLoops", c_ulong),
                ("lpNext", c_void_p), ("reserved", ctypes.c_size_t)]


class WAVEINCAPSW(Structure):
    _fields_ = [("wMid", c_ushort), ("wPid", c_ushort), ("vDriverVersion", c_uint),
                ("szPname", wintypes.WCHAR * 32), ("dwFormats", c_ulong), ("wChannels", c_ushort),
                ("wReserved1", c_ushort)]


class MicError(RuntimeError):
    pass


_configured = False


def _winmm():
    """winmm with exact argument types (handles and DWORD_PTR values are pointer-sized)."""
    global _configured
    winmm = ctypes.windll.winmm
    if not _configured:
        size_t = ctypes.c_size_t
        winmm.waveInGetNumDevs.argtypes = []
        winmm.waveInGetNumDevs.restype = c_uint
        winmm.waveInMessage.argtypes = [c_void_p, c_uint, size_t, size_t]
        winmm.waveInOpen.argtypes = [POINTER(c_void_p), c_uint, POINTER(WAVEFORMATEX), size_t, size_t, c_ulong]
        for name in ("waveInPrepareHeader", "waveInUnprepareHeader", "waveInAddBuffer"):
            getattr(winmm, name).argtypes = [c_void_p, POINTER(WAVEHDR), c_uint]
        for name in ("waveInStart", "waveInReset", "waveInClose"):
            getattr(winmm, name).argtypes = [c_void_p]
        for name in ("waveInMessage", "waveInOpen", "waveInPrepareHeader", "waveInUnprepareHeader",
                     "waveInAddBuffer", "waveInStart", "waveInReset", "waveInClose"):
            getattr(winmm, name).restype = c_uint
        _configured = True
    return winmm


def wavein_endpoints() -> dict[str, int]:
    """Map Core Audio endpoint IDs to waveIn device numbers."""
    if not IS_WINDOWS:
        return {}
    winmm = _winmm()
    out: dict[str, int] = {}
    for dev in range(int(winmm.waveInGetNumDevs())):
        size = c_ulong(0)
        handle = c_void_p(dev)
        result = winmm.waveInMessage(handle, DRV_QUERYFUNCTIONINSTANCEIDSIZE, ctypes.addressof(size), 0)
        if result != 0 or not size.value:
            continue
        buf = ctypes.create_unicode_buffer(size.value // 2 + 1)
        if winmm.waveInMessage(handle, DRV_QUERYFUNCTIONINSTANCEID, ctypes.addressof(buf), size.value) == 0:
            out[buf.value] = dev
    return out


def level_db(samples: bytes) -> tuple[float, float]:
    """(peak, RMS) of 16-bit mono PCM in dBFS (-90 for silence)."""
    n = len(samples) // 2
    if n == 0:
        return -90.0, -90.0
    values = struct.unpack(f"<{n}h", samples[: n * 2])
    peak = max(abs(v) for v in values) / 32768.0
    rms = math.sqrt(sum(v * v for v in values) / n) / 32768.0
    to_db = (lambda x: max(-90.0, 20 * math.log10(x)) if x > 0 else -90.0)
    return to_db(peak), to_db(rms)


def to_wav(pcm: bytes, rate: int = RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


class MicCapture:
    """Captures 16-bit mono audio from one waveIn device. Call :meth:`poll` regularly
    (e.g. from a QTimer); it returns the newest level and, when recording, keeps the samples."""

    def __init__(self, device: int = WAVE_MAPPER, rate: int = RATE) -> None:
        if not IS_WINDOWS:
            raise MicError("Microphone testing is only available on Windows.")
        self.device = device
        self.rate = rate
        self.handle = c_void_p()
        self.headers: list[WAVEHDR] = []
        self.buffers: list = []
        self.recording: bytearray | None = None
        self.peak_db = -90.0
        self.rms_db = -90.0
        self.loudest_db = -90.0
        self._open = False

    def start(self) -> None:
        winmm = _winmm()
        fmt = WAVEFORMATEX(1, 1, self.rate, self.rate * 2, 2, 16, 0)
        result = winmm.waveInOpen(byref(self.handle), self.device, byref(fmt), 0, 0, CALLBACK_NULL)
        if result != 0:
            raise MicError(ERRORS.get(result, f"Windows couldn't open the microphone (error {result}). Check that "
                                              "microphone access is allowed in Settings → Privacy & security → "
                                              "Microphone."))
        self._open = True
        size = self.rate * 2 * BUFFER_MS // 1000
        try:
            for _ in range(BUFFERS):
                data = ctypes.create_string_buffer(size)
                hdr = WAVEHDR()
                hdr.lpData = ctypes.cast(data, POINTER(c_char))
                hdr.dwBufferLength = size
                self._check(winmm.waveInPrepareHeader(self.handle, byref(hdr), ctypes.sizeof(WAVEHDR)))
                self._check(winmm.waveInAddBuffer(self.handle, byref(hdr), ctypes.sizeof(WAVEHDR)))
                self.headers.append(hdr)
                self.buffers.append(data)
            self._check(winmm.waveInStart(self.handle))
        except MicError:
            self.stop()
            raise

    @staticmethod
    def _check(result: int) -> None:
        if result != 0:
            raise MicError(ERRORS.get(result, f"The microphone stopped responding (error {result})."))

    def poll(self) -> float:
        """Collect finished buffers; returns the latest peak level in dBFS."""
        if not self._open:
            return -90.0
        winmm = _winmm()
        for hdr, data in zip(self.headers, self.buffers):
            if hdr.dwFlags & WHDR_DONE:
                chunk = data.raw[: hdr.dwBytesRecorded]
                if chunk:
                    self.peak_db, self.rms_db = level_db(chunk)
                    self.loudest_db = max(self.loudest_db, self.peak_db)
                    if self.recording is not None and len(self.recording) < self.rate * 2 * MAX_TEST_SECONDS:
                        self.recording.extend(chunk)
                hdr.dwFlags &= ~WHDR_DONE
                hdr.dwBytesRecorded = 0
                winmm.waveInAddBuffer(self.handle, byref(hdr), ctypes.sizeof(WAVEHDR))
        return self.peak_db

    def start_recording(self) -> None:
        self.recording = bytearray()

    def take_recording(self) -> bytes:
        data = bytes(self.recording or b"")
        self.recording = None
        return data

    @property
    def recorded_seconds(self) -> float:
        return len(self.recording) / (self.rate * 2) if self.recording is not None else 0.0

    def stop(self) -> None:
        if not self._open:
            return
        winmm = _winmm()
        winmm.waveInReset(self.handle)
        for hdr in self.headers:
            winmm.waveInUnprepareHeader(self.handle, byref(hdr), ctypes.sizeof(WAVEHDR))
        winmm.waveInClose(self.handle)
        self._open = False
        self.headers.clear()
        self.buffers.clear()


def play_wav(data: bytes) -> None:
    """Play WAV bytes on the default output (blocking: call it from a worker thread)."""
    import winsound

    winsound.PlaySound(data, winsound.SND_MEMORY | winsound.SND_NODEFAULT)


def stop_playback() -> None:
    if IS_WINDOWS:
        import winsound

        winsound.PlaySound(None, 0)
