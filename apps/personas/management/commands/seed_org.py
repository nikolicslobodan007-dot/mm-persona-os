"""Kostur korporacije: sektori, radna mesta, prvi raspored. ADR-0017.

    manage.py seed_org                       (sektori i radna mesta)
    manage.py seed_org --persona P-00001     (uz to: raspored i dosije Mile)

Idempotentno — ponovno pokretanje ne pravi duplikate i ne dira postojeće
rasporede. Ne dodeljuje nijedno poverenje: radno mesto nije dozvola.
"""

from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from api.context import bind
from apps.personas import org
from apps.personas.models import Assignment, Department, Persona, Position
from common import enums as E

L = E.OrgLevel

#: (code, ime, čemu služi)
DEPARTMENTS: tuple[tuple[str, str, str], ...] = (
    ("UPRAVA", "Uprava", "Ciljevi, odobrenja i merenje rada cele korporacije."),
    ("NABAVKA", "Nabavka i dobavljači",
     "Pronalazak proizvođača, uslovi saradnje i privatna robna marka."),
    ("PRODAJA", "Prodaja i izvoz", "Tržišta, ponude i zaključenje posla."),
    ("MARKETING", "Marketing i sadržaj",
     "Sadržaj po jeziku i platformi; gradnja publike, ne targetiranje kupaca."),
    ("PODRSKA", "Korisnička podrška", "Pošta, upiti i reklamacije."),
    ("LOGISTIKA", "Logistika i magacin", "Prijem, otprema i rokovi isporuke."),
    ("FINANSIJE", "Finansije", "Avansi, marže, troškovi i naplata."),
    ("ISTRAZIVANJE", "Istraživanje tržišta", "Konkurencija, cene i kretanja u branši."),
    ("KVALITET", "Kvalitet i usklađenost",
     "Pravila platformi, AI oznake, incidenti i provera pre objave."),
    ("RAZVOJ", "Razvoj i održavanje sistema",
     "Kod, testovi, puštanje i održavanje same korporacije (ADR-0034)."),
)

