"""Melofinds PC — FLmake : un projet FL Studio prêt pour chaque prod reçue.

Pour chaque prod téléchargée (si FLmake est activé) :
  1. copie ton projet modèle FL (ton preset de voix : insert 2 avec ton micro et Graillon) ;
  2. y met le BPM de la prod et remplace le son de la piste 1 (→ insert 1) par l'instru ;
  3. enregistre le projet sous le nom de la prod dans ton dossier de projets ;
  4. ouvre FL Studio sur ce projet. Le script « Melofinds FLmake » (dans FL) règle alors
     Graillon sur la clé de la prod et sauvegarde.

Le projet est modifié directement dans le fichier .flp (format à événements de FL
Studio) : seuls le tempo, le chemin du son de la piste de l'instru, la longueur de son
clip et le titre changent ; tout le reste du modèle est recopié octet pour octet.
"""

import os
import re
import struct
import subprocess
import time
from pathlib import Path

import mf_core as C
from mf_core import P, log

# --- Format .flp : en-tête « FLhd » + bloc « FLdt » d'événements (id sur 1 octet).
#     id < 64 : 1 octet · < 128 : 2 octets · < 192 : 4 octets · sinon taille (varint) + données
WORD, DWORD, TEXT = 64, 128, 192
EV_CHANNEL_NEW = 64           # début d'un canal (n° du canal)
EV_TEMPO_COARSE = 66          # anciens projets : tempo entier
EV_TEMPO_FINE_OLD = 93        # anciens projets : partie décimale
EV_TEMPO = 156                # tempo × 1000
EV_TITLE = 194                # titre du projet (Infos du projet)
EV_SAMPLE_PATH = 196          # fichier du son d'un canal
EV_VERSION = 199              # version de FL (texte ASCII)
EV_PLAYLIST = 233             # clips de la playlist
NEW_TEXT_IDS = (TEXT + 49, TEXT + 39, TEXT + 47)
PATTERN_BASE = 20480
HEADER = struct.Struct("<4sIhHH")


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


def read_flp(data):
    """→ (format, nb de canaux, ppq, [[id, données], …])"""
    if len(data) < 22:
        raise FlpError("fichier trop court")
    magic, size, fmt, nchan, ppq = HEADER.unpack_from(data, 0)
    if magic != b"FLhd" or size != 6 or data[14:18] != b"FLdt":
        raise FlpError("ce n'est pas un projet FL Studio (.flp)")
    total = struct.unpack_from("<I", data, 18)[0]
    if 22 + total != len(data):
        raise FlpError("projet FL abîmé (taille incorrecte)")
    events, i = [], 22
    while i < len(data):
        eid = data[i]
        i += 1
        if eid < WORD:
            n = 1
        elif eid < DWORD:
            n = 2
        elif eid < TEXT:
            n = 4
        else:
            n, shift = 0, 0
            while True:
                if i >= len(data):
                    raise FlpError("projet FL abîmé (taille d'événement)")
                b = data[i]
                i += 1
                n |= (b & 0x7F) << shift
                shift += 7
                if not b & 0x80:
                    break
        if i + n > len(data):
            raise FlpError("projet FL abîmé (événement coupé)")
        events.append([eid, bytes(data[i:i + n])])
        i += n
    return fmt, nchan, ppq, events


def write_flp(fmt, nchan, ppq, events):
    body = bytearray()
    for eid, val in events:
        body.append(eid)
        if eid >= TEXT:
            body += _varint(len(val))
        body += val
    return HEADER.pack(b"FLhd", 6, fmt, nchan, ppq) + b"FLdt" + struct.pack("<I", len(body)) + bytes(body)


def _unicode(events):
    """FL 11.5+ écrit les textes en UTF-16."""
    for eid, val in events:
        if eid == EV_VERSION:
            parts = [int(x) for x in re.findall(r"\d+", val.decode("ascii", "replace"))[:2]] or [0]
            return parts >= [11, 5]
    return True


def _text(val, uni):
    try:
        return (val.decode("utf-16-le") if uni else val.decode("cp1252")).rstrip("\0")
    except UnicodeDecodeError:
        return ""


def _enc(s, uni):
    return (s + "\0").encode("utf-16-le") if uni else (s + "\0").encode("cp1252", "replace")


