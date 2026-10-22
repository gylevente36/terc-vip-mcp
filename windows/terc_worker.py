# -*- coding: utf-8 -*-
"""TERC VIP worker: one JSON line on stdout per call. Windows python, pywinauto win32 (32-bit TERC, 64-bit python is fine).
Only the program's own menus/dialogs are used. The registration form is never filled in."""
import sys, os, re, json, time, ctypes, subprocess, warnings, argparse, traceback
warnings.filterwarnings("ignore")
import win32gui, win32con, win32process, win32api
from pywinauto import mouse, keyboard
from pywinauto.controls.hwndwrapper import HwndWrapper

WORK = os.environ.get("TERC_MCP_WORK", r"C:\terc-mcp\work")
TERC_DIR = os.environ.get("TERC_DIR", r"C:\terc\tercvipx")
MAIN_EXE = "TercKsgx.exe"
BUDGET_EXE = "ksgvetesy.exe"
EDITOR = "TFrSzamed"
os.makedirs(WORK, exist_ok=True)
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass

class WorkerError(Exception):
    def __init__(self, msg, shot=None): super().__init__(msg); self.shot = shot

# ---------- process / window helpers ----------
def pids(name):
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    r = []
    for l in out.splitlines():
        p = l.strip().split('","')
        if len(p) > 1 and p[0].strip('"').lower() == name.lower(): r.append(int(p[1]))
    return r

_PCACHE = {"t": 0.0, "v": set()}
def terc_pids(fresh=False):
    if fresh or time.time() - _PCACHE["t"] > 2.0:
        _PCACHE["v"] = set(pids(BUDGET_EXE)) | set(pids(MAIN_EXE)); _PCACHE["t"] = time.time()
    return set(_PCACHE["v"])

def wins(pidset=None, min_w=40):
    pidset = pidset or terc_pids()
    res = []
    def cb(h, _):
        if not win32gui.IsWindowVisible(h): return
        try: _, p = win32process.GetWindowThreadProcessId(h)
        except Exception: return
        if p not in pidset: return
        cls = win32gui.GetClassName(h)
        if cls in ("TApplication", "THintWindow", "TPUtilWindow", "MSCTFIME UI", "IME", "#32768", "SysShadow", "tooltips_class32", "ComboLBox"): return
        r = win32gui.GetWindowRect(h)
        if r[2] - r[0] < min_w: return
        res.append({"h": h, "cls": cls, "title": win32gui.GetWindowText(h), "rect": r})
    win32gui.EnumWindows(cb, None)
    return res

def find(pred, timeout=6.0, interval=0.15):
    t0 = time.time()
    while True:
        for w in wins():
            if pred(w): return w
        if time.time() - t0 >= timeout: return None
        time.sleep(interval)

def wait_gone(h, timeout=6.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not win32gui.IsWindow(h) or not win32gui.IsWindowVisible(h): return True
        time.sleep(0.1)
    return False

def foreground(h):
    if win32gui.GetForegroundWindow() == h: return True
    ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)
    try: win32gui.SetForegroundWindow(h)
    except Exception: pass
    ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)
    time.sleep(0.25)
    return win32gui.GetForegroundWindow() == h

def children(h):
    out = []
    try:
        desc = HwndWrapper(h).descendants()
    except Exception:
        return out
    for c in desc:
        try:
            if not c.is_visible(): continue
            r = c.rectangle(); out.append({"cls": c.class_name(), "text": c.window_text(), "rect": (r.left, r.top, r.right, r.bottom), "h": c.handle})
        except Exception: pass
    return out

def texts(h):
    return [c["text"] for c in children(h) if c["text"] and c["cls"] not in ("TCheckBox",)]

def shot(name):
    path = os.path.join(WORK, name if name.lower().endswith(".png") else name + ".png")
    ps = ("Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
          "$b=[System.Windows.Forms.SystemInformation]::VirtualScreen;"
          "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height;"
          "$g=[System.Drawing.Graphics]::FromImage($bmp);"
          "$g.CopyFromScreen($b.Left,$b.Top,0,0,$bmp.Size);"
          "$bmp.Save('%s',[System.Drawing.Imaging.ImageFormat]::Png)" % path)
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], capture_output=True)
    return path

def fg_is_terc():
    try:
        _, p = win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())
    except Exception:
        return False
    return p in terc_pids()

