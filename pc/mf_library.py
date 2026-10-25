"""Melofinds PC — « Mes prods » : les prods reçues (.wav) et leurs projets FL.

  - liste : chaque prod du dossier des prods, avec son projet FL (FLmake) s'il existe,
    sa clé, son BPM et sa licence (lus dans le nom « Titre [C# min, 150 BPM] [FFP] ») ;
  - favoris ;
  - ouvrir dans FL (crée le projet FLmake s'il n'existe pas encore) ;
  - renommer : le .wav, le dossier du projet FL, les fichiers du dossier qui portent
    l'ancien nom, et les chemins enregistrés dans les .flp (l'instru, les fichiers du
    dossier, le titre). Tout ou rien : en cas d'erreur, tout est remis comme avant.
"""

import os
import re
import struct
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import mf_core as C
import mf_flmake as FM

LIC_RE = re.compile(r"^(FFP(?:, UPTO(?: \d+)?)?|F)$")
KEY_RE = re.compile(r"^[A-G][#b]?(?: (?:min|maj))?$")
BPM_RE = re.compile(r"^(\d{2,3}) BPM$")
TAIL_RE = re.compile(r"\s*(\[[^\[\]]*\]|\(\d+\))\s*$")
BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


class LibError(Exception):
    pass


@dataclass
class Prod:
    id: str                      # nom en minuscules (stable pour les favoris)
    name: str                    # nom complet « Titre [C# min, 150 BPM] [FFP] »
    title: str                   # « Titre »
    suffix: str = ""             # « [C# min, 150 BPM] [FFP] » (gardé quand on renomme)
    key: str = ""
    bpm: int | None = None
    lic: str = ""
    wav: Path | None = None
    flp: Path | None = None
    folder: Path | None = None   # dossier du projet FL (None pour un .flp seul)
    date: float = 0.0
    fav: bool = False
    kind: str = "prod"           # « prod » (dossier des prods) ou « project » (projet FL)
    extra: dict = field(default_factory=dict)

    @property
    def fav_key(self):
        return "fav_projects" if self.kind == "project" else "favs"


def parse_name(name):
    """« Titre [C# min, 150 BPM] [FFP] (2) » → (titre, suffixe, clé, bpm, licence)."""
    return parse_name_tb(name)[:5]


def parse_name_tb(name):
    """Comme parse_name, plus ce qui a été trouvé avec Tunebat (« [TB 150 BPM] ») : {"key", "bpm"}."""
    rest, groups, tb = name, [], set()
    while True:
        m = TAIL_RE.search(rest)
        if not m or m.start() == 0:
            break
        groups.insert(0, m.group(1))
        rest = rest[:m.start()]
    key, bpm, lic, keep = "", None, "", []
    for g in groups:
        inner = g[1:-1].strip()
        if g.startswith("("):
            continue  # « (2) » des doublons : pas repris en renommant
        if LIC_RE.match(inner):
            lic = inner
            keep.append(g)
            continue
        found = inner[:3] == "TB "
        parts = [p.strip() for p in (inner[3:] if found else inner).split(",")]
        if parts and all(KEY_RE.match(p) or BPM_RE.match(p) for p in parts):
            for p in parts:
                if BPM_RE.match(p):
                    bpm = int(BPM_RE.match(p).group(1))
                    tb.discard("bpm")
                    if found:
                        tb.add("bpm")
                else:
                    key = p
                    tb.discard("key")
                    if found:
                        tb.add("key")
            keep.append(g)
        else:
            rest = f"{rest} {g}"  # crochets qui font partie du titre
    return rest.strip(), " ".join(keep), key, bpm, lic, tb


def clean_new_title(text):
    t = BAD_CHARS.sub(" ", str(text or ""))
    t = re.sub(r"\s{2,}", " ", t).strip().rstrip(". ")
    t = t[:110].rstrip(". ")
    if re.fullmatch(r"(?i)(con|prn|aux|nul|com\d|lpt\d)", t):
        t = f"Prod {t}"
    return t


# --- Instru d'un projet (chemin du son de la piste INSTRU), en cache

