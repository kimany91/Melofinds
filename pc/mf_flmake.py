"""Melofinds PC — FLmake : un projet FL Studio prêt pour chaque prod reçue.

Pour chaque prod téléchargée (si FLmake est activé) :
  1. copie ton projet modèle FL (ton preset de voix : insert 2 avec ton micro et Graillon) ;
  2. y met le BPM de la prod et pose l'instru sur la piste du haut (« INSTRU ») ;
  3. enregistre le projet dans un dossier au nom de la prod (comme une sauvegarde FL) ;
  4. ouvre FL Studio sur ce projet. Le script « Melofinds FLmake » (dans FL) règle alors
     Graillon sur la clé de la prod et sauvegarde.

Le projet est modifié directement dans le fichier .flp (suite d'événements de FL Studio).
Seuls le tempo, le titre, le canal de l'instru et son clip sont touchés ; tout le reste du
modèle (mixer, preset de voix, plugins) est recopié octet pour octet.

Formats vérifiés sur de vrais projets FL 20, FL 25 et FL 2026 (PyFLP, flpdiff, flpkit) :
  - FL 25+ : l'événement 172 n'a qu'un octet (contrôle : nombre de canaux = en-tête) ;
  - clip de playlist : 32 octets (FL ≤ 20), 60 (FL 21-24), 80 (FL 25+) ;
  - clip audio entier : décalages −1.0 / −1.0 ; piste 1 stockée sous le n° 499 ;
  - tempo absent quand il vaut la valeur par défaut : on l'ajoute en fin de fichier.
"""

import base64
import os
import shutil
import re
import struct
import subprocess
import time
from pathlib import Path

import mf_core as C
from mf_core import P, log

WORD, DWORD, TEXT = 64, 128, 192
EV_CHANNEL_TYPE = 21          # 4 = clip audio
EV_ROUTE = 22                 # insert du mixer (anciens projets)
EV_CHANNEL_NEW = 64           # début d'un canal (n° du canal)
EV_TEMPO_COARSE = 66          # très anciens projets : tempo entier
EV_TEMPO_FINE_OLD = 93        # très anciens projets : partie décimale
EV_ARRANGEMENT = 99           # début d'un arrangement (playlist)
EV_TEMPO = 156                # tempo × 1000
EV_TITLE = 194                # titre du projet
EV_SAMPLE_PATH = 196          # fichier du son d'un canal
EV_VERSION = 199              # version de FL (texte ASCII)
EV_PLUGIN_INTERNAL = 201      # nom interne du plugin ('' pour un son)
EV_NAME = 203                 # nom du canal
EV_CHANNEL_RUNTIME = 212      # identifiants de voix du canal
EV_PLAYLIST = 233             # clips de la playlist
EV_TRACK_DATA = 238           # une piste de la playlist
EV_TRACK_NAME = 239           # nom de la piste
NEW_TEXT_IDS = (TEXT + 49, TEXT + 39, TEXT + 47)
PATTERN_BASE = 20480
TRACK_TOP = 499               # piste 1 (les pistes sont stockées à l'envers)
HEADER = struct.Struct("<4sIhHH")
SIZE_RULES = ({172: 1}, {172: 3}, {})  # FL 2026/25 (vérifié), variante, classique

