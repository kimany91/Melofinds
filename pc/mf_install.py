"""Melofinds PC — installation, raccourcis, démarrage avec Windows, en ligne / hors ligne.

L'installateur (MelofindsSetup.exe = le même programme lancé hors de son dossier
d'installation) copie le programme dans le dossier choisi, télécharge les outils
s'ils manquent, crée les raccourcis (bureau + menu Démarrer), l'inscrit dans
« Applications installées » et, si demandé, le lance avec Windows.
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import mf_core as C
from mf_core import P, log

APP_NAME = "Melofinds PC"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "MelofindsPC"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\MelofindsPC"
APP_KEY = r"Software\Melofinds"
# Fichiers que le programme crée dans son dossier : la désinstallation ne touche qu'à eux.
OWN_FILES = [C.EXE_NAME, "MelofindsPC.new.exe", "config.json", "config.tmp", "state.json", "state.tmp",
             "melofinds.log", "melofinds.old.log", "heartbeat", "worker.lock", "worker.pid", "stop",
             "update.bat", C.MARKER]
OWN_DIRS = ["tools"]
DETACHED = 0x00000008


def frozen():
    return bool(getattr(sys, "frozen", False))


def installed_exe():
    return P.base / C.EXE_NAME


def launcher(*args):
    """Commande qui lance le programme installé (exe, ou script Python en développement)."""
    if frozen():
        return [str(installed_exe()), *args]
    return [sys.executable, str(Path(__file__).with_name("melofinds_pc.py")), *args]


def is_setup_mode():
    """Lancé hors de son dossier d'installation (ex. depuis Téléchargements) = installateur."""
    if not frozen():
        return P.dir is None or not P.config.exists()
    if P.dir is None:
        return True
    return Path(sys.executable).resolve() != installed_exe().resolve()


def installed_version():
    if not C.WINDOWS:
        return C.VERSION if P.config.exists() else None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            return winreg.QueryValueEx(k, "DisplayVersion")[0]
    except OSError:
        return None if not installed_exe().exists() else "2.x"


# ---------------------------------------------------------------------------
# Choix du dossier d'installation (jamais dans un dossier qui n'est pas à nous)

def pick_install_dir(chosen):
    d = Path(str(chosen or "").strip().strip('"')).expanduser()
    if not str(d) or not d.is_absolute():
        raise ValueError("Choisis un dossier complet (ex. C:\\Users\\toi\\Melofinds).")
    if d.exists() and any(d.iterdir()) and not (d / C.MARKER).exists() and not (d / "config.json").exists():
        d = d / "Melofinds"  # dossier déjà utilisé : on s'installe dans un sous-dossier à nous
    if len(d.parts) <= 1:
        raise ValueError("Pas à la racine d'un disque : choisis un dossier.")
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".melofinds-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError:
        raise ValueError(f"Impossible d'écrire dans {d}. Choisis un dossier à toi (ex. dans ton dossier utilisateur).")
    return d


# ---------------------------------------------------------------------------
# Registre Windows (pas besoin d'être administrateur : tout est dans HKCU)

def _reg_set(path, values):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as k:
        for name, val in values.items():
            kind = winreg.REG_DWORD if isinstance(val, int) else winreg.REG_SZ
            winreg.SetValueEx(k, name, 0, kind, val)


def _reg_delete_value(path, name):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, name)
    except OSError:
        pass


def _reg_delete_key(path):
    import winreg
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    except OSError:
        pass


def autostart_enabled():
    if not C.WINDOWS:
        return bool(C.load_config().get("autostart"))
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_VALUE)
            return True
    except OSError:
        return False


def set_autostart(on):
    cfg = C.load_config()
    cfg["autostart"] = bool(on)
    C.save_config(cfg)
    if not C.WINDOWS:
        return
    if on:
        _reg_set(RUN_KEY, {RUN_VALUE: f'"{installed_exe()}" --background'})
    else:
        _reg_delete_value(RUN_KEY, RUN_VALUE)
    legacy = legacy_startup_file()
    if legacy.exists():  # ancien lancement automatique (version 2.x)
        try:
            legacy.unlink()
        except OSError:
            pass


def legacy_startup_file():
    return Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Melofinds PC.vbs"


