"""Samostalan pokretač Aidera. ADR-0086.

Vrti se Pajtonom iz Aiderovog kaveza (ADR-0082), odvojeno od aplikacije.
Upisuje JSON sa TAČNIM brojem tokena — ekran Aidera zaokružuje
(`format_tokens`), pa se nikad ne parsira (ADR-0086).

Dva uslova bez kojih testovi ne prolaze:
  1. uvoz Aidera je UNUTAR funkcije — kapija (pytest kontejner) nema ni
     Aider ni mrežu ka njemu;
  2. poziv Aidera stoji u zasebnoj funkciji (`_pozovi_aider`) da bi test
     mogao da je zameni preko monkeypatch.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _sastavi_argv(
    *,
    model: str,
    podesavanja: str,
    fajlovi: list[str],
    citanja: list[str],
) -> list[str]:
    """Slaže argv za Aidera, u redu propisanom ADR-0086.

    Bez `--message-file`: ADR-0089 — sa `return_coder=True` Aider vraća codera
    pre petlje razgovora (aider/main.py:1018) i tu zastavicu nikad ne pročita.
    Brif isporučuje `coder.run`, pa ovde mrtva zastavica ne stoji.
    """
    argv: list[str] = [
        "--no-git",
        "--model", model,
        "--model-settings-file", podesavanja,
    ]
    for f in fajlovi:
        argv += ["--file", f]
    for r in citanja:
        argv += ["--read", r]
    argv += [
        "--no-auto-commits",
        "--yes-always",
        "--no-stream",
        "--analytics-disable",
        "--no-check-update",
        "--no-show-model-warnings",
    ]
    return argv


def _pozovi_aider(argv: list[str], poruka: str):
    """Jedina tačka gde se Aider stvarno zove.

    Uvoz je namerno ovde, ne na vrhu modula: kapija nema ni Aider ni mrežu
    ka provajderu (ADR-0086, ADR-0082). Test ovu funkciju menja preko
    monkeypatch i ne dira uvoz.

    ADR-0089 — DVA poziva, ne jedan. `main(..., return_coder=True)` samo
    sastavi codera i izadje (aider/main.py:1018), pre nego sto je ijedna
    poruka poslata. Razgovor pokrece `coder.run`, i tek on zove model.
    """
    from aider.main import main as aider_main

    coder = aider_main(argv, return_coder=True)
    coder.run(with_message=poruka)
    return coder


def _izvestaj_iz_codera(coder, model: str, greska: str | None) -> dict:
    """Broj se čita isključivo preko `getattr(..., None)` (ADR-0086).

    `None` znači „nije izmereno", nula znači „izmereno nula" — ne sme da se
    izmisli jedno umesto drugog, jer se od ovog broja direktno računa cena.
    """
    return {
        "model": model,
        "tokens_sent": getattr(coder, "total_tokens_sent", None),
        "tokens_received": getattr(coder, "total_tokens_received", None),
        "cache_read": getattr(coder, "total_tokens_cache_read", None),
        "cache_write": getattr(coder, "total_tokens_cache_write", None),
        "finish": "ok" if greska is None else "greska",
        "greska": greska or "",
    }


def _parsiraj_argumente(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pokretač Aidera (ADR-0086).")
    parser.add_argument("--brif", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--podesavanja", required=True)
    parser.add_argument("--fajl", action="append", default=[])
    parser.add_argument("--citaj", action="append", default=[])
    parser.add_argument("--radni", required=True)
    parser.add_argument("--izvestaj", required=True)
    return parser.parse_args(argv)


def pokreni(argv: list[str] | None = None) -> int:
    """Pokreće Aidera i upisuje izveštaj. Vraća izlazni kod procesa."""
    args = _parsiraj_argumente(argv)

    aider_argv = _sastavi_argv(
        model=args.model,
        podesavanja=args.podesavanja,
        fajlovi=args.fajl,
        citanja=args.citaj,
    )

    pocetni_dir = os.getcwd()
    coder = None
    greska: str | None = None
    try:
        os.chdir(args.radni)
        try:
            # ADR-0089 — brif se predaje kao TEKST. Putanja u argv ne bi bila
            # pročitana: Aider sa `return_coder=True` izlazi pre petlje.
            coder = _pozovi_aider(aider_argv, Path(args.brif).read_text(encoding="utf-8"))
        except Exception as exc:  # svaki kvar poziva ide u izveštaj, ne ruši proces
            greska = str(exc)
        finally:
            os.chdir(pocetni_dir)
    except OSError as exc:  # --radni ne postoji ili nije dostupan
        greska = str(exc)

    izvestaj = _izvestaj_iz_codera(coder, args.model, greska)

    try:
        Path(args.izvestaj).write_text(
            json.dumps(izvestaj, ensure_ascii=False, indent=2)
        )
    except OSError as exc:
        sys.stderr.write(f"ne mogu da upišem izveštaj: {exc}\n")
        return 1

    return 0 if greska is None else 1


def main(argv: list[str] | None = None) -> int:
    return pokreni(argv)


if __name__ == "__main__":
    sys.exit(main())