# Canal « clip audio » authentique (sans son), recopié de vraies sauvegardes FL :
# toutes les valeurs par défaut dont FL a besoin pour jouer le son.
CLIP_SCOPE = {
    25: base64.b64decode("QDoAFQTJAgAA1DQAAAAAAAAAAP////8AAAAAUAAAAAMAAAAAAAAAAAAAAAAAAAA6AAAAZAAAAAAAAAAAAAAAywIAAJtLAAAAgIItFAApAQAB0RQAAAAAABkAAAAAAAAEAAAAkAAAAIqAAIAAiwAAAQBZAABhgAAwAEWAAFYAAUcABFMAAEoAAEsAAEwAAFUACIMAAIAARgAAaAEAMgHbGAAZAAAQJwAAAAAAAAABAAAAAAAAAAAAAOUUAAAAAAAyAAAAAAAAAAAAAAAAAADdCQAAAAD0AQAAANeoAYwAAAAAAAAAAQAAAP////88AAAAAACAPwAAgD8AAIA/AACAPwAAgD8AAAAAAwAAAAAAAAAABAAAMAAAAAAAAQCnBQAAAAAAAAABAAAAAAAAAAAAAQAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAACAAAA/v////////8AAAAAAAAAAAAAAAAAAAAAAADwPwAAAAAAAAAA/////wEBAAAAAAAAAADgP4QAAAAAkAAAAACRAAAAACAA5BBkAAAAAAAAAAAAAAAAAAAA5BA8AAAAAAAAAAAAAAAAAAAA2kQAAAAAAAAAAGQAAAAgTgAAIE4AADB1AAAyAAAAIE4AAAAAAABkAAAAIE4AAAAAAAC2gAAAAAAAAAAAAAAAAAAAAAAAANpEBAAAAAAAAABkAAAAIE4AACBOAAAwdQAAMgAAACBOAAAAAAAAZAAAACBOAAAAAAAAtoAAAAAAAAAAAAAAAAAAAJv////aRAAAAAAAAAAAZAAAACBOAAAgTgAAMHUAADIAAAAgTgAAAAAAAGQAAAAgTgAAAAAAALaAAAAAAAAAAAAAAAAAAAAAAAAA2kQAAAAAAAAAAGQAAAAgTgAAIE4AADB1AAAyAAAAIE4AAAAAAABkAAAAIE4AAAAAAAC2gAAAAAAAAAAAAAAAAAAAAAAAANpEAAAAAAAAAABkAAAAIE4AACBOAAAwdQAAMgAAACBOAAAAAAAAZAAAACBOAAAAAAAAtoAAAAAAAAAAAAAAAAAAAAAAAACPBgAAABQAxAIAAKr/////MwA="),
    20: base64.b64decode("QAsAFQTJAgAA1DQAAAAAAAAAAP////8AAAAAUAAAAAAAAAAAAAAAAAAAAAAAAACoAAAA/AAAAAAAAAAAAAAAywIAAJsAAAAAgFxlagAAAdEUAAAAAAAZAAAAAAAABAAAAJAAAACKgACAAIsAAAEAWQAAYYAARYAAVgABRwAEUwAASgAASwAATAAAVQAIgwAAgABGAAAWANsYABkAABAnAAAAAAAAAAEAAAAAAAAAAAAA5RQAAAAAADIAAAAAAAAAAAAAAAAAAN0JAAAAAPQBAAAA154BjAAAAAAAAAABAAAA/////zwAAAAAAIA/AACAPwAAgD8AAIA/AACAPwAAAAADAAAAAAAAAAAEAAAwAAAAAAABAKcFAAAAAAAAAAEAAAAAAAAAAAABAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAIAAAD+/////////wAAAAAAAAAAAAAAAAAAAAAAAPA/AAAAAAAAAAD/////AQGEAAAAAJAAAAAAkQAAAAAgAOQQZAAAAAAAAAAAAAAAAAAAAOQQPAAAAAAAAAAAAAAAAAAAANpEAAAAAAAAAABkAAAAIE4AACBOAAAwdQAAMgAAACBOAAAAAAAAZAAAACBOAAAAAAAAtoAAAAAAAAAAAAAAAAAAAAAAAADaRAQAAAAAAAAAZAAAACBOAAAgTgAAMHUAADIAAAAgTgAAAAAAAGQAAAAgTgAAAAAAALaAAAAAAAAAAAAAAAAAAACb////2kQAAAAAAAAAAGQAAAAgTgAAIE4AADB1AAAyAAAAIE4AAAAAAABkAAAAIE4AAAAAAAC2gAAAAAAAAAAAAAAAAAAAAAAAANpEAAAAAAAAAABkAAAAIE4AACBOAAAwdQAAMgAAACBOAAAAAAAAZAAAACBOAAAAAAAAtoAAAAAAAAAAAAAAAAAAAAAAAADaRAAAAAAAAAAAZAAAACBOAAAgTgAAMHUAADIAAAAgTgAAAAAAAGQAAAAgTgAAAAAAALaAAAAAAAAAAAAAAAAAAAAAAAAAjwIAAAAUAMQCAAA="),
}
INSTRU_NAMES = re.compile(r"\b(instrus?|instrumentale?s?|beats?|prods?|prod de|la prod)\b", re.I)


class FlpError(Exception):
    pass


def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _parse_events(data, start, end, rules):
    events, i = [], start
    while i < end:
        eid = data[i]
        i += 1
        if eid in rules:
            n = rules[eid]
        elif eid < WORD:
            n = 1
        elif eid < DWORD:
            n = 2
        elif eid < TEXT:
            n = 4
        else:
            n, shift = 0, 0
            while True:
                if i >= end:
                    raise FlpError("projet FL abîmé (taille d'événement)")
                b = data[i]
                i += 1
                n |= (b & 0x7F) << shift
                shift += 7
                if not b & 0x80:
                    break
        if i + n > end:
            raise FlpError("projet FL abîmé (événement coupé)")
        events.append([eid, bytes(data[i:i + n])])
        i += n
    return events


