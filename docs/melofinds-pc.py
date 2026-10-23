#!/usr/bin/env python3
"""Melofinds PC : télécharge sur ce PC les prods envoyées depuis Melofinds Web.

Ton téléphone (en 5G ou en Wi-Fi, n'importe où) envoie la prod via ntfy.sh
(service de messages gratuit, sans compte). Ce programme tourne sur ton PC,
récupère les envois toutes les 15 secondes et télécharge l'audio avec yt-dlp
dans ton dossier, rangé par licence.

Installation (une fois, Windows) :
    winget install --id Python.Python.3.12 -e
    winget install --id DenoLand.Deno -e
    winget install --id Gyan.FFmpeg -e
    python -m pip install -U "yt-dlp[default]"

Lancer :
    python melofinds-pc.py --code TON-CODE          (le code est dans Melofinds Web)
    python melofinds-pc.py --demarrage              (se lance tout seul au démarrage du PC)

Options :
    --dossier "D:\\Prods"     dossier de destination (par défaut : Musique\\Melofinds)
    --format wav|mp3|m4a      wav par défaut si ffmpeg est installé, sinon m4a
"""

import argparse
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

NTFY = os.environ.get("MELOFINDS_NTFY", "https://ntfy.sh").rstrip("/")
CONFIG = Path.home() / ".melofinds-pc.json"
POLL_SECONDS = int(os.environ.get("MELOFINDS_POLL", "15"))
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
CODE_RE = re.compile(r"^melofinds-[a-f0-9]{24,48}$")
# Dossiers par licence : on n'utilise jamais le texte reçu pour nommer un dossier.
FOLDERS = {
    "ffp": "Free for profit",
    "upto": "Up to (limite de streams)",
    "fnp": "Free non-profit",
    "paid": "Payant",
    "unknown": "A verifier",
}


def log(msg):
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        with open(Path.home() / ".melofinds-pc.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d} {line}\n")
    except OSError:
        pass


def load_config():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def default_folder():
    home = Path.home()
    for name in ("Music", "Musique"):
        if (home / name).is_dir():
            return str(home / name / "Melofinds")
    return str(home / "Melofinds")


def http(url, data=None, timeout=40):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "melofinds-pc/1"})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read().decode("utf-8", "replace")


def reply(code, payload):
    """Prévient l'app (sujet <code>-ok) : prod téléchargée, erreur, ou PC en ligne."""
    try:
        http(f"{NTFY}/{code}-ok", data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), timeout=15)
    except (urllib.error.URLError, OSError) as e:
        log(f"Impossible de prévenir l'app : {e}")


def poll(code, since):
    url = f"{NTFY}/{code}/json?poll=1&since={urllib.parse.quote(str(since))}"
    out = []
    for line in http(url).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("event") == "message":
            out.append(ev)
    return out


def safe_name(s, limit=120):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", str(s or "")).strip(" .")
    return re.sub(r"\s+", " ", s)[:limit] or "prod"


def download(video_id, cat, fmt, folder, info):
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        return False, 'yt-dlp n\'est pas installé : python -m pip install -U "yt-dlp[default]"'

    target = Path(folder) / FOLDERS.get(cat, FOLDERS["unknown"])
    target.mkdir(parents=True, exist_ok=True)
    has_ffmpeg = shutil.which("ffmpeg") is not None
    if fmt in ("wav", "mp3") and not has_ffmpeg:
        log("ffmpeg introuvable : je garde le format d'origine (m4a). Installe-le : winget install --id Gyan.FFmpeg -e")
        fmt = "m4a"
    opts = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": str(target / "%(title).150B [%(id)s].%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    if fmt in ("wav", "mp3"):
        pp = {"key": "FFmpegExtractAudio", "preferredcodec": fmt}
        if fmt == "mp3":
            pp["preferredquality"] = "320"
        opts["postprocessors"] = [pp]
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        with YoutubeDL(opts) as ydl:
            meta = ydl.extract_info(url, download=True)
            path = Path(ydl.prepare_filename(meta))
            if fmt in ("wav", "mp3"):
                path = path.with_suffix(f".{fmt}")
    except Exception as e:  # yt-dlp lève beaucoup de types d'erreurs différents
        return False, str(e).splitlines()[0][:200]

    # Petite fiche à côté du son : lien, licence, BPM (pour retrouver les conditions).
    lines = [
        f"Titre : {meta.get('title') or info.get('t') or ''}",
        f"YouTube : {url}",
        f"Licence (Melofinds) : {info.get('licence') or FOLDERS.get(cat, '')}",
    ]
    if info.get("bpm"):
        lines.append(f"BPM : {info['bpm']}")
    if info.get("key"):
        lines.append(f"Tonalité : {info['key']}")
    lines += ["", "Attention : l'audio YouTube contient souvent le tag du beatmaker.",
              "La version sans tag s'achète ou se télécharge via le lien de la description.",
              "", "Description :", (meta.get("description") or "")[:5000]]
    try:
        path.with_suffix(".txt").write_text("\n".join(lines), encoding="utf-8")
    except OSError:
        pass
    return True, path.name