_flp_cache = {}


def _flp_samples(flp):
    try:
        mt = flp.stat().st_mtime
    except OSError:
        return []
    hit = _flp_cache.get(str(flp))
    if hit and hit[0] == mt:
        return hit[1]
    try:
        _, _, _, events = FM.read_flp(flp.read_bytes())
        uni = FM._unicode(events)
        paths = [FM._text(v, uni) for e, v in events if e == FM.EV_SAMPLE_PATH]
    except (OSError, FM.FlpError):
        paths = []
    _flp_cache[str(flp)] = (mt, paths)
    return paths


def _project_flps(folder):
    """Projets du dossier FLmake : un dossier par projet (+ les .flp seuls d'avant 3.3.1)."""
    out = []
    try:
        entries = list(Path(folder).iterdir())
    except OSError:
        return out
    for e in entries:
        if e.is_dir():
            flps = sorted(e.glob("*.flp"), key=lambda p: (p.stem != e.name, -p.stat().st_mtime))
            if flps:
                out.append((flps[0], e))
        elif e.suffix.lower() == ".flp":
            out.append((e, None))
    return out


def scan(cfg=None):
    """Toutes les prods (dossier des prods) + leurs projets FL, les plus récentes d'abord."""
    cfg = cfg if cfg is not None else C.load_config()
    root = Path(cfg.get("dossier") or C.default_folder())
    favs = set(cfg.get("favs") or [])
    items = {}

    def make(name):
        title, suffix, key, bpm, lic, tb = parse_name_tb(name)
        return Prod(id=name.lower(), name=name, title=title or name, suffix=suffix, key=key, bpm=bpm, lic=lic,
                    extra={"tb": tb} if tb else {})

    try:
        wavs = [p for p in root.glob("*.wav") if p.is_file()]
    except OSError:
        wavs = []
    for w in wavs:
        it = make(w.stem)
        it.wav = w
        it.date = w.stat().st_mtime
        items[it.id] = it
    rootl = str(root.resolve()).lower()
    for flp, folder in _project_flps(FM.settings(cfg)["dossier"]):
        target = None
        for s in _flp_samples(flp):
            sp = Path(s.replace("\\", os.sep)) if os.sep == "/" else Path(s)
            if str(sp.parent).lower() == rootl and sp.stem.lower() in items:
                target = items[sp.stem.lower()]
                break
        if target is None:
            target = items.get((folder.name if folder else flp.stem).lower())
        if target is None or target.flp:
            target = make(folder.name if folder else flp.stem)
            target.id = f"flp:{target.id}"
            items[target.id] = target
        target.flp, target.folder = flp, folder
        try:
            target.date = max(target.date, flp.stat().st_mtime)
        except OSError:
            pass
    for it in items.values():
        it.fav = it.id in favs
    return sorted(items.values(), key=lambda i: i.date, reverse=True)


AUDIO = (".wav", ".mp3", ".flac", ".ogg", ".aif", ".aiff", ".m4a")

# Couleurs et icônes des projets (symboles simples, présents dans les polices Windows)
PALETTE = ["#8b5cf6", "#ec4899", "#f87171", "#fb923c", "#fbbf24", "#a3e635",
           "#34d399", "#2dd4bf", "#22d3ee", "#60a5fa", "#818cf8", "#9aa1b2"]
ICONS = ["♪", "♫", "★", "♥", "⚡", "☀", "☾", "✦", "✿", "♛", "☁", "♠", "♦", "⚑", "☯", "☠", "⚔", "✈",
         "♬", "♩", "♣", "❄", "☂", "☘", "✪", "✺", "❖", "☢", "⚓", "⚙", "☎", "✉", "✎", "✂", "⌛", "☕",
         "♨", "⚛", "☮", "✌", "☺", "♔", "♞", "⚜", "⚖", "☄", "♻", "⚠", "✝", "☪"]


