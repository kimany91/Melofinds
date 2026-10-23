"""Melofinds PC — panneau de gestion (l'installation est faite par MelofindsSetup.exe)."""

import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import mf_core as C
import mf_install as I
from mf_core import P

BG, PANEL, PANEL2, LINE = "#0b0c10", "#15171d", "#1b1e26", "#2a2e3a"
FG, MUTED, ACCENT, GREEN, AMBER, RED = "#f3f4f7", "#a0a6b6", "#8b5cf6", "#34d399", "#fbbf24", "#f87171"
FONT = "Segoe UI" if C.WINDOWS else "DejaVu Sans"


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
    return f"il y a {int(s // 86400)} j"


def _style(root):
    from tkinter import ttk
    root.configure(bg=BG)
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except Exception:
        pass
    st.configure(".", background=BG, foreground=FG, font=(FONT, 10), fieldbackground=PANEL2, bordercolor=LINE)
    st.configure("TFrame", background=BG)
    st.configure("Card.TFrame", background=PANEL, relief="flat")
    st.configure("TLabel", background=BG, foreground=FG)
    st.configure("Card.TLabel", background=PANEL)
    st.configure("Muted.TLabel", foreground=MUTED)
    st.configure("CardMuted.TLabel", background=PANEL, foreground=MUTED)
    st.configure("Title.TLabel", font=(FONT, 17, "bold"))
    st.configure("H.TLabel", font=(FONT, 11, "bold"))
    st.configure("CardH.TLabel", background=PANEL, font=(FONT, 11, "bold"))
    st.configure("Status.TLabel", background=PANEL, font=(FONT, 14, "bold"))
    st.configure("TButton", background=PANEL2, foreground=FG, padding=(12, 7), borderwidth=0, font=(FONT, 10, "bold"))
    st.map("TButton", background=[("active", LINE), ("disabled", PANEL)], foreground=[("disabled", MUTED)])
    st.configure("Accent.TButton", background=ACCENT, foreground="#ffffff")
    st.map("Accent.TButton", background=[("active", "#7c3aed"), ("disabled", PANEL2)])
    st.configure("Danger.TButton", background=PANEL2, foreground=RED)
    st.configure("Online.TButton", background=GREEN, foreground="#0b0c10", padding=(18, 10), font=(FONT, 11, "bold"))
    st.map("Online.TButton", background=[("active", "#10b981")])
    st.configure("Offline.TButton", background=PANEL2, foreground=FG, padding=(18, 10), font=(FONT, 11, "bold"))
    st.configure("TCheckbutton", background=BG, foreground=FG)
    st.configure("Card.TCheckbutton", background=PANEL, foreground=FG)
    st.map("TCheckbutton", background=[("active", BG)])
    st.map("Card.TCheckbutton", background=[("active", PANEL)])
    st.configure("TEntry", fieldbackground=PANEL2, foreground=FG, insertcolor=FG, padding=6)
    st.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 0))
    st.configure("TNotebook.Tab", background=BG, foreground=MUTED, padding=(16, 8), font=(FONT, 10, "bold"), borderwidth=0)
    st.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", FG)])
    st.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG, rowheight=30, borderwidth=0)
    st.configure("Treeview.Heading", background=PANEL2, foreground=MUTED, font=(FONT, 9, "bold"), borderwidth=0)
    st.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#ffffff")])
    st.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=PANEL2, borderwidth=0)
    return st


def _icon(root):
    try:
        import tkinter as tk
        img = tk.PhotoImage(width=32, height=32)
        img.put(ACCENT, to=(0, 0, 32, 32))
        img.put("#ffffff", to=(8, 14, 11, 24))
        img.put("#ffffff", to=(14, 9, 17, 24))
        img.put("#ffffff", to=(20, 12, 23, 24))
        root.iconphoto(True, img)
        root._icon = img
    except Exception:
        pass


SITE_URL = "https://kimany91.github.io/Melofinds/"


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


# ---------------------------------------------------------------------------
# Panneau de gestion

