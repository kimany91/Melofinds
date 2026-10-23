#!/usr/bin/env python3
"""Melofinds PC : télécharge sur ce PC les prods envoyées depuis Melofinds Web.

Ton téléphone (en 5G ou en Wi-Fi, n'importe où) envoie la prod via ntfy.sh
(service de messages gratuit, sans compte). Ce programme tourne sur ton PC,
récupère les envois toutes les 15 secondes et télécharge l'audio en WAV.

Sécurité :
  - chaque envoi est signé avec ta clé secrète (HMAC-SHA256). La clé ne passe
    jamais par ntfy : un envoi sans la bonne signature est ignoré ;
  - un envoi ne contient qu'un identifiant de vidéo YouTube (11 caractères) :
    jamais de lien, de chemin ou de commande ;
  - tout arrive dans UN seul dossier, choisi ici sur le PC (impossible à changer
    à distance) ; seuls des fichiers .wav vérifiés y sont gardés ;
  - vidéos de 15 min max, 40 téléchargements par heure max, envois de plus de
    48 h ou déjà vus refusés.

Installation (une fois, Windows, dans « Terminal ») :
    winget install --id Python.Python.3.12 -e; winget install --id DenoLand.Deno -e; winget install --id Gyan.FFmpeg -e
    (ferme et rouvre le Terminal)
    python -m pip install -U "yt-dlp[default]"

Lancer (la commande complète, avec ton code et ta clé, est dans Melofinds Web → Mon PC) :
    python melofinds-pc.py --code CODE --cle CLE --demarrage
    --dossier "D:\\Prods"   pour choisir le dossier (par défaut : Musique\\Melofinds)
"""

import argparse
import hashlib
import hmac
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

NTFY = os.environ.get("MELOFINDS_NTFY", "https://ntfy.sh").rstrip("/")
CONFIG = Path.home() / ".melofinds-pc.json"
LOGFILE = Path.home() / ".melofinds-pc.log"
POLL_SECONDS = int(os.environ.get("MELOFINDS_POLL", "15"))
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
CODE_RE = re.compile(r"^melofinds-[a-f0-9]{32}$")
KEY_RE = re.compile(r"^[a-f0-9]{64}$")
MAX_AGE = 48 * 3600          # un envoi plus vieux que 48 h est refusé
MAX_DURATION = 15 * 60       # 15 min max par vidéo
MAX_PER_HOUR = 40


def log(msg):
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    try:
        print(line, flush=True)
    except (OSError, ValueError):
        pass  # pas de console (lancement au démarrage)
    try:
        with open(LOGFILE, "a", encoding="utf-8") as f:
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
    try:
        os.chmod(CONFIG, 0o600)  # la clé secrète n'est lisible que par toi
    except OSError:
        pass


def default_folder():
    home = Path.home()
    for name in ("Music", "Musique"):
        if (home / name).is_dir():
            return str(home / name / "Melofinds")
    return str(home / "Melofinds")


# ---------------------------------------------------------------------------
# Nom du fichier : « Titre propre [Clé, BPM].wav », jamais « free » dedans.

_FREE_BRACKETS = re.compile(
    r"[\[({【「*]\s*(?:100\s*%\s*)?(?:free|ffp|f4p|fnp|gratuit|royalty)[^\])}】」*\n]{0,40}[\])}】」*]", re.I)
_FREE_WORDS = [
    re.compile(r"\b(?:100\s*%\s*)?free\s*(?:for|4)\s*(?:non[\s-]*)?(?:profit|commercial)(?:\s*(?:use|beats?|instrumental))?\b", re.I),
    re.compile(r"\b(?:non[\s-]*)?(?:for\s*)?profit\s*use\b", re.I),
    re.compile(r"\broyalty[\s-]*free\b|\blibre\s*de\s*droits?\b", re.I),
    re.compile(r"\b(?:ffp|f4p|fnp)\b", re.I),
    re.compile(r"\bfree\s*(?:beat|instrumental|instru|download|dl)s?\b", re.I),
    re.compile(r"\b(?:100\s*%\s*)?free\b", re.I),
    re.compile(r"\bgratuite?s?\b", re.I),
]
_ALLOWED = re.compile(r"[^\w\s\-\[\]()',.&+!#]", re.UNICODE)


