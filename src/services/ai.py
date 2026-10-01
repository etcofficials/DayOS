"""Optional AI assistance behind a small provider interface.

DayOS works fully without AI. When the user configures a provider:

* the API key lives only in Windows Credential Manager (``DayOS/<provider>-api-key``);
* every request that includes the user's own content is shown to them first and sent
  only after they confirm (see :mod:`src.ui.ai_consent`);
* only the minimum text needed for the task is sent, and nothing is logged except the
  feature name, the outcome and (for errors) the error kind;
* results are treated as suggestions the user reviews before anything is saved.

The one built-in provider is Anthropic's Claude, called through the official ``anthropic``
SDK. Other providers can be added by implementing :class:`Provider`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from src.services import credentials

log = logging.getLogger(__name__)

PROVIDERS = {"anthropic": "Anthropic Claude"}
MODELS = {
    "anthropic": [
        ("claude-opus-5-5", "Claude Opus 5.5 (most capable, default)"),
        ("claude-sonnet-5-5", "Claude Sonnet 5.5 (faster, lower cost)"),
        ("claude-haiku-4-5", "Claude Haiku 4.5 (fastest, lowest cost)"),
    ],
}
DEFAULT_MODEL = {"anthropic": "claude-opus-5-5"}
# Server-side fallback re-runs a declined request on Anthropic's recommended model.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5"}
TIMEOUT_SECONDS = 120.0


class AIError(Exception):
    """kind: not_configured, auth, rate_limited, offline, refused, too_long, bad_response, unavailable."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def credential_name(provider: str) -> str:
    return f"{provider}-api-key"


@dataclass
class AIConfig:
    provider: str
    model: str

    @property
    def label(self) -> str:
        names = dict(MODELS.get(self.provider, []))
        return f"{PROVIDERS.get(self.provider, self.provider)} · {names.get(self.model, self.model)}"


def config_from_settings(settings) -> AIConfig | None:
    provider = str(settings.get("ai.provider") or "")
    if provider not in PROVIDERS:
        return None
    model = str(settings.get("ai.model") or DEFAULT_MODEL[provider])
    if model not in dict(MODELS[provider]):
        model = DEFAULT_MODEL[provider]
    return AIConfig(provider, model)


class Provider:
    def generate_json(self, *, feature: str, system: str, content: str, schema: dict, effort: str = "low",
                      max_tokens: int = 16000) -> dict:
        raise NotImplementedError

    def check(self) -> None:
        raise NotImplementedError


class AnthropicProvider(Provider):
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def _client(self):
        try:
            import anthropic
        except ImportError:
            raise AIError("unavailable", "The AI component isn't included in this copy of DayOS.") from None
        return anthropic, anthropic.Anthropic(api_key=self.api_key, timeout=TIMEOUT_SECONDS, max_retries=2)

    def _create(self, **kwargs):
        anthropic, client = self._client()
        if self.model in FALLBACK_MODELS:
            kwargs.update(betas=[FALLBACK_BETA], fallbacks="default")
        try:
            return client.beta.messages.create(model=self.model, **kwargs)
        except anthropic.AuthenticationError:
            raise AIError("auth", "Anthropic didn't accept the API key. Check it in Settings → AI.") from None
        except anthropic.PermissionDeniedError:
            raise AIError("auth", "This API key isn't allowed to use that model.") from None
        except anthropic.RateLimitError:
            raise AIError("rate_limited", "Anthropic is limiting requests right now. Try again in a minute.") from None
        except anthropic.BadRequestError as exc:
            message = str(getattr(exc, "message", "") or "")
            if "too long" in message.lower() or "context" in message.lower():
                raise AIError("too_long", "That's too much text to send at once.") from None
            raise AIError("bad_response", "Anthropic couldn't process this request.") from None
        except anthropic.APIStatusError as exc:
            raise AIError("unavailable", f"Anthropic had a problem ({exc.status_code}). Try again later.") from None
        except anthropic.APIConnectionError:
            raise AIError("offline", "Couldn't reach Anthropic. Check your internet connection.") from None

    def generate_json(self, *, feature: str, system: str, content: str, schema: dict, effort: str = "low",
                      max_tokens: int = 16000) -> dict:
        response = self._create(
            max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": content}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}})
        if response.stop_reason == "refusal":
            log.info("AI request for %s was declined by the provider", feature)
            raise AIError("refused", "The AI declined this request. Nothing was changed.")
        if response.stop_reason == "max_tokens":
            raise AIError("bad_response", "The answer was cut off. Try with less text.")
        text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), "")
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            raise AIError("bad_response", "The AI's answer couldn't be read.") from None
        if not isinstance(data, dict):
            raise AIError("bad_response", "The AI's answer couldn't be read.")
        log.info("AI request for %s completed", feature)
        return data

    def check(self) -> None:
        """A tiny request to confirm the key and model work (sends no personal data)."""
        self.generate_json(feature="connection check", system="Reply with the requested JSON only.",
                           content="Return {\"ok\": true}.",
                           schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"],
                                   "additionalProperties": False}, effort="low", max_tokens=2048)


def provider_for(settings, api_key: str | None = None) -> Provider:
    config = config_from_settings(settings)
    if config is None:
        raise AIError("not_configured", "AI isn't set up. You can add a provider in Settings → AI.")
    key = api_key if api_key is not None else credentials.load(credential_name(config.provider))
    if not key:
        raise AIError("not_configured", "No API key is saved. Add one in Settings → AI.")
    return AnthropicProvider(key, config.model)


def is_configured(settings) -> bool:
    config = config_from_settings(settings)
    return config is not None and credentials.exists(credential_name(config.provider))