#: (code, sektor, naziv, nivo, specijalnost, odgovara, poslovi, koliko ljudi)
#: Šefovska mesta su za jednog; izvršilačka primaju više agenata, jer se posao
#: deli po jeziku, tržištu i smeni (ADR-0017, dopuna 24.09.).
POSITIONS: tuple[tuple[str, str, str, str, str, str | None, list[str], int], ...] = (
    ("DIR-00", "UPRAVA", "Direktor korporacije", L.HEAD, "vođenje", None,
     ["postavlja ciljeve sektorima", "prati merenja i troškove"], 1),
    ("UPR-ASI", "UPRAVA", "Asistent uprave", L.MEDIOR, "izveštaji", "DIR-00",
     ["sprema preglede za direktora", "prati rokove po sektorima"], 1),

    ("SEF-NAB", "NABAVKA", "Šef nabavke", L.HEAD, "dobavljači", "DIR-00",
     ["traži proizvođače", "ugovara uslove i robnu marku"], 1),
    ("NAB-REF", "NABAVKA", "Referent nabavke", L.MEDIOR, "proizvođači i uzorci",
     "SEF-NAB", ["traži i upoređuje dobavljače", "vodi prepisku o uzorcima"], 3),

    ("SEF-PRO", "PRODAJA", "Šef prodaje i izvoza", L.HEAD, "izvoz", "DIR-00",
     ["vodi tržišta", "priprema ponude"], 1),
    ("PRO-REF", "PRODAJA", "Referent prodaje", L.MEDIOR, "ponude i upiti",
     "SEF-PRO", ["odgovara na upite kupaca", "priprema nacrte ponuda"], 3),

    ("SEF-MKT", "MARKETING", "Šef marketinga", L.HEAD, "sadržaj", "DIR-00",
     ["planira teme i kalendar", "pušta sadržaj u odobrenje"], 1),
    ("URE-SR", "MARKETING", "Urednik sadržaja — B2B, srpski", L.SENIOR,
     "B2B, automatizacija, produktivnost", "SEF-MKT",
     ["piše nacrte objava sa izvorom", "odgovara na poslovnu poštu",
      "uči iz odluka urednika"], 2),
    ("MKT-DRU", "MARKETING", "Urednik društvenih mreža", L.MEDIOR,
     "kratke objave i zajednica", "SEF-MKT",
     ["prilagođava tekst platformi", "prati šta je odjeknulo"], 2),

    ("SEF-POD", "PODRSKA", "Šef podrške", L.HEAD, "korisnici", "DIR-00",
     ["prati poštu i upite", "vodi reklamacije"], 1),
    ("POD-SR", "PODRSKA", "Agent podrške — srpski", L.MEDIOR, "upiti i reklamacije",
     "SEF-POD", ["odgovara na pristigla pitanja", "prosleđuje ono što traži čoveka"], 3),

    ("SEF-LOG", "LOGISTIKA", "Šef logistike", L.HEAD, "otprema", "DIR-00",
     ["prati rokove", "usklađuje magacin i otpremu"], 1),
    ("LOG-REF", "LOGISTIKA", "Referent otpreme", L.MEDIOR, "rokovi i prevoznici",
     "SEF-LOG", ["prati pošiljke i rokove", "javlja kašnjenja pre nego što se vide"], 3),

    ("SEF-FIN", "FINANSIJE", "Šef finansija", L.HEAD, "marže", "DIR-00",
     ["prati avanse i marže", "prati troškove sistema"], 1),
    ("FIN-REF", "FINANSIJE", "Referent naplate", L.MEDIOR, "avansi i naplata",
     "SEF-FIN", ["prati ko je platio i ko kasni", "priprema podsetnike za naplatu"], 2),

    ("SEF-IST", "ISTRAZIVANJE", "Šef istraživanja", L.HEAD, "tržište", "DIR-00",
     ["prati konkurenciju i cene", "priprema nalaze za ostale sektore"], 1),
    ("IST-ANA", "ISTRAZIVANJE", "Analitičar tržišta", L.MEDIOR, "cene i konkurencija",
     "SEF-IST", ["prati cene i ponudu konkurencije", "piše kratke nalaze sa izvorom"], 3),

    ("SEF-KVA", "KVALITET", "Šef kvaliteta i usklađenosti", L.HEAD, "pravila", "DIR-00",
     ["prati pravila platformi i AI oznake", "vodi incidente"], 1),
    ("KVA-KON", "KVALITET", "Kontrolor usklađenosti", L.MEDIOR, "provera pre objave",
     "SEF-KVA", ["proverava oznake i tvrdnje pre objave", "prijavljuje odstupanja"], 2),

    # ADR-0034. Jedini sektor čiji se rezultat proverava mašinski — i jedini koji
    # dira ono što ostale ograničava. Zato su recenzent i testolog odvojena mesta.
    ("SEF-RAZ", "RAZVOJ", "Šef razvoja", L.HEAD, "vođenje razvoja", "DIR-00",
     ["prima zahteve za izmenu i deli ih na zadatke",
      "prima eskalaciju iz sektora"], 1),
    ("RAZ-ARH", "RAZVOJ", "Arhitekta sistema", L.SENIOR, "odluke i ADR", "SEF-RAZ",
     ["piše predlog ADR-a sa posledicama i onim što se odbacuje",
      "ne prihvata sopstveni predlog"], 2),
    ("RAZ-PRO", "RAZVOJ", "Programer", L.MEDIOR, "izmene u kodu", "SEF-RAZ",
     ["piše izmenu po zadatku, u granicama dozvoljenih fajlova",
      "predaje tek kad su kapije zelene"], 6),
    ("RAZ-REC", "RAZVOJ", "Recenzent koda", L.SENIOR, "pregled izmena", "SEF-RAZ",
     ["pušta determinističke provere pre modela",
      "piše nalaz sa fajlom, linijom i težinom", "nikad ne pregleda svoj rad"], 2),
    ("RAZ-TES", "RAZVOJ", "Testolog", L.MEDIOR, "testovi i regresije", "SEF-RAZ",
     ["piše test koji obara grešku pre nego što je neko popravi",
      "čuva zlatne skupove"], 2),
    ("RAZ-DEZ", "RAZVOJ", "Dežurni inženjer", L.MEDIOR, "puštanje i incidenti",
     "SEF-RAZ", ["pušta izmene i vraća ih unazad kad zatreba",
                 "prati logove, trošak i incidente"], 2),
    ("RAZ-BIB", "RAZVOJ", "Bibliotekar koda", L.MEDIOR, "zavisnosti i licence",
     "SEF-RAZ", ["prati licence i bezbednosne zakrpe zavisnosti",
                 "odbija zavisnost bez licence (ADR-0032)"], 1),
)

#: Modelovani dosije referentne persone (ADR-0017). Izmišljeno i dosledno.
MILA_DOSSIER = dict(
    birth_place="Novi Sad",
    residence="Beograd",
    height_cm=172,
    weight_kg=63,
    build="vitka",
    eye_color="smeđa",
    hair_color="tamno smeđa",
    hair_style="do ramena, ravna",
    marital_status="u vezi",
    children=0,
    hobbies=["planinarenje", "kuvanje", "čitanje o logistici"],
    appearance_prompt=(
        "Žena od oko 35 godina, srednje visine i vitke građe, tamno smeđa kosa do "
        "ramena, smeđe oči, prirodna šminka, poslovno-ležerna odeća u zemljanim "
        "tonovima, topao i sabran izraz lica."
    ),
)
MILA_BIRTH = date(1991, 4, 17)