def _items(val):
    size = 60 if len(val) % 60 == 0 else 32 if len(val) % 32 == 0 else 0
    return size, (len(val) // size if size else 0)


def _clip_channels(events):
    """N° des canaux (sons) placés dans la playlist."""
    out = []
    for eid, val in events:
        if eid == EV_PLAYLIST:
            size, n = _items(val)
            for k in range(n):
                base, idx = struct.unpack_from("<HH", val, k * size + 4)
                if base == PATTERN_BASE and idx < PATTERN_BASE:
                    out.append(idx)
    return out


def inspect_template(path):
    """Vérifie le modèle → {ok, msg, ...}. Le son de l'instru = le premier son placé
    dans la playlist (sinon le premier canal qui a un son)."""
    try:
        fmt, nchan, ppq, events = read_flp(Path(path).read_bytes())
    except (OSError, FlpError) as e:
        return {"ok": False, "msg": f"Modèle illisible : {e}"}
    uni = _unicode(events)
    chans, cur = {}, None
    for i, (eid, val) in enumerate(events):
        if eid == EV_CHANNEL_NEW:
            cur = struct.unpack("<H", val)[0]
        elif eid == EV_SAMPLE_PATH and cur is not None and cur not in chans:
            chans[cur] = (i, _text(val, uni))
    with_sample = {k: v for k, v in chans.items() if v[1]}
    clips = _clip_channels(events)
    chan = next((c for c in clips if c in with_sample), None)
    if chan is None and with_sample:
        chan = min(with_sample)
    tempo = next((struct.unpack("<I", v)[0] / 1000 for e, v in events if e == EV_TEMPO), None)
    if chan is None:
        return {"ok": False, "msg": "Aucun son dans le modèle : glisse n'importe quel .wav sur la piste 1 de la playlist (envoyé vers l'insert 1), puis enregistre le modèle."}
    return {"ok": True, "channel": chan, "sample": with_sample[chan][1], "in_playlist": chan in clips, "ppq": ppq, "tempo": tempo,
            "msg": f"Modèle OK : l'instru remplacera « {Path(with_sample[chan][1].replace(chr(92), '/')).name} »"
                   + ("" if chan in clips else " (pas encore placé dans la playlist)") + "."}


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


def build_project(template, wav, out_path, bpm=None, title=None):
    """Écrit le projet de la prod. Renvoie un petit résumé (texte)."""
    t = inspect_template(template)
    if not t["ok"]:
        raise FlpError(t["msg"])
    fmt, nchan, ppq, events = read_flp(Path(template).read_bytes())
    uni = _unicode(events)
    chan = t["channel"]
    done = []
    tempo = bpm if bpm and 40 <= float(bpm) <= 300 else (t["tempo"] or 140)
    if bpm:
        for ev in events:
            if ev[0] == EV_TEMPO:
                ev[1] = struct.pack("<I", int(round(float(bpm) * 1000)))
            elif ev[0] == EV_TEMPO_COARSE:
                ev[1] = struct.pack("<H", int(float(bpm)))
            elif ev[0] == EV_TEMPO_FINE_OLD:
                ev[1] = struct.pack("<H", 0)
        done.append(f"{bpm} BPM")
    # Le son de l'instru
    cur = None
    for ev in events:
        if ev[0] == EV_CHANNEL_NEW:
            cur = struct.unpack("<H", ev[1])[0]
        elif ev[0] == EV_SAMPLE_PATH and cur == chan:
            ev[1] = _enc(str(Path(wav).resolve()), uni)
            break
    done.append("instru")
    # Longueur du clip de l'instru dans la playlist (le clip suit la durée de la prod)
    try:
        ticks = max(1, int(round(wav_seconds(wav) * float(tempo) / 60 * ppq)))
    except (OSError, FlpError, ValueError):
        ticks = None
    if ticks:
        for ev in events:
            if ev[0] != EV_PLAYLIST:
                continue
            size, n = _items(ev[1])
            buf = bytearray(ev[1])
            for k in range(n):
                o = k * size
                base, idx = struct.unpack_from("<HH", buf, o + 4)
                if base != PATTERN_BASE or idx != chan:
                    continue
                old = struct.unpack_from("<I", buf, o + 8)[0]
                struct.pack_into("<I", buf, o + 8, ticks)
                start, end = struct.unpack_from("<ff", buf, o + 24)
                if old and start >= 0 and end > start:  # même unité que la longueur d'origine
                    struct.pack_into("<f", buf, o + 28, start + (end - start) * ticks / old)
            ev[1] = bytes(buf)
    if title:
        for ev in events:
            if ev[0] == EV_TITLE:
                ev[1] = _enc(title[:120], uni)
    data = write_flp(fmt, nchan, ppq, events)
    read_flp(data)  # contrôle : le fichier écrit se relit
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
    fm.setdefault("dossier", str(Path(cfg.get("dossier") or C.default_folder()) / "Projets FL"))
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
    folder = Path(folder)
    p = folder / f"{name}.flp"
    i = 2
    while p.exists():
        p = folder / f"{name} ({i}).flp"
        i += 1
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
    out = project_path(fm["dossier"], wav.stem)
    summary = build_project(fm["template"], wav, out, bpm=C.valid_bpm(bpm), title=title or wav.stem)
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
        files = [p for p in folder.glob("*.flp") if p.is_file()]
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
