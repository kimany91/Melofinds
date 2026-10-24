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
    extra: dict = field(default_factory=dict)


def parse_name(name):
    """« Titre [C# min, 150 BPM] [FFP] (2) » → (titre, suffixe, clé, bpm, licence)."""
    rest, groups = name, []
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
        parts = [p.strip() for p in inner.split(",")]
        if parts and all(KEY_RE.match(p) or BPM_RE.match(p) for p in parts):
            for p in parts:
                if BPM_RE.match(p):
                    bpm = int(BPM_RE.match(p).group(1))
                else:
                    key = p
            keep.append(g)
        else:
            rest = f"{rest} {g}"  # crochets qui font partie du titre
    return rest.strip(), " ".join(keep), key, bpm, lic


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
        title, suffix, key, bpm, lic = parse_name(name)
        return Prod(id=name.lower(), name=name, title=title or name, suffix=suffix, key=key, bpm=bpm, lic=lic)

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


def toggle_fav(item, cfg=None):
    cfg = cfg if cfg is not None else C.load_config()
    favs = [f for f in (cfg.get("favs") or []) if f != item.id]
    if not item.fav:
        favs.insert(0, item.id)
    cfg["favs"] = favs[:2000]
    C.save_config(cfg)
    item.fav = not item.fav
    return item.fav


def open_item(item, cfg=None):
    """Ouvre la prod dans FL (projet FLmake, créé si besoin), sinon le .wav."""
    cfg = cfg if cfg is not None else C.load_config()
    if item.flp and item.flp.is_file():
        return FM.open_in_fl(item.flp, item.key or None, item.bpm, cfg)
    fm = FM.settings(cfg)
    if item.wav and fm["template"] and Path(fm["template"]).is_file():
        out, msg = FM.make(item.wav, item.key or None, item.bpm, item.name, cfg)
        item.flp, item.folder = out, out.parent
        return f"{msg} · {FM.open_in_fl(out, item.key or None, item.bpm, cfg)}"
    if item.wav:
        if C.WINDOWS:
            os.startfile(str(item.wav))  # noqa: S606 (fichier du dossier des prods)
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

    mapping = []
    try:
        if plan["wav"]:
            a, b = plan["wav"]
            move(a, b)
            mapping.append((str(a), str(b)))
        flps = []
        if plan["folder"]:
            a, b = plan["folder"]
            move(a, b)
            # fichiers / sous-dossiers qui portent l'ancien nom, les plus profonds d'abord
            inner = sorted((p for p in b.rglob("*") if item.name in p.name), key=lambda x: len(x.parts), reverse=True)
            for p in inner:
                rel = p.relative_to(b)
                final = b.joinpath(*[part.replace(item.name, new) for part in rel.parts])
                move(p, p.with_name(p.name.replace(item.name, new)))
                mapping.append((str(a / rel), str(final)))
            mapping.sort(key=lambda m: len(m[0]), reverse=True)
            mapping.append((str(a), str(b)))
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
    favs = cfg.get("favs") or []
    if item.id in favs:
        cfg["favs"] = [new.lower() if f == item.id else f for f in favs]
    if plan["wav"]:
        ren = cfg.get("renamed") or {}
        ren[plan["wav"][0].name] = plan["wav"][1].name
        cfg["renamed"] = dict(list(ren.items())[-500:])
    C.save_config(cfg)
    return new
