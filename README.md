# terc-vip-mcp

An MCP server that lets an AI agent drive the **TERC V.I.P.** construction-estimating
desktop program (Windows) through the program's own menus: create a budget with a given
hourly overhead rate, add items by their 12-digit ENGY code, let TERC price them from its
licensed ÖN database, and read the result back through TERC's official Excel export as JSON.

> **Unofficial.** This project is not affiliated with, endorsed by or supported by TERC Kft.
> You need your own licensed TERC V.I.P. installation and hardware key.
> The tool only uses the program's user interface and its official export. It does not
> decompile, reverse-engineer or read TERC's binaries, databases or project files, and this
> repository contains no TERC data (no norms, prices or catalogue content).

## How it works

```
AI agent --MCP--> server.py (WSL/Linux) --cmd.exe--> windows/terc_worker.py (Windows, pywinauto)
                                                     |-> TERC V.I.P. menus (WM_COMMAND)
                     JSON <-- terc_export_parse.py <-|-- TERC "Excel export (new beta)" (.xls = HTML table)
```

Tools: `terc_status`, `terc_start`, `terc_uj_koltsegvetes` (new budget: name, hourly rate,
renovation/new), `terc_tetel_felvitel` (items `[{"engy": "...", "menny": 1.0}]`),
`terc_export` (returns items, unit prices, per-trade and total net), `terc_close`.

## Requirements

- Windows with a licensed TERC V.I.P. (tested with **2026/2**; menu positions are
  version-specific) and its hardware key.
- Windows Python 3 with `pywinauto` and `pywin32`.
- MCP side: Python 3 with `mcp` (FastMCP). Written for WSL; set the paths below elsewhere.
- The screen must be free while a job runs (real clicks and keystrokes). One job at a time.

## Configuration (environment variables)

| Variable | Default |
|---|---|
| `TERC_DIR` | `C:\terc\tercvipx` |
| `TERC_MCP_WORK` | `C:\terc-mcp\work` |
| `TERC_WORKER` | `C:\terc-mcp\terc_worker.py` |
| `TERC_MCP_WORK_WSL` | `/mnt/c/terc-mcp/work` |
| `TERC_CMD` | `/mnt/c/Windows/System32/cmd.exe` |

## Usage

```bash
claude mcp add terc -- python3 /path/to/server.py
```

The worker can also be used directly:
`python terc_worker.py status|start|new --name X --rezsioradij 12000 --jelleg felujitas|add --items items.json|export --out C:\terc-mcp\work\x.xls|close`.
Each call prints one JSON line; exit code 0 = ok.

## Limits

- Items must be identified by their 12-digit ENGY code; text-only items are not priced by TERC.
- TERC's own Excel import does not price items, and plain XML import is a separate TERC
  subscription; the Etalon XML import is not wired in yet.
- Startup dialogs are handled by their text; an unknown dialog stops the worker with a screenshot.

## License

MIT
