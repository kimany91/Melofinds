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
import http.client
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

VERSION = "3.17.0"
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
        self.kick = b / "kick"  # le panneau a changé un projet : le programme en ligne prévient l'app tout de suite
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


def projects_root(cfg):
    """Le dossier des projets : chaque prod reçue y arrive dans son propre dossier
    (« Nom/Nom.wav », et « Nom/Nom.flp » avec FLmake)."""
    fm = cfg.get("flmake") if isinstance(cfg.get("flmake"), dict) else {}
    return Path(fm.get("dossier") or cfg.get("dossier") or default_folder())


def follow_renames(path, renamed):
    """Chemin après les renommages faits depuis le panneau (fichier ou dossier parent)."""
    p = str(path)
    for _ in range(50):
        nxt = None
        for old, new in renamed.items():
            o = old.rstrip("\\/")
            if p.lower() == o.lower():
                nxt = new
            elif Path(p).name == old and not any(c in old for c in "\\/"):  # anciennes versions : nom seul
                nxt = str(Path(p).with_name(new))
            else:
                for sep in ("\\", "/"):
                    if p.lower().startswith(o.lower() + sep):
                        nxt = new.rstrip("\\/") + sep + p[len(o) + 1:]
                        break
            if nxt:
                break
        if not nxt or nxt == p:
            return Path(p)
        p = nxt
    return Path(p)


def received_file(st, cfg, vid, roots):
    """Fichier .wav déjà reçu pour cette vidéo, s'il est encore là (en suivant les
    renommages faits depuis le panneau). None sinon : il faut la retélécharger."""
    name = (st.get("files") or {}).get(vid)
    if not name:
        return None
    roots = [roots] if isinstance(roots, (str, Path)) else roots
    renamed = cfg.get("renamed") or {}
    cands = [Path(name)] if Path(name).is_absolute() else [Path(r) / name for r in roots]
    for c in cands:
        if c.is_file():
            return c
        p = follow_renames(c, renamed)
        if p.is_file():
            return p
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


# ---------------------------------------------------------------------------
# Deuxième vérification de la licence, sur le PC, avec la description COMPLÈTE lue par
# yt-dlp. L'app juge parfois sur le titre seul (YouTube lui a caché la description) :
# « [FREE FOR PROFIT] » dans le titre mais « SoundCloud and YT ONLY » / « a license must be
# purchased for Spotify » dans la description → la prod est rangée en [F], jamais en [FFP].

def _lic_norm(text):
    t = unicodedata.normalize("NFKC", str(text or ""))
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = t.replace("’", "'").replace("‘", "'")
    return re.sub(r"\b(etc|e\.g|i\.e|ex|vs)\.+", lambda m: m.group(0).replace(".", " "), t)


