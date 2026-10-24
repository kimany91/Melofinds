"""Melofinds PC — programme en arrière-plan (« en ligne »).

Il écoute les appareils appairés (un sujet ntfy chacun), télécharge les prods
reçues, répond à l'app (en ligne, allumé, téléchargée, erreur) et s'arrête
proprement quand le panneau de gestion le met hors ligne.
"""

import http.client
import json
import os
import re
import time
import traceback
import urllib.error
from pathlib import Path

import hashlib
import tempfile

import mf_core as C
import mf_flmake as FM
import mf_library as L
from mf_core import P, log


def _device_label(raw):
    """Nom court de l'appareil envoyé par l'app (« iPhone · Safari »), nettoyé."""
    return re.sub(r"[^\w\s·.,()+-]", "", str(raw or ""), flags=re.UNICODE)[:40].strip()


NET_ERRORS = (urllib.error.URLError, OSError, TimeoutError, ValueError, http.client.HTTPException)


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
    C.beat()  # toujours en ligne pendant un long téléchargement
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


def _stop_reason():
    try:
        return P.stop.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


class Remote:
    """Écoute et gestion depuis l'app web : liste des projets, copies d'écoute, renommer,
    icône / couleur, favori. Tout reste dans le dossier des projets ; les limites de
    ntfy.sh (pièces jointes de 2 Mo, 20 Mo / 3 h, ~250 envois / jour) sont respectées."""
    AUDIO_PER_HOUR = 25
    BYTES_3H = 17_000_000

    def __init__(self, st):
        self.st = st
        self.want = set()        # appareils qui attendent la liste tout de suite
        self.active = {}         # appareil → dernière commande (la liste ne part qu'aux appareils actifs)
        self.sent_at = {}        # appareil → dernier envoi de la liste
        self.sig = {}            # appareil → empreinte de la dernière liste envoyée
        self.checked = 0.0
        self.audio = []          # (heure, octets) des copies d'écoute envoyées

    @staticmethod
    def enabled(cfg):
        return cfg.get("remote", True) is not False

    def _budget(self, size):
        now = time.time()
        self.audio = [(t, n) for t, n in self.audio if t > now - 3 * 3600]
        last_hour = sum(1 for t, _ in self.audio if t > now - 3600)
        return last_hour < self.AUDIO_PER_HOUR and sum(n for _, n in self.audio) + size <= self.BYTES_3H

    def push_audio(self, code, it, f, auto=False):
        """Copie d'écoute d'un son du projet, découpée en pièces jointes de 1,9 Mo."""
        meta = {"aud": f["id"], "p": it.id, "n": f["name"][:140], "v": f["label"], "m": int(f["mtime"])}
        try:
            with tempfile.TemporaryDirectory(prefix="melofinds-ecoute-") as tmp:
                data = C.make_preview(f["path"], Path(tmp) / "ecoute.m4a").read_bytes()
        except (OSError, C.subprocess.SubprocessError) as e:
            if not auto:
                C.reply(code, {"aud": f["id"], "err": f"copie d'écoute impossible : {e}"[:200]})
            return False
        if not self._budget(len(data)):
            if not auto:
                C.reply(code, {"aud": f["id"], "err": "limite d'envoi atteinte (ntfy.sh) : réessaie dans un moment"})
            return False
        parts = C.chunks(data)
        for i, part in enumerate(parts):
            if not C.publish_attachment(code, part, f"{f['id']}-{i}.m4a", {**meta, "i": i, "of": len(parts), "len": len(data)}):
                if not auto:
                    C.reply(code, {"aud": f["id"], "err": "envoi de la copie d'écoute impossible"})
                return False
        self.audio.append((time.time(), len(data)))
        pushed = self.st.setdefault("pushed", {})
        pushed[f["id"]] = int(time.time())
        self.st["pushed"] = dict(list(pushed.items())[-500:])
        return True

    def command(self, code, msg, cfg):
        """Commande signée venue de l'app (déjà vérifiée)."""
        cmd = str(msg.get("cmd") or "")
        self.active[code] = time.time()
        if not self.enabled(cfg):
            C.reply(code, {"cmd": cmd, "ok": False, "err": "écoute et gestion à distance désactivées dans Melofinds PC"})
            return
        if cmd == "lib":
            self.want.add(code)
            return
        if cmd == "play":
            it, f = L.find_audio(str(msg.get("f") or "")[:16], cfg)
            if not f:
                C.reply(code, {"aud": str(msg.get("f") or "")[:16], "err": "son introuvable sur le PC"})
                return
            self.push_audio(code, it, f)
            return
        it = L.find_project(str(msg.get("p") or "")[:260], cfg)
        if not it:
            C.reply(code, {"cmd": cmd, "ok": False, "p": str(msg.get("p") or "")[:260], "err": "projet introuvable sur le PC"})
            self.want.add(code)
            return
        try:
            if cmd == "ren":
                new = L.rename(it, str(msg.get("t") or "")[:110], cfg)
                C.reply(code, {"cmd": cmd, "ok": True, "p": it.id, "new": new})
            elif cmd == "style":
                c, i = msg.get("c"), msg.get("i")
                if (c is None and i is None) or (c in L.PALETTE and i in L.ICONS):
                    L.set_style(it, c, i, cfg)
                    C.reply(code, {"cmd": cmd, "ok": True, "p": it.id})
                else:
                    C.reply(code, {"cmd": cmd, "ok": False, "p": it.id, "err": "couleur ou icône inconnue"})
            elif cmd == "fav":
                if bool(msg.get("on")) != it.fav:
                    L.toggle_fav(it, cfg)
                C.reply(code, {"cmd": cmd, "ok": True, "p": it.id})
            else:
                return
        except L.LibError as e:
            C.reply(code, {"cmd": cmd, "ok": False, "p": it.id, "err": str(e)[:200]})
        self.want.add(code)

    def tick(self, devices, cfg, force=False):
        """Envoie la liste des projets aux appareils qui la veulent, ou quand elle a changé
        (au plus toutes les 10 min, seulement aux appareils actifs ces dernières 24 h)."""
        now = time.time()
        if not self.enabled(cfg) or not (self.want or force or now - self.checked > 60):
            return
        self.checked = now
        try:
            lib = L.library_index(cfg)
        except Exception as e:
            log(f"Liste des projets impossible : {e}")
            return
        body = json.dumps(lib, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        sig = hashlib.sha1(json.dumps(lib["projects"], sort_keys=True).encode("utf-8")).hexdigest()
        for d in devices:
            code = d["code"]
            wanted = code in self.want
            changed = self.sig.get(code) != sig and now - self.active.get(code, 0) < 24 * 3600 and now - self.sent_at.get(code, 0) > 600
            if not (wanted or changed or force):
                continue
            if C.publish_attachment(code, body, "projets.json", {"lib": 1, "n": len(lib["projects"]), "at": lib["at"]}):
                self.sig[code], self.sent_at[code] = sig, now
            self.want.discard(code)


def _handle(msg, code, d, root, cfg, st, recent, seen, done, left, remote=None):
    """Traite un envoi authentique. Renvoie (chemin du projet FL à ouvrir, clé, bpm) ou None."""
    seen.add(msg["n"])
    info = st["devices"].setdefault(code, {})
    info["last_seen"] = int(time.time())
    if msg.get("dev"):
        info["ua"] = _device_label(msg.get("dev"))
    if msg.get("ping"):
        C.reply(code, {"pong": msg["n"], "version": C.VERSION, "dossier": str(root), "name": d.get("name", "")})
        return None
    if msg.get("cmd") and remote is not None:
        remote.command(code, msg, cfg)
        return None
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
        except NET_ERRORS as e:
            C.reply(code, {"update": "error", "err": str(e)[:200]})
        return None
    vid = str(msg.get("v") or "")
    if not C.VIDEO_ID.match(vid):
        return None
    have = C.received_file(st, cfg, vid, [root, Path(cfg.get("dossier") or C.default_folder())])
    if have and not msg.get("force"):
        C.reply(code, {"v": vid, "ok": True, "deja": True, "file": have.name})
        return None
    recent[:] = [t for t in recent if t > time.time() - 3600]
    if len(recent) >= C.MAX_PER_HOUR:
        C.reply(code, {"v": vid, "ok": False, "err": "limite de 40 téléchargements par heure"})
        return None
    recent.append(time.time())
    log(f"Téléchargement ({d.get('name', '?')}) : {msg.get('t') or vid}")
    got = {}
    title = C.clean_title(msg.get("t") or vid)
    pending = left if isinstance(left, list) else []
    C.reply(code, {"q": {"v": vid, "t": title[:160], "left": len(pending)}})  # « en cours » dans la file d'attente de l'app

    def progress(stage, pct):
        show_progress({"t": title, "stage": stage, "pct": pct, "queue": len(pending), "pending": pending[:20]})
    try:
        ok, detail = C.download(vid, root, msg, got, progress)
    except Exception as e:  # jamais d'arrêt du programme pour une prod
        log(traceback.format_exc())
        ok, detail = False, f"erreur inattendue : {e}"[:200]
    log(f"  {'OK' if ok else 'Erreur'} : {detail}")
    flp = fl = None
    if ok:
        done.add(vid)
        st.setdefault("files", {})[vid] = str(Path(got.get("path") or root / detail).resolve())
        if len(st["files"]) > 3000:
            st["files"] = dict(list(st["files"].items())[-3000:])
        # FLmake : projet FL prêt (BPM, instru, preset de voix) ; FL s'ouvre après le lot
        try:
            if FM.settings(cfg)["on"]:
                show_progress({"t": title, "stage": "flp", "pct": None, "queue": left})
            out, flp = FM.maybe_make(got.get("path"), got.get("key"), got.get("bpm"), got.get("title"), cfg)
            if out:
                fl = (out, got.get("key"), got.get("bpm"))
        except Exception as e:
            log(traceback.format_exc())
            flp = f"FLmake : {e}"[:200]
    st["history"].insert(0, {"t": title, "ok": ok, "detail": detail, "at": int(time.time()),
                             "device": d.get("name", ""), **({"flp": flp} if flp else {})})
    st["history"] = st["history"][:50]
    show_progress(None)
    C.reply(code, {"v": vid, "ok": ok, "file" if ok else "err": detail, **({"tb": got["tb"]} if ok and got.get("tb") else {})})
    if ok and remote is not None and Remote.enabled(cfg):
        # la nouvelle prod est gardée sur le téléphone : écoutable même quand le PC sera éteint
        try:
            path = Path(got.get("path") or "")
            it = next((x for x in L.scan_projects(cfg) if x.folder and path.parent.resolve() == x.folder.resolve()), None)
            f = next((x for x in L.audio_files(it) if x["instru"]), None) if it else None
            if f:
                remote.push_audio(code, it, f, auto=True)
            remote.want.add(code)
        except Exception as e:
            log(f"Copie d'écoute : {e}")
    return fl


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
    C.beat()
    try:
        for e in C.ensure_tools():
            log(f"Outil : {e}")
    except Exception as e:
        log(f"Outils : {e}")

    st = C.load_state()
    announced = set()
    recent = []
    last_maint = time.time() - 24 * 3600 + 120  # 1re vérification de mise à jour 2 min après le démarrage
    last_alive = time.time()
    last_cycle = time.time()
    log(f"Melofinds PC {C.VERSION} en ligne.")
    reason = ""
    remote = Remote(st)
    try:
        while True:
            if P.stop.exists():
                reason = _stop_reason()
                log("Arrêt pour mise à jour." if reason == "update" else "Mis hors ligne.")
                break
            C.beat()
            if time.time() - last_cycle > 180:  # retour de veille : on se réannonce
                announced.clear()
            last_cycle = time.time()
            try:
                cfg = C.load_config()  # relu à chaque tour : dossier et appareils modifiables à chaud
                devices = cfg["devices"]
                root = C.projects_root(cfg)  # dossier des projets : un dossier par prod
                try:
                    root.mkdir(parents=True, exist_ok=True)
                except OSError as e:
                    log(f"Dossier des prods inaccessible : {e}")

                # « je suis en ligne » à chaque appareil ; réessayé tant que le réseau ne répond pas
                for d in devices:
                    if d["code"] not in announced and C.reply(d["code"], {"pc": "online", "version": C.VERSION, "dossier": str(root), "name": d.get("name", "")}):
                        announced.add(d["code"])
                if time.time() - last_alive > 3000:
                    last_alive = time.time()
                    for d in devices:
                        C.reply(d["code"], {"pc": "alive", "version": C.VERSION})
                if time.time() - last_maint > 24 * 3600 and not once:
                    last_maint = time.time()
                    C.update_ytdlp()
                    try:
                        if C.check_update():
                            log(C.apply_update())
                    except NET_ERRORS as e:
                        log(f"Vérification de mise à jour impossible : {e}")

                seen = set(st["seen"])
                done = set(st["done"])
                fl_last = None
                for d in devices:
                    code, key = d["code"], d["cle"]
                    since = st["since"].get(code) or "12h"
                    try:
                        events = C.poll(code, since)
                    except NET_ERRORS as e:
                        log(f"Pas de connexion à ntfy.sh ({e}).")
                        announced.discard(code)  # se réannoncer quand le réseau revient
                        break
                    msgs = [(ev, C.verify(ev.get("message") or "", key)) for ev in events]
                    for n, (ev, msg) in enumerate(msgs):
                        since = ev.get("id") or since
                        st["since"][code] = since
                        if not msg:
                            log(f"Envoi ignoré (« {d.get('name', '?')} ») : signature absente ou fausse.")
                            continue
                        if msg["n"] in seen:
                            continue
                        # prods qui attendent derrière celle-ci (file d'attente du panneau)
                        left = [C.clean_title(m.get("t") or m.get("v"))[:120] for _, m in msgs[n + 1:]
                                if m and m.get("v") and m["n"] not in seen]
                        try:
                            fl = _handle(msg, code, d, root, cfg, st, recent, seen, done, left, remote)
                        except Exception:
                            log(traceback.format_exc())
                            show_progress(None)
                            fl = None
                        fl_last = fl or fl_last
                        C.beat()
                        if P.stop.exists():
                            break
                remote.tick(devices, cfg)
                if fl_last:
                    try:
                        FM.open_last(*fl_last, cfg)
                    except Exception as e:
                        log(f"FLmake : {e}")
                st["seen"] = list(seen)[-3000:]
                st["done"] = list(done)[-3000:]
                known = {d["code"] for d in devices}
                st["since"] = {k: v for k, v in st["since"].items() if k in known}
                st["devices"] = {k: v for k, v in st["devices"].items() if k in known}
                C.save_state(st)
            except Exception:  # un souci imprévu ne met jamais le PC hors ligne
                log("Erreur inattendue (le programme reste en ligne) :\n" + traceback.format_exc())
            if once:
                break
            _sleep(C.POLL_SECONDS)
    finally:
        if reason != "update":  # pendant une mise à jour, le nouveau programme se réannonce tout de suite
            try:
                for d in C.load_config()["devices"]:
                    if d["code"] in announced:
                        C.reply(d["code"], {"pc": "offline", "version": C.VERSION})
            except Exception:
                pass
        for f in (P.heartbeat, P.pid, P.progress) if reason == "update" else (P.heartbeat, P.pid, P.stop, P.progress):
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass
        lock.release()
        log("Hors ligne.")
    return 0