def read_flp(data):
    """→ (format, nb de canaux, ppq, [[id, données], …]). Choisit la règle de taille
    qui relit exactement autant de canaux que l'en-tête en annonce."""
    if len(data) < 22:
        raise FlpError("fichier trop court")
    magic, size, fmt, nchan, ppq = HEADER.unpack_from(data, 0)
    if magic != b"FLhd" or size != 6 or data[14:18] != b"FLdt":
        raise FlpError("ce n'est pas un projet FL Studio (.flp)")
    total = struct.unpack_from("<I", data, 18)[0]
    if 22 + total != len(data):
        raise FlpError("projet FL abîmé (taille incorrecte)")
    first = None
    for rules in SIZE_RULES:
        try:
            events = _parse_events(data, 22, len(data), rules)
        except FlpError as e:
            first = first or e
            continue
        if sum(1 for e, _ in events if e == EV_CHANNEL_NEW) == nchan:
            return fmt, nchan, ppq, events
        first = first or FlpError("projet FL illisible (version de FL non reconnue)")
    raise first


def write_flp(fmt, nchan, ppq, events):
    body = bytearray()
    for eid, val in events:
        body.append(eid)
        if eid >= TEXT:
            body += _varint(len(val))
        body += val
    return HEADER.pack(b"FLhd", 6, fmt, nchan, ppq) + b"FLdt" + struct.pack("<I", len(body)) + bytes(body)


def fl_version(events):
    for eid, val in events:
        if eid == EV_VERSION:
            parts = [int(x) for x in re.findall(r"\d+", val.decode("ascii", "replace"))[:3]]
            return tuple(parts) or (0,)
    return (0,)


def _unicode(events):
    """FL 11.5+ écrit les textes en UTF-16."""
    return list(fl_version(events)[:2]) >= [11, 5] or fl_version(events) == (0,)


def _text(val, uni):
    try:
        return (val.decode("utf-16-le") if uni else val.decode("cp1252")).rstrip("\0")
    except UnicodeDecodeError:
        return ""


def _enc(s, uni):
    return (s + "\0").encode("utf-16-le") if uni else (s + "\0").encode("cp1252", "replace")


def _stride(blob, version):
    """Taille d'un clip : détectée sur les clips existants (signature 20480), sinon
    d'après la version de FL."""
    if blob:
        for size in (80, 60, 32):
            if len(blob) % size == 0 and all(struct.unpack_from("<H", blob, k + 4)[0] == PATTERN_BASE
                                              for k in range(0, len(blob), size)):
                return size
        return None
    return 80 if version[0] >= 25 else 60 if version[0] >= 21 else 32


def _clip_record(size, position, channel, length, track_rv, clip_id, template=None):
    """Un clip audio entier (non coupé) sur la playlist."""
    if template and len(template) == size:
        rec = bytearray(template)
    else:
        rec = bytearray(size)
        struct.pack_into("<HH4B", rec, 16, 120, 64, 64, 100, 128, 128)
        if size >= 60:
            struct.pack_into("<f", rec, 52, 1.0)
        if size >= 80:
            struct.pack_into("<d", rec, 64, 1.0)
    struct.pack_into("<IHHIHH", rec, 0, position, PATTERN_BASE, channel, length, track_rv, 0)
    struct.pack_into("<ff", rec, 24, -1.0, -1.0)
    if size >= 36:
        struct.pack_into("<I", rec, 32, clip_id)
    return bytes(rec)


