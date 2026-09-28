"""Rečnik: odrednica se prepoznaje po UVLACI, ne po praznom redu.

Prazan red između odrednica postoji na većini strana, ali ne na svima — na
str. 346, 354 i 361 OCR je ceo stubac slepio u jedan blok, pa je „razdvaja
prazan red" dalo odrednice od 2900 znakova. Uvlaka je u knjizi stvarna:
odrednica počinje uz levu ivicu stupca, nastavak je uvučen.

Zato tesseract ovde piše TSV — svaka reč sa svojom `left` koordinatom. Red
čiji je početak u prvih `PRAG` piksela stupca je nova odrednica.
"""
from __future__ import annotations

import csv
import io
import pathlib
import subprocess
import sys

import numpy as np
from PIL import Image

PDF = "/mnt/user-data/uploads/Persona OS/PDF Za AI  Agente/pravopis-za-ocr.pdf"
B = pathlib.Path("/home/claude/pravopis")
IZL = B / "izgradnja" / "tsv"
IZL.mkdir(parents=True, exist_ok=True)
TMP = pathlib.Path("/tmp/rtsv")
TMP.mkdir(exist_ok=True)

def stupci(png: pathlib.Path) -> list[tuple[int, int, int, int]]:
    """Deli stranu na stupce po mastilu — razmak se traži, ne pretpostavlja."""
    a = np.array(Image.open(png).convert("L"))
    mast = (a < 160).sum(axis=0)
    w, h = len(mast), a.shape[0]
    sred = mast[int(w * 0.35):int(w * 0.65)]
    glatko = np.convolve(sred, np.ones(30) / 30, "same")
    x = int(w * 0.35) + int(np.argmin(glatko))
    if glatko.min() < mast.mean() * 0.10:
        return [(0, 0, x, h), (x, 0, w, h)]
    return [(0, 0, w, h)]


#: Znakovi koje skener ostavlja uz ivicu stupca (linija reza, mrlja). Reč
#: sastavljena samo od njih nije početak reda nego smeće, a ako se uzme kao
#: početak, cela strana ispadne „uvučena" i odrednice se sleploe u jednu.
SMECE_REC = set("|!I[]{}()_-–—.,;:'\"`~*/\\")


def redovi(tsv: str) -> list[tuple[int, str]]:
    """(left prve prave reči, tekst reda) za svaki red koji tesseract vidi."""
    citac = csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE)
    grupe: dict[tuple, list[dict]] = {}
    for r in citac:
        if (r.get("text") or "").strip() and int(r["level"]) == 5:
            kljuc = (r["block_num"], r["par_num"], r["line_num"])
            grupe.setdefault(kljuc, []).append(r)
    out = []
    for reci in grupe.values():
        reci.sort(key=lambda r: int(r["left"]))
        prave = [r for r in reci if set(r["text"].strip()) - SMECE_REC]
        if not prave:
            continue
        out.append((int(prave[0]["left"]), " ".join(r["text"] for r in reci)))
    return out


def granica(lefts: list[int]) -> int:
    """Do koje `left` vrednosti je red početak odrednice.

    Rečnik ima visећu uvlaku: odrednica je uz ivicu stupca, nastavak je oko
    25 px udesno (300 dpi). Raspodela je zato dvogrba. Najmanji `left` ne
    valja kao ivica — to je uvek neka mrlja ili linija reza — a ni modus, jer
    pada čas u jednu čas u drugu grbu.

    Uzimamo 15. i 85. percentil: kad su razmaknuti, granica je na pola puta
    između njih; kad nisu, na strani nema nastavaka (same kratke odrednice)
    pa su svi redovi početak.
    """
    p = sorted(lefts)
    lo = p[int(len(p) * 0.15)]
    hi = p[int(len(p) * 0.85)]
    return (lo + hi) // 2 if hi - lo >= 12 else lo + 12


def obradi(n: int) -> str:
    cilj = IZL / f"str_{n:03d}.txt"
    if cilj.exists() and cilj.stat().st_size > 100:
        return "preskočeno"
    png = TMP / f"p{n}.png"
    if not png.exists():
        subprocess.run(["pdftoppm", "-r", "300", "-gray", "-f", str(n), "-l", str(n),
                        "-png", "-singlefile", PDF, str(png)[:-4]],
                       check=False, capture_output=True)
    if not png.exists():
        return "nema slike"
    im = Image.open(png)
    odrednice: list[str] = []
    for k, box in enumerate(stupci(png)):
        p = TMP / f"p{n}_{k}.png"
        im.crop(box).save(p)
        o = TMP / f"p{n}_{k}"
        subprocess.run(["tesseract", str(p), str(o), "-l", "srp+eng", "--psm", "6", "tsv"],
                       check=False, capture_output=True,
                       env={"TESSDATA_PREFIX": "/home/claude/tess", "PATH": "/usr/bin:/bin"})
        t = pathlib.Path(f"{o}.tsv")
        if not t.exists():
            p.unlink(missing_ok=True)
            continue
        rr = redovi(t.read_text(encoding="utf-8", errors="replace"))
        t.unlink()
        p.unlink(missing_ok=True)
        if not rr:
            continue
        prag = granica([x for x, _ in rr])
        for i, (levo, tekst) in enumerate(rr):
            if i == 0 or levo <= prag:
                odrednice.append(tekst)
            else:
                odrednice[-1] += " " + tekst
    png.unlink(missing_ok=True)
    cilj.write_text("\n".join(odrednice), encoding="utf-8")
    return f"{len(odrednice)} redova-odrednica"


if __name__ == "__main__":
    poc, kraj = int(sys.argv[1]), int(sys.argv[2])
    for n in range(poc, kraj + 1):
        print(n, obradi(n), flush=True)