def install_startup(script):
    if os.name != "nt":
        log("Démarrage auto : seulement sur Windows. Sur Mac/Linux, ajoute la commande à tes programmes de démarrage.")
        return
    startup = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    runner = pythonw if pythonw.exists() else exe
    bat = startup / "Melofinds PC.bat"
    bat.write_text(f'@echo off\r\nstart "" /min "{runner}" "{script}"\r\n', encoding="utf-8")
    log(f"OK : Melofinds PC se lancera à chaque démarrage ({bat})")


def main():
    ap = argparse.ArgumentParser(description="Télécharge sur ce PC les prods envoyées depuis Melofinds Web.")
    ap.add_argument("--code", help="code affiché dans Melofinds Web (Télécharger sur mon PC)")
    ap.add_argument("--dossier", help="dossier de destination")
    ap.add_argument("--format", choices=["wav", "mp3", "m4a"], help="format audio (wav par défaut)")
    ap.add_argument("--demarrage", action="store_true", help="lancer automatiquement au démarrage de Windows")
    ap.add_argument("--une-fois", action="store_true", help="vérifier une fois puis quitter (test)")
    args = ap.parse_args()

    cfg = load_config()
    if args.code:
        cfg["code"] = args.code.strip()
    if args.dossier:
        cfg["dossier"] = args.dossier
    if args.format:
        cfg["format"] = args.format
    cfg.setdefault("dossier", default_folder())
    cfg.setdefault("format", "wav")
    while not CODE_RE.match(cfg.get("code") or ""):
        if not sys.stdin or not sys.stdin.isatty():
            log("Code manquant : lance une fois  python melofinds-pc.py --code TON-CODE")
            return 1
        cfg["code"] = input("Colle le code affiché dans Melofinds Web : ").strip()
    save_config(cfg)
    if args.demarrage:
        install_startup(Path(__file__).resolve())

    code = cfg["code"]
    Path(cfg["dossier"]).mkdir(parents=True, exist_ok=True)
    log(f"Melofinds PC prêt. Dossier : {cfg['dossier']} · format : {cfg['format']}")
    log("Laisse cette fenêtre ouverte (ou utilise --demarrage). Ctrl+C pour arrêter.")
    reply(code, {"pc": "online", "dossier": cfg["dossier"]})

    done = set(cfg.get("done", []))
    since = cfg.get("since") or "12h"
    while True:
        try:
            events = poll(code, since)
            for ev in events:
                since = ev.get("id") or since
                try:
                    msg = json.loads(ev.get("message") or "{}")
                except ValueError:
                    continue
                if not isinstance(msg, dict):
                    continue
                if msg.get("ping"):
                    reply(code, {"pong": msg.get("ping"), "dossier": cfg["dossier"]})
                    continue
                vid = str(msg.get("v") or "")
                if not VIDEO_ID.match(vid):
                    continue
                if vid in done and not msg.get("force"):
                    reply(code, {"v": vid, "ok": True, "deja": True})
                    continue
                log(f"Téléchargement : {msg.get('t') or vid}")
                ok, detail = download(vid, str(msg.get("cat") or "unknown"), cfg["format"], cfg["dossier"], msg)
                if ok:
                    done.add(vid)
                    log(f"  OK : {detail}")
                else:
                    log(f"  Erreur : {detail}")
                reply(code, {"v": vid, "ok": ok, "file" if ok else "err": detail})
            cfg["since"] = since
            cfg["done"] = list(done)[-1000:]
            save_config(cfg)
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            log(f"Pas de connexion à ntfy.sh ({e}). Nouvel essai dans {POLL_SECONDS * 2} s.")
            time.sleep(POLL_SECONDS)
        if args.une_fois:
            return 0
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        print("\nArrêté.")
