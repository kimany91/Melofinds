#!/usr/bin/env python3
"""Melofinds PC : un seul programme qui gère tout sur ton PC.

Double-clique sur MelofindsPC.exe, colle le code d'appairage affiché dans
Melofinds Web (bouton « Mon PC »), choisis ton dossier : c'est tout.
Le programme
  - télécharge lui-même ses outils (yt-dlp, ffmpeg, Deno) dans son dossier ;
  - se lance tout seul, en arrière-plan, à chaque démarrage du PC ;
  - récupère les prods envoyées depuis ton téléphone (5G ou Wi-Fi) via ntfy.sh
    et les enregistre en .wav, nommées « Titre [Clé, BPM].wav » ;
  - se met à jour quand tu le demandes depuis l'app (et tout seul chaque jour),
    uniquement depuis les versions officielles de ton dépôt GitHub.

Sécurité :
  - chaque envoi est signé avec ta clé secrète (HMAC-SHA256) ; la clé ne passe
    jamais par ntfy. Envoi non signé, modifié, rejoué ou de plus de 48 h : ignoré ;
  - un envoi ne contient qu'un identifiant de vidéo YouTube : jamais de lien,
    de chemin, de fichier ou de commande ;
  - téléchargement et conversion dans un dossier temporaire : seul un vrai .wav
    (en-tête RIFF/WAVE vérifié) entre dans TON dossier, choisi sur le PC ;
  - mise à jour : seulement depuis github.com/kimany91/Melofinds/releases, avec
    empreinte SHA-256 vérifiée ; les outils aussi sont vérifiés quand l'éditeur
    publie une empreinte.
"""

import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

VERSION = "2.0.0"
REPO = "kimany91/Melofinds"
RELEASES = f"https://github.com/{REPO}/releases"
MANIFEST_URL = f"{RELEASES}/latest/download/version.json"
NTFY = os.environ.get("MELOFINDS_NTFY", "https://ntfy.sh").rstrip("/")
POLL_SECONDS = int(os.environ.get("MELOFINDS_POLL", "15"))
WINDOWS = os.name == "nt"
NO_WINDOW = 0x08000000 if WINDOWS else 0  # pas de fenêtre noire pour les outils

if WINDOWS:
    APP_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Melofinds"
else:
    APP_DIR = Path(os.environ.get("MELOFINDS_HOME") or Path.home() / ".melofinds")
CONFIG = APP_DIR / "config.json"
LOGFILE = APP_DIR / "melofinds.log"
HEARTBEAT = APP_DIR / "heartbeat"
LOCKFILE = APP_DIR / "worker.lock"
TOOLS = APP_DIR / "tools"
EXE_NAME = "MelofindsPC.exe"

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
CODE_RE = re.compile(r"^melofinds-[a-f0-9]{32}$")
KEY_RE = re.compile(r"^[a-f0-9]{64}$")
PAIR_RE = re.compile(r"^(melofinds-[a-f0-9]{32})\.([a-f0-9]{64})$")
MAX_AGE = 48 * 3600
MAX_DURATION = 15 * 60
MAX_PER_HOUR = 40

TOOL_SOURCES = {
    "yt-dlp.exe": {
        "url": "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe",
        "sums": "https://github.com/yt-dlp/yt-dlp/releases/latest/download/SHA2-256SUMS",
        "asset": "yt-dlp.exe",
    },
    "ffmpeg.exe": {
        "url": "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
        "sums": "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/checksums.sha256",
        "asset": "ffmpeg-master-latest-win64-gpl.zip",
        "extract": ["ffmpeg.exe", "ffprobe.exe"],
    },
    "deno.exe": {
        "url": "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip",
        "sums": "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip.sha256sum",
        "asset": "deno-x86_64-pc-windows-msvc.zip",
        "extract": ["deno.exe"],
    },
}


# ---------------------------------------------------------------------------
# Journal, réglages

def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    try:
        print(line, flush=True)
    except (OSError, ValueError, AttributeError):
        pass  # pas de console (programme fenêtré)
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        if LOGFILE.exists() and LOGFILE.stat().st_size > 2_000_000:
            LOGFILE.replace(LOGFILE.with_suffix(".old.log"))
        with open(LOGFILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_config():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CONFIG)
    try:
        os.chmod(CONFIG, 0o600)
    except OSError:
        pass