_PLAT = r"(?:youtube|yt|soundcloud|soudcloud|souncloud|sondcloud|soundclound|soundclod|sc|tiktok|tik\s*tok|instagram|insta|reels?|twitch|facebook|social\s*media)"
_PLAT_LIST = rf"{_PLAT}(?:\s*(?:,|and|&|/|\+|or|et|ou|n)\s*{_PLAT})*"
_FFP_RE = re.compile(r"(?:free|fr33|gratuit)\s*[-_]?\s*(?:to\s*use\s*)?(?:for|4|pour)?\s*[-_]?\s*(?:profit|commercial)\b|\bffp\b|\bf4p\b")
_LIC_ONLY = [
    re.compile(rf"\b{_PLAT_LIST}\s*\(?\s*(?:(?:non[\s-]*moneti[sz]ed\s*)?(?:use|usage|videos?|uploads?|placements?|content|moneti[sz]\w*)\s*)?\)?\s*[\"']?\s*(?:only|uniquement|seulement)\b"),
    re.compile(rf"(?:only|uniquement|seulement|exclusivement)\s*(?:be\s*)?(?:applies\s*to|apply\s*to|allowed\s*(?:on|for)|valid\s*(?:on|for)|use(?:\s*(?:it|this|the\s*beat))?(?:\s*for\s*profit)?\s*(?:on|for|in)|for|on|in|sur|pour|en)\s*(?:non[\s-]*moneti[sz]ed\s*)?{_PLAT_LIST}\b"),
    re.compile(r"\bnot\s*(?:free\s*)?(?:for\s*profit\s*)?(?:for|on|to)\s*(?:all\s*plat\w*|spotify|streaming|apple\s*music|dsps?|other\s*plat\w*)"),
    re.compile(r"\b(?:not|n'?est\s*pas)\s*(?:free\s*for\s*profit|ffp)\b"),
    re.compile(r"(?:spotify|streaming|apple\s*music|dsps?|distribution|plateformes?)\s*[:\-=]?\s*(?:❌|✖|✗|⛔|\U0001f6ab|no\b|non\b|not\s*(?:allowed|permitted))"),
]
_LIC_PLATFREE = re.compile(rf"(?:(?:free|gratuit\w*)\s*(?:for|4)?\s*(?:profit\s*)?(?:to\s*use\s*)?(?:use\s*)?(?:(?:on|for|in|sur|pour)\s*(?:the\s*)?|[(\[]\s*)){_PLAT_LIST}\b")
_LIC_NONPROFIT = re.compile(r"\bnon\s*-?\s*(?:profit|commercial\w*|commerciaux|lucrati\w*)\b")
_LIC_BROAD = re.compile(r"spotify|apple\s*music|itunes|deezer|tidal|amazon\s*music|all\s*plat\w*|toutes?\s*les\s*plateformes|streaming|dsps?\b|distrib")
_LIC_RESTRICT_WORDS = re.compile(r"\bonly\b|uniquement|seulement|\bnot\b|n't|\bno\b|\bpas\b|purchase|\bbuy|lease|licen[cs]e|\bneed|\bmust|\bpay|acheter|payer|sauf|except")
_LIC_REQ = [
    re.compile(r"(?:licen[cs]e|lease|beat)\s*(?:must|has\s*to|have\s*to|needs?\s*to|should|is\s*to)\s*be\s*(?:purchased|bought|acquired|obtained|leased)"),
    re.compile(r"(?:licen[cs]e|lease)\s*(?:is\s*)?(?:required|needed|necessary|mandatory)"),
    re.compile(r"\b(?:purchase|buy|grab|get|acquire)\s*(?:a|an|the|my|this|our)?\s*(?:paid\s*)?(?:lease|licen[cs]e|beat)\b"),
    re.compile(r"\bpaid\s*(?:lease|licen[cs]e)\b|(?:=|->|→)\s*(?:a\s*)?(?:lease|licen[cs]e)\b"),
    re.compile(r"\b(?:must|need(?:s)?(?:\s*to)?|have\s*to|has\s*to|will\s*need\s*to|gotta|required\s*to|please)\s*(?:to\s*)?(?:purchase|buy|lease|pay|acquire)\b"),
    re.compile(r"(?:veuillez|merci\s*d'?|vous\s*devez|tu\s*dois|il\s*faut|faut|obligation\s*d'?)\s*(?:l'?\s*)?(?:acheter|payer|louer|prendre\s*une\s*licence)"),
    re.compile(r"achat\s*(?:d'?\s*une\s*|de\s*(?:la\s*)?)?(?:licence\s*)?obligatoire"),
]
_LIC_TARGET = re.compile(r"spotify|apple\s*music|itunes|deezer|tidal|amazon\s*music|stre+aming|all\s*plat\w*|other\s*plat\w*|any\s*plat\w*|plateformes?|dsps?\b|distrib\w*|distrokid|tunecore|for\s*profit|commercial\w*|moneti[sz]\w*|monetis\w*|lucrati\w*|any\s*(?:other\s*)?use|toutes?\s*autres?\s*utilisations?|toute\s*utilisation")
_LIC_SOFT = re.compile(r"recommend|recommande|optional|optionnel|to\s*be\s*(?:100\s*%\s*)?(?:safe|sure)|support\s*(?:me|the\s*channel)")
_LIC_NO_NEED = re.compile(r"no\s*(?:need|lease|licen[cs]e)|without\s*(?:a\s*)?(?:lease|licen[cs]e|buying|paying)|don'?t\s*(?:need|have)\s*to|pas\s*besoin|sans\s*(?:pay|achet|licen|rien\s*payer)|not\s*required")
_LIC_SENT = re.compile(r"[^.!?\n•▷○|]+")