class Project:
    """Vue d'un projet : canaux, arrangement, pistes, clips."""

    def __init__(self, data):
        self.fmt, self.nchan, self.ppq, self.events = read_flp(data)
        self.version = fl_version(self.events)
        self.uni = _unicode(self.events)

    def channels(self):
        """{n° : {start, end, type, sample, name}} — un canal va de son 64 au suivant
        (ou au début des arrangements)."""
        out, cur = {}, None
        for i, (e, v) in enumerate(self.events):
            if e == EV_CHANNEL_NEW:
                if cur is not None:
                    out[cur]["end"] = i
                cur = struct.unpack("<H", v)[0]
                out[cur] = {"start": i, "end": None, "type": None, "sample": "", "name": ""}
            elif cur is not None and e == EV_ARRANGEMENT:
                out[cur]["end"] = i
                cur = None
            elif cur is not None:
                c = out[cur]
                if e == EV_CHANNEL_TYPE and c["type"] is None:
                    c["type"] = v[0]
                elif e == EV_SAMPLE_PATH:
                    c["sample"] = _text(v, self.uni)
                elif e == EV_NAME and not c["name"]:
                    c["name"] = _text(v, self.uni)
        if cur is not None:
            out[cur]["end"] = len(self.events)
        return out

    def arrangement(self):
        """Premier arrangement : (début, fin, index du clip-blob ou None, [(n° piste, nom)])."""
        start = next((i for i, (e, _) in enumerate(self.events) if e == EV_ARRANGEMENT), None)
        if start is None:
            raise FlpError("pas de playlist dans le modèle")
        end = next((i for i in range(start + 1, len(self.events)) if self.events[i][0] == EV_ARRANGEMENT), len(self.events))
        pl = next((i for i in range(start, end) if self.events[i][0] == EV_PLAYLIST), None)
        tracks, last = [], None
        for i in range(start, end):
            e, v = self.events[i]
            if e == EV_TRACK_DATA and len(v) >= 4:
                last = struct.unpack_from("<I", v)[0]
                tracks.append([last, ""])
            elif e == EV_TRACK_NAME and tracks:
                tracks[-1][1] = _text(v, self.uni)
        return start, end, pl, tracks

    def instru_track(self):
        """Piste de l'instru : celle nommée « INSTRU » (ou beat / prod), sinon la piste 1."""
        _, _, _, tracks = self.arrangement()
        for n, name in tracks:
            if name and INSTRU_NAMES.search(name):
                return n, name
        return 1, (tracks[0][1] if tracks and tracks[0][0] == 1 else "")

    def clips(self):
        _, _, pl, _ = self.arrangement()
        blob = self.events[pl][1] if pl is not None else b""
        size = _stride(blob, self.version)
        if size is None:
            raise FlpError("clips de la playlist illisibles (version de FL non reconnue)")
        out = []
        for k in range(0, len(blob), size):
            pos, base, idx, length, rv, grp = struct.unpack_from("<IHHIHH", blob, k)
            out.append({"at": k, "pos": pos, "item": idx, "len": length, "track": TRACK_TOP + 1 - rv})
        return size, blob, out


def inspect_template(path):
    """Vérifie le modèle → {ok, msg, …}."""
    try:
        pr = Project(Path(path).read_bytes())
        track, tname = pr.instru_track()
        size, _, clips = pr.clips()
    except (OSError, FlpError) as e:
        return {"ok": False, "msg": f"Modèle illisible : {e}"}
    chans = pr.channels()
    on_track = [c for c in clips if c["track"] == track and c["item"] < PATTERN_BASE and chans.get(c["item"], {}).get("sample")]
    tempo = next((struct.unpack("<I", v)[0] / 1000 for e, v in pr.events if e == EV_TEMPO), None)
    where = f"piste {track}" + (f" « {tname} »" if tname else "")
    ver = ".".join(str(x) for x in pr.version[:2])
    return {"ok": True, "track": track, "track_name": tname, "replace": bool(on_track), "tempo": tempo, "ppq": pr.ppq, "version": pr.version,
            "msg": f"Modèle OK (FL {ver}) : l'instru sera posée sur la {where}, au début, envoyée vers son insert."}


def wav_seconds(path):
    """Durée d'un .wav (lecture de l'en-tête)."""
    with open(path, "rb") as f:
        head = f.read(12)
        if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            raise FlpError("pas un .wav")
        rate = align = 0
        while True:
            h = f.read(8)
            if len(h) < 8:
                break
            cid, size = h[:4], struct.unpack("<I", h[4:])[0]
            if cid == b"fmt ":
                fmtb = f.read(size)
                rate, align = struct.unpack_from("<I", fmtb, 4)[0], struct.unpack_from("<H", fmtb, 12)[0]
                if size & 1:
                    f.seek(1, 1)
            elif cid == b"data":
                if not rate or not align:
                    break
                if size in (0, 0xFFFFFFFF):  # flux : taille inconnue → jusqu'à la fin du fichier
                    size = os.path.getsize(path) - f.tell()
                return size / (rate * align)
            else:
                f.seek(size + (size & 1), 1)
    raise FlpError("durée du .wav illisible")


def _new_channel_scope(pr, iid, name, sample, insert=1):
    """Événements d'un nouveau canal « clip audio » : cloné sur un clip audio du modèle
    s'il y en a un, sinon sur un clip audio authentique de la même époque de FL."""
    chans = pr.channels()
    src = next((c for c in chans.values() if c["type"] == 4 and c["sample"]), None)
    if src:
        scope = [list(ev) for ev in pr.events[src["start"]:src["end"]]]
    else:
        raw = CLIP_SCOPE[25 if pr.version[0] >= 21 else 20]
        scope = _parse_events(raw, 0, len(raw), {})
    # identifiants de voix uniques (octets 36 et 40 du bloc 212), comme FL
    maxf = [0, 0]
    for c in chans.values():
        for e, v in pr.events[c["start"]:c["end"]]:
            if e == EV_CHANNEL_RUNTIME and len(v) >= 44:
                maxf[0] = max(maxf[0], struct.unpack_from("<I", v, 36)[0])
                maxf[1] = max(maxf[1], struct.unpack_from("<I", v, 40)[0])
    out, has_sample, has_route = [], False, False
    for e, v in scope:
        if e == EV_CHANNEL_NEW:
            v = struct.pack("<H", iid)
        elif e == EV_CHANNEL_TYPE:
            v = b"\x04"
        elif e == EV_PLUGIN_INTERNAL:
            v = _enc("", pr.uni)
        elif e == EV_NAME:
            v = _enc(name, pr.uni)
        elif e == EV_SAMPLE_PATH:
            v, has_sample = _enc(sample, pr.uni), True
        elif e == EV_ROUTE:
            v, has_route = bytes([insert]), True
        elif e == EV_CHANNEL_RUNTIME and len(v) >= 44:
            b = bytearray(v)
            struct.pack_into("<II", b, 36, maxf[0] + 1, maxf[1] + 1)
            v = bytes(b)
        out.append([e, v])
    if not has_sample:
        out.append([EV_SAMPLE_PATH, _enc(sample, pr.uni)])
    if not has_route and pr.version[0] < 25:
        out.insert(1, [EV_ROUTE, bytes([insert])])
    return out


