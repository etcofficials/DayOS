"""AudioDock schema (migration 7): saved audio profiles.

A profile remembers preferred input and output devices (by their Windows endpoint ID,
plus the name for display) and a checklist. Applying one changes Windows' default
devices only; it never routes audio or changes other apps' settings.
"""

from __future__ import annotations

PROFILE_KINDS = {
    "recording": "Recording",
    "voiceover": "Voiceover",
    "obs": "OBS / streaming",
    "meeting": "Calls & meetings",
    "custom": "Custom",
}

SCHEMA_V7_AUDIO = """
CREATE TABLE ad_profiles (
    id             INTEGER PRIMARY KEY,
    name           TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK (length(trim(name)) > 0),
    kind           TEXT NOT NULL DEFAULT 'custom'
                   CHECK (kind IN ('recording', 'voiceover', 'obs', 'meeting', 'custom')),
    input_id       TEXT NOT NULL DEFAULT '',
    input_name     TEXT NOT NULL DEFAULT '',
    output_id      TEXT NOT NULL DEFAULT '',
    output_name    TEXT NOT NULL DEFAULT '',
    communications INTEGER NOT NULL DEFAULT 0 CHECK (communications IN (0, 1)),
    input_volume   INTEGER CHECK (input_volume IS NULL OR input_volume BETWEEN 0 AND 100),
    notes          TEXT NOT NULL DEFAULT '',
    position       INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL
)
"""

STARTER_PROFILES = [
    ("Recording", "recording", 0,
     "Close noisy apps and notifications.\nSpeak at a steady distance from the microphone.\nAim for peaks between "
     "−18 and −6 dB on the meter; never touching 0 dB.\nRecord a few seconds of silence first so you can hear the "
     "room."),
    ("Voiceover", "voiceover", 0,
     "Use a quiet, soft-furnished room.\nKeep about a hand's width between mouth and microphone.\nIf Windows offers "
     "'Audio enhancements' for this microphone, turning them off keeps the voice natural.\nAim for peaks around "
     "−12 dB."),
    ("OBS / streaming", "obs", 0,
     "In OBS → Settings → Audio, choose this profile's microphone (or 'Default').\nUse OBS's own filters (for "
     "example Noise Suppression) inside OBS; DayOS doesn't change OBS.\nCheck the OBS mixer moves when you speak "
     "before going live."),
    ("Calls & meetings", "meeting", 1,
     "Also sets the Windows 'communications' device that most call apps use.\nIn the call app, choose 'Default' "
     "devices so it follows this profile.\nUse the meter here to check you're not muted before joining."),
]
