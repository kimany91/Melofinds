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
ACCENT, ACCENT2, PINK = "#a78bfa", "#8b5cf6", "#ec4899"
GREEN, AMBER, RED, BLUE = "#34d399", "#fbbf24", "#f87171", "#60a5fa"
FONT = "Segoe UI" if C.WINDOWS else "DejaVu Sans"
MONO = "Consolas" if C.WINDOWS else "DejaVu Sans Mono"
LIC_COLORS = {"FFP": GREEN, "F": BLUE}

SITE_URL = "https://kimany91.github.io/Melofinds/"


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
          "flp": "Création du projet FL…"}


# ---------------------------------------------------------------------------
# Petits composants (Tk) au style de Melofinds Web

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

        def wheel(e):
            if body.winfo_height() <= canvas.winfo_height():
                return
            step = -1 if getattr(e, "num", 0) == 4 or getattr(e, "delta", 0) > 0 else 1
            canvas.yview_scroll(step * 3, "units")
        canvas.bind("<Enter>", lambda e: (canvas.bind_all("<MouseWheel>", wheel), canvas.bind_all("<Button-4>", wheel), canvas.bind_all("<Button-5>", wheel)))
        canvas.bind("<Leave>", lambda e: (canvas.unbind_all("<MouseWheel>"), canvas.unbind_all("<Button-4>"), canvas.unbind_all("<Button-5>")))
        return body

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

    for k, txt, gl in (("home", "Accueil", ""), ("prods", "Mes projets FL", ""), ("flmake", "FLmake", ""),
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
    home = page("home", "Accueil", "Ton PC reçoit les prods envoyées depuis Melofinds Web, en .wav, dans ton dossier.")
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

    listc = card(prods, padx=2, pady=2)
    listc.pack(fill="both", expand=True)
    cols = (("fav", "", 34, "center"), ("name", "PROJET", 250, "w"), ("key", "CLÉ", 70, "w"), ("bpm", "BPM", 52, "e"),
            ("instru", "INSTRU", 170, "w"), ("date", "MODIFIÉ", 100, "e"))
    tree = ttk.Treeview(listc, columns=[c[0] for c in cols], show="headings", selectmode="browse")
    for cid, txt, w, anchor in cols:
        tree.heading(cid, text=txt, anchor=anchor)
        tree.column(cid, width=w, anchor=anchor, stretch=cid in ("name", "instru"))
    tsb = ttk.Scrollbar(listc, orient="vertical", command=tree.yview, style="Dark.Vertical.TScrollbar")
    tree.configure(yscrollcommand=tsb.set)
    tsb.pack(side="right", fill="y")
    tree.pack(fill="both", expand=True)
    empty_lbl = label(listc, "", 10, MUTED, wrap=600)

    acts = tk.Frame(prods, bg=BG)
    acts.pack(fill="x", pady=(12, 0))
    sel_lbl = label(acts, "Choisis un projet dans la liste.", 10, MUTED)
    sel_lbl.pack(side="left")
    a_open = Btn(acts, "Ouvrir dans FL", kind="primary")
    a_ren = Btn(acts, "Renommer…")
    a_fav = Btn(acts, "☆ Favori")
    a_dir = Btn(acts, "Dossier")
    a_play = Btn(acts, "▶ Instru")
    for b in (a_play, a_dir, a_fav, a_ren, a_open):
        b.pack(side="right", padx=(8, 0))

    lib = {"items": [], "by_id": {}, "sig": None}

    def selected():
        s = tree.selection()
        return lib["by_id"].get(s[0]) if s else None

    def fill_prods():
        text = q_var.get().strip().lower()
        items = lib["items"]
        shown = [i for i in items if (not text or text in i.name.lower() or text in i.extra.get("instru", "").lower())
                 and (filt["v"] == "all" or i.fav)]
        sel = tree.selection()
        tree.delete(*tree.get_children())
        for i in shown:
            tree.insert("", "end", iid=i.id, values=("★" if i.fav else "☆", i.title, i.key or "—", i.bpm or "—",
                                                     i.extra.get("instru") or "—", _ago(i.date)))
        if sel and tree.exists(sel[0]):
            tree.selection_set(sel[0])
        n_fav = sum(1 for i in items if i.fav)
        count_lbl.configure(text=f"{len(shown)} / {len(items)} projet{'s' if len(items) > 1 else ''} · {n_fav} favori{'s' if n_fav > 1 else ''}")
        if not items:
            empty_lbl.configure(text="Aucun projet FL dans ce dossier pour l'instant. Active FLmake (un projet par prod reçue) "
                                     "ou enregistre tes projets FL dans ce dossier.")
            empty_lbl.place(relx=0.5, rely=0.45, anchor="center")
        elif not shown:
            empty_lbl.configure(text="Aucun projet ne correspond.")
            empty_lbl.place(relx=0.5, rely=0.45, anchor="center")
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
        sig = [(i.id, i.name, i.fav, int(i.date), i.extra.get("instru")) for i in items]
        if force or sig != lib["sig"]:
            lib.update(items=items, by_id={i.id: i for i in items}, sig=sig)
            fill_prods()

    def update_actions():
        it = selected()
        for b in (a_open, a_ren, a_fav, a_dir, a_play):
            b.set(enabled=bool(it))
        if not it:
            sel_lbl.configure(text="Choisis un projet dans la liste.")
            return
        a_fav.set(text="★ Favori" if it.fav else "☆ Favori")
        a_open.set(text="Ouvrir dans FL" if it.flp else ("Créer le projet FL" if FM.settings()["template"] else "Ouvrir la prod"))
        ip = it.extra.get("instru_path")
        a_play.set(enabled=bool(ip and ip.is_file()))
        files = it.extra.get("files")
        sel_lbl.configure(text=f"{it.title[:48]}" + (f"  ·  {files} fichier{'s' if files > 1 else ''}" if files else ""))

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

    def do_play():
        it = selected()
        ip = it and it.extra.get("instru_path")
        if ip and ip.is_file():
            _open_path(ip)

    def do_rename():
        it = selected()
        if not it:
            return
        dlg = tk.Toplevel(root, bg=PANEL)
        dlg.title("Renommer le projet")
        dlg.transient(root)
        dlg.resizable(False, False)
        f = tk.Frame(dlg, bg=PANEL, padx=24, pady=20)
        f.pack(fill="both", expand=True)
        label(f, "Renommer le projet FL", 14, bold=True).pack(anchor="w")
        label(f, "Le dossier du projet et tous les fichiers qui portent son nom (projet, sauvegardes, exports) prennent le "
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
            load_prods(force=True)
            nid = f"p:{new.lower()}"
            if tree.exists(nid):
                tree.selection_set(nid)
                tree.see(nid)
        Btn(row, "Renommer", ok, kind="primary").pack(side="right")
        Btn(row, "Annuler", dlg.destroy).pack(side="right", padx=8)
        e.focus_set()
        e.select_range(0, "end")
        e.bind("<Return>", lambda _e: ok())
        e.bind("<Escape>", lambda _e: dlg.destroy())
        dlg.update_idletasks()
        dlg.geometry(f"+{root.winfo_rootx() + 220}+{root.winfo_rooty() + 140}")
        dlg.grab_set()

    a_open.command, a_ren.command, a_fav.command, a_dir.command, a_play.command = do_open, do_rename, do_fav, do_dir, do_play
    tree.bind("<<TreeviewSelect>>", lambda e: update_actions())
    tree.bind("<Double-1>", lambda e: tree.identify_row(e.y) and do_open(lib["by_id"].get(tree.identify_row(e.y))))

    def tree_click(e):
        row = tree.identify_row(e.y)
        if row and tree.identify_column(e.x) == "#1":
            do_fav(lib["by_id"].get(row))
            return "break"
    tree.bind("<Button-1>", tree_click, add="+")
    menu = tk.Menu(root, tearoff=0, bg=PANEL2, fg=FG, activebackground=ACCENT2, activeforeground="#ffffff", bd=0, font=(FONT, 10))
    menu.add_command(label="Ouvrir dans FL", command=do_open)
    menu.add_command(label="Renommer…", command=do_rename)
    menu.add_command(label="Favori", command=do_fav)
    menu.add_separator()
    menu.add_command(label="Écouter l'instru", command=do_play)
    menu.add_command(label="Ouvrir le dossier", command=do_dir)

    def popup(e):
        row = tree.identify_row(e.y)
        if row:
            tree.selection_set(row)
            menu.tk_popup(e.x_root, e.y_root)
    tree.bind("<Button-3>", popup)
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
            refresh()
            if not I.worker_running():
                I.start_worker()
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
    sw_auto = setting_row(sc, "Se mettre en ligne au démarrage de l'ordinateur", "Melofinds PC reçoit tes prods même si tu n'ouvres pas ce panneau.",
                          lambda p: Switch(p, I.autostart_enabled(), lambda v: (I.set_autostart(v), refresh())))
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
                r = C.apply_update(lambda s: root.after(0, toast, s))
            except Exception as ex:
                r = f"Mise à jour impossible : {ex}"
            root.after(0, toast, r)
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
                I.start_worker()
                for _ in range(30):
                    if I.worker_running():
                        break
                    time.sleep(0.5)
            else:
                I.stop_worker()
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
            else:
                status_lbl.configure(text="Hors ligne")
                status_sub.configure(text="Les prods envoyées t'attendent : elles arrivent dès que tu remets en ligne.")
                dot.itemconfigure(dot_id, fill=AMBER)
                toggle.set(text="Mettre en ligne", kind="online", enabled=True)
        sw_auto.set(I.autostart_enabled())
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

    root._show, root._tree = show, tree  # (tests : captures d'écran)
    show("home" if C.load_config()["devices"] else "devices")
    tick()
    tick_progress()
    if selftest:
        for k in ("home", "prods", "flmake", "devices", "settings"):
            show(k)
            root.update()
        root.destroy()
        return
    root.mainloop()
