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
)

#: (code, sektor, naziv, nivo, specijalnost, odgovara, poslovi)
POSITIONS: tuple[tuple[str, str, str, str, str, str | None, list[str]], ...] = (
    ("DIR-00", "UPRAVA", "Direktor korporacije", L.HEAD, "vođenje", None,
     ["postavlja ciljeve sektorima", "prati merenja i troškove"]),
    ("SEF-NAB", "NABAVKA", "Šef nabavke", L.HEAD, "dobavljači", "DIR-00",
     ["traži proizvođače", "ugovara uslove i robnu marku"]),
    ("SEF-PRO", "PRODAJA", "Šef prodaje i izvoza", L.HEAD, "izvoz", "DIR-00",
     ["vodi tržišta", "priprema ponude"]),
    ("SEF-MKT", "MARKETING", "Šef marketinga", L.HEAD, "sadržaj", "DIR-00",
     ["planira teme i kalendar", "pušta sadržaj u odobrenje"]),
    ("SEF-POD", "PODRSKA", "Šef podrške", L.HEAD, "korisnici", "DIR-00",
     ["prati poštu i upite", "vodi reklamacije"]),
    ("SEF-LOG", "LOGISTIKA", "Šef logistike", L.HEAD, "otprema", "DIR-00",
     ["prati rokove", "usklađuje magacin i otpremu"]),
    ("SEF-FIN", "FINANSIJE", "Šef finansija", L.HEAD, "marže", "DIR-00",
     ["prati avanse i marže", "prati troškove sistema"]),
    ("SEF-IST", "ISTRAZIVANJE", "Šef istraživanja", L.HEAD, "tržište", "DIR-00",
     ["prati konkurenciju i cene", "priprema nalaze za ostale sektore"]),
    ("SEF-KVA", "KVALITET", "Šef kvaliteta i usklađenosti", L.HEAD, "pravila", "DIR-00",
     ["prati pravila platformi i AI oznake", "vodi incidente"]),
    ("URE-SR", "MARKETING", "Urednik sadržaja — B2B, srpski", L.SENIOR,
     "B2B, automatizacija, produktivnost", "SEF-MKT",
     ["piše nacrte objava sa izvorom", "odgovara na poslovnu poštu",
      "uči iz odluka urednika"]),
    ("POD-SR", "PODRSKA", "Agent podrške — srpski", L.MEDIOR, "upiti i reklamacije",
     "SEF-POD", ["odgovara na pristigla pitanja", "prosleđuje ono što traži čoveka"]),
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


class Command(BaseCommand):
    help = "Postavlja sektore i radna mesta korporacije (ADR-0017)."

    def add_arguments(self, parser):
        parser.add_argument("--persona", default="",
                            help="Public ID persone koju treba rasporediti (npr. P-00001).")
        parser.add_argument("--actor", default="user:slobodan")
        parser.add_argument("--human-owner", default="user:slobodan")

    def handle(self, *args, persona, actor, human_owner, **opts):
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
            for code, dep, title, level, specialty, _boss, duties in POSITIONS:
                p, _ = Position.objects.update_or_create(
                    code=code,
                    defaults={"department": deps[dep], "title": title, "level": level,
                              "specialty": specialty, "duties": duties})
                made[code] = p
            for code, _dep, _t, _l, _s, boss, _d in POSITIONS:
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
