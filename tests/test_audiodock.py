"""AudioDock: device listing, profiles and the microphone check — without touching real devices.

Switching defaults, volume changes and recording are tested against stand-ins, so running
the tests never changes this computer's audio setup or opens its microphone.
"""

import ctypes
import os
import struct
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.modules.audiodock import wavein  # noqa: E402
from src.modules.audiodock.coreaudio import (  # noqa: E402
    CAPTURE, COMMUNICATIONS, CONSOLE, MULTIMEDIA, RENDER, STATE_ACTIVE, STATE_UNPLUGGED, AudioDevice,
    AudioUnavailable, parse_wave_format,
)
from src.modules.audiodock.service import ProfileRepository, apply_profile  # noqa: E402
from src.services.dates import ValidationError  # noqa: E402
from tests.helpers import TempHomeTestCase  # noqa: E402

app = QApplication.instance() or QApplication([])


def pump(ms: int = 30) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class FakeAudio:
    def __init__(self, refuse_switch: bool = False) -> None:
        self.refuse_switch = refuse_switch
        self.list = {
            CAPTURE: [AudioDevice("mic-a", "Desk Mic", CAPTURE, STATE_ACTIVE, sample_rate=48000, channels=1, bits=24),
                      AudioDevice("mic-b", "Headset Mic", CAPTURE, STATE_ACTIVE),
                      AudioDevice("mic-c", "Old Webcam", CAPTURE, STATE_UNPLUGGED)],
            RENDER: [AudioDevice("spk-a", "Speakers", RENDER, STATE_ACTIVE),
                     AudioDevice("spk-b", "Headphones", RENDER, STATE_ACTIVE)],
        }
        self.defaults = {(CAPTURE, r): "mic-a" for r in (0, 1, 2)} | {(RENDER, r): "spk-a" for r in (0, 1, 2)}
        self.volume = {"mic-a": (0.5, False), "mic-b": (0.7, False), "spk-a": (0.3, False), "spk-b": (1.0, True)}
        self.calls: list = []

    def devices(self, flow):
        return list(self.list[flow])

    def default_id(self, flow, role=CONSOLE):
        return self.defaults.get((flow, role))

    def set_default(self, device_id, flow, roles=(CONSOLE, MULTIMEDIA)):
        self.calls.append(("default", device_id, tuple(roles)))
        if self.refuse_switch:
            return False
        for r in roles:
            self.defaults[(flow, r)] = device_id
        return True

    def get_volume(self, device_id):
        return self.volume[device_id]

    def set_volume(self, device_id, level):
        self.calls.append(("volume", device_id, round(level, 2)))
        self.volume[device_id] = (level, self.volume[device_id][1])

    def set_mute(self, device_id, muted):
        self.calls.append(("mute", device_id, muted))
        self.volume[device_id] = (self.volume[device_id][0], muted)


