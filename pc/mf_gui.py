"""Melofinds PC — panneau de gestion (l'installation est faite par MelofindsSetup.exe).

Même identité que Melofinds Web : anthracite profond, accent violet, chiffres en mono.
Menu à gauche : Accueil (en ligne, téléchargement en cours), Mes projets FL, FLmake,
Appareils, Réglages.
"""

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import mf_core as C
import mf_flmake as FM
import mf_install as I
import mf_library as L
from mf_core import P

# Couleurs de Melofinds Web (artifact/style.css)
BG, BG2, PANEL, PANEL2, PANEL3 = "#0b0c10", "#101217", "#15171d", "#1b1e26", "#242833"
LINE, LINE2 = "#23262f", "#323745"
FG, MUTED, FAINT = "#f3f4f7", "#a0a6b6", "#6e7487"
TB_BLUE = "#60a5fa"  # clé / BPM trouvés avec Tunebat (comme dans l'app web)
ACCENT, ACCENT2, PINK = "#a78bfa", "#8b5cf6", "#ec4899"
GREEN, AMBER, RED, BLUE = "#34d399", "#fbbf24", "#f87171", "#60a5fa"
FONT = "Segoe UI" if C.WINDOWS else "DejaVu Sans"
SYMB = "Segoe UI Symbol" if C.WINDOWS else "DejaVu Sans"  # icônes ♪ ★ ⚡ …
MONO = "Consolas" if C.WINDOWS else "DejaVu Sans Mono"
LIC_COLORS = {"FFP": GREEN, "F": BLUE}

SITE_URL = "https://kimany91.github.io/Melofinds/"


def blend(color, base, t):
    """Mélange color (proportion t) avec base : teinte douce d'une couleur sur le fond."""
    a = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(base[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * t + y * (1 - t)):02x}" for x, y in zip(a, b))


def _ago(ts):
    if not ts:
        return "jamais"
    s = time.time() - ts
    if s < 90:
        return "à l'instant"
    if s < 3600:
        return f"il y a {int(s // 60)} min"
    if s < 86400:
        return f"il y a {int(s // 3600)} h"
    if s < 7 * 86400:
        return f"il y a {int(s // 86400)} j"
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y")


def _chrome_path():
    """Chrome installé sur ce PC (dossiers habituels, puis le registre Windows)."""
    cands = []
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            cands.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
    for p in cands:
        if p.exists():
            return str(p)
    if C.WINDOWS:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe") as k:
                    v = winreg.QueryValueEx(k, None)[0]
                    if v and Path(v).exists():
                        return v
            except OSError:
                pass
    import shutil
    return shutil.which("google-chrome") or shutil.which("chrome")


def open_site():
    """Ouvre Melofinds Web dans Chrome (sinon le navigateur par défaut)."""
    chrome = _chrome_path()
    if chrome:
        try:
            subprocess.Popen([chrome, SITE_URL], close_fds=True)
            return
        except OSError:
            pass
    import webbrowser
    webbrowser.open(SITE_URL)


def _open_path(p):
    try:
        if C.WINDOWS:
            os.startfile(str(p))  # noqa: S606 (dossier choisi par l'utilisateur)
        else:
            subprocess.Popen(["xdg-open", str(p)])
    except OSError:
        pass


def _mmss(sec):
    sec = int(sec or 0)
    return f"{sec // 60}:{sec % 60:02d}"


class Player:
    """Lecture des sons dans le panneau avec le lecteur intégré à Windows (MCI) : .wav,
    .mp3…, pause, reprise, position. Ailleurs : le lecteur par défaut du système."""

    def __init__(self):
        self.path = None
        self.length = 0
        self.ok = C.WINDOWS
        if self.ok:
            import ctypes
            self._send = ctypes.windll.winmm.mciSendStringW
            self._buf = ctypes.create_unicode_buffer(256)

    def _cmd(self, text):
        if not self.ok:
            return None
        return self._buf.value if self._send(text, self._buf, 255, 0) == 0 else None

    def play(self, path):
        self.stop()
        p = str(path).replace('"', "")
        if not self.ok or (self._cmd(f'open "{p}" type mpegvideo alias mfplay') is None and self._cmd(f'open "{p}" alias mfplay') is None):
            _open_path(path)
            return False
        self._cmd("set mfplay time format milliseconds")
        try:
            self.length = int(self._cmd("status mfplay length") or 0)
        except ValueError:
            self.length = 0
        self._cmd("play mfplay")
        self.path = str(path)
        return True

    def mode(self):
        return (self._cmd("status mfplay mode") or "stopped") if self.path else None

    def position(self):
        try:
            return int(self._cmd("status mfplay position") or 0) if self.path else 0
        except ValueError:
            return 0

    def toggle(self):
        m = self.mode()
        if m == "playing":
            self._cmd("pause mfplay")
        elif m in ("paused", "stopped"):
            self._cmd("play mfplay")

    def seek(self, frac):
        if not self.path or not self.length:
            return
        ms = int(max(0.0, min(1.0, frac)) * self.length)
        was = self.mode()
        self._cmd(f"seek mfplay to {ms}")
        if was == "playing":
            self._cmd("play mfplay")

    def stop(self):
        if self.path:
            self._cmd("close mfplay")
        self.path, self.length = None, 0

    def is_(self, path):
        return bool(self.path) and str(path).lower() == self.path.lower()


PLAYER = Player()


def read_progress():
    """Téléchargement en cours (écrit par le programme en ligne), ou None."""
    try:
        p = json.loads(P.progress.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(p, dict) or time.time() - float(p.get("at") or 0) > 120:
        return None
    return p


STAGES = {"info": "Recherche de la vidéo…", "download": "Téléchargement", "convert": "Conversion en WAV…",
          "tunebat": "Clé / BPM manquants : recherche sur Tunebat…", "flp": "Création du projet FL…"}


# ---------------------------------------------------------------------------
# Petits composants (Tk) au style de Melofinds Web

SCROLLERS = {}


def _ui():
    import tkinter as tk
    from tkinter import ttk

    class Btn(tk.Label):
        """Bouton plat : primary (violet), ghost (gris), danger, subtle (texte)."""
        KINDS = {"primary": (ACCENT2, "#ffffff", "#7c3aed"), "ghost": (PANEL2, FG, PANEL3),
                 "danger": (PANEL2, RED, PANEL3), "subtle": (None, MUTED, None), "online": (GREEN, BG, "#10b981")}

        def __init__(self, parent, text, command=None, kind="ghost", size=10, padx=14, pady=7, **kw):
            self.bg_parent = parent.cget("bg")
            bg, fg, hover = self.KINDS[kind]
            super().__init__(parent, text=text, bg=bg or self.bg_parent, fg=fg, font=(FONT, size, "bold"),
                             padx=padx, pady=pady, cursor="hand2", **kw)
            self.kind, self.command, self.enabled = kind, command, True
            self.bind("<Enter>", lambda e: self.enabled and self.configure(bg=hover or self.bg_parent, fg=FG if kind == "subtle" else fg))
            self.bind("<Leave>", lambda e: self.restyle())
            self.bind("<Button-1>", lambda e: self.enabled and self.command and self.command())

        def restyle(self):
            bg, fg, _ = self.KINDS[self.kind]
            self.configure(bg=bg or self.bg_parent, fg=fg if self.enabled else FAINT)

        def set(self, text=None, kind=None, enabled=None):
            if text is not None:
                self.configure(text=text)
            if kind:
                self.kind = kind
            if enabled is not None:
                self.enabled = enabled
                self.configure(cursor="hand2" if enabled else "arrow")
            self.restyle()

    class Switch(tk.Canvas):
        """Interrupteur on/off."""

        def __init__(self, parent, value=False, command=None):
            super().__init__(parent, width=40, height=22, bg=parent.cget("bg"), highlightthickness=0, cursor="hand2")
            self.value, self.command = bool(value), command
            self.bind("<Button-1>", lambda e: self.toggle())
            self.draw()

        def draw(self):
            self.delete("all")
            c = ACCENT2 if self.value else PANEL3
            self.create_oval(1, 1, 21, 21, fill=c, outline=c)
            self.create_oval(19, 1, 39, 21, fill=c, outline=c)
            self.create_rectangle(11, 1, 29, 21, fill=c, outline=c)
            x = 20 if self.value else 3
            self.create_oval(x, 3, x + 16, 19, fill="#ffffff", outline="")

        def set(self, v):
            self.value = bool(v)
            self.draw()

        def toggle(self):
            self.set(not self.value)
            if self.command:
                self.command(self.value)

    class Bar(tk.Canvas):
        """Barre de progression (pourcentage, ou animation quand on ne sait pas)."""

        def __init__(self, parent):
            super().__init__(parent, height=8, bg=parent.cget("bg"), highlightthickness=0)
            self.pct, self.phase = 0.0, 0.0
            self.bind("<Configure>", lambda e: self.draw())

        def draw(self):
            self.delete("all")
            w = max(10, self.winfo_width())
            self.create_rectangle(0, 0, w, 8, fill=PANEL3, outline="")
            if self.pct is None:  # étape sans pourcentage : un segment qui glisse
                seg = w * 0.28
                x = (self.phase % 1.0) * (w + seg) - seg
                self.create_rectangle(max(0, x), 0, min(w, x + seg), 8, fill=ACCENT2, outline="")
            else:
                fw = w * max(0.0, min(100.0, self.pct)) / 100
                if fw > 0:
                    self.create_rectangle(0, 0, fw * 0.7, 8, fill=ACCENT2, outline="")
                    self.create_rectangle(fw * 0.7, 0, fw, 8, fill=PINK if fw > 40 else ACCENT2, outline="")

        def set(self, pct):
            self.pct = pct
            self.draw()

        def tick(self):
            if self.pct is None:
                self.phase += 0.025
                self.draw()

    def card(parent, padx=18, pady=16, **kw):
        f = tk.Frame(parent, bg=PANEL, highlightthickness=1, highlightbackground=LINE, padx=padx, pady=pady, **kw)
        return f

    def label(parent, text="", size=10, color=FG, bold=False, mono=False, wrap=0, **kw):
        return tk.Label(parent, text=text, bg=parent.cget("bg"), fg=color, justify="left", anchor="w",
                        font=(MONO if mono else FONT, size, "bold" if bold else "normal"), wraplength=wrap, **kw)

    def entry(parent, var, width=30, readonly=False):
        e = tk.Entry(parent, textvariable=var, width=width, bg=PANEL2, fg=FG, insertbackground=FG, relief="flat",
                     highlightthickness=1, highlightbackground=LINE2, highlightcolor=ACCENT, font=(FONT, 10),
                     readonlybackground=PANEL2, disabledforeground=MUTED)
        if readonly:
            e.configure(state="readonly")
        return e

    def scroll_area(parent):
        canvas = tk.Canvas(parent, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview, style="Dark.Vertical.TScrollbar")
        body = tk.Frame(canvas, bg=BG)
        win = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        SCROLLERS[str(canvas)] = (canvas, body)
        if not SCROLLERS.get("_bound"):
            SCROLLERS["_bound"] = True

            def wheel(e):
                w = e.widget.winfo_containing(e.x_root, e.y_root) if hasattr(e.widget, "winfo_containing") else None
                path = str(w) if w else ""
                for key, val in SCROLLERS.items():
                    if key == "_bound":
                        continue
                    cv, bd = val
                    if path.startswith(key) and bd.winfo_height() > cv.winfo_height():
                        step = -1 if getattr(e, "num", 0) == 4 or getattr(e, "delta", 0) > 0 else 1
                        cv.yview_scroll(step * 3, "units")
                        return
            for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                canvas.bind_all(ev, wheel, add="+")
        return body

    SCROLLERS.clear()
    return tk, ttk, Btn, Switch, Bar, card, label, entry, scroll_area


def _style(root):
    from tkinter import ttk
    root.configure(bg=BG)
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except Exception:
        pass
    st.configure(".", background=BG, foreground=FG, font=(FONT, 10), fieldbackground=PANEL2, bordercolor=LINE)
    st.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG, rowheight=34, borderwidth=0,
                 font=(FONT, 10), lightcolor=PANEL, darkcolor=PANEL, bordercolor=PANEL)
    st.configure("Treeview.Heading", background=PANEL, foreground=FAINT, font=(FONT, 9, "bold"), borderwidth=0,
                 relief="flat", padding=(8, 8), lightcolor=PANEL, darkcolor=PANEL, bordercolor=LINE)
    st.map("Treeview.Heading", background=[("active", PANEL2)])
    st.map("Treeview", background=[("selected", PANEL3)], foreground=[("selected", FG)])
    st.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    st.configure("Dark.Vertical.TScrollbar", background=PANEL2, troughcolor=BG, bordercolor=BG, arrowcolor=MUTED,
                 lightcolor=PANEL2, darkcolor=PANEL2, gripcount=0, relief="flat")
    st.map("Dark.Vertical.TScrollbar", background=[("active", PANEL3)])
    return st


