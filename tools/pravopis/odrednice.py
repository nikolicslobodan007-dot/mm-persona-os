"""Seče Rečnik uz Pravopis na odrednice i razrešava brojeve tačaka.

Ulaz je `izgradnja/tsv/str_NNN.txt` — jedan red po odrednici, dobijen po
uvlaci (vidi `tsv.py`). Ovde se odrednica čisti, preslovljava na latinicu i
iz nje se vade upućivanja na tačke Pravopisa.

O tačkama: deo PRAVILA ide do tačke 322. Svako upućivanje veće od toga nastalo
je tako što je OCR pročitao slovo pod-tačke kao cifru (`b`→`6`, `d`→`4`,
`a`→`2`). Koje je slovo bilo — ne znamo, pa se **ne pogađa**: upućivanje se
spušta na samu tačku. „т. 85" je istinito i proverivo; „т. 85d" bi bilo
izmišljeno (ADR-0033).
"""
from __future__ import annotations

import glob
import json
import re
from collections import Counter

MAX_TACKA = 322
PRVA, POSLEDNJA = 332, 505

CIR = ("абвгдђежзијклљмнњопрстћуфхцчџш"
       "АБВГДЂЕЖЗИЈКЛЉМНЊОПРСТЋУФХЦЧЏШ")
LAT = ["a", "b", "v", "g", "d", "đ", "e", "ž", "z", "i", "j", "k", "l", "lj", "m",
       "n", "nj", "o", "p", "r", "s", "t", "ć", "u", "f", "h", "c", "č", "dž", "š",
       "A", "B", "V", "G", "D", "Đ", "E", "Ž", "Z", "I", "J", "K", "L", "Lj", "M",
       "N", "Nj", "O", "P", "R", "S", "T", "Ć", "U", "F", "H", "C", "Č", "Dž", "Š"]
MAPA = dict(zip(CIR, LAT, strict=True))


def lat(s: str) -> str:
    return "".join(MAPA.get(z, z) for z in s)


def udeo_cirilice(s: str) -> float:
    slova = [z for z in s if z.isalpha()]
    return sum(z in MAPA for z in slova) / len(slova) if slova else 0.0


# --- tačke ------------------------------------------------------------------
# Posle preslovljavanja i Т i т postaju t; „T." je latinično iz OCR-a.
REF = re.compile(r"\b[Tt]\.?\s*([0-9lI]{1,4})\s*([a-hA-Hs])?")
#: Slova pod-tačaka u knjizi (latinična a–h). Mora biti skup: `"" in "abcdefgh"`
#: je tačno, pa bi niska propuštala upućivanja bez slova kao da slovo imaju.
PODTACKA = frozenset("abcdefgh")
#: Ćirilično „с" je u skenu latinično „c" pod-tačke; preslovljavanje ga pretvara
#: u „s", a „s" nije slovo pod-tačke — vraćamo ga.
SLOVO_ISPRAVKA = {"s": "c"}


#: Cifre koje su u ovom skenu pročitane umesto slova pod-tačke. Izmereno na
#: str. 400: knjiga piše „т. 27b", OCR daje „т. 276". Isto d→4, a→2.
CIFRA_KAO_SLOVO = {"2": "a", "4": "d", "6": "b"}


def _razresi(m: re.Match) -> str | None:
    """Uredna oznaka tačke, ili None kad se ne može stati iza nje.

    Tri slučaja:

    - izričito slovo („т. 86d") — sigurno;
    - broj veći od 322 („т. 854") — tačke toliko velike nema, pa je poslednja
      cifra slovo. Broj tačke je siguran, slovo nije: vraća se sama tačka;
    - broj u opsegu koji se završava cifrom 2, 4 ili 6 („т. 276") — može biti
      i tačka 276 i tačka 27b, i po tekstu se ne razlikuju. Vraća se None:
      radije bez upućivanja nego sa pogrešnim (ADR-0033).
    """
    broj = m.group(1).replace("l", "1").replace("I", "1")   # OCR meša 1, l i I
    slovo = (m.group(2) or "").lower()
    slovo = SLOVO_ISPRAVKA.get(slovo, slovo)
    n = int(broj)
    if slovo in PODTACKA:
        return f"{n}{slovo}" if n <= MAX_TACKA else None
    if n > MAX_TACKA:
        return str(int(broj[:-1])) if len(broj) > 1 and int(broj[:-1]) <= MAX_TACKA else None
    if len(broj) > 1 and broj[-1] in CIFRA_KAO_SLOVO and int(broj[:-1]) > 0:
        return None
    return str(n)


