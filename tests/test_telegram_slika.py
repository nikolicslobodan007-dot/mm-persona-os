"""Telegram ulaz za sliku (ADR-0118/0158) — ekstrakcija slike iz poruke.

Čist test nad `_slika_iz` (parsiranje dict-a, bez baze i mreže). Skidanje i
pravljenje asseta idu kroz MediaAsset/storage i pokriveni su lancem konzole.
"""

from __future__ import annotations

from apps.channels import telegram


def test_photo_uzima_najvecu_velicinu():
    msg = {"photo": [{"file_id": "mala", "width": 90},
                     {"file_id": "velika", "width": 1280}]}
    assert telegram._slika_iz(msg) == ("velika", "image/jpeg")


def test_document_slika_po_mime():
    msg = {"document": {"file_id": "d1", "mime_type": "image/png"}}
    assert telegram._slika_iz(msg) == ("d1", "image/png")


def test_document_koji_nije_slika_se_ignorise():
    msg = {"document": {"file_id": "z", "mime_type": "application/zip"}}
    assert telegram._slika_iz(msg) is None


def test_samo_tekst_nema_slike():
    assert telegram._slika_iz({"text": "zdravo"}) is None


def test_prazna_poruka_nema_slike():
    assert telegram._slika_iz({}) is None