def build_project(template, wav, out_path, bpm=None, title=None):
    """Écrit le projet de la prod. Renvoie un petit résumé (texte)."""
    pr = Project(Path(template).read_bytes())
    ev = pr.events
    done = []
    wav = Path(wav).resolve()
    sample = str(wav)
    tempo = float(bpm) if bpm and 40 <= float(bpm) <= 300 else None
    # 1) Tempo : remplacé, ou ajouté en fin de fichier s'il manque (FL ne l'écrit pas
    #    quand il vaut la valeur par défaut ; le dernier lu l'emporte).
    if tempo:
        found = False
        for e in ev:
            if e[0] == EV_TEMPO:
                e[1] = struct.pack("<I", int(round(tempo * 1000)))
                found = True
            elif e[0] == EV_TEMPO_COARSE:
                e[1] = struct.pack("<H", int(tempo))
            elif e[0] == EV_TEMPO_FINE_OLD:
                e[1] = struct.pack("<H", 0)
        if not found:
            ev.append([EV_TEMPO, struct.pack("<I", int(round(tempo * 1000)))])
        done.append(f"{bpm} BPM")
    else:
        tempo = next((struct.unpack("<I", v)[0] / 1000 for e, v in ev if e == EV_TEMPO), 140.0)
    try:
        ticks = max(1, int(round(wav_seconds(wav) * tempo / 60 * pr.ppq)))
    except (OSError, FlpError, ValueError):
        ticks = pr.ppq * 4 * 64  # 64 mesures si la durée est illisible
    # 2) L'instru sur la piste INSTRU
    track, tname = pr.instru_track()
    size, blob, clips = pr.clips()
    chans = pr.channels()
    mine = next((c for c in clips if c["track"] == track and c["item"] < PATTERN_BASE and chans.get(c["item"], {}).get("sample")), None)
    if mine:  # le modèle a déjà un son sur cette piste : on le remplace par l'instru
        ch = chans[mine["item"]]
        for i in range(ch["start"], ch["end"]):
            if ev[i][0] == EV_SAMPLE_PATH:
                ev[i][1] = _enc(sample, pr.uni)
            elif ev[i][0] == EV_NAME:
                ev[i][1] = _enc(wav.stem[:120], pr.uni)
        rec = bytearray(blob[mine["at"]:mine["at"] + size])
        struct.pack_into("<II", rec, 0, 0, PATTERN_BASE | (mine["item"] << 16))
        struct.pack_into("<I", rec, 8, ticks)
        struct.pack_into("<ff", rec, 24, -1.0, -1.0)
        new_blob = blob[:mine["at"]] + bytes(rec) + blob[mine["at"] + size:]
        _, _, pl, _ = pr.arrangement()
        ev[pl][1] = new_blob
    else:  # nouveau canal « clip audio » + clip au début de la piste
        iid = max(chans) + 1 if chans else 0
        scope = _new_channel_scope(pr, iid, wav.stem[:120], sample)
        arr = next(i for i, (e, _) in enumerate(ev) if e == EV_ARRANGEMENT)
        ev[arr:arr] = scope
        pr.nchan += 1
        start, end, pl, _ = pr.arrangement()
        ids = [struct.unpack_from("<I", blob, k + 32)[0] for k in range(0, len(blob), size)] if size >= 36 else []
        rec = _clip_record(size, 0, iid, ticks, TRACK_TOP + 1 - track, max(ids, default=0) + 1, blob[:size] if blob else None)
        if pl is not None:
            ev[pl][1] = rec + blob
        else:
            at = next((i for i in range(start, end) if ev[i][0] == EV_TRACK_DATA), end)
            ev[at:at] = [[EV_PLAYLIST, rec]]
    done.append(f"instru sur la piste {track}" + (f" « {tname} »" if tname else ""))
    if title:
        for e in ev:
            if e[0] == EV_TITLE:
                e[1] = _enc(title[:120], pr.uni)
    data = write_flp(pr.fmt, pr.nchan, pr.ppq, ev)
    check = Project(data)  # contrôle : le fichier écrit se relit, l'instru est en place
    if not any(c["track"] == track and c["item"] < PATTERN_BASE and check.channels().get(c["item"], {}).get("sample") == sample
               for c in check.clips()[2]):
        raise FlpError("contrôle raté : l'instru n'est pas dans le projet écrit")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".flp.tmp")
    tmp.write_bytes(data)
    tmp.replace(out_path)
    return ", ".join(done)