def style_of(item, cfg):
    """Couleur et icône du projet : choisies dans le panneau, sinon une couleur tirée du nom
    (toujours la même pour un projet) et la note ♪."""
    st = (cfg.get("project_style") or {}).get(item.id) or {}
    color = st.get("color") if st.get("color") in PALETTE else PALETTE[zlib.crc32(item.title.lower().encode()) % len(PALETTE)]
    icon = st.get("icon") if st.get("icon") in ICONS else ICONS[0]
    return color, icon, bool(st)


def set_style(item, color=None, icon=None, cfg=None):
    """Choisit (ou remet par défaut, avec None/None) la couleur et l'icône du projet."""
    cfg = cfg if cfg is not None else C.load_config()
    styles = dict(cfg.get("project_style") or {})
    if color is None and icon is None:
        styles.pop(item.id, None)
    else:
        styles[item.id] = {k: v for k, v in (("color", color), ("icon", icon)) if v}
    cfg["project_style"] = dict(list(styles.items())[-3000:])
    C.save_config(cfg)
    item.extra["color"], item.extra["icon"], item.extra["styled"] = style_of(item, cfg)


def _has_audio(folder, depth=2):
    """Un dossier avec des sons (même seulement des .mp3 ou dans un sous-dossier) est un projet."""
    try:
        for p in folder.iterdir():
            if p.is_file() and p.suffix.lower() in AUDIO_EXT:
                return True
            if depth > 1 and p.is_dir() and not p.name.startswith(".") and _has_audio(p, depth - 1):
                return True
    except OSError:
        pass
    return False


def scan_projects(cfg=None):
    """Mes projets FL : chaque dossier de projet du dossier des projets (projet FL et/ou
    prod .wav), plus les .flp seuls ; les plus récemment modifiés d'abord."""
    cfg = cfg if cfg is not None else C.load_config()
    folder = Path(FM.settings(cfg)["dossier"])
    favs = set(cfg.get("fav_projects") or [])
    out = []
    try:
        entries = list(folder.iterdir())
    except OSError:
        entries = []
    for e in entries:
        try:
            if e.is_dir():
                flps = sorted(e.glob("*.flp"), key=lambda p: (p.stem != e.name, -p.stat().st_mtime))
                wavs = sorted(e.glob("*.wav"), key=lambda p: p.stem != e.name)
                if not flps and not wavs and not _has_audio(e):
                    continue
                flp, sub, name = (flps[0] if flps else None), e, e.name
            elif e.suffix.lower() == ".flp":
                flp, sub, wavs, name = e, None, [], e.stem
            else:
                continue
        except OSError:
            continue
        title, suffix, key, bpm, lic, tb = parse_name_tb(name)
        it = Prod(id=f"p:{name.lower()}", name=name, title=title or name, suffix=suffix, key=key, bpm=bpm, lic=lic,
                  flp=flp, folder=sub, kind="project", extra={"tb": tb} if tb else {})
        try:
            files = [p for p in sub.rglob("*") if p.is_file()] if sub else [flp]
            it.date = max((p.stat().st_mtime for p in files), default=0.0)
            it.extra["files"] = len(files)
        except OSError:
            it.date = 0.0
        sounds = [Path(s) for s in (_flp_samples(flp) if flp else []) if s and not s.startswith("%") and s.lower().endswith(AUDIO)]
        if sub:  # l'instru du dossier du projet d'abord
            sounds.sort(key=lambda p: str(p.parent).lower() != str(sub).lower() and str(p.parent).lower() != str(sub.resolve()).lower())
        sounds = sounds or wavs
        if sounds:
            it.extra["instru"] = parse_name(sounds[0].stem)[0] or sounds[0].stem
            it.extra["instru_path"] = sounds[0]
        it.fav = it.id in favs
        it.extra["color"], it.extra["icon"], it.extra["styled"] = style_of(it, cfg)
        ip = it.extra.get("instru_path")
        if ip:
            d = _duration(ip)
            if d:
                it.extra["dur"] = d
        out.append(it)
    videos = _videos(cfg)
    for it in out:
        if it.folder:
            vid = next((videos[k] for k in _forms(it.folder) if k in videos), None)
            if vid:
                it.extra["yt"] = vid
    return order_projects(out, cfg)


