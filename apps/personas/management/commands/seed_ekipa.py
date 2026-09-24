"""Zapošljava prvu ekipu korporacije. ADR-0028.

    manage.py seed_ekipa --pokazi        (ko je na spisku, bez upisa)
    manage.py seed_ekipa                 (zapošljava sve koji još ne postoje)
    manage.py seed_ekipa --samo NABAVKA  (samo jedan sektor)

Idempotentno: agent koji već postoji (po slug-u) se preskače, ne duplira i ne
menja. Puno radno mesto se preskače sa razlogom, ne ruši ostatak.

Svaki agent prolazi kroz isti `hiring.hire()` kao i prvi (ADR-0023): rađa se
kao `DRAFT`, prelazi u `READY` kroz pravi prelaz statusa, dobija `L0` na svemu
i nijedan stvarni nalog.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from api.context import bind
from apps.personas import ekipa as spisak
from apps.personas import hiring, org
from apps.personas.models import Persona, Position


class Command(BaseCommand):
    help = "Zapošljava prvu ekipu: po nekoliko agenata na svakom radnom mestu."

    def add_arguments(self, parser):
        parser.add_argument("--pokazi", action="store_true")
        parser.add_argument("--samo", default="", help="Šifra sektora (npr. NABAVKA).")
        parser.add_argument("--actor", default="user:slobodan")

    def handle(self, *args, pokazi, samo, actor, **opts):
        mesta = {p.code: p for p in Position.objects.select_related("department")}
        redovi = [r for r in spisak.EKIPA
                  if not samo or mesta.get(r["mesto"]) is not None
                  and mesta[r["mesto"]].department.code == samo.upper()]
        if not redovi:
            raise CommandError("Spisak je prazan — proveri --samo.")

        if pokazi:
            for r in redovi:
                mesto = mesta.get(r["mesto"])
                gde = f"{mesto.department.name} / {mesto.title}" if mesto else "NEMA MESTA"
                stanje = "postoji" if self._postoji(r["ime"]) else "novo"
                self.stdout.write(f"  {stanje:8} {r['ime']:22} {r['mesto']:8} {gde}")
            self.stdout.write(f"\nUkupno na spisku: {len(redovi)}")
            return

        napravljeno, preskoceno = [], []
        for r in redovi:
            if self._postoji(r["ime"]):
                preskoceno.append(f"{r['ime']}: već postoji")
                continue
            mesto = mesta.get(r["mesto"])
            if mesto is None:
                preskoceno.append(f"{r['ime']}: radno mesto {r['mesto']} ne postoji")
                continue
            try:
                with bind(actor_id=actor):
                    p = hiring.hire(name=r["ime"], position=mesto, actor=actor,
                                    niches=[n.strip() for n in r.get("nise", "").split(",")
                                            if n.strip()])
                    org.set_dossier(p, actor=actor, birth_date=r.get("rodjen"),
                                    **spisak.dosije_od(r))
            except (hiring.HiringError, org.OrgError) as e:
                preskoceno.append(f"{r['ime']}: {e}")
                continue
            napravljeno.append(f"{p.public_id} {p.display_name} → {mesto.code}")

        for red in napravljeno:
            self.stdout.write(self.style.SUCCESS(f"  {red}"))
        for red in preskoceno:
            self.stdout.write(self.style.WARNING(f"  {red}"))
        self.stdout.write(f"\nZaposleno: {len(napravljeno)}, preskočeno: "
                          f"{len(preskoceno)}.")
        if napravljeno:
            self.stdout.write(
                "Svi su READY, sa L0 na svemu i bez ključa modela — dok im ne daš "
                "ključ, nacrte bi im pisao lokalni šablon.")
            self._bez_sanducica()

    def _bez_sanducica(self) -> None:
        """Sandučić se otvara sam na READY, ali može da padne (kvota domena).

        Zapošljavanje se zbog toga ne prekida — ali se ne prećutkuje ni to ko je
        ostao bez sandučića (nalaz 24.09.).
        """
        from apps.channels import mailbox

        if not mailbox.enabled():
            return
        fale = [p for p in Persona.objects.order_by("public_id")
                if mailbox.mailbox_of(p) is None]
        if fale:
            self.stdout.write(self.style.WARNING(
                f"Bez sandučića: {len(fale)} ({', '.join(p.public_id for p in fale)}). "
                "Proveri `manage.py mailbox bez`, pa `mailbox popuni`."))

    @staticmethod
    def _postoji(ime: str) -> bool:
        return Persona.objects.filter(slug=hiring.slugify_sr(ime)).exists()