def licence_restriction(text):
    """Phrase de la description qui interdit Spotify & co sans payer, ou None."""
    t = _lic_norm(text)
    for rx in _LIC_ONLY:
        m = rx.search(t)
        if m and not re.search(r"\bnot\s*$", t[max(0, m.start() - 6):m.start()]):
            return m.group(0)
    for m in _LIC_PLATFREE.finditer(t):
        sent = next((s.group(0) for s in _LIC_SENT.finditer(t) if s.start() <= m.start() < s.end()), m.group(0))
        if not (_LIC_BROAD.search(sent) and not _LIC_RESTRICT_WORDS.search(sent)):
            return m.group(0)
    for m in _LIC_NONPROFIT.finditer(t):
        before = t[max(0, m.start() - 22):m.start()]
        after = t[m.end():m.end() + 22]
        if re.search(r"(?:profit|commercial|lucratif)\s*(?:or|and|&|/|ou|et)\s*(?:for\s*|pour\s*)?$", before):
            continue
        if re.match(r"\s*(?:or|and|&|/|ou|et)\s*(?:for\s*|pour\s*)?(?:profit|commercial|lucratif)", after):
            continue
        return m.group(0)
    for s in _LIC_SENT.finditer(t):
        sent = s.group(0)
        if not _LIC_TARGET.search(sent) or _LIC_SOFT.search(sent) or _LIC_NO_NEED.search(sent):
            continue
        for rx in _LIC_REQ:
            m = rx.search(sent)
            if m:
                return sent.strip()[:160]
    return None


def check_licence(title, desc, lic, limit=None):
    """Licence envoyée par l'app, revue avec la description complète → (licence, limite, raison).
    Ne rend jamais une prod plus « libre » que l'app ne l'a dit, sauf une prod que l'app n'a
    pas pu lire (licence inconnue) et que la description dit clairement free for profit."""
    lic = str(lic or "")
    desc = str(desc or "")
    if not desc.strip() or lic in ("fnp", "paid"):
        return lic, limit, None
    why = licence_restriction(desc)
    if why and lic in ("ffp", "upto", "unknown", ""):
        return "fnp", None, why
    if lic in ("unknown", "") and not why:
        d = _lic_norm(desc)
        if _FFP_RE.search(d) and not re.search(r"up\s*-?\s*to|\bmax|limit|\bfirst\s*\d|after\s*\d|streams?\b", d):
            return "ffp", None, "free for profit dans la description"
    return lic, limit, None


def build_name(title, key=None, bpm=None, lic=None, limit=None, tb_key=False, tb_bpm=False):
    """« Titre [C# min, 150 BPM] [FFP] ». Ce que Tunebat a trouvé va dans son propre groupe :
    « Titre [C# min] [TB 150 BPM] », « Titre [TB C# min, 150 BPM] »."""
    own = [x for x, tb in ((key, tb_key), (f"{bpm} BPM" if bpm else None, tb_bpm)) if x and not tb]
    found = [x for x, tb in ((key, tb_key), (f"{bpm} BPM" if bpm else None, tb_bpm)) if x and tb]
    base = clean_title(title)[:110].rstrip(" -,.")
    name = f"{base} [{', '.join(own)}]" if own else base
    if found:
        name = f"{name} [TB {', '.join(found)}]"
    lt = licence_tag(lic, limit)
    if lt:
        name = f"{name} [{lt}]"
    if re.fullmatch(r"(?i)(con|prn|aux|nul|com\d|lpt\d)(\s.*)?", name):
        name = f"Prod {name}"
    return name.rstrip(" .") or "Prod"