class AudioDataTests(TempHomeTestCase):
    def test_starter_profiles_and_validation(self):
        repo = ProfileRepository(self.ctx.db)
        self.assertEqual([p.kind for p in repo.list()], ["recording", "voiceover", "obs", "meeting"])
        self.assertTrue(all(p.input_id == "" for p in repo.list()))
        with self.assertRaises(ValidationError):
            repo.save(None, name="recording")  # names are unique, case-insensitively
        with self.assertRaises(ValidationError):
            repo.save(None, name="Loud", input_volume=150)
        pid = repo.save(None, name="Podcast", kind="recording", input_id="mic-b", input_name="Headset Mic",
                        input_volume=65)
        self.assertEqual(repo.get(pid).input_volume, 65)

    def test_apply_profile_switches_verifies_and_reports(self):
        fake = FakeAudio()
        repo = ProfileRepository(self.ctx.db)
        meeting = next(p for p in repo.list() if p.kind == "meeting")
        repo.save(meeting.id, name=meeting.name, kind="meeting", input_id="mic-b", input_name="Headset Mic",
                  output_id="spk-b", output_name="Headphones", communications=True, input_volume=80,
                  notes=meeting.notes)
        ok, messages = apply_profile(fake, repo.get(meeting.id))
        self.assertTrue(ok, messages)
        self.assertIn(("default", "mic-b", (CONSOLE, MULTIMEDIA, COMMUNICATIONS)), fake.calls)
        self.assertEqual(fake.default_id(RENDER, COMMUNICATIONS), "spk-b")
        self.assertIn(("volume", "mic-b", 0.8), fake.calls)
        ok, messages = apply_profile(FakeAudio(refuse_switch=True), repo.get(meeting.id))
        self.assertFalse(ok)
        self.assertTrue(any("Sound settings" in m for m in messages))
        pid = repo.save(None, name="Webcam", input_id="mic-c", input_name="Old Webcam")
        ok, messages = apply_profile(fake, repo.get(pid))
        self.assertFalse(ok)
        self.assertIn("unplugged", messages[0])

    def test_wave_format_and_levels(self):
        blob = struct.pack("<HHIIHHH", 0xFFFE, 2, 48000, 48000 * 8, 8, 32, 22) + struct.pack("<H", 24) + b"\0" * 20
        self.assertEqual(parse_wave_format(blob), (48000, 2, 24))
        self.assertEqual(parse_wave_format(struct.pack("<HHIIHH", 1, 1, 44100, 88200, 2, 16)), (44100, 1, 16))
        full = struct.pack("<4h", 32767, -32768, 0, 0)
        peak, rms = wavein.level_db(full)
        self.assertAlmostEqual(peak, 0.0, places=1)
        self.assertLess(rms, peak)
        self.assertEqual(wavein.to_wav(b"\0\0" * 4)[:4], b"RIFF")

    @unittest.skipUnless(os.name == "nt", "Windows only")
    def test_real_core_audio_listing_is_read_only_and_safe(self):
        from src.modules.audiodock.coreaudio import CoreAudio

        try:
            audio = CoreAudio()
        except AudioUnavailable:
            self.skipTest("Windows audio service not available")
        try:
            for flow in (CAPTURE, RENDER):
                devices = audio.devices(flow)
                self.assertTrue(all(d.id and d.name for d in devices))
                default = audio.default_id(flow)
                if default:
                    self.assertIn(default, [d.id for d in devices])
        finally:
            audio.close()


class FakeWinmm:
    """Stands in for winmm: buffers are filled by the test instead of a microphone."""

    def __init__(self) -> None:
        self.headers = []
        self.started = self.closed = False

    def waveInOpen(self, handle_ref, device, fmt_ref, cb, inst, flags):  # noqa: N802
        handle_ref._obj.value = 1234
        self.format = fmt_ref._obj
        return 0

    def waveInPrepareHeader(self, handle, hdr_ref, size):  # noqa: N802
        return 0

    def waveInAddBuffer(self, handle, hdr_ref, size):  # noqa: N802
        if hdr_ref._obj not in self.headers:
            self.headers.append(hdr_ref._obj)
        return 0

    def waveInStart(self, handle):  # noqa: N802
        self.started = True
        return 0

    def waveInReset(self, handle):  # noqa: N802
        return 0

    def waveInUnprepareHeader(self, handle, hdr_ref, size):  # noqa: N802
        return 0

    def waveInClose(self, handle):  # noqa: N802
        self.closed = True
        return 0

    def fill(self, samples: bytes) -> None:
        for hdr in self.headers:
            if not hdr.dwFlags & wavein.WHDR_DONE:
                ctypes.memmove(hdr.lpData, samples, len(samples))
                hdr.dwBytesRecorded = len(samples)
                hdr.dwFlags |= wavein.WHDR_DONE
                return


