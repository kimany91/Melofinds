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
        text = "".join(L.ICONS) + "★☆▶■✓✗❚▾▴"
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
    # Clé / BPM sur le PC (Essentia dans Edge invisible) : prod de test en la mineur à 140 BPM
    try:
        import math
        import struct
        import wave
        import mf_keybpm as K
        with tempfile.TemporaryDirectory(prefix="melofinds-kb-test-") as d:
            wav = Path(d) / "test.wav"
            sr, n = 22050, 22050 * 24
            f = lambda m: 440 * 2 ** ((m - 69) / 12)
            prog = [[0, 3, 7], [5, 8, 12], [7, 11, 14], [0, 3, 7]]
            data = []
            for i in range(n):
                t = i / sr
                ch = prog[int(t / (60 / 140 * 4)) % 4]
                v = 0.07 * (sum(math.sin(2 * math.pi * f(69 + iv) * t) for iv in ch) + 0.7 * math.sin(2 * math.pi * f(45 + ch[0]) * t))
                b = (t % (60 / 140))
                v += 0.9 * math.sin(2 * math.pi * (50 + 110 * math.exp(-b * 30)) * b) * math.exp(-b * 10) if int(t / (60 / 140)) % 2 == 0 else 0
                data.append(struct.pack("<h", max(-32767, min(32767, int(v * 20000)))))
            with wave.open(str(wav), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(sr)
                w.writeframes(b"".join(data))
            res["keybpm"] = K.analyze(wav)
    except Exception as e:
        res["keybpm"] = f"erreur : {e}"[:200]
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
    # Arrêt de Windows : la fenêtre invisible qui prévient le téléphone doit exister
    if C.WINDOWS:
        import ctypes
        import time
        rep = {}
        stop = C.watch_windows_shutdown(lambda: rep.update(called=True), rep)
        time.sleep(1.5)
        found = ctypes.windll.user32.FindWindowW("MelofindsPCWorker", None)
        res["shutdown_watch"] = {**rep, "found": bool(found)}
        if found:
            ctypes.windll.user32.SendMessageW(found, 0x16, 1, 0)
            res["shutdown_watch"]["called"] = bool(rep.get("called"))
        stop()
    # Tunebat (informatif) : une prod connue, sortie sur Spotify par son beatmaker
    res["tunebat"] = C.tunebat_lookup("NEMZZZ TYPE BEAT", "Nemzzz", 173) or "rien / injoignable"
    desc = C.video_description("jNQXAC9IVRw")  # « Me at the zoo » : lecture d'une vraie description
    res["description"] = (desc[:80] if desc else "rien / injoignable")
    res["glyphs_missing"] = missing_glyphs()
    try:
        import mf_gui as G
        G.manager_window(selftest=True)
        res["gui"] = "ok"
    except Exception as e:  # Tk absent ou cassé
        res["gui"] = f"erreur {e}"
    res["ok"] = (res["preview"]["ok"] and not res["glyphs_missing"] and not res["tool_errors"] and all(res[n] != "absent" for n in ("yt-dlp.exe", "ffmpeg.exe", "deno.exe"))
                 and res["gui"] == "ok")
    Path(out).write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if res["ok"] else 1


def promotest(out):
    """Test Promo (construction sur GitHub, Windows) : moteur de paroles officiel téléchargé,
    une voix sur un beat → paroles datées → vidéo 1080x1920 ; une image de la vidéo pour la vérifier."""
    import subprocess
    import time
    import mf_promo as PM
    res = {"version": C.VERSION}
    t0 = time.time()
    try:
        PM.ensure_whisper(lambda *a: None)
        PM.ensure_fonts()
        res["ready"] = PM.ready()
        res["install_s"] = round(time.time() - t0, 1)
        speech = os.environ.get("MELOFINDS_TEST_SPEECH", "")
        ff = C.tool_path("ffmpeg.exe")
        d = Path(tempfile.mkdtemp(prefix="melofinds-promotest-"))
        song, bg = d / "son.wav", d / "visuel.mp4"
        # la voix arrive à 1,5 s, sur un beat (kick + basse) : comme un vrai morceau
        subprocess.run([ff, "-loglevel", "error", "-y", "-i", speech, "-f", "lavfi", "-i", "sine=frequency=55:duration=14",
                        "-f", "lavfi", "-i", "aevalsrc=0.6*sin(2*PI*60*t)*exp(-12*mod(t\\,0.43)):d=14",
                        "-filter_complex", "[0:a]adelay=1500|1500,volume=1.6[v];[1:a]volume=0.25[b];[2:a]volume=0.5[k];[v][b][k]amix=3:duration=longest[o]",
                        "-map", "[o]", "-ar", "44100", str(song)], check=True, timeout=120)
        subprocess.run([ff, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=720x1280:rate=30", "-t", "3", str(bg)],
                       check=True, timeout=120)
        t1 = time.time()
        r = PM.transcribe(song, 0, 12, None, lambda *a: None, lang="en")
        res["transcribe_s"] = round(time.time() - t1, 1)
        res["words"], res["lines"], res["dtw_tokens"] = r["words"], r["lines"], r.get("dtw")
        t2 = time.time()
        vid = PM.render(bg, song, 0, 12, r["lines"], d / "promo.mp4", "impact")
        res["render_s"] = round(time.time() - t2, 1)
        at = (r["lines"][0]["s"] + 0.3) if r["lines"] else 2
        frame = Path(out).with_suffix(".jpg")
        subprocess.run([ff, "-loglevel", "error", "-y", "-ss", f"{at:.2f}", "-i", str(vid), "-frames:v", "1", "-vf", "scale=270:-2",
                        "-q:v", "5", str(frame)], timeout=60)
        res["video"] = {"bytes": vid.stat().st_size, "frame": str(frame)}
        first = r["words"][0]["s"] if r["words"] else -1
        res["first_word_s"] = first
        res["ok"] = bool(r["lines"]) and 1.0 <= first <= 2.4  # la voix commence à 1,5 s
    except Exception as e:
        import traceback
        res["ok"] = False
        res["err"] = traceback.format_exc()[-1500:]
    Path(out).write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
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
    ap.add_argument("--embedtest", metavar="FICHIER", help=argparse.SUPPRESS)
    ap.add_argument("--promotest", metavar="FICHIER", help=argparse.SUPPRESS)  # test : paroles + vidéo Promo  # test : site dans la page Rechercher
    args = ap.parse_args(argv)
    P.set(C.resolve_install_dir())

    if args.selftest:
        return selftest(args.selftest)
    if args.promotest:
        return promotest(args.promotest)
    if args.embedtest:
        import mf_gui as G
        G.manager_window(selftest=True, embedtest=args.embedtest)
        return 0
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