def _icon(root):
    try:
        import tkinter as tk
        img = tk.PhotoImage(width=32, height=32)
        img.put(ACCENT2, to=(0, 0, 32, 32))
        img.put("#ffffff", to=(8, 14, 11, 24))
        img.put("#ffffff", to=(14, 9, 17, 24))
        img.put("#ffffff", to=(20, 12, 23, 24))
        root.iconphoto(True, img)
        root._icon = img
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Panneau de gestion

def manager_window(selftest=False):
    from tkinter import filedialog, messagebox, simpledialog
    tk, ttk, Btn, Switch, Bar, card, label, entry, scroll_area = _ui()

    root = tk.Tk()
    root.title("Melofinds PC")
    root.geometry("1040x700")
    root.minsize(880, 580)
    _style(root)
    _icon(root)

    # ----- Mise en page : menu à gauche, page à droite
    side = tk.Frame(root, bg=BG2, width=230, highlightthickness=0)
    side.pack(side="left", fill="y")
    side.pack_propagate(False)
    tk.Frame(root, bg=LINE, width=1).pack(side="left", fill="y")
    main = tk.Frame(root, bg=BG)
    main.pack(side="left", fill="both", expand=True)

    logo = tk.Frame(side, bg=BG2, padx=20, pady=22)
    logo.pack(fill="x")
    mark = tk.Canvas(logo, width=30, height=30, bg=BG2, highlightthickness=0)
    mark.pack(side="left")
    for i, (x, h, c) in enumerate(((5, 14, ACCENT2), (13, 22, "#b14fe0"), (21, 17, PINK))):
        mark.create_rectangle(x, 30 - h - 4, x + 5, 26, fill=c, outline="")
    tl = tk.Frame(logo, bg=BG2)
    tl.pack(side="left", padx=10)
    label(tl, "Melofinds", 14, bold=True).pack(anchor="w")
    label(tl, "PC", 8, FAINT, bold=True).pack(anchor="w")

    nav = tk.Frame(side, bg=BG2, padx=10)
    nav.pack(fill="x", pady=(6, 0))
    pages, nav_items = {}, {}
    current = {"page": None}

    def nav_item(key, text, glyph):
        row = tk.Frame(nav, bg=BG2, cursor="hand2")
        row.pack(fill="x", pady=1)
        bar = tk.Frame(row, bg=BG2, width=3)
        bar.pack(side="left", fill="y")
        g = tk.Label(row, text=glyph, bg=BG2, fg=FAINT, font=(FONT, 11))
        g.pack(side="left", padx=(12, 0), pady=9)
        t = tk.Label(row, text=text, bg=BG2, fg=MUTED, font=(FONT, 10, "bold"))
        t.pack(side="left", pady=9)
        badge = tk.Label(row, text="", bg=BG2, fg=ACCENT, font=(MONO, 9, "bold"))
        badge.pack(side="right", padx=10)
        nav_items[key] = (row, bar, g, t, badge)
        for w in (row, g, t, badge):
            w.bind("<Button-1>", lambda e, k=key: show(k))
            w.bind("<Enter>", lambda e, k=key: current["page"] != k and paint(k, hover=True))
            w.bind("<Leave>", lambda e, k=key: paint(k))

    def paint(key, hover=False):
        row, bar, g, t, badge = nav_items[key]
        on = current["page"] == key
        bg = PANEL2 if on else (PANEL if hover else BG2)
        for w in (row, g, t, badge):
            w.configure(bg=bg)
        bar.configure(bg=ACCENT2 if on else bg)
        t.configure(fg=FG if on else MUTED)
        g.configure(fg=ACCENT if on else FAINT)

    for k, txt, gl in (("home", "File d'attente", ""), ("prods", "Mes projets FL", ""), ("flmake", "FLmake", ""),
                       ("devices", "Appareils", ""), ("settings", "Réglages", "")):
        nav_item(k, txt, gl)

    # Bas du menu : état + mise en ligne
    foot = tk.Frame(side, bg=BG2, padx=14, pady=16)
    foot.pack(side="bottom", fill="x")
    status_box = tk.Frame(foot, bg=PANEL, highlightthickness=1, highlightbackground=LINE, padx=12, pady=12)
    status_box.pack(fill="x")
    srow = tk.Frame(status_box, bg=PANEL)
    srow.pack(fill="x")
    dot = tk.Canvas(srow, width=12, height=12, bg=PANEL, highlightthickness=0)
    dot.pack(side="left", padx=(0, 8))
    dot_id = dot.create_oval(1, 1, 11, 11, fill=MUTED, outline="")
    status_lbl = label(srow, "…", 11, bold=True)
    status_lbl.pack(side="left")
    status_sub = label(status_box, "", 9, MUTED, wrap=180)
    status_sub.pack(anchor="w", pady=(4, 10))
    toggle = Btn(status_box, "Mettre en ligne", kind="online", pady=8)
    toggle.pack(fill="x")
    Btn(foot, "Ouvrir Melofinds Web ↗", kind="subtle", command=open_site, padx=0, pady=10).pack(anchor="w")
    label(foot, f"version {C.VERSION}", 8, FAINT, mono=True).pack(anchor="w")

    # En-tête de page + zone de message
    head = tk.Frame(main, bg=BG, padx=30, pady=22)
    head.pack(fill="x")
    page_title = label(head, "", 20, bold=True)
    page_title.pack(anchor="w")
    page_sub = label(head, "", 10, MUTED, wrap=720)
    page_sub.pack(anchor="w", pady=(2, 0))
    toast_lbl = tk.Label(main, text="", bg=PANEL3, fg=FG, font=(FONT, 10), padx=14, pady=9)
    toast_state = {"after": None}

    def toast(msg, ms=4500):
        if not msg:
            return
        toast_lbl.configure(text=msg)
        toast_lbl.place(relx=0.5, rely=1.0, y=-18, anchor="s")
        toast_lbl.lift()
        if toast_state["after"]:
            root.after_cancel(toast_state["after"])
        toast_state["after"] = root.after(ms, toast_lbl.place_forget)

    body = tk.Frame(main, bg=BG)
    body.pack(fill="both", expand=True)

    def page(key, title, sub, scroll=False):
        outer = tk.Frame(body, bg=BG)
        inner = scroll_area(outer) if scroll else outer
        content = tk.Frame(inner, bg=BG, padx=30)
        content.pack(fill="both", expand=True, pady=(0, 24))
        pages[key] = (outer, title, sub)
        return content

    on_show = {}

    def show(key):
        current["page"] = key
        for k, (f, _, _) in pages.items():
            f.pack_forget()
        f, t, s = pages[key]
        page_title.configure(text=t)
        page_sub.configure(text=s)
        f.pack(fill="both", expand=True)
        for k in nav_items:
            paint(k)
        if key in on_show:
            on_show[key]()

    # ================= Accueil
    home = page("home", "File d'attente", "Les prods envoyées depuis Melofinds Web : celle qui arrive, celles qui attendent, "
                                          "et les dernières reçues (en .wav, dans ton dossier des projets).")
    dl = card(home)
    dl.pack(fill="x", pady=(0, 14))
    dl_top = tk.Frame(dl, bg=PANEL)
    dl_top.pack(fill="x")
    label(dl_top, "TÉLÉCHARGEMENT", 8, FAINT, bold=True).pack(side="left")
    dl_queue = label(dl_top, "", 9, ACCENT, bold=True)
    dl_queue.pack(side="right")
    dl_title = label(dl, "Aucun téléchargement en cours", 13, bold=True, wrap=680)
    dl_title.pack(anchor="w", pady=(8, 2))
    dl_stage = label(dl, "Les prods envoyées depuis ton téléphone s'affichent ici pendant qu'elles arrivent.", 10, MUTED, wrap=680)
    dl_stage.pack(anchor="w")
    dl_barrow = tk.Frame(dl, bg=PANEL)
    dl_bar = Bar(dl_barrow)
    dl_bar.pack(side="left", fill="x", expand=True, pady=(12, 0))
    dl_pct = label(dl_barrow, "", 10, FG, bold=True, mono=True)
    dl_pct.pack(side="left", padx=(12, 0), pady=(10, 0))

    waitc = card(home, pady=12)
    waitc.pack(fill="x", pady=(0, 14))
    label(waitc, "EN ATTENTE", 8, FAINT, bold=True).pack(anchor="w")
    wait_box = tk.Frame(waitc, bg=PANEL)
    wait_box.pack(fill="x", pady=(6, 0))
    wait_state = {"sig": None}

    def fill_wait(items):
        if items == wait_state["sig"]:
            return
        wait_state["sig"] = items
        for w in wait_box.winfo_children():
            w.destroy()
        if not items:
            label(wait_box, "Rien en attente. Les prods envoyées pendant qu'une autre arrive s'affichent ici.", 10, MUTED, wrap=680).pack(anchor="w")
            return
        for n, t in enumerate(items[:12], 1):
            r = tk.Frame(wait_box, bg=PANEL)
            r.pack(fill="x", pady=2)
            label(r, f"{n}", 9, FAINT, mono=True).pack(side="left", padx=(0, 10))
            label(r, t, 10, FG).pack(side="left")
        if len(items) > 12:
            label(wait_box, f"+ {len(items) - 12} autres", 9, FAINT).pack(anchor="w", pady=(4, 0))
    fill_wait([])

    recent = card(home, pady=12)
    recent.pack(fill="both", expand=True)
    rh = tk.Frame(recent, bg=PANEL)
    rh.pack(fill="x", pady=(0, 6))
    label(rh, "Dernières prods reçues", 11, bold=True).pack(side="left")
    Btn(rh, "Voir mes projets FL →", kind="subtle", command=lambda: show("prods"), padx=0).pack(side="right")
    hist = ttk.Treeview(recent, columns=("ok", "prod", "quand"), show="", height=7, selectmode="none")
    hist.column("ok", width=34, anchor="center", stretch=False)
    hist.column("prod", width=560)
    hist.column("quand", width=120, anchor="e", stretch=False)
    hist.tag_configure("err", foreground=RED)
    hist.tag_configure("ok", foreground=FG)
    hist.pack(fill="both", expand=True)

    fdir_var = tk.StringVar()

    # ================= Mes projets FL
    prods = page("prods", "Mes projets FL", "Chaque prod reçue arrive dans son propre dossier de projet, avec son projet FL. "
                                            "Double-clic pour ouvrir dans FL.")
    fold = tk.Frame(prods, bg=BG)
    fold.pack(fill="x", pady=(0, 10))
    fold_lbl = label(fold, "", 9, FAINT, mono=True)
    fold_lbl.pack(side="left")

    def change_proj_dir():
        """Le seul dossier : chaque prod reçue y arrive dans son dossier de projet."""
        p = filedialog.askdirectory(title="Ton dossier des projets", initialdir=FM.settings()["dossier"], parent=root)
        if not p:
            return
        Path(p).mkdir(parents=True, exist_ok=True)
        cfg = C.load_config()
        fm = FM.settings(cfg)
        fm["dossier"] = cfg["dossier"] = str(Path(p))
        cfg["flmake"] = fm
        C.save_config(cfg)
        fdir_var.set(str(Path(p)))
        load_prods(force=True)
        toast("Dossier des projets changé : les prochaines prods arriveront là, chacune dans son dossier.")
    Btn(fold, "Changer…", change_proj_dir, kind="subtle", padx=8, pady=0).pack(side="left", padx=(8, 0))
    Btn(fold, "Ouvrir", lambda: _open_path(FM.settings()["dossier"]), kind="subtle", padx=0, pady=0).pack(side="left")

    bar = tk.Frame(prods, bg=BG)
    bar.pack(fill="x", pady=(0, 12))
    q_var = tk.StringVar()
    q = entry(bar, q_var, width=32)
    q.pack(side="left", ipady=6)
    q_hint = label(q, "", 10, FAINT)
    filt = {"v": "all"}
    seg = tk.Frame(bar, bg=PANEL2, padx=3, pady=3)
    seg.pack(side="left", padx=12)
    seg_btns = {}
    for k, txt in (("all", "Tous"), ("fav", "★ Favoris")):
        b = tk.Label(seg, text=txt, bg=PANEL2, fg=MUTED, font=(FONT, 9, "bold"), padx=12, pady=5, cursor="hand2")
        b.pack(side="left")
        b.bind("<Button-1>", lambda e, k=k: (filt.update(v=k), paint_seg(), fill_prods()))
        seg_btns[k] = b

    def paint_seg():
        for k, b in seg_btns.items():
            b.configure(bg=PANEL3 if filt["v"] == k else PANEL2, fg=FG if filt["v"] == k else MUTED)
    paint_seg()
    count_lbl = label(bar, "", 9, FAINT)
    count_lbl.pack(side="right")

    gridwrap = tk.Frame(prods, bg=BG)
    gridwrap.pack(fill="both", expand=True)
    gbody = scroll_area(gridwrap)
    grid = tk.Frame(gbody, bg=BG)
    grid.pack(fill="both", expand=True)
    empty_lbl = label(gridwrap, "", 10, MUTED, wrap=600)

    acts = tk.Frame(prods, bg=BG)
    acts.pack(fill="x", pady=(12, 0))
    sel_lbl = label(acts, "Choisis un projet.", 10, MUTED)
    sel_lbl.pack(side="left")
    a_open = Btn(acts, "Ouvrir dans FL", kind="primary")
    a_ren = Btn(acts, "Renommer…")
    a_style = Btn(acts, "Icône et couleur…")
    a_dir = Btn(acts, "Dossier")
    a_play = Btn(acts, "♪ Sons")
    for b in (a_play, a_dir, a_style, a_ren, a_open):
        b.pack(side="right", padx=(8, 0))

    lib = {"items": [], "by_id": {}, "sig": None, "shown": []}
    sel = {"id": None}
    cards = {}
    lay = {"cols": 0}
    CARD_W = 218

    def selected():
        return lib["by_id"].get(sel["id"])

    def ncols():
        w = gbody.winfo_width() or grid.winfo_width() or 760
        return max(1, (w - 8) // (CARD_W + 14))

    def icon_tile(parent, color, icon, size=42, bg=PANEL):
        cv = tk.Canvas(parent, width=size, height=size, bg=bg, highlightthickness=0)
        r = size // 4
        tint = blend(color, bg, 0.24)
        cv.create_rectangle(r, 0, size - r, size, fill=tint, outline="")
        cv.create_rectangle(0, r, size, size - r, fill=tint, outline="")
        for x, y in ((0, 0), (size - 2 * r, 0), (0, size - 2 * r), (size - 2 * r, size - 2 * r)):
            cv.create_oval(x, y, x + 2 * r, y + 2 * r, fill=tint, outline="")
        cv.create_text(size / 2, size / 2 + 1, text=icon, fill=color, font=(SYMB, int(size * 0.42)))
        return cv

    # --- Glisser-déposer, comme les icônes du bureau de Windows : la carte suit la souris
    # et les autres se poussent pour lui faire de la place ; on lâche, c'est rangé.
    drag = {"src": None, "x": 0, "y": 0, "on": False, "ghost": None, "order": None}
    gcanvas = gbody.master

    def card_at(x, y):
        w = root.winfo_containing(x, y)
        while w is not None:
            cid = getattr(w, "_mf_card", None)
            if cid:
                return cid
            w = getattr(w, "master", None)
        return None

    def drag_start(e, it):
        drag.update(src=it.id, x=e.x_root, y=e.y_root, on=False, order=None)

    def make_ghost(it):
        g = tk.Toplevel(root)
        g.overrideredirect(True)
        try:
            g.attributes("-alpha", 0.88)
            g.attributes("-topmost", True)
        except tk.TclError:
            pass
        color = it.extra.get("color", ACCENT2)
        f = tk.Frame(g, bg=PANEL, highlightthickness=2, highlightbackground=color, padx=10, pady=8)
        f.pack()
        icon_tile(f, color, it.extra.get("icon", "♪"), 34, PANEL).pack(side="left")
        tk.Label(f, text=it.title[:30], bg=PANEL, fg=FG, font=(FONT, 10, "bold")).pack(side="left", padx=(10, 4))
        return g

    def drag_move(e):
        src = drag["src"]
        if not src or src not in cards:
            return
        if not drag["on"]:
            if abs(e.x_root - drag["x"]) + abs(e.y_root - drag["y"]) < 10:
                return
            drag.update(on=True, order=list(lib["shown"]), ghost=make_ghost(lib["by_id"][src]))
            root.configure(cursor="fleur")
            frame_card(src, state="drag")
        drag["ghost"].geometry(f"+{e.x_root + 16}+{e.y_root + 12}")
        top, bottom = gcanvas.winfo_rooty(), gcanvas.winfo_rooty() + gcanvas.winfo_height()
        if e.y_root < top + 40:
            gcanvas.yview_scroll(-1, "units")
        elif e.y_root > bottom - 40:
            gcanvas.yview_scroll(1, "units")
        tgt = card_at(e.x_root, e.y_root)
        if not tgt or tgt == src or tgt not in cards:
            return
        c = cards[tgt]
        after = e.x_root > c.winfo_rootx() + c.winfo_width() / 2  # moitié droite : après
        order = [x for x in drag["order"] if x != src]
        order.insert(order.index(tgt) + (1 if after else 0), src)
        if order != drag["order"]:
            drag["order"] = order
            lib["shown"] = order
            for idx, cid in enumerate(order):
                place(cid, idx)

    def drag_end(e):
        src, was, order, ghost = drag["src"], drag["on"], drag["order"], drag["ghost"]
        drag.update(src=None, on=False, order=None, ghost=None)
        if not was:
            return
        if ghost:
            ghost.destroy()
        root.configure(cursor="")
        frame_card(src)
        if order:
            L.reorder(order)
            load_prods(force=True)
            toast("Projet rangé · ton ordre est gardé")

    def frame_card(cid, state=None):
        c = cards.get(cid)
        it = lib["by_id"].get(cid)
        if not c or not it or not c.winfo_exists():
            return
        color = it.extra.get("color", ACCENT2)
        if state == "drag":  # sa place pendant le déplacement : un cadre en pointillés
            c.configure(highlightthickness=3, highlightbackground=ACCENT)
        else:
            on = sel["id"] == cid
            c.configure(highlightthickness=3 if on else 2, highlightbackground=color if on else blend(color, PANEL, 0.55))

    def bind_all_children(w, it):
        w.bind("<ButtonPress-1>", lambda e, i=it: (drag_start(e, i), select(i.id)), add="+")
        w.bind("<B1-Motion>", drag_move, add="+")
        w.bind("<ButtonRelease-1>", drag_end, add="+")
        w.bind("<Double-1>", lambda e, i=it: do_open(i))
        w.bind("<Button-3>", lambda e, i=it: (select(i.id), menu.tk_popup(e.x_root, e.y_root)))
        for ch in w.winfo_children():
            bind_all_children(ch, it)

    def open_video(it):
        it = it or selected()
        vid = it.extra.get("yt") if it else None
        if vid:
            webbrowser.open(f"https://www.youtube.com/watch?v={vid}")
        elif it:
            toast("Pas de vidéo YouTube : ce projet ne vient pas d'une prod envoyée depuis l'app")

    # --- Lecteur de chaque carte : le son principal (dernière version, sinon l'instru, sinon
    # ton dernier export), barre de lecture, et ▾ pour les autres versions.
    choice = {}          # projet → son choisi dans son lecteur
    opened = set()       # projets dont la liste des versions est ouverte
    pw = {}              # projet → widgets de son lecteur

    def refresh_players():
        for cid, w in list(pw.items()):
            if not w["btn"].winfo_exists():
                pw.pop(cid, None)
                continue
            on = PLAYER.is_(w["path"])
            playing = on and PLAYER.mode() == "playing"
            w["btn"].configure(text="❚❚" if playing else "▶")
            if not on:
                w["bar"].delete("all")
                w["tm"].configure(text=w["dur"])

    def tick_player():
        try:
            if PLAYER.path:
                pos, length, mode = PLAYER.position(), PLAYER.length, PLAYER.mode()
                if mode == "stopped" and length and pos >= length - 250:
                    PLAYER.stop()
                    refresh_players()
                for w in pw.values():
                    if PLAYER.is_(w["path"]) and w["bar"].winfo_exists():
                        bw = w["bar"].winfo_width()
                        w["bar"].delete("all")
                        if length:
                            w["bar"].create_rectangle(0, 0, bw * pos / length, 6, fill=w["color"], width=0)
                        w["tm"].configure(text=f"{_mmss(pos / 1000)} / {_mmss(length / 1000)}")
        finally:
            root.after(250, tick_player)

    def rebuild_card(cid):
        it = lib["by_id"].get(cid)
        if not it or cid not in cards:
            return
        cards[cid].destroy()
        cards[cid] = make_card(it)
        if cid in lib["shown"]:
            place(cid, lib["shown"].index(cid))

    def player_box(parent, it, files, color):
        mine = [f for f in files if f["kind"] != "fl"]
        if not mine:
            return None
        cur = next((f for f in mine if f["id"] == choice.get(it.id)), None) or next((f for f in mine if f.get("main")), mine[0])
        box = tk.Frame(parent, bg=PANEL2, highlightthickness=1, highlightbackground=blend(color, PANEL2, 0.45), padx=8, pady=7)
        row = tk.Frame(box, bg=PANEL2)
        row.pack(fill="x")
        btn = tk.Label(row, text="▶", bg=color, fg=BG, font=(SYMB, 9, "bold"), width=3, cursor="hand2")
        btn.pack(side="left")
        tag = "INSTRU" if cur["instru"] else cur["label"].upper() if cur["label"] else "MIX"
        tk.Label(row, text=tag, bg=PANEL2, fg=GREEN if cur["instru"] else ACCENT if cur["label"] else MUTED,
                 font=(MONO, 7, "bold")).pack(side="left", padx=(7, 4))
        name = L.parse_name(cur["name"])[0] or cur["name"]
        tk.Label(row, text=name if len(name) <= 16 else name[:15] + "…", bg=PANEL2, fg=FG, font=(FONT, 9), anchor="w").pack(side="left", fill="x", expand=True)
        others = [f for f in mine if f["id"] != cur["id"]]
        nfl = sum(1 for f in files if f["kind"] == "fl")
        arrow = None
        if others or nfl:
            arrow = tk.Label(row, text="▴" if it.id in opened else "▾", bg=PANEL2, fg=MUTED, font=(SYMB, 11), cursor="hand2")
            arrow.pack(side="right")
        bar = tk.Canvas(box, height=6, bg=PANEL3, highlightthickness=0, cursor="hand2")
        bar.pack(fill="x", pady=(7, 1))
        dur = L._duration(cur["path"])
        tm = tk.Label(box, text=_mmss(dur) if dur else "", bg=PANEL2, fg=FAINT, font=(MONO, 7))
        tm.pack(anchor="e")
        picks = []
        if it.id in opened:
            lst = tk.Frame(box, bg=PANEL2)
            lst.pack(fill="x", pady=(4, 0))
            for f in others[:14]:
                r = tk.Frame(lst, bg=PANEL2, cursor="hand2")
                r.pack(fill="x", pady=1)
                t = "INSTRU" if f["instru"] else f["label"].upper() if f["label"] else "MIX"
                a1 = tk.Label(r, text="▶", bg=PANEL2, fg=MUTED, font=(SYMB, 8))
                a1.pack(side="left")
                a2 = tk.Label(r, text=t, bg=PANEL2, fg=ACCENT if f["label"] else MUTED, font=(MONO, 7, "bold"))
                a2.pack(side="left", padx=(4, 4))
                nm = L.parse_name(f["name"])[0] or f["name"]
                a3 = tk.Label(r, text=nm if len(nm) <= 18 else nm[:17] + "…", bg=PANEL2, fg=FG, font=(FONT, 8), anchor="w")
                a3.pack(side="left", fill="x", expand=True)
                picks += [(w_, f) for w_ in (r, a1, a2, a3)]
            if nfl:
                more = tk.Label(lst, text=f"+ {nfl} son{'s' if nfl > 1 else ''} créé{'s' if nfl > 1 else ''} par FL", bg=PANEL2, fg=FAINT,
                                font=(FONT, 8), cursor="hand2", anchor="w")
                more.pack(fill="x", pady=(3, 0))
                picks.append((more, None))
        pw[it.id] = {"btn": btn, "bar": bar, "tm": tm, "path": str(cur["path"]), "color": color, "dur": _mmss(dur) if dur else ""}

        def toggle(_e=None, path=str(cur["path"])):
            if PLAYER.is_(path):
                PLAYER.toggle()
            else:
                PLAYER.play(path)
            refresh_players()
            return "break"

        def seek(e, path=str(cur["path"])):
            if not PLAYER.is_(path):
                PLAYER.play(path)
            PLAYER.seek(e.x / max(1, e.widget.winfo_width()))
            refresh_players()
            return "break"

        def flip(_e=None):
            opened.symmetric_difference_update({it.id})
            rebuild_card(it.id)
            return "break"

        def pick(_e=None, f=None):
            if f is None:
                do_play(it)
                return "break"
            choice[it.id] = f["id"]
            opened.discard(it.id)
            PLAYER.play(f["path"])
            rebuild_card(it.id)
            refresh_players()
            return "break"
        handlers = [(btn, toggle), (bar, seek)] + ([(arrow, flip)] if arrow else []) + [(w_, lambda e, f=f: pick(e, f)) for w_, f in picks]
        return box, handlers

    def make_card(it):
        color, icon = it.extra.get("color", ACCENT2), it.extra.get("icon", "♪")
        on = sel["id"] == it.id
        bgc = PANEL
        c = tk.Frame(grid, bg=bgc, highlightthickness=3 if on else 2, highlightbackground=color if on else blend(color, PANEL, 0.55),
                     cursor="hand2", width=CARD_W)
        c._mf_card = it.id
        tk.Frame(c, bg=color, height=5).pack(fill="x")
        inner = tk.Frame(c, bg=bgc, padx=14, pady=12)
        inner.pack(fill="both", expand=True)
        top = tk.Frame(inner, bg=bgc)
        top.pack(fill="x")
        tile = icon_tile(top, color, icon, 44, bgc)
        tile.pack(side="left")
        star = tk.Label(top, text="★" if it.fav else "☆", bg=bgc, fg=AMBER if it.fav else FAINT, font=(SYMB, 14), cursor="hand2")
        star.pack(side="right", anchor="n")
        tk.Label(inner, text=it.title if len(it.title) <= 64 else it.title[:62] + "…", bg=bgc, fg=FG, font=(FONT, 11, "bold"),
                 wraplength=CARD_W - 34, justify="left", anchor="w").pack(fill="x", pady=(10, 6))
        chips = tk.Frame(inner, bg=bgc)
        chips.pack(fill="x")
        tb = it.extra.get("tb") or ()
        for txt, col in ((it.key, TB_BLUE if "key" in tb else FG), (f"{it.bpm} BPM" if it.bpm else "", TB_BLUE if "bpm" in tb else FG),
                         (it.lic, LIC_COLORS.get(it.lic.split(",")[0], AMBER) if it.lic else FG)):
            if txt:
                tk.Label(chips, text=txt, bg=PANEL3 if not on else blend(color, PANEL3, 0.18), fg=col, font=(MONO, 8, "bold"),
                         padx=7, pady=2).pack(side="left", padx=(0, 6))
        dur = it.extra.get("dur")
        if dur:
            tk.Label(chips, text=f"{int(dur) // 60}:{int(dur) % 60:02d}", bg=PANEL3, fg=MUTED, font=(MONO, 8, "bold"),
                     padx=7, pady=2).pack(side="left", padx=(0, 6))
        if not (it.key or it.bpm or it.lic or dur):
            tk.Label(chips, text="—", bg=bgc, fg=FAINT, font=(MONO, 8)).pack(side="left")

        foot = tk.Frame(inner, bg=bgc)
        foot.pack(fill="x", pady=(6, 0))
        tk.Label(foot, text="Projet FL" if it.flp else "Prod seule", bg=bgc, fg=GREEN if it.flp else AMBER, font=(FONT, 8, "bold")).pack(side="left")
        tk.Label(foot, text=_ago(it.date), bg=bgc, fg=FAINT, font=(FONT, 8)).pack(side="right")
        yt = None
        if it.extra.get("yt"):
            yt = tk.Label(inner, text="▶ Voir la vidéo YouTube", bg=bgc, fg="#ff5a52", font=(FONT, 9, "bold"), cursor="hand2", anchor="w")
            yt.pack(fill="x", pady=(6, 0))
        pb = player_box(inner, it, L.audio_files(it), color)
        if pb:
            pb[0].pack(fill="x", pady=(10, 0), before=foot)
        else:
            tk.Label(inner, text="Aucun son à écouter", bg=bgc, fg=FAINT, font=(FONT, 9), anchor="w").pack(fill="x", pady=(10, 0), before=foot)
        bind_all_children(c, it)
        if pb:  # le lecteur garde ses clics pour lui (ni sélection, ni déplacement, ni ouverture)
            def quiet(w):
                w.bind("<Button-1>", lambda e: "break")
                w.unbind("<Double-1>")
                w.unbind("<B1-Motion>")
                for ch in w.winfo_children():
                    quiet(ch)
            quiet(pb[0])
            for w_, fn in pb[1]:
                w_.bind("<Button-1>", fn)
        star.bind("<Button-1>", lambda e, i=it: (do_fav(i), "break")[1])
        tile.configure(cursor="hand2")
        tile.bind("<Button-1>", lambda e, i=it: (select(i.id), do_style(i), "break")[2])
        if yt:
            yt.bind("<Button-1>", lambda e, i=it: (open_video(i), "break")[1])
        return c

    def place(cid, idx):
        cols = lay["cols"]
        cards[cid].grid(row=idx // cols, column=idx % cols, padx=6, pady=6, sticky="nsew")

    def relayout(force=False):
        cols = ncols()
        if cols == lay["cols"] and not force:
            return
        lay["cols"] = cols
        for i in range(12):
            grid.columnconfigure(i, weight=1 if i < cols else 0, uniform="c" if i < cols else "")
        for idx, cid in enumerate(lib["shown"]):
            place(cid, idx)
    gbody.bind("<Configure>", lambda e: relayout(), add="+")

    def select(cid):
        """Sélection sans recréer la carte (le double-clic pour ouvrir dans FL marche à coup sûr)."""
        old = sel["id"]
        sel["id"] = cid
        for x in {old, cid}:
            if x:
                frame_card(x)
        update_actions()

    def fill_prods():
        text = q_var.get().strip().lower()
        items = lib["items"]
        shown = [i for i in items if (not text or text in i.name.lower() or text in i.extra.get("instru", "").lower())
                 and (filt["v"] == "all" or i.fav)]
        for c in cards.values():
            c.destroy()
        cards.clear()
        lib["shown"] = [i.id for i in shown]
        if sel["id"] not in lib["by_id"]:
            sel["id"] = None
        for i in shown:
            cards[i.id] = make_card(i)
        relayout(force=True)
        n_fav = sum(1 for i in items if i.fav)
        count_lbl.configure(text=f"{len(shown)} / {len(items)} projet{'s' if len(items) > 1 else ''} · {n_fav} favori{'s' if n_fav > 1 else ''}")
        if not items:
            empty_lbl.configure(text="Aucun projet pour l'instant. Chaque prod envoyée depuis ton téléphone arrivera ici, dans son dossier de projet.")
            empty_lbl.place(relx=0.5, rely=0.4, anchor="center")
        elif not shown:
            empty_lbl.configure(text="Aucun projet ne correspond.")
            empty_lbl.place(relx=0.5, rely=0.4, anchor="center")
        else:
            empty_lbl.place_forget()
        update_actions()
        nav_items["prods"][4].configure(text=str(len(items)) if items else "")

    def load_prods(force=False):
        fold_lbl.configure(text=f"Dossier : {FM.settings()['dossier']}")
        try:
            items = L.scan_projects()
        except OSError:
            items = []
        sig = [(i.id, i.name, i.fav, int(i.date), i.extra.get("instru"), i.extra.get("color"), i.extra.get("icon"), bool(i.flp)) for i in items]
        if force or sig != lib["sig"]:
            lib.update(items=items, by_id={i.id: i for i in items}, sig=sig)
            fill_prods()

    def update_actions():
        it = selected()
        for b in (a_open, a_ren, a_style, a_dir, a_play):
            b.set(enabled=bool(it))
        if not it:
            sel_lbl.configure(text="Double-clic : ouvrir dans FL · clic sur l'icône : icône et couleur · glisser : changer l'ordre")
            return
        a_open.set(text="Ouvrir dans FL" if it.flp else ("Créer le projet FL" if FM.settings()["template"] else "Ouvrir la prod"))
        ip = it.extra.get("instru_path")
        a_play.set(enabled=bool((ip and Path(ip).is_file()) or it.folder))
        files = it.extra.get("files")
        sel_lbl.configure(text=f"{it.title[:44]}" + (f"  ·  {files} fichier{'s' if files > 1 else ''}" if files else ""))

    def do_open(it=None):
        it = it or selected()
        if not it:
            return
        try:
            toast(L.open_item(it), 7000)
        except (OSError, FM.FlpError, L.LibError) as e:
            toast(f"Impossible d'ouvrir : {e}")
        load_prods(force=True)

    def do_fav(it=None):
        it = it or selected()
        if it:
            L.toggle_fav(it)
            load_prods(force=True)

    def do_dir():
        it = selected()
        if it:
            _open_path(it.folder or it.flp.parent)

    playing = {"path": None, "after": None}

    def stop_sound():
        playing["path"] = None
        PLAYER.stop()
        refresh_players()

    def play_sound(path):
        """Joue le son ici (lecteur de Windows : .wav, .mp3…)."""
        ok = PLAYER.play(path)
        playing["path"] = PLAYER.path
        refresh_players()
        return ok

    def do_play(it=None):
        """Sons du projet : l'instru, les versions (0.1, 1.3.3…) dans l'ordre, les autres sons."""
        it = it or selected()
        if not it:
            return
        files = L.audio_files(it)
        dlg, f = dialog("Sons du projet")
        head = tk.Frame(f, bg=PANEL)
        head.pack(fill="x")
        icon_tile(head, it.extra.get("color", L.PALETTE[0]), it.extra.get("icon", L.ICONS[0]), 44).pack(side="left")
        hx = tk.Frame(head, bg=PANEL)
        hx.pack(side="left", padx=12)
        label(hx, it.title[:60], 13, bold=True, wrap=420).pack(anchor="w")
        files = [x for x in files if x["kind"] != "fl"] + [x for x in files if x["kind"] == "fl"]
        nv = sum(1 for x in files if x["ver"])
        label(hx, f"{len(files)} son{'s' if len(files) > 1 else ''}" + (f" · {nv} version{'s' if nv > 1 else ''}, de la plus ancienne à la plus récente" if nv else ""),
              9, MUTED).pack(anchor="w")
        box = tk.Frame(f, bg=PANEL)
        box.pack(fill="both", pady=(14, 0))
        rows = {}

        def paint():
            for pth, (btn, row) in rows.items():
                on = playing["path"] == pth
                btn.configure(text="■" if on else "▶", fg=BG if on else FG, bg=ACCENT if on else PANEL3)
                row.configure(highlightbackground=ACCENT2 if on else LINE)

        def toggle(pth):
            if playing["path"] == pth:
                stop_sound()
            else:
                play_sound(pth)
            paint()
        if not files:
            label(box, "Aucun son dans ce projet.", 10, MUTED).pack(anchor="w")
        fl_head = False
        for x in files:
            if x["kind"] == "fl" and not fl_head:
                fl_head = True
                label(box, "CRÉÉS PAR FL · enregistrements, rendus, samples", 8, FAINT, bold=True).pack(anchor="w", pady=(10, 2))
            pth = str(x["path"])
            row = tk.Frame(box, bg=PANEL2, highlightthickness=1, highlightbackground=LINE, padx=10, pady=7)
            row.pack(fill="x", pady=3)
            btn = tk.Label(row, text="▶", bg=PANEL3, fg=FG, font=(SYMB, 11), width=3, cursor="hand2")
            btn.pack(side="left")
            btn.bind("<Button-1>", lambda e, p=pth: toggle(p))
            tag = "INSTRU" if x["instru"] else x["label"].upper() if x["ver"] else x["ext"].upper()
            tcol = GREEN if x["instru"] else ACCENT if x["ver"] else FAINT
            tk.Label(row, text=tag, bg=PANEL2, fg=tcol, font=(MONO, 8, "bold"), width=9).pack(side="left", padx=(10, 6))
            label(row, x["name"][:70], 10, FG).pack(side="left")
            if x.get("latest"):
                tk.Label(row, text="DERNIÈRE", bg=blend(ACCENT, PANEL2, 0.25), fg=ACCENT, font=(MONO, 7, "bold"), padx=5).pack(side="left", padx=8)
            o = tk.Label(row, text="Ouvrir", bg=PANEL2, fg=MUTED, font=(FONT, 9), cursor="hand2")
            o.pack(side="right")
            o.bind("<Button-1>", lambda e, p=pth: (stop_sound(), paint(), _open_path(p)))
            rows[pth] = (btn, row)
        foot = tk.Frame(f, bg=PANEL)
        foot.pack(fill="x", pady=(14, 0))
        label(foot, "▶ joue le son ici (.wav, .mp3…), ■ l'arrête.", 8, FAINT).pack(side="left")

        def close():
            stop_sound()
            dlg.destroy()
        Btn(foot, "Fermer", close).pack(side="right")
        dlg.protocol("WM_DELETE_WINDOW", close)
        dlg.bind("<Escape>", lambda _e: close())
        dlg.update_idletasks()
        dlg.geometry(f"+{root.winfo_rootx() + 200}+{root.winfo_rooty() + 90}")

    def dialog(title):
        dlg = tk.Toplevel(root, bg=PANEL)
        dlg.title(title)
        dlg.transient(root)
        dlg.resizable(False, False)
        f = tk.Frame(dlg, bg=PANEL, padx=24, pady=20)
        f.pack(fill="both", expand=True)
        return dlg, f

    def show_dialog(dlg):
        dlg.update_idletasks()
        dlg.geometry(f"+{root.winfo_rootx() + 240}+{root.winfo_rooty() + 110}")
        dlg.grab_set()

    def do_style(it=None):
        it = it or selected()
        if not it:
            return
        dlg, f = dialog("Icône et couleur")
        st = {"color": it.extra.get("color", L.PALETTE[0]), "icon": it.extra.get("icon", L.ICONS[0])}
        head = tk.Frame(f, bg=PANEL)
        head.pack(fill="x")
        prev = tk.Frame(head, bg=PANEL)
        prev.pack(side="left")
        label(head, it.title[:50], 13, bold=True, wrap=360).pack(side="left", padx=14)
        label(f, "COULEUR", 8, FAINT, bold=True).pack(anchor="w", pady=(18, 6))
        sw = tk.Frame(f, bg=PANEL)
        sw.pack(anchor="w")
        label(f, "ICÔNE", 8, FAINT, bold=True).pack(anchor="w", pady=(16, 6))
        ig = tk.Frame(f, bg=PANEL)
        ig.pack(anchor="w")
        swatches, icons = {}, {}

        def redraw():
            for w in prev.winfo_children():
                w.destroy()
            icon_tile(prev, st["color"], st["icon"], 58).pack()
            for c, cv in swatches.items():
                cv.delete("all")
                if c == st["color"]:
                    cv.create_oval(1, 1, 29, 29, outline=FG, width=2)
                cv.create_oval(5, 5, 25, 25, fill=c, outline="")
            for ic, lb in icons.items():
                lb.configure(bg=blend(st["color"], PANEL, 0.28) if ic == st["icon"] else PANEL2,
                             fg=st["color"] if ic == st["icon"] else MUTED)

        for c in L.PALETTE:
            cv = tk.Canvas(sw, width=30, height=30, bg=PANEL, highlightthickness=0, cursor="hand2")
            cv.pack(side="left", padx=2)
            cv.bind("<Button-1>", lambda e, c=c: (st.update(color=c), redraw()))
            swatches[c] = cv
        for n, ic in enumerate(L.ICONS):
            lb = tk.Label(ig, text=ic, font=(SYMB, 15), width=2, bg=PANEL2, fg=MUTED, cursor="hand2", pady=4)
            lb.grid(row=n // 10, column=n % 10, padx=2, pady=2)
            lb.bind("<Button-1>", lambda e, ic=ic: (st.update(icon=ic), redraw()))
            icons[ic] = lb
        redraw()
        row = tk.Frame(f, bg=PANEL)
        row.pack(fill="x", pady=(20, 0))

        def save():
            L.set_style(it, st["color"], st["icon"])
            dlg.destroy()
            load_prods(force=True)

        def reset():
            L.set_style(it, None, None)
            dlg.destroy()
            load_prods(force=True)
        Btn(row, "Enregistrer", save, kind="primary").pack(side="right")
        Btn(row, "Annuler", dlg.destroy).pack(side="right", padx=8)
        Btn(row, "Par défaut", reset, kind="subtle", padx=0).pack(side="left")
        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        dlg.bind("<Return>", lambda _e: save())
        show_dialog(dlg)

    def do_rename():
        it = selected()
        if not it:
            return
        dlg, f = dialog("Renommer le projet")
        label(f, "Renommer le projet", 14, bold=True).pack(anchor="w")
        label(f, "Le dossier du projet et tous les fichiers qui portent son nom (prod, projet, sauvegardes, exports) prennent le "
                 "nouveau nom ; les chemins enregistrés dans les projets FL suivent. La clé et le BPM restent.", 9, MUTED, wrap=460).pack(anchor="w", pady=(4, 14))
        v = tk.StringVar(value=it.title)
        e = entry(f, v, width=56)
        e.pack(fill="x", ipady=7)
        preview = label(f, "", 9, ACCENT, mono=True, wrap=460)
        preview.pack(anchor="w", pady=(10, 0))
        what = label(f, "", 9, MUTED, wrap=460)
        what.pack(anchor="w", pady=(4, 0))
        err = label(f, "", 9, RED, wrap=460)
        err.pack(anchor="w", pady=(6, 0))

        def upd(*_):
            try:
                plan = L.rename_plan(it, v.get())
            except L.LibError as ex:
                preview.configure(text="")
                what.configure(text=str(ex))
                return
            preview.configure(text=plan["new"])
            n = len(plan["files"])
            what.configure(text=f"Renommé : le dossier et {n} fichier{'s' if n > 1 else ''}" if plan["folder"] else "Renommé : le projet")
        v.trace_add("write", upd)
        upd()
        row = tk.Frame(f, bg=PANEL)
        row.pack(fill="x", pady=(16, 0))

        def ok():
            try:
                new = L.rename(it, v.get())
            except L.LibError as ex:
                err.configure(text=str(ex))
                return
            dlg.destroy()
            toast(f"Projet renommé : {new}")
            sel["id"] = f"p:{new.lower()}"
            load_prods(force=True)
        Btn(row, "Renommer", ok, kind="primary").pack(side="right")
        Btn(row, "Annuler", dlg.destroy).pack(side="right", padx=8)
        e.focus_set()
        e.select_range(0, "end")
        e.bind("<Return>", lambda _e: ok())
        e.bind("<Escape>", lambda _e: dlg.destroy())
        show_dialog(dlg)

    a_open.command, a_ren.command, a_style.command, a_dir.command, a_play.command = do_open, do_rename, do_style, do_dir, do_play
    menu = tk.Menu(root, tearoff=0, bg=PANEL2, fg=FG, activebackground=ACCENT2, activeforeground="#ffffff", bd=0, font=(FONT, 10))
    menu.add_command(label="Ouvrir dans FL", command=do_open)
    menu.add_command(label="Renommer…", command=do_rename)
    menu.add_command(label="Icône et couleur…", command=do_style)
    menu.add_command(label="Favori ★", command=do_fav)
    menu.add_separator()
    menu.add_command(label="Écouter les sons (instru, versions)…", command=do_play)
    menu.add_command(label="Ouvrir le dossier", command=do_dir)
    menu.add_command(label="Voir la vidéo YouTube", command=lambda: open_video(None))
    q_var.trace_add("write", lambda *_: fill_prods())

    def q_placeholder(*_):
        if q_var.get() or root.focus_get() == q:
            q_hint.place_forget()
        else:
            q_hint.configure(text="Rechercher un projet…", bg=PANEL2)
            q_hint.place(x=8, rely=0.5, anchor="w")
    q.bind("<FocusIn>", q_placeholder)
    q.bind("<FocusOut>", q_placeholder)
    q_hint.bind("<Button-1>", lambda e: q.focus_set())
    q_var.trace_add("write", q_placeholder)
    root.after(50, q_placeholder)
    on_show["prods"] = lambda: load_prods(force=True)

    # ================= FLmake
    flm = page("flmake", "FLmake", "Un projet FL Studio prêt pour chaque prod reçue : ton preset de voix, le BPM, l'instru sur la piste INSTRU, "
                                  "Graillon sur la clé de la prod.", scroll=True)
    fm0 = FM.settings()

    def fm_save(**kw):
        cfg = C.load_config()
        fm = FM.settings(cfg)
        fm.update(kw)
        cfg["flmake"] = fm
        C.save_config(cfg)
        return fm

    def setting_row(parent, title, sub, widget_factory):
        r = tk.Frame(parent, bg=PANEL)
        r.pack(fill="x", pady=6)
        t = tk.Frame(r, bg=PANEL)
        t.pack(side="left", fill="x", expand=True)
        label(t, title, 10, bold=True).pack(anchor="w")
        if sub:
            label(t, sub, 9, MUTED, wrap=560).pack(anchor="w")
        w = widget_factory(r)
        w.pack(side="right", padx=(12, 0))
        return w

    c = card(flm)
    c.pack(fill="x", pady=(0, 14))
    sw_on = setting_row(c, "Activer FLmake", "Pour chaque prod reçue, un projet FL au nom de la prod, dans son dossier.",
                        lambda p: Switch(p, fm0["on"], lambda v: (fm_save(on=v), toast("FLmake activé" if v else "FLmake désactivé"))))
    tk.Frame(c, bg=LINE, height=1).pack(fill="x", pady=6)
    sw_open = setting_row(c, "Ouvrir FL Studio tout seul", "Quand la prod arrive (une seule fois si plusieurs arrivent d'un coup).",
                          lambda p: Switch(p, fm0.get("open", True), lambda v: fm_save(open=v)))

    def path_card(parent, title, sub, var, buttons):
        cc = card(parent)
        cc.pack(fill="x", pady=(0, 14))
        label(cc, title, 11, bold=True).pack(anchor="w")
        if sub:
            label(cc, sub, 9, MUTED, wrap=680).pack(anchor="w", pady=(2, 0))
        r = tk.Frame(cc, bg=PANEL)
        r.pack(fill="x", pady=(10, 0))
        entry(r, var, readonly=True).pack(side="left", fill="x", expand=True, ipady=6)
        for txt, cmd, kind in buttons:
            Btn(r, txt, cmd, kind=kind).pack(side="left", padx=(8, 0))
        return cc

    tpl_var = tk.StringVar(value=fm0["template"] or "Pas encore choisi")

    def pick_tpl():
        p = filedialog.askopenfilename(title="Ton projet modèle FL (preset de voix)", filetypes=[("Projet FL Studio", "*.flp")], parent=root)
        if p:
            fm_save(template=str(Path(p)))
            tpl_var.set(str(Path(p)))
            check_tpl()

    def help_tpl():
        messagebox.showinfo("Créer ton modèle FL", (
            "À faire une seule fois :\n\n"
            "1. Dans FL Studio : Fichier → Nouveau.\n"
            "2. Mixer, insert 2 : charge ton preset de voix (glisse ton fichier .fst sur l'insert 2), avec Graillon dedans. "
            "En haut à droite du mixer, choisis ton micro comme entrée de l'insert 2.\n"
            "3. Playlist : nomme la piste du haut « INSTRU » et relie-la à l'insert 1 ; la piste « VOICE » à l'insert 2. "
            "FLmake pose l'instru tout seul au début de la piste INSTRU.\n"
            "4. Fichier → Enregistrer sous… (ex. « MODEL FL.flp »), puis choisis ce fichier ici."), parent=root)
    tc = path_card(flm, "Ton preset de voix (projet modèle FL)", "", tpl_var,
                   (("Choisir…", pick_tpl, "primary"), ("Comment le créer ?", help_tpl, "ghost")))
    tpl_state = label(tc, "", 9, MUTED, wrap=680)
    tpl_state.pack(anchor="w", pady=(8, 0))

    def check_tpl():
        p = FM.settings()["template"]
        if not p:
            tpl_state.configure(text="Choisis ton projet modèle (preset de voix) pour activer FLmake.", fg=AMBER)
            return
        t = FM.inspect_template(p)
        tpl_state.configure(text=t["msg"], fg=GREEN if t["ok"] else RED)
    check_tpl()

    fdir_var.set(fm0["dossier"])

    path_card(flm, "Dossier des projets", "Chaque prod arrive dans son dossier, au nom de la prod : la prod (.wav) et son projet FL.", fdir_var,
              (("Changer…", change_proj_dir, "ghost"),
               ("Ouvrir", lambda: (Path(fdir_var.get()).mkdir(parents=True, exist_ok=True), _open_path(fdir_var.get())), "ghost")))

    flexe_var = tk.StringVar(value=FM.fl_exe(fm0) or "FL Studio introuvable : choisis FL64.exe")

    def pick_fl():
        p = filedialog.askopenfilename(title="FL Studio (FL64.exe)", filetypes=[("FL Studio", "FL64.exe FL.exe"), ("Programme", "*.exe")], parent=root)
        if p:
            fm_save(fl=str(Path(p)))
            flexe_var.set(str(Path(p)))
    path_card(flm, "FL Studio", "", flexe_var, (("Choisir…", pick_fl, "ghost"),))

    gc = card(flm)
    gc.pack(fill="x", pady=(0, 14))
    label(gc, "Clé de Graillon automatique", 11, bold=True).pack(anchor="w")
    script_lbl = label(gc, "", 9, MUTED, wrap=680)
    script_lbl.pack(anchor="w", pady=(2, 10))
    gr = tk.Frame(gc, bg=PANEL)
    gr.pack(fill="x")

    def inst_script():
        try:
            toast(f"Script installé : {FM.install_script().name}")
        except OSError as ex:
            toast(f"Installation du script impossible : {ex}")
        refresh_fl()

    def help_script():
        messagebox.showinfo("Clé de Graillon automatique", (
            "FL Studio ne lance ses scripts que sur un port MIDI. À faire une seule fois :\n\n"
            "1. Clique « Installer le script dans FL ».\n"
            "2. Installe loopMIDI (gratuit : tobias-erichsen.de/software/loopmidi.html) et crée un port avec le bouton +.\n"
            "3. Dans FL Studio : Options → MIDI settings. Dans « Input », choisis le port loopMIDI, active-le, "
            "et dans « Controller type » choisis « Melofinds FLmake ». Redémarre FL.\n\n"
            "Sans ça, tout le reste marche : seule la clé de Graillon reste à régler à la main (elle est dans le nom du projet)."), parent=root)
    Btn(gr, "Installer le script dans FL", inst_script, kind="primary").pack(side="left")
    Btn(gr, "Comment l'activer ?", help_script).pack(side="left", padx=8)

    def test_make():
        start = C.load_config().get("dossier") or C.default_folder()
        p = filedialog.askopenfilename(title="Une prod (.wav) pour tester FLmake", initialdir=start, filetypes=[("Prod", "*.wav")], parent=root)
        if not p:
            return
        stem = Path(p).stem
        try:
            out, msg = FM.make(p, C.find_key(stem), C.find_bpm(stem), stem)
            if FM.settings().get("open", True):
                msg = f"{msg} · {FM.open_in_fl(out)}"
            toast(msg, 7000)
        except (OSError, FM.FlpError) as ex:
            toast(f"FLmake : {ex}", 7000)
    tt = card(flm)
    tt.pack(fill="x")
    ttr = tk.Frame(tt, bg=PANEL)
    ttr.pack(fill="x")
    tx = tk.Frame(ttr, bg=PANEL)
    tx.pack(side="left", fill="x", expand=True)
    label(tx, "Tester FLmake", 11, bold=True).pack(anchor="w")
    label(tx, "Choisis une prod de ton dossier : FLmake crée son projet et l'ouvre dans FL.", 9, MUTED).pack(anchor="w")
    Btn(ttr, "Tester avec une prod…", test_make, kind="primary").pack(side="right")

    def refresh_fl():
        res = FM.last_result()
        if not FM.script_installed():
            script_lbl.configure(text="Script pas installé : la clé de Graillon ne se réglera pas toute seule.", fg=AMBER)
        elif res:
            script_lbl.configure(text=f"Dernier passage du script dans FL : {'✓' if res[1] else '✗'} {res[2]}", fg=GREEN if res[1] else RED)
        else:
            script_lbl.configure(text="Script installé, mais il n'a encore jamais tourné dans FL : active-le une fois "
                                      "(« Comment l'activer ? » : loopMIDI + Controller type « Melofinds FLmake »).", fg=AMBER)
    on_show["flmake"] = lambda: (check_tpl(), refresh_fl())

    # ================= Appareils
    devp = page("devices", "Appareils", "Les téléphones (ou ordinateurs) qui peuvent envoyer des prods à ce PC. Chacun a son propre code secret.")
    dc = card(devp, padx=2, pady=2)
    dc.pack(fill="both", expand=True)
    devs = ttk.Treeview(dc, columns=("nom", "type", "activite", "ajout"), show="headings", height=8, selectmode="browse")
    for col, txt, w in (("nom", "NOM", 200), ("type", "APPAREIL", 190), ("activite", "DERNIÈRE ACTIVITÉ", 160), ("ajout", "AJOUTÉ LE", 120)):
        devs.heading(col, text=txt, anchor="w")
        devs.column(col, width=w)
    devs.pack(fill="both", expand=True)
    dev_empty = label(dc, "Aucun appareil. Sur ton téléphone : Melofinds Web → Mon PC → Copier le code, puis « Ajouter un appareil ».", 10, MUTED, wrap=560)
    dbar = tk.Frame(devp, bg=BG)
    dbar.pack(fill="x", pady=(12, 0))

    def add_dev():
        dlg = tk.Toplevel(root, bg=PANEL)
        dlg.title("Ajouter un appareil")
        dlg.transient(root)
        f = tk.Frame(dlg, bg=PANEL, padx=24, pady=20)
        f.pack(fill="both", expand=True)
        label(f, "Ajouter un appareil", 14, bold=True).pack(anchor="w")
        label(f, "Sur le téléphone : Melofinds Web → Mon PC → Copier, puis colle le code ici.", 9, MUTED).pack(anchor="w", pady=(4, 12))
        code = tk.StringVar()
        e = entry(f, code, width=70)
        e.configure(font=(MONO, 9))
        e.pack(fill="x", ipady=6)
        label(f, "Nom (ex. « iPhone de Kim »)", 10, bold=True).pack(anchor="w", pady=(12, 4))
        name = tk.StringVar(value=f"Appareil {len(C.load_config()['devices']) + 1}")
        entry(f, name).pack(fill="x", ipady=6)
        err = label(f, "", 9, RED)
        err.pack(anchor="w", pady=(8, 0))

        def ok():
            cfg = C.load_config()
            try:
                I.add_device(cfg, code.get(), name.get().strip())
            except ValueError as ex:
                err.configure(text=str(ex))
                return
            C.save_config(cfg)
            dlg.destroy()
            I.go_online()
            refresh()
            toast("Appareil ajouté")
        row = tk.Frame(f, bg=PANEL)
        row.pack(fill="x", pady=(14, 0))
        Btn(row, "Ajouter", ok, kind="primary").pack(side="right")
        Btn(row, "Annuler", dlg.destroy).pack(side="right", padx=8)
        e.focus_set()
        dlg.update_idletasks()
        dlg.geometry(f"+{root.winfo_rootx() + 220}+{root.winfo_rooty() + 140}")
        dlg.grab_set()

    def selected_device():
        sel = devs.selection()
        if not sel:
            toast("Choisis d'abord un appareil dans la liste.")
            return None, None
        cfg = C.load_config()
        for d in cfg["devices"]:
            if d["id"] == sel[0]:
                return cfg, d
        return None, None

    def rename_dev():
        cfg, d = selected_device()
        if not d:
            return
        new = simpledialog.askstring("Renommer", "Nouveau nom de l'appareil :", initialvalue=d.get("name", ""), parent=root)
        if new and new.strip():
            d["name"] = new.strip()[:40]
            C.save_config(cfg)
            refresh()

    def remove_dev():
        cfg, d = selected_device()
        if not d:
            return
        if messagebox.askyesno("Retirer l'appareil", f"Retirer « {d.get('name')} » ? Il ne pourra plus envoyer de prods à ce PC.", parent=root):
            cfg["devices"] = [x for x in cfg["devices"] if x["id"] != d["id"]]
            C.save_config(cfg)
            refresh()
    Btn(dbar, "Ajouter un appareil", add_dev, kind="primary").pack(side="left")
    Btn(dbar, "Renommer", rename_dev).pack(side="left", padx=8)
    Btn(dbar, "Retirer", remove_dev, kind="danger").pack(side="left")

    # ================= Réglages
    setp = page("settings", "Réglages", "Dossier des projets, démarrage, mises à jour.", scroll=True)
    path_card(setp, "Dossier des projets", "Chaque prod reçue y arrive dans son propre dossier : « Nom/Nom.wav », et « Nom/Nom.flp » "
                                         "avec FLmake. Seuls des fichiers .wav y sont téléchargés.", fdir_var,
              (("Changer…", change_proj_dir, "ghost"), ("Ouvrir", lambda: (Path(fdir_var.get()).mkdir(parents=True, exist_ok=True), _open_path(fdir_var.get())), "ghost")))
    sc = card(setp)
    sc.pack(fill="x", pady=(0, 14))
    label(sc, "Reconnexion automatique", 11, bold=True).pack(anchor="w")
    label(sc, "Melofinds PC reste en ligne tout seul : quand tu fermes ce panneau, quand tu redémarres l'ordinateur "
              "et après chaque mise à jour. Il ne se met hors ligne que si tu appuies sur « Mettre hors ligne ».",
          9, MUTED, wrap=680).pack(anchor="w", pady=(2, 0))
    rc = card(setp)
    rc.pack(fill="x", pady=(0, 14))

    def set_remote(v):
        cfg = C.load_config()
        cfg["remote"] = bool(v)
        C.save_config(cfg)
        toast("Écoute et gestion depuis l'app web " + ("activées" if v else "désactivées"))
    setting_row(rc, "Écouter et gérer depuis l'app web", "Ta liste de projets et des copies d'écoute légères passent par ntfy.sh pour "
                    "l'onglet « File d'attente » de Melofinds Web (renommer, icône, couleur, favori, écouter, même PC éteint).",
                lambda p: Switch(p, C.load_config().get("remote", True) is not False, set_remote))
    pc_ = card(setp)
    pc_.pack(fill="x", pady=(0, 14))
    label(pc_, "Emplacement du programme", 11, bold=True).pack(anchor="w")
    label(pc_, str(P.base), 9, MUTED, mono=True, wrap=680).pack(anchor="w", pady=(2, 10))
    r5 = tk.Frame(pc_, bg=PANEL)
    r5.pack(fill="x")
    Btn(r5, "Ouvrir", lambda: _open_path(P.base)).pack(side="left")
    Btn(r5, "Journal", lambda: _open_path(P.log)).pack(side="left", padx=8)
    uc = card(setp)
    uc.pack(fill="x", pady=(0, 14))
    ur = tk.Frame(uc, bg=PANEL)
    ur.pack(fill="x")
    ux = tk.Frame(ur, bg=PANEL)
    ux.pack(side="left", fill="x", expand=True)
    label(ux, "Mises à jour", 11, bold=True).pack(anchor="w")
    label(ux, "Seulement les versions officielles (github.com/kimany91/Melofinds), empreinte vérifiée. Vérification automatique chaque jour.",
          9, MUTED, wrap=520).pack(anchor="w")

    def upd():
        toast("Recherche d'une mise à jour…")

        def work():
            try:
                r = C.apply_update(lambda s: root.after(0, toast, s), reopen=True)
            except Exception as ex:
                r = f"Mise à jour impossible : {ex}"
            root.after(0, toast, r)
            if r.startswith("Mise à jour vers"):
                # le panneau se ferme pour laisser l'installateur remplacer ses fichiers ; il se rouvre ensuite
                updating["v"] = True
                root.after(0, toast, f"{r} Le panneau se rouvre tout seul dans un instant.")
                root.after(2500, root.destroy)
        threading.Thread(target=work, daemon=True).start()
    Btn(ur, "Vérifier maintenant", upd, kind="primary").pack(side="right")

    def remove():
        unins = I.uninstaller()
        if not unins:
            messagebox.showinfo("Melofinds PC", "Pour désinstaller : Paramètres Windows → Applications → Melofinds PC.", parent=root)
            return
        subprocess.Popen([str(unins)], close_fds=True)
        root.destroy()
    Btn(setp, "Désinstaller Melofinds PC", remove, kind="danger").pack(anchor="e")

    # ================= En ligne / hors ligne, rafraîchissement
    busy = {"v": False}
    updating = {"v": False}
    down = {"n": 0}

    def toggle_online():
        if busy["v"]:
            return
        going_online = not I.worker_running()
        if going_online and not C.load_config()["devices"]:
            show("devices")
            toast("Ajoute d'abord ton téléphone avec son code d'appairage.")
            return
        busy["v"] = True
        toggle.set(text="Mise en ligne…" if going_online else "Mise hors ligne…", enabled=False)

        def work():
            if going_online:
                I.go_online()
                for _ in range(30):
                    if I.worker_running():
                        break
                    time.sleep(0.5)
            else:
                I.go_offline()
            busy["v"] = False
            root.after(0, refresh)
        threading.Thread(target=work, daemon=True).start()
    toggle.command = toggle_online

    last = {"hist": None}

    def refresh():
        cfg = C.load_config()
        st = C.load_state()
        on = I.worker_running()
        n = len(cfg["devices"])
        if not busy["v"]:
            if on:
                status_lbl.configure(text="En ligne")
                status_sub.configure(text=f"Prêt à recevoir les prods de {n} appareil{'s' if n > 1 else ''}." if n else "Ajoute ton téléphone dans Appareils.")
                dot.itemconfigure(dot_id, fill=GREEN)
                toggle.set(text="Mettre hors ligne", kind="ghost", enabled=True)
            elif I.wants_online(cfg):
                status_lbl.configure(text="Reconnexion…")
                status_sub.configure(text="Melofinds PC se remet en ligne tout seul.")
                dot.itemconfigure(dot_id, fill=AMBER)
                toggle.set(text="Mettre en ligne", kind="online", enabled=True)
            else:
                status_lbl.configure(text="Hors ligne")
                status_sub.configure(text="Tu l'as mis hors ligne. Les prods envoyées t'attendent : elles arrivent dès que tu remets en ligne.")
                dot.itemconfigure(dot_id, fill=AMBER)
                toggle.set(text="Mettre en ligne", kind="online", enabled=True)
        # Reconnexion automatique : en ligne voulu mais programme arrêté (plantage, fermeture…)
        if not busy["v"] and not updating["v"] and not on and I.wants_online(cfg) and not I.update_in_progress():
            down["n"] += 1
            if down["n"] >= 2:
                down["n"] = 0
                I.start_worker()
        else:
            down["n"] = 0
        sel = devs.selection()
        devs.delete(*devs.get_children())
        for d in cfg["devices"]:
            info = st["devices"].get(d["code"], {})
            devs.insert("", "end", iid=d["id"], values=(d.get("name", ""), info.get("ua") or "—", _ago(info.get("last_seen")),
                                                         datetime.fromtimestamp(d.get("added", 0)).strftime("%d/%m/%Y") if d.get("added") else "—"))
        if sel and devs.exists(sel[0]):
            devs.selection_set(sel[0])
        if cfg["devices"]:
            dev_empty.place_forget()
        else:
            dev_empty.place(relx=0.5, rely=0.45, anchor="center")
        nav_items["devices"][4].configure(text=str(n) if n else "")
        h = [(x.get("ok"), x.get("detail"), x.get("t"), x.get("at"), x.get("flp")) for x in st["history"][:40]]
        if h != last["hist"]:
            last["hist"] = h
            hist.delete(*hist.get_children())
            for ok, detail, t, at, flp in h:
                fl = "   · projet FL ✓" if flp and not str(flp).startswith("FLmake") else ""
                hist.insert("", "end", tags=("ok" if ok else "err",),
                            values=("✓" if ok else "✗", f"{Path(detail).stem}{fl}" if ok else f"{t} — {detail}", _ago(at)))
            if not h:
                hist.insert("", "end", values=("", "Aucune prod reçue pour l'instant.", ""))
            if current["page"] == "prods":
                load_prods()

    def tick_progress():
        p = read_progress()
        if p:
            dl_title.configure(text=p.get("t") or "Prod")
            stage = p.get("stage")
            pct = p.get("pct")
            dl_stage.configure(text=STAGES.get(stage, "…") if stage != "download" else "Téléchargement de l'audio…")
            dl_bar.set(float(pct) if (stage == "download" and pct is not None) else None)
            dl_pct.configure(text=f"{float(pct):.0f} %" if stage == "download" and pct is not None else "")
            fill_wait([str(x) for x in (p.get("pending") or []) if isinstance(x, str)])
            qn = int(p.get("queue") or 0)
            dl_queue.configure(text=f"+{qn} en attente" if qn else "EN COURS")
            if not dl_barrow.winfo_ismapped():
                dl_barrow.pack(fill="x")
            dl.configure(highlightbackground=ACCENT2)
            nav_items["home"][4].configure(text="⬇")
        else:
            if dl_barrow.winfo_ismapped():
                dl_barrow.pack_forget()
                last["hist"] = None
                refresh()
            fill_wait([])
            dl_title.configure(text="Aucun téléchargement en cours")
            dl_stage.configure(text="Les prods envoyées depuis ton téléphone s'affichent ici pendant qu'elles arrivent.")
            dl_queue.configure(text="")
            dl.configure(highlightbackground=LINE)
            nav_items["home"][4].configure(text="")
        dl_bar.tick()
        root.after(120 if p else 600, tick_progress)

    def tick():
        try:
            refresh()
            if current["page"] == "flmake":
                refresh_fl()
            elif current["page"] == "prods":
                load_prods()
        finally:
            root.after(3000, tick)

    root._show, root._select, root._style, root._sounds = show, lambda cid: select(cid), lambda: do_style(), lambda: do_play()  # (tests : captures d'écran)
    if not selftest:
        I.ensure_autostart()
        if I.wants_online() and not I.worker_running():
            I.start_worker()  # ouvrir le panneau remet en ligne s'il le faut
    show("home" if C.load_config()["devices"] else "devices")
    tick()
    tick_progress()
    tick_player()
    if selftest:
        for k in ("home", "prods", "flmake", "devices", "settings"):
            show(k)
            root.update()
        root.destroy()
        return
    root.mainloop()