def real_click(x, y, double=False):
    # never click blind: the foreground window must belong to TERC (other windows must not be touched)
    if not fg_is_terc():
        raise WorkerError("a TERC ablak nincs elol (elol: %s), nem kattintok" % win32gui.GetWindowText(win32gui.GetForegroundWindow())[:40])
    (mouse.double_click if double else mouse.click)(button="left", coords=(int(x), int(y)))

def click_ctrl(c, h_window=None):
    """real mouse click on the centre of a control (HwndWrapper BM_CLICK does not work on TBitBtn)"""
    r = c["rect"]
    if h_window: foreground(h_window)
    real_click((r[0] + r[2]) // 2, (r[1] + r[3]) // 2)

BTN_CLASSES = ("TBitBtn", "TButton", "TSpeedButton", "Button")

def find_button(h, label):
    lab = label.replace("&", "").strip().lower()
    for c in children(h):
        if c["cls"] in BTN_CLASSES:
            if c["text"].replace("&", "").strip().lower() == lab: return c
    for c in children(h):
        if c["cls"] in BTN_CLASSES and lab in c["text"].replace("&", "").strip().lower(): return c
    return None

def press_button(h, label):
    b = find_button(h, label)
    if not b: return False
    click_ctrl(b, h)
    return True

def editor():
    return find(lambda w: w["cls"] == EDITOR, timeout=0.2)

def budget_name():
    e = editor()
    if not e: return None
    m = re.search(r":\s*(.+)$", e["title"])
    return m.group(1).strip() if m else e["title"]

def idle_seconds():
    class LII(ctypes.Structure): _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    l = LII(); l.cbSize = ctypes.sizeof(l); ctypes.windll.user32.GetLastInputInfo(ctypes.byref(l))
    return (ctypes.windll.kernel32.GetTickCount() - l.dwTime) / 1000.0

def fail(msg, tag="err"):
    p = shot("err_%s_%d" % (tag, int(time.time())))
    raise WorkerError(msg, p)

# ---------- menu by command id (no mouse on popups) ----------
def menu_dump(h):
    hm = win32gui.GetMenu(h)
    out = []
    def walk(m, path):
        for i in range(win32gui.GetMenuItemCount(m)):
            try: txt = win32gui.GetMenuString(m, i, win32con.MF_BYPOSITION)
            except Exception: txt = ""
            sub = win32gui.GetSubMenu(m, i)
            mid = win32gui.GetMenuItemID(m, i)
            out.append(("/".join(map(str, path + [i])), txt, mid, bool(sub)))
            if sub: walk(sub, path + [i])
    if hm: walk(hm, [])
    return out

def menu_command(h, idx_path):
    """idx_path e.g. [4,3,2]: Nth top item, then submenu items by position. Posts WM_COMMAND with the item id."""
    m = win32gui.GetMenu(h)
    for i in idx_path[:-1]: m = win32gui.GetSubMenu(m, i)
    mid = win32gui.GetMenuItemID(m, idx_path[-1])
    if mid in (-1, 0xFFFFFFFF): raise WorkerError("menu item has no id: %s" % idx_path)
    win32gui.PostMessage(h, win32con.WM_COMMAND, mid, 0)
    return mid

def wait_responsive(h, timeout=60.0):
    """the first lookup of a session keeps the TERC UI thread busy for a while; messages posted meanwhile are delayed"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            win32gui.SendMessageTimeout(h, win32con.WM_NULL, 0, 0, win32con.SMTO_ABORTIFHUNG, 800)
            return True
        except Exception:
            time.sleep(0.2)
    return False

def menu_enabled(h, idx_path):
    m = win32gui.GetMenu(h)
    for i in idx_path[:-1]: m = win32gui.GetSubMenu(m, i)
    st = win32gui.GetMenuState(m, idx_path[-1], win32con.MF_BYPOSITION)
    if st == -1 or st == 0xFFFFFFFF: return True
    return (st & (win32con.MF_GRAYED | win32con.MF_DISABLED)) == 0

def menu_command_when_enabled(h, idx_path, timeout=5.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if menu_enabled(h, idx_path): break
        time.sleep(0.1)
    return menu_command(h, idx_path)

def out(obj, code=None):
    print(json.dumps(obj, ensure_ascii=False))
    sys.stdout.flush()
    sys.exit(code if code is not None else (0 if obj.get("ok") else 1))

# ======================= operations =======================
LOG = os.path.join(WORK, "worker.log")
def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f: f.write("%s %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception: pass

BM_GETCHECK, BM_CLICK, WM_SETTEXT = 0x00F0, 0x00F5, 0x000C

def wtext(h):
    return HwndWrapper(h).window_text()

def set_text(h, value):
    w = HwndWrapper(h)
    w.set_text(str(value))
    time.sleep(0.05)
    return w.window_text()

def is_checked(h):
    return win32gui.SendMessage(h, BM_GETCHECK, 0, 0) == 1

def msg_text(h):
    t = [c["text"] for c in children(h) if c["cls"] == "TMemo" and c["text"]]
    return (t[0] if t else " ".join(texts(h))).replace("\r", " ").replace("\n", " ").strip()

def msg_windows():
    return [w for w in wins() if w["cls"] == "TFrmFigyelmeztetes"]

class Unresolved(WorkerError): pass

def dismiss_msg(w, prefer=("ok",), strict=False):
    """read a TERC message box, press the preferred button, return its text.
    strict: raise if no preferred button exists (an unexpected question must not be left hanging)"""
    t = msg_text(w["h"])
    for lab in prefer:
        if press_button(w["h"], lab):
            wait_gone(w["h"], 3)
            return t
    if strict: raise Unresolved("ismeretlen uzenet/kerdes a TERC-ben, nincs %s gomb: %s" % ("/".join(prefer), t[:120]))
    return t

# ---- startup dialogs ----
def handle_startup_dialog(w):
    cls, title = w["cls"], w["title"]
    h = w["h"]
    if cls == "TfrmTipOn":
        return "tip:Bezár" if press_button(h, "Bezár") else None
    if cls == "TStartUpUj":
        return "starter:Megnyitás" if press_button(h, "Megnyitás") else None
    if cls == "TFrmFigyelmeztetes":
        t = msg_text(h).lower()
        if "regisztr" in t:
            dismiss_msg(w, ("ok",)); return "notice-regisztracio:Ok"
        if "frissít" in t or "aktualiz" in t or "letölt" in t or "verzió" in t:
            dismiss_msg(w, ("nem",)); return "question-frissites:Nem"
        if "méretez" in t or "ablak" in t:
            dismiss_msg(w, ("nem", "ok")); return "question-ablakmeret:Nem"
        if find_button(h, "ok") and not (find_button(h, "igen") or find_button(h, "nem")):
            dismiss_msg(w, ("ok",)); return "notice:Ok(" + t[:50] + ")"
        return None
    low = (title + " " + " ".join(texts(h))).lower()
    if "regisztr" in low:
        if press_button(h, "Bezár") or press_button(h, "Mégse"): return "regform:Bezár(nem toltom ki)"
        win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0); return "regform:WM_CLOSE"
    return None

def main_form():
    return find(lambda w: w["cls"] == "TForm1", timeout=0.2)

def op_status(a):
    ps = terc_pids(True)
    ws = wins() if ps else []
    return {"ok": True, "op": "status", "running": bool(ps), "windows": [w["title"] or w["cls"] for w in ws],
            "classes": [w["cls"] for w in ws], "budget": budget_name(),
            "budget_name": (os.path.splitext(os.path.basename(budget_name()))[0] if budget_name() else None)}

def op_start(a):
    if editor():
        return {"ok": True, "op": "start", "already": True, "budget": budget_name()}
    steps = []
    if not terc_pids(True):
        if idle_seconds() < 20 and win32gui.GetClassName(win32gui.GetForegroundWindow()) not in ("CASCADIA_HOSTING_WINDOW_CLASS", "ConsoleWindowClass"):
            return {"ok": False, "op": "start", "error": "a felhasznalo dolgozik a gepen (utolso input %.0f s, elol: %s), nem inditom" %
                    (idle_seconds(), win32gui.GetWindowText(win32gui.GetForegroundWindow())[:40])}
        subprocess.Popen([os.path.join(TERC_DIR, MAIN_EXE)], cwd=TERC_DIR)
        steps.append("launch main")
    t0 = time.time(); clicked_main = False; seen = {}
    while time.time() - t0 < 120:
        e = editor()
        if e: break
        ws = wins()
        acted = False
        for w in ws:
            if w["cls"] == "TForm1":
                if not clicked_main:
                    foreground(w["h"]); r = w["rect"]; real_click(r[0] + 200, r[1] + 121)   # KOLTSEGVETES gomb
                    clicked_main = True; steps.append("main:KOLTSEGVETES"); acted = True; time.sleep(1.0)
                continue
            if w["cls"] == EDITOR: continue
            seen[w["h"]] = seen.get(w["h"], 0) + 1
            if seen[w["h"]] > 6: fail("a(z) %s ablak nem zarodik (%s)" % (w["cls"], w["title"][:40]), "start")
            a2 = handle_startup_dialog(w)
            if a2 is None: fail("ismeretlen inditasi ablak: %s '%s' %s" % (w["cls"], w["title"][:50], texts(w["h"])[:4]), "start")
            steps.append(a2); acted = True; time.sleep(0.6)
        if not acted: time.sleep(0.4)
    if not editor(): fail("a szerkeszto ablak nem allt fel 120 s alatt", "start")
    log("start ok " + "; ".join(steps))
    return {"ok": True, "op": "start", "already": False, "steps": steps, "budget": budget_name(), "secs": round(time.time() - t0, 1)}

def need_editor():
    e = editor()
    if not e: raise WorkerError("nincs nyitott szerkeszto ablak (futtasd: start)")
    others = [w for w in wins() if w["cls"] not in (EDITOR,)]
    return e, others

def op_new(a):
    e, others = need_editor()
    if others: fail("nyitott modalis ablak(ok): " + ", ".join(w["cls"] for w in others), "new")
    if not re.match(r"^[A-Za-z0-9_.\-]+$", a.name): raise WorkerError("a --name csak betu/szam/_.- lehet")
    path = os.path.join(WORK, a.name + ".slo9")
    if os.path.exists(path) and not a.overwrite: raise WorkerError("mar letezik: " + path + " (--overwrite)")
    jelleg = a.jelleg.lower()
    if jelleg not in ("felujitas", "uj"): raise WorkerError("--jelleg felujitas|uj")
    foreground(e["h"])
    menu_command(e["h"], [0, 0])
    d = find(lambda w: w["cls"] == "TFrszNewUj" and w["title"].startswith("Új költségvetés"), timeout=8)
    if not d: fail("az 'Uj koltsegvetes alapadatai' ablak nem jelent meg", "new")
    t1 = time.time()
    while True:
        ch = children(d["h"])
        eds0 = [c for c in ch if c["cls"] == "TEdit"]
        if len(eds0) >= 2 and all(c["text"].strip() for c in eds0): break
        if time.time() - t1 > 6: break
        time.sleep(0.2)
    want = "Felújítás" if jelleg == "felujitas" else "Új"
    rb = [c for c in ch if c["cls"] == "TRadioButton" and c["text"] == want]
    if not rb: fail("nincs '%s' valasztogomb" % want, "new")
    win32gui.SendMessage(rb[0]["h"], BM_CLICK, 0, 0); time.sleep(0.2)
    if not is_checked(rb[0]["h"]):
        click_ctrl(rb[0], d["h"]); time.sleep(0.2)
    if not is_checked(rb[0]["h"]): fail("a jelleg nem allithato be: " + want, "new")
    eds = sorted([c for c in ch if c["cls"] == "TEdit"], key=lambda c: -c["rect"][1])
    rate_edit = eds[0]
    if len(eds) < 2 or not re.match(r"^\d{2,6}$", rate_edit["text"].strip()) or len(eds[1]["text"].strip()) > 3:
        fail("a rezsioradij mezo nem azonosithato (edits=%s)" % [x["text"] for x in eds], "new")
    got = set_text(rate_edit["h"], str(int(a.rezsioradij)))
    if got.strip() != str(int(a.rezsioradij)): fail("a rezsioradij mezo erteke nem allt be: " + got, "new")
    foreground(d["h"])
    if not press_button(d["h"], "Alkalmaz"): fail("nincs Alkalmaz gomb", "new")
    # save-as dialog
    sd = None; t0 = time.time()
    while time.time() - t0 < 10 and not sd:
        for w in wins():
            if w["cls"] == "#32770": sd = w; break
            if w["cls"] == "TFrmFigyelmeztetes": log("new: notice: " + dismiss_msg(w, ("ok",)))
        time.sleep(0.2)
    if not sd: fail("a 'Mentes masként' ablak nem jelent meg", "new")
    foreground(sd["h"]); time.sleep(0.3)
    esc = re.sub(r"([{}()+^%~])", r"{\1}", path)
    keyboard.send_keys("{HOME}+{END}{DEL}" + esc, pause=0.01); time.sleep(0.3)
    keyboard.send_keys("{ENTER}")
    t0 = time.time(); stable_since = None
    while time.time() - t0 < 20:
        e2 = editor()
        sdw = [w for w in wins() if w["cls"] == "#32770"]
        busy = False
        for w in sdw:
            busy = True
            if "megerős" in w["title"].lower() or "felül" in " ".join(texts(w["h"])).lower():
                if a.overwrite: press_button(w["h"], "Igen")
                else: fail("felulirast kerdez a mentes", "new")
        for w in msg_windows():
            busy = True
            if "felülír" in msg_text(w["h"]).lower():
                if a.overwrite: dismiss_msg(w, ("igen",), strict=True); log("new: felulir: Igen")
                else:
                    dismiss_msg(w, ("nem",)); fail("a fajl mar letezik, felulirast kerdez a TERC", "new")
            else:
                log("new: notice: " + dismiss_msg(w, ("ok",), strict=True))
        if e2 and a.name.lower() + ".slo9" in e2["title"].lower() and not busy:
            if stable_since is None: stable_since = time.time()
            elif time.time() - stable_since > 2.0: break      # the overwrite question can come late
        else:
            stable_since = None
        time.sleep(0.25)
    e2 = editor()
    if not e2 or a.name.lower() + ".slo9" not in e2["title"].lower(): fail("a mentes utan nem az uj koltsegvetes van nyitva", "new")
    # read back rate from the program ('Koltsegves alapadatainak modositasa')
    menu_command(e2["h"], [0, 7])
    d2 = find(lambda w: w["cls"] == "TFrszNewUj" and "módosítása" in w["title"], timeout=8)
    if not d2: fail("az alapadat-modosito ablak nem nyilt meg (visszaolvasas)", "new")
    t1 = time.time()
    while True:
        ch2 = children(d2["h"])
        if len([c for c in ch2 if c["cls"] == "TEdit" and c["text"].strip()]) >= 2 or time.time() - t1 > 6: break
        time.sleep(0.2)
    eds2 = sorted([c for c in ch2 if c["cls"] == "TEdit"], key=lambda c: -c["rect"][1])
    back = wtext(eds2[0]["h"]).strip()
    fel = [c for c in ch2 if c["cls"] == "TRadioButton" and c["text"] == "Felújítás"]
    uj = [c for c in ch2 if c["cls"] == "TRadioButton" and c["text"] == "Új"]
    jb = "felujitas" if (fel and is_checked(fel[0]["h"])) else ("uj" if (uj and is_checked(uj[0]["h"])) else None)
    press_button(d2["h"], "Mégse"); wait_gone(d2["h"], 4)
    ok = back == str(int(a.rezsioradij)) and jb == jelleg
    log("new %s rate_back=%s jelleg_back=%s" % (a.name, back, jb))
    res = {"ok": ok, "op": "new", "budget": path, "rezsioradij_visszaolvasva": back, "jelleg_visszaolvasva": jb}
    if not ok: res["error"] = "a visszaolvasott rezsioradij/jelleg nem egyezik"
    return res

def fmt_qty(x):
    x = float(x)
    s = ("%d" % x) if x == int(x) else ("%.4f" % x).rstrip("0").rstrip(".")
    return s.replace(".", ",")

def get_picker():
    return find(lambda w: w["cls"] == "TFrmOnAdatt", timeout=0.3)

def ensure_picker():
    p = get_picker()
    if p: return p
    e = editor()
    if not e: raise WorkerError("a szerkeszto ablak elveszett")
    foreground(e["h"])
    menu_command(e["h"], [2, 1])                    # Adattarak - Tetel kivalasztas (F12)
    p = find(lambda w: w["cls"] == "TFrmOnAdatt", timeout=8)
    if not p: raise WorkerError("a tetelkivalaszto ablak nem nyilik")
    return p

def picker_fields(p):
    """ENGY edit = lowest TEdit in the left column, unit edit = the one above it"""
    ch = [c for c in children(p["h"]) if c["cls"] == "TEdit"]
    left = sorted([c for c in ch if abs(c["rect"][0] - p["rect"][0] - 77) < 15], key=lambda c: c["rect"][1])
    if len(left) < 2: raise WorkerError("a tetelkivalaszto mezoi nem azonosithatok")
    return left[-1], left[-2]     # engy, unit

def add_one(it):
    engy = re.sub(r"\s+", "", str(it.get("engy", "")))
    rec = {"engy": engy, "menny": it.get("menny"), "status": None}
    t0 = time.time()
    if not re.match(r"^\d{12}$", engy):
        rec["status"] = "BUKOTT: az ENGY kod nem 12 szamjegy"; rec["secs"] = 0; return rec
    for w in msg_windows(): dismiss_msg(w, ('ok',), strict=True)
    p = ensure_picker()
    foreground(p["h"])
    f_engy, f_unit = picker_fields(p)
    def memo_now():
        m = [c["text"] for c in children(p["h"]) if c["cls"] == "TMemo"]
        return (m[0] if m else "")
    memo_before = memo_now(); title_before = win32gui.GetWindowText(p["h"])
    set_text(f_unit["h"], "")                      # negative control: the lookup must repopulate this
    got = set_text(f_engy["h"], engy)
    if got.strip() != engy: rec["status"] = "BUKOTT: az ENGY mezo nem allithato"; return rec
    menu_command(p["h"], [1, 3])                   # Adattar - ENGY (MVH) tetelszammal beolvas
    loaded = False; t1 = time.time()
    while time.time() - t1 < 4:
        ms = msg_windows()
        if ms:
            rec["status"] = "BUKOTT: " + dismiss_msg(ms[0]); rec["secs"] = round(time.time() - t0, 1); return rec
        unit = wtext(f_unit["h"]).strip()
        if unit and unit != engy: loaded = True; break
        time.sleep(0.1)
    if not loaded:
        rec["status"] = "BUKOTT: a lookup nem toltott be tetelt (nincs egyseg, nincs uzenet)"; rec["secs"] = round(time.time() - t0, 1); return rec
    # wait until the tree navigation has settled (first lookup of a session is slow): memo/title changed, or 1.5 s
    t2 = time.time()
    while time.time() - t2 < 20:
        mn = memo_now()
        if mn.strip() and (mn != memo_before or win32gui.GetWindowText(p["h"]) != title_before): break
        if time.time() - t2 > 1.5 and mn.strip() and mn == memo_before: break
        time.sleep(0.15)
    time.sleep(0.2)
    memo = [memo_now()]
    rec["tetel"] = (memo[0] if memo else "").replace("\r\n", " ")[:90]
    rec["egyseg"] = unit
    foreground(p["h"])
    d = None
    wait_responsive(p["h"], 60)
    for attempt in range(4):
        if attempt == 0:
            menu_command_when_enabled(p["h"], [1, 0])          # WM_COMMAND: Adattar - Aktualis tetel koltsegvetesbe rogzitese
        else:
            wait_responsive(p["h"], 30)
            foreground(p["h"])
            keyboard.send_keys("%a"); time.sleep(0.4); keyboard.send_keys("{ENTER}")   # same menu item with real keyboard input
        d = find(lambda w: w["cls"] == "TFrmAzonnaliRogzitesOn", timeout=4 if attempt == 0 else 5)
        if d: break
        rec.setdefault("megjegyzes", "rogzites ujraprobalva (%d)" % (attempt + 1))
    if not d: rec["status"] = "BUKOTT: a rogzito ablak nem nyilt meg"; rec["secs"] = round(time.time() - t0, 1); return rec
    qe = [c for c in children(d["h"]) if c["cls"] == "TEdit"]
    if len(qe) != 1: rec["status"] = "BUKOTT: a mennyiseg mezo nem azonosithato"; win32gui.PostMessage(d["h"], win32con.WM_CLOSE, 0, 0); return rec
    qtxt = fmt_qty(it["menny"])
    if set_text(qe[0]["h"], qtxt).strip() != qtxt: rec["status"] = "BUKOTT: a mennyiseg nem allt be"; press_button(d["h"], "Mégsem"); return rec
    if not press_button(d["h"], "Rögzítés"): rec["status"] = "BUKOTT: nincs Rogzites gomb"; return rec
    t1 = time.time(); res = None
    while time.time() - t1 < 8 and res is None:
        dd = find(lambda w: w["cls"] == "TFrmMarVanIlyenTetel", timeout=0.1)
        if dd:
            press_button(dd["h"], "Nem"); wait_gone(dd["h"], 3); res = "MAR_VOLT"; break
        for w in msg_windows():
            t = dismiss_msg(w)
            res = "OK" if "felvételre került" in t else "BUKOTT: " + t
        time.sleep(0.1)
    rec["status"] = res or "BUKOTT: nincs visszaigazolas a rogzitesre"
    rec["secs"] = round(time.time() - t0, 1)
    return rec

STRUCT = ("rogzito ablak nem nyilt", "mezoi nem azonosithatok", "tetelkivalaszto ablak nem nyilik", "mennyiseg mezo", "elveszett")

def op_add(a):
    e, others = need_editor()
    foreign = [w for w in others if w["cls"] != "TFrmOnAdatt"]
    if foreign: fail("nyitott modalis ablak(ok): " + ", ".join(w["cls"] for w in foreign), "add")
    consec = 0
    items = json.load(open(a.items, encoding="utf-8-sig"))
    out_items = []; lost = None
    for it in items:
        try:
            rec = add_one(it)
        except WorkerError as ex:
            rec = {"engy": it.get("engy"), "menny": it.get("menny"), "status": "BUKOTT: " + str(ex)}
        except Exception as ex:
            rec = {"engy": it.get("engy"), "menny": it.get("menny"), "status": "BUKOTT: kivetel " + repr(ex)[:120]}
        out_items.append(rec)
        log("add %s -> %s" % (rec.get("engy"), rec.get("status")))
        consec = consec + 1 if any(k in rec["status"] for k in STRUCT) else 0
        if consec >= 3:
            lost = "3 egymas utani szerkezeti hiba (modalis ablak?), megallok"; break
        if not editor():
            lost = "a szerkeszto ablak elveszett"; break
        if rec["status"].startswith("BUKOTT"):
            for w in msg_windows(): dismiss_msg(w)
            for x in wins():
                if x["cls"] == "TFrmAzonnaliRogzitesOn": win32gui.PostMessage(x["h"], win32con.WM_CLOSE, 0, 0); time.sleep(0.3)
    p = get_picker()
    if p: win32gui.PostMessage(p["h"], win32con.WM_CLOSE, 0, 0); wait_gone(p["h"], 3)
    ok_db = sum(1 for r in out_items if r["status"] in ("OK",))
    mar = sum(1 for r in out_items if r["status"] == "MAR_VOLT")
    hiba = sum(1 for r in out_items if r["status"].startswith("BUKOTT"))
    res = {"ok": lost is None, "op": "add", "items": out_items, "ok_db": ok_db, "mar_volt_db": mar, "hiba_db": hiba, "osszes": len(items)}
    if lost: res["error"] = lost; res["shot"] = shot("err_add_%d" % int(time.time()))
    return res

def op_export(a):
    e, others = need_editor()
    if others: fail("nyitott modalis ablak(ok): " + ", ".join(w["cls"] for w in others), "export")
    out_path = os.path.abspath(a.out)
    if not out_path.lower().startswith(WORK.lower() + os.sep) or not out_path.lower().endswith((".xls", ".xlsx")):
        raise WorkerError("az --out a %s alatt legyen, .xls kiterjesztessel" % WORK)
    if os.path.exists(out_path): os.remove(out_path)
    foreground(e["h"])
    menu_command(e["h"], [4, 25, 1])                # Koltsegvetes - Exportalasok - Excel allomanyba (uj beta)
    d = find(lambda w: "exportálása Excel" in w["title"] or w["cls"] == "TFrmExcelOnUj", timeout=8)
    if not d: fail("az export ablak nem nyilt meg", "export")
    ch = children(d["h"])
    cbs = [c for c in ch if c["cls"] == "TCheckBox"]
    if not any("Anyag+Díj" in c["text"] for c in cbs): fail("nem az 'uj beta' export ablak nyilt meg", "export")
    built = [c for c in ch if c["cls"] == "TRadioButton" and "beépített" in c["text"]]
    if not built: fail("nincs 'beepitett szolgaltatas' valasztogomb", "export")
    win32gui.SendMessage(built[0]["h"], BM_CLICK, 0, 0); time.sleep(0.2)
    if not is_checked(built[0]["h"]): fail("a beepitett szolgaltatas nem valaszthato", "export")
    for c in cbs:
        if "Árazatlan" in c["text"] and is_checked(c["h"]): win32gui.SendMessage(c["h"], BM_CLICK, 0, 0)
    fe = [c for c in ch if c["cls"] == "TEdit"]
    if len(fe) != 1: fail("a fajlnev mezo nem azonosithato (%d edit)" % len(fe), "export")
    if set_text(fe[0]["h"], out_path).strip().lower() != out_path.lower(): fail("a fajlnev nem allt be", "export")
    foreground(d["h"])
    if not press_button(d["h"], "Exportálás"): fail("nincs Exportalas gomb", "export")
    t0 = time.time(); said = None
    while time.time() - t0 < 30:
        ms = msg_windows()
        if ms: said = dismiss_msg(ms[0]); break
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0 and time.time() - t0 > 3: break
        time.sleep(0.2)
    press_button(d["h"], "Bezár"); wait_gone(d["h"], 4)
    size = os.path.getsize(out_path) if os.path.exists(out_path) else 0
    ok = size > 0
    res = {"ok": ok, "op": "export", "file": out_path, "size": size, "program_uzenet": said}
    if not ok: res["error"] = "a fajl nem jott letre / ures"; res["shot"] = shot("err_export_%d" % int(time.time()))
    return res

def op_close(a):
    steps = []
    e = editor()
    if e:
        foreground(e["h"]); menu_command(e["h"], [0, 26]); steps.append("Kilepes a fomenube")
        t0 = time.time()
        while time.time() - t0 < 15 and (editor() or msg_windows()):
            for w in msg_windows():
                t = dismiss_msg(w, ("igen", "ok")); steps.append("uzenet:" + t[:50])
            time.sleep(0.3)
        if editor(): fail("a szerkeszto ablak nem zarodott be", "close")
    t0 = time.time()
    while terc_pids(True) and time.time() - t0 < 15:
        mf = main_form()
        if mf and not steps[-1:] == ["main:KILEPES"]:
            foreground(mf["h"]); r = mf["rect"]; real_click(r[0] + 241, r[1] + 318); steps.append("main:KILEPES"); time.sleep(1.5); continue
        for w in msg_windows():
            steps.append("uzenet:" + dismiss_msg(w, ("igen", "ok"))[:50])
        time.sleep(0.4)
    left = sorted(terc_pids(True))
    if left: fail("a TERC folyamat(ok) futnak: %s" % left, "close")
    return {"ok": True, "op": "close", "steps": steps}

def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="op", required=True)
    sp.add_parser("status"); sp.add_parser("start"); sp.add_parser("close")
    n = sp.add_parser("new"); n.add_argument("--name", required=True); n.add_argument("--rezsioradij", required=True, type=float)
    n.add_argument("--jelleg", default="felujitas"); n.add_argument("--overwrite", action="store_true")
    ad = sp.add_parser("add"); ad.add_argument("--items", required=True)
    ex = sp.add_parser("export"); ex.add_argument("--out", required=True)
    a = ap.parse_args()
    t0 = time.time()
    try:
        res = {"status": op_status, "start": op_start, "new": op_new, "add": op_add, "export": op_export, "close": op_close}[a.op](a)
    except WorkerError as ex:
        res = {"ok": False, "op": a.op, "error": str(ex)}
        if ex.shot: res["shot"] = ex.shot
        else:
            try: res["shot"] = shot("err_%s_%d" % (a.op, int(time.time())))
            except Exception: pass
    except Exception as ex:
        res = {"ok": False, "op": a.op, "error": "kivetel: " + repr(ex)[:300], "trace": traceback.format_exc()[-600:]}
        try: res["shot"] = shot("err_%s_%d" % (a.op, int(time.time())))
        except Exception: pass
    res["elapsed_s"] = round(time.time() - t0, 1)
    out(res)

if __name__ == "__main__":
    main()
