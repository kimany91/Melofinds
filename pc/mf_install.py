"""Melofinds PC — démarrage avec Windows, en ligne / hors ligne, appareils, reprise
des anciennes versions.

L'installation elle-même (dossier choisi, raccourcis bureau + menu Démarrer,
« Applications installées », désinstallation) est faite par l'installateur
Windows standard MelofindsSetup.exe (Inno Setup, voir pc/installer.iss) : pas de
script caché, pas de PowerShell, pas de « taskkill ».
"""

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import mf_core as C
from mf_core import P, log

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "MelofindsPC"
OLD_UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\MelofindsPC"  # version 3.0
OLD_APP_KEY = r"Software\Melofinds"  # version 3.0
DETACHED = 0x00000008


def frozen():
    return bool(getattr(sys, "frozen", False))


def app_exe():
    return Path(sys.executable).resolve() if frozen() else None


def launcher(*args):
    """Commande qui lance le programme (exe installé, ou script Python en développement)."""
    if frozen():
        return [str(app_exe()), *args]
    return [sys.executable, str(Path(__file__).with_name("melofinds_pc.py")), *args]


# ---------------------------------------------------------------------------
# Démarrage avec Windows (clé « Run » de l'utilisateur, comme les autres applis).
# Toujours inscrit : au démarrage, le programme se remet en ligne tout seul, sauf si
# tu as choisi « Mettre hors ligne » dans le panneau (voir wants_online).

def autostart_enabled():
    if not C.WINDOWS:
        return True
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_VALUE)
            return True
    except OSError:
        return False


def ensure_autostart():
    if not (C.WINDOWS and frozen()):
        return
    import winreg
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, f'"{app_exe()}" --background')
    except OSError as e:
        log(f"Démarrage avec Windows impossible à inscrire : {e}")


# ---------------------------------------------------------------------------
# Reprise des anciennes versions (2.x, 3.0)

def migrate_old():
    """Reprend les réglages (appareils, dossier) et les outils d'une ancienne version,
    puis retire ses restes (inscriptions Windows, ancien lancement automatique)."""
    if not P.config.exists():
        for old in C.previous_install_dirs():
            if old.resolve() == P.base.resolve():
                continue
            P.base.mkdir(parents=True, exist_ok=True)
            for name in ("config.json", "state.json"):
                if (old / name).exists() and not (P.base / name).exists():
                    shutil.copyfile(old / name, P.base / name)
            if (old / "tools").is_dir() and not P.tools.exists():
                shutil.copytree(old / "tools", P.tools, dirs_exist_ok=True)
            log(f"Réglages repris de l'ancienne version ({old})")
            break
    C.load_config()  # convertit le format 2.x si besoin
    if not C.WINDOWS:
        return
    import winreg
    for key in (OLD_UNINSTALL_KEY, OLD_APP_KEY):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        except OSError:
            pass
    legacy = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Melofinds PC.vbs"
    try:
        legacy.unlink(missing_ok=True)
    except OSError:
        pass


def configure(dossier=None, pairing=None, device_name=""):
    """Appelé par l'installateur après la copie des fichiers (et à chaque mise à jour)."""
    migrate_old()
    cfg = C.load_config()
    if dossier:
        cfg["dossier"] = str(Path(dossier).expanduser())
    cfg.setdefault("dossier", C.default_folder())
    try:
        Path(cfg["dossier"]).mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log(f"Dossier des prods impossible à créer : {e}")
    if pairing:
        add_device(cfg, pairing, device_name or "Mon téléphone")
    cfg.pop("autostart", None)  # ancien réglage (3.7 et avant) : remplacé par « online »
    C.save_config(cfg)
    ensure_autostart()
    return cfg


# ---------------------------------------------------------------------------
# Appareils

def add_device(cfg, pairing, name=""):
    parsed = C.parse_pairing(pairing)
    if not parsed:
        raise ValueError("Code d'appairage invalide : copie-le depuis Melofinds Web → Mon PC.")
    code, key = parsed
    for d in cfg["devices"]:
        if d["code"] == code:
            d["cle"] = key
            if name:
                d["name"] = name[:40]
            return d
    n = len(cfg["devices"]) + 1
    d = {"id": f"d{int(time.time())}{n}", "name": (name or f"Appareil {n}")[:40], "code": code, "cle": key, "added": int(time.time())}
    cfg["devices"].append(d)
    return d


# ---------------------------------------------------------------------------
# En ligne / hors ligne

def worker_running():
    return C.running()


def wants_online(cfg=None):
    """En ligne voulu : au moins un appareil, et pas mis « hors ligne » dans le panneau."""
    cfg = cfg if cfg is not None else C.load_config()
    return bool(cfg.get("devices")) and cfg.get("online", True) is not False


def set_wanted(on):
    cfg = C.load_config()
    cfg["online"] = bool(on)
    C.save_config(cfg)


BREAKAWAY = 0x01000000  # hors du « groupe » du panneau : fermer le panneau ne l'arrête pas
NEW_GROUP = 0x00000200


def start_worker():
    if worker_running():
        return True
    try:
        P.stop.unlink(missing_ok=True)
    except OSError:
        pass
    kw = dict(close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not C.WINDOWS:
        subprocess.Popen(launcher("--background"), start_new_session=True, **kw)
        return True
    for flags in (DETACHED | NEW_GROUP | BREAKAWAY, DETACHED | NEW_GROUP):
        try:
            subprocess.Popen(launcher("--background"), creationflags=flags, **kw)
            return True
        except OSError as e:  # sortie du groupe refusée par Windows : lancement normal
            err = e
    log(f"Mise en ligne impossible : {err}")
    return False


def go_online():
    """« Mettre en ligne » (panneau) : retenu, même après un redémarrage."""
    set_wanted(True)
    ensure_autostart()
    return start_worker()


def go_offline():
    """« Mettre hors ligne » (panneau) : seul moyen de rester hors ligne."""
    set_wanted(False)
    return stop_worker()


def update_in_progress():
    """Une mise à jour remplace les fichiers : on ne relance pas le programme en attendant."""
    try:
        return P.stop.read_text(encoding="utf-8").strip() == "update" and time.time() - P.stop.stat().st_mtime < 300
    except OSError:
        return False


def stop_worker(timeout=20, reason="stop"):
    """Demande l'arrêt : le programme prévient les appareils (sauf pour une mise à jour)
    puis s'arrête de lui-même. Le verrou qu'il tient dit s'il tourne encore."""
    try:
        P.base.mkdir(parents=True, exist_ok=True)
        P.stop.write_text(reason, encoding="utf-8")
    except OSError:
        pass
    end = time.time() + timeout
    while time.time() < end:
        if not C.lock_held():
            break
        time.sleep(0.5)
    else:  # il ne répond pas : on termine son processus (celui qui tient le verrou)
        try:
            pid = int(P.pid.read_text(encoding="utf-8"))
            if pid != os.getpid():
                os.kill(pid, signal.SIGTERM)
        except (OSError, ValueError):
            pass
    for f in (P.pid, P.heartbeat):
        try:
            f.unlink(missing_ok=True)
        except OSError:
            pass
    return True


def start_if_configured():
    """Après une installation ou une mise à jour : remet en ligne (sauf si mis hors ligne
    dans le panneau)."""
    cfg = configure()
    if wants_online(cfg):
        start_worker()


def uninstaller():
    """Le désinstalleur Windows créé par l'installateur (unins000.exe)."""
    if not frozen():
        return None
    found = sorted(app_exe().parent.glob("unins*.exe"))
    return found[0] if found else None
