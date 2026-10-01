"""Decide whether a clipboard change may be stored.

These checks reduce the chance of keeping secrets, but no detection is perfect:
the UI says so plainly and always offers pause, exclusions and clear-history.
Reasons returned here describe *why* something was skipped and never include
the clipboard text itself, so they are safe to show and to log.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Password managers and similar apps (matched against the executable that owns the clipboard).
PRIVATE_APPS = {
    "keepass.exe", "keepassxc.exe", "1password.exe", "bitwarden.exe", "lastpass.exe", "dashlane.exe",
    "enpass.exe", "roboform.exe", "nordpass.exe", "keeper.exe", "keeperpasswordmanager.exe", "protonpass.exe",
    "passwordsafe.exe", "pwsafe.exe", "sticky password.exe", "stickypassword.exe", "zoho vault.exe",
    "authy desktop.exe", "authy.exe", "winauth.exe",
}

# Windows clipboard formats that apps set to ask clipboard tools not to keep the content.
PRIVATE_FORMATS = (
    "ExcludeClipboardContentFromMonitorProcessing",
    "CanIncludeInClipboardHistory",
    "Clipboard Viewer Ignore",
)

_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])("
    r"gh[pousr]_[A-Za-z0-9]{30,}"
    r"|github_pat_[A-Za-z0-9_]{40,}"
    r"|glpat-[A-Za-z0-9_-]{20,}"
    r"|xox[abprs]-[A-Za-z0-9-]{10,}"
    r"|sk-(?:ant-|proj-|live_|test_)?[A-Za-z0-9_-]{20,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|AIza[0-9A-Za-z_-]{35}"
    r"|eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
    r")")
_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
_ASSIGNED_SECRET = re.compile(
    r"(?i)\b(password|passwd|pwd|passcode|secret|api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret)"
    r"\s*[:=]\s*\S+")
_OTP = re.compile(r"\d{6}|\d{8}|\d{3}[ -]\d{3}")
_CARD = re.compile(r"\d[\d -]{11,22}\d")


def luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def sensitive_reason(text: str) -> str | None:
    """A short reason if ``text`` looks like a secret, else None."""
    stripped = text.strip()
    if _PRIVATE_KEY.search(text):
        return "looked like a private key"
    if _TOKEN.search(text):
        return "looked like an access token or API key"
    if _ASSIGNED_SECRET.search(text):
        return "looked like a password or key"
    if _OTP.fullmatch(stripped):
        return "looked like a one-time code"
    if _CARD.fullmatch(stripped):
        digits = re.sub(r"\D", "", stripped)
        if 13 <= len(digits) <= 19 and luhn_ok(digits):
            return "looked like a card number"
    return None


@dataclass(frozen=True)
class Rule:
    kind: str  # app / contains / pattern
    value: str
    enabled: bool = True


def validate_rule(kind: str, value: str) -> str:
    """Normalise a rule value or raise ValueError with a readable message."""
    value = str(value or "").strip()
    if not value:
        raise ValueError("Enter something for the rule to match.")
    if len(value) > 200:
        raise ValueError("Rules can be up to 200 characters.")
    if kind == "app":
        value = value.split("\\")[-1].split("/")[-1].lower()
        if not value.endswith(".exe"):
            value += ".exe"
    elif kind == "pattern":
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"That pattern isn't valid: {exc}") from None
    elif kind != "contains":
        raise ValueError(f"Unknown rule type: {kind}")
    return value


def rule_reason(text: str, app: str, rules: list[Rule]) -> str | None:
    app = (app or "").lower()
    sample = text[:20000]
    lowered = sample.lower()
    for rule in rules:
        if not rule.enabled:
            continue
        if rule.kind == "app" and app and app == rule.value.lower():
            return f"copied from {rule.value} (your exclusion rule)"
        if rule.kind == "contains" and rule.value.lower() in lowered:
            return "matched one of your exclusion rules"
        if rule.kind == "pattern":
            try:
                if re.search(rule.value, sample):
                    return "matched one of your exclusion patterns"
            except re.error:
                continue
    return None


@dataclass(frozen=True)
class Decision:
    keep: bool
    reason: str = ""


def decide(text: str, app: str, formats: set[str], rules: list[Rule], *, max_chars: int,
           skip_sensitive: bool, skip_private_apps: bool) -> Decision:
    """Whether to store a clipboard change. ``formats``: private clipboard formats present."""
    if skip_private_apps:
        if formats & set(PRIVATE_FORMATS):
            return Decision(False, "the app that copied it marked it as private")
        if app and app.lower() in PRIVATE_APPS:
            return Decision(False, f"copied from a password manager ({app})")
    if not text or not text.strip():
        return Decision(False, "empty")
    if len(text) > max_chars:
        return Decision(False, f"longer than {max_chars:,} characters")
    reason = rule_reason(text, app, rules)
    if reason:
        return Decision(False, reason)
    if skip_sensitive:
        reason = sensitive_reason(text)
        if reason:
            return Decision(False, reason)
    return Decision(True)