def register_app():
    """Inscrit le programme dans « Applications installées » (désinstallation propre)."""
    if not C.WINDOWS:
        return
    exe = installed_exe()
    size_kb = 0
    for f in P.base.rglob("*"):
        try:
            size_kb += f.stat().st_size // 1024 if f.is_file() else 0
        except OSError:
            pass
    _reg_set(APP_KEY, {"InstallDir": str(P.base)})
    _reg_set(UNINSTALL_KEY, {
        "DisplayName": APP_NAME, "DisplayVersion": C.VERSION, "Publisher": "Melofinds",
        "InstallLocation": str(P.base), "DisplayIcon": f"{exe},0",
        "UninstallString": f'"{exe}" --uninstall', "NoModify": 1, "NoRepair": 1,
        "EstimatedSize": int(size_kb), "URLInfoAbout": "https://kimany91.github.io/Melofinds/",
    })


# ---------------------------------------------------------------------------
# Raccourcis (bureau + menu Démarrer) via PowerShell

def _ps_quote(s):
    return "'" + str(s).replace("'", "''") + "'"


def shortcut_script(folder_expr, target, workdir, description):
    """Script PowerShell qui crée « Melofinds PC.lnk » dans le dossier spécial donné."""
    return (
        f"$d = {folder_expr}; "
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Melofinds PC.lnk')); "
        f"$s.TargetPath = {_ps_quote(target)}; $s.WorkingDirectory = {_ps_quote(workdir)}; "
        f"$s.IconLocation = {_ps_quote(str(target) + ',0')}; $s.Description = {_ps_quote(description)}; $s.Save()"
    )


def _powershell(script):
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
                       capture_output=True, timeout=60, creationflags=C.NO_WINDOW)
    if r.returncode != 0:
        raise OSError(C.last_line(r.stderr))


def create_shortcuts(desktop=True, start_menu=True):
    if not C.WINDOWS:
        return []
    made = []
    exe = installed_exe()
    for on, expr, label in ((desktop, "[Environment]::GetFolderPath('Desktop')", "bureau"),
                            (start_menu, "[Environment]::GetFolderPath('Programs')", "menu Démarrer")):
        if not on:
            continue
        try:
            _powershell(shortcut_script(expr, exe, P.base, "Gérer Melofinds PC : en ligne, appareils, dossier des prods"))
            made.append(label)
        except (OSError, subprocess.SubprocessError) as e:
            log(f"Raccourci {label} impossible : {e}")
    return made


def remove_shortcuts():
    if not C.WINDOWS:
        return
    try:
        _powershell("foreach ($f in 'Desktop','Programs') { $p = Join-Path ([Environment]::GetFolderPath($f)) 'Melofinds PC.lnk'; if (Test-Path $p) { Remove-Item $p -Force } }")
    except (OSError, subprocess.SubprocessError):
        pass


# ---------------------------------------------------------------------------
# En ligne / hors ligne

def worker_running():
    return C.running()