# ---------------------------------------------------------------------------
# Réglages, FL Studio, script

def settings(cfg=None):
    cfg = cfg if cfg is not None else C.load_config()
    fm = cfg.get("flmake") if isinstance(cfg.get("flmake"), dict) else {}
    fm.setdefault("on", False)
    fm.setdefault("template", "")
    fm.setdefault("dossier", str(Path(cfg.get("dossier") or C.default_folder())))
    fm.setdefault("fl", "")
    fm.setdefault("open", True)
    return fm


def find_fl():
    """FL Studio installé (dossiers habituels, version la plus récente)."""
    found = []
    for env in ("PROGRAMFILES", "PROGRAMW6432", "PROGRAMFILES(X86)"):
        base = os.environ.get(env)
        if not base:
            continue
        d = Path(base) / "Image-Line"
        if d.is_dir():
            for sub in d.glob("FL Studio*"):
                for exe in ("FL64.exe", "FL.exe"):
                    if (sub / exe).is_file():
                        found.append(sub / exe)
                        break
    found.sort(key=lambda p: [int(x) for x in re.findall(r"\d+", p.parent.name)] or [0], reverse=True)
    return str(found[0]) if found else ""


def fl_exe(fm):
    p = fm.get("fl") or ""
    return p if p and Path(p).is_file() and Path(p).suffix.lower() == ".exe" else find_fl()


def documents_dir():
    if C.WINDOWS:
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:  # Mes documents
                return Path(buf.value)
        except Exception:
            pass
    return Path.home() / "Documents"


def script_dir():
    return documents_dir() / "Image-Line" / "FL Studio" / "Settings" / "Hardware" / "Melofinds FLmake"


def job_files():
    d = P.base / "flmake"
    return d, d / "job.txt", d / "done.txt"


