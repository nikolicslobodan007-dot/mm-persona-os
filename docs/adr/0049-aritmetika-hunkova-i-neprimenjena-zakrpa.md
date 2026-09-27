# ADR-0049 — Aritmetika hunkova u aplikaciji; zakrpa koja se nije primenila nije pala kapija

- **Status:** prihvaćen (27.09.2026.)
- **Prethodi:** ADR-0038 (zakrpa), ADR-0040 (poslušnik), ADR-0042 (merenje),
  ADR-0043 (rezultat u granu), ADR-0048 (diff bez `git` zaglavlja), ADR-0033 (pravilo nula)
- **Menja:** ADR-0040, deo o tome šta poslušnik prijavljuje kad posao padne

## Šta se desilo

Zakrpa iz ADR-0048, predata ponovo iz sačuvanog teksta, prošla je kao `ACCEPTED`
(3245 znakova, jedan fajl). Poslušnik ju je uzeo i stao:

```
greška: apply --check: error: corrupt patch at line 22
```

Prebrojavanje redova je pokazalo da su **oba `@@` zaglavlja pogrešna**:

```
red 3  : prijavljeno -6  +20 | izbrojano -6  +18   NE VALJA
red 22 : prijavljeno -14 +45 | izbrojano -17 +45   NE VALJA
```

To je agentov propust — zaglavlje hunka mora da odgovara telu. Ali oko te jedne
greške stoje dve naše:

1. **Pustili smo je kao `ACCEPTED`.** Zbir redova u hunku je čista aritmetika koju
   umemo da uradimo bez `git`-a; nismo je radili, pa je pokvarena zakrpa ušla u red
   i pala tek u poslušniku, daleko od onoga ko ju je napisao i bez poruke koja mu
   kaže šta da popravi.
2. **Poslušnik je upisao palu kapiju `pytest`.** Nijedan test nije pokrenut. Do sad
   je to bio jedini način da posao izađe iz reda (red gleda `ACCEPTED` bez kapija,
   ADR-0040), pa je neistina bila ugrađena u mehanizam.

Druga je teža. ADR-0042 celu meru gradi na tome da brojevi ne lažu; `ucinak` je i
ovde, drugi dan zaredom, prikazao našu grešku kao agentovu — ovog puta kao pali
test koji nikad nije pokrenut.

## Odluka

### 1. Zaglavlje hunka se proverava prebrojavanjem, u aplikaciji

