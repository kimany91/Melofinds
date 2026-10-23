#!/usr/bin/env python3
"""Melofinds PC : reçoit sur ton PC, en .wav, les prods envoyées depuis Melofinds Web.

  - MelofindsSetup.exe (installateur Windows standard, pc/installer.iss) : demande où
    installer, où arrivent les prods, installe le programme et ses outils (inclus),
    crée les raccourcis et peut le lancer avec Windows ;
  - le raccourci « Melofinds PC » ouvre le PANNEAU DE GESTION : mettre en ligne /
    hors ligne, démarrage automatique, appareils connectés, dossier des prods,
    mises à jour, désinstallation ;
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
    """Vérification automatique (construction sur GitHub, Windows) : outils, nom de fichier,
    fenêtre, et (si demandé) un vrai téléchargement."""
    res = {"version": C.VERSION, "frozen": I.frozen(), "dir": str(P.base)}
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
        G.manager_window(selftest=True)
        res["gui"] = "ok"
    except Exception as e:  # Tk absent ou cassé
        res["gui"] = f"erreur {e}"
    res["ok"] = (not res["tool_errors"] and all(res[n] != "absent" for n in ("yt-dlp.exe", "ffmpeg.exe", "deno.exe"))
                 and res["gui"] == "ok")
    Path(out).write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if res["ok"] else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Melofinds PC : reçoit les prods envoyées depuis Melofinds Web.")
    ap.add_argument("--background", action="store_true", help="être en ligne (reçoit les prods), sans fenêtre")
    ap.add_argument("--stop", action="store_true", help="se mettre hors ligne (utilisé par l'installateur)")
    ap.add_argument("--configure", action="store_true", help="réglages après installation (utilisé par l'installateur)")
    ap.add_argument("--start-if-configured", action="store_true", help="se remettre en ligne après une installation")
    ap.add_argument("--pair", help="ajouter un appareil avec son code d'appairage")
    ap.add_argument("--nom", default="", help="nom de l'appareil ajouté avec --pair")
    ap.add_argument("--dossier", help="dossier des prods")
    ap.add_argument("--une-fois", action="store_true", help="vérifier une fois puis quitter (test)")
    ap.add_argument("--selftest", metavar="FICHIER", help="vérification automatique")
    args = ap.parse_args(argv)
    P.set(C.resolve_install_dir())

    if args.selftest:
        return selftest(args.selftest)
    if args.stop:
        I.stop_worker()
        return 0
    if args.configure or args.pair or args.dossier:
        try:
            I.configure(dossier=args.dossier, pairing=args.pair, device_name=args.nom)
        except ValueError as e:
            log(f"Configuration : {e}")
        if not (args.background or args.une_fois or args.start_if_configured):
            return 0
    if args.start_if_configured:
        I.start_if_configured()
        return 0
    if args.background or args.une_fois:
        I.migrate_old()
        return worker(once=args.une_fois)
    try:
        import tkinter  # noqa: F401
        import mf_gui as G
    except ImportError:
        log("Pas d'interface graphique ici : utilise --pair CODE puis --background.")
        return 1
    I.migrate_old()
    G.manager_window()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        pass
