"""Settings → AI: choose a provider, add / check / remove your own API key, pick a model."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from src.services import ai, credentials
from src.ui.widgets.common import Card, button, confirm, label, show_error
from src.ui.worker import run_in_background


def build(page) -> QWidget:
    ctx = page.ctx
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    card = Card("AI assistance (optional)", "sparkle")
    card.body.addWidget(label(
        "DayOS works fully without AI. If you add your own API key, a few features can make suggestions: note "
        "summaries and tags, project task breakdowns and practice questions. Before anything is sent, DayOS shows "
        "you the exact text and waits for you to confirm. Results are suggestions you review; AI-made questions are "
        "marked unverified. Clipboard history is never sent.", "muted", wrap=True))
    row = QHBoxLayout()
    row.addWidget(label("Provider", "muted"))
    provider = QComboBox()
    provider.addItem("Off", "")
    for key, name in ai.PROVIDERS.items():
        provider.addItem(name, key)
    provider.setAccessibleName("AI provider")
    row.addWidget(provider)
    row.addWidget(label("Model", "muted"))
    model = QComboBox()
    model.setAccessibleName("AI model")
    row.addWidget(model, 1)
    card.body.addLayout(row)
    status = label("", "", wrap=True)
    card.body.addWidget(status)
    key_row = QHBoxLayout()
    key = QLineEdit()
    key.setEchoMode(QLineEdit.EchoMode.Password)
    key.setPlaceholderText("Paste your API key")
    key.setAccessibleName("API key")
    key_row.addWidget(key, 1)
    save_btn = button("Check and save", "primary", "check")
    key_row.addWidget(save_btn)
    card.body.addLayout(key_row)
    remove_btn = button("Remove saved key", "ghost", "trash")
    card.body.addWidget(remove_btn)
    card.body.addWidget(label("The key is stored in Windows Credential Manager for your Windows account only — never "
                              "in DayOS's database, backups, exports, logs or the program itself. Checking the key "
                              "sends one tiny test request with no personal data. Usage is billed to your own "
                              "provider account.", "caption", wrap=True))
    lay.addWidget(card)

    def fill_models() -> None:
        current = ctx.settings.get("ai.model")
        model.blockSignals(True)
        model.clear()
        for mid, name in ai.MODELS.get(provider.currentData() or "", []):
            model.addItem(name, mid)
        model.setCurrentIndex(max(0, model.findData(current)))
        model.blockSignals(False)
        model.setEnabled(bool(provider.currentData()))

    def load() -> None:
        provider.blockSignals(True)
        provider.setCurrentIndex(max(0, provider.findData(ctx.settings.get("ai.provider") or "")))
        provider.blockSignals(False)
        fill_models()
        p = provider.currentData()
        saved = credentials.load(ai.credential_name(p)) if p else None
        if not p:
            status.setText("AI is off.")
        elif saved:
            status.setText(f"Key saved ({credentials.mask(saved)}). AI suggestions are available.")
        else:
            status.setText("No key saved yet.")
        for w in (key, save_btn):
            w.setEnabled(bool(p))
        remove_btn.setVisible(bool(saved))

    def provider_changed() -> None:
        page.set_pref("ai.provider", provider.currentData() or "")
        p = provider.currentData()
        if p and ctx.settings.get("ai.model") not in dict(ai.MODELS[p]):
            page.set_pref("ai.model", ai.DEFAULT_MODEL[p])
        load()

    def save() -> None:
        p = provider.currentData()
        value = key.text().strip()
        if not p or not value:
            return
        save_btn.setEnabled(False)
        status.setText("Checking the key…")
        test = ai.AnthropicProvider(value, model.currentData() or ai.DEFAULT_MODEL[p])

        def done(_r) -> None:
            save_btn.setEnabled(True)
            try:
                credentials.save(ai.credential_name(p), value)
            except credentials.CredentialError as exc:
                show_error(page, "Couldn't save the key", str(exc))
                return
            key.clear()
            load()

        def failed(exc: Exception) -> None:
            save_btn.setEnabled(True)
            status.setText(f"The key wasn't saved: {exc}")

        run_in_background(test.check, done, failed)

    def remove() -> None:
        p = provider.currentData()
        if p and confirm(page, "Remove the API key?", "DayOS will forget the key. You can also revoke it in your "
                                                      "provider's console.", "Remove"):
            credentials.delete(ai.credential_name(p))
            load()

    provider.activated.connect(lambda _i: provider_changed())
    model.activated.connect(lambda _i: page.set_pref("ai.model", model.currentData()))
    save_btn.clicked.connect(lambda _=False: save())
    key.returnPressed.connect(save)
    remove_btn.clicked.connect(lambda _=False: remove())
    page.on_refresh(load)
    return box
