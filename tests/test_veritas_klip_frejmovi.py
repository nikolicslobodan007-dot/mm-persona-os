"""Veritas klip — frejmovi preko celog klipa (fps raspodela)."""

from apps.memory.veritas import klip


class TestVfPrekoKlipa:
    def test_dug_klip_rasporedi_preko_celog(self, monkeypatch):
        monkeypatch.setattr(klip, "_trajanje_ms", lambda v: 30000)  # 30 s
        fps = float(klip._vf_preko_klipa("x.mp4", 5).split("=")[1])
        assert 0.15 < fps < 0.18  # 5 frejmova / 30 s

    def test_kratak_klip_kapiran_na_2fps(self, monkeypatch):
        monkeypatch.setattr(klip, "_trajanje_ms", lambda v: 1000)  # 1 s
        fps = float(klip._vf_preko_klipa("x.mp4", 5).split("=")[1])
        assert fps <= 2.0

    def test_nepoznato_trajanje_ne_puca(self, monkeypatch):
        monkeypatch.setattr(klip, "_trajanje_ms", lambda v: 0)  # ffprobe pao
        vf = klip._vf_preko_klipa("x.mp4", 5)
        assert vf.startswith("fps=") and float(vf.split("=")[1]) > 0
