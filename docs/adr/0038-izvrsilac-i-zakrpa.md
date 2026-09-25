# ADR-0038 — Izvršilac: radni primerak po zadatku i zakrpa kao kapija

- **Status:** prihvaćen (25.09.2026.)
- **Prethodi:** ADR-0034 (departman, zaštićene zone), ADR-0035 (model zadatka),
  ADR-0036 (mašinska recenzija), ADR-0037 (poverenje po mestu), ADR-0033 (pravilo nula)
- **Canon:** §9.6 (kill-switch), §12 (izvršenje), §16.5 (audit)

## Problem

Departman za programiranje ima radna mesta, ljude, poverenje po opsegu, model zadatka
i mašinsku recenziju. Nema ruke. Nijedan agent nema radni primerak repozitorijuma ni
ljusku, pa `may_touch` danas vraća **mišljenje** — niko ga ne pita pre nego što se fajl
stvarno promeni, jer nema ko da menja fajlove.

Dok je tako, ceo departman je dobro projektovana ograda oko prazne njive.

## Odluka

### 1. Radni primerak po zadatku, na sopstvenoj privatnoj mreži

Svaki zadatak dobija svoj kontejner i svoj primerak repozitorijuma. Izvor je 7,3 MB —
kopija je jeftina; skupo je ono što se u njoj vrti.

**„Bez mreže" mora da znači tačno šta.** Kapije traže bazu: `pytest` bez Postgresa
preskoči sve i vrati lažno zeleno — to smo videli uživo. Kontejner bez mrežnog
namespace-a zato ne radi. Umesto toga:

- mreža po zadatku, `internal: true` — **nema rute ka internetu**;
- na njoj su samo radni kontejner i **jednokratni Postgres** koji nestaje sa zadatkom;
- **nema** produkcijske baze, `secrets` volumena, MinIO-a, Redisa, Mailcow-a.

Zadatak koji stvarno traži mrežu (nova zavisnost) je poseban slučaj i traži odobrenje;
ne rešava se otvaranjem mreže svima.

### 2. Aplikacija nikada ne dobija `docker.sock`

Da bi Django pokrenuo kontejner, treba mu Docker socket. **Docker socket je root na
hostu.** Danas ga nijedan servis nema — proveravano u `docker-compose.prod.yml` — i to
se ne menja. Kad bi ga `web` ili worker dobio, svaka greška u aplikaciji postala bi
root na mašini, a zaštićene zone dekor: do njih se stiže ispod aplikacije.

Zato **poslušnik** (`runner`) živi **van aplikacije**, kao systemd jedinica na hostu:

- jedini ima pristup Docker-u;
- uzima posao preko API-ja i prima **samo `task_id`**;
- ništa što agent napiše ne stiže do njega kao komanda, ime, putanja ni zastavica.

Granica koja ne prolazi kroz Python ne može da padne na grešci u Python-u.

### 3. Agent predaje zakrpu; sistem je primenjuje

Agent ne piše fajlove. Agent vraća **unified diff**. Sistem ga prima, proverava i tek
onda primenjuje. Ljuska postoji — u kontejneru, i niko je ne drži.

Pre primene, **svaka** putanja iz zakrpe prolazi `may_touch` (zaštićena zona →
dozvoljeni prefiks zadatka → poverenje ≥ L1 na toj putanji). Uz to se odbija:

- **preimenovanje kod kog i stara i nova putanja ne prolaze.** Ako se proverava samo
  nova, izmena u `apps/policy` se provuče tako što se fajl prvo preimenuje.
- **`..` u putanji i apsolutna putanja.** `git apply` ume da piše van radnog
  direktorijuma.
- **promena moda u simbolički link** (`120000`). Posle nje obična putanja pokazuje gde
  hoće, pa sve provere putanja postaju bezvredne.
- **binarna zakrpa.** Blob koji niko ne može da pročita se ne recenzira, pa ni ne ulazi.
- **navodnicima zaštićena putanja** (`"a/fajl\ts imenom"`) se prvo dekodira, pa proverava;
  ako dekodiranje ne uspe, zakrpa se odbija. Ime fajla ne sme da bude način da se
  provera preskoči.

Zakrpa je **zapis** (`TaskPatch`), ne poruka: ko ju je predao, nad kojim commit-om,
šta je dirala, da li je prošla i zašto nije.

### 4. Rezultat ide na granu, `main` dobija samo čovek

Grana `zadatak/TSK-…`; commit nosi **agenta kao autora** i sistem kao pošiljaoca, pa se
u istoriji vidi ko je pisao. `push` samo na tu granu.

`main` menja isključivo ljudska ruka. To i nije samo pravilo: deploy ključ na serveru
je read-only, pa server danas ne može ni da gura. Ako poslušnik dobije ključ sa
pisanjem, ide uz zaštitu grane `main`, ne uz poverenje.

### 5. Jedan zadatak u isto vreme na ovoj mašini

CX23 ima 2 vCPU i 4 GB. Pun prolaz kapija traje oko dva i po minuta i traži svoju bazu.
To je **jedan zadatak u isto vreme**, ne petnaest. „Petnaestak istovremeno" iz ADR-0034
je granica sudara u kodu; granica mašine je mnogo niža i stiže prva. Paralelizam počinje
na farmi, ne ovde.

### 6. Zelene kapije nisu ispravnost

Recenzija puštena 25.09. našla je dve rupe u kodu koji je prošao svih 675 testova.
Kapije znače „nije pokvarilo ono što testiramo", ne „ispravno je". Zato ljudska kapija
pred `main` stoji dok ne postoji izmereno — to je pravilo nula (ADR-0033) primenjeno na
ovaj postupak, a ne nepoverenje prema njemu.

## Šta je odbačeno

- **Zajednički radni direktorijum sa zaključavanjem.** Jeftinije, ali pravi sudare, a
  zaključavanje koje neko zaobiđe je gore od nikakvog.
- **`docker.sock` u aplikaciji**, u bilo kom obliku, uključujući „samo za čitanje".
- **Da agent piše fajlove direktno, uz proveru posle.** Provera koju je moguće
  zaboraviti nije kapija.
- **`push` na `main` iz sistema**, čak i kad su sve kapije zelene.
- **Otvaranje mreže radnom kontejneru zato što je zgodno** za instalaciju paketa.

## Posledice

- `apps/orchestration/zakrpa.py` — čitanje i provera zakrpe; `TaskPatch` + migracija;
  `manage.py zakrpa --proveri | --prihvati`.
- `deploy/runner/` — systemd jedinica i compose za radni kontejner sa `internal: true`
  mrežom i jednokratnim Postgresom. Ovo se ne može pokriti testovima kao logika i zato
  ide kao zaseban korak, posle kapije.
- Sledeće, odvojeno: ko i čime pozove model da napiše zakrpu (trošak po zadatku,
  najviše iteracija, prekidač „nema napretka" iz OpenHuman beležaka).