def clean_title(title):
    t = unicodedata.normalize("NFC", str(title or ""))
    t = re.sub(r"[“”«»]", '"', t)
    t = _FREE_BRACKETS.sub(" ", t)
    for rx in _FREE_WORDS:
        t = rx.sub(" ", t)
    t = t.replace('"', "'")
    t = _ALLOWED.sub(" ", t)
    t = re.sub(r"[\[(]\s*[\])]|'\s*'", " ", t)  # crochets / guillemets vidés
    t = re.sub(r"\s*([|\-–—:,])\s*([|\-–—:,]\s*)+", r" \1 ", t)
    t = re.sub(r"\s{2,}", " ", t)
    t = re.sub(r"^[\s|\-–—:,/.+&]+|[\s|\-–—:,/.+&]+$", "", t)
    return t.strip() or "Prod"


_KEY_PATTERNS = [
    re.compile(r"\b(?:key|tonalit[eé]|cl[eé]|scale)\s*[:=\-|]?\s*([a-g])\s*(#|b|♯|♭|sharp|flat)?\s*(minor|min|major|maj|mineur|majeur|m)?(?![a-z])", re.I),
    re.compile(r"(?:^|[\s|•·,/(\[-])([a-g])\s*(#|♯|b|♭)?\s*(minor|major|min|maj|mineur|majeur)\b", re.I),
]
_BPM_PATTERNS = [
    re.compile(r"(?:^|[^\d])(\d{2,3})\s*-?\s*bpm\b", re.I),
    re.compile(r"\bbpm\s*[:=\-|]?\s*(\d{2,3})\b", re.I),
    re.compile(r"\btempo\s*[:=\-|]?\s*(\d{2,3})\b", re.I),
]


def find_key(*texts):
    for t in texts:
        for rx in _KEY_PATTERNS:
            m = rx.search(t or "")
            if m:
                note, acc, mode = m.group(1).upper(), (m.group(2) or "").lower(), (m.group(3) or "").lower()
                a = "#" if acc in ("#", "♯", "sharp") else "b" if acc in ("b", "♭", "flat") else ""
                md = " min" if mode in ("m", "min", "minor", "mineur") else " maj" if mode in ("maj", "major", "majeur") else ""
                return f"{note}{a}{md}"
    return None


def find_bpm(*texts):
    for t in texts:
        for rx in _BPM_PATTERNS:
            for m in rx.finditer(t or ""):
                n = int(m.group(1))
                if 50 <= n <= 220:
                    return n
    return None


def valid_key(k):
    k = str(k or "").strip()
    return k if re.fullmatch(r"[A-G][#b]?(?: (?:min|maj))?", k) else None


def valid_bpm(b):
    try:
        n = int(b)
    except (TypeError, ValueError):
        return None
    return n if 50 <= n <= 220 else None


def build_name(title, key=None, bpm=None):
    tags = [x for x in (key, f"{bpm} BPM" if bpm else None) if x]
    base = clean_title(title)[:110].rstrip(" -,.")
    name = f"{base} [{', '.join(tags)}]" if tags else base
    # Noms interdits sous Windows (CON, NUL…) et points finaux
    if re.fullmatch(r"(?i)(con|prn|aux|nul|com\d|lpt\d)(\s.*)?", name):
        name = f"Prod {name}"
    return name.rstrip(" .") or "Prod"


# ---------------------------------------------------------------------------
# Envois signés