SCRIPT = r'''# name=Melofinds FLmake
# url=https://github.com/kimany91/Melofinds
# Script installé par Melofinds PC (FLmake). Quand Melofinds PC ouvre un projet préparé
# pour une prod, ce script règle Graillon sur la clé de la prod puis sauvegarde le projet.
# Il ne fait rien d'autre. Fichiers lus / écrits : JOB et DONE ci-dessous.
import midi
import mixer
import plugins
import transport

try:
    import time
except Exception:
    time = None

JOB = r"__JOB__"
DONE = r"__DONE__"
FLAT = {"DB": "C#", "EB": "D#", "FB": "E", "GB": "F#", "AB": "G#", "BB": "A#", "CB": "B", "E#": "F", "B#": "C"}
S = {"armed": True, "tick": 0, "wait": 0, "last": ""}


def _job():
    try:
        with open(JOB, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except Exception:
        return None
    job = {}
    for line in lines:
        if "=" in line:
            k, v = line.split("=", 1)
            job[k.strip()] = v.strip()
    if not job.get("id") or job.get("id") == S["last"]:
        return None
    try:
        with open(DONE, "r", encoding="utf-8") as f:
            if ("id=" + job["id"]) in f.read():
                return None
    except Exception:
        pass
    if time is not None:
        try:
            if time.time() - float(job.get("created", "0")) > 900:
                return None
        except Exception:
            pass
    return job


def _done(job, ok, msg):
    S["last"] = job.get("id", "")
    try:
        with open(DONE, "w", encoding="utf-8") as f:
            f.write("id=%s\nok=%d\nmsg=%s\n" % (job.get("id", ""), 1 if ok else 0, msg))
    except Exception:
        pass


def _note(txt):
    t = str(txt or "").strip().upper().replace("♯", "#").replace("♭", "B")
    if len(t) >= 2 and t[0] in "ABCDEFG" and t[1] in "#B" and (len(t) == 2 or not t[2].isalpha() or t[1] == "#" or t[2] == "M"):
        n = t[:2]
    elif t[:1] and t[0] in "ABCDEFG" and (len(t) == 1 or not t[1].isalpha() or t[1:4] in ("MIN", "MAJ") or t[1:] == "M"):
        n = t[0]
    else:
        return None
    return FLAT.get(n, n)


def _mode(txt):
    t = str(txt or "").lower()
    if "minor" in t or t.endswith("min") or " min" in t or t.endswith("m") and len(t) <= 3:
        return "min"
    if "major" in t or "maj" in t:
        return "maj"
    return None


def _graillon():
    order = [2] + [t for t in range(0, mixer.trackCount()) if t != 2]
    for t in order:
        for s in range(10):
            try:
                if plugins.isValid(t, s) and "graillon" in plugins.getPluginName(t, s).lower():
                    return t, s
            except Exception:
                pass
    return None


def _set(i, t, s, ok):
    try:
        before = plugins.getParamValue(i, t, s)
    except Exception:
        before = None
    for step in range(0, 241):
        v = step / 240.0
        plugins.setParamValue(v, i, t, s)
        if ok(plugins.getParamValueString(i, t, s)):
            return True
    if before is not None:
        plugins.setParamValue(before, i, t, s)
    return False


def _apply(job, t, s):
    want = FLAT.get(job.get("note", "").upper(), job.get("note", "").upper())
    mode = job.get("mode", "")
    names = []
    for i in range(min(plugins.getParamCount(t, s), 600)):
        try:
            names.append((i, plugins.getParamName(i, t, s).lower()))
        except Exception:
            pass
    keys = [i for i, n in names if ("key" in n or "root" in n or "tonic" in n) and "keep" not in n]
    scales = [i for i, n in names if "scale" in n]
    did = []
    if keys:
        if _set(keys[0], t, s, lambda x: _note(x) == want):
            did.append("cle " + want)
        if mode and scales:
            if _set(scales[0], t, s, lambda x: _mode(x) == mode and "penta" not in str(x).lower() and "harm" not in str(x).lower() and "melod" not in str(x).lower()):
                did.append(mode)
    elif scales:
        if _set(scales[0], t, s, lambda x: _note(x) == want and (not mode or _mode(x) == mode)):
            did.append("gamme " + want + (" " + mode if mode else ""))
    return did, [n for _, n in names if "key" in n or "root" in n or "scale" in n][:6]


def OnInit():
    S["armed"] = True


def OnProjectLoad(status):
    if status == getattr(midi, "PL_LoadOk", 100):
        S["armed"] = True
        S["wait"] = 0


def OnIdle():
    S["tick"] += 1
    if S["tick"] % 25 or not S["armed"]:
        return
    job = _job()
    if not job:
        return
    try:
        bpm = float(job.get("bpm") or 0)
        try:
            cur = float(mixer.getCurrentTempo())
            if cur > 1000:
                cur = cur / 1000.0
        except Exception:
            cur = bpm
        if bpm:
            if abs(cur - bpm) > 0.6:  # pas encore le projet de la prod
                S["wait"] += 1
                if S["wait"] > 240:
                    _done(job, False, "projet de la prod pas ouvert dans FL")
                    S["armed"] = False
                return
        g = _graillon()
        if not g:
            S["wait"] += 1
            if S["wait"] > 120:
                _done(job, False, "Graillon introuvable dans le mixer")
                S["armed"] = False
            return
        did, seen = [], []
        if job.get("note"):
            did, seen = _apply(job, g[0], g[1])
        transport.globalTransport(getattr(midi, "FPT_Save", 92), 1)
        if job.get("note") and not did:
            _done(job, False, "cle Graillon non trouvee (parametres : %s) ; projet sauvegarde" % ", ".join(seen))
        else:
            _done(job, True, "Graillon : %s ; projet sauvegarde" % (", ".join(did) or "cle inconnue, inchange"))
    except Exception as e:
        _done(job, False, "erreur : %s" % e)
    S["armed"] = False
    S["wait"] = 0
'''


def script_text():
    _, job, done = job_files()
    return SCRIPT.replace("__JOB__", str(job)).replace("__DONE__", str(done))


def install_script():
    d = script_dir()
    d.mkdir(parents=True, exist_ok=True)
    f = d / "device_MelofindsFLmake.py"
    f.write_text(script_text(), encoding="utf-8")
    return f


def script_installed():
    f = script_dir() / "device_MelofindsFLmake.py"
    try:
        return f.read_text(encoding="utf-8") == script_text()
    except OSError:
        return False


def split_key(key):
    """« C# min » → ("C#", "min")."""
    m = re.fullmatch(r"([A-G][#b]?)(?: (min|maj))?", str(key or "").strip())
    return (m.group(1), m.group(2) or "") if m else ("", "")


def project_path(folder, name):
    """« Dossier/Nom de la prod/Nom de la prod.flp », comme une sauvegarde FL."""
    folder = Path(folder)
    sub, i = name, 2
    while (folder / sub).exists():
        sub = f"{name} ({i})"
        i += 1
    p = folder / sub / f"{sub}.flp"
    if not C.inside(p, folder) or p.suffix.lower() != ".flp":
        raise FlpError("nom de projet refusé")
    return p


