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
import queue
import tempfile
import threading

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
        if P.stop.exists() or P.kick.exists():
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


class Mci:
    """Lecteur intégré à Windows (MCI) : .wav, pause, reprise, position. Rien à installer."""

    def __init__(self, alias="mflisten"):
        self.alias, self.path, self.error, self.length = alias, None, "", 0
        self.ok = C.WINDOWS
        if self.ok:
            import ctypes
            self._send = ctypes.windll.winmm.mciSendStringW
            self._buf = ctypes.create_unicode_buffer(256)

    def _cmd(self, text):
        if not self.ok:
            return None
        code = self._send(text, self._buf, 255, 0)
        if code == 0:
            return self._buf.value
        self.error = self._error(code)
        return None

    def _error(self, code):
        try:
            import ctypes
            b = ctypes.create_unicode_buffer(256)
            ctypes.windll.winmm.mciGetErrorStringW(code, b, 255)
            return b.value or f"erreur {code}"
        except Exception:
            return f"erreur {code}"

    def play(self, path):
        """Le .wav s'ouvre avec le lecteur de sons de Windows (waveaudio), sinon celui des médias."""
        self.stop()
        self.error = ""
        p = str(path).replace('"', "")
        for kind in ("waveaudio", "mpegvideo"):
            if self._cmd(f'open "{p}" type {kind} alias {self.alias}') is None:
                continue
            self.path = str(path)
            self._cmd(f"set {self.alias} time format milliseconds")
            try:
                self.length = int(self._cmd(f"status {self.alias} length") or 0)
            except ValueError:
                self.length = 0
            if self._cmd(f"play {self.alias}") is not None:
                return True
            self.stop()
        return False

    def mode(self):
        return (self._cmd(f"status {self.alias} mode") or "stopped") if self.path else None

    def position(self):
        try:
            return int(self._cmd(f"status {self.alias} position") or 0) if self.path else 0
        except ValueError:
            return 0

    def toggle(self):
        m = self.mode()
        if m == "playing":
            self._cmd(f"pause {self.alias}")
            return "paused"
        if m in ("paused", "stopped"):
            self._cmd(f"play {self.alias}")
            return "playing"
        return None

    def seek(self, ms):
        if not self.path:
            return
        was = self.mode()
        self._cmd(f"seek {self.alias} to {int(max(0, min(ms, self.length or ms)))}")
        if was == "playing":
            self._cmd(f"play {self.alias}")

    def stop(self):
        if self.path:
            self._cmd(f"close {self.alias}")
        self.path, self.length = None, 0


def _hue_of(rgb):
    """Couleur dominante et vive d'une petite image (octets RVB) : (teinte, saturation %), ou None.
    Même calcul que l'appli (PhoneLibrary.colorOf)."""
    import colorsys
    import math
    x = y = w = ls = 0.0
    for i in range(0, len(rgb) - 2, 3):
        h, s, v = colorsys.rgb_to_hsv(rgb[i] / 255, rgb[i + 1] / 255, rgb[i + 2] / 255)
        if s * v < 0.04:
            continue
        wt = s * s * (0.3 + v)
        x += math.cos(h * 2 * math.pi) * wt
        y += math.sin(h * 2 * math.pi) * wt
        w += wt
        ls += s * wt
    if w < 0.5:
        return None
    return int(round((math.degrees(math.atan2(y, x)) + 360) % 360)), int(round(max(45, min(85, ls / w * 100 + 15))))


