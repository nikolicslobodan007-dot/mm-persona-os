"""Grind — mlevenje PDF-a u LKP blokove (ADR-0031, sloj 2).

Verno preneto iz Grinder prototipa (Libero Libri): tekst se rekonstruiše
geometrijski iz charbox koordinata (rešava dizajnersko razvlačenje slova), pa
se linije klasifikuju na heading/paragraph, uklanjaju tekuća zaglavlja i
brojevi strana. Čiste funkcije — ne piše fajlove, ne dira bazu; vraća
(meta, blokovi). PDFium preko pypdfium2 (BSD-3 + Apache-2.0 — ADR-0079).
"""

from __future__ import annotations

import hashlib
import re
import statistics
from collections import Counter

import pypdfium2 as pdfium

VERSION_ID = "v1"
_SENT_END = re.compile(r"[.!?:”\"]$")
_DEHYPH = re.compile(r"(?<=\w)[‐‑-]\s+(?=\w)")


def _word_threshold(pos, line_h):
    if not pos:
        return line_h * 0.3
    return statistics.median(pos) + max(0.14 * line_h, 0.4)


def extract_lines(page):
    tp = page.get_textpage()
    chars = []
    for i in range(tp.count_chars()):
        c = tp.get_text_range(i, 1)
        if not c or c in ("\r", "\n", "\t"):
            continue
        left, bottom, right, top = tp.get_charbox(i)
        chars.append({"c": c, "l": left, "b": bottom, "r": right, "t": top})
    if not chars:
        return []
    heights = [c["t"] - c["b"] for c in chars if c["t"] > c["b"]]
    line_h = statistics.median(heights) if heights else 10.0
    chars.sort(key=lambda c: (-c["b"], c["l"]))
    lines = []
    cur = [chars[0]]
    for ch in chars[1:]:
        if abs(ch["b"] - cur[-1]["b"]) <= line_h * 0.6:
            cur.append(ch)
        else:
            lines.append(cur)
            cur = [ch]
    lines.append(cur)
    out = []
    for row in lines:
        row.sort(key=lambda c: c["l"])
        hs = [c["t"] - c["b"] for c in row if c["t"] > c["b"]]
        lh = statistics.median(hs) if hs else line_h
        gaps = sorted(
            b["l"] - a["r"]
            for a, b in zip(row, row[1:], strict=False)
            if b["l"] > a["r"]
        )
        thr = _word_threshold(gaps, lh)
        s = row[0]["c"]
        for a, b in zip(row, row[1:], strict=False):
            if (b["l"] - a["r"]) >= thr:
                s += " "
            s += b["c"]
        s = re.sub(r" +", " ", s).strip()
        if s:
            out.append({"y": row[0]["b"], "h": lh, "text": s})
    return out


def detect_script_lang(text):
    lat = len(re.findall(r"[a-zA-ZčćžšđČĆŽŠĐ]", text))
    cyr = len(re.findall(r"[Ѐ-ӿ]", text))
    return ("sr-Cyrl", "cyrillic") if cyr > lat else ("sr-Latn", "latin")


def classify(text):
    letters = re.sub(r"[^A-Za-zČĆŽŠĐčćžšđ]", "", text)
    if not letters:
        return "paragraph"
    ratio = sum(1 for ch in letters if ch.isupper()) / len(letters)
    is_heading = ratio > 0.7 and len(text) < 80 and len(letters) >= 3
    return "heading" if is_heading else "paragraph"


def _collapse(t):
    return re.sub(r"\s+", "", t).lower()


def _is_pageno(t):
    return bool(re.fullmatch(r"\d{1,4}", t.strip()))


def grind(path, *, naslov=""):
    """Samelji PDF u (meta, blokovi). Ne piše fajlove, ne dira bazu."""
    with open(path, "rb") as f:
        raw = f.read()
    checksum = hashlib.sha256(raw).hexdigest()

    doc = pdfium.PdfDocument(path)
    npages = len(doc)

    pages_lines = []
    all_h = []
    for pi in range(npages):
        lns = extract_lines(doc[pi])
        all_h.extend(li["h"] for li in lns)
        pages_lines.append(lns)
    body_h = statistics.median(all_h) if all_h else 10.0

    top_bot = Counter()
    for lns in pages_lines:
        if not lns:
            continue
        ys = [li["y"] for li in lns]
        ymin, ymax = min(ys), max(ys)
        for li in lns:
            near_edge = li["y"] <= ymin + body_h or li["y"] >= ymax - body_h
            if near_edge and len(li["text"]) < 70:
                top_bot[_collapse(li["text"])] += 1
    running = {k for k, c in top_bot.items() if k and c >= 4}

    lang, script = detect_script_lang(
        " ".join(li["text"] for lns in pages_lines for li in lns)[:5000]
    )

    blocks = []
    blk_n = 0
    heading_path = []

    def flush_para(buf, page, section_path):
        nonlocal blk_n
        text = re.sub(r" +", " ", " ".join(buf).strip())
        text = _DEHYPH.sub("", text)
        if not text:
            return
        blk_n += 1
        blocks.append({
            "block_id": f"blk_{blk_n:06d}", "block_type": "paragraph",
            "text": text, "language": lang, "order": blk_n,
            "heading_path": list(section_path),
            "source_page": page,
            "source_section": section_path[-1] if section_path else "",
            "extraction_confidence": 0.9, "human_verified": False,
        })

    for pi, lns in enumerate(pages_lines):
        page = pi + 1
        para_buf = []
        for li in sorted(lns, key=lambda x: -x["y"]):
            t = li["text"].strip()
            if not t or _collapse(t) in running or _is_pageno(t):
                continue
            if classify(t) == "heading":
                flush_para(para_buf, page, heading_path)
                para_buf = []
                heading_path = [t]
                blk_n += 1
                blocks.append({
                    "block_id": f"blk_{blk_n:06d}", "block_type": "heading",
                    "text": t, "language": lang, "order": blk_n,
                    "heading_path": [t], "source_page": page,
                    "source_section": t,
                    "extraction_confidence": 0.5, "human_verified": False,
                })
            else:
                para_buf.append(t)
                if _SENT_END.search(t):
                    flush_para(para_buf, page, heading_path)
                    para_buf = []
        flush_para(para_buf, page, heading_path)

    for i, b in enumerate(blocks):
        b["previous_block_id"] = blocks[i - 1]["block_id"] if i > 0 else ""
        b["next_block_id"] = blocks[i + 1]["block_id"] if i + 1 < len(blocks) else ""
        b["parent_section_id"] = ""

    meta = {
        "document_id": "doc_" + checksum[:12], "version_id": VERSION_ID,
        "title": naslov or "doc_" + checksum[:12], "checksum": checksum,
        "language": lang, "script": script, "pages": npages,
        "running_headers_removed": sorted(running),
    }
    return meta, blocks
