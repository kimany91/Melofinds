"""Le moteur de recherche Melofinds dans sa propre fenêtre, depuis Melofinds PC.

La recherche de prods (et le lien d'une prod ou d'une playlist collé) s'ouvre dans une
fenêtre Melofinds (Edge / Chrome en mode application, profil à part : pas d'onglets ni de
barre d'adresse, tes navigateurs ne sont pas touchés). La première fois, cette fenêtre est
reliée à ce PC comme un téléphone : le bouton « Sur mon PC » d'une prod la télécharge ici.
"""

import re
import subprocess
import urllib.parse
import webbrowser

import mf_core as C
import mf_install as I
import mf_tunebat as T

DEVICE_NAME = "Ce PC (fenêtre Melofinds)"
RECENT_MAX = 8
LINK_RE = re.compile(r"https?://(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)/\S+", re.I)


def profile_dir():
    return C.P.base / "web-profile"


def clean_query(q):
    return re.sub(r"[\x00-\x1f]", " ", str(q or "")).strip()[:400]


def remember(cfg, q):
    """Recherches récentes (les liens aussi), la plus récente d'abord, sans doublon."""
    q = clean_query(q)
    if not q:
        return cfg.get("recent_searches", [])
    old = [x for x in cfg.get("recent_searches", []) if isinstance(x, str) and x.lower() != q.lower()]
    cfg["recent_searches"] = [q, *old][:RECENT_MAX]
    return cfg["recent_searches"]


def window_device(cfg):
    """L'appareil « fenêtre Melofinds » de ce PC (créé la première fois) → (code, clé)."""
    pair = str(cfg.get("pc_window") or "")
    parsed = C.parse_pairing(pair)
    if parsed and any(d.get("code") == parsed[0] for d in cfg.get("devices", [])):
        return parsed
    code, key = C.new_pairing()
    I.add_device(cfg, f"{code}.{key}", DEVICE_NAME)
    cfg["pc_window"] = f"{code}.{key}"
    return code, key


def window_url(query="", pairing=None):
    url = C.WEB_APP + ("?" + urllib.parse.urlencode({"q": clean_query(query)}) if clean_query(query) else "")
    if pairing:  # la clé reste après « # » : jamais envoyée à un serveur
        url += f"#pair={pairing[0]}.{pairing[1]}&pcwin=1"
    return url


def open_search(query="", browser=None, launch=subprocess.Popen):
    """Ouvre la fenêtre Melofinds sur cette recherche (ou ce lien). Renvoie l'adresse ouverte."""
    cfg = C.load_config()
    if clean_query(query):
        remember(cfg, query)
    first = not profile_dir().exists() or not cfg.get("pc_window")
    pairing = window_device(cfg) if first else None
    C.save_config(cfg)
    if pairing:
        I.go_online()  # le programme en ligne répond à la fenêtre comme à un téléphone
    url = window_url(query, pairing)
    browser = browser or T.find_browser()
    if browser:
        try:
            launch([browser, f"--user-data-dir={profile_dir()}", f"--app={url}", "--window-size=1280,860",
                    "--no-first-run", "--no-default-browser-check"],
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return url
        except OSError:
            pass
    webbrowser.open(url)
    return url


def link_in(text):
    """Un lien YouTube (prod ou playlist) dans un texte copié, sinon None."""
    m = LINK_RE.search(str(text or ""))
    return m.group(0)[:300] if m else None