def default_folder():
    home = Path.home()
    for name in ("Music", "Musique"):
        if (home / name).is_dir():
            return str(home / name / "Melofinds")
    return str(home / "Melofinds")


def parse_pairing(text):
    m = PAIR_RE.match(str(text or "").strip().lower())
    return (m.group(1), m.group(2)) if m else None


def version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:3]) or (0,)


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
    if re.fullmatch(r"(?i)(con|prn|aux|nul|com\d|lpt\d)(\s.*)?", name):
        name = f"Prod {name}"
    return name.rstrip(" .") or "Prod"


# ---------------------------------------------------------------------------
# Envois signés (ntfy)

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


def http_get(url, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": f"melofinds-pc/{VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read()


def http_post(url, data, timeout=15):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": f"melofinds-pc/{VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read()


def reply(code, payload):
    """Prévient l'app (sujet <code>-ok)."""
    try:
        http_post(f"{NTFY}/{code}-ok", json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    except (urllib.error.URLError, OSError) as e:
        log(f"Impossible de prévenir l'app : {e}")


def poll(code, since):
    url = f"{NTFY}/{code}/json?poll=1&since={urllib.parse.quote(str(since))}"
    out = []
    for line in http_get(url).decode("utf-8", "replace").splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict) and ev.get("event") == "message":
            out.append(ev)
    return out


# ---------------------------------------------------------------------------
# Outils (yt-dlp, ffmpeg, Deno) : téléchargés et vérifiés par le programme

def download_file(url, dest, progress=None, label=""):
    req = urllib.request.Request(url, headers={"User-Agent": f"melofinds-pc/{VERSION}"})
    h = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=60) as res, open(dest, "wb") as f:
        total = int(res.headers.get("Content-Length") or 0)
        got = 0
        last = 0
        while True:
            chunk = res.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            got += len(chunk)
            if progress and time.time() - last > 0.3:
                last = time.time()
                progress(f"{label} : {got // 1_000_000} Mo" + (f" / {total // 1_000_000} Mo" if total else ""))
    return h.hexdigest()


def expected_hash(sums_url, asset):
    """Empreinte publiée par l'éditeur de l'outil, ou None si introuvable."""
    try:
        text = http_get(sums_url, timeout=20).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError):
        return None
    lines = [l for l in text.splitlines() if asset in l] or text.splitlines()
    for l in lines:
        m = re.search(r"\b([a-fA-F0-9]{64})\b", l)
        if m:
            return m.group(1).lower()
    return None


def tool_path(name):
    """Chemin d'un outil : dossier du programme, sinon le PATH (Mac / Linux)."""
    local = TOOLS / name
    if local.exists():
        return str(local)
    return shutil.which(name.replace(".exe", "")) or shutil.which(name)


def ensure_tools(progress=None):
    """Télécharge les outils manquants (Windows). Renvoie la liste des erreurs."""
    errors = []
    if not WINDOWS:
        for t in ("yt-dlp", "ffmpeg"):
            if not shutil.which(t):
                errors.append(f"{t} introuvable dans le PATH")
        return errors
    TOOLS.mkdir(parents=True, exist_ok=True)
    for name, src in TOOL_SOURCES.items():
        if (TOOLS / name).exists():
            continue
        say = progress or (lambda s: None)
        say(f"Téléchargement de {name.replace('.exe', '')}…")
        log(f"Téléchargement de l'outil {name}")
        with tempfile.TemporaryDirectory(prefix="melofinds-tool-") as tmp:
            dest = Path(tmp) / src["asset"]
            try:
                got = download_file(src["url"], dest, say, name.replace(".exe", ""))
            except (urllib.error.URLError, OSError) as e:
                errors.append(f"{name} : téléchargement impossible ({e})")
                continue
            want = expected_hash(src["sums"], src["asset"])
            if want and want != got:
                errors.append(f"{name} : empreinte SHA-256 incorrecte, fichier rejeté")
                continue
            if "extract" in src:
                try:
                    with zipfile.ZipFile(dest) as z:
                        for member in z.namelist():
                            base = member.rsplit("/", 1)[-1]
                            if base in src["extract"]:  # jamais de chemin venant du zip
                                with z.open(member) as fi, open(TOOLS / base, "wb") as fo:
                                    shutil.copyfileobj(fi, fo)
                except zipfile.BadZipFile:
                    errors.append(f"{name} : archive abîmée")
                    continue
            else:
                shutil.copyfile(dest, TOOLS / name)
        if not (TOOLS / name).exists():
            errors.append(f"{name} : introuvable après installation")
    return errors


def tool_env():
    env = dict(os.environ)
    env["PATH"] = str(TOOLS) + os.pathsep + env.get("PATH", "")  # yt-dlp y trouve Deno et ffmpeg
    return env


def run_tool(args, timeout):
    return subprocess.run(args, capture_output=True, timeout=timeout, env=tool_env(),
                          creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)


def update_ytdlp():
    exe = TOOLS / "yt-dlp.exe"
    if exe.exists():
        try:
            run_tool([str(exe), "-U"], 300)
            log("yt-dlp vérifié / mis à jour")
        except (OSError, subprocess.SubprocessError) as e:
            log(f"Mise à jour de yt-dlp impossible : {e}")


# ---------------------------------------------------------------------------
# Téléchargement d'une prod : WAV seulement, dans TON dossier seulement

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


def decode(b):
    try:
        return (b or b"").decode("utf-8")
    except UnicodeDecodeError:
        return (b or b"").decode("cp1252" if WINDOWS else "latin-1", "replace")  # console Windows


def last_line(b):
    lines = [l for l in decode(b).splitlines() if l.strip()]
    return (lines[-1] if lines else "erreur inconnue")[:200]


def download(video_id, root, info):
    ytdlp = tool_path("yt-dlp.exe")
    ffmpeg = tool_path("ffmpeg.exe")
    if not ytdlp:
        return False, "yt-dlp manquant (relance l'installation)"
    if not ffmpeg:
        return False, "ffmpeg manquant : impossible de faire un WAV"
    url = f"https://www.youtube.com/watch?v={video_id}"

    # 1) Infos : on refuse les vidéos trop longues et les directs.
    try:
        r = run_tool([ytdlp, "-J", "--no-playlist", "--no-warnings", url], 180)
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"yt-dlp : {e}"
    if r.returncode != 0:
        return False, last_line(r.stderr)
    try:
        meta = json.loads(decode(r.stdout))
    except ValueError:
        return False, "réponse illisible de yt-dlp"
    if meta.get("is_live") or (meta.get("duration") or 0) > MAX_DURATION:
        return False, "vidéo trop longue ou en direct (15 min max)"
    desc = meta.get("description") or ""
    key = valid_key(info.get("key")) or find_key(meta.get("title") or "", desc)
    bpm = valid_bpm(info.get("bpm")) or find_bpm(meta.get("title") or "", desc)
    final = unique_path(root, build_name(meta.get("title") or info.get("t") or video_id, key, bpm))
    if not inside(final, root) or final.suffix.lower() != ".wav":
        return False, "nom de fichier refusé"

    # 2) Téléchargement + conversion dans un dossier temporaire, hors de ton dossier.
    with tempfile.TemporaryDirectory(prefix="melofinds-") as tmp:
        args = [ytdlp, "--no-playlist", "--no-warnings", "--no-progress", "--no-mtime",
                "-f", "bestaudio/best", "-x", "--audio-format", "wav",
                "--ffmpeg-location", str(Path(ffmpeg).parent),
                "--max-filesize", "200M", "-P", f"home:{tmp}", "-P", f"temp:{tmp}",
                "-o", "audio.%(ext)s", url]
        try:
            r = run_tool(args, 900)
        except (OSError, subprocess.SubprocessError) as e:
            return False, f"yt-dlp : {e}"
        if r.returncode != 0:
            return False, last_line(r.stderr)
        wavs = [p for p in Path(tmp).iterdir() if p.suffix.lower() == ".wav" and is_wav(p)]
        if not wavs:
            return False, "la conversion en WAV a échoué"
        # 3) Seul le .wav vérifié entre dans ton dossier.
        shutil.move(str(wavs[0]), str(final))
    if not is_wav(final):
        final.unlink(missing_ok=True)
        return False, "fichier non WAV supprimé"
    return True, final.name


# ---------------------------------------------------------------------------
# Mise à jour du programme (uniquement depuis les versions officielles)

def check_update():
    """Renvoie (version, url, sha256) si une version plus récente existe."""
    data = json.loads(http_get(MANIFEST_URL, timeout=20).decode("utf-8-sig"))
    ver, url, sha = str(data.get("version", "")), str(data.get("url", "")), str(data.get("sha256", "")).lower()
    if not url.startswith(f"{RELEASES}/download/") or not re.fullmatch(r"[a-f0-9]{64}", sha):
        raise ValueError("fichier de version invalide")
    if version_tuple(ver) <= version_tuple(VERSION):
        return None
    return ver, url, sha


def apply_update(progress=None):
    """Télécharge, vérifie et installe la nouvelle version. Renvoie un message."""
    if not getattr(sys, "frozen", False) or not WINDOWS:
        return "Mise à jour automatique : seulement pour MelofindsPC.exe sur Windows."
    found = check_update()
    if not found:
        return f"Déjà à jour (version {VERSION})."
    ver, url, sha = found
    APP_DIR.mkdir(parents=True, exist_ok=True)
    new = APP_DIR / "MelofindsPC.new.exe"
    got = download_file(url, new, progress, f"Version {ver}")
    if got != sha:
        new.unlink(missing_ok=True)
        raise ValueError("empreinte SHA-256 incorrecte : mise à jour refusée")
    target = APP_DIR / EXE_NAME
    bat = APP_DIR / "update.bat"
    bat.write_text(
        "@echo off\r\n"
        "timeout /t 2 /nobreak >nul\r\n"
        f'taskkill /f /im "{EXE_NAME}" >nul 2>&1\r\n'
        "timeout /t 1 /nobreak >nul\r\n"
        f'move /y "{new}" "{target}" >nul\r\n'
        f'start "" "{target}" --background\r\n'
        'del "%~f0"\r\n', encoding="utf-8")
    subprocess.Popen(["cmd", "/c", str(bat)], creationflags=NO_WINDOW | 0x00000008, close_fds=True)
    log(f"Mise à jour vers la version {ver} : redémarrage")
    return f"Mise à jour vers la version {ver}…"


# ---------------------------------------------------------------------------
# Installation : copie dans %LOCALAPPDATA%\Melofinds + lancement au démarrage

def startup_file():
    return Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Melofinds PC.vbs"


def install(pairing, folder, progress=None):
    say = progress or (lambda s: None)
    parsed = parse_pairing(pairing)
    if not parsed:
        raise ValueError("Code d'appairage invalide : copie-le depuis Melofinds Web → Mon PC.")
    code, key = parsed
    root = Path(folder).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    cfg.update(code=code, cle=key, dossier=str(root.resolve()))
    cfg.setdefault("since", "12h")
    save_config(cfg)
    say("Installation des outils (une seule fois, quelques minutes)…")
    errors = ensure_tools(say)
    if WINDOWS and getattr(sys, "frozen", False):
        target = APP_DIR / EXE_NAME
        here = Path(sys.executable).resolve()
        if here != target.resolve():
            subprocess.run(["taskkill", "/f", "/im", EXE_NAME, "/fi", f"PID ne {os.getpid()}"],
                           capture_output=True, creationflags=NO_WINDOW)
            time.sleep(1)
            shutil.copyfile(here, target)
        vbs = startup_file()
        vbs.parent.mkdir(parents=True, exist_ok=True)
        vbs.write_text(f'CreateObject("Wscript.Shell").Run """{target}"" --background", 0, False\r\n', encoding="utf-8")
        subprocess.Popen([str(target), "--background"], creationflags=0x00000008, close_fds=True)
    log(f"Installé. Dossier : {root}")
    return errors


def uninstall():
    try:
        startup_file().unlink(missing_ok=True)
    except OSError:
        pass
    if WINDOWS:
        bat = Path(tempfile.gettempdir()) / "melofinds-uninstall.bat"
        bat.write_text(
            "@echo off\r\ntimeout /t 2 /nobreak >nul\r\n"
            f'taskkill /f /im "{EXE_NAME}" >nul 2>&1\r\n'
            f'rmdir /s /q "{APP_DIR}"\r\ndel "%~f0"\r\n', encoding="utf-8")
        subprocess.Popen(["cmd", "/c", str(bat)], creationflags=NO_WINDOW | 0x00000008, close_fds=True)


# ---------------------------------------------------------------------------
# Programme en arrière-plan

class SingleInstance:
    """Un seul programme en arrière-plan à la fois."""

    def __init__(self):
        APP_DIR.mkdir(parents=True, exist_ok=True)
        self.f = open(LOCKFILE, "a+")
        try:
            if WINDOWS:
                import msvcrt
                msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.ok = True
        except OSError:
            self.ok = False


def worker(once=False):
    lock = SingleInstance()
    if not lock.ok:
        log("Déjà en marche en arrière-plan.")
        return 0
    cfg = load_config()
    if not CODE_RE.match(cfg.get("code") or "") or not KEY_RE.match(cfg.get("cle") or ""):
        log("Pas encore installé : ouvre MelofindsPC et colle ton code d'appairage.")
        return 1
    root = Path(cfg["dossier"])
    root.mkdir(parents=True, exist_ok=True)
    code, key = cfg["code"], cfg["cle"]
    errors = ensure_tools()
    for e in errors:
        log(f"Outil : {e}")
    log(f"Melofinds PC {VERSION} en marche. Dossier (le seul utilisé) : {root}")
    reply(code, {"pc": "online", "version": VERSION, "dossier": str(root)})

    seen = set(cfg.get("seen", []))
    done = set(cfg.get("done", []))
    since = cfg.get("since") or "12h"
    recent = []
    last_maint = 0.0
    while True:
        try:
            HEARTBEAT.write_text(str(time.time()), encoding="utf-8")
        except OSError:
            pass
        if time.time() - last_maint > 24 * 3600 and not once:
            last_maint = time.time()
            update_ytdlp()
            try:
                if check_update():
                    log(apply_update())
            except (urllib.error.URLError, OSError, ValueError) as e:
                log(f"Vérification de mise à jour impossible : {e}")
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
                    reply(code, {"pong": msg["n"], "version": VERSION, "dossier": str(root)})
                    continue
                if msg.get("update"):
                    try:
                        found = check_update()
                        if not found:
                            reply(code, {"update": "none", "version": VERSION})
                        else:
                            reply(code, {"update": "start", "version": found[0]})
                            cfg.update(since=since, seen=list(seen)[-3000:])
                            save_config(cfg)
                            log(apply_update())
                    except (urllib.error.URLError, OSError, ValueError) as e:
                        reply(code, {"update": "error", "err": str(e)[:200]})
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
                log(f"  {'OK' if ok else 'Erreur'} : {detail}")
                if ok:
                    done.add(vid)
                hist = cfg.get("history", [])
                hist.insert(0, {"t": clean_title(msg.get("t") or vid), "ok": ok, "detail": detail, "at": int(time.time())})
                cfg["history"] = hist[:30]
                reply(code, {"v": vid, "ok": ok, "file" if ok else "err": detail})
            cfg = {**load_config(), "since": since, "seen": list(seen)[-3000:], "done": list(done)[-3000:], "history": cfg.get("history", [])}
            save_config(cfg)
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            log(f"Pas de connexion à ntfy.sh ({e}). Nouvel essai bientôt.")
            time.sleep(POLL_SECONDS)
        if once:
            return 0
        time.sleep(POLL_SECONDS)


def running():
    try:
        return time.time() - float(HEARTBEAT.read_text(encoding="utf-8")) < 90
    except (OSError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Fenêtre (installation / état)

def gui(selftest=False):
    import tkinter as tk
    from tkinter import filedialog, ttk

    root = tk.Tk()
    root.title(f"Melofinds PC {VERSION}")
    root.geometry("560x470")
    root.minsize(480, 420)
    bg, fg, accent, muted = "#0b0c10", "#f3f4f7", "#8b5cf6", "#a0a6b6"
    root.configure(bg=bg)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("TFrame", background=bg)
    style.configure("TLabel", background=bg, foreground=fg, font=("Segoe UI", 10))
    style.configure("Muted.TLabel", foreground=muted)
    style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
    style.configure("TButton", font=("Segoe UI", 10, "bold"), padding=8)
    style.configure("Accent.TButton", background=accent, foreground="#ffffff")
    style.map("Accent.TButton", background=[("active", "#7c3aed")])

    frame = ttk.Frame(root, padding=22)
    frame.pack(fill="both", expand=True)

    def clear():
        for w in frame.winfo_children():
            w.destroy()

    def setup_view():
        clear()
        cfg = load_config()
        ttk.Label(frame, text="Installer Melofinds PC", style="Title.TLabel").pack(anchor="w")
        ttk.Label(frame, text="Les prods envoyées depuis ton téléphone arriveront ici en .wav,\nmême quand tu es loin (5G ou Wi-Fi).", style="Muted.TLabel").pack(anchor="w", pady=(4, 16))
        ttk.Label(frame, text="1. Code d'appairage (Melofinds Web → Mon PC → Copier)").pack(anchor="w")
        pair = tk.StringVar(value="")
        e = ttk.Entry(frame, textvariable=pair, font=("Consolas", 10))
        e.pack(fill="x", pady=(4, 14))
        ttk.Label(frame, text="2. Dossier où arrivent les prods (le seul utilisé)").pack(anchor="w")
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(4, 14))
        folder = tk.StringVar(value=cfg.get("dossier") or default_folder())
        ttk.Entry(row, textvariable=folder).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Choisir…", command=lambda: folder.set(filedialog.askdirectory(initialdir=folder.get()) or folder.get())).pack(side="left", padx=(8, 0))
        status = tk.StringVar(value="")
        ttk.Label(frame, textvariable=status, style="Muted.TLabel", wraplength=500).pack(anchor="w", pady=(4, 10))
        btn = ttk.Button(frame, text="Installer", style="Accent.TButton")
        btn.pack(anchor="w")

        def go():
            if not parse_pairing(pair.get()):
                status.set("Ce code n'est pas valide. Dans Melofinds Web → Mon PC, touche « Copier » et colle-le ici.")
                return
            btn.state(["disabled"])

            def work():
                try:
                    errs = install(pair.get(), folder.get(), lambda s: root.after(0, status.set, s))
                    root.after(0, lambda: done_view(errs))
                except Exception as ex:  # affiché à l'utilisateur
                    root.after(0, status.set, f"Erreur : {ex}")
                    root.after(0, lambda: btn.state(["!disabled"]))
            threading.Thread(target=work, daemon=True).start()
        btn.configure(command=go)
        e.focus_set()

    def done_view(errs):
        clear()
        ttk.Label(frame, text="C'est prêt ✓" if not errs else "Installé, avec un souci", style="Title.TLabel").pack(anchor="w")
        txt = ("Melofinds PC tourne en arrière-plan et se lancera tout seul à chaque démarrage.\n"
               "Dans l'app, touche « Tester la connexion », puis ⬇ sur une prod.\n\nTu peux fermer cette fenêtre.")
        if errs:
            txt = "Certains outils n'ont pas pu être installés :\n- " + "\n- ".join(errs) + "\n\nVérifie ta connexion puis relance MelofindsPC."
        ttk.Label(frame, text=txt, wraplength=500).pack(anchor="w", pady=12)
        ttk.Button(frame, text="Fermer", command=root.destroy).pack(anchor="w")

    def status_view():
        clear()
        cfg = load_config()
        ttk.Label(frame, text="Melofinds PC", style="Title.TLabel").pack(anchor="w")
        state = tk.StringVar()
        ttk.Label(frame, textvariable=state).pack(anchor="w", pady=(6, 2))
        ttk.Label(frame, text=f"Dossier : {cfg.get('dossier', '')}", style="Muted.TLabel", wraplength=500).pack(anchor="w")
        ttk.Label(frame, text=f"Version {VERSION}", style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        lst = tk.Listbox(frame, height=8, bg="#15171d", fg=fg, highlightthickness=0, borderwidth=0, font=("Segoe UI", 10))
        lst.pack(fill="both", expand=True, pady=(0, 10))
        for h in cfg.get("history", [])[:30]:
            lst.insert("end", f"{'✓' if h.get('ok') else '✗'}  {h.get('detail') if h.get('ok') else h.get('t', '') + ' — ' + str(h.get('detail', ''))}")
        if not cfg.get("history"):
            lst.insert("end", "Aucune prod reçue pour l'instant.")
        msg = tk.StringVar()
        ttk.Label(frame, textvariable=msg, style="Muted.TLabel", wraplength=500).pack(anchor="w")
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(8, 0))

        def open_folder():
            p = cfg.get("dossier")
            if p and WINDOWS:
                os.startfile(p)  # noqa: S606 (dossier choisi par l'utilisateur)

        def start():
            if WINDOWS and getattr(sys, "frozen", False):
                subprocess.Popen([str(APP_DIR / EXE_NAME), "--background"], creationflags=0x00000008, close_fds=True)
                msg.set("Démarré.")

        def upd():
            def work():
                try:
                    r = apply_update(lambda s: root.after(0, msg.set, s))
                except Exception as ex:
                    r = f"Mise à jour impossible : {ex}"
                root.after(0, msg.set, r)
            msg.set("Recherche d'une mise à jour…")
            threading.Thread(target=work, daemon=True).start()

        def remove():
            uninstall()
            msg.set("Désinstallé. Tes prods restent dans ton dossier.")
            root.after(1500, root.destroy)

        ttk.Button(row, text="Ouvrir le dossier", command=open_folder).pack(side="left")
        ttk.Button(row, text="Mettre à jour", command=upd).pack(side="left", padx=6)
        ttk.Button(row, text="Changer le code / dossier", command=setup_view).pack(side="left")
        ttk.Button(row, text="Démarrer", command=start).pack(side="left", padx=6)
        ttk.Button(frame, text="Désinstaller", command=remove).pack(anchor="e", pady=(8, 0))

        def tick():
            state.set("● En marche — prêt à recevoir des prods" if running() else "○ Arrêté (clique sur « Démarrer »)")
            if frame.winfo_exists():
                root.after(3000, tick)
        tick()

    if CODE_RE.match(load_config().get("code") or ""):
        status_view()
    else:
        setup_view()
    if selftest:
        root.update()
        setup_view()
        root.update()
        status_view()
        root.update()
        root.destroy()
        return
    root.mainloop()


# ---------------------------------------------------------------------------

def selftest(out):
    """Vérification automatique (construction du programme sur GitHub)."""
    res = {"version": VERSION, "frozen": bool(getattr(sys, "frozen", False))}
    res["tool_errors"] = ensure_tools()
    for name, args in (("yt-dlp.exe", ["--version"]), ("ffmpeg.exe", ["-version"]), ("deno.exe", ["--version"])):
        p = tool_path(name)
        try:
            r = run_tool([p, *args], 120) if p else None
            res[name] = last_line(r.stdout)[:80] if r and r.returncode == 0 else "absent"
        except (OSError, subprocess.SubprocessError) as e:
            res[name] = f"erreur {e}"
    res["name"] = build_name('[FREE FOR PROFIT] Luther Type Beat "TREE"', "F# min", 140)
    vid = os.environ.get("MELOFINDS_TEST_VIDEO", "")
    if VIDEO_ID.match(vid):  # vrai téléchargement (informatif : YouTube bloque souvent les serveurs)
        with tempfile.TemporaryDirectory(prefix="melofinds-test-") as d:
            ok, detail = download(vid, d, {})
            res["download"] = {"ok": ok, "detail": detail, "files": [p.name for p in Path(d).iterdir()]}
    try:
        gui(selftest=True)
        res["gui"] = "ok"
    except Exception as e:  # Tk absent ou cassé
        res["gui"] = f"erreur {e}"
    res["ok"] = not res["tool_errors"] and all(res[n] not in ("absent",) for n in ("yt-dlp.exe", "ffmpeg.exe", "deno.exe")) and res["gui"] == "ok"
    Path(out).write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if res["ok"] else 1


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Melofinds PC : reçoit les prods envoyées depuis Melofinds Web.")
    ap.add_argument("--background", action="store_true", help="tourner en arrière-plan (lancé au démarrage)")
    ap.add_argument("--pair", help="code d'appairage (installation sans fenêtre)")
    ap.add_argument("--dossier", help="dossier des prods (installation sans fenêtre)")
    ap.add_argument("--une-fois", action="store_true", help="vérifier une fois puis quitter (test)")
    ap.add_argument("--selftest", metavar="FICHIER", help="vérification automatique")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest(args.selftest)
    if args.pair:
        errs = install(args.pair, args.dossier or load_config().get("dossier") or default_folder(), log)
        for e in errs:
            log(f"Outil : {e}")
        if not WINDOWS or not getattr(sys, "frozen", False):
            return worker(once=args.une_fois)
        return 0
    if args.background or args.une_fois:
        return worker(once=args.une_fois)
    try:
        gui()
    except ImportError:
        log("Pas d'interface graphique : utilise --pair CODE puis --background.")
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        pass