#: ADR-0037 — šta koje radno mesto TRAŽI da bi se posao radio. Ovo NIJE dozvola:
#: motor pravila i dalje gleda samo `TrustState`, a agent premešten na mesto ne
#: dobija ništa (ADR-0017). Služi da se izmeri manjak i da se dodela ne kuca
#: capability po capability za svakog od 10.000 agenata.
#:
#: Oblik: "capability@nivo" ili "capability@nivo:opseg" (opseg samo za kod).
POSITION_NEEDS: dict[str, list[str]] = {
    # Sadržaj i publika
    "URE-SR": ["content.publish_approved@L1", "web.read_public@L0"],
    "POD-SR": ["email.reply_inbound@L2", "social.reply_inbound@L2"],
    "PRO-REF": ["email.reply_inbound@L2", "email.outbound_approved@L2"],
    "NAB-REF": ["email.reply_inbound@L2", "email.outbound_approved@L2",
                "web.read_public@L0"],
    "IST-ANA": ["web.read_public@L0", "social.read_public@L0"],

    # Razvoj (ADR-0034). Opseg je namerno uzak: niko ne traži ceo repozitorijum.
    "SEF-RAZ": ["code.read@L0", "review.comment@L1"],
    "RAZ-ARH": ["code.read@L0", "review.comment@L1"],
    "RAZ-PRO": ["code.read@L0", "test.run@L0",
                "code.write@L1:apps/content", "code.write@L1:apps/channels",
                "code.write@L1:console", "deploy.stage@L1"],
    "RAZ-REC": ["code.read@L0", "review.comment@L1", "test.run@L0"],
    "RAZ-TES": ["code.read@L0", "test.run@L0", "code.write@L1:tests"],
    "RAZ-DEZ": ["code.read@L0", "deploy.stage@L1"],
    "RAZ-BIB": ["code.read@L0", "dependency.add@L2"],
}


class Command(BaseCommand):
    help = "Postavlja sektore i radna mesta korporacije (ADR-0017)."

    def add_arguments(self, parser):
        parser.add_argument("--persona", default="",
                            help="Public ID persone koju treba rasporediti (npr. P-00001).")
        parser.add_argument("--actor", default="user:slobodan")
        parser.add_argument("--human-owner", default="user:slobodan")
        parser.add_argument("--spisak", action="store_true",
                            help="Samo ispiši radna mesta i ko ih drži.")

    def handle(self, *args, persona, actor, human_owner, **opts):
        if opts.get("spisak"):
            return self._spisak()
        if not actor.startswith("user:"):
            raise CommandError("--actor mora biti čovek (user:…).")
        now = timezone.now()
        with bind(actor_id=actor):
            deps = {}
            for order, (code, name, purpose) in enumerate(DEPARTMENTS):
                d, _ = Department.objects.update_or_create(
                    code=code,
                    defaults={"name": name, "purpose": purpose, "sort_order": order,
                              "human_owner": human_owner, "is_active": True})
                deps[code] = d
            made = {}
            for code, dep, title, level, specialty, _boss, duties, koliko in POSITIONS:
                p, _ = Position.objects.update_or_create(
                    code=code,
                    defaults={"department": deps[dep], "title": title, "level": level,
                              "specialty": specialty, "duties": duties,
                              "needs": POSITION_NEEDS.get(code, []),
                              "headcount_max": koliko})
                made[code] = p
            for code, _dep, _t, _l, _s, boss, _d, _k in POSITIONS:
                if boss:
                    Position.objects.filter(pk=made[code].pk).update(
                        reports_to=made[boss])
            self.stdout.write(f"Sektora: {len(deps)} · radnih mesta: {len(made)}.")

            if not persona:
                return
            p = Persona.objects.filter(public_id=persona).first()
            if p is None:
                raise CommandError(f"Persona {persona} ne postoji.")
            if not Assignment.objects.filter(persona=p, ended_at__isnull=True).exists():
                org.assign(p, made["URE-SR"], actor=actor, now=now,
                           note="Prvi raspored (ADR-0017).")
            pos = org.position_of(p)
            if org.dossier_of(p) is None:
                org.set_dossier(p, actor=actor, birth_date=MILA_BIRTH, now=now,
                                **MILA_DOSSIER)
            d = org.dossier_of(p)
            self.stdout.write(
                f"{p.public_id} · {pos.department.name} / {pos.title} · "
                f"dosije v{d.dossier_version}, {d.residence}.")

    def _spisak(self) -> None:
        """Ko gde radi — polazna tačka za `manage.py zaposli --mesto …`."""
        from apps.personas import org

        for d in Department.objects.order_by("sort_order"):
            self.stdout.write(f"\n{d.code}  {d.name}")
            for p in Position.objects.filter(department=d).order_by("code"):
                ko = ", ".join(x.display_name for x in org.holders(p)) or "slobodno"
                self.stdout.write(f"  {p.code:10} {p.title:34} {ko}")