def manager_window(selftest=False):
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog, ttk

    root = tk.Tk()
    root.title("Melofinds PC")
    root.geometry("760x560")
    root.minsize(640, 500)
    _style(root)
    _icon(root)
    outer = ttk.Frame(root, padding=(20, 16))
    outer.pack(fill="both", expand=True)
    head = ttk.Frame(outer)
    head.pack(fill="x")
    ttk.Label(head, text="Melofinds PC", style="Title.TLabel").pack(side="left")
    ttk.Label(head, text=f"version {C.VERSION}", style="Muted.TLabel").pack(side="left", padx=10, pady=(6, 0))
    ttk.Button(head, text="Ouvrir Melofinds Web", style="Accent.TButton", command=open_site).pack(side="right")
    tabs = ttk.Notebook(outer)
    tabs.pack(fill="both", expand=True, pady=(12, 0))

    def card(parent, **kw):
        f = ttk.Frame(parent, style="Card.TFrame", padding=16)
        f.pack(fill="x", pady=(0, 12), **kw)
        return f

    # --- Accueil
    home = ttk.Frame(tabs, padding=14)
    tabs.add(home, text="  Accueil  ")
    c1 = card(home)
    status_var = tk.StringVar()
    sub_var = tk.StringVar()
    left = ttk.Frame(c1, style="Card.TFrame")
    left.pack(side="left", fill="x", expand=True)
    dot = tk.Canvas(left, width=14, height=14, bg=PANEL, highlightthickness=0)
    dot.pack(side="left", padx=(0, 10))
    dot_id = dot.create_oval(2, 2, 12, 12, fill=MUTED, outline="")
    txt = ttk.Frame(left, style="Card.TFrame")
    txt.pack(side="left", fill="x", expand=True)
    ttk.Label(txt, textvariable=status_var, style="Status.TLabel").pack(anchor="w")
    ttk.Label(txt, textvariable=sub_var, style="CardMuted.TLabel", wraplength=420).pack(anchor="w")
    toggle = ttk.Button(c1, text="Mettre en ligne", style="Online.TButton")
    toggle.pack(side="right")

    c2 = card(home)
    auto_var = tk.BooleanVar(value=I.autostart_enabled())
    ttk.Checkbutton(c2, text="Se mettre en ligne tout seul au démarrage de l'ordinateur", variable=auto_var, style="Card.TCheckbutton",
                    command=lambda: (I.set_autostart(auto_var.get()), refresh())).pack(anchor="w")

    c3 = ttk.Frame(home, style="Card.TFrame", padding=16)
    c3.pack(fill="both", expand=True)
    ttk.Label(c3, text="Dernières prods reçues", style="CardH.TLabel").pack(anchor="w", pady=(0, 8))
    hist = ttk.Treeview(c3, columns=("prod", "quand"), show="headings", height=6)
    hist.heading("prod", text="Prod")
    hist.heading("quand", text="Reçue")
    hist.column("prod", width=480)
    hist.column("quand", width=120, anchor="e")
    hist.pack(fill="both", expand=True)

    # --- Appareils
    dev_tab = ttk.Frame(tabs, padding=14)
    tabs.add(dev_tab, text="  Appareils  ")
    ttk.Label(dev_tab, text="Les téléphones (ou ordinateurs) qui peuvent envoyer des prods à ce PC. Chacun a son propre code secret.",
              style="Muted.TLabel", wraplength=680).pack(anchor="w", pady=(0, 10))
    devs = ttk.Treeview(dev_tab, columns=("nom", "type", "activite", "ajout"), show="headings", height=8, selectmode="browse")
    for col, label, w in (("nom", "Nom", 180), ("type", "Appareil", 170), ("activite", "Dernière activité", 150), ("ajout", "Ajouté le", 120)):
        devs.heading(col, text=label)
        devs.column(col, width=w)
    devs.pack(fill="both", expand=True)
    dev_btns = ttk.Frame(dev_tab)
    dev_btns.pack(fill="x", pady=(10, 0))

    def add_dev():
        dlg = tk.Toplevel(root)
        dlg.title("Ajouter un appareil")
        dlg.configure(bg=BG)
        dlg.transient(root)
        dlg.grab_set()
        f = ttk.Frame(dlg, padding=18)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Code d'appairage", style="H.TLabel").pack(anchor="w")
        ttk.Label(f, text="Sur le téléphone : Melofinds Web → Mon PC → Copier, puis colle-le ici.", style="Muted.TLabel").pack(anchor="w")
        code = tk.StringVar()
        e = ttk.Entry(f, textvariable=code, width=70, font=("Consolas", 9))
        e.pack(fill="x", pady=(4, 10))
        ttk.Label(f, text="Nom (ex. « iPhone de Kim »)", style="H.TLabel").pack(anchor="w")
        name = tk.StringVar(value=f"Appareil {len(C.load_config()['devices']) + 1}")
        ttk.Entry(f, textvariable=name).pack(fill="x", pady=(4, 10))
        err = tk.StringVar()
        ttk.Label(f, textvariable=err, foreground=RED).pack(anchor="w")

        def ok():
            cfg = C.load_config()
            try:
                I.add_device(cfg, code.get(), name.get().strip())
            except ValueError as ex:
                err.set(str(ex))
                return
            C.save_config(cfg)
            dlg.destroy()
            refresh()
            if not I.worker_running():
                I.start_worker()
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(6, 0))
        ttk.Button(row, text="Ajouter", style="Accent.TButton", command=ok).pack(side="right")
        ttk.Button(row, text="Annuler", command=dlg.destroy).pack(side="right", padx=8)
        e.focus_set()

    def selected_device():
        sel = devs.selection()
        if not sel:
            messagebox.showinfo("Melofinds PC", "Choisis d'abord un appareil dans la liste.", parent=root)
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

    ttk.Button(dev_btns, text="Ajouter un appareil", style="Accent.TButton", command=add_dev).pack(side="left")
    ttk.Button(dev_btns, text="Renommer", command=rename_dev).pack(side="left", padx=8)
    ttk.Button(dev_btns, text="Retirer", style="Danger.TButton", command=remove_dev).pack(side="left")

    # --- Dossier & réglages
    set_tab = ttk.Frame(tabs, padding=14)
    tabs.add(set_tab, text="  Dossier & réglages  ")
    c4 = card(set_tab)
    ttk.Label(c4, text="Dossier où arrivent les prods", style="CardH.TLabel").pack(anchor="w")
    ttk.Label(c4, text="Seuls des fichiers .wav y sont enregistrés, nommés « Titre [Clé, BPM].wav ».", style="CardMuted.TLabel").pack(anchor="w")
    beats_var = tk.StringVar(value=C.load_config().get("dossier") or C.default_folder())
    r4 = ttk.Frame(c4, style="Card.TFrame")
    r4.pack(fill="x", pady=(8, 0))
    ttk.Entry(r4, textvariable=beats_var, state="readonly").pack(side="left", fill="x", expand=True)

    def change_folder():
        p = filedialog.askdirectory(title="Où ranger les prods reçues ?", initialdir=beats_var.get(), parent=root)
        if not p:
            return
        cfg = C.load_config()
        cfg["dossier"] = str(Path(p))
        Path(cfg["dossier"]).mkdir(parents=True, exist_ok=True)
        C.save_config(cfg)
        beats_var.set(cfg["dossier"])
        msg_var.set("Dossier changé : les prochaines prods arriveront là.")
    ttk.Button(r4, text="Changer…", command=change_folder).pack(side="left", padx=(8, 0))
    ttk.Button(r4, text="Ouvrir", command=lambda: _open_path(beats_var.get())).pack(side="left", padx=(8, 0))

    c5 = card(set_tab)
    ttk.Label(c5, text="Emplacement du programme", style="CardH.TLabel").pack(anchor="w")
    ttk.Label(c5, text=str(P.base), style="CardMuted.TLabel", wraplength=640).pack(anchor="w", pady=(2, 8))
    r5 = ttk.Frame(c5, style="Card.TFrame")
    r5.pack(fill="x")
    ttk.Button(r5, text="Ouvrir", command=lambda: _open_path(P.base)).pack(side="left")
    ttk.Button(r5, text="Journal", command=lambda: _open_path(P.log)).pack(side="left", padx=8)

    c6 = card(set_tab)
    ttk.Label(c6, text="Mises à jour", style="CardH.TLabel").pack(anchor="w")
    ttk.Label(c6, text="Seulement les versions officielles (github.com/kimany91/Melofinds), empreinte vérifiée. Vérification automatique chaque jour.",
              style="CardMuted.TLabel", wraplength=640).pack(anchor="w", pady=(2, 8))
    r6 = ttk.Frame(c6, style="Card.TFrame")
    r6.pack(fill="x")

    def upd():
        msg_var.set("Recherche d'une mise à jour…")

        def work():
            try:
                r = C.apply_update(lambda s: root.after(0, msg_var.set, s))
            except Exception as e:
                r = f"Mise à jour impossible : {e}"
            root.after(0, msg_var.set, r)
        threading.Thread(target=work, daemon=True).start()
    ttk.Button(r6, text="Vérifier maintenant", command=upd).pack(side="left")

    def remove():
        unins = I.uninstaller()
        if not unins:
            messagebox.showinfo("Melofinds PC", "Pour désinstaller : Paramètres Windows → Applications → Melofinds PC.", parent=root)
            return
        # Le désinstalleur Windows (créé par l'installateur) demande confirmation, arrête le
        # programme et retire tout, sauf tes prods.
        subprocess.Popen([str(unins)], close_fds=True)
        root.destroy()
    ttk.Button(set_tab, text="Désinstaller Melofinds PC", style="Danger.TButton", command=remove).pack(anchor="e", pady=(4, 0))
    msg_var = tk.StringVar()
    ttk.Label(outer, textvariable=msg_var, style="Muted.TLabel", wraplength=700).pack(anchor="w", pady=(8, 0))

    # --- En ligne / hors ligne
    busy = {"v": False}

    def toggle_online():
        if busy["v"]:
            return
        busy["v"] = True
        toggle.state(["disabled"])
        going_online = not I.worker_running()
        if going_online and not C.load_config()["devices"]:
            busy["v"] = False
            toggle.state(["!disabled"])
            tabs.select(dev_tab)
            msg_var.set("Ajoute d'abord ton téléphone (onglet Appareils) avec son code d'appairage.")
            return
        msg_var.set("Mise en ligne…" if going_online else "Mise hors ligne… (les prods envoyées t'attendront)")

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
            root.after(0, lambda: (toggle.state(["!disabled"]), msg_var.set(""), refresh()))
        threading.Thread(target=work, daemon=True).start()
    toggle.configure(command=toggle_online)

    def refresh():
        cfg = C.load_config()
        st = C.load_state()
        on = I.worker_running()
        n = len(cfg["devices"])
        if busy["v"]:
            pass
        elif on:
            status_var.set("En ligne")
            sub_var.set(f"Prêt à recevoir des prods de {n} appareil{'s' if n > 1 else ''}." if n else "Aucun appareil : ajoute ton téléphone dans « Appareils ».")
            dot.itemconfigure(dot_id, fill=GREEN)
            toggle.configure(text="Mettre hors ligne", style="Offline.TButton")
        else:
            status_var.set("Hors ligne")
            sub_var.set("Les prods envoyées attendent et arriveront dès que tu remets en ligne.")
            dot.itemconfigure(dot_id, fill=AMBER)
            toggle.configure(text="Mettre en ligne", style="Online.TButton")
        auto_var.set(I.autostart_enabled())
        sel = devs.selection()
        devs.delete(*devs.get_children())
        for d in cfg["devices"]:
            info = st["devices"].get(d["code"], {})
            devs.insert("", "end", iid=d["id"], values=(d.get("name", ""), info.get("ua") or "—", _ago(info.get("last_seen")),
                                                         datetime.fromtimestamp(d.get("added", 0)).strftime("%d/%m/%Y") if d.get("added") else "—"))
        if sel and devs.exists(sel[0]):
            devs.selection_set(sel[0])
        hist.delete(*hist.get_children())
        for h in st["history"][:30]:
            label = h.get("detail") if h.get("ok") else f"✗ {h.get('t', '')} — {h.get('detail', '')}"
            hist.insert("", "end", values=(label, _ago(h.get("at"))))
        if not st["history"]:
            hist.insert("", "end", values=("Aucune prod reçue pour l'instant.", ""))

    def tick():
        try:
            refresh()
        finally:
            root.after(3000, tick)

    if not C.load_config()["devices"]:
        tabs.select(dev_tab)
    tick()
    if selftest:
        for t in (home, dev_tab, set_tab):
            tabs.select(t)
            root.update()
        root.destroy()
        return
    root.mainloop()