def start_worker():
    if worker_running():
        return True
    try:
        P.stop.unlink(missing_ok=True)
    except OSError:
        pass
    flags = (DETACHED | C.NO_WINDOW) if C.WINDOWS else 0
    subprocess.Popen(launcher("--background"), creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def stop_worker(timeout=20):
    """Demande l'arrêt (le programme prévient les appareils puis s'arrête)."""
    try:
        P.base.mkdir(parents=True, exist_ok=True)
        P.stop.write_text("stop", encoding="utf-8")
    except OSError:
        pass
    end = time.time() + timeout
    while time.time() < end:
        if not P.pid.exists() and not worker_running():
            return True
        time.sleep(0.5)
    try:
        pid = int(P.pid.read_text(encoding="utf-8"))
        if C.WINDOWS:
            subprocess.run(["taskkill", "/f", "/pid", str(pid)], capture_output=True, creationflags=C.NO_WINDOW)
        else:
            os.kill(pid, 15)
    except (OSError, ValueError):
        pass
    for f in (P.pid, P.heartbeat):
        try:
            f.unlink(missing_ok=True)
        except OSError:
            pass
    return True


def kill_other_instances():
    if C.WINDOWS:
        subprocess.run(["taskkill", "/f", "/im", C.EXE_NAME, "/fi", f"PID ne {os.getpid()}"],
                       capture_output=True, creationflags=C.NO_WINDOW)
        time.sleep(1)


# ---------------------------------------------------------------------------
# Installation / mise à jour / désinstallation

def install(install_dir, beats_dir, desktop=True, autostart=True, pairing=None, device_name="", progress=None):
    """Installe (ou met à jour) le programme. Renvoie la liste des soucis éventuels."""
    say = progress or (lambda s: None)
    issues = []
    target = pick_install_dir(install_dir)
    previous = C.resolve_install_dir()
    old_cfg = C.load_config() if previous else {}
    old_state = C.load_state() if previous else {}

    say("Arrêt de l'ancienne version…")
    if previous:
        stop_worker(timeout=8)
    kill_other_instances()

    old_tools = P.tools
    P.set(target)
    if old_tools.is_dir() and old_tools.resolve() != P.tools.resolve():
        shutil.copytree(old_tools, P.tools, dirs_exist_ok=True)  # pas besoin de retélécharger
    (P.base / C.MARKER).write_text(f"Melofinds PC {C.VERSION}\n", encoding="utf-8")
    say("Copie du programme…")
    if frozen():
        here = Path(sys.executable).resolve()
        if here != installed_exe().resolve():
            shutil.copyfile(here, installed_exe())

    # Réglages : on garde ceux d'avant (appareils, dossier) si le programme était déjà là.
    cfg = C.load_config()
    if not cfg.get("devices") and old_cfg.get("devices"):
        cfg["devices"] = old_cfg["devices"]
    cfg["dossier"] = str(Path(beats_dir).expanduser()) if beats_dir else (old_cfg.get("dossier") or cfg.get("dossier") or C.default_folder())
    Path(cfg["dossier"]).mkdir(parents=True, exist_ok=True)
    if pairing:
        add_device(cfg, pairing, device_name)
    C.save_config(cfg)
    if not P.state.exists() and old_state:
        C.save_state(old_state)

    say("Installation des outils (une seule fois, quelques minutes)…")
    issues += C.ensure_tools(say)

    say("Raccourcis…")
    try:
        register_app()
    except OSError as e:
        issues.append(f"inscription Windows : {e}")
    made = create_shortcuts(desktop=desktop, start_menu=True)
    if desktop and "bureau" not in made and C.WINDOWS:
        issues.append("raccourci sur le bureau non créé")
    set_autostart(autostart)

    # Ancienne installation 2.x : on retire son programme (les réglages ont été repris).
    if previous and previous.resolve() != P.base.resolve() and previous.resolve() == C.LEGACY_DIR.resolve():
        remove_own_files(previous)

    if cfg.get("devices"):
        say("Mise en ligne…")
        start_worker()
    log(f"Installé dans {P.base} (dossier des prods : {cfg['dossier']})")
    return issues


def add_device(cfg, pairing, name=""):
    parsed = C.parse_pairing(pairing)
    if not parsed:
        raise ValueError("Code d'appairage invalide : copie-le depuis Melofinds Web → Mon PC.")
    code, key = parsed
    for d in cfg["devices"]:
        if d["code"] == code:
            d["cle"] = key
            if name:
                d["name"] = name
            return d
    n = len(cfg["devices"]) + 1
    d = {"id": f"d{int(time.time())}{n}", "name": (name or f"Appareil {n}")[:40], "code": code, "cle": key, "added": int(time.time())}
    cfg["devices"].append(d)
    return d


def remove_own_files(folder):
    """Supprime uniquement les fichiers créés par le programme (jamais tes prods)."""
    folder = Path(folder)
    for name in OWN_FILES:
        try:
            (folder / name).unlink(missing_ok=True)
        except OSError:
            pass
    for name in OWN_DIRS:
        shutil.rmtree(folder / name, ignore_errors=True)
    try:
        folder.rmdir()  # seulement s'il est vide
    except OSError:
        pass


def uninstall():
    """Désinstalle : arrêt, démarrage auto, raccourcis, inscription Windows, fichiers du programme.
    Les prods reçues restent dans leur dossier."""
    stop_worker(timeout=10)
    if C.WINDOWS:
        _reg_delete_value(RUN_KEY, RUN_VALUE)
        _reg_delete_key(UNINSTALL_KEY)
        _reg_delete_key(APP_KEY)
        try:
            legacy_startup_file().unlink(missing_ok=True)
        except OSError:
            pass
    remove_shortcuts()
    log("Désinstallé.")
    folder = P.base
    running_from_inside = frozen() and Path(sys.executable).resolve().parent == folder.resolve()
    if running_from_inside and C.WINDOWS:
        # Le programme ne peut pas s'effacer lui-même pendant qu'il tourne : un petit script le fait juste après.
        import tempfile
        bat = Path(tempfile.gettempdir()) / "melofinds-uninstall.bat"
        lines = ["@echo off", "timeout /t 2 /nobreak >nul", f'taskkill /f /im "{C.EXE_NAME}" >nul 2>&1']
        lines += [f'del /f /q "{folder / n}" >nul 2>&1' for n in OWN_FILES]
        lines += [f'rmdir /s /q "{folder / d}" >nul 2>&1' for d in OWN_DIRS]
        lines += [f'rmdir "{folder}" >nul 2>&1', 'del "%~f0"']
        bat.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
        subprocess.Popen(["cmd", "/c", str(bat)], creationflags=C.NO_WINDOW | DETACHED, close_fds=True)
    else:
        remove_own_files(folder)