def order_projects(items, cfg):
    """Ton ordre (glisser-déposer dans le panneau) ; les nouveaux projets arrivent en haut."""
    pos = {pid: n for n, pid in enumerate(cfg.get("project_order") or [])}
    new = sorted((i for i in items if i.id not in pos), key=lambda i: i.date, reverse=True)
    return new + sorted((i for i in items if i.id in pos), key=lambda i: pos[i.id])


def move_project(src_id, dst_id, cfg=None):
    """Déplace un projet à la place d'un autre (glisser-déposer). Renvoie le nouvel ordre."""
    cfg = cfg if cfg is not None else C.load_config()
    order = [i.id for i in scan_projects(cfg)]
    if src_id not in order or dst_id not in order or src_id == dst_id:
        return order
    down = order.index(src_id) < order.index(dst_id)
    order.remove(src_id)
    order.insert(order.index(dst_id) + (1 if down else 0), src_id)
    cfg["project_order"] = order[:3000]
    C.save_config(cfg)
    return order


_dur_cache = {}


def _duration(path):
    """Durée (s) d'une prod .wav, lue dans l'en-tête (rapide), gardée en mémoire."""
    p = Path(path)
    if p.suffix.lower() != ".wav":
        return None
    try:
        key = (str(p).lower(), p.stat().st_mtime)
    except OSError:
        return None
    if key not in _dur_cache:
        try:
            import wave
            with wave.open(str(p), "rb") as w:
                _dur_cache[key] = round(w.getnframes() / float(w.getframerate()))
        except (OSError, EOFError, ValueError, ZeroDivisionError, wave.Error):
            _dur_cache[key] = None
        if len(_dur_cache) > 5000:
            _dur_cache.clear()
    return _dur_cache[key]


_video_cache = {"sig": None, "map": {}}


def _videos(cfg):
    """Dossier de projet → identifiant de la vidéo YouTube d'où vient la prod (prods
    téléchargées depuis l'app ; suit les renommages)."""
    try:
        sig = (P_state_mtime(), len(cfg.get("renamed") or {}))
    except OSError:
        sig = None
    if sig and sig == _video_cache["sig"]:
        return _video_cache["map"]
    out = {}
    renamed = cfg.get("renamed") or {}
    for vid, path in (C.load_state().get("files") or {}).items():
        if not C.VIDEO_ID.match(str(vid)) or not path:
            continue
        p = C.follow_renames(path, renamed)
        for k in _forms(p.parent):
            out[k] = vid
    _video_cache.update(sig=sig, map=out)
    return out


def _forms(path):
    """Écritures d'un dossier (Windows : nom court « RUNNER~1 » ou complet), en minuscules."""
    out = {str(path).lower()}
    try:
        out.add(str(Path(path).resolve()).lower())
        out.add(os.path.realpath(path).lower())
    except OSError:
        pass
    return out


def P_state_mtime():
    return C.P.state.stat().st_mtime if C.P.state.exists() else 0


def toggle_fav(item, cfg=None):
    cfg = cfg if cfg is not None else C.load_config()
    favs = [f for f in (cfg.get(item.fav_key) or []) if f != item.id]
    if not item.fav:
        favs.insert(0, item.id)
    cfg[item.fav_key] = favs[:2000]
    C.save_config(cfg)
    item.fav = not item.fav
    return item.fav


def open_item(item, cfg=None):
    """Ouvre le projet dans FL ; s'il n'a encore que la prod, crée le projet FLmake à côté
    (si un modèle est choisi), sinon ouvre la prod."""
    cfg = cfg if cfg is not None else C.load_config()
    if item.flp and item.flp.is_file():
        return FM.open_in_fl(item.flp, item.key or None, item.bpm, cfg)
    wav = item.wav or item.extra.get("instru_path")
    fm = FM.settings(cfg)
    if wav and Path(wav).is_file() and fm["template"] and Path(fm["template"]).is_file():
        out, msg = FM.make(wav, item.key or None, item.bpm, None, cfg)
        item.flp = out
        return f"{msg} · {FM.open_in_fl(out, item.key or None, item.bpm, cfg)}"
    if wav and Path(wav).is_file():
        if C.WINDOWS:
            os.startfile(str(wav))  # noqa: S606 (fichier du dossier des projets)
        return "Prod ouverte (choisis ton modèle dans FLmake pour avoir un projet FL)"
    raise LibError("rien à ouvrir")