def tacke(tekst_lat: str) -> tuple[list[str], int, str]:
    """(uredne oznake tačaka, koliko nije razrešeno, tekst sa ispravljenim t.).

    Tekst se ispravlja zajedno sa spiskom: agent čita tekst, pa bi mu „t. 1057"
    ostalo pred očima i kad je u spisku uredno stoji „105".
    """
    nadjene, odbaceno = [], 0

    def zameni(m: re.Match) -> str:
        nonlocal odbaceno
        oznaka = _razresi(m)
        if oznaka is not None:
            nadjene.append(oznaka)
            return f"t. {oznaka}"
        odbaceno += 1
        broj = m.group(1).replace("l", "1").replace("I", "1")
        if not m.group(2) and len(broj) > 1 and broj[-1] in CIFRA_KAO_SLOVO:
            # Reci šta piše i šta bi moglo biti — agent tada ne citira ništa.
            drugo = f"{int(broj[:-1])}{CIFRA_KAO_SLOVO[broj[-1]]}"
            return f"t. [nejasno: {int(broj)} ili {drugo}]"
        return f"t. [nejasno: {m.group(0).split('.')[-1].strip()}]"

    cist = REF.sub(zameni, tekst_lat)
    return list(dict.fromkeys(nadjene)), odbaceno, cist


# --- odrednice --------------------------------------------------------------
#: Tekuće zaglavlje strane: broj i velika slova („332 АВИОН – АЈЗЕНШТАЈН").
ZAGLAVLJE = re.compile(
    r"^[\s\d_|.,\-–—/]*[А-ШЂЋЖЧЏЈЉЊA-Z]"
    r"[А-ШЂЋЖЧЏЈЉЊA-Z\s_|\-–—/,.]*\d{0,3}[\s_|.]*$")
SMECE = re.compile(r"^[\s|\-–—_.,;:!]*$")
#: Odrednica počinje slovom ili navodnikom; sve drugo je rep prethodne.
POCETAK = re.compile(r"^[А-ШЂЋЖЧЏЈЉЊа-шђћжчџјљња„»\"]")
#: Reči na kojima se odrednica završava iako nema zareza: veznici i skraćenice
#: gramatičkog opisa. Bez njih „Verneržica ili -ice" daje glavu „Verneržica ili".
STOP = {"ili", "i", "v", "t", "up", "prema", "gen", "dat", "instr", "vok", "mn",
        "komp", "prid", "ek", "ijek", "zast", "tako", "ne", "boljе", "bolje"}
#: Glava odrednice ume da bude i višečlana („bez belaja", „Prespansko jezero",
#: „Dela Kverča"), ali ne duža od tri reči — dalje počinje opis.
MAX_REC_GLAVE = 3


#: Prelom reda usred reči: „Крушедо- лац". Prava crtica u knjizi nikad nema
#: razmak iza sebe (Pravopis, t. 217), pa je „slovo- slovo" uvek prelom.
PRELOM = re.compile(r"(\w)-\s+(\w)")


def ocisti(red: str) -> str:
    return re.sub(r"\s+", " ", red.replace("|", " ")).strip()


def spoji_prelome(tekst: str) -> str:
    return PRELOM.sub(r"\1\2", tekst)


def glava(tekst: str) -> str:
    """Sama reč koja se traži — do prve interpunkcije ili opisne reči."""
    reci: list[str] = []
    for rec in tekst.split():
        if re.search(r"[,(;:]", rec):
            reci.append(re.split(r"[,(;:]", rec)[0])
            break
        if reci and rec.strip(".").lower() in STOP:
            break
        reci.append(rec)
        if len(reci) >= MAX_REC_GLAVE:
            break
    return " ".join(w for w in reci if w).strip(" ,.;-")


def sirove():
    for putanja in sorted(glob.glob("izgradnja/tsv/str_*.txt"),
                          key=lambda p: int(re.search(r"str_(\d+)", p).group(1))):
        strana = int(re.search(r"str_(\d+)", putanja).group(1))
        if not PRVA <= strana <= POSLEDNJA:
            continue
        redovi = [ocisti(r) for r in open(putanja, encoding="utf-8")]
        redovi = [r for r in redovi if r and not SMECE.match(r)]
        # Prvi red stupca ume da bude tekuće zaglavlje; ono nije odrednica.
        redovi = [r for r in redovi if not ZAGLAVLJE.match(r)]
        spojeni: list[str] = []
        for r in redovi:
            if spojeni and not POCETAK.match(r):
                spojeni[-1] += " " + r
            else:
                spojeni.append(r)
        for r in spojeni:
            yield strana, r