def fetch_art(vid, folder):
    """Miniature YouTube de la prod en PNG 128×72 (le panneau sait l'afficher sans rien
    installer) et sa couleur. Renvoie (chemin ou None, (teinte, saturation) ou None)."""
    ffmpeg = C.tool_path("ffmpeg.exe")
    if not ffmpeg or not C.VIDEO_ID.match(vid):
        return None, None
    folder = Path(folder)
    jpg, png = folder / f"{vid}.jpg", folder / f"{vid}.png"
    try:
        data = C.http_get(f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg", timeout=10)
        if len(data) < 500 or len(data) > 400_000 or not data.startswith(b"\xff\xd8"):
            return None, None
        folder.mkdir(parents=True, exist_ok=True)
        jpg.write_bytes(data)
        C.run_tool([ffmpeg, "-y", "-v", "error", "-i", str(jpg), "-vf", "scale=128:72", str(png)], 30)
        r = C.run_tool([ffmpeg, "-v", "error", "-i", str(jpg), "-vf", "scale=32:18", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], 30)
        color = _hue_of(r.stdout) if r.returncode == 0 else None
        return (png if png.exists() and png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" else None), color
    except Exception:
        return None, None
    finally:
        try:
            jpg.unlink(missing_ok=True)
        except OSError:
            pass


class Listen:
    """Bouton PC de l'onglet Téléphone : la prod est téléchargée en .wav dans un dossier
    temporaire (jamais dans ton dossier de prods) et jouée sur le PC, avec sa barre d'écoute
    dans le panneau (miniature, couleur, avance, pause, arrêt). Seule la dernière demande
    compte ; les sons d'écoute sont effacés (4 gardés au plus, tous à l'arrêt)."""
    PER_HOUR = 60
    KEEP = 4
    MAX_AGE_MS = 180_000  # demande faite pendant que le PC était éteint : pas de son surprise plus tard
    FILE = re.compile(r"[A-Za-z0-9_-]{11}\.(wav|png|jpg)")

    def __init__(self, folder=None, player=None, fetch=None, reply=None, art=None):
        self.dir = Path(folder or Path(tempfile.gettempdir()) / "melofinds-ecoute-pc")
        self.player = player or Mci()
        self.fetch = fetch or C.download_listen
        self.art_fetch = art or fetch_art
        self.reply = reply or C.reply
        self.gen = 0
        self.recent = []
        self.cur = None          # le son chargé : {code, v, t, tags, ch, color, img}
        self.info = {}           # dernière demande : ce qu'il faut afficher
        self.state = ""
        self.shown_at = 0.0
        self.q = queue.Queue()   # tout ce qui touche au lecteur passe par un seul fil
        self.clear()
        for f in (P.listen, P.listen_cmd):
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _files(self):
        try:
            return [p for p in self.dir.iterdir() if p.is_file() and self.FILE.fullmatch(p.name)]
        except OSError:
            return []

    def clear(self, keep=0, spare=None):
        """Efface les sons et miniatures d'écoute (garde les `keep` sons les plus récents)."""
        files = self._files()
        wavs = sorted((p for p in files if p.suffix == ".wav"), key=lambda p: p.stat().st_mtime, reverse=True)
        kept = {p.stem for p in wavs[:keep]} | ({Path(spare).stem} if spare else set())
        for p in files:
            if p.stem not in kept:
                try:
                    p.unlink()
                except OSError:
                    pass

    # ---------------------------------------------------------------- affichage

    def _show(self, state):
        """listen.json, lu par le panneau : la prod, sa miniature, sa couleur, où en est la lecture."""
        self.state = state
        self.shown_at = time.time()
        try:
            if state in ("loading", "playing", "paused"):
                i = self.info
                pos = self.player.position() if state != "loading" else 0
                body = {"v": i.get("v", ""), "t": i.get("t", ""), "ch": i.get("ch", ""), "tags": i.get("tags", []),
                        "s": state, "at": time.time(), "pos": pos, "len": self.player.length if state != "loading" else 0,
                        "img": str(i["img"]) if i.get("img") else "", "color": i.get("color")}
                tmp = P.listen.with_suffix(".tmp")
                tmp.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
                tmp.replace(P.listen)
            else:
                P.listen.unlink(missing_ok=True)
        except OSError:
            pass

    def _say(self, code, vid, state, title="", err=""):
        if vid == self.info.get("v") or state in ("stopped", "ended"):
            self._show(state)
        body = {"v": vid, "s": state}
        if title:
            body["t"] = title[:160]
        if err:
            body["err"] = str(err)[:200]
        if not code:
            return
        try:
            self.reply(code, {"listen": body})
        except Exception:
            pass

    # ---------------------------------------------------------------- demandes du téléphone

    @staticmethod
    def _clean_info(msg, vid):
        tags = msg.get("tags")
        tags = [re.sub(r"[\x00-\x1f]", "", str(x))[:24] for x in tags[:4] if isinstance(x, str) and x.strip()] if isinstance(tags, list) else []
        col = msg.get("color")
        color = None
        if isinstance(col, dict) and isinstance(col.get("h"), (int, float)) and not isinstance(col.get("h"), bool):
            s = col.get("s")
            color = [int(max(0, min(360, col["h"]))), int(max(0, min(100, s if isinstance(s, (int, float)) and not isinstance(s, bool) else 60)))]
        return {"v": vid, "t": C.clean_title(msg.get("t") or vid)[:160], "tags": tags,
                "ch": re.sub(r"[\x00-\x1f]", "", str(msg.get("ch") or ""))[:60], "color": color, "img": None}

    def request(self, code, msg):
        a = str(msg.get("a") or "")
        if a in ("toggle", "stop", "seek"):
            if a == "stop":
                self.gen += 1  # un téléchargement en cours ne jouera pas
            ms = msg.get("ms")
            self.q.put((a, code, ms if isinstance(ms, (int, float)) and not isinstance(ms, bool) else 0))
            return
        vid = str(msg.get("v") or "")
        if not C.VIDEO_ID.match(vid):
            return
        ts = msg.get("ts")
        if isinstance(ts, (int, float)) and time.time() * 1000 - ts > self.MAX_AGE_MS:
            return
        info = self._clean_info(msg, vid)
        title = info["t"]
        if not self.player.ok:
            self._say(code, vid, "error", title, "lecture sur le PC : Windows seulement")
            return
        now = time.time()
        self.recent = [t for t in self.recent if t > now - 3600]
        if len(self.recent) >= self.PER_HOUR:
            self._say(code, vid, "error", title, "limite de 60 écoutes par heure")
            return
        self.recent.append(now)
        self.gen += 1
        gen = self.gen
        self.q.put(("halt", code, info))
        threading.Thread(target=self._get_art, args=(gen, info), daemon=True).start()
        have = self.dir / f"{vid}.wav"
        if C.is_wav(have):
            self.q.put(("play", gen, code, info, have))
            return
        self._say(code, vid, "loading", title)
        log(f"Écoute sur le PC : {title}")
        threading.Thread(target=self._get, args=(gen, code, info), daemon=True).start()

    def _get_art(self, gen, info):
        png = self.dir / f"{info['v']}.png"
        color = None
        if not png.exists():
            try:
                png, color = self.art_fetch(info["v"], self.dir)
            except Exception:
                png = None
        if gen == self.gen:
            self.q.put(("art", gen, png, color))

    def _get(self, gen, code, info):
        try:
            path, err = self.fetch(info["v"], self.dir)
        except Exception as e:
            path, err = None, f"erreur inattendue : {e}"
        if gen != self.gen:
            return  # une autre prod a été demandée entre-temps
        if not path:
            self._say(code, info["v"], "error", info["t"], err or "téléchargement impossible")
            return
        self.q.put(("play", gen, code, info, path))

    # ---------------------------------------------------------------- lecteur (un seul fil)

    def _panel_command(self):
        """Boutons de la barre d'écoute du panneau : { a: toggle | stop | seek, ms }."""
        try:
            raw = P.listen_cmd.read_text(encoding="utf-8")
            P.listen_cmd.unlink(missing_ok=True)
            c = json.loads(raw)
        except (OSError, ValueError):
            return None
        if not isinstance(c, dict) or c.get("a") not in ("toggle", "stop", "seek"):
            return None
        if c["a"] == "stop":
            self.gen += 1
        ms = c.get("ms")
        return c["a"], (self.cur or {}).get("code", ""), ms if isinstance(ms, (int, float)) and not isinstance(ms, bool) else 0

    def _loop(self):
        while True:
            try:
                act = self.q.get(timeout=0.25)
            except queue.Empty:
                act = None
            try:
                if act is None and P.listen_cmd.exists():
                    act = self._panel_command()
                if act is None:
                    if self.cur and self.player.mode() == "stopped":  # arrivée à la fin
                        cur = self.cur
                        self.player.stop()
                        self.cur = None
                        self._say(cur["code"], cur["v"], "ended", cur["t"])
                    elif self.cur and self.state == "playing" and time.time() - self.shown_at > 1:
                        self._show("playing")  # le panneau suit la lecture
                    continue
                kind = act[0]
                if kind == "quit":
                    self.player.stop()
                    self.cur = None
                    self._show("stopped")
                    self.clear()
                    return
                if kind == "halt":  # une nouvelle prod arrive : celle d'avant s'arrête tout de suite
                    self.player.stop()
                    self.cur = None
                    self.info = act[2]
                elif kind == "art":
                    _, gen, png, color = act
                    if gen == self.gen:
                        if png:
                            self.info["img"] = png
                        if color and not self.info.get("color"):
                            self.info["color"] = list(color)
                        if self.state in ("loading", "playing", "paused"):
                            self._show(self.state)
                elif kind == "play":
                    _, gen, code, info, path = act
                    if gen != self.gen:
                        continue
                    if self.player.play(path):
                        self.cur = {**info, "code": code}
                        self._say(code, info["v"], "playing", info["t"])
                        self.clear(self.KEEP, spare=Path(path).name)
                    else:
                        err = getattr(self.player, "error", "")
                        log(f"Écoute sur le PC impossible : {err}")
                        self._say(code, info["v"], "error", info["t"], f"le PC n'arrive pas à lire ce son{f' ({err})' if err else ''}")
                elif kind == "toggle" and self.cur:
                    st = self.player.toggle()
                    if st:
                        self._say(self.cur["code"], self.cur["v"], st, self.cur["t"])
                elif kind == "seek" and self.cur:
                    self.player.seek(act[2])
                    self._show(self.state or "playing")
                elif kind == "stop":
                    was = self.cur
                    self.player.stop()
                    self.cur = None
                    self._say(was["code"] if was else act[1], was["v"] if was else "", "stopped", was["t"] if was else "")
            except Exception:
                log("Écoute sur le PC :\n" + traceback.format_exc())

    def close(self):
        self.gen += 1
        self.q.put(("quit",))
        self.thread.join(timeout=5)


class Remote:
    """Écoute et gestion depuis l'app web : liste des projets, copies d'écoute, renommer,
    icône / couleur, favori. Tout reste dans le dossier des projets ; les limites de
    ntfy.sh (pièces jointes de 2 Mo, 20 Mo / 3 h, ~250 envois / jour) sont respectées."""
    AUDIO_PER_HOUR = 25
    BYTES_3H = 17_000_000
    SYNC_PER_TICK = 3

    def __init__(self, st):
        self.st = st
        self.queue = {}          # appareil → sons à lui envoyer (synchronisation du téléphone)
        self.reported = {}       # appareil → dernier état de synchro annoncé
        self.blocked_until = 0.0
        self.kick = False
        self.fmap = {}
        self.want = set()        # appareils qui attendent la liste tout de suite
        self.active = {}         # appareil → dernière commande (la liste ne part qu'aux appareils actifs)
        self.sent_at = {}        # appareil → dernier envoi de la liste
        self.sig = {}            # appareil → empreinte de la dernière liste envoyée
        self.checked = 0.0
        self.listen = None       # écoute sur le PC (créée à la première demande)
        # (heure, octets) envoyés en pièces jointes ces 3 dernières heures : gardé dans l'état,
        # pour ne pas l'oublier à un redémarrage ou une mise à jour (ntfy.sh, lui, s'en souvient)
        self.audio = [tuple(x) for x in (st.get("uploads") or []) if isinstance(x, (list, tuple)) and len(x) == 2]

    @staticmethod
    def enabled(cfg):
        return cfg.get("remote", True) is not False

    LIB_RESERVE = 3_000_000  # place gardée pour la liste des projets et les sons demandés

    def _note(self, size):
        self.audio.append((time.time(), size))
        self.st["uploads"] = [list(x) for x in self.audio[-400:]]

    def _budget(self, size):
        now = time.time()
        self.audio = [(t, n) for t, n in self.audio if t > now - 3 * 3600]
        self.st["uploads"] = [list(x) for x in self.audio]
        last_hour = sum(1 for t, n in self.audio if t > now - 3600 and n > 300_000)
        return last_hour < self.AUDIO_PER_HOUR and sum(n for _, n in self.audio) + size <= self.BYTES_3H

    def next_free(self, size=1_900_000 + 3_000_000):
        """Heure à laquelle ntfy.sh acceptera de nouveau un son (les pièces jointes expirent après 3 h)."""
        now = time.time()
        if self._budget(size):
            return now
        total = sum(n for _, n in self.audio)
        for t, n in sorted(self.audio):
            total -= n
            if total + size <= self.BYTES_3H:
                return t + 3 * 3600
        return now + 3 * 3600

    def push_audio(self, code, it, f, auto=False):
        """Copie d'écoute d'un son du projet, découpée en pièces jointes de 1,9 Mo."""
        """Renvoie "ok", "budget" (limite ntfy.sh : à refaire plus tard) ou "error"."""
        meta = {"aud": f["id"], "p": it.id, "n": f["name"][:140], "v": f["label"], "m": int(f["mtime"])}
        reserve = self.LIB_RESERVE if auto else 0  # la synchro laisse toujours de la place à la liste
        if not self._budget(1_000_000 + reserve):
            if not auto:
                C.reply(code, {"aud": f["id"], "err": "limite d'envoi atteinte (ntfy.sh) : réessaie dans un moment"})
            return "budget"
        try:
            with tempfile.TemporaryDirectory(prefix="melofinds-ecoute-") as tmp:
                data = C.make_preview(f["path"], Path(tmp) / "ecoute.m4a").read_bytes()
        except (OSError, C.subprocess.SubprocessError) as e:
            if not auto:
                C.reply(code, {"aud": f["id"], "err": f"copie d'écoute impossible : {e}"[:200]})
            return "error"
        if not self._budget(len(data) + reserve):
            if not auto:
                C.reply(code, {"aud": f["id"], "err": "limite d'envoi atteinte (ntfy.sh) : réessaie dans un moment"})
            return "budget"
        parts = C.chunks(data)
        for i, part in enumerate(parts):
            if not C.publish_attachment(code, part, f"{f['id']}-{i}.m4a", {**meta, "i": i, "of": len(parts), "len": len(data)}):
                if not auto:
                    C.reply(code, {"aud": f["id"], "err": "envoi de la copie d'écoute impossible"})
                self.blocked_until = time.time() + 900  # ntfy.sh refuse : on réessaie dans 15 min
                return "budget"
        now = time.time()
        self._note(len(data))
        pushed = self.st.setdefault("pushed", {})
        pushed[f["id"]] = int(now)
        self.st["pushed"] = dict(list(pushed.items())[-500:])
        sent = self.st.setdefault("sent_dev", {}).setdefault(code, {})
        sent[f["id"]] = [int(f["mtime"]), int(now)]
        self.st["sent_dev"][code] = dict(list(sent.items())[-800:])
        return "ok"

    def sync_request(self, code, fids, reset=False):
        """Le téléphone dit quels sons il n'a pas encore (dernière version de chaque projet) :
        ils partent petit à petit, sans dépasser les limites de ntfy.sh. reset : le téléphone a
        tout effacé (bouton « Vider »), on oublie ce qui lui a déjà été envoyé."""
        if reset:
            self.st.setdefault("sent_dev", {})[code] = {}
            self.queue[code] = []
            self.reported.pop(code, None)
        q = [x for x in self.queue.get(code, []) if x in fids]  # ce qu'il a reçu entre-temps n'est plus demandé
        for fid in fids:
            if isinstance(fid, str) and re.fullmatch(r"[a-f0-9]{12}", fid) and fid not in q:
                q.append(fid)
        self.queue[code] = q[:300]
        self.kick = True

    def process_sync(self, devices):
        now = time.time()
        sent = 0
        for d in devices:
            code = d["code"]
            q = self.queue.get(code) or []
            done_dev = self.st.get("sent_dev", {}).get(code, {})
            while q and sent < self.SYNC_PER_TICK and now >= self.blocked_until:
                fid = q[0]
                hit = self.fmap.get(fid)
                rec = done_dev.get(fid)
                if not hit or (rec and rec[0] >= int(hit[1]["mtime"]) and now - rec[1] < 2.5 * 3600):
                    q.pop(0)  # disparu, ou déjà envoyé il y a moins de 2 h 30 (encore sur ntfy)
                    continue
                res = self.push_audio(code, hit[0], hit[1], auto=True)
                if res == "budget":
                    self.blocked_until = max(self.blocked_until, self.next_free())
                    break
                q.pop(0)
                sent += 1
            state = (len(q), int(max(0, self.next_free() - now) // 600)) if q else (0, 0)
            if state != self.reported.get(code, (0, 0)):
                C.reply(code, {"sync": {"left": len(q), "wait": int(max(0, max(self.blocked_until, self.next_free()) - now)) if q else 0}})
                self.reported[code] = state

    def command(self, code, msg, cfg):
        """Commande signée venue de l'app (déjà vérifiée)."""
        cmd = str(msg.get("cmd") or "")
        self.active[code] = time.time()
        if cmd == "desc":  # descriptions que YouTube cache à l'app (rien du PC n'est partagé)
            self.send_descriptions(code, msg.get("v"))
            return
        if cmd == "listen":  # bouton PC de l'onglet Téléphone : jouer la prod sur le PC
            if self.listen is None:
                self.listen = Listen()
            self.listen.request(code, msg)
            return
        if not self.enabled(cfg):
            C.reply(code, {"cmd": cmd, "ok": False, "err": "écoute et gestion à distance désactivées dans Melofinds PC"})
            return
        if cmd == "lib":
            self.want.add(code)
            return
        if cmd == "links":  # liens des prods reçues avant (gardés par le téléphone)
            v = msg.get("v")
            pairs = {str(k): str(x)[:260] for k, x in list(v.items())[:300]} if isinstance(v, dict) else {}
            n = L.remember_links(pairs, cfg)
            if n:
                self.want.add(code)
            return
        if cmd == "sync":
            f = msg.get("f")
            self.sync_request(code, [x for x in f if isinstance(x, str)][:300] if isinstance(f, list) else [], bool(msg.get("reset")))
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
            elif cmd == "tags":  # BPM / clé trouvés (ou corrigés) après le téléchargement
                k = str(msg.get("key") or "")
                k = k if re.fullmatch(r"[A-G][#b]? (min|maj)", k) else None
                b = msg.get("bpm")
                b = int(b) if isinstance(b, (int, float)) and not isinstance(b, bool) and 50 <= b <= 220 else None
                if not k and not b:
                    C.reply(code, {"cmd": cmd, "ok": False, "p": it.id, "err": "ni clé ni BPM"})
                else:
                    new = L.set_tags(it, k, b, bool(msg.get("fk", True)), bool(msg.get("fb", True)), bool(msg.get("user")), cfg)
                    C.reply(code, {"cmd": cmd, "ok": True, "p": it.id, "new": new})
            elif cmd == "fav":
                if bool(msg.get("on")) != it.fav:
                    L.toggle_fav(it, cfg)
                C.reply(code, {"cmd": cmd, "ok": True, "p": it.id})
            else:
                return
        except L.LibError as e:
            C.reply(code, {"cmd": cmd, "ok": False, "p": it.id, "err": str(e)[:200]})
        self.want.add(code)

    @staticmethod
    def _sig(lib):
        """Empreinte de la liste sans les dates : les sauvegardes auto de FL ne la renvoient pas."""
        slim = [{**{k: v for k, v in p.items() if k != "d"}, "files": [{k: v for k, v in f.items() if k not in ("m", "s")} for f in p["files"]]}
                for p in lib["projects"]]
        return hashlib.sha1(json.dumps(slim, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    def send_descriptions(self, code, ids):
        ids = [str(x) for x in ids if isinstance(x, str)][:60] if isinstance(ids, list) else []
        if not ids:
            return
        found = C.video_descriptions(ids)
        body = json.dumps({"d": found, "miss": [v for v in ids if v not in found]}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if C.publish_attachment(code, body, "descriptions.json", {"desc": 1, "n": len(found)}):
            self._note(len(body))
        log(f"Descriptions lues pour l'app : {len(found)}/{len(ids)}")

    def tick(self, devices, cfg, final=False):
        """Liste des projets envoyée à l'app : au démarrage, à chaque changement (au plus
        toutes les 3 min), quand l'app la demande, et à l'arrêt. Les nouveaux sons
        (versions exportées…) partent aussi tout seuls en copie d'écoute."""
        now = time.time()
        if not self.enabled(cfg) or not devices or not (self.want or self.kick or final or now - self.checked > 45):
            return
        self.checked, self.kick = now, False
        fmap = {}
        try:
            lib = L.library_index(cfg, files_out=fmap)
        except Exception as e:
            log(f"Liste des projets impossible : {e}")
            return
        body = json.dumps(lib, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        sig = self._sig(lib)
        for d in devices:
            code = d["code"]
            changed = self.sig.get(code) != sig
            if not (code in self.want or (changed and (final or now - self.sent_at.get(code, 0) > 180))):
                continue
            if C.publish_attachment(code, body, "projets.json", {"lib": 1, "n": len(lib["projects"]), "at": lib["at"]}):
                self.sig[code], self.sent_at[code] = sig, now
                self.want.discard(code)
                self._note(len(body))  # compte aussi dans les 20 Mo de ntfy.sh
        self.fmap = fmap
        if not final:
            self.new_sounds(devices, fmap, now)
            self.process_sync(devices)

    def new_sounds(self, devices, fmap, now):
        """Sons apparus ou modifiés dans les projets (un export « Haze 1.3.4.wav »…) :
        copie d'écoute envoyée toute seule, 2 par tour au plus, les plus récents d'abord."""
        cur = {fid: int(f["mtime"]) for fid, (_, f) in fmap.items()}
        targets = phone_targets(fmap)
        known = self.st.get("known")
        if not isinstance(known, dict):  # premier passage : on note ce qui existe déjà
            self.st["known"] = cur
            return
        pushed = self.st.get("pushed") or {}
        todo = [(fid, m) for fid, m in cur.items() if known.get(fid) != m and now - m > 20 and now - m < 3 * 86400]
        todo.sort(key=lambda x: -x[1])
        for fid, m in todo[:2]:
            known[fid] = m
            if pushed.get(fid, 0) >= m or fid not in targets:  # déjà envoyé, ou pas la dernière version
                continue
            it, f = fmap[fid]
            for d in devices:
                self.push_audio(d["code"], it, f, auto=True)
        for fid, m in cur.items():  # sons anciens ou déjà connus : rien à envoyer
            if fid not in known and now - m >= 3 * 86400:
                known[fid] = m
        self.st["known"] = {k: v for k, v in known.items() if k in cur}


def note_cancels(cancels, msgs):
    """Retient les prods annulées depuis l'app : {id vidéo: heure de l'annulation}.
    Un envoi plus ancien que l'annulation est sauté ; un nouvel envoi (« Renvoyer ») passe."""
    for ev, msg in msgs:
        vid = str((msg or {}).get("cancel") or "")
        if C.VIDEO_ID.match(vid):
            cancels[vid] = max(cancels.get(vid, 0), int(ev.get("time") or time.time()))
    if len(cancels) > 300:
        for k in sorted(cancels, key=cancels.get)[:-300]:
            cancels.pop(k, None)


def phone_targets(fmap):
    """Le son de chaque projet que le téléphone garde : la dernière version, sinon l'instru,
    sinon ton export le plus récent (jamais un enregistrement ou un sample de FL)."""
    return {fid for fid, (_, f) in fmap.items() if f.get("main")}


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
    if ok and got.get("lic"):
        fix = got["lic"]
        log(f"  Licence revue avec la description complète : {fix['from'] or '?'} → {fix['to']}"
            + (f" (« {fix['why']} »)" if fix.get("why") else ""))
    flp = fl = None
    if ok:
        done.add(vid)
        try:  # le lien de la vidéo, gardé aussi dans les réglages
            L.remember_link(f"p:{Path(got.get('path') or detail).parent.name.lower()}", vid)
        except OSError:
            pass
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
    C.reply(code, {"v": vid, "ok": ok, "file" if ok else "err": detail, **({"tb": got["tb"]} if ok and got.get("tb") else {}),
                   **({"lic": got["lic"]["to"]} if ok and got.get("lic") else {})})
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
    last_maint = time.time() - 6 * 3600 + 120  # 1re vérification de mise à jour 2 min après le démarrage
    last_alive = time.time()
    last_cycle = time.time()
    log(f"Melofinds PC {C.VERSION} en ligne.")
    reason = ""
    remote = Remote(st)

    def windows_off():
        """Windows s'éteint (ou ferme la session) : le téléphone est prévenu tout de suite."""
        log("Windows s'éteint : le téléphone est prévenu.")
        for d in C.load_config()["devices"]:
            if d["code"] in announced:
                C.reply(d["code"], {"pc": "offline", "version": C.VERSION, "why": "shutdown"}, timeout=3)
        try:
            P.stop.write_text("shutdown", encoding="utf-8")
        except OSError:
            pass
    stop_watch = C.watch_windows_shutdown(windows_off)
    try:
        while True:
            if P.stop.exists():
                reason = _stop_reason()
                log({"update": "Arrêt pour mise à jour.", "shutdown": "Arrêt de Windows."}.get(reason, "Mis hors ligne."))
                break
            C.beat()
            if P.kick.exists():  # le panneau a changé un projet : liste envoyée tout de suite
                try:
                    P.kick.unlink()
                except OSError:
                    pass
                for d in C.load_config()["devices"]:
                    remote.want.add(d["code"])
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
                        remote.want.add(d["code"])  # la liste des projets part tout de suite
                if time.time() - last_alive > 3000:
                    last_alive = time.time()
                    for d in devices:
                        C.reply(d["code"], {"pc": "alive", "version": C.VERSION})
                if time.time() - last_maint > 6 * 3600 and not once:  # mises à jour : toutes les 6 h
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
                # les appareils jamais entendus d'abord (téléphone qui vient de scanner le QR code) :
                # si ntfy.sh limite les requêtes, ce n'est pas lui qui attend
                for d in sorted(devices, key=lambda x: x["code"] in st["since"]):
                    code, key = d["code"], d["cle"]
                    since = st["since"].get(code) or "12h"
                    try:
                        events = C.poll(code, since)
                    except NET_ERRORS as e:
                        log(f"Pas de connexion à ntfy.sh ({e}).")
                        announced.discard(code)  # se réannoncer quand le réseau revient
                        break
                    msgs = [(ev, C.verify(ev.get("message") or "", key)) for ev in events]
                    cancels = st.setdefault("cancel", {})
                    note_cancels(cancels, msgs)
                    peeked = time.time()
                    for n, (ev, msg) in enumerate(msgs):
                        since = ev.get("id") or since
                        st["since"][code] = since
                        if not msg:
                            log(f"Envoi ignoré (« {d.get('name', '?')} ») : signature absente ou fausse.")
                            continue
                        if msg["n"] in seen:
                            continue
                        if msg.get("cancel"):  # « Annuler » dans la file d'attente de l'app
                            seen.add(msg["n"])
                            vid = str(msg.get("cancel") or "")
                            if C.VIDEO_ID.match(vid):
                                C.reply(code, {"v": vid, "cancel": True})
                            continue
                        vid = "" if msg.get("cmd") else str(msg.get("v") or "")  # écoute sur le PC… : pas un téléchargement
                        if vid and time.time() - peeked > 3 and msgs[-1][0].get("id"):
                            # une annulation envoyée pendant le téléchargement d'avant
                            try:
                                note_cancels(cancels, [(e, C.verify(e.get("message") or "", key)) for e in C.poll(code, msgs[-1][0]["id"])])
                            except NET_ERRORS:
                                pass
                            peeked = time.time()
                        if vid in cancels and cancels[vid] >= (ev.get("time") or 0):
                            seen.add(msg["n"])
                            log(f"Annulée depuis l'app : {msg.get('t') or vid}")
                            C.reply(code, {"v": vid, "cancel": True})
                            continue
                        # prods qui attendent derrière celle-ci (file d'attente du panneau)
                        left = [C.clean_title(m.get("t") or m.get("v"))[:120] for e2, m in msgs[n + 1:]
                                if m and m.get("v") and not m.get("cmd") and m["n"] not in seen and not (str(m.get("v")) in cancels and cancels[str(m.get("v"))] >= (e2.get("time") or 0))]
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
            # un téléphone vient d'envoyer une commande (écoute sur le PC…) : réponse plus rapide
            busy = any(time.time() - t < 180 for t in remote.active.values())
            _sleep(min(C.POLL_SECONDS, 6) if busy else C.POLL_SECONDS)
    finally:
        if reason not in ("update", "shutdown"):  # mise à jour : le nouveau programme se réannonce tout de suite
            try:
                cfg = C.load_config()
                remote.tick(cfg["devices"], cfg, final=True)  # dernière liste des projets
                for d in cfg["devices"]:
                    if d["code"] in announced:
                        C.reply(d["code"], {"pc": "offline", "version": C.VERSION})
            except Exception:
                pass
        stop_watch()
        if remote.listen is not None:
            remote.listen.close()  # le son s'arrête et les fichiers d'écoute sont effacés
        for f in (P.heartbeat, P.pid, P.progress, P.kick) if reason == "update" else (P.heartbeat, P.pid, P.stop, P.progress, P.kick):
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass
        lock.release()
        log("Hors ligne.")
    return 0
