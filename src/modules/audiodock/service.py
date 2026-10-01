"""AudioDock services: saved profiles (database) and applying them through an audio backend.

The backend is :class:`~src.modules.audiodock.coreaudio.CoreAudio` in DayOS; tests pass
a stand-in. Nothing here records audio.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.repositories.base import Repository, clean_text
from src.services.dates import ValidationError, now_stamp

from .coreaudio import CAPTURE, COMMUNICATIONS, CONSOLE, MULTIMEDIA, RENDER
from .schema import PROFILE_KINDS


@dataclass
class AudioProfile:
    id: int
    name: str
    kind: str = "custom"
    input_id: str = ""
    input_name: str = ""
    output_id: str = ""
    output_name: str = ""
    communications: int = 0
    input_volume: int | None = None
    notes: str = ""
    position: int = 0
    created_at: str = ""


class ProfileRepository(Repository):
    def list(self) -> list[AudioProfile]:
        return [AudioProfile(**dict(r)) for r in self.db.query("SELECT * FROM ad_profiles ORDER BY position, id")]

    def get(self, profile_id: int) -> AudioProfile | None:
        row = self.db.query_one("SELECT * FROM ad_profiles WHERE id = ?", (profile_id,))
        return AudioProfile(**dict(row)) if row else None

    def save(self, profile_id: int | None, *, name: str, kind: str = "custom", input_id: str = "",
             input_name: str = "", output_id: str = "", output_name: str = "", communications: bool = False,
             input_volume: int | None = None, notes: str = "") -> int:
        name = clean_text(name, field="Profile name", required=True, max_len=60)
        if kind not in PROFILE_KINDS:
            raise ValidationError(f"Unknown profile type: {kind}")
        if input_volume is not None and not 0 <= int(input_volume) <= 100:
            raise ValidationError("Microphone volume must be between 0 and 100.")
        clash = self.db.scalar("SELECT id FROM ad_profiles WHERE name = ? COLLATE NOCASE AND id IS NOT ?",
                               (name, profile_id))
        if clash:
            raise ValidationError(f"A profile called “{name}” already exists.")
        values = (name, kind, input_id[:500], clean_text(input_name, field="Input", max_len=200), output_id[:500],
                  clean_text(output_name, field="Output", max_len=200), int(bool(communications)),
                  None if input_volume is None else int(input_volume),
                  clean_text(notes, field="Notes", max_len=4000))
        with self.db.transaction():
            if profile_id is None:
                position = int(self.db.scalar("SELECT COALESCE(MAX(position), 0) + 1 FROM ad_profiles", default=1))
                return self.db.insert(
                    "INSERT INTO ad_profiles (name, kind, input_id, input_name, output_id, output_name, "
                    "communications, input_volume, notes, position, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (*values, position, now_stamp()))
            self.db.execute(
                "UPDATE ad_profiles SET name = ?, kind = ?, input_id = ?, input_name = ?, output_id = ?, "
                "output_name = ?, communications = ?, input_volume = ?, notes = ? WHERE id = ?",
                (*values, profile_id))
            return int(profile_id)

    def delete(self, profile_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM ad_profiles WHERE id = ?", (profile_id,))


def apply_profile(backend, profile: AudioProfile) -> tuple[bool, list[str]]:
    """Make the profile's devices the Windows defaults. Returns (all applied, messages)."""
    messages: list[str] = []
    ok = True
    roles = (CONSOLE, MULTIMEDIA) + ((COMMUNICATIONS,) if profile.communications else ())
    for flow, device_id, name, label in ((CAPTURE, profile.input_id, profile.input_name, "Microphone"),
                                         (RENDER, profile.output_id, profile.output_name, "Speakers / headphones")):
        if not device_id:
            messages.append(f"{label}: not set in this profile (left as it is).")
            continue
        present = {d.id: d for d in backend.devices(flow)}
        device = present.get(device_id)
        if device is None or not device.active:
            ok = False
            state = device.state_text.lower() if device else "not connected"
            messages.append(f"{label}: “{name or 'saved device'}” is {state}, so it wasn't selected.")
            continue
        if all(backend.default_id(flow, r) == device_id for r in roles):
            messages.append(f"{label}: “{device.name}” was already the default.")
        elif backend.set_default(device_id, flow, roles):
            messages.append(f"{label}: “{device.name}” is now the default.")
        else:
            ok = False
            messages.append(f"{label}: Windows didn't accept the change. Choose “{device.name}” in Sound settings.")
        if flow == CAPTURE and profile.input_volume is not None and device is not None and device.active:
            try:
                backend.set_volume(device_id, profile.input_volume / 100)
                messages.append(f"{label} volume set to {profile.input_volume}%.")
            except OSError:
                ok = False
                messages.append(f"{label}: this device doesn't allow its volume to be changed.")
    return ok, messages
