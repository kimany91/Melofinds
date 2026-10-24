"""Melofinds PC — cœur : noms de fichiers, envois signés, outils, téléchargement en
WAV, mises à jour. Utilisé par le programme en arrière-plan et par les fenêtres.

Sécurité :
  - chaque envoi est signé avec la clé secrète de l'appareil (HMAC-SHA256) ; la clé
    ne passe jamais par ntfy. Envoi non signé, modifié, rejoué ou de plus de 48 h : ignoré ;
  - un envoi ne contient qu'un identifiant de vidéo YouTube : jamais de lien,
    de chemin, de fichier ou de commande ;
  - téléchargement et conversion dans un dossier temporaire : seul un vrai .wav
    (en-tête RIFF/WAVE vérifié) entre dans le dossier des prods, choisi sur le PC ;
  - mise à jour : seulement depuis github.com/kimany91/Melofinds/releases, avec
    empreinte SHA-256 vérifiée ; les outils aussi quand l'éditeur publie une empreinte.
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

VERSION = "3.4.0"
REPO = "kimany91/Melofinds"
RELEASES = f"https://github.com/{REPO}/releases"
MANIFEST_URL = f"{RELEASES}/latest/download/version.json"
NTFY = os.environ.get("MELOFINDS_NTFY", "https://ntfy.sh").rstrip("/")
POLL_SECONDS = int(os.environ.get("MELOFINDS_POLL", "15"))
WINDOWS = os.name == "nt"
NO_WINDOW = 0x08000000 if WINDOWS else 0  # pas de fenêtre noire pour les outils
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
# Emplacement des fichiers du programme (choisi à l'installation)

LEGACY_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Melofinds"
DEFAULT_INSTALL = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Programs" / "Melofinds"
MARKER = ".melofinds-install"


class Paths:
    """Fichiers du programme : config.json (réglages), state.json (suivi),
    tools/ (yt-dlp, ffmpeg, Deno), journal, battement de cœur, verrou."""

    def __init__(self, d=None):
        self.set(d)

    def set(self, d):
        self.dir = Path(d) if d else None
        self.base = self.dir or Path(tempfile.gettempdir()) / "melofinds-sans-installation"
        b = self.base
        self.config, self.state, self.log = b / "config.json", b / "state.json", b / "melofinds.log"
        self.heartbeat, self.lock, self.pid, self.stop = b / "heartbeat", b / "worker.lock", b / "worker.pid", b / "stop"
        self.tools = b / "tools"
        self.progress = b / "progress.json"  # téléchargement en cours (affiché par le panneau)
        return self


P = Paths()


def registry_install_dir():
    if not WINDOWS:
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Melofinds") as k:
            return winreg.QueryValueEx(k, "InstallDir")[0]
    except OSError:
        return None


def _writable(d):
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".melofinds-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def resolve_install_dir():
    """Où le programme range ses fichiers (réglages, outils, journal) : son propre dossier
    d'installation (choisi dans l'installateur), sinon un dossier à toi dans AppData."""
    if not WINDOWS:
        return Path(os.environ.get("MELOFINDS_HOME") or Path.home() / ".melofinds")
    if getattr(sys, "frozen", False):
        here = Path(sys.executable).resolve().parent
        return here if _writable(here) else LEGACY_DIR / "data"
    return Path(os.environ.get("MELOFINDS_HOME") or LEGACY_DIR / "dev")


def previous_install_dirs():
    """Anciennes installations (2.x, 3.0) dont on reprend les réglages."""
    out = []
    r = registry_install_dir()
    if r:
        out.append(Path(r))
    out.append(LEGACY_DIR)
    return [d for d in out if (d / "config.json").exists()]


# ---------------------------------------------------------------------------
# Journal, réglages

def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    try:
        print(line, flush=True)
    except (OSError, ValueError, AttributeError):
        pass  # pas de console (programme fenêtré)
    try:
        P.base.mkdir(parents=True, exist_ok=True)
        if P.log.exists() and P.log.stat().st_size > 2_000_000:
            P.log.replace(P.log.with_suffix(".old.log"))
        with open(P.log, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _read_json(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path, data, private=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    if private:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def load_config():
    """Réglages (écrits par le panneau de gestion) : dossier, appareils, démarrage auto."""
    cfg = _read_json(P.config)
    # Migration 2.x : un seul appareil (code + clé à la racine) → liste d'appareils
    if "devices" not in cfg and CODE_RE.match(cfg.get("code") or "") and KEY_RE.match(cfg.get("cle") or ""):
        cfg["devices"] = [{"id": "d1", "name": "Mon téléphone", "code": cfg["code"], "cle": cfg["cle"], "added": int(time.time())}]
        st = _read_json(P.state)
        if not st:
            st = {"since": {cfg["code"]: cfg.get("since") or "12h"}, "seen": cfg.get("seen", []), "done": cfg.get("done", []), "history": cfg.get("history", [])}
            _write_json(P.state, st)
        for k in ("code", "cle", "since", "seen", "done", "history"):
            cfg.pop(k, None)
        _write_json(P.config, cfg, private=True)
    cfg.setdefault("devices", [])
    cfg["devices"] = [d for d in cfg["devices"] if isinstance(d, dict) and CODE_RE.match(d.get("code") or "") and KEY_RE.match(d.get("cle") or "")]
    return cfg


def save_config(cfg):
    _write_json(P.config, cfg, private=True)


def load_state():
    """Suivi (écrit par le programme en arrière-plan) : envois lus, prods reçues, appareils vus."""
    st = _read_json(P.state)
    st.setdefault("since", {})
    st.setdefault("seen", [])
    st.setdefault("done", [])
    st.setdefault("history", [])
    st.setdefault("devices", {})
    return st


def received_file(st, cfg, vid, root):
    """Fichier .wav déjà reçu pour cette vidéo, s'il est encore dans le dossier (en suivant
    les renommages faits depuis le panneau). None sinon : il faut la retélécharger."""
    name = (st.get("files") or {}).get(vid)
    renamed = cfg.get("renamed") or {}
    for _ in range(50):
        if not name:
            return None
        p = Path(root) / name
        if p.is_file():
            return p
        name = renamed.get(name)
    return None


def save_state(st):
    _write_json(P.state, st)


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


def licence_tag(lic, limit=None):
    """Licence lue par l'app → étiquette du nom de fichier :
    free for profit [FFP] · free [F] · free for profit limité [FFP, UPTO 5000]."""
    lic = str(lic or "")
    if lic == "ffp":
        return "FFP"
    if lic == "fnp":
        return "F"
    if lic == "upto":
        try:
            n = int(limit)
        except (TypeError, ValueError):
            n = 0
        return f"FFP, UPTO {n}" if 0 < n < 10**10 else "FFP, UPTO"
    return None  # payant / inconnu : pas d'étiquette


def build_name(title, key=None, bpm=None, lic=None, limit=None):
    tags = [x for x in (key, f"{bpm} BPM" if bpm else None) if x]
    base = clean_title(title)[:110].rstrip(" -,.")
    name = f"{base} [{', '.join(tags)}]" if tags else base
    lt = licence_tag(lic, limit)
    if lt:
        name = f"{name} [{lt}]"
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
    local = P.tools / name
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
    P.tools.mkdir(parents=True, exist_ok=True)
    for name, src in TOOL_SOURCES.items():
        if (P.tools / name).exists():
            continue
        old = LEGACY_DIR / "tools" / name
        if old.exists() and old.resolve() != (P.tools / name).resolve():
            try:
                shutil.copyfile(old, P.tools / name)
                for extra in src.get("extract", []):
                    if (LEGACY_DIR / "tools" / extra).exists() and not (P.tools / extra).exists():
                        shutil.copyfile(LEGACY_DIR / "tools" / extra, P.tools / extra)
                continue
            except OSError:
                pass
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
                                with z.open(member) as fi, open(P.tools / base, "wb") as fo:
                                    shutil.copyfileobj(fi, fo)
                except zipfile.BadZipFile:
                    errors.append(f"{name} : archive abîmée")
                    continue
            else:
                shutil.copyfile(dest, P.tools / name)
        if not (P.tools / name).exists():
            errors.append(f"{name} : introuvable après installation")
    return errors


def tool_env():
    env = dict(os.environ)
    env["PATH"] = str(P.tools) + os.pathsep + env.get("PATH", "")  # yt-dlp y trouve Deno et ffmpeg
    return env


def run_tool(args, timeout):
    return subprocess.run(args, capture_output=True, timeout=timeout, env=tool_env(),
                          creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)


def stream_tool(args, timeout, on_line):
    """Lance un outil et passe chaque ligne de sortie à on_line (progression en direct).
    Renvoie (code de sortie, dernières lignes)."""
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=tool_env(),
                            creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    timer = threading.Timer(timeout, proc.kill)
    timer.start()
    tail = []
    try:
        for raw in iter(proc.stdout.readline, b""):
            line = decode(raw).strip()
            if not line:
                continue
            on_line(line)
            if "MFPCT" not in line:
                tail = (tail + [line])[-20:]
        proc.wait()
    finally:
        timer.cancel()
        if proc.poll() is None:
            proc.kill()
    return proc.returncode, tail


def update_ytdlp():
    exe = P.tools / "yt-dlp.exe"
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


def download(video_id, root, info, out=None, progress=None):
    """Télécharge la prod en .wav dans root. progress(étape, pourcentage) : « info »,
    « download » (0-100), « convert »."""
    step = progress or (lambda *_: None)
    ytdlp = tool_path("yt-dlp.exe")
    ffmpeg = tool_path("ffmpeg.exe")
    if not ytdlp:
        return False, "yt-dlp manquant (relance l'installation)"
    if not ffmpeg:
        return False, "ffmpeg manquant : impossible de faire un WAV"
    url = f"https://www.youtube.com/watch?v={video_id}"
    step("info", None)

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
    final = unique_path(root, build_name(meta.get("title") or info.get("t") or video_id, key, bpm, info.get("lic"), info.get("limit")))
    if not inside(final, root) or final.suffix.lower() != ".wav":
        return False, "nom de fichier refusé"

    # 2) Téléchargement + conversion dans un dossier temporaire, hors de ton dossier.
    with tempfile.TemporaryDirectory(prefix="melofinds-") as tmp:
        args = [ytdlp, "--no-playlist", "--no-warnings", "--progress", "--newline", "--no-mtime",
                "--progress-template", "download:MFPCT %(progress._percent_str)s",
                "-f", "bestaudio/best", "-x", "--audio-format", "wav",
                "--ffmpeg-location", str(Path(ffmpeg).parent),
                "--max-filesize", "200M", "-P", f"home:{tmp}", "-P", f"temp:{tmp}",
                "-o", "audio.%(ext)s", url]
        step("download", 0)

        def on_line(line):
            m = re.search(r"MFPCT\s*([\d.]+)%", line)
            if m:
                step("download", min(100.0, float(m.group(1))))
            elif "[ExtractAudio]" in line or "Destination:" in line and line.endswith(".wav"):
                step("convert", None)
        try:
            code, tail = stream_tool(args, 900, on_line)
        except (OSError, subprocess.SubprocessError) as e:
            return False, f"yt-dlp : {e}"
        if code != 0:
            errs = [l for l in tail if "ERROR" in l]
            return False, ((errs or tail or ["erreur inconnue"])[-1])[:200]
        step("convert", None)
        wavs = [p for p in Path(tmp).iterdir() if p.suffix.lower() == ".wav" and is_wav(p)]
        if not wavs:
            return False, "la conversion en WAV a échoué"
        # 3) Seul le .wav vérifié entre dans ton dossier.
        shutil.move(str(wavs[0]), str(final))
    if not is_wav(final):
        final.unlink(missing_ok=True)
        return False, "fichier non WAV supprimé"
    if out is not None:  # pour FLmake
        out.update(path=str(final), key=key, bpm=bpm, title=clean_title(meta.get("title") or info.get("t") or video_id))
    return True, final.name


# ---------------------------------------------------------------------------
# Mise à jour du programme (uniquement depuis les versions officielles)

def check_update():
    """Renvoie (version, url de l'installateur, sha256) si une version plus récente existe."""
    data = json.loads(http_get(MANIFEST_URL, timeout=20).decode("utf-8-sig"))
    ver = str(data.get("version", ""))
    url = str(data.get("setup_url") or data.get("url") or "")
    sha = str(data.get("setup_sha256") or data.get("sha256") or "").lower()
    if not url.startswith(f"{RELEASES}/download/") or not re.fullmatch(r"[a-f0-9]{64}", sha):
        raise ValueError("fichier de version invalide")
    if version_tuple(ver) <= version_tuple(VERSION):
        return None
    return ver, url, sha


def apply_update(progress=None):
    """Télécharge le nouvel installateur officiel, vérifie son empreinte et le lance en
    mode silencieux dans le même dossier : il arrête proprement le programme, remplace
    les fichiers et le remet en ligne. Renvoie un message."""
    if not getattr(sys, "frozen", False) or not WINDOWS:
        return "Mise à jour automatique : seulement pour la version installée sur Windows."
    found = check_update()
    if not found:
        return f"Déjà à jour (version {VERSION})."
    ver, url, sha = found
    folder = P.base / "updates"
    folder.mkdir(parents=True, exist_ok=True)
    setup = folder / f"MelofindsSetup-{re.sub(r'[^0-9.]', '', ver)}.exe"
    got = download_file(url, setup, progress, f"Version {ver}")
    if got != sha:
        setup.unlink(missing_ok=True)
        raise ValueError("empreinte SHA-256 incorrecte : mise à jour refusée")
    app_dir = Path(sys.executable).resolve().parent
    subprocess.Popen([str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", f"/DIR={app_dir}"],
                     creationflags=0x00000008, close_fds=True)
    log(f"Mise à jour vers la version {ver} lancée")
    return f"Mise à jour vers la version {ver}…"


class SingleInstance:
    """Un seul programme en arrière-plan à la fois."""

    def __init__(self):
        P.base.mkdir(parents=True, exist_ok=True)
        self.f = open(P.lock, "a+")
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



def running():
    try:
        return time.time() - float(P.heartbeat.read_text(encoding="utf-8")) < 45
    except (OSError, ValueError):
        return False

