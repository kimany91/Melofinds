"""Melofinds PC — programme en arrière-plan (« en ligne »).

Il écoute les appareils appairés (un sujet ntfy chacun), télécharge les prods
reçues, répond à l'app (en ligne, allumé, téléchargée, erreur) et s'arrête
proprement quand le panneau de gestion le met hors ligne.
"""

import json
import os
import re
import time
import urllib.error
from pathlib import Path

import mf_core as C
import mf_flmake as FM
from mf_core import P, log


def _device_label(raw):
    """Nom court de l'appareil envoyé par l'app (« iPhone · Safari »), nettoyé."""
    return re.sub(r"[^\w\s·.,()+-]", "", str(raw or ""), flags=re.UNICODE)[:40].strip()


def _sleep(seconds):
    """Attend, mais réagit tout de suite à une demande d'arrêt."""
    end = time.time() + seconds
    while time.time() < end:
        if P.stop.exists():
            return
        time.sleep(0.5)


_last_progress = {"at": 0.0, "stage": None}


def show_progress(p):
    """Téléchargement en cours → progress.json (lu par le panneau). None = terminé.
    Au plus ~4 écritures par seconde (sauf changement d'étape)."""
    now = time.time()
    if p is not None and p.get("stage") == _last_progress["stage"] and now - _last_progress["at"] < 0.25:
        return
    _last_progress.update(at=now, stage=p and p.get("stage"))
    try:
        if p is None:
            P.progress.unlink(missing_ok=True)
            return
        tmp = P.progress.with_suffix(".tmp")
        tmp.write_text(json.dumps({**p, "at": time.time()}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(P.progress)
    except OSError:
        pass


def _write_pid():
    try:
        P.pid.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass


def worker(once=False):
    lock = C.SingleInstance()
    if not lock.ok:
        log("Déjà en ligne (un autre Melofinds PC tourne).")
        return 0
    try:
        P.stop.unlink(missing_ok=True)
    except OSError:
        pass
    _write_pid()
    errors = C.ensure_tools()
    for e in errors:
        log(f"Outil : {e}")

    st = C.load_state()
    announced = set()
    recent = []
    last_maint = 0.0
    last_alive = time.time()
    log(f"Melofinds PC {C.VERSION} en ligne.")
    try:
        while True:
            if P.stop.exists():
                log("Mis hors ligne depuis le panneau de gestion.")
                break
            try:
                P.heartbeat.write_text(str(time.time()), encoding="utf-8")
            except OSError:
                pass
            cfg = C.load_config()  # relu à chaque tour : dossier et appareils modifiables à chaud
            devices = cfg["devices"]
            root = Path(cfg.get("dossier") or C.default_folder())
            try:
                root.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                log(f"Dossier des prods inaccessible : {e}")

            for d in devices:  # « je suis en ligne » à chaque nouvel appareil
                if d["code"] not in announced:
                    announced.add(d["code"])
                    C.reply(d["code"], {"pc": "online", "version": C.VERSION, "dossier": str(root), "name": d.get("name", "")})
            if time.time() - last_alive > 1800:
                last_alive = time.time()
                for d in devices:
                    C.reply(d["code"], {"pc": "alive", "version": C.VERSION})
            if time.time() - last_maint > 24 * 3600 and not once:
                last_maint = time.time()
                C.update_ytdlp()
                try:
                    if C.check_update():
                        save_and_exit = C.apply_update()
                        log(save_and_exit)
                except (urllib.error.URLError, OSError, ValueError) as e:
                    log(f"Vérification de mise à jour impossible : {e}")

            seen = set(st["seen"])
            done = set(st["done"])
            fl_last = None
            for d in devices:
                code, key = d["code"], d["cle"]
                since = st["since"].get(code) or "12h"
                try:
                    events = C.poll(code, since)
                except (urllib.error.URLError, OSError, TimeoutError) as e:
                    log(f"Pas de connexion à ntfy.sh ({e}).")
                    break
                for ev in events:
                    since = ev.get("id") or since
                    st["since"][code] = since
                    msg = C.verify(ev.get("message") or "", key)
                    if not msg:
                        log(f"Envoi ignoré (« {d.get('name', '?')} ») : signature absente ou fausse.")
                        continue
                    if msg["n"] in seen:
                        continue
                    seen.add(msg["n"])
                    info = st["devices"].setdefault(code, {})
                    info["last_seen"] = int(time.time())
                    if msg.get("dev"):
                        info["ua"] = _device_label(msg.get("dev"))
                    if msg.get("ping"):
                        C.reply(code, {"pong": msg["n"], "version": C.VERSION, "dossier": str(root), "name": d.get("name", "")})
                        continue
                    if msg.get("update"):
                        try:
                            found = C.check_update()
                            if not found:
                                C.reply(code, {"update": "none", "version": C.VERSION})
                            else:
                                C.reply(code, {"update": "start", "version": found[0]})
                                st["seen"] = list(seen)[-3000:]
                                C.save_state(st)
                                log(C.apply_update())
                        except (urllib.error.URLError, OSError, ValueError) as e:
                            C.reply(code, {"update": "error", "err": str(e)[:200]})
                        continue
                    vid = str(msg.get("v") or "")
                    if not C.VIDEO_ID.match(vid):
                        continue
                    have = C.received_file(st, cfg, vid, root)
                    if have and not msg.get("force"):
                        C.reply(code, {"v": vid, "ok": True, "deja": True, "file": have.name})
                        continue
                    recent = [t for t in recent if t > time.time() - 3600]
                    if len(recent) >= C.MAX_PER_HOUR:
                        C.reply(code, {"v": vid, "ok": False, "err": "limite de 40 téléchargements par heure"})
                        continue
                    recent.append(time.time())
                    log(f"Téléchargement ({d.get('name', '?')}) : {msg.get('t') or vid}")
                    got = {}
                    title = C.clean_title(msg.get("t") or vid)
                    left = sum(1 for e in events[events.index(ev) + 1:] if re.search(r'\\?"v\\?"\s*:', e.get("message") or ""))

                    def progress(stage, pct, _t=title, _left=left):
                        show_progress({"t": _t, "stage": stage, "pct": pct, "queue": _left})
                    ok, detail = C.download(vid, root, msg, got, progress)
                    log(f"  {'OK' if ok else 'Erreur'} : {detail}")
                    flp = None
                    if ok:
                        done.add(vid)
                        st.setdefault("files", {})[vid] = Path(got.get("path") or detail).name
                        if len(st["files"]) > 3000:
                            st["files"] = dict(list(st["files"].items())[-3000:])
                        # FLmake : projet FL prêt (BPM, instru, preset de voix) ; FL s'ouvre après le lot
                        if FM.settings(cfg)["on"]:
                            show_progress({"t": title, "stage": "flp", "pct": None, "queue": left})
                        out, flp = FM.maybe_make(got.get("path"), got.get("key"), got.get("bpm"), got.get("title"), cfg)
                        if out:
                            fl_last = (out, got.get("key"), got.get("bpm"))
                    st["history"].insert(0, {"t": C.clean_title(msg.get("t") or vid), "ok": ok, "detail": detail,
                                             "at": int(time.time()), "device": d.get("name", ""), **({"flp": flp} if flp else {})})
                    st["history"] = st["history"][:50]
                    show_progress(None)
                    C.reply(code, {"v": vid, "ok": ok, "file" if ok else "err": detail})
                    if P.stop.exists():
                        break
            if fl_last:
                FM.open_last(*fl_last, cfg)
            st["seen"] = list(seen)[-3000:]
            st["done"] = list(done)[-3000:]
            known = {d["code"] for d in devices}
            st["since"] = {k: v for k, v in st["since"].items() if k in known}
            st["devices"] = {k: v for k, v in st["devices"].items() if k in known}
            C.save_state(st)
            if once:
                break
            _sleep(C.POLL_SECONDS)
    finally:
        for d in C.load_config()["devices"]:
            if d["code"] in announced:
                C.reply(d["code"], {"pc": "offline", "version": C.VERSION})
        for f in (P.heartbeat, P.pid, P.stop, P.progress):
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass
        log("Hors ligne.")
    return 0