class MicCaptureTests(unittest.TestCase):
    def test_meter_and_recording_stay_in_memory(self):
        fake = FakeWinmm()
        with mock.patch.object(wavein, "_winmm", return_value=fake):
            cap = wavein.MicCapture(0)
            cap.start()
            self.assertTrue(fake.started)
            self.assertEqual((fake.format.nSamplesPerSec, fake.format.wBitsPerSample), (wavein.RATE, 16))
            loud = struct.pack("<4h", 16000, -16000, 16000, -16000)
            fake.fill(loud)
            peak = cap.poll()
            self.assertGreater(peak, -7)
            cap.start_recording()
            fake.fill(loud)
            cap.poll()
            self.assertEqual(cap.take_recording(), loud)
            fake.fill(loud)
            cap.poll()
            self.assertIsNone(cap.recording)  # nothing kept outside an explicit test recording
            cap.stop()
            self.assertTrue(fake.closed)

    def test_open_errors_are_explained(self):
        fake = FakeWinmm()
        fake.waveInOpen = lambda *a: wavein.MMSYSERR_ALLOCATED
        with mock.patch.object(wavein, "_winmm", return_value=fake):
            with self.assertRaises(wavein.MicError) as err:
                wavein.MicCapture(0).start()
        self.assertIn("in use", str(err.exception))


class AudioDockUiTests(TempHomeTestCase):
    def open_page(self, factory):
        from src.ui.main_window import MainWindow
        from src.ui.theme import theme

        theme.set_asset_dir(self.paths.cache_dir)
        theme.apply("paper")
        self.ctx.settings.set("capture.global", False)
        self.ctx.services["audiodock.backend"] = factory
        self.window = MainWindow(self.ctx)
        self.window.show()
        self.window.navigate("audiodock")
        pump(20)
        return self.window.page("audiodock")

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        pump(20)
        super().tearDown()

    def test_devices_defaults_volume_and_profiles(self):
        fake = FakeAudio()
        page = self.open_page(lambda: fake)
        self.assertFalse(page.error_view.isVisibleTo(page))
        self.assertEqual(page.mic_combo.count(), 2)  # unplugged device isn't offered
        page.make_default(fake.list[RENDER][1])
        self.assertEqual(fake.default_id(RENDER), "spk-b")
        page.set_volume(fake.list[CAPTURE][0], 40)
        self.assertIn(("volume", "mic-a", 0.4), fake.calls)
        page.set_mute(fake.list[RENDER][1], False)
        self.assertIn(("mute", "spk-b", False), fake.calls)
        from src.modules.audiodock.ui.page import ProfileDialog

        dlg = ProfileDialog(page)
        dlg.name.setText("Late-night stream")
        dlg.input.setCurrentIndex(dlg.input.findData("mic-b"))
        dlg._on_save()
        self.assertFalse(dlg.error.isVisibleTo(dlg))
        profile = page.profiles.get(dlg.saved_id)
        self.assertEqual((profile.input_id, profile.input_name, profile.output_id), ("mic-b", "Headset Mic", ""))
        with mock.patch("src.modules.audiodock.ui.page.show_info") as info:
            page.apply(profile)
            info.assert_called_once()
        self.assertEqual(fake.default_id(CAPTURE), "mic-b")

    def test_missing_audio_is_explained_and_dayos_keeps_working(self):
        def broken():
            raise AudioUnavailable("Windows audio service is not available.")

        page = self.open_page(broken)
        self.assertTrue(page.error_view.isVisibleTo(page))
        self.assertIn("not available", page.error_reason.text())
        self.window.navigate("today")
        self.assertIs(self.window.current_page(), self.window.page("today"))

    def test_meter_stops_when_leaving_the_page(self):
        fake = FakeAudio()
        page = self.open_page(lambda: fake)
        page.capture = mock.Mock(recording=None, loudest_db=-20.0)
        page.capture.poll.return_value = -20.0
        page._timer.start()
        self.window.navigate("today")
        pump(10)
        self.assertIsNone(page.capture)
        self.assertFalse(page._timer.isActive())


if __name__ == "__main__":
    unittest.main()