# --- Renommer

def _replace_prefix(text, old, new):
    if text.lower() == old.lower():
        return new
    for sep in ("\\", "/"):
        o = old.rstrip("\\/") + sep
        if text.lower().startswith(o.lower()):
            return new.rstrip("\\/") + sep + text[len(o):]
    return None


def rewrite_flp(flp, mapping, old_title, new_title):
    """Remplace les chemins (et le titre) enregistrés dans un .flp. mapping : [(ancien, nouveau)]."""
    data = Path(flp).read_bytes()
    fmt, nchan, ppq, events = FM.read_flp(data)
    uni = FM._unicode(events)
    changed = 0
    for ev in events:
        eid = ev[0]
        if not (FM.TEXT <= eid < 208 or eid in FM.NEW_TEXT_IDS) or eid == FM.EV_VERSION:
            continue
        txt = FM._text(ev[1], uni)
        if not txt:
            continue
        new = None
        if eid == FM.EV_TITLE and txt in (old_title,):
            new = new_title
        else:
            for a, b in mapping:
                new = _replace_prefix(txt, a, b)
                if new is not None:
                    break
        if new is not None and new != txt:
            ev[1] = FM._enc(new, uni)
            changed += 1
    if changed:
        out = FM.write_flp(fmt, nchan, ppq, events)
        FM.read_flp(out)  # contrôle
        tmp = Path(flp).with_suffix(".flp.tmp")
        tmp.write_bytes(out)
        tmp.replace(flp)
    return data, changed


def rename_plan(item, new_title):
    """Ce que le renommage va faire (affiché avant de confirmer)."""
    title = clean_new_title(new_title)
    if not title:
        raise LibError("nom vide")
    new = f"{title} {item.suffix}".strip()
    plan = {"new": new, "title": title, "wav": None, "folder": None, "files": [], "flp": None}
    if item.wav:
        plan["wav"] = (item.wav, item.wav.with_name(new + item.wav.suffix))
    if item.folder:
        dst = item.folder.with_name(new)
        plan["folder"] = (item.folder, dst)
        for p in sorted(item.folder.rglob("*"), key=lambda x: len(x.parts), reverse=True):
            if item.name in p.name:
                plan["files"].append(p)
    elif item.flp:
        plan["flp"] = (item.flp, item.flp.with_name(new + ".flp"))
    return plan


def _free(src, dst):
    """dst libre (ou même fichier à la casse près)."""
    if not dst.exists():
        return True
    try:
        return src.resolve() == dst.resolve() or os.path.samefile(src, dst)
    except OSError:
        return False


