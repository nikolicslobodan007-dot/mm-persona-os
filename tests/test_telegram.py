"""ADR-0134 — Telegram most: allowlist, offset, raspoređivanje (bez baze)."""

from __future__ import annotations

import apps.channels.tasks as tasks
from apps.channels import telegram


class _FakeRedis:
    def __init__(self):
        self.store: dict = {}

    def set(self, k, v, nx=False, ex=None):
        if nx and k in self.store:
            return False
        self.store[k] = v
        return True

    def get(self, k):
        return self.store.get(k)

    def delete(self, k):
        self.store.pop(k, None)


def test_dozvoljeni_i_actor(settings):
    settings.TELEGRAM_ALLOWED_IDS = "111, 222"
    assert telegram.dozvoljeni() == {"111", "222"}
    assert telegram.actor_za(111) == "user:slobodan"
    assert telegram.actor_za(999) is None


def test_obradi_batch_uspavan(settings):
    settings.TELEGRAM_ENABLED = False
    assert telegram.obradi_batch() == {"off": True}


def test_obradi_batch_allowlist(settings, monkeypatch):
    settings.TELEGRAM_ENABLED = True
    settings.TELEGRAM_ALLOWED_IDS = "111"
    monkeypatch.setattr(telegram, "_token", lambda: "T")
    fake = _FakeRedis()
    monkeypatch.setattr(telegram, "_redis", lambda: fake)
    poslato: list = []
    monkeypatch.setattr(telegram, "posalji_poruku",
                        lambda cid, t: poslato.append((cid, t)))
    zakazano: list = []
    monkeypatch.setattr(tasks.telegram_odgovori, "delay",
                        lambda *a: zakazano.append(a))
    updates = {"result": [
        {"update_id": 10, "message": {"chat": {"id": 111}, "text": "zdravo"}},
        {"update_id": 11, "message": {"chat": {"id": 999}, "text": "napolje"}},
    ]}
    monkeypatch.setattr(telegram, "_api",
                        lambda tok, m, p, timeout=10: updates if m == "getUpdates" else {})

    rez = telegram.obradi_batch()
    assert rez == {"procitano": 2, "zakazano": 1}
    # samo dozvoljeni ID je zakazan; nedozvoljeni tiho preskočen
    assert zakazano == [(111, "zdravo", "user:slobodan", None, "")]
    assert fake.get(telegram.OFFSET_KEY) == 12  # max(update_id)+1
    assert any(cid == 111 for cid, _ in poslato)      # ack dozvoljenom
    assert not any(cid == 999 for cid, _ in poslato)  # ne nedozvoljenom


def test_obradi_batch_slika_salje_file_id(settings, monkeypatch):
    """Slika (ADR-0158): caption je telo, najveći photo → (file_id, image/jpeg)."""
    settings.TELEGRAM_ENABLED = True
    settings.TELEGRAM_ALLOWED_IDS = "111"
    monkeypatch.setattr(telegram, "_token", lambda: "T")
    fake = _FakeRedis()
    monkeypatch.setattr(telegram, "_redis", lambda: fake)
    monkeypatch.setattr(telegram, "posalji_poruku", lambda cid, t: None)
    zakazano: list = []
    monkeypatch.setattr(tasks.telegram_odgovori, "delay", lambda *a: zakazano.append(a))
    updates = {"result": [
        {"update_id": 20, "message": {
            "chat": {"id": 111}, "caption": "Šta je ovo?",
            "photo": [{"file_id": "mala"}, {"file_id": "velika"}]}},
    ]}
    monkeypatch.setattr(telegram, "_api",
                        lambda tok, m, p, timeout=10: updates if m == "getUpdates" else {})
    telegram.obradi_batch()
    assert zakazano == [(111, "Šta je ovo?", "user:slobodan", "velika", "image/jpeg")]
