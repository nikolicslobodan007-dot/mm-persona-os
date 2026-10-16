# ADR-0095 — Ponovni uvoz osvežava ono što je čovek doneo

- **Status:** prihvaćen (16.10.2026.)
- **Povod:** Posle ADR-0077 §3 polja `commit_sha` i `file_path` postoje, ali
  posle ponovnog uvoza stoje prazna. Izmereno u produkciji, 16.10.
- **Prethodi:** ADR-0077 §3, ADR-0074, ADR-0076, ADR-0059, ADR-0055, ADR-0033
- **Menja:** `apps/memory/vestine.py` — `uvezi()` pri ponovnom uvozu osvežava
  podatke izvora. Testovi uz to.
- **Canon:** §10.4

## Izmereno

Uvoz 16.10. je prosledio `--commit` i `--putanja`, i prošao uredno
(`{'upisano': 13, 'obrisano': 13}`). Red izvora posle toga:

```
uri: git:mm-persona-os/docs/adr@bb52d10
commit_sha: ''
file_path: ''
```

Uzrok je u `uvezi()`:

```python
izvor, _ = KnowledgeSource.objects.get_or_create(
    persona=None, title=naslov_izvora,
    defaults={... "uri": uri, "license_box": ..., "license_note": ...})
```

`defaults` važe **samo pri prvom upisu**. Svaki sledeći uvoz istog izvora ih
tiho ignoriše. To nije bio problem dok se nosio samo `uri`, koji se retko
menja — a `commit_sha` se menja **pri svakom uvozu**, pa polje radi tačno
jednom i posle toga laže.

Ovo nije promaklo agentu: brif za ADR-0077 §3 to nije ni tražio. Rupa je
starija od tog zadatka.

## Odluka

Ponovni uvoz **osvežava** podatke koje je čovek doneo uz materijal: `uri`,
`license_box`, `license_note`, `commit_sha` i `file_path`.

Obrazloženje je isto za svih pet: svi dolaze od čoveka pri svakom uvozu
(ADR-0074, ADR-0059, ADR-0077 §3). Novija vrednost je tačnija od starije, a
tiho zadržana stara vrednost je zapis koji laže — gore od zapisa kojeg nema
(ADR-0033).

Isti obrazac kao za same činjenice: ponovni uvoz ih briše i upisuje ponovo
(ADR-0055). Izvor do sada nije pratio to pravilo; sada prati.

## Šta se ovim NE menja

`ingested_at` ostaje kakav jeste — pečat se i dalje upisuje tek kad su veštine
stvarno upisane (ADR-0076 tačka 2).

`persona` i `title` su ključ po kom se izvor pronalazi i ne diraju se.

`trust_score` se ne osvežava: njega ne donosi čovek uz materijal nego ga nosi
sam izvor, i njegova promena je zasebna odluka.

Posle ove izmene `uri` više ne nosi commit ugurat kao niz znakova
(`…/docs/adr@bb52d10`) — to je bila privremena zakrpa od 15.10. dok polja nije
bilo. Prvi uvoz posle ove izmene je ispravlja.

## Ispravka — `ingested_at` se prepisuje pri svakom uvozu (16.10., posle prve zakrpe)

Odeljak „Šta se ovim NE menja" je tačan ali nedovoljno precizan, i brif koji
je iz njega napisan bio je netačan. Zato ovde stoji mereno stanje.

U `apps/memory/vestine.py`, na kraju iste transakcije, stoji od ADR-0076 §2:

```python
if vestine:
    izvor.ingested_at = timezone.now()
    izvor.save(update_fields=["ingested_at"])
```

Dakle `ingested_at` se **prepisuje pri svakom uvozu koji ima veštine**. Ono
što ADR-0095 tvrdi jeste uže: osvežavanje pet polja ne dira `ingested_at` —
pečat i dalje upisuje isključivo kod iz ADR-0076 §2, po svom pravilu.

Brif za zadatak TSK-01M51X7N4JC62J82TM8VQQYQ1G je to skratio u „NE diraj:
ingested_at", što čita kao da polje posle ponovnog uvoza ostaje isto. Agent je
tu rečenicu verno sproveo i napisao test koji zamrzne sat pa tvrdi da
jednakost `ingested_at` dokazuje da ga naša izmena nije dotakla. Ne dokazuje:
polje se svakako prepisuje, a sa zamrznutim satom prepiše se istom vrednošću.
Test bi prošao i da je izmena pokvarila to polje — to je prazna straža, a
prazna straža je gora od nepostojeće, jer se čovek na nju osloni (ADR-0033).

Greška je čovekova, u brifu, ne agentova.

Zato, kao pravilo za testove oko ovog polja:

1. Test NE SME da tvrdi da `ingested_at` ostaje isti posle ponovnog uvoza sa
   veštinama. Izmereno je suprotno.
2. Ponašanje koje se sme proveravati jeste da se pečat upisuje kad ima
   veština, a da se ne upisuje kad ih nema (ADR-0076 §2) — i da ga upis pet
   polja iz ADR-0095 ne upisuje sam po sebi: uvoz sa praznim spiskom veština
   osvežava pet polja i ostavlja `ingested_at` nedirnut.
3. Zamrzavanje sata se ne koristi da bi se dobila jednakost koja ništa ne
   tvrdi.
