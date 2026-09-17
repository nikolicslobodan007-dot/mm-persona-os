# Zakup i postavljanje servera

Cilj: jedan Hetzner Cloud VM koji nosi F1 do kraja Pilota B (44 dana), sa
mogućnošću da se u dva minuta poveća ako zatreba.

---

## 0. Pre nego što otvoriš Hetzner

### SSH ključ

Bez ovoga ne ideš dalje. U PowerShell-u na Windows-u:

```powershell
ssh-keygen -t ed25519 -C "slobodan@mm-persona-os"
```

Tri puta Enter (podrazumevana putanja, bez lozinke ili sa — kako hoćeš).
Javni ključ je u `C:\Users\PC\.ssh\id_ed25519.pub`. Otvori ga i kopiraj ceo
sadržaj — jedan red koji počinje sa `ssh-ed25519`.

Privatni ključ (`id_ed25519`, bez `.pub`) **nikada nigde ne ide.**

### DNS zapis

Odluči poddomen sada, npr. `persona.mercatomaster.com`. A zapis podesiš
posle koraka 1, kad dobiješ IP. Caddy neće moći da izda sertifikat dok DNS
ne pokazuje na server.

---

## 1. Kreiranje servera

`console.hetzner.cloud` → **New project** → ime projekta: `MM Persona OS`
→ **Add Server**

| Polje | Izbor | Zašto |
|---|---|---|
| **Location** | Falkenstein (ili Nürnberg) | ~30 ms do Beograda, najveći kapacitet, EU |
| **Image** | Ubuntu 24.04 | LTS do 2029, `provision.sh` je pisan za nju |
| **Type** | Shared vCPU → x86 → **CX23** *(CX43 kad se vrati na stanje)* | vidi §1a |
| **Networking** | Public IPv4 **i** IPv6 | IPv4 je obavezan, mnogo servisa još ne zna IPv6 |
| **SSH keys** | Add SSH key → nalepi `.pub` sadržaj | Bez ovoga Hetzner šalje root lozinku mejlom |
| **Volumes** | ništa | disk servera je dovoljan; volume se kasnije ne može skinuti |
| **Firewall** | **Create firewall** → vidi dole | Stoji ISPRED mašine; Docker ga ne može zaobići |
| **Backups** | **uključi** (+20 % cene servera) | 7 dnevnih snimaka celog diska, jedan klik za povratak |
| **Placement group** | ništa | Ima smisla tek kod više mašina |
| **Name** | `mm-persona-os-01` | |

### 1a. Kad je CX43 zasivljen

Od 26.06.2026. Hetzner ima zvaničan incident *„Limited availability of cloud
instances"* — nedostatak hardvera. **CX33, CX43, CX53 i ceo CAX niz su
rasprodati u svim lokacijama.** Jedini CX koji se drži na stanju je CX23.
Zaliha se vraća u talasima, po nekoliko sati.

Ne kupovati zamenu iz drugog niza — cene posle poskupljenja od 15.06.2026:

| Plan | vCPU / RAM / disk | € / mes | odnos prema CX43 |
|---|---|---|---|
| CX43 | 8 / 16 GB / 160 GB | 15,99 | — |
| CPX42 | 8 / 16 GB / 320 GB | 69,49 | **4,3×** za isti RAM |
| CPX32 | 4 / 8 GB / 160 GB | 35,49 | 2,2× za pola RAM-a |
| CCX23 | 4 dedic. / 16 GB / 160 GB | 85,99 | 5,4× |

**Uzmi CX23 (2 vCPU / 4 GB / 40 GB, 5,49 €) sada.** Nosi F1–F5 bez problema
— jedna persona, prazna baza, bez browsera. Podešavanja u `.env.prod` su već
kalibrisana za 4 GB. Kad se CX43 pojavi, Rescaling ga menja za dva minuta.

Praćenje zalihe: <https://radar.iodev.org/cloud-status>.

### Firewall pravila (Inbound)

| Port | Protokol | Izvor |
|---|---|---|
| 22 | TCP | tvoja IP adresa `x.x.x.x/32` — ili `0.0.0.0/0` ako ti je IP dinamički |
| 80 | TCP | `0.0.0.0/0`, `::/0` |
| 443 | TCP | `0.0.0.0/0`, `::/0` |

Outbound: sve dozvoljeno.

> Zašto i Hetznerov firewall i `ufw` u skripti: Docker upisuje pravila
> direktno u `iptables` i time **zaobilazi ufw**. Port koji objaviš u
> compose-u postaje javan bez obzira na ufw. Hetznerov firewall je izvan
> mašine i to ne može da mu se desi. Zato su u `docker-compose.prod.yml`
> Postgres, Redis i MinIO vezani na `127.0.0.1` — to je treći, stvarni sloj.

**Create & Buy now.** Naplata je po satu; mesečna cena je gornja granica.

---

## 2. DNS

Kad dobiješ IP, kod registratora domena:

```
A    persona    <IP servera>    TTL 300
```

Proveri pre nastavka:

```powershell
nslookup persona.mercatomaster.com
```

---

## 3. Priprema mašine

```bash
ssh root@<IP>
```

Prihvati otisak ključa. Zatim:

```bash
curl -fsSL -o provision.sh \
  https://raw.githubusercontent.com/<nalog>/mm-persona-os/main/deploy/provision.sh
bash provision.sh mm
```

