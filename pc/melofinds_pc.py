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


def missing_glyphs():
    """Icônes du panneau absentes de la police Windows qui les dessine (contrôle du build)."""
    if not C.WINDOWS:
        return None
    try:
        import ctypes
        import mf_library as L
        text = "".join(L.ICONS) + "★☆▶■✓✗"
        gdi, user = ctypes.windll.gdi32, ctypes.windll.user32
        hdc = user.GetDC(0)
        font = gdi.CreateFontW(-20, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0, "Segoe UI Symbol")
        old = gdi.SelectObject(hdc, font)
        buf = (ctypes.c_ushort * len(text))()
        gdi.GetGlyphIndicesW(hdc, text, len(text), buf, 1)  # 1 = marquer les absents (0xFFFF)
        gdi.SelectObject(hdc, old)
        gdi.DeleteObject(font)
        user.ReleaseDC(0, hdc)
        return [ch for ch, g in zip(text, buf) if g == 0xFFFF]
    except Exception as e:
        return f"contrôle impossible : {e}"


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
            seen = {}
            ok, detail = C.download(vid, d, {}, None, lambda st, pct: seen.update({st: max(seen.get(st) or 0, pct or 0)}))
            res["download"] = {"ok": ok, "detail": detail, "progress": seen,
                               "files": [str(x.relative_to(d)) for x in Path(d).rglob("*")]}
    # Copie d'écoute pour l'app web (vrai ffmpeg) : un son de 3 min doit tenir en 2 pièces jointes ntfy
    try:
        import math
        import struct
        import wave
        with tempfile.TemporaryDirectory(prefix="melofinds-ecoute-test-") as d:
            src = Path(d) / "test.wav"
            with wave.open(str(src), "wb") as w:
                w.setnchannels(2)
                w.setsampwidth(2)
                w.setframerate(44100)
                second = b"".join(struct.pack("<hh", v, v) for v in (int(8000 * math.sin(i * 440 * 2 * math.pi / 44100)
                                                                         + 3000 * math.sin(i * 0.37)) for i in range(44100)))
                w.writeframes(second * 180)  # 3 min (une seconde répétée : rapide)
            prev = C.make_preview(src, Path(d) / "ecoute.m4a")
            n = prev.stat().st_size
            res["preview"] = {"bytes": n, "parts": len(C.chunks(prev.read_bytes())), "ok": 0 < n <= 2 * C.ATTACH_MAX}
    except Exception as e:
        res["preview"] = {"ok": False, "err": str(e)[:200]}
    # Tunebat (informatif) : une prod connue, sortie sur Spotify par son beatmaker
    res["tunebat"] = C.tunebat_lookup("NEMZZZ TYPE BEAT", "Nemzzz", 173) or "rien / injoignable"
    res["glyphs_missing"] = missing_glyphs()
    try:
        import mf_gui as G
        G.manager_window(selftest=True)
        res["gui"] = "ok"
    except Exception as e:  # Tk absent ou cassé
        res["gui"] = f"erreur {e}"
    res["ok"] = (res["preview"]["ok"] and not res["tool_errors"] and all(res[n] != "absent" for n in ("yt-dlp.exe", "ffmpeg.exe", "deno.exe"))
                 and res["gui"] == "ok")
    Path(out).write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if res["ok"] else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Melofinds PC : reçoit les prods envoyées depuis Melofinds Web.")
    ap.add_argument("--background", action="store_true", help="être en ligne (reçoit les prods), sans fenêtre")
    ap.add_argument("--stop", action="store_true", help="arrêter le programme en ligne (installateur ; reviendra tout seul)")
    ap.add_argument("--arret-maj", action="store_true", help=argparse.SUPPRESS)  # installateur : arrêt le temps d'une mise à jour
    ap.add_argument("--en-ligne", action="store_true", help="se mettre en ligne (retenu)")
    ap.add_argument("--hors-ligne", action="store_true", help="se mettre hors ligne (retenu, même après redémarrage)")
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
    if args.arret_maj:
        I.stop_worker(reason="update")
        return 0
    if args.hors_ligne:
        I.go_offline()
        return 0
    if args.en_ligne:
        I.migrate_old()
        I.go_online()
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
        if args.background and not I.wants_online():
            # Démarrage de Windows : on reste hors ligne seulement si tu l'as choisi dans le panneau
            log("Hors ligne (choisi dans le panneau, ou aucun appareil) : pas de mise en ligne.")
            return 0
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