# ---------------------------------------------------------------------------
# Tunebat : clé et BPM des prods sorties sur Spotify (même logique que l'app web,
# src/core/tunebat.js). On ne garde un résultat que s'il correspond vraiment à la vidéo.

TB_SEARCH = "https://api.tunebat.com/api/tracks/search?term="


def tb_norm(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower().replace("$", "s")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def similarity(a, b):
    """Ressemblance de deux textes (coefficient de Dice sur les paires de lettres), 0 à 1."""
    a, b = tb_norm(a).replace(" ", ""), tb_norm(b).replace(" ", "")
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if len(a) < 2 or len(b) < 2:
        return 0.0
    pairs = {}
    for i in range(len(a) - 1):
        pairs[a[i:i + 2]] = pairs.get(a[i:i + 2], 0) + 1
    hit = 0
    for i in range(len(b) - 1):
        p = b[i:i + 2]
        if pairs.get(p, 0) > 0:
            pairs[p] -= 1
            hit += 1
    return 2 * hit / (len(a) + len(b) - 2)


_TB_NOISE = re.compile(r"\b(free|for profit|ffp|type beat|typebeat|instrumental|instru|beat|prod(?:uced)? by|prod\.?|\d{4}|hard|sad|dark|melodic|new|x)\b", re.I)
_TB_BRACKETS = re.compile(r"[\[(【][^\])】]*[\])】]")


def beat_name(title):
    """Nom de la prod : le texte entre guillemets (« "HAZE" »), sinon le titre nettoyé."""
    t = str(title or "")
    m = re.search(r'["“”«»]([^"“”«»]{2,60})["“”«»]', t) or re.search(r"(?:^|\W)'([^']{2,40})'(?!\w)", t)
    if m:
        return m.group(1).strip()
    t = _TB_NOISE.sub(" ", _TB_BRACKETS.sub(" ", t))
    return re.sub(r"\s{2,}", " ", re.sub(r"[|\-–—:]+", " ", t)).strip()


def tb_queries(title, channel):
    """Recherches à faire sur Tunebat (2 au plus : Tunebat limite le nombre de requêtes)."""
    name = beat_name(title)
    ch = re.sub(r"(?i)\s*(beats?|prod|music|- topic)$", "", str(channel or "")).strip()
    out = []
    for q in (f"{name} {ch}" if name and ch else "", name, _TB_BRACKETS.sub(" ", str(title or "")).strip()):
        k = tb_norm(q)
        if len(k) >= 3 and all(tb_norm(x) != k for x in out):
            out.append(q.strip())
    return out[:2]


def tb_key(k):
    """Clé Tunebat (« A♯ minor », « D Major ») → « A# min » / « D maj »."""
    m = re.match(r"^\s*([A-Ga-g])\s*(#|b)?\s*(major|minor|maj|min)", str(k or "").replace("♯", "#").replace("♭", "b"), re.I)
    if not m:
        return None
    return f"{m.group(1).upper()}{m.group(2) or ''} {'maj' if m.group(3).lower().startswith('maj') else 'min'}"


def tb_pick(items, title, channel, duration):
    """Choisit le résultat Tunebat qui correspond à la vidéo, ou None (jamais de faux BPM)."""
    name, ch = beat_name(title), tb_norm(channel)
    try:
        dur = float(duration or 0)
    except (TypeError, ValueError):
        dur = 0.0
    best = None
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        n = str(it.get("n") or "")
        artists = [str(a) for a in it.get("as")] if isinstance(it.get("as"), list) else []
        contains = 0.8 if name and len(tb_norm(name)) >= 4 and tb_norm(name) in tb_norm(n) else 0
        score_name = max(similarity(n, name), similarity(n, title), contains)
        artist_ok = bool(ch) and any(len(tb_norm(a)) >= 3 and (similarity(a, ch) >= 0.8 or tb_norm(a) in ch or ch in tb_norm(a)) for a in artists)
        try:
            d = float(it.get("d") or 0) / 1000
        except (TypeError, ValueError):
            d = 0.0
        dur_ok = dur > 0 and d > 0 and abs(d - dur) <= 4
        if not ((artist_ok and score_name >= 0.6) or (dur_ok and score_name >= 0.5) or (artist_ok and dur_ok)):
            continue
        try:
            bpm = valid_bpm(round(float(it.get("b"))))
        except (TypeError, ValueError, OverflowError):
            bpm = None
        key = valid_key(tb_key(it.get("k")))
        if not bpm and not key:
            continue
        score = score_name + artist_ok + dur_ok
        if not best or score > best[0]:
            best = (score, {"bpm": bpm, "key": key, "name": n, "artists": artists})
    return best[1] if best else None


def tunebat_lookup(title, channel, duration, timeout=10):
    """Cherche la clé et le BPM sur Tunebat. Renvoie {"bpm", "key"} ou None (rien / hors ligne)."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36",
               "Accept": "application/json", "Origin": "https://tunebat.com", "Referer": "https://tunebat.com/"}
    for q in tb_queries(title, channel):
        try:
            req = urllib.request.Request(TB_SEARCH + urllib.parse.quote(q), headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as res:
                data = json.loads(res.read(2_000_000).decode("utf-8", "replace"))
        except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as e:
            log(f"Tunebat injoignable ({str(e)[:80]}).")
            return None
        items = (data.get("data") or {}).get("items") if isinstance(data, dict) else None
        hit = tb_pick(items, title, channel, duration)
        if hit:
            return {"bpm": hit["bpm"], "key": hit["key"]}
    return None


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


def reply(code, payload, timeout=15):
    """Prévient l'app (sujet <code>-ok)."""
    try:
        http_post(f"{NTFY}/{code}-ok", json.dumps(payload, ensure_ascii=False).encode("utf-8"), timeout=timeout)
        return True
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as e:
        log(f"Impossible de prévenir l'app : {e}")
        return False


# ---------------------------------------------------------------------------
# Écoute et gestion depuis l'app web : la liste des projets et des copies d'écoute
# (AAC, ~2 Mo par morceau) passent en pièces jointes ntfy sur le sujet <code>-ok.
# ntfy.sh : 2 Mo max par pièce jointe (on découpe), 20 Mo en tout gardés 3 h, ~250 envois
# par jour : on n'envoie que ce qui est demandé, plus les dernières prods reçues.

ATTACH_MAX = 1_900_000
PREVIEW_MAX_SECONDS = 6 * 60


def publish_attachment(code, data, filename, meta, timeout=60):
    """Envoie un fichier (pièce jointe) à l'app, avec un petit message JSON. Renvoie True/False."""
    headers = {"User-Agent": f"melofinds-pc/{VERSION}", "Filename": re.sub(r"[^\w.\-]", "_", filename)[:80],
               "X-Message": json.dumps(meta, ensure_ascii=True, separators=(",", ":"))}
    try:
        req = urllib.request.Request(f"{NTFY}/{code}-ok", data=data, headers=headers, method="PUT")
        with urllib.request.urlopen(req, timeout=timeout) as res:
            res.read()
        return True
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as e:
        log(f"Envoi d'un fichier à l'app impossible : {e}")
        return False


def audio_seconds(path):
    """Durée d'un son (ffprobe, sinon en-tête WAV), ou None."""
    probe = tool_path("ffprobe.exe")
    if probe:
        try:
            r = run_tool([probe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)], 30)
            return float(decode(r.stdout).strip())
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    try:
        import wave
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except (OSError, EOFError, ValueError, wave.Error):
        return None