def verify(raw, key_hex):
    """Renvoie le contenu d'un envoi authentique, sinon None."""
    try:
        env = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(env, dict) or not isinstance(env.get("p"), str) or not isinstance(env.get("s"), str):
        return None
    good = hmac.new(bytes.fromhex(key_hex), env["p"].encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(good, env["s"].lower()):
        return None
    try:
        msg = json.loads(env["p"])
    except ValueError:
        return None
    if not isinstance(msg, dict) or msg.get("mf") != 2:
        return None
    ts = msg.get("ts")
    if not isinstance(ts, (int, float)) or abs(time.time() - ts / 1000) > MAX_AGE:
        return None
    if not re.fullmatch(r"[a-f0-9]{16,64}", str(msg.get("n") or "")):
        return None
    return msg


def http(url, data=None, timeout=40):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "melofinds-pc/2"})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read().decode("utf-8", "replace")


def reply(code, payload):
    """Prévient l'app (sujet <code>-ok) : PC en ligne, prod téléchargée ou erreur."""
    try:
        http(f"{NTFY}/{code}-ok", data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), timeout=15)
    except (urllib.error.URLError, OSError) as e:
        log(f"Impossible de prévenir l'app : {e}")


def poll(code, since):
    url = f"{NTFY}/{code}/json?poll=1&since={urllib.parse.quote(str(since))}"
    out = []
    for line in http(url).splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict) and ev.get("event") == "message":
            out.append(ev)
    return out


# ---------------------------------------------------------------------------
# Téléchargement : WAV seulement, dans le dossier choisi seulement

def is_wav(path):
    try:
        with open(path, "rb") as f:
            head = f.read(12)
        return head[:4] == b"RIFF" and head[8:12] == b"WAVE"
    except OSError:
        return False


def inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def unique_path(root, name):
    p = Path(root) / f"{name}.wav"
    i = 2
    while p.exists():
        p = Path(root) / f"{name} ({i}).wav"
        i += 1
    return p


def download(video_id, root, info):
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        return False, 'yt-dlp n\'est pas installé : python -m pip install -U "yt-dlp[default]"'
    if not shutil.which("ffmpeg"):
        return False, "ffmpeg n'est pas installé (winget install --id Gyan.FFmpeg -e) : impossible de faire un WAV"

    url = f"https://www.youtube.com/watch?v={video_id}"
    base = {
        "noplaylist": True, "quiet": True, "no_warnings": True, "noprogress": True,
        "writethumbnail": False, "writesubtitles": False, "writeinfojson": False,
        "writedescription": False, "writeannotations": False, "keepvideo": False,
    }
    # 1) Infos d'abord : on refuse les vidéos trop longues (ou les directs).
    try:
        with YoutubeDL(base) as ydl:
            meta = ydl.extract_info(url, download=False)
    except Exception as e:  # yt-dlp lève beaucoup de types d'erreurs
        return False, str(e).splitlines()[0][:200]
    if meta.get("is_live") or (meta.get("duration") or 0) > MAX_DURATION:
        return False, "vidéo trop longue ou en direct (15 min max)"

    desc = meta.get("description") or ""
    key = valid_key(info.get("key")) or find_key(meta.get("title") or "", desc)
    bpm = valid_bpm(info.get("bpm")) or find_bpm(meta.get("title") or "", desc)
    final = unique_path(root, build_name(meta.get("title") or info.get("t") or video_id, key, bpm))

    # 2) Téléchargement + conversion dans un dossier temporaire, hors de ton dossier.
    with tempfile.TemporaryDirectory(prefix="melofinds-") as tmp:
        opts = dict(base)
        opts.update({
            "format": "bestaudio/best",
            "paths": {"home": tmp, "temp": tmp},
            "outtmpl": "audio.%(ext)s",
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}],
            "max_filesize": 200 * 1024 * 1024,
        })
        try:
            with YoutubeDL(opts) as ydl:
                ydl.download([url])
        except Exception as e:
            return False, str(e).splitlines()[0][:200]
        wavs = [p for p in Path(tmp).iterdir() if p.suffix.lower() == ".wav" and is_wav(p)]
        if not wavs:
            return False, "la conversion en WAV a échoué"
        # 3) Seul le .wav vérifié entre dans ton dossier.
        if not inside(final, root) or final.suffix.lower() != ".wav":
            return False, "nom de fichier refusé"
        shutil.move(str(wavs[0]), str(final))
    if not is_wav(final):
        final.unlink(missing_ok=True)
        return False, "fichier non WAV supprimé"
    return True, final.name


