"""Uvoz veština u bazu znanja — prva vrata (ADR-0074), i spisak (ADR-0084).

ADR-0074 kaže: materijal za ovu vrstu znanja daje čovek, agent ništa spolja
ne radi. Zato `uvezi()` ne pretpostavlja ni `uri` ni `license_box` — ona
dolaze kao argumenti, jer ih je čovek doneo uz materijal, i ne izmišljaju se
ovde.

ADR-0077 §3 dodaje `commit_sha` i `file_path` za korpus koji dolazi iz
repozitorijuma: isti `uri` tamo daje različit sadržaj u različitim
trenucima, pa sam `uri` ne kaže ŠTA je tačno pročitano. Oba polja su prazna
za izvore koji nisu iz repozitorijuma — ne pretpostavljaju se, prosleđuje ih
onaj ko uvozi.

ADR-0095 dodaje: pri PONOVNOM uvozu istog izvora, pet polja koje čovek
donosi pri SVAKOM uvozu (`uri`, `license_box`, `license_note`, `commit_sha`,
`file_path`) se osvežavaju na postojećem redu. Bez toga je `get_or_create`
sa `defaults=` upisivao te vrednosti SAMO pri prvom pravljenju reda, pa je
ponovni uvoz sa novim zastavicama ostavljao stare podatke — izmereno na
`docs/adr` korpusu: posle uvoza sa novim zastavicama red je i dalje nosio
stari `uri` i prazne `commit_sha`/`file_path`, iako je uvoz prijavio da je
upisao i obrisao činjenice.

ADR-0101 dodaje šesto takvo polje: `sector` — kom sektoru korporacije
korpus pripada (`Department.code`, ADR-0017). Bez osvežavanja bi ponovni
uvoz sa ispravljenim sektorom ostavljao stari. Prazno znači „važi za sve
sektore".

`ingested_at` (ADR-0076 §2), `persona`, `title`
(ključ pretrage), `trust_score`, `source_kind` i `is_active` se NE diraju
ovim osvežavanjem.

Jedna veština je jedan `KnowledgeFact`: `subject` je ime veštine,
`predicate` je `vestina.postupak`, `object_json` nosi korake i napomene —
naš opis postupka, nikad doslovan prepis izvora (ADR-0074 tačka 3): takvo
polje se namerno ne upisuje.

`spisak()` (ADR-0084) je čisto čitanje baze znanja — ne upisuje i ne menja
ništa. Postoji da bi se videlo šta je već uvezeno, pre nego što se nešto
uveze po drugi put.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from api import audit
from apps.memory.models import KnowledgeFact, KnowledgeSource
from common import enums as E


PREDIKAT = "vestina.postupak"

#: ADR-0095 — polja koja čovek donosi pri SVAKOM uvozu i koja se zato
#: osvežavaju i na postojećem redu, ne samo pri prvom pravljenju.
_POLJA_ZA_OSVEZAVANJE = ("uri", "license_box", "license_note", "commit_sha",
                         "file_path", "sector")


@dataclass(frozen=True)
class Vestina:
    """Jedna veština koju čovek unosi — opis postupka, ne tuđi tekst."""

    ime: str
    koraci: list[str]
    napomene: str
    pouzdanost: float


def uvezi(
    *,
    naslov_izvora: str,
    uri: str,
    license_box: E.LicenseBox,
    license_note: str = "",
    commit_sha: str = "",
    file_path: str = "",
    sector: str = "",
    vestine: list[Vestina],
    actor: str,
) -> dict[str, int]:
    """Upisuje veštine u `KnowledgeSource`/`KnowledgeFact`. Vraća prebrojano.

    `commit_sha` i `file_path` (ADR-0077 §3) su prazni za izvore koji nisu iz
    repozitorijuma — ne pretpostavljaju se, prosleđuje ih pozivalac.

    Ponovni uvoz **osvežava** `uri`, `license_box`, `license_note`,
    `commit_sha` i `file_path` na postojećem redu (ADR-0095), i **briše i
    upisuje ponovo** postojeće `KnowledgeFact` za taj izvor sa predikatom
    `vestina.postupak` — isti obrazac kao u Rečniku
    (apps/content/recnik.py), iz istog razloga: spajanje red po red ne bi
    ništa dobilo, a ostavilo bi staro da živi pored novog. Sve u jednoj
    transakciji.
    """
    for v in vestine:
        if not 0.0 <= v.pouzdanost <= 1.0:
            raise ValueError(f"Pouzdanost van [0,1] za veštinu '{v.ime}'.")

    # ADR-0059 tačka 2: slobodna kutija mora da imenuje licencu — provera ovde,
    # pre upisa, da uvoz ne padne tek na CHECK ogradi u bazi.
    if E.LicenseBox(license_box) == E.LicenseBox.SLOBODNA and not license_note:
        raise ValueError(
            "ADR-0059: slobodna kutija mora da imenuje licencu (license_note)."
        )

    with transaction.atomic():
        izvor, napravljen = KnowledgeSource.objects.get_or_create(
            persona=None, title=naslov_izvora,
            defaults={"source_kind": E.SourceKind.FIRST_PARTY_USER_INPUT.value,
                      "trust_score": 1.0, "uri": uri,
                      "license_box": E.LicenseBox(license_box).value,
                      "license_note": license_note,
                      "commit_sha": commit_sha,
                      "file_path": file_path,
                      "sector": sector,
                      "is_active": True})
        if not napravljen:
            # ADR-0095 — red već postoji; osvežavamo tačno pet polja koja
            # čovek donosi pri svakom uvozu. `ingested_at`, `persona`,
            # `title`, `trust_score`, `source_kind` i `is_active` ostaju
            # netaknuti ovim upisom.
            izvor.uri = uri
            izvor.license_box = E.LicenseBox(license_box).value
            izvor.license_note = license_note
            izvor.commit_sha = commit_sha
            izvor.file_path = file_path
            izvor.sector = sector
            izvor.save(update_fields=list(_POLJA_ZA_OSVEZAVANJE))
        # „obrisano" znači broj obrisanih VEŠTINA. Ne čitamo `.delete()[0]`
        # (ukupan broj redova uključuje kaskadu — od ADR-0120 i obrisane
        # KnowledgeEmbedding veština), nego prebrojimo veštine pre brisanja.
        stare = KnowledgeFact.objects.filter(source=izvor, predicate=PREDIKAT)
        obrisano = stare.count()
        stare.delete()
        napravljene = KnowledgeFact.objects.bulk_create([
            KnowledgeFact(
                source=izvor, persona=None, subject=v.ime[:220],
                predicate=PREDIKAT, provenance=E.Provenance.USER_PROVIDED.value,
                confidence=v.pouzdanost,
                object_json={"koraci": list(v.koraci), "napomene": v.napomene})
            for v in vestine
        ], batch_size=1000)
        # ADR-0076 tačka 2: pečat se upisuje tek kad su veštine stvarno
        # upisane — prazan uvoz ne sme da skine izvor sa reda čekanja.
        if vestine:
            izvor.ingested_at = timezone.now()
            izvor.save(update_fields=["ingested_at"])
    # ADR-0120 — van transakcije: veštine su već upisane (FK važi), a poziv
    # semantičkog modela je spor i ne sme da drži zaključan red. Best-effort:
    # ako model nije dostupan, uvoz svejedno uspeva, a vektori se dopune
    # komandom `embed_vestine` (ADR-0009).
    embedovano = embeduj(napravljene)
    broj = {"upisano": len(vestine), "obrisano": obrisano}
    audit.record("memory.vestina.loaded",
                 details={"izvor": naslov_izvora, "actor": actor, **broj,
                          "embedovano": embedovano["upisano"]})
    return broj


def tekst_za_embedding(subject: str, object_json: dict) -> str:
    """Tekst veštine za semantički vektor (ADR-0120): ime + čemu služi + koraci.

    Isti oblik koristi i uvoz, i komanda `embed_vestine`, i merenje
    (`vestina_eval`) — da vektor uvek predstavlja isti sadržaj, pa je skor
    merenja jednak ponašanju u pogonu.
    """
    koraci = (object_json or {}).get("koraci") or []
    napomene = str((object_json or {}).get("napomene") or "")
    delovi = [subject or "", napomene, *[str(k) for k in koraci]]
    return "\n".join(d for d in delovi if d).strip()


def embeduj(facts, *, model_key: str | None = None) -> dict[str, int]:
    """Napravi/osveži `KnowledgeEmbedding` za date veštine (ADR-0120).

    Tanak omotač nad `znanje_vektori.embeduj` (zajednički sloj za veštine i
    pravila): prosleđuje `tekst_za_embedding` kao izbor sadržaja veštine (ime
    + čemu služi + koraci). Best-effort i dedup po `text_hash` su u zajedničkom
    modulu — ovde ostaje samo ŠTA se od veštine embeduje.
    """
    from apps.memory import znanje_vektori

    return znanje_vektori.embeduj(
        facts, text_fn=tekst_za_embedding, model_key=model_key)


def spisak(*, izvor: str = "") -> list[dict]:
    """Sve veštine iz baze znanja, za prikaz čoveku (ADR-0084).

    Jedan red po `KnowledgeFact` sa predikatom `vestina.postupak`, sa
    naslovom izvora, kutijom licence i time da li je izvor aktivan — da bi
    čovek video šta je već uvezeno pre nego što nešto uveze po drugi put.
    `izvor` filtrira po delu naslova izvora (bez obzira na veličinu slova);
    prazan niz ne filtrira ništa. Ne upisuje i ne menja ništa.
    """
    qs = (
        KnowledgeFact.objects.filter(predicate=PREDIKAT)
        .select_related("source")
        .order_by("source__title", "subject")
    )
    if izvor:
        qs = qs.filter(source__title__icontains=izvor)
    return [
        {
            "subject": f.subject,
            "izvor": f.source.title,
            "licenca": f.source.license_box,
            "aktivan": f.source.is_active,
        }
        for f in qs
    ]
