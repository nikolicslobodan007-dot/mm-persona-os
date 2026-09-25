"""Poverenje po agentu, sposobnosti i opsegu. ADR-0034.

    manage.py poverenje --persona P-00027                    (šta ko sme)
    manage.py poverenje --persona P-00027 --sposobnost code.write \\
        --opseg apps/content --nivo L1 --razlog "prvi zadatak"
    manage.py poverenje --zone                               (zaštićene zone)
    manage.py poverenje --proveri apps/policy/service.py --persona P-00027

Opseg je prefiks putanje. Najduži opseg koji odgovara putanji pobeđuje, pa
`L0` na `apps/policy/` obara opšti `L1`. Zaštićene zone se ne otvaraju ni na
jednom nivou — one se menjaju ADR-om, ne komandom.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from api.context import bind
from apps.personas import ovlascenja
from apps.personas.models import Persona, Position
from apps.policy import service
from apps.policy.models import TrustState
from common import enums as E


class Command(BaseCommand):
    help = "Prikaz i dodela poverenja po opsegu (ADR-0034)."

    def add_arguments(self, parser):
        parser.add_argument("--persona", default="")
        parser.add_argument("--sposobnost", default="")
        parser.add_argument("--opseg", default="", help="Prefiks putanje, npr. apps/content")
        parser.add_argument("--nivo", default="", help="L0, L1 ili L2")
        parser.add_argument("--razlog", default="")
        parser.add_argument("--zone", action="store_true", help="Ispiši zaštićene zone.")
        parser.add_argument("--proveri", default="", help="Putanja koju treba proveriti.")
        parser.add_argument("--manjak", action="store_true",
                            help="Šta nedostaje do onoga što radno mesto traži (ADR-0037).")
        parser.add_argument("--sektor", default="", help="Uz --manjak: ceo sektor, npr. RAZVOJ.")
        parser.add_argument("--po-mestu", dest="po_mestu", default="",
                            help="Dodeli tačno manjak svima na tom mestu, npr. RAZ-PRO.")
        parser.add_argument("--actor", default="user:slobodan")

    def handle(self, *args, persona, sposobnost, opseg, nivo, razlog, zone, proveri,
               manjak, sektor, po_mestu, actor, **opts):
        if zone:
            self.stdout.write("Zaštićene zone — nijedan agent, nijedan nivo (ADR-0034):")
            for z in service.config.protected_paths():
                self.stdout.write(f"  {z}")
            return

        if proveri and not persona:
            zona = service.path_is_protected(proveri)
            self.stdout.write(f"{proveri}: " + (
                self.style.ERROR(f"zaštićena zona ({zona})") if zona
                else self.style.SUCCESS("nije zaštićena")))
            return

        if po_mestu:
            self._po_mestu(po_mestu, razlog, actor)
            return

        if manjak:
            self._manjak(persona, sektor)
            return

        if not persona:
            raise CommandError("Treba --persona (ili --zone, --manjak, --po-mestu).")
        p = Persona.objects.filter(public_id=persona).first()
        if p is None:
            raise CommandError(f"Persona {persona} ne postoji.")

        if proveri:
            zona = service.path_is_protected(proveri)
            if zona:
                self.stdout.write(self.style.ERROR(
                    f"{proveri}: zaštićena zona ({zona}) — niko ne dira."))
                return
            cap = sposobnost or "code.write"
            lv = service.trust_for(p, cap, proveri)
            stil = self.style.SUCCESS if lv != E.TrustLevel.L0 else self.style.WARNING
            self.stdout.write(f"{p.public_id} · {cap} · {proveri} → " + stil(lv.value))
            return

        if sposobnost and nivo:
            if not razlog.strip():
                raise CommandError("Promena poverenja traži --razlog.")
            try:
                lv = E.TrustLevel(nivo.upper())
            except ValueError as e:
                raise CommandError(f"Nepoznat nivo {nivo!r} (L0, L1, L2).") from e
            with bind(actor_id=actor):
                try:
                    promenjeno = service.change_trust(p, sposobnost, lv, actor=actor,
                                                      reason=razlog, scope=opseg)
                except service.PolicyError as e:
                    raise CommandError(str(e)) from e
            gde = opseg or "svuda"
            self.stdout.write(self.style.SUCCESS(
                f"{p.public_id} · {sposobnost} · {gde} → {lv.value}"
                + ("" if promenjeno else "  (bez promene)")))
            return

        redovi = TrustState.objects.filter(persona=p).order_by("capability", "scope")
        if not redovi:
            self.stdout.write(f"{p.public_id}: nema nijednog zapisa — sve je L0.")
            return
        self.stdout.write(f"{p.public_id} · {p.display_name}")
        for t in redovi:
            self.stdout.write(f"  {t.capability:24} {t.scope or 'svuda':28} {t.level}")

    # ------------------------------------------------------------- ADR-0037

    def _mesta(self, sektor: str):
        redovi = Position.objects.select_related("department").order_by("code")
        if sektor:
            redovi = redovi.filter(department__code=sektor.upper())
            if not redovi:
                raise CommandError(f"Sektor {sektor!r} nema nijedno radno mesto.")
        return redovi

    def _manjak(self, persona: str, sektor: str):
        """Poredi šta posao traži sa onim što agent ima. Ne menja ništa."""
        if persona:
            p = Persona.objects.filter(public_id=persona).first()
            if p is None:
                raise CommandError(f"Persona {persona} ne postoji.")
            ljudi = [p]
        else:
            ljudi = sorted(
                {a for m in self._mesta(sektor) for a in ovlascenja.personas_on(m)},
                key=lambda x: x.public_id)
        if not ljudi:
            self.stdout.write("Nema nijednog zaposlenog agenta po tom filteru.")
            return
        ukupno = 0
        for p in ljudi:
            nedostaje = ovlascenja.gap_for(p)
            mesta = ", ".join(m.code for m in ovlascenja.positions_of(p)) or "bez mesta"
            if not nedostaje:
                self.stdout.write(self.style.SUCCESS(
                    f"{p.public_id}  {mesta:10} nema manjka"))
                continue
            ukupno += len(nedostaje)
            self.stdout.write(f"{p.public_id}  {mesta:10} {p.display_name}")
            for t in nedostaje:
                self.stdout.write(self.style.WARNING(f"    nedostaje  {t}"))
        self.stdout.write(f"\nUkupno nedostaje: {ukupno} stavki kod {len(ljudi)} agenata.")

    def _po_mestu(self, kod: str, razlog: str, actor: str):
        """Daje TAČNO manjak, svakom na tom mestu — jedan red u auditu po agentu."""
        if not razlog.strip():
            raise CommandError("Dodela traži --razlog.")
        mesto = Position.objects.filter(code=kod.upper()).first()
        if mesto is None:
            raise CommandError(f"Radno mesto {kod!r} ne postoji.")
        trazi = ovlascenja.needs_of(mesto)
        if not trazi:
            raise CommandError(f"{mesto.code} ne traži nijednu sposobnost "
                               f"(prazan `needs` — ADR-0037 §1).")
        ljudi = ovlascenja.personas_on(mesto)
        if not ljudi:
            self.stdout.write(f"{mesto.code}: nema nijednog zaposlenog agenta.")
            return

        dato = 0
        with bind(actor_id=actor):
            for p in ljudi:
                nedostaje = ovlascenja.gap_for(p, mesto)
                if not nedostaje:
                    self.stdout.write(f"{p.public_id}  nema manjka")
                    continue
                for t in nedostaje:
                    try:
                        service.change_trust(p, t.capability, t.level, actor=actor,
                                             reason=razlog, scope=t.scope)
                    except service.PolicyError as e:
                        raise CommandError(f"{p.public_id} · {t}: {e}") from e
                    dato += 1
                    self.stdout.write(self.style.SUCCESS(f"{p.public_id}  dato  {t}"))
        self.stdout.write(
            f"\n{mesto.code} · {mesto.title}: {dato} dodela kod {len(ljudi)} agenata.")