def preview_kbps(seconds):
    """Débit de la copie d'écoute : le plus haut (96 kb/s) qui tient en une seule pièce
    jointe ntfy (~1,7 Mo), 64 kb/s au minimum. Une prod de 3 min : ~73 kb/s, un envoi."""
    if not seconds or seconds <= 0:
        return 80
    return max(64, min(96, int(1_700_000 * 8 / min(seconds, PREVIEW_MAX_SECONDS) / 1000) - 2))


def make_preview(src, out):
    """Copie d'écoute légère du son (AAC 64 à 96 kb/s, 6 min max) pour l'app web."""
    ffmpeg = tool_path("ffmpeg.exe")
    if not ffmpeg:
        raise OSError("ffmpeg manquant")
    kbps = preview_kbps(audio_seconds(src))
    r = run_tool([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-vn", "-map", "0:a:0",
                  "-t", str(PREVIEW_MAX_SECONDS), "-ac", "2", "-ar", "44100", "-c:a", "aac", "-b:a", f"{kbps}k",
                  "-movflags", "+faststart", "-f", "mp4", str(out)], 180)
    if r.returncode != 0 or not Path(out).is_file():
        raise OSError(last_line(r.stderr))
    return Path(out)


def chunks(data, size=ATTACH_MAX):
    return [data[i:i + size] for i in range(0, len(data), size)] or [b""]


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