def rename(item, new_title, cfg=None):
    """Renomme la prod partout. Tout ou rien. Renvoie le nouveau nom."""
    cfg = cfg if cfg is not None else C.load_config()
    plan = rename_plan(item, new_title)
    new = plan["new"]
    if new == item.name:
        return new
    moves, backups = [], []  # pour tout remettre en cas d'erreur

    def move(src, dst):
        if src == dst:
            return
        if not _free(src, dst):
            raise LibError(f"« {dst.name} » existe déjà")
        tmp = None
        if dst.exists():  # même fichier, autre casse (Windows) : passage par un nom temporaire
            tmp = src.with_name(src.name + ".mf-renommage")
            os.replace(src, tmp)
            os.replace(tmp, dst)
        else:
            os.replace(src, dst)
        moves.append((src, dst))

    def forms(p):
        """Toutes les écritures d'un chemin (nom court « RUNNER~1 » ou complet, liens) :
        le .flp garde celle de FLmake, la liste peut en avoir une autre."""
        out = [str(p)]
        try:
            out.append(str(p.resolve()))
            out.append(os.path.realpath(p))
        except OSError:
            pass
        return list(dict.fromkeys(out))

    def full(p):
        try:
            return str(p.parent.resolve() / p.name)
        except OSError:
            return str(p)

    mapping = []
    try:
        if plan["wav"]:
            a, b = plan["wav"]
            olds = forms(a)
            move(a, b)
            mapping += [(o, full(b)) for o in olds]
        flps = []
        if plan["folder"]:
            a, b = plan["folder"]
            olds = forms(a)
            move(a, b)
            nb = full(b)
            # fichiers / sous-dossiers qui portent l'ancien nom, les plus profonds d'abord
            inner = sorted((p for p in b.rglob("*") if item.name in p.name), key=lambda x: len(x.parts), reverse=True)
            for p in inner:
                rel = p.relative_to(b)
                final = Path(nb).joinpath(*[part.replace(item.name, new) for part in rel.parts])
                move(p, p.with_name(p.name.replace(item.name, new)))
                mapping += [(str(Path(o) / rel), str(final)) for o in olds]
            mapping.sort(key=lambda m: len(m[0]), reverse=True)
            mapping += [(o, nb) for o in olds]
            flps = [p for p in b.rglob("*.flp") if p.is_file()]
        elif plan["flp"]:
            a, b = plan["flp"]
            move(a, b)
            flps = [b]
        for f in flps:
            data, n = rewrite_flp(f, mapping, item.name, new)
            if n:
                backups.append((f, data))
    except Exception as e:
        for f, data in reversed(backups):
            try:
                f.write_bytes(data)
            except OSError:
                pass
        for src, dst in reversed(moves):
            try:
                os.replace(dst, src)
            except OSError:
                pass
        raise LibError(f"renommage annulé : {e}") from e
    # Favori, suivi des fichiers reçus (le PC ne retélécharge pas une prod renommée)
    new_id = f"p:{new.lower()}" if item.kind == "project" else new.lower()
    favs = cfg.get(item.fav_key) or []
    if item.id in favs:
        cfg[item.fav_key] = [new_id if f == item.id else f for f in favs]
    order = cfg.get("project_order") or []
    if item.id in order:  # sa place dans ton ordre aussi
        cfg["project_order"] = [new_id if x == item.id else x for x in order]
    styles = cfg.get("project_style") or {}
    if item.id in styles:  # l'icône et la couleur suivent le projet
        styles[new_id] = styles.pop(item.id)
        cfg["project_style"] = styles
    # Suivi des fichiers reçus : le PC ne retélécharge pas une prod renommée (ou déplacée
    # avec son dossier de projet)
    ren = cfg.get("renamed") or {}
    for old, newp in mapping:
        ren[old] = newp
    cfg["renamed"] = dict(list(ren.items())[-1000:])
    C.save_config(cfg)
    return new


# --- Sons d'un projet (instru, versions « 0.1 », « v1.3.3 »…) et liste pour l'app web

AUDIO_EXT = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aif", ".aiff", ".opus"}
_VER_DOTS = re.compile(r"(?i)(?:^|[\s_\-\[(.#])v?(?:er(?:sion)?\s?)?(\d{1,3}(?:\.\d{1,3}){1,3})(?=$|[\s_\-\])])")
_VER_V = re.compile(r"(?i)(?:^|[\s_\-\[(])v(?:er(?:sion)?)?\s?(\d{1,3})(?=$|[\s_\-\])])")
_VER_FL = re.compile(r"_(\d{1,3})$")  # « Enregistrer une nouvelle version » de FL : « Haze_2 »


def version_of(name):
    """« Haze 1.3.3 », « Haze v2 », « Haze_v0.1 (mix) » → (1, 3, 3) / (2,) / (0, 1), sinon None.
    Les crochets de clé / BPM / licence sont ignorés."""
    rest = parse_name(str(name or ""))[0].strip()
    for rx in (_VER_DOTS, _VER_V, _VER_FL):
        found = rx.findall(rest)
        if found:
            return tuple(int(x) for x in found[-1].split("."))
    return None


