#!/usr/bin/env python3
"""TERC VIP MCP server.

Drives the licensed TERC VIP desktop program through its own menus via the Windows-side
worker (C:\\terc-mcp\\terc_worker.py, pywinauto). It never reads TERC's binaries or data
files: input goes in through the program's item lookup, output comes back through the
program's official Excel export, which is parsed here into JSON.
"""
import json
import os
import subprocess
import sys
import tempfile

from mcp.server.fastmcp import FastMCP

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from terc_export_parse import parse  # noqa: E402

CMD = os.environ.get("TERC_CMD", "/mnt/c/Windows/System32/cmd.exe")
WORKER = os.environ.get("TERC_WORKER", r"C:\terc-mcp\terc_worker.py")
WORK_WIN = os.environ.get("TERC_MCP_WORK", r"C:\terc-mcp\work")
WORK_WSL = os.environ.get("TERC_MCP_WORK_WSL", "/mnt/c/terc-mcp/work")

mcp = FastMCP("terc")


def _worker(*args, timeout=900):
    # cmd.exe needs a Windows cwd, otherwise it warns about UNC paths.
    proc = subprocess.run([CMD, "/c", "python", WORKER, *args], cwd="/mnt/c",
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout)
    lines = [l for l in proc.stdout.splitlines() if l.strip().startswith("{")]
    if not lines:
        return {"ok": False, "error": "worker gave no JSON", "rc": proc.returncode,
                "stdout": proc.stdout[-1500:], "stderr": proc.stderr[-1500:]}
    return json.loads(lines[-1])


@mcp.tool()
def terc_status() -> dict:
    """Is TERC running, which windows are open, which budget is loaded."""
    return _worker("status", timeout=60)


@mcp.tool()
def terc_start() -> dict:
    """Start the TERC budget module and click through the startup notices."""
    return _worker("start", timeout=300)


@mcp.tool()
def terc_uj_koltsegvetes(nev: str, rezsioradij: int = 12000, jelleg: str = "felujitas",
                         felulir: bool = False) -> dict:
    """Create a new budget with the given hourly overhead rate (Ft/hour); jelleg: felujitas|uj.
    felulir=True overwrites an existing budget of the same name."""
    if jelleg not in ("felujitas", "uj"):
        return {"ok": False, "error": "jelleg must be felujitas or uj"}
    args = ["new", "--name", nev, "--rezsioradij", str(rezsioradij), "--jelleg", jelleg]
    if felulir:
        args.append("--overwrite")
    return _worker(*args, timeout=300)


@mcp.tool()
def terc_tetel_felvitel(tetelek: list[dict]) -> dict:
    """Add items by 12-digit ENGY code: [{"engy": "710130819490", "menny": 1.0}, ...].
    TERC prices each item from its own ÖN norm with the budget's hourly rate."""
    bad = [t for t in tetelek if not str(t.get("engy", "")).strip().isdigit() or "menny" not in t]
    if bad:
        return {"ok": False, "error": "every item needs a numeric engy and a menny", "bad": bad[:5]}
    os.makedirs(WORK_WSL, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix="items-", suffix=".json", dir=WORK_WSL)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump([{"engy": str(t["engy"]).strip(), "menny": float(t["menny"])} for t in tetelek], f)
    win = WORK_WIN + "\\" + os.path.basename(path)
    try:
        return _worker("add", "--items", win, timeout=60 + 30 * len(tetelek))
    finally:
        os.unlink(path)


@mcp.tool()
def terc_export(fajlnev: str = "export.xls") -> dict:
    """Export the open budget through TERC's Excel export and return it as JSON
    (items with unit prices, per-trade and grand net totals)."""
    name = os.path.basename(fajlnev)
    if not name.lower().endswith(".xls"):
        name += ".xls"
    res = _worker("export", "--out", WORK_WIN + "\\" + name, timeout=300)
    if not res.get("ok"):
        return res
    res["koltsegvetes"] = parse(os.path.join(WORK_WSL, name))
    return res


@mcp.tool()
def terc_close() -> dict:
    """Save and close the TERC budget module."""
    return _worker("close", timeout=120)


if __name__ == "__main__":
    mcp.run()