`zakrpa._proveri_hunkove` broji redove svakog hunka i poredi sa `@@ -s,n +s,n @@`.
Kontekstni red se broji na obe strane, `-` samo na staroj, `+` samo na novoj,
`\ No newline at end of file` nigde. Prazan red je kontekst, jer uređivači seku
prateći razmak. Red koji ne počinje razmakom, `+`, `-` ni `\` je proza u hunku i
zakrpa se odbija.

Ova provera ide u aplikaciju, a ne u poslušnika, jer **ne traži `git`**. Provera
koja se može uraditi pre izlaska posla iz sistema pripada sistemu; ono što traži
radni primerak (`git apply --check`) ostaje tamo gde primerak i postoji.

Poruka imenuje red zaglavlja, oba zbira i šta da se uradi:

```
Zaglavlje u redu 22 kaže -14 +45, a hunk ima -17 +45. `git apply` ovo odbija kao
pokvarenu zakrpu; prebroj redove i ispravi `@@`.
```

Razlog stiže do pisca kroz brif (ADR-0041), pa sledeći pokušaj zna gde da gleda.

### 2. Provera ide POSLE čitanja putanja, i ne zahteva da hunk postoji

Prvo sam je stavio na vrh `paths_in`, sa uslovom „mora postojati `@@`". Devet
testova je palo i dobro su pali: **preimenovanje i izmena moda su valjane zakrpe
bez ijednog hunka**, a binarna zakrpa ima svoju poruku (`BINARY_PATCH`) koju je novi
uslov pregazio. Provera sada stoji na kraju `paths_in` i tvrdi samo ono što ume da
dokaže: svako zaglavlje koje **postoji** mora da odgovara svom telu.

Zapisano kao takvo, jer je to tačno ona pretpostavka iz ADR-0033 — da svaka zakrpa
mora imati hunk — koju nisam proverio prije nego što sam je ugradio u kapiju.

### 3. Zakrpa koja se nije primenila prijavljuje se kao takva

Nova tačka, jedina koju poslušnik dobija ovim ADR-om:

```
POST /api/v1/tasks/{task_id}/unapplied   {"patch": <uuid>, "reason": "<tekst>"}
```

`zakrpa.odbij_posle_provere` stavlja zakrpu na `REJECTED` sa razlogom
`nije se primenila: <tekst>` i upisuje `task.patch.unapplied` u zapis, sa
`severity=WARNING`. Time posao izlazi iz reda — jer red gleda `ACCEPTED` — a da se
ne izmišlja nijedan ishod kapije.

Izmerena zakrpa se ovim putem ne prepravlja (`ALREADY_MEASURED`): kapije su zapis i
ne brišu se time što je nešto posle njih puklo.

### 4. Poslušnik razlikuje pre-kapija od posle-kapija

`obradi` nosi zastavicu `prijavljeno`, koja se diže kad su svi ishodi kapija
poslati:

- greška **pre** nje → `POST /unapplied`, nijedna kapija se ne upisuje;
- greška **posle** nje → samo dnevnik. Kapije su izmerene i ostaju; neuspeo
  `push` nije stvar zakrpe;
- bez `patch_id` → nema šta da se odbije, greška ostaje u dnevniku.

### 5. Pad jednog zadatka više ne gasi poslušnika

Uz ovo se videlo i treće: `GET /work` stoji **pre** `try` u `obradi`, a `main` nije
imao nikakvu zaštitu oko poziva `obradi`. Jedan neuspeo poziv je dizao izuzetak kroz
`main` i gasio proces — red bi posle ćutao do sledećeg ručnog pokretanja, isto
ponašanje kao 25.09., samo iz drugog razloga. Komentar u kodu je tvrdio da poslušnik
„ne sme da padne na jednom zadatku"; sada je to i tačno.

## Šta je odbačeno

- **Poziv `git apply --check` u aplikaciji.** Slika aplikacije nema radni primerak
  (ADR-0041 §1), pa bi ga morala da napravi — a to je upravo posao poslušnika.
  Aritmetika ne traži ni jedno ni drugo.
- **Ispravljanje pogrešnog `@@` u naše ime.** Pretpostavka o tome šta je pisac
  hteo je najgora vrsta pretpostavke: zakrpa bi se primenila, a kod bi bio drugi od
  recenziranog.
- **Brisanje lažne kapije `pytest` sa postojeće zakrpe.** Zapis se ne doteruje da bi
  brojevi izgledali bolje (ADR-0046). Ostaje, uz ovaj ADR kao objašnjenje.
- **Nov status `UNAPPLIED` u `PatchStatus`.** `REJECTED` sa razlogom nosi istu
  informaciju, a enum se ne širi za stanje koje se od `REJECTED` ne razlikuje ni u
  jednom postupku (Canon `common/enums.py`).
- **Da poslušnik zatvori zadatak kad se zakrpa ne primeni.** „Gotovo" i dalje nije
  njegova odluka (ADR-0039 §3).

## Posledice

- `zakrpa._HUNK`, `_nov_fajl`, `_proveri_hunkove`, `odbij_posle_provere`;
  `api/views/zadaci.py` → `UnappliedIn`, `TaskUnappliedView`; nova ruta
  `task-unapplied`; `runner.obradi` → `prijavljeno`, `runner.main` → `try` oko
  `obradi`.
- Ugovor je ponovo izdat — `contracts/openapi/persona-os-v1.yaml` nosi
  `tasks_unapplied`.
- 31 nova provera: `tests/test_zakrpa.py` (aritmetika i neprimenjena zakrpa),
  `tests/test_api_zadaci.py` (tačka), `tests/test_runner.py` (pre/posle kapija,
  petlja). Ukupno 955.
- Nema migracije.
- Dva postojeća testa su imala ogromnu zakrpu sa zaglavljem `@@ -1 +1 @@` nad telom
  od 9001 reda — plafon su merili zakrpom koju `git apply` ne bi primio. Oba sad
  grade istu zakrpu sa ispravnim zaglavljem, kroz `_ogroman()`.

## Zapisano za ADR-0033

Treći dan zaredom se naša greška pojavila u `ucinak`-u kao agentova: 26.09. odbijena
valjana zakrpa (ADR-0048), 27.09. pali test koji nije pokrenut. Obrazac je isti —
mesto gde se posao meri prima podatke od koda koji nije pisan da bi merio pošteno,
nego da bi posao krenuo dalje.

I moja greška u ovom istom ADR-u: proveru sam stavio na vrh `paths_in`, sa uslovom da
hunk mora postojati. Testovi su je odbili u prvom prolazu — devet njih, uključujući
preimenovanje i binarnu zakrpu. Pretpostavka je bila da svaka zakrpa ima `@@`.
Nisam je proverio; `zakrpa.py`, koji sam u tom trenutku čitao, imao je test
`test_preimenovanje_daje_obe_putanje` koji to izričito obara.
