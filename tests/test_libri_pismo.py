"""Testovi dvopisma (latinica + ćirilica) za determinističke ekstraktore."""

from __future__ import annotations

from apps.libri.pismo import u_latinicu


def test_u_latinicu_srpska_cirilica():
    assert u_latinicu("Фурнир је танак") == "Furnir je tanak"
    assert u_latinicu("компанији") == "kompaniji"
    assert u_latinicu("Љубав Њива Џак Ђак") == "Ljubav Njiva Džak Đak"


def test_u_latinicu_latinica_nepromenjena():
    assert u_latinicu("Milan Jovanović") == "Milan Jovanović"
    assert u_latinicu("") == ""