def install_startup(script):
    if os.name != "nt":
        log("Démarrage auto : seulement sur Windows. Sur Mac/Linux, ajoute la commande aux programmes de démarrage.")
        return
    startup = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    runner = pythonw if pythonw.exists() else exe
    bat = startup / "Melofinds PC.bat"
    bat.write_text(f'@echo off\r\nstart "" /min "{runner}" "{script}"\r\n', encoding="utf-8")
    log(f"OK : Melofinds PC se lancera à chaque démarrage ({bat})")


def main():
    ap = argparse.ArgumentParser(description="Télécharge sur ce PC (en WAV) les prods envoyées depuis Melofinds Web.")
    ap.add_argument("--code", help="code affiché dans Melofinds Web (Mon PC)")
    ap.add_argument("--cle", help="clé secrète affichée dans Melofinds Web (Mon PC)")
    ap.add_argument("--dossier", help="le SEUL dossier où les prods arrivent")
    ap.add_argument("--demarrage", action="store_true", help="lancer automatiquement au démarrage de Windows")
    ap.add_argument("--une-fois", action="store_true", help="vérifier une fois puis quitter (test)")
    args = ap.parse_args()

    cfg = load_config()
    if args.code:
        cfg["code"] = args.code.strip().lower()
    if args.cle:
        cfg["cle"] = args.cle.strip().lower()
    if args.dossier:
        cfg["dossier"] = str(Path(args.dossier).expanduser().resolve())
    cfg.setdefault("dossier", default_folder())
    if not CODE_RE.match(cfg.get("code") or "") or not KEY_RE.match(cfg.get("cle") or ""):
        log("Code ou clé manquant : copie la commande complète depuis Melofinds Web → Mon PC.")
        return 1
    root = Path(cfg["dossier"])
    root.mkdir(parents=True, exist_ok=True)
    save_config(cfg)
    if args.demarrage:
        install_startup(Path(__file__).resolve())

    code, key = cfg["code"], cfg["cle"]
    log(f"Melofinds PC prêt. Dossier (le seul utilisé) : {root} · format : WAV")
    log("Laisse tourner (ou utilise --demarrage). Ctrl+C pour arrêter.")
    reply(code, {"pc": "online", "dossier": str(root)})

    seen = set(cfg.get("seen", []))
    done = set(cfg.get("done", []))
    since = cfg.get("since") or "12h"
    recent = []
    while True:
        try:
            for ev in poll(code, since):
                since = ev.get("id") or since
                msg = verify(ev.get("message") or "", key)
                if not msg:
                    log("Envoi ignoré : signature absente ou fausse.")
                    continue
                if msg["n"] in seen:
                    continue
                seen.add(msg["n"])
                if msg.get("ping"):
                    reply(code, {"pong": msg["n"], "dossier": str(root)})
                    continue
                vid = str(msg.get("v") or "")
                if not VIDEO_ID.match(vid):
                    continue
                if vid in done and not msg.get("force"):
                    reply(code, {"v": vid, "ok": True, "deja": True})
                    continue
                recent = [t for t in recent if t > time.time() - 3600]
                if len(recent) >= MAX_PER_HOUR:
                    reply(code, {"v": vid, "ok": False, "err": "limite de 40 téléchargements par heure"})
                    continue
                recent.append(time.time())
                log(f"Téléchargement : {msg.get('t') or vid}")
                ok, detail = download(vid, root, msg)
                if ok:
                    done.add(vid)
                    log(f"  OK : {detail}")
                else:
                    log(f"  Erreur : {detail}")
                reply(code, {"v": vid, "ok": ok, "file" if ok else "err": detail})
            cfg.update(since=since, seen=list(seen)[-3000:], done=list(done)[-3000:])
            save_config(cfg)
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            log(f"Pas de connexion à ntfy.sh ({e}). Nouvel essai bientôt.")
            time.sleep(POLL_SECONDS)
        if args.une_fois:
            return 0
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        print("\nArrêté.")