#: Oblici koje knjiga izričito odbija. Odavde nastaje provera nad nacrtom:
#: ako agent napiše „havlija", odrednica „avlija (ne havlija)" to obara sa
#: izvorom, bez ijednog poziva modelu.
ODBIJENO = (
    re.compile(r"\bne\s+[„\"']([^„“\"']{2,40})[“\"']"),
    re.compile(r"\(\s*ne\s+([a-zA-ZćčšžđĆČŠŽĐ\-]{3,30})\s*[,)]"),
    re.compile(r"\bbolje\s+nego\s+([a-zA-ZćčšžđĆČŠŽĐ\-]{3,30})"),
)
# „običnije X" je namerno izostavljeno: tu je X oblik koji SE preporučuje, a
# odbija se sama odrednica („nekoji … običnije neki"). Obrazac je obrnut od
# ostalih i uhvaćen je tek kad je „neki" ispao kao zabranjena reč.
#: Reči koje obrasci pokupe, a nisu oblik: veznici i skraćenice.
NIJE_OBLIK = {"nego", "sl", "itd", "npr", "tako", "samo", "i", "ili", "kao",
              "se", "je", "su", "od", "do", "uz", "na", "za"}
#: Srpska latinica. Oblik sa x, y, q ili w nije srpska reč nego OCR smeće
#: („ajznxayep" iz „Ajzn-хауер"), i takav se ne upisuje kao zabranjen.
SRPSKA_LAT = re.compile(r"^[a-zćčšžđA-ZĆČŠŽĐ][a-zćčšžđ\-]{3,}$")


def odbijeni_oblici(tekst_lat: str) -> list[str]:
    nadjeni: list[str] = []
    for obrazac in ODBIJENO:
        for m in obrazac.finditer(tekst_lat):
            o = m.group(1).strip(" -,.")
            # Velika slova se čuvaju: „Koraks (ne Korak)" govori o prezimenu,
            # a snižen oblik bi prijavljivao svaki „korak" u tekstu.
            if o.lower() not in NIJE_OBLIK and SRPSKA_LAT.match(o):
                nadjeni.append(o)
    return list(dict.fromkeys(nadjeni))


def main() -> None:
    izlaz, broj = [], Counter()
    for strana, tekst in sirove():
        if len(tekst) < 4:
            broj["prekratko"] += 1
            continue
        if udeo_cirilice(tekst) < 0.5:
            broj["nije ćirilica"] += 1
            continue
        tekst = spoji_prelome(tekst)
        t, odbaceno, tekst_lat = tacke(lat(tekst))
        broj["odrednica"] += 1
        broj["sa tačkom"] += bool(t)
        broj["odbačenih upućivanja"] += odbaceno
        broj["odbijenih oblika"] += len(odbijeni_oblici(tekst_lat))
        g = glava(tekst_lat)
        # Ćirilična glava je isti broj reči — STOP reči su latinične, pa se
        # odluka donosi jednom, nad preslovljenim tekstom.
        g_cir = " ".join(tekst.split()[:len(g.split())]).strip(" ,.;-(")
        izlaz.append({"odrednica": g,
                      "odrednica_cir": g_cir,
                      "tekst": tekst_lat, "tekst_cir": tekst,
                      "tacke": t, "strana_pdf": strana,
                      "ne": odbijeni_oblici(tekst_lat)})
    # Ovde je stajala zaštita „oblik koji i sam ima svoju odrednicu nije
    # zabranjen". Izbačena je: knjiga pogrešnom obliku redovno daje SVOJU
    # odrednicu koja upućuje nazad („havlija, ne nego avlija"), pa je zaštita
    # obarala baš najkorisnije slučajeve — među njima i „havlija", na kom je
    # provera prvi put demonstrirana i ništa nije prijavila.
    # Mereno nad 51 ADR-om (35.704 reči, bez ADR-0054 i 0055 koji sadrže same
    # primere): sa zaštitom i bez nje isto — 4 pogotka, 0,011%. Zaštita je
    # koštala 22 oblika i nije donela ništa. Retke lažne uzbune se gase
    # komandom `recnik --utisaj`, uz razlog u zapisu.
    with open("izgradnja/recnik.jsonl", "w", encoding="utf-8") as f:
        for r in izlaz:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    duzine = sorted(len(r["tekst"]) for r in izlaz)
    print(dict(broj))
    print("dužina: min", duzine[0], "| medijana", duzine[len(duzine) // 2],
          "| 99%", duzine[int(len(duzine) * 0.99)], "| max", duzine[-1])
    print("različitih odrednica:", len({r["odrednica"] for r in izlaz}))


if __name__ == "__main__":
    main()
