"""ADR-0103 — nacrt postaje stvaran fajl.

  - `.odt` nastaje bez LibreOffice-a i u njemu zaista piše ono što je agent
    napisao (proverava se sadržaj ZIP-a, ne samo da je fajl nastao);
  - isti nacrt drugi put ne pravi drugi red u bazi;
  - prazan nacrt i nepoznat format se odbijaju pre nego što se bilo šta upiše;
  - format koji traži LibreOffice, kad njega nema, kaže ZAŠTO i šta radi bez
    njega — tiho prazan fajl je gori od greške;
  - upis se vidi u auditu.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from apps.content import dokument
from apps.content.models import ContentItem
from apps.observability.models import AuditEvent
from apps.visuals import storage
from apps.visuals.models import MediaAsset
from common import enums as E
from tests.conftest import requires_db

pytestmark = [requires_db]

NASLOV = "Web Korporacija — Energija novih ideja!"
PASUS_JEDAN = "Web Korporacija je firma u kojoj poslove obavljaju AI agenti."
PASUS_DVA = "Svaki agent ima jasnu ulogu i granice delovanja."


@pytest.fixture
def skladiste(monkeypatch):
    """Skladište je lažno, biblioteka je prava — merimo svoj kod, ne MinIO."""
    fajlovi: dict[str, bytes] = {}
    monkeypatch.setattr(
        storage, "put",
        lambda data, *, key, mime: fajlovi.__setitem__(key, data) or key)
    monkeypatch.setattr(storage, "get", lambda key: fajlovi[key])
    return fajlovi


@pytest.fixture
def nacrt(mila):
    return ContentItem.objects.create(
        persona=mila, format=E.ContentFormat.POST.value, title=NASLOV,
        body=f"{PASUS_JEDAN}\n\n{PASUS_DVA}", language="sr-Latn-RS",
        status=E.ContentStatus.DRAFT.value,
        provenance=E.Provenance.USER_PROVIDED.value)


@pytest.mark.django_db
class TestDokument:

    def test_odt_nosi_tekst_koji_je_agent_napisao(self, nacrt, skladiste):
        asset = dokument.napravi(nacrt, oblik="odt", actor="user:qa")

        assert asset.kind == E.AssetKind.DOCUMENT.value
        assert asset.mime_type == "application/vnd.oasis.opendocument.text"
        assert asset.public_id.startswith("IMG-")  # Canon §2.2, vrstu nosi `kind`

        podaci = skladiste[asset.storage_key]
        assert podaci[:2] == b"PK"  # ODF je ZIP
        with zipfile.ZipFile(io.BytesIO(podaci)) as z:
            sadrzaj = z.read("content.xml").decode("utf-8")
        assert PASUS_JEDAN in sadrzaj
        assert PASUS_DVA in sadrzaj
        assert "Energija novih ideja" in sadrzaj

    def test_isti_nacrt_ne_pravi_drugi_red(self, nacrt, skladiste):
        prvi = dokument.napravi(nacrt, oblik="odt")
        drugi = dokument.napravi(nacrt, oblik="odt")
        assert prvi.pk == drugi.pk
        assert MediaAsset.objects.count() == 1

    def test_prazan_nacrt_se_odbija(self, mila, skladiste):
        prazan = ContentItem.objects.create(
            persona=mila, format=E.ContentFormat.POST.value, title="Bez tela",
            body="   ", language="sr-Latn-RS",
            status=E.ContentStatus.DRAFT.value,
            provenance=E.Provenance.USER_PROVIDED.value)
        with pytest.raises(dokument.DokumentError, match="prazan"):
            dokument.napravi(prazan, oblik="odt")
        assert MediaAsset.objects.count() == 0

    def test_nepoznat_format_se_odbija(self, nacrt, skladiste):
        with pytest.raises(dokument.DokumentError, match="Nepoznat format"):
            dokument.napravi(nacrt, oblik="jpeg")
        assert MediaAsset.objects.count() == 0

    def test_format_koji_trazi_libreoffice_kaze_zasto(self, nacrt, skladiste,
                                                      monkeypatch):
        """Ne merimo da li u slici ima LibreOffice-a — merimo šta kažemo kad ga
        nema. Zato izvoz namerno pada."""
        from cli_anything.libreoffice.core import export as lo_izvoz

        def pukni(*a, **kw):
            raise RuntimeError("LibreOffice not found")

        monkeypatch.setattr(lo_izvoz, "export", pukni)
        with pytest.raises(dokument.DokumentError) as greska:
            dokument.napravi(nacrt, oblik="pdf")
        poruka = str(greska.value)
        assert "LibreOffice" in poruka
        assert "odt" in poruka  # mora da kaže šta radi i bez njega
        assert MediaAsset.objects.count() == 0

    def test_upis_se_vidi_u_auditu(self, nacrt, skladiste):
        asset = dokument.napravi(nacrt, oblik="odt", actor="user:qa")
        dogadjaj = AuditEvent.objects.filter(
            event_key="content.document.created").order_by("-occurred_at").first()
        assert dogadjaj is not None
        detalji = dogadjaj.payload["details"]
        assert detalji["asset"] == asset.public_id
        assert detalji["oblik"] == "odt"
        assert detalji["sadrzaj"] == str(nacrt.id)
        assert detalji["bajtova"] > 0