def unique_project(root, name):
    """« root/Nom/Nom.wav » (ou « Nom (2) » si le dossier existe déjà)."""
    sub, i = name, 2
    while (Path(root) / sub).exists():
        sub = f"{name} ({i})"
        i += 1
    return Path(root) / sub / f"{sub}.wav"


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


def pick_value(sent, sent_tb, desc):
    """Valeur à garder → (valeur, trouvée avec Tunebat ?). Priorité : ce que l'app a envoyé
    (sauf si ça vient de Tunebat), puis la description complète, puis Tunebat."""
    if sent and not sent_tb:
        return sent, False
    if desc:
        return desc, False
    return sent, bool(sent)


YT_URL = "https://www.youtube.com/watch?v="


def tag_wav_link(ffmpeg, src, dst, video_id, title=""):
    """Copie du .wav avec le lien de la vidéo dans ses infos (commentaire), sans réencoder."""
    if not VIDEO_ID.match(str(video_id)):
        return None
    t = re.sub(r"[\x00-\x1f]", " ", clean_title(title))[:200]
    try:
        r = run_tool([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-map", "0:a", "-c", "copy",
                      "-metadata", f"comment={YT_URL}{video_id}", "-metadata", f"title={t}", str(dst)], 120)
    except (OSError, subprocess.SubprocessError):
        return None
    return Path(dst) if r.returncode == 0 and is_wav(dst) else None


_link_cache = {}