# -- task helpers (each returns validated data; callers show it for review) --------------------
MAX_INPUT_CHARS = 60_000


def _limit(text: str) -> str:
    if len(text) > MAX_INPUT_CHARS:
        raise AIError("too_long", f"That's more than {MAX_INPUT_CHARS:,} characters. Select a shorter part.")
    return text


SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}},
    "required": ["summary", "tags"], "additionalProperties": False,
}


def note_payload(title: str, content: str) -> str:
    """The exact text sent for a note summary (also what the consent dialog shows)."""
    return f"Title: {title}\n\n{content}"


def project_payload(name: str, description: str, existing: list[str]) -> str:
    return (f"Project: {name}\nDescription: {description or '(none)'}\nExisting tasks and milestones:\n"
            + "\n".join(f"- {t}" for t in existing[:60]))


def questions_payload(topic_path: str, count: int, material: str = "") -> str:
    count = max(1, min(10, int(count)))
    return (f"Topic: {topic_path}\nNumber of questions: {count}\n"
            + (f"\nStudy material provided by the student:\n{material}" if material.strip() else ""))


def summarize_note(provider: Provider, title: str, content: str) -> tuple[str, list[str]]:
    payload = _limit(note_payload(title, content))
    data = provider.generate_json(
        feature="note summary", effort="low", schema=SUMMARY_SCHEMA,
        system="You help a person organise their own notes. Write a short, faithful summary (2-5 sentences, "
               "plain language) of the note, using only what the note says. Suggest up to 5 short topic tags "
               "(one or two words each, lowercase).",
        content=payload)
    summary = str(data.get("summary", "")).strip()
    tags = [str(t).strip().lstrip("#")[:40] for t in data.get("tags", []) if str(t).strip()][:5]
    if not summary:
        raise AIError("bad_response", "The AI didn't return a summary.")
    return summary, tags


TASKS_SCHEMA = {
    "type": "object",
    "properties": {"tasks": {"type": "array", "items": {
        "type": "object",
        "properties": {"title": {"type": "string"}, "minutes": {"type": "integer"}},
        "required": ["title", "minutes"], "additionalProperties": False}}},
    "required": ["tasks"], "additionalProperties": False,
}


def suggest_tasks(provider: Provider, name: str, description: str, existing: list[str]) -> list[tuple[str, int]]:
    payload = _limit(project_payload(name, description, existing))
    data = provider.generate_json(
        feature="project breakdown", effort="medium", schema=TASKS_SCHEMA,
        system="Break the person's project into 5-12 concrete next tasks, each something one person can do in "
               "one sitting, starting with a verb. Don't repeat existing tasks. Give a realistic estimate in "
               "minutes (15-240).",
        content=payload)
    out = []
    for item in data.get("tasks", [])[:15]:
        title = " ".join(str(item.get("title", "")).split())[:200]
        try:
            minutes = max(5, min(480, int(item.get("minutes", 30))))
        except (TypeError, ValueError):
            minutes = 30
        if title:
            out.append((title, minutes))
    if not out:
        raise AIError("bad_response", "The AI didn't suggest any tasks.")
    return out


QUESTION_SCHEMA = {
    "type": "object",
    "properties": {"questions": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "qtype": {"type": "string", "enum": ["mcq", "tf", "sa"]},
            "text": {"type": "string"},
            "options": {"type": "array", "items": {"type": "string"}},
            "answer": {"type": "string"},
            "explanation": {"type": "string"},
            "marks": {"type": "integer"},
        },
        "required": ["qtype", "text", "options", "answer", "explanation", "marks"],
        "additionalProperties": False}}},
    "required": ["questions"], "additionalProperties": False,
}


def generate_questions(provider: Provider, topic_path: str, count: int, material: str = "") -> list[dict]:
    """Practice questions for review. Every one is checked here; invalid ones are dropped."""
    count = max(1, min(10, int(count)))
    payload = _limit(questions_payload(topic_path, count, material))
    data = provider.generate_json(
        feature="practice questions", effort="medium", schema=QUESTION_SCHEMA, max_tokens=16000,
        system="Write practice questions for a student on the given topic. Mix types: 'mcq' (exactly 4 options; "
               "answer is the 0-based index of the one correct option as a string), 'tf' (options empty; answer "
               "'true' or 'false') and 'sa' (short answer; options empty; answer is a model answer). Marks: 1 for "
               "mcq and tf, 2 or 3 for sa. Keep each question accurate and unambiguous; if study material is "
               "given, base questions on it. Explanations: one or two sentences.",
        content=payload)
    out = []
    for q in data.get("questions", [])[: count + 2]:
        qtype = q.get("qtype")
        text = " ".join(str(q.get("text", "")).split())
        if qtype not in ("mcq", "tf", "sa") or len(text) < 5:
            continue
        options = [str(o).strip() for o in q.get("options") or [] if str(o).strip()]
        answer = str(q.get("answer", "")).strip()
        try:
            marks = int(q.get("marks", 1))
        except (TypeError, ValueError):
            continue
        if qtype == "mcq":
            if len(options) != 4 or answer not in {"0", "1", "2", "3"} or marks != 1:
                continue
        elif qtype == "tf":
            if answer.lower() not in ("true", "false") or marks != 1:
                continue
            options, answer = [], answer.lower()
        else:
            if not answer or marks not in (2, 3):
                continue
            options = []
        out.append({"qtype": qtype, "text": text[:2000], "options": options, "answer": answer[:2000],
                    "explanation": str(q.get("explanation", "")).strip()[:1000], "marks": marks})
    return out[:count]