def file_id(path):
    """Identifiant court et stable d'un fichier (pour l'app web)."""
    try:
        p = str(Path(path).resolve())
    except OSError:
        p = str(path)
    return zlib.crc32(p.lower().encode("utf-8")).to_bytes(4, "big").hex() + format(len(p), "04x")


def audio_files(item, limit=60):
    """Sons du projet : l'instru d'abord, puis les versions dans l'ordre (0.1, 0.2, 1.0…),
    puis les autres sons, les plus récents d'abord."""
    instru = item.wav or item.extra.get("instru_path")
    found = []
    if item.folder:
        try:
            base = len(item.folder.parts)
            for p in item.folder.rglob("*"):
                if len(found) >= 400:
                    break
                if p.suffix.lower() in AUDIO_EXT and len(p.parts) - base <= 3 and not p.name.startswith(".") and p.is_file():
                    found.append(p)
        except OSError:
            pass
    elif instru and Path(instru).is_file():
        found = [Path(instru)]
    ins_key = str(Path(instru)).lower() if instru else ""
    out = []
    for p in found:
        try:
            stt = p.stat()
        except OSError:
            continue
        ver = version_of(p.stem)
        out.append({"path": p, "id": file_id(p), "name": p.stem, "ext": p.suffix.lower()[1:], "ver": ver,
                    "label": f"v{'.'.join(map(str, ver))}" if ver else "", "size": stt.st_size, "mtime": stt.st_mtime,
                    "instru": str(p).lower() == ins_key or (not ins_key and p.stem == item.name and p.suffix.lower() == ".wav")})
    if out and not any(f["instru"] for f in out):
        wavs = [f for f in out if f["ext"] == "wav" and not f["ver"]]
        if wavs:
            min(wavs, key=lambda f: len(f["name"]))["instru"] = True
    vers = [f for f in out if f["ver"] and not f["instru"]]
    if vers:
        max(vers, key=lambda f: f["ver"])["latest"] = True
    out.sort(key=lambda f: (0 if f["instru"] else 1 if f["ver"] else 2, f["ver"] or (), -f["mtime"]))
    return out[:limit]


def library_index(cfg=None, limit=150, files_out=None):
    """Tous les projets, en court, pour l'app web (liste gardée sur le téléphone : visible
    même quand le PC est éteint). files_out (dict) reçoit {id: (projet, son)}."""
    cfg = cfg if cfg is not None else C.load_config()
    out = []
    for it in scan_projects(cfg)[:limit]:
        af = audio_files(it, 40)
        if files_out is not None:
            files_out.update({f["id"]: (it, f) for f in af})
        files = [{"f": f["id"], "n": f["name"][:140], "e": f["ext"], "v": f["label"], "s": f["size"], "m": int(f["mtime"]),
                  **({"i": 1} if f["instru"] else {}), **({"l": 1} if f.get("latest") else {})} for f in af]
        out.append({"p": it.id, "n": it.name[:200], "t": it.title[:160], "k": it.key or "", "b": it.bpm or 0,
                    "tb": sorted(it.extra.get("tb") or []), "lic": it.lic or "", "fav": 1 if it.fav else 0,
                    "c": it.extra.get("color"), "ic": it.extra.get("icon"), "d": int(it.date), "fl": 1 if it.flp else 0,
                    **({"y": it.extra["yt"]} if it.extra.get("yt") else {}), **({"du": it.extra["dur"]} if it.extra.get("dur") else {}),
                    "files": files})
    return {"at": int(time.time()), "projects": out, "palette": PALETTE, "icons": ICONS}


def find_project(pid, cfg=None):
    return next((it for it in scan_projects(cfg) if it.id == pid), None)


def find_audio(fid, cfg=None):
    """(projet, son) pour un identifiant envoyé par l'app : seulement un son trouvé dans le
    dossier des projets (jamais un chemin venu de l'extérieur)."""
    for it in scan_projects(cfg):
        for f in audio_files(it, 400):
            if f["id"] == fid:
                return it, f
    return None, None