Traje 3–5 minuta. Skripta pravi korisnika `mm`, gasi root prijavu i lozinke,
diže ufw i fail2ban, pravi 4 GB swap-a, podešava kernel parametre za Postgres
i Chromium, instalira Docker sa rotacijom logova i uključuje automatske
bezbednosne zakrpe.

**Ne zatvaraj ovu sesiju dok iz drugog prozora ne potvrdiš:**

```bash
ssh mm@<IP>
```

Ako to radi — root sesija može da se zatvori. Ako ne radi, imaš još otvoren
root i možeš da popraviš. Ovo je jedini korak gde se čovek zaista zaključa
napolju.

---

## 4. Kod na server

Repo mora negde da živi. **GitHub, privatan repo** — CI je već napisan kao
`.github/workflows/ci.yml`, a Forgejo na svom serveru prvog dana znači jedan
servis više za održavanje uz nula koristi kod jednog korisnika. Selidba na
svoje kasnije je `git remote set-url`, ne migracija.

Na serveru napravi deploy ključ:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/deploy -N ""
cat ~/.ssh/deploy.pub
```

Na GitHub-u: repo → Settings → Deploy keys → Add → nalepi → **bez** write
pristupa. Pa nazad na server:

```bash
cat >> ~/.ssh/config <<'EOF'
Host github.com
  IdentityFile ~/.ssh/deploy
  IdentitiesOnly yes
EOF

mkdir -p ~/apps && cd ~/apps
git clone git@github.com:<nalog>/mm-persona-os.git
cd mm-persona-os
```

---

## 5. Konfiguracija

```bash
cp .env.prod.example .env.prod
openssl rand -base64 48   # DJANGO_SECRET_KEY
openssl rand -base64 32   # POSTGRES_PASSWORD
openssl rand -base64 32   # MINIO_ROOT_PASSWORD
nano .env.prod
```

Obavezno:

```
DOMAIN=persona.mercatomaster.com
DJANGO_ALLOWED_HOSTS=persona.mercatomaster.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://persona.mercatomaster.com
```

`GLOBAL_EXTERNAL_ACTIONS_ENABLED` **ostaje `false`** do GO odluke na kraju
Pilota A. Taj prekidač je jedina stvar između pisanja koda i objave na tuđoj
platformi.

---

## 6. Pokretanje

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f caddy
```

Caddy traži sertifikat pri prvom pokretanju. Ako DNS nije stigao, pisaće
grešku i pokušavati ponovo — sačekaj i osveži, ne restartuj u krug (Let's
Encrypt ima nedeljni limit na neuspele pokušaje).

Provera:

```bash
curl -I https://persona.mercatomaster.com/
```

---

## 7. Rezervne kopije

Hetznerov backup pokriva ceo disk. `deploy/backup.sh` pokriva „obrisao sam
pogrešnu personu u utorak":

```bash
chmod +x deploy/backup.sh
crontab -e
```

```
15 3 * * * /home/mm/apps/mm-persona-os/deploy/backup.sh >> /home/mm/backups/backup.log 2>&1
```

Jednom mesečno probaj **povratak** iz kopije na lokalnoj mašini. Kopija koja
nije vraćena nije kopija.

---

## 8. Podešavanje po veličini mašine

Posle svakog rescale-a promeni ove vrednosti u `.env.prod`, pa:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d postgres worker_browser
```

| | CX23 (4 GB) | CX43 (16 GB) | CX53 (32 GB) |
|---|---|---|---|
| `PG_SHARED_BUFFERS` | 512MB | 2GB | 4GB |
| `PG_EFFECTIVE_CACHE_SIZE` | 1536MB | 6GB | 12GB |
| `PG_MAINTENANCE_WORK_MEM` | 256MB | 1GB | 2GB |
| `PG_WORK_MEM` | 8MB | 16MB | 32MB |
| `PG_MAX_CONNECTIONS` | 50 | 100 | 150 |
| `BROWSER_CONCURRENCY` | 1 | 4 | 8 |

`PG_MAINTENANCE_WORK_MEM` je namerno visok na većim mašinama — HNSW indeks
iz F4 se gradi njime i na 256 MB se gradi neprijatno dugo.

## 9. Povećanje kapaciteta

Server → **Rescaling** → tip → Rescale. Restart ~2 minuta, IP ostaje isti.

- **CPU i RAM** idu gore i dole ako izabereš *Rescale CPU and RAM only*.
- **Disk ide samo gore.** Nepovratno. Ne diraj ga dok stvarno ne zatreba.
- Rescale te prebacuje na **trenutni cenovnik**, ne na onaj od kupovine.

Prag: CX43 prestaje da bude dovoljan na **8–10 persona koje istovremeno drže
otvoren browser** — ne 8–10 persona ukupno. Sledeći korak je CX53
(16 vCPU / 32 GB / 320 GB, 29,49 €).

Šta gledati pre nego što skaliraš:

```bash
docker stats --no-stream
free -h
df -h
```

Ako je `free -h` stalno ispod ~2 GB slobodnih ili swap raste — vreme je.

---

## Trošak

| Stavka | CX23 sada | CX43 posle rescale-a |
|---|---|---|
| Server | 5,49 | 15,99 |
| IPv4 | 0,50 | 0,50 |
| Backups (20 %) | 1,10 | 3,20 |
| **Ukupno** | **7,09** | **19,69** |

Bez PDV-a. Naplata je po satu, pa rescale usred meseca ne znači dupli račun.

Domen i DNS su već tvoji. LLM tokeni zasebno — do provere besplatnih kvota
računaj ~2 € mesečno na jeftinom modelu za pilotskih ~90 poziva dnevno.
