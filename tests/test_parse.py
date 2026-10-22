"""Parser test on a synthetic export (made-up rows, same table shape as TERC's export)."""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from terc_export_parse import parse

HTML = """<html xmlns:x='urn:schemas-microsoft-com:office:excel'><body><table>
<tr><td>71 Example trade</td></tr>
<tr><td>Ssz.</td><td>Tetelszam</td><td>Szoveg</td><td>Menny.</td><td>Egyseg</td><td>Anyag</td><td>Dij</td></tr>
<tr><td>1</td><td>71-000-1.1</td><td>Example item A</td><td>2</td><td>db</td><td>100</td><td>50</td></tr>
<tr><td>2</td><td>71-000-2.2</td><td>Example item B</td><td>1,5</td><td>m</td><td>0</td><td>1000</td></tr>
</table></body></html>"""

def test_totals():
    with tempfile.NamedTemporaryFile("wb", suffix=".xls", delete=False) as f:
        f.write(HTML.encode("cp1250")); p = f.name
    r = parse(p)
    assert r["tetel_db"] == 2
    assert r["anyag"] == 200 and r["dij"] == 100 + 1500 and r["netto"] == 1800

def test_rejects_non_export():
    with tempfile.NamedTemporaryFile("wb", suffix=".xls", delete=False) as f:
        f.write(b"PK\x03\x04 not html"); p = f.name
    try:
        parse(p); assert False, "should raise"
    except ValueError:
        pass

if __name__ == "__main__":
    test_totals(); test_rejects_non_export(); print("ok")
