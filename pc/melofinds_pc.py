#!/usr/bin/env python3
"""Melofinds PC : reçoit sur ton PC, en .wav, les prods envoyées depuis Melofinds Web.

Un seul programme :
  - lancé depuis Téléchargements (MelofindsSetup.exe) : c'est l'INSTALLATEUR. Il demande
    où mettre ses fichiers, installe ses outils s'ils manquent (yt-dlp, ffmpeg, Deno),
    crée un raccourci sur le bureau et peut se lancer avec Windows ;
  - lancé depuis son dossier (raccourci du bureau) : c'est le PANNEAU DE GESTION :
    mettre en ligne / hors ligne, démarrage automatique, appareils connectés,
    dossier des prods, mises à jour, désinstallation ;
  - « --background » : la partie en ligne, qui reçoit et télécharge les prods.

Voir mf_core.py pour la sécurité (envois signés, WAV seulement, un seul dossier).
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mf_core as C  # noqa: E402
import mf_install as I  # noqa: E402
from mf_core import P, log  # noqa: E402
from mf_worker import worker  # noqa: E402


def selftest(out):
    """Vérification automatique (construction du programme sur GitHub, Windows)."""
    res = {"version": C.VERSION, "frozen": I.frozen()}
    res["tool_errors"] = C.ensure_tools()
    for name, args in (("yt-dlp.exe", ["--version"]), ("ffmpeg.exe", ["-version"]), ("deno.exe", ["--version"])):
        p = C.tool_path(name)
        try:
            r = C.run_tool([p, *args], 120) if p else None
            res[name] = C.last_line(r.stdout)[:80] if r and r.returncode == 0 else "absent"
        except OSError as e:
            res[name] = f"erreur {e}"
    res["name"] = C.build_name('[FREE FOR PROFIT] Luther Type Beat "TREE"', "F# min", 140)
    vid = os.environ.get("MELOFINDS_TEST_VIDEO", "")
    if C.VIDEO_ID.match(vid):  # vrai téléchargement (informatif : YouTube bloque souvent les serveurs)
        with tempfile.TemporaryDirectory(prefix="melofinds-test-") as d:
            ok, detail = C.download(vid, d, {})
            res["download"] = {"ok": ok, "detail": detail, "files": [x.name for x in Path(d).iterdir()]}
    try:
        import mf_gui as G
        G.setup_window(selftest=True)
        G.manager_window(selftest=True)
        res["gui"] = "ok"
    except Exception as e:  # Tk absent ou cassé
        res["gui"] = f"erreur {e}"
    # Vraie installation dans un dossier temporaire, puis désinstallation.
    inst = {}
    if C.WINDOWS and I.frozen():
        try:
            target = Path(tempfile.mkdtemp(prefix="mf-install-")) / "Melofinds Test"
            token = f"melofinds-{os.urandom(16).hex()}.{os.urandom(32).hex()}"
            inst["issues"] = I.install(target, target.parent / "Prods", desktop=True, autostart=True, pairing=token, device_name="Test")
            inst["exe"] = (target / C.EXE_NAME).exists()
            inst["devices"] = len(C.load_config()["devices"])
            inst["registry"] = C.registry_install_dir() == str(target)
            inst["autostart"] = I.autostart_enabled()
            desktop = Path(os.environ.get("USERPROFILE", "")) / "Desktop" / "Melofinds PC.lnk"
            inst["desktop_lnk"] = desktop.exists()
            import time as _t
            for _ in range(40):
                if I.worker_running():
                    break
                _t.sleep(0.5)
            inst["online"] = I.worker_running()
            I.stop_worker(timeout=20)
            inst["offline_after_stop"] = not I.worker_running()
            I.uninstall()
            inst["removed"] = not (target / C.EXE_NAME).exists() and not (target / "tools").exists()
            inst["registry_clean"] = C.registry_install_dir() is None and not I.autostart_enabled()
            inst["desktop_lnk_removed"] = not desktop.exists()
            inst["prods_kept"] = (target.parent / "Prods").exists()
            inst["ok"] = all(inst[k] for k in ("exe", "registry", "autostart", "desktop_lnk", "online", "offline_after_stop",
                                                "removed", "registry_clean", "desktop_lnk_removed", "prods_kept")) and inst["devices"] == 1
        except Exception as e:
            inst["ok"] = False
            inst["error"] = repr(e)
    res["install"] = inst
    res["ok"] = (not res["tool_errors"] and all(res[n] != "absent" for n in ("yt-dlp.exe", "ffmpeg.exe", "deno.exe"))
                 and res["gui"] == "ok" and (inst.get("ok", True)))
    Path(out).write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if res["ok"] else 1


def confirm_uninstall():
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        ok = messagebox.askyesno("Désinstaller Melofinds PC", "Désinstaller Melofinds PC ?\nTes prods restent dans leur dossier.")
        r.destroy()
        return ok
    except Exception:
        return True


def main(argv=None):
    ap = argparse.ArgumentParser(description="Melofinds PC : reçoit les prods envoyées depuis Melofinds Web.")
    ap.add_argument("--background", action="store_true", help="être en ligne (reçoit les prods), sans fenêtre")
    ap.add_argument("--uninstall", action="store_true", help="désinstaller")
    ap.add_argument("--pair", help="ajouter un appareil avec son code d'appairage (sans fenêtre)")
    ap.add_argument("--nom", default="", help="nom de l'appareil ajouté avec --pair")
    ap.add_argument("--dossier", help="dossier des prods (sans fenêtre)")
    ap.add_argument("--une-fois", action="store_true", help="vérifier une fois puis quitter (test)")
    ap.add_argument("--selftest", metavar="FICHIER", help="vérification automatique")
    args = ap.parse_args(argv)
    P.set(C.resolve_install_dir())

    if args.selftest:
        return selftest(args.selftest)
    if args.uninstall:
        if P.dir and confirm_uninstall():
            I.uninstall()
        return 0
    if args.pair or args.dossier:
        if P.dir is None:
            log("Pas encore installé : lance d'abord l'installateur.")
            return 1
        cfg = C.load_config()
        if args.pair:
            I.add_device(cfg, args.pair, args.nom)
        if args.dossier:
            cfg["dossier"] = str(Path(args.dossier).expanduser())
        C.save_config(cfg)
        if not args.background and not args.une_fois:
            return 0
    if args.background or args.une_fois:
        if P.dir is None:
            log("Pas encore installé : lance d'abord l'installateur.")
            return 1
        return worker(once=args.une_fois)
    try:
        import tkinter  # noqa: F401
        import mf_gui as G
    except ImportError:
        log("Pas d'interface graphique ici : utilise --pair CODE puis --background.")
        return 1
    if I.is_setup_mode():
        G.setup_window()
    else:
        G.manager_window()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        pass
