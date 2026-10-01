"""AudioDock page: Windows input/output devices, defaults, a microphone test and audio profiles.

AudioDock chooses Windows' default devices and tests microphones. It does not route
audio between apps, apply effects or change other apps' settings — the page says so.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from src.modules.audiodock.coreaudio import CAPTURE, COMMUNICATIONS, CONSOLE, RENDER, AudioDevice, AudioUnavailable
from src.modules.audiodock.schema import PROFILE_KINDS
from src.modules.audiodock.service import ProfileRepository, apply_profile
from src.ui.pages.base import Page
from src.ui.widgets.common import (
    Card,
    EmptyState,
    FormDialog,
    PageHeader,
    button,
    chip,
    clear_layout,
    confirm,
    guarded,
    label,
    scroll_wrap,
    show_error,
    show_info,
    tool_button,
)
from src.ui.worker import run_in_background

SCOPE = ("AudioDock picks Windows' default microphone and speakers, adjusts their volume and tests your "
         "microphone. It doesn't route audio between apps, add effects or change other apps' settings.")
METER_FLOOR = -60


def make_backend(ctx):
    factory = ctx.services.get("audiodock.backend")
    if factory is not None:
        return factory()
    from src.modules.audiodock.coreaudio import CoreAudio

    return CoreAudio()


class ProfileDialog(FormDialog):
    def __init__(self, page: "AudioDockPage", profile=None) -> None:
        super().__init__("Edit profile" if profile else "New profile", page, "Save", 520)
        self.page = page
        self.profile = profile
        self.saved_id: int | None = None
        self.name = QLineEdit(profile.name if profile else "")
        self.name.setMaxLength(60)
        self.add_row("Name", self.name)
        self.kind = QComboBox()
        for key, text in PROFILE_KINDS.items():
            self.kind.addItem(text, key)
        self.kind.setCurrentIndex(max(0, self.kind.findData(profile.kind if profile else "custom")))
        self.add_row("Type", self.kind)
        self.input = self._device_combo(CAPTURE, profile.input_id if profile else "",
                                        profile.input_name if profile else "")
        self.add_row("Microphone", self.input)
        self.output = self._device_combo(RENDER, profile.output_id if profile else "",
                                         profile.output_name if profile else "")
        self.add_row("Speakers / headphones", self.output)
        self.comms = QCheckBox("Also use these as the communications devices (most call apps use them)")
        self.comms.setChecked(bool(profile.communications) if profile else False)
        self.add_row("", self.comms)
        vol_row = QHBoxLayout()
        self.set_volume = QCheckBox("Set microphone volume to")
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setAccessibleName("Microphone volume")
        self.volume_text = label("", "caption")
        self.volume.valueChanged.connect(lambda v: self.volume_text.setText(f"{v}%"))
        has_vol = profile is not None and profile.input_volume is not None
        self.set_volume.setChecked(has_vol)
        self.volume.setValue(profile.input_volume if has_vol else 80)
        vol_row.addWidget(self.set_volume)
        vol_row.addWidget(self.volume, 1)
        vol_row.addWidget(self.volume_text)
        self.add_row("", vol_row)
        self.notes = QPlainTextEdit(profile.notes if profile else "")
        self.notes.setPlaceholderText("Your checklist for this setup")
        self.notes.setFixedHeight(110)
        self.add_row("Checklist", self.notes)

    def _device_combo(self, flow: int, current_id: str, current_name: str) -> QComboBox:
        """Items carry the endpoint ID; display names are kept in ``self.names``."""
        if not hasattr(self, "names"):
            self.names: dict[str, str] = {}
        combo = QComboBox()
        combo.addItem("Leave as it is", "")
        for dev in self.page.devices.get(flow, []):
            if dev.active:
                combo.addItem(dev.name, dev.id)
                self.names[dev.id] = dev.name
        if current_id and combo.findData(current_id) < 0:
            combo.addItem(f"{current_name or 'Saved device'} (not connected)", current_id)
            self.names[current_id] = current_name
        combo.setCurrentIndex(max(0, combo.findData(current_id)))
        return combo

    def save(self) -> None:
        in_id, out_id = self.input.currentData() or "", self.output.currentData() or ""
        in_name, out_name = self.names.get(in_id, ""), self.names.get(out_id, "")
        self.saved_id = self.page.profiles.save(
            self.profile.id if self.profile else None, name=self.name.text(), kind=self.kind.currentData(),
            input_id=in_id, input_name=in_name, output_id=out_id, output_name=out_name,
            communications=self.comms.isChecked(),
            input_volume=self.volume.value() if self.set_volume.isChecked() else None,
            notes=self.notes.toPlainText())


class AudioDockPage(Page):
    domains = ("settings",)
    title = "AudioDock"

    def __init__(self, ctx, window) -> None:
        super().__init__(ctx, window)
        self.profiles = ProfileRepository(ctx.db)
        self.backend = None
        self.error = ""
        self.devices: dict[int, list[AudioDevice]] = {CAPTURE: [], RENDER: []}
        self.capture = None
        self.test_audio: bytes = b""
        self._recording_until = 0.0
        window.shutdown_hooks.append(self.stop_meter)

        header = PageHeader("AudioDock", "Your microphones and speakers, a quick microphone check, and profiles "
                                         "for recording, streaming and calls.", eyebrow="Audio")
        header.add_action(button("Sound settings", "ghost", "external", self.open_sound_settings,
                                 "Open Windows Sound settings"))
        header.add_action(button("Refresh", "soft", "refresh", self.reload_devices, "Look for devices again"))
        self.root.addWidget(header)
        self.root.addWidget(label(SCOPE, "caption", wrap=True))

        self.body_holder = QWidget()
        self.body = QVBoxLayout(self.body_holder)
        self.body.setContentsMargins(0, 0, 6, 0)
        self.body.setSpacing(14)
        self.root.addWidget(scroll_wrap(self.body_holder), 1)

        self.show_all = QCheckBox("Show unplugged and disabled devices")
        self.show_all.toggled.connect(lambda _v: self._fill_devices())
        self.out_card = Card("Speakers & headphones", "headphones")
        self.in_card = Card("Microphones", "mic")
        self.out_list = QVBoxLayout()
        self.in_list = QVBoxLayout()
        self.out_card.body.addLayout(self.out_list)
        self.in_card.body.addLayout(self.in_list)

        # microphone test
        self.mic_card = Card("Microphone check", "mic")
        row = QHBoxLayout()
        self.mic_combo = QComboBox()
        self.mic_combo.setAccessibleName("Microphone to test")
        row.addWidget(self.mic_combo, 1)
        self.meter_btn = button("Start meter", "primary", "play", self.toggle_meter)
        row.addWidget(self.meter_btn)
        self.mic_card.body.addLayout(row)
        self.meter = QProgressBar()
        self.meter.setRange(METER_FLOOR, 0)
        self.meter.setValue(METER_FLOOR)
        self.meter.setTextVisible(False)
        self.meter.setFixedHeight(10)
        self.meter.setAccessibleName("Input level")
        self.mic_card.body.addWidget(self.meter)
        self.level_text = label("The meter listens only while it's running. Nothing is saved.", "caption", wrap=True)
        self.mic_card.body.addWidget(self.level_text)
        rec_row = QHBoxLayout()
        self.record_btn = button("Record a 5-second test", "ghost", "mic", self.record_test)
        self.record_btn.setEnabled(False)
        rec_row.addWidget(self.record_btn)
        self.play_btn = button("Play it back", "ghost", "play", self.play_test)
        self.play_btn.setEnabled(False)
        rec_row.addWidget(self.play_btn)
        self.discard_btn = button("Discard", "link", on_click=self.discard_test)
        self.discard_btn.setEnabled(False)
        rec_row.addWidget(self.discard_btn)
        rec_row.addStretch(1)
        self.mic_card.body.addLayout(rec_row)
        self.mic_card.body.addWidget(label("Good levels: speaking normally peaks between −20 and −6 dB. A flat meter "
                                           "means the microphone is muted, the wrong one is chosen, or desktop apps "
                                           "aren't allowed to use it (Settings → Privacy & security → Microphone). "
                                           "Test recordings stay in memory and play on the default output.",
                                           "caption", wrap=True))

        self.profile_card = Card("Profiles", "routine")
        self.profile_box = QVBoxLayout()
        self.profile_card.body.addLayout(self.profile_box)
        prow = QHBoxLayout()
        prow.addWidget(button("New profile", "soft", "plus", self.new_profile))
        prow.addStretch(1)
        self.profile_card.body.addLayout(prow)

        self.trouble_card = Card("Troubleshooting details", "info")
        self.trouble_box = QVBoxLayout()
        self.trouble_card.body.addLayout(self.trouble_box)

        self.error_view = EmptyState("audio", "Audio devices aren't available", "",
                                     [("Refresh", self.reload_devices)])
        self.error_reason = label("", "muted", wrap=True)
        self.body.addWidget(self.error_view)
        self.body.addWidget(self.error_reason)
        for w in (self.show_all, self.out_card, self.in_card, self.mic_card, self.profile_card, self.trouble_card):
            self.body.addWidget(w)
        self.body.addStretch(1)
        self.error_view.hide()
        self.error_reason.hide()

        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)

    # -- devices ---------------------------------------------------------------------------
    def refresh(self) -> None:
        if self.backend is None and not self.error:
            self.reload_devices()
        else:
            self._fill_profiles()

    def reload_devices(self) -> None:
        self.error = ""
        try:
            if self.backend is None:
                self.backend = make_backend(self.ctx)
            self.devices = {CAPTURE: self.backend.devices(CAPTURE), RENDER: self.backend.devices(RENDER)}
        except (AudioUnavailable, OSError) as exc:
            self.backend = None
            self.error = str(exc) or "Windows audio isn't available."
            self.devices = {CAPTURE: [], RENDER: []}
        self._build()

    def _build(self) -> None:
        failed = bool(self.error)
        self.error_view.setVisible(failed)
        self.error_reason.setVisible(failed)
        for w in (self.show_all, self.out_card, self.in_card, self.mic_card, self.trouble_card):
            w.setVisible(not failed)
        if failed:
            self.error_reason.setText(f"{self.error} The rest of DayOS works normally. Try Refresh after connecting "
                                      "a device or restarting the Windows Audio service.")
        else:
            self._fill_devices()
        self._fill_profiles()

    def _defaults(self, flow: int) -> tuple[str | None, str | None]:
        if self.backend is None:
            return None, None
        return self.backend.default_id(flow, CONSOLE), self.backend.default_id(flow, COMMUNICATIONS)

    def _fill_devices(self) -> None:
        for flow, box in ((RENDER, self.out_list), (CAPTURE, self.in_list)):
            clear_layout(box)
            default, comms = self._defaults(flow)
            shown = [d for d in self.devices[flow] if d.active or self.show_all.isChecked()]
            if not shown:
                box.addWidget(label("No devices found." if flow == CAPTURE else "No output devices found.", "muted"))
            for dev in shown:
                box.addWidget(self._device_row(dev, dev.id == default, dev.id == comms))
        keep = self.mic_combo.currentData()
        self.mic_combo.clear()
        default_in = self._defaults(CAPTURE)[0]
        for dev in self.devices[CAPTURE]:
            if dev.active:
                self.mic_combo.addItem(dev.name + ("  (default)" if dev.id == default_in else ""), dev.id)
        index = self.mic_combo.findData(keep if keep else default_in)
        self.mic_combo.setCurrentIndex(max(0, index))
        self.meter_btn.setEnabled(self.mic_combo.count() > 0)
        self._fill_trouble()

    def _device_row(self, dev: AudioDevice, is_default: bool, is_comms: bool) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(3)
        top = QHBoxLayout()
        name = label(dev.name, "rowtitle")
        name.setWordWrap(True)
        top.addWidget(name, 1)
        if is_default:
            top.addWidget(chip("Default", "accent"))
        if is_comms and not is_default:
            top.addWidget(chip("Communications", "blue"))
        elif is_comms:
            top.addWidget(chip("Also for calls", "blue"))
        if not dev.active:
            top.addWidget(chip(dev.state_text, "warning"))
        lay.addLayout(top)
        details = " · ".join(x for x in (dev.adapter if dev.adapter and dev.adapter not in dev.name else "",
                                          dev.format_text) if x)
        if details:
            lay.addWidget(label(details, "caption", wrap=True))
        if dev.active:
            row = QHBoxLayout()
            try:
                volume, muted = self.backend.get_volume(dev.id)
            except OSError:
                volume, muted = None, False
            if volume is not None:
                mute = tool_button("pause-circle" if muted else "audio", "Unmute" if muted else "Mute",
                                   lambda d=dev, m=muted: self.set_mute(d, not m))
                mute.setCheckable(True)
                mute.setChecked(muted)
                row.addWidget(mute)
                slider = QSlider(Qt.Orientation.Horizontal)
                slider.setRange(0, 100)
                slider.setValue(round(volume * 100))
                slider.setAccessibleName(f"Volume of {dev.name}")
                slider.setMaximumWidth(260)
                value = label(f"{round(volume * 100)}%" + (" · muted" if muted else ""), "caption")
                slider.valueChanged.connect(lambda v, lab=value: lab.setText(f"{v}%"))
                slider.sliderReleased.connect(lambda s=slider, d=dev: self.set_volume(d, s.value()))
                row.addWidget(slider)
                row.addWidget(value)
            row.addStretch(1)
            if not is_default:
                row.addWidget(button("Make default", "soft", "check", lambda d=dev: self.make_default(d)))
            if dev.flow == CAPTURE:
                row.addWidget(button("Test", "link", "mic", lambda d=dev: self._choose_mic(d)))
            lay.addLayout(row)
        return w

    def make_default(self, dev: AudioDevice) -> None:
        try:
            ok = self.backend.set_default(dev.id, dev.flow)
        except OSError:
            ok = False
        if ok:
            self.toast(f"“{dev.name}” is now the default")
        else:
            show_error(self, "Windows didn't switch devices",
                       "This Windows version or device didn't accept the change. You can choose it in Windows "
                       "Sound settings instead.")
        self._fill_devices()

    def set_volume(self, dev: AudioDevice, value: int) -> None:
        try:
            self.backend.set_volume(dev.id, value / 100)
        except OSError:
            show_error(self, "Volume not changed", f"“{dev.name}” doesn't allow its volume to be changed here.")

    def set_mute(self, dev: AudioDevice, muted: bool) -> None:
        try:
            self.backend.set_mute(dev.id, muted)
        except OSError:
            show_error(self, "Mute not changed", f"“{dev.name}” doesn't allow muting here.")
        self._fill_devices()

    def open_sound_settings(self) -> None:
        QDesktopServices.openUrl(QUrl("ms-settings:sound"))

    # -- microphone check -----------------------------------------------------------------
    def _choose_mic(self, dev: AudioDevice) -> None:
        index = self.mic_combo.findData(dev.id)
        if index >= 0:
            self.stop_meter()
            self.mic_combo.setCurrentIndex(index)
            self.toggle_meter()

    def toggle_meter(self) -> None:
        if self.capture is not None:
            self.stop_meter()
            return
        from src.modules.audiodock import wavein

        device_id = self.mic_combo.currentData()
        try:
            mapping = wavein.wavein_endpoints()
            if device_id not in mapping:
                raise wavein.MicError("Windows doesn't offer this microphone for testing. Try Refresh.")
            capture = wavein.MicCapture(mapping[device_id])
            capture.start()
        except (wavein.MicError, OSError) as exc:
            show_error(self, "Microphone check unavailable", str(exc))
            return
        self.capture = capture
        self.meter_btn.setText("Stop meter")
        self.record_btn.setEnabled(True)
        self.mic_combo.setEnabled(False)
        self.level_text.setText("Listening… speak normally. Nothing is saved.")
        self._timer.start()

    def stop_meter(self) -> None:
        self._timer.stop()
        if self.capture is not None:
            try:
                self.capture.stop()
            except OSError:
                pass
            self.capture = None
        self._recording_until = 0.0
        self.meter_btn.setText("Start meter")
        self.record_btn.setEnabled(False)
        self.record_btn.setText("Record a 5-second test")
        self.mic_combo.setEnabled(True)
        self.meter.setValue(METER_FLOOR)

    def _tick(self) -> None:
        if self.capture is None:
            return
        try:
            peak = self.capture.poll()
        except OSError as exc:
            self.stop_meter()
            show_error(self, "The microphone stopped", str(exc))
            return
        self.meter.setValue(int(max(METER_FLOOR, min(0, peak))))
        if self.capture.recording is not None:
            seconds = self.capture.recorded_seconds
            self.record_btn.setText(f"Recording… {max(0.0, 5 - seconds):.0f} s")
            if seconds >= 5:
                self.test_audio = self.capture.take_recording()
                self.record_btn.setText("Record a 5-second test")
                self.play_btn.setEnabled(bool(self.test_audio))
                self.discard_btn.setEnabled(bool(self.test_audio))
                self.toast("Test recorded — play it back to hear yourself")
            return
        loudest = self.capture.loudest_db
        hint = ("Very quiet — move closer or raise the microphone volume." if loudest < -40 else
                "Loud — peaks near 0 dB can distort; lower the volume a little." if loudest > -3 else
                "Levels look good.")
        self.level_text.setText(f"Now {peak:.0f} dB · loudest {loudest:.0f} dB. {hint}")

    def record_test(self) -> None:
        if self.capture is None or self.capture.recording is not None:
            return
        self.discard_test()
        self.capture.start_recording()

    def play_test(self) -> None:
        if not self.test_audio:
            return
        from src.modules.audiodock import wavein

        data = wavein.to_wav(self.test_audio)
        self.play_btn.setEnabled(False)
        run_in_background(lambda: wavein.play_wav(data), lambda _r: self.play_btn.setEnabled(bool(self.test_audio)),
                          lambda e: (self.play_btn.setEnabled(True), show_error(self, "Playback failed", str(e))))

    def discard_test(self) -> None:
        self.test_audio = b""
        self.play_btn.setEnabled(False)
        self.discard_btn.setEnabled(False)

    # -- profiles --------------------------------------------------------------------------
    def _fill_profiles(self) -> None:
        clear_layout(self.profile_box)
        for p in self.profiles.list():
            w = QWidget()
            lay = QVBoxLayout(w)
            lay.setContentsMargins(0, 4, 0, 6)
            lay.setSpacing(3)
            top = QHBoxLayout()
            top.addWidget(label(p.name, "rowtitle"), 1)
            top.addWidget(chip(PROFILE_KINDS.get(p.kind, p.kind)))
            lay.addLayout(top)
            devices = []
            if p.input_name:
                devices.append(f"Mic: {p.input_name}")
            if p.output_name:
                devices.append(f"Output: {p.output_name}")
            lay.addWidget(label(" · ".join(devices) if devices else "No devices chosen yet — edit to choose them.",
                                "caption", wrap=True))
            row = QHBoxLayout()
            apply_btn = button("Apply", "soft", "check", lambda pr=p: self.apply(pr))
            apply_btn.setEnabled(bool(p.input_id or p.output_id) and self.backend is not None)
            row.addWidget(apply_btn)
            row.addWidget(button("Edit", "link", "edit", lambda pr=p: self.edit_profile(pr)))
            row.addWidget(button("Checklist", "link", "list-check", lambda pr=p: show_info(
                self, pr.name, pr.notes or "No checklist yet.")))
            row.addWidget(button("Delete", "link", "trash", lambda pr=p: self.delete_profile(pr)))
            row.addStretch(1)
            lay.addLayout(row)
            self.profile_box.addWidget(w)

    def apply(self, profile) -> None:
        if self.backend is None:
            return
        try:
            ok, messages = apply_profile(self.backend, profile)
        except OSError as exc:
            ok, messages = False, [str(exc)]
        self._fill_devices()
        text = "\n".join(messages)
        if profile.notes:
            text += "\n\nChecklist:\n" + profile.notes
        show_info(self, f"{profile.name} applied" if ok else f"{profile.name}: partly applied",
                  "Windows' default devices were updated." if ok else "Some devices couldn't be selected.", text)

    def new_profile(self) -> None:
        dlg = ProfileDialog(self)
        if dlg.exec():
            self._fill_profiles()

    def edit_profile(self, profile) -> None:
        dlg = ProfileDialog(self, profile)
        if dlg.exec():
            self._fill_profiles()

    def delete_profile(self, profile) -> None:
        if confirm(self, "Delete profile?", f"“{profile.name}” will be deleted. Your devices aren't changed.") \
                and guarded(self, lambda: self.profiles.delete(profile.id)):
            self._fill_profiles()

    # -- troubleshooting -------------------------------------------------------------------
    def _fill_trouble(self) -> None:
        clear_layout(self.trouble_box)
        lines: list[str] = []
        for flow, name in ((RENDER, "Output"), (CAPTURE, "Input")):
            default, comms = self._defaults(flow)
            devs = self.devices[flow]
            dev = next((d for d in devs if d.id == default), None)
            lines.append(f"Default {name.lower()}: {dev.name if dev else 'none'}"
                         + (f" ({dev.format_text})" if dev and dev.format_text else ""))
            comms_dev = next((d for d in devs if d.id == comms), None)
            if comms_dev and comms_dev.id != default:
                lines.append(f"Communications {name.lower()}: {comms_dev.name}")
            counts = {}
            for d in devs:
                counts[d.state_text] = counts.get(d.state_text, 0) + 1
            lines.append(f"{name} devices: " + ", ".join(f"{n} {s.lower()}" for s, n in counts.items()) if counts
                         else f"{name} devices: none")
        for line in lines:
            self.trouble_box.addWidget(label(line, "", wrap=True))
        tips = ("If a device is missing: check the cable or Bluetooth connection, then press Refresh.\n"
                "If a device shows “Disabled in Windows”: enable it in Sound settings → More sound settings.\n"
                "If apps can't hear you: allow microphone access for desktop apps in Settings → Privacy & security → "
                "Microphone.\nIf a call app uses the wrong device: choose 'Default' in that app, then apply a profile "
                "with “communications” ticked.")
        self.trouble_box.addWidget(label(tips, "caption", wrap=True))
        row = QHBoxLayout()
        row.addWidget(button("Copy details", "link", "copy",
                             lambda: (QGuiApplication.clipboard().setText("\n".join(lines)), self.toast("Copied"))))
        row.addStretch(1)
        self.trouble_box.addLayout(row)

    def hideEvent(self, event) -> None:  # noqa: N802
        self.stop_meter()  # never keep listening on a page you can't see
        super().hideEvent(event)
