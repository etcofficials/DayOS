"""AudioDock: Windows audio devices, defaults, volume, a microphone check and audio profiles.

Windows-specific code lives behind :mod:`.coreaudio` and :mod:`.wavein`; if they can't be
used, the AudioDock page explains why and the rest of DayOS is unaffected.
"""

from __future__ import annotations

from src.modules import registry
from src.modules.registry import ModuleSpec

registry.register(ModuleSpec(
    "audiodock", "AudioDock", "headphones", "tools", "src.modules.audiodock.ui.page:AudioDockPage",
    "Microphones and speakers, default devices, a microphone check and recording / meeting profiles."))


def install(window) -> None:
    from src.ui.shell.commands import Command

    def page():
        window.navigate("audiodock")
        return window.page("audiodock")

    window.commands.add(Command("audiodock.open", "Audio devices", "Choose microphone and speakers", "",
                                "headphones", page, ("audio", "microphone", "speakers", "headset", "audiodock")))
    window.commands.add(Command("audiodock.test", "Test my microphone", "Live level meter and a 5-second test",
                                "", "mic", lambda: page().toggle_meter(), ("mic", "microphone", "test", "audio")))