def wav_link(path):
    """Identifiant de la vidéo YouTube écrit dans les infos d'un .wav (ou None)."""
    p = Path(path)
    try:
        key = (str(p).lower(), p.stat().st_mtime)
    except OSError:
        return None
    if key in _link_cache:
        return _link_cache[key]
    vid = None
    try:
        with open(p, "rb") as f:
            head = f.read(12)
            if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
                for _ in range(24):
                    h = f.read(8)
                    if len(h) < 8:
                        break
                    cid, size = h[:4], int.from_bytes(h[4:], "little")
                    if cid == b"LIST" and size < 65536:
                        body = f.read(size + (size & 1))
                        m = re.search(rb"(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})", body)
                        if m:
                            vid = m.group(1).decode()
                            break
                    else:
                        f.seek(size + (size & 1), 1)
    except OSError:
        pass
    _link_cache[key] = vid
    if len(_link_cache) > 5000:
        _link_cache.clear()
    return vid


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
    vt = meta.get("title") or ""
    # Clé / BPM : ceux que tu as donnés, sinon la description, sinon Tunebat (marqués [TB …]).
    key, tb_k = pick_value(valid_key(info.get("key")), bool(info.get("tbKey")), find_key(vt, desc))
    bpm, tb_b = pick_value(valid_bpm(info.get("bpm")), bool(info.get("tbBpm")), find_bpm(vt, desc))
    if not key or not bpm:
        step("tunebat", None)
        hit = tunebat_lookup(vt or info.get("t") or "", meta.get("uploader") or meta.get("channel") or "", meta.get("duration"))
        if hit and not key and hit.get("key"):
            key, tb_k = hit["key"], True
        if hit and not bpm and hit.get("bpm"):
            bpm, tb_b = hit["bpm"], True
    # Chaque prod arrive dans son propre dossier de projet : « Nom/Nom.wav »
    lic, limit, why = check_licence(vt, desc, info.get("lic"), info.get("limit"))
    if lic != str(info.get("lic") or "") and out is not None:
        out["lic"] = {"from": str(info.get("lic") or ""), "to": lic, "why": str(why or "")[:160]}
    final = unique_project(root, build_name(vt or info.get("t") or video_id, key, bpm, lic, limit, tb_k, tb_b))
    if not inside(final, root) or final.suffix.lower() != ".wav" or final.parent.parent.resolve() != Path(root).resolve():
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
        # Le lien de la vidéo est écrit dans le .wav (commentaire) : il suit la prod partout,
        # même renommée ou déplacée à la main.
        tagged = tag_wav_link(ffmpeg, wavs[0], Path(tmp) / "tagged.wav", video_id, vt or info.get("t") or "")
        if tagged:
            wavs = [tagged]
        # 3) Seul le .wav vérifié entre dans ton dossier.
        final.parent.mkdir(parents=True, exist_ok=False)
        shutil.move(str(wavs[0]), str(final))
    if not is_wav(final):
        final.unlink(missing_ok=True)
        try:
            final.parent.rmdir()
        except OSError:
            pass
        return False, "fichier non WAV supprimé"
    if out is not None:  # pour FLmake
        out.update(path=str(final), key=key, bpm=bpm, title=clean_title(meta.get("title") or info.get("t") or video_id), yt=video_id,
                   tb={k: v for k, v in (("key", key if tb_k else None), ("bpm", bpm if tb_b else None)) if v})
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


def apply_update(progress=None, reopen=False):
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
    args = [str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", f"/DIR={app_dir}",
            f"/LOG={folder / 'installation.log'}"]
    if reopen:
        args.append("/OUVRIR=1")  # rouvre le panneau après la mise à jour
    for flags in (0x00000008 | 0x00000200 | 0x01000000, 0x00000008 | 0x00000200):  # indépendant du programme qui le lance
        try:
            subprocess.Popen(args, creationflags=flags, close_fds=True)
            break
        except OSError:
            if flags == 0x00000008 | 0x00000200:
                raise
    log(f"Mise à jour vers la version {ver} lancée")
    return f"Mise à jour vers la version {ver}…"


_WNDPROCS = []  # fonctions des fenêtres invisibles : jamais libérées (sinon Windows appelle du vide)


