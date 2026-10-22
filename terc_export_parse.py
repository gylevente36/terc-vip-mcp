#!/usr/bin/env python3
"""Parse a TERC VIP 'Excel allomanyba (uj beta)' export into JSON.

The export is an HTML table saved with an .xls extension (cp1250). Totals in the file are
Excel formulas, so they are recomputed here from quantity x unit prices.
"""
import html
import json
import re
import sys

ITEM_NO = re.compile(r"^\d{2}-\d{3}")


def _num(s):
    s = s.replace("\xa0", "").replace(" ", "").replace(",", ".")
    return float(s) if s else 0.0


def parse(path):
    raw = open(path, "rb").read()
    if b"<html" not in raw[:2000].lower():
        raise ValueError(f"{path}: not a TERC HTML export")
    text = raw.decode("cp1250", errors="replace")
    items = []
    for row in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", text):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"(?is)<td[^>]*>(.*?)</td>", row)]
        if len(cells) >= 7 and ITEM_NO.match(cells[1]):
            q, a, d = _num(cells[3]), _num(cells[5]), _num(cells[6])
            items.append({
                "ssz": cells[0], "tetelszam": cells[1], "szoveg": cells[2],
                "mennyiseg": q, "egyseg": cells[4],
                "anyag_egysegar": a, "dij_egysegar": d,
                "anyag_osszesen": round(q * a), "dij_osszesen": round(q * d),
                "munkanem": cells[1][:2],
            })
    if not items:
        raise ValueError(f"{path}: no item rows found")
    per = {}
    for it in items:
        p = per.setdefault(it["munkanem"], {"anyag": 0, "dij": 0})
        p["anyag"] += it["anyag_osszesen"]
        p["dij"] += it["dij_osszesen"]
    anyag = sum(p["anyag"] for p in per.values())
    dij = sum(p["dij"] for p in per.values())
    return {"tetelek": items, "munkanemek": per, "tetel_db": len(items),
            "anyag": anyag, "dij": dij, "netto": anyag + dij}


if __name__ == "__main__":
    r = parse(sys.argv[1])
    if len(sys.argv) > 2 and sys.argv[2] == "--summary":
        print(json.dumps({k: r[k] for k in ("tetel_db", "anyag", "dij", "netto", "munkanemek")}, ensure_ascii=False))
    else:
        print(json.dumps(r, ensure_ascii=False, indent=1))