def make(wav, key=None, bpm=None, title=None, cfg=None):
    """Écrit le projet FL de la prod → (chemin du .flp, texte à afficher)."""
    fm = settings(cfg)
    if not fm["template"] or not Path(fm["template"]).is_file():
        raise FlpError("choisis ton preset de voix (projet modèle FL) dans Melofinds PC → FLmake")
    wav = Path(wav)
    if not C.is_wav(wav):
        raise FlpError("l'instru n'est pas un .wav")
    root = Path(fm["dossier"])
    created = None
    try:
        in_own_folder = C.inside(wav, root) and wav.parent.resolve() != root.resolve()
    except OSError:
        in_own_folder = False
    if in_own_folder:  # la prod est déjà dans son dossier de projet : le .flp va à côté
        out, i = wav.parent / f"{wav.parent.name}.flp", 2
        while out.exists():
            out = wav.parent / f"{wav.parent.name} ({i}).flp"
            i += 1
        instru = wav
    else:  # prod d'ailleurs : nouveau dossier de projet, avec une copie de la prod dedans
        out = project_path(root, wav.stem)
        created = out.parent
        created.mkdir(parents=True)
        instru = created / f"{created.name}.wav"
        shutil.copy2(wav, instru)
    try:
        summary = build_project(fm["template"], instru, out, bpm=C.valid_bpm(bpm), title=title or out.stem)
    except Exception:
        if created:
            shutil.rmtree(created, ignore_errors=True)
        raise
    note, mode = split_key(C.valid_key(key))
    key_txt = f", clé {note}{(' ' + mode) if mode else ''}" if note else ", clé inconnue"
    return out, f"Projet FL « {out.name} » prêt ({summary}{key_txt})"


def open_in_fl(flp, key=None, bpm=None, cfg=None):
    """Ouvre le projet dans FL Studio et demande au script de régler Graillon puis sauvegarder."""
    fm = settings(cfg)
    flp = Path(flp)
    if flp.suffix.lower() != ".flp" or not flp.is_file():
        raise FlpError("projet introuvable")
    if key is None and bpm is None:  # clé et BPM lus dans le nom : « Titre [C# min, 140 BPM] »
        key, bpm = C.find_key(flp.stem), C.find_bpm(flp.stem)
    note, mode = split_key(C.valid_key(key))
    d, job, _ = job_files()
    if note:  # le script FL règle Graillon (et sauvegarde) seulement quand on connaît la clé
        d.mkdir(parents=True, exist_ok=True)
        job.write_text(f"id={int(time.time() * 1000):x}\ncreated={time.time():.0f}\nflp={flp}\nnote={note}\nmode={mode}\nbpm={C.valid_bpm(bpm) or ''}\n",
                       encoding="utf-8")
    exe = fl_exe(fm)
    if not exe:
        raise FlpError("FL Studio introuvable : choisis FL64.exe dans Melofinds PC → FLmake")
    subprocess.Popen([exe, str(flp)], close_fds=True)
    return "FL Studio ouvert" + (f" (Graillon → {note}{(' ' + mode) if mode else ''})" if note else "")


def recent_projects(cfg=None, n=15):
    folder = Path(settings(cfg)["dossier"])
    try:
        files = [p for p in [*folder.glob("*/*.flp"), *folder.glob("*.flp")] if p.is_file()]
    except OSError:
        return []
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:n]


def last_result():
    """Dernier compte rendu du script FL : (id, ok, message) ou None."""
    _, _, done = job_files()
    try:
        data = dict(l.split("=", 1) for l in done.read_text(encoding="utf-8").splitlines() if "=" in l)
    except (OSError, ValueError):
        return None
    return data.get("id"), data.get("ok") == "1", data.get("msg", "")


def maybe_make(path, key, bpm, title, cfg):
    """Appelé après chaque prod téléchargée → (projet .flp ou None, texte). Rien si FLmake est désactivé."""
    if not settings(cfg)["on"]:
        return None, None
    try:
        out, r = make(path, key, bpm, title, cfg)
    except (OSError, FlpError) as e:
        out, r = None, f"FLmake : {e}"
    log(r)
    return out, r


def open_last(flp, key, bpm, cfg):
    """Après un lot de prods : FL s'ouvre une seule fois, sur la dernière."""
    fm = settings(cfg)
    if not flp or not fm["on"] or not fm.get("open", True):
        return None
    try:
        r = open_in_fl(flp, key, bpm, cfg)
    except (OSError, FlpError) as e:
        r = f"FLmake : {e}"
    log(r)
    return r