def watch_windows_shutdown(callback, report=None):
    """Fenêtre invisible qui reçoit « Windows s'éteint / ferme la session » et appelle
    callback (quelques secondes au plus). Renvoie une fonction qui arrête la surveillance."""
    if not WINDOWS:
        return lambda: None
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = LRESULT
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
                    ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]
    state = {"done": False, "hwnd": None}
    report = report if report is not None else {}

    def proc(hwnd, msg, wp, lp):
        if msg == 0x0011:  # WM_QUERYENDSESSION : on ne bloque jamais l'arrêt
            return 1
        if msg == 0x0016:  # WM_ENDSESSION
            if wp and not state["done"]:
                state["done"] = True
                try:
                    callback()
                except Exception as e:
                    log(f"Arrêt de Windows : {e}")
            return 0
        return user32.DefWindowProcW(hwnd, msg, wp, lp)
    wndproc = WNDPROC(proc)
    _WNDPROCS.append(wndproc)

    def run():
        try:
            hinst = kernel32.GetModuleHandleW(None)
            wc = WNDCLASSW()
            wc.lpfnWndProc = wndproc
            wc.hInstance = hinst
            wc.lpszClassName = "MelofindsPCWorker"
            if not user32.RegisterClassW(ctypes.byref(wc)):
                report["register"] = ctypes.get_last_error()
            hwnd = user32.CreateWindowExW(0, "MelofindsPCWorker", "Melofinds PC (en ligne)", 0, 0, 0, 0, 0, None, None, hinst, None)
            if not hwnd:
                report["create"] = ctypes.get_last_error()
                log(f"Surveillance de l'arrêt de Windows indisponible (erreur {report['create']}).")
                return
            report["hwnd"] = int(hwnd)
            log(f"Surveillance de l'arrêt de Windows active (fenêtre {int(hwnd)}).")
            state["hwnd"] = hwnd
            msg = wintypes.MSG()
            while not state.get("stop") and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            # fin de la surveillance : fenêtre et classe retirées (une prochaine mise en ligne
            # dans le même programme repart de zéro)
            state["hwnd"] = None
            user32.DestroyWindow(hwnd)
            user32.UnregisterClassW("MelofindsPCWorker", hinst)
        except Exception as e:
            report["error"] = repr(e)[:200]
            log(f"Surveillance de l'arrêt de Windows indisponible : {e!r}")
    th = threading.Thread(target=run, name="arret-windows", daemon=True)
    th.start()

    def stop():
        state["stop"] = True  # arrêt demandé avant même que la fenêtre existe
        if state["hwnd"]:
            user32.PostMessageW(state["hwnd"], 0x0012, 0, 0)  # WM_QUIT
        if threading.current_thread() is not th:
            th.join(3)  # fenêtre détruite avant une éventuelle nouvelle mise en ligne
    stop.wndproc = wndproc  # garde la fonction en vie
    return stop


def _try_lock(f):
    try:
        if WINDOWS:
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(f):
    try:
        if WINDOWS:
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


class SingleInstance:
    """Un seul programme en arrière-plan à la fois (verrou tenu tant qu'il tourne)."""

    def __init__(self, tries=10):
        P.base.mkdir(parents=True, exist_ok=True)
        self.f = open(P.lock, "a+")
        for i in range(tries):  # le panneau vérifie parfois le verrou une fraction de seconde
            self.ok = _try_lock(self.f)
            if self.ok:
                break
            time.sleep(0.3)

    def release(self):
        if self.ok:
            _unlock(self.f)
        self.f.close()
        self.ok = False


def kick_worker():
    """Réveille le programme en ligne : un projet a changé (nom, icône, couleur, favori,
    ordre), la liste part tout de suite vers l'app web."""
    try:
        P.kick.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass


def beat():
    """Battement de cœur : « je suis en ligne » (lu par le panneau)."""
    try:
        P.heartbeat.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass


def lock_held():
    """Le programme en ligne tourne-t-il ? (il garde le verrou tant qu'il est vivant,
    même pendant un long téléchargement)."""
    if not P.lock.exists():
        return False
    try:
        with open(P.lock, "a+") as f:
            if _try_lock(f):
                _unlock(f)
                return False
            return True
    except OSError:
        return False


def running():
    try:
        if time.time() - float(P.heartbeat.read_text(encoding="utf-8")) < 45:
            return True
    except (OSError, ValueError):
        pass
    return lock_held()

