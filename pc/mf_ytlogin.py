"""Compte YouTube pour les téléchargements, quand YouTube bloque le PC.

YouTube répond parfois « Sign in to confirm you're not a bot » à un PC (selon son adresse
internet) : il demande de se connecter. Rien n'est contourné : tu te connectes toi-même, une
fois, à un compte YouTube dans une fenêtre Edge / Chrome à part (profil réservé à Melofinds,
ton navigateur habituel n'est pas touché). Les cookies de connexion YouTube sont ensuite
donnés à yt-dlp (fichier privé dans le dossier du programme), comme le conseille yt-dlp.

La fenêtre de connexion est un navigateur normal (pas piloté). Après sa fermeture, le profil
est relu en arrière-plan par le protocole DevTools (local seulement) pour en tirer les cookies
YouTube / Google, quel que soit le chiffrement du navigateur. « Déconnecter » efface tout.
"""

import json
import shutil
import subprocess
import time
from pathlib import Path

import mf_core as C
import mf_tunebat as T

LOGIN_URL = "https://accounts.google.com/ServiceLogin?service=youtube&continue=https%3A%2F%2Fwww.youtube.com%2F"
DOMAINS = (".youtube.com", "youtube.com", ".google.com", "accounts.google.com", ".googleapis.com")
SIGNED_IN = ("LOGIN_INFO", "SAPISID", "__Secure-3PSID", "SID")


class LoginError(Exception):
    pass


def profile_dir():
    return C.P.base / "youtube-profile"


def cookies_file():
    return C.P.base / "youtube-cookies.txt"


def connected():
    """Un compte YouTube est-il relié (fichier de cookies avec une connexion) ?"""
    try:
        txt = cookies_file().read_text(encoding="utf-8")
    except OSError:
        return False
    return any(f"\t{n}\t" in txt for n in SIGNED_IN)


def ytdlp_args():
    """Options à ajouter à yt-dlp (rien si aucun compte n'est relié)."""
    return ["--cookies", str(cookies_file())] if connected() else []


def _netscape(cookies, domains=DOMAINS):
    lines = ["# Netscape HTTP Cookie File", "# Melofinds PC : compte YouTube (Réglages → Déconnecter pour l'effacer)", ""]
    n = 0
    for c in cookies:
        dom = str(c.get("domain") or "")
        if not any(dom == d or dom.endswith(d if d.startswith(".") else "." + d) for d in domains):
            continue
        name, value = str(c.get("name") or ""), str(c.get("value") or "")
        if not name or "\t" in name + value or "\n" in name + value:
            continue
        exp = c.get("expires")
        exp = int(exp) if isinstance(exp, (int, float)) and exp > 0 else 0
        lines.append("\t".join([dom, "TRUE" if dom.startswith(".") else "FALSE", str(c.get("path") or "/"),
                                "TRUE" if c.get("secure") else "FALSE", str(exp), name, value]))
        n += 1
    return "\n".join(lines) + "\n", n


def export_cookies(browser=None, extra_args=None, domains=DOMAINS, timeout=30):
    """Relit le profil (navigateur invisible, quelques secondes) et écrit le fichier de cookies.
    Renvoie True si une connexion YouTube s'y trouve."""
    browser = browser or T.find_browser()
    if not browser:
        raise LoginError("Edge ou Chrome introuvable sur ce PC")
    prof = profile_dir()
    if not prof.exists():
        return False
    port_file = prof / "DevToolsActivePort"
    try:
        port_file.unlink(missing_ok=True)
    except OSError:
        pass
    proc = subprocess.Popen([browser, f"--user-data-dir={prof}", "--remote-debugging-port=0", "--headless=new",
                             "--no-first-run", "--no-default-browser-check", "about:blank", *(extra_args or [])],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=C.NO_WINDOW)
    b = None
    try:
        port, bpath = T._wait_port(port_file, proc, timeout)
        b = T.CDP(f"ws://127.0.0.1:{port}{bpath}")
        cookies = (b.call("Storage.getCookies") or {}).get("cookies") or []
        text, n = _netscape(cookies, domains)
        if not n:
            return False
        out = cookies_file()
        tmp = out.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        try:
            tmp.chmod(0o600)
        except OSError:
            pass
        tmp.replace(out)
        return connected()
    except T.TunebatError as e:
        raise LoginError(str(e))
    finally:
        if b:
            try:
                b.ws.send(json.dumps({"id": 99, "method": "Browser.close"}))
            except Exception:
                pass
            b.close()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()


def connect(browser=None, wait=600):
    """Ouvre la page de connexion Google / YouTube dans la fenêtre Melofinds (navigateur
    normal), attend que tu la fermes, puis garde la connexion pour yt-dlp."""
    browser = browser or T.find_browser()
    if not browser:
        raise LoginError("Edge ou Chrome introuvable sur ce PC")
    prof = profile_dir()
    prof.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen([browser, f"--user-data-dir={prof}", "--no-first-run", "--no-default-browser-check",
                             f"--app={LOGIN_URL}", "--window-size=520,720"],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        proc.wait(timeout=wait)
    except subprocess.TimeoutExpired:
        proc.terminate()
    time.sleep(1.0)  # le navigateur finit d'écrire ses cookies
    ok = export_cookies(browser)
    if not ok:
        raise LoginError("pas de connexion YouTube trouvée : connecte-toi, puis ferme la fenêtre")
    return True


def disconnect():
    """Efface la connexion : fichier de cookies et profil Melofinds du navigateur."""
    try:
        cookies_file().unlink(missing_ok=True)
    except OSError:
        pass
    shutil.rmtree(profile_dir(), ignore_errors=True)


def refresh():
    """YouTube renouvelle ses cookies : relus depuis le profil avant de réessayer."""
    if not profile_dir().exists():
        return False
    try:
        return export_cookies()
    except LoginError:
        return False
