"""Promo : une vidéo TikTok / Reels avec tes paroles en sous-titres, sur le visuel choisi.

- Paroles : Whisper (OpenAI, licence MIT) par whisper.cpp (MIT), sur le PC, sans service
  payant ni envoi de ton son. Modèle « large-v3-turbo » (le plus précis qui reste rapide),
  téléchargé une fois depuis les dépôts officiels et vérifié (empreinte publiée). Chaque mot
  a son moment exact (alignement DTW) ; les phrases s'enchaînent sans trou. Tu peux corriger
  le texte et caler une ligne avant l'export.
- Visuels : ta vidéo, ou une vidéo Instagram que tu as ouverte (lien d'un post / reel).
  Le nom du compte est gardé pour la mention « visuel : @compte ».
- Export : ffmpeg (déjà inclus) : 1080x1920, 30 i/s, H.264 + AAC, sous-titres incrustés
  (polices libres Anton / Silkscreen / Archivo Black, licence OFL, de Google Fonts).
"""

import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

import mf_core as C

WHISPER_API = "https://api.github.com/repos/ggml-org/whisper.cpp/releases/latest"
WHISPER_ASSET = "whisper-bin-x64.zip"
# Deux moteurs d'écoute. « precise » : Whisper large-v3 complet (32 couches pour écrire les
# mots, contre 4 pour turbo) : bien meilleur sur le rap rapide ou mal articulé, plus lent.
MODELS = {
    # slow : voix ralentie (même hauteur) pour suivre un débit rapide. Mesuré (CI, voix très
    # rapide sur un beat) : précise ralentie 31/33 mots justes, précise 29/33, rapide 30/33.
    "precise": {"file": "ggml-large-v3.bin", "dtw": "large.v3", "size": "3 Go", "label": "Précise", "slow": 0.85},
    "rapide": {"file": "ggml-large-v3-turbo-q5_0.bin", "dtw": "large.v3.turbo", "size": "550 Mo", "label": "Rapide", "slow": 1.0},
}
QUALITY = "precise"
MODEL = MODELS["rapide"]["file"]  # (ancien nom, gardé pour les tests)
MODEL_DTW = MODELS["rapide"]["dtw"]
HF = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
MODEL_URL = HF + MODEL
MODEL_TREE = "https://huggingface.co/api/models/ggerganov/whisper.cpp/tree/main"
FONTS_CSS = "https://fonts.googleapis.com/css2?family=Anton&family=Silkscreen:wght@700&family=Archivo+Black"
FONT_FILES = {"Anton": "Anton.ttf", "Silkscreen": "Silkscreen.ttf", "Archivo Black": "ArchivoBlack.ttf"}

AUDIO_EXT = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
IG_RE = re.compile(r"^https://(?:www\.)?instagram\.com/(?:[A-Za-z0-9._]{1,30}/)?(?:p|reels?|tv)/([A-Za-z0-9_-]{5,40})/?(?:\?[^\s]*)?$")
USER_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
ACCOUNTS = ["otisaltaiexp", "godhandusa", "psxsht", "violetnmarlowne"]

W, H = 1080, 1920
# Styles des sous-titres (comme les vidéos TikTok de visualizers)
STYLES = {
    "impact": {"label": "Impact", "font": "Anton", "size": 150, "outline": 7, "shadow": 3, "case": "upper", "spacing": 1},
    "pixel": {"label": "Pixel", "font": "Silkscreen", "size": 72, "outline": 6, "shadow": 0, "case": "lower", "spacing": 0},
    "bold": {"label": "Gras", "font": "Archivo Black", "size": 92, "outline": 6, "shadow": 2, "case": "", "spacing": 0},
}
POSITIONS = {"centre": (5, 0), "bas": (2, 430), "haut": (8, 360)}
# Phrases que Whisper invente sur la musique sans voix (connues) : jamais affichées
HALLU = re.compile(r"amara\.org|sous-titr|merci d'avoir regard|abonnez-vous|n'oubliez pas de vous abonner|"
                   r"thanks for watching|subtitles by", re.I)
PROMPT = "Paroles d'un morceau de rap français, avec de l'argot."
# Whisper (alignement DTW) date les mots en retard : mesuré mot par mot sur une voix aux moments
# connus, posée sur un beat (CI Windows) : 0,09 à 0,30 s, 0,17 s en moyenne, jamais en avance.
DTW_SHIFT = 0.14
# large-v3 complet n'a pas ce retard (mesuré : 0,01 s d'avance en moyenne) : rien à corriger
DTW_SHIFTS = {"precise": 0.0, "rapide": 0.14}
LEX_MAX = 80


class PromoError(Exception):
    pass


# ---------------------------------------------------------------------------
# Dossiers

def promo_dir(cfg=None):
    return C.projects_root(cfg if cfg is not None else C.load_config()) / "Promo"


def visuals_dir(cfg=None):
    return promo_dir(cfg) / "Visuels"


def videos_dir(cfg=None):
    return promo_dir(cfg) / "Vidéos"


def whisper_dir():
    return C.P.tools / "whisper"


def fonts_dir():
    return C.P.tools / "fonts"


def safe_name(s, n=60):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", str(s or "")).strip(" .")
    return re.sub(r"\s+", " ", s)[:n].strip(" .") or "promo"


# ---------------------------------------------------------------------------
# Outils : whisper.cpp, modèle, polices (téléchargés une fois, vérifiés)

def whisper_exe():
    d = whisper_dir()
    for n in ("whisper-cli.exe", "whisper-cli", "main.exe"):
        if (d / n).exists():
            return d / n
    if not C.WINDOWS:
        p = shutil.which("whisper-cli")
        return Path(p) if p else None
    return None


def _quality(q):
    return q if q in MODELS else QUALITY


def model_path(quality=None):
    p = whisper_dir() / MODELS[_quality(quality)]["file"]
    return p if p.exists() else None


def ready(quality=None):
    return {"whisper": bool(whisper_exe()), "model": bool(model_path(quality)), "fonts": all((fonts_dir() / f).exists() for f in FONT_FILES.values())}


# ---------- Tes mots : ce que tu corriges dans les paroles est retenu et donné à Whisper la
# fois d'après (ton blaze, ton argot, les noms…), pour qu'il les entende bien.
def _lex_file():
    return C.P.base / "promo-mots.json"


def lexicon():
    d = C._read_json(_lex_file())
    return [w for w in d.get("mots") or [] if isinstance(w, str)][-LEX_MAX:] if isinstance(d, dict) else []


def _tok(text):
    return [t for t in re.findall(r"[\w'’-]+", _fix_text(str(text or "")).lower()) if len(t) > 1 and not t.isdigit()]


def learn_words(heard, lines):
    """Mots écrits dans les paroles finales que Whisper n'avait pas entendus : retenus."""
    got = set(_tok(" ".join(str(w.get("w") or "") for w in heard or [])))
    new = []
    for ln in lines or []:
        for t in re.findall(r"[\w'’-]+", _fix_text(str(ln.get("t") or ""))):
            if len(t) > 1 and not t.isdigit() and t.lower() not in got and t.lower() not in {x.lower() for x in new}:
                new.append(t[:30])
    if not new:
        return []
    keep = [w for w in lexicon() if w.lower() not in {x.lower() for x in new}] + new
    try:
        C._write_json(_lex_file(), {"mots": keep[-LEX_MAX:]})
    except OSError:
        return []
    return new


def forget_word(word):
    keep = [w for w in lexicon() if w.lower() != str(word).lower()]
    C._write_json(_lex_file(), {"mots": keep})
    return keep


def prompt_for(title=""):
    """Consigne donnée à Whisper : rap français + le titre + tes mots (≈ 150 mots au plus)."""
    p = PROMPT
    t = re.sub(r"\s+", " ", re.sub(r"[\[\]()_]", " ", str(title or ""))).strip()[:60]
    if t:
        p += f" Titre : {t}."
    lex = lexicon()[-60:]
    if lex:
        p += " Mots : " + ", ".join(lex) + "."
    return p


def _json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": f"melofinds-pc/{C.VERSION}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _safe_member(name):
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    return base if re.fullmatch(r"[\w.+-]{1,80}\.(?:exe|dll)", base, re.I) else None


def pick_whisper_asset(assets):
    """Le .zip Windows 64 bits « processeur » de la version officielle (pas CUDA / BLAS)."""
    ok = [a for a in assets if isinstance(a, dict) and re.fullmatch(r"whisper-bin-x64\.zip", str(a.get("name") or ""))]
    ok = ok or [a for a in assets if isinstance(a, dict) and re.fullmatch(r"whisper-[\w.-]*bin[\w.-]*x64[\w.-]*\.zip", str(a.get("name") or ""), re.I)
                and not re.search(r"cublas|cuda|blas|vulkan|arm", str(a.get("name") or ""), re.I)]
    return ok[0] if ok else None


def ensure_whisper(progress=None, quality=None):
    """whisper.cpp (version officielle pour Windows) + le modèle choisi. Lève PromoError."""
    q = MODELS[_quality(quality)]
    say = progress or (lambda *_: None)
    d = whisper_dir()
    d.mkdir(parents=True, exist_ok=True)
    if not whisper_exe():
        if not C.WINDOWS:
            raise PromoError("whisper-cli introuvable")
        say("Téléchargement du moteur de paroles (whisper.cpp)…")
        try:
            rels = [_json(WHISPER_API)]
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise PromoError(f"whisper.cpp introuvable ({e})")
        rel = asset = None
        for i in range(2):  # la dernière version, sinon la plus récente qui a le fichier Windows et son empreinte
            for r in rels:
                a = pick_whisper_asset(r.get("assets") or [])
                if a and str(a.get("digest") or "").startswith("sha256:") and not r.get("prerelease") and not r.get("draft"):
                    rel, asset = r, a
                    break
            if asset or i:
                break
            try:
                rels = _json(WHISPER_API.replace("/latest", "?per_page=10"))
            except (urllib.error.URLError, OSError, ValueError):
                break
        if not asset:
            last = rels[0] if rels else {}
            names = ", ".join(f"{a.get('name')}{'' if a.get('digest') else ' (sans empreinte)'}" for a in last.get("assets") or [])[:400]
            raise PromoError(f"whisper.cpp {last.get('tag_name')} : fichier Windows ou empreinte introuvable ({names})")
        digest = str(asset.get("digest"))
        with tempfile.TemporaryDirectory(prefix="melofinds-whisper-", ignore_cleanup_errors=True) as tmp:
            z = Path(tmp) / WHISPER_ASSET
            got = C.download_file(asset["browser_download_url"], z, say, "whisper.cpp")
            if got.lower() != digest.split(":", 1)[1].lower():
                raise PromoError("whisper.cpp : empreinte différente, fichier refusé")
            with zipfile.ZipFile(z) as zf:
                for m in zf.namelist():
                    base = _safe_member(m)
                    if base:
                        with zf.open(m) as src, open(d / base, "wb") as dst:
                            shutil.copyfileobj(src, dst)
        if not whisper_exe():
            raise PromoError("whisper.cpp : programme absent de l'archive")
        C.log(f"whisper.cpp installé ({rel.get('tag_name')})")
    if not model_path(quality):
        say(f"Téléchargement du modèle de paroles {q['label'].lower()} (une seule fois, ~{q['size']})…")
        try:
            tree = _json(MODEL_TREE)
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise PromoError(f"modèle introuvable ({e})")
        ent = next((t for t in tree if isinstance(t, dict) and t.get("path") == q["file"]), None)
        sha = str(((ent or {}).get("lfs") or {}).get("oid") or "")
        if not re.fullmatch(r"[a-f0-9]{64}", sha):
            raise PromoError("modèle : empreinte officielle introuvable")
        part = d / (q["file"] + ".part")
        got = C.download_file(HF + q["file"], part, say, "modèle")
        if got != sha:
            part.unlink(missing_ok=True)
            raise PromoError("modèle : empreinte différente, fichier refusé")
        part.replace(d / q["file"])
        C.log(f"Modèle Whisper installé ({q['file']})")
    return whisper_exe(), model_path(quality)


def ensure_fonts(progress=None):
    """Polices des sous-titres (OFL, Google Fonts). Sans réseau : polices de Windows."""
    d = fonts_dir()
    if all((d / f).exists() for f in FONT_FILES.values()):
        return d
    d.mkdir(parents=True, exist_ok=True)
    (progress or (lambda *_: None))("Polices des sous-titres…")
    try:
        req = urllib.request.Request(FONTS_CSS, headers={"User-Agent": "Mozilla/5.0"})  # navigateur ancien : .ttf
        css = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        C.log(f"Polices : {e}")
        return d
    for fam, url in re.findall(r"font-family:\s*'([^']+)';[^}]*?src:\s*url\((https://fonts\.gstatic\.com/[^)]+\.ttf)\)", css, re.S):
        name = FONT_FILES.get(fam)
        if not name or (d / name).exists():
            continue
        try:
            data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read(5_000_000)
        except (urllib.error.URLError, OSError):
            continue
        if data[:4] in (b"\x00\x01\x00\x00", b"true", b"OTTO"):
            (d / name).write_bytes(data)
    return d


# ---------------------------------------------------------------------------
# Paroles : Whisper → mots datés → lignes de sous-titres sans trou

def _fix_text(s):
    return s.encode("utf-8", "surrogateescape").decode("utf-8", "replace").replace("�", "")


def words_from_json(data):
    """Sortie JSON complète de whisper.cpp → [{w, s, e}] (secondes). Les jetons qui commencent
    par une espace ouvrent un mot ; le moment vient de l'alignement DTW quand il existe."""
    words = []
    for gi, seg in enumerate((data or {}).get("transcription") or []):
        if HALLU.search(_fix_text(str(seg.get("text") or ""))):
            continue
        for tok in seg.get("tokens") or []:
            t = str(tok.get("text") or "")
            if not t or t.startswith("[_") or t.startswith("<|"):
                continue
            off = tok.get("offsets") or {}
            dtw = tok.get("t_dtw", -1)
            s = (dtw * 10 if isinstance(dtw, (int, float)) and dtw >= 0 else off.get("from", 0)) / 1000
            e = (off.get("to") or 0) / 1000
            if t.startswith(" ") or not words or words[-1].get("g") != gi:
                words.append({"w": t.strip(), "s": s, "e": max(e, s), "g": gi})  # g : phrase de Whisper
            else:
                words[-1]["w"] += t
                words[-1]["e"] = max(words[-1]["e"], e)
    out = []
    for w in words:
        w["w"] = _fix_text(w["w"]).strip().strip('"“”«»„').strip()  # guillemets ajoutés par Whisper
        if w["w"] and re.search(r"\w", w["w"]):
            out.append(w)
    for i in range(1, len(out)):  # dans l'ordre, toujours
        out[i]["s"] = max(out[i]["s"], out[i - 1]["s"])
    for i in range(len(out) - 1):  # un mot dure jusqu'au suivant (au plus 1,2 s)
        out[i]["e"] = min(max(out[i]["e"], out[i]["s"] + 0.08), out[i + 1]["s"] if out[i + 1]["s"] > out[i]["s"] else out[i]["s"] + 0.08)
        out[i]["e"] = min(out[i]["e"], out[i]["s"] + 1.2)
    if out:
        out[-1]["e"] = min(max(out[-1]["e"], out[-1]["s"] + 0.25), out[-1]["s"] + 1.5)
    return out


# Petits mots qui appellent la suite : une ligne ne finit jamais par eux (« le », « de », « que »…)
GLUE = set("""le la les l' un une des du de d' au aux à a en dans sur sous pour par avec sans chez vers entre et ou mais donc
ni car que qu' qui quoi dont où je j' tu il elle on nous vous ils elles me m' te t' se s' ne n' mon ma mes ton ta tes son sa ses
notre nos votre vos leur leurs ce c' cet cette ces y si comme quand plus très trop pas the a an to of and or but in on at for
with my your his her our their i you we they is are was it that this tout tous toute toutes chaque même quelques""".split())
# Mots qui ouvrent une nouvelle idée : couper juste avant est naturel
STARTERS = set("""avec mais et quand pour dans sur sous comme parce puisque alors donc ou si sans depuis pendant chez vers
que qui où dont moi toi lui eux but and when because cause if with so then""".split())
# Rythme des sous-titres : mots par ligne, longueur, durée visée / minimale (secondes)
MODES = {
    "deux": {"label": "2 mots", "words": 2, "chars": 16, "target": 0.55, "min": 0.3},
    "court": {"label": "Phrases courtes", "words": 4, "chars": 24, "target": 1.0, "min": 0.5},
    "phrase": {"label": "Phrase entière", "words": 8, "chars": 38, "target": 2.0, "min": 0.8},
}


def _glue(word):
    """Le mot appelle la suite (article, préposition, pronom… ou « j'la », « l'y », « qu' »)."""
    w = re.sub(r"[^\w']", "", word.lower()).replace("’", "'")
    if not w or w.endswith("'") or w in GLUE:
        return True
    parts = [x for x in w.split("'") if x]
    return len(parts) > 1 and all((p + "'") in GLUE or p in GLUE for p in parts)


def _say(w):
    """Durée probable d'un mot dit (rap) : sert à repérer les respirations entre deux mots."""
    return 0.06 + 0.055 * len(re.sub(r"\W", "", w["w"]))


def _phrases(words):
    """Coupe les mots en phrases : nouvelle phrase de Whisper, ponctuation forte, ou respiration."""
    out, cur = [], []
    for i, w in enumerate(words):
        if cur:
            prev = cur[-1]
            gap = w["s"] - (prev["s"] + _say(prev))
            if w.get("g") != prev.get("g") or re.search(r"[.!?;:…,]$", prev["w"]) or gap > 0.6:
                out.append(cur)
                cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return out


def _split(ph, m):
    """Meilleur découpage d'une phrase en lignes (programmation dynamique) : lignes de durée
    régulière, jamais terminées par un petit mot, coupées de préférence sur une respiration ou
    une virgule, jamais trop longues à lire."""
    n = len(ph)
    ends = [ph[i + 1]["s"] if i + 1 < n else ph[i]["s"] + max(_say(ph[i]), 0.25) for i in range(n)]
    best = [0.0] + [float("inf")] * n
    back = [0] * (n + 1)
    for i in range(1, n + 1):
        for j in range(max(0, i - m["words"] * 2), i):
            chunk = ph[j:i]
            k = i - j
            text = " ".join(x["w"] for x in chunk)
            if k > m["words"] + 1 or (len(text) > m["chars"] + 6 and k > 1):
                continue
            dur = ends[i - 1] - chunk[0]["s"]
            cost = ((dur - m["target"]) / m["target"]) ** 2 + 0.35
            if k > m["words"] or len(text) > m["chars"]:
                cost += 1.5  # un mot de plus que prévu : seulement pour couper au bon endroit
            if dur < m["min"]:
                cost += 3.0 * (m["min"] - dur) / m["min"] + 1.0  # ligne qui passe trop vite
            if i < n and _glue(chunk[-1]["w"]):
                cost += 4.0  # « … que » / « … de » : la suite irait sur la ligne d'après
            if k == 1 and len(re.sub(r"\W", "", chunk[0]["w"])) <= 3 and n > 1:
                cost += 1.5  # un petit mot tout seul sur une ligne (« pas », « moi »…)
            if i < n and re.sub(r"[^\w]", "", ph[i]["w"].lower()) in STARTERS:
                cost -= 0.6  # la ligne suivante commence par « avec », « mais », « quand »…
            if i < n:
                gap = ph[i]["s"] - (chunk[-1]["s"] + _say(chunk[-1]))
                if gap > 0.2:
                    cost -= min(0.8, gap)  # coupure sur une respiration : naturelle
                if re.search(r"[,]$", chunk[-1]["w"]):
                    cost -= 0.5
            if best[j] + cost < best[i]:
                best[i], back[i] = best[j] + cost, j
    cuts, i = [], n
    while i > 0:
        cuts.append((back[i], i))
        i = back[i]
    return [ph[a:b] for a, b in reversed(cuts)]


def lines_from_words(words, mode="court", hold=1.2):
    """Mots datés → lignes de sous-titres logiques : jamais deux phrases dans une ligne, découpage
    le plus régulier possible, chaque ligne reste à l'écran jusqu'à la suivante (pas de trou), sauf
    vrai silence (> hold s : elle part 0,3 s après le dernier mot)."""
    m = MODES.get(mode) or MODES["court"]
    groups = []
    for ph in _phrases([w for w in words if w.get("w")]):
        groups += _split(ph, m)
    out = []
    for k, g in enumerate(groups):
        s = g[0]["s"]
        last = g[-1]["s"] + max(_say(g[-1]), 0.25)
        nxt = groups[k + 1][0]["s"] if k + 1 < len(groups) else None
        e = nxt if nxt is not None and nxt - last <= hold else last + 0.3
        text = re.sub(r"\s+", " ", " ".join(x["w"] for x in g)).strip()
        text = re.sub(r"[,;:.…]+$", "", text)
        out.append({"t": text, "s": round(s, 2), "e": round(max(e, s + 0.3), 2)})
    return out


def snap_to_voice(lines, vocals, start, dur):
    """Avec la voix seule : chaque ligne commence exactement quand ta voix reprend (montée du
    niveau de la piste voix près du moment donné par Whisper, ±0,35 s)."""
    ffmpeg = C.tool_path("ffmpeg.exe")
    if not (ffmpeg and vocals and lines):
        return lines
    try:
        r = subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.0, start):.3f}", "-t", f"{dur:.3f}",
                            "-i", str(vocals), "-ac", "1", "-ar", "8000", "-f", "s16le", "-"], capture_output=True, timeout=120,
                           creationflags=C.NO_WINDOW, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return lines
    import array
    pcm = array.array("h")
    pcm.frombytes(r.stdout[: len(r.stdout) // 2 * 2])
    hop = 80  # 10 ms
    rms = [(sum(x * x for x in pcm[i:i + hop]) / hop) ** 0.5 for i in range(0, len(pcm) - hop, hop)]
    if not rms:
        return lines
    loud = sorted(rms)[int(len(rms) * 0.9)] or 1
    thr = loud * 0.12
    out = []
    for i, ln in enumerate(lines):
        c = int(ln["s"] * 100)
        lo, hi = max(0, c - 35), min(len(rms) - 1, c + 35)
        best = None
        for f in range(lo + 3, hi + 1):  # attaque : silence juste avant, voix juste après
            if rms[f] >= thr and max(rms[f - 3:f]) < thr and (best is None or abs(f - c) < abs(best - c)):
                best = f
        s = best / 100 if best is not None else ln["s"]
        prev_s = out[-1]["s"] if out else -1
        out.append({**ln, "s": round(max(s, prev_s + 0.1), 2)})
    for i in range(len(out) - 1):
        if out[i]["e"] >= lines[i + 1]["s"] - 0.01:  # collée à la suivante : le reste
            out[i]["e"] = out[i + 1]["s"]
        out[i]["e"] = max(out[i]["e"], out[i]["s"] + 0.2)
    return out


def clean_lines(lines, dur=None):
    """Lignes venues de l'app (corrigées à la main) : texte court, temps rangés, sans chevauchement."""
    out = []
    for x in lines or []:
        if not isinstance(x, dict):
            continue
        t = re.sub(r"\s+", " ", str(x.get("t") or "")).strip()[:120]
        try:
            s, e = float(x.get("s")), float(x.get("e"))
        except (TypeError, ValueError):
            continue
        if not t or s < 0 or (dur and s >= dur):
            continue
        out.append({"t": t, "s": s, "e": max(e, s + 0.1)})
    out.sort(key=lambda x: x["s"])
    for i in range(len(out) - 1):
        out[i]["e"] = min(out[i]["e"], out[i + 1]["s"])
    if dur:
        for x in out:
            x["e"] = min(x["e"], dur)
    return out[:400]


def _run_whisper(cmd, exe, dur, say):
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            creationflags=C.NO_WINDOW, cwd=str(exe.parent))
    tail = []
    end = time.time() + max(900, dur * 60)
    for raw in iter(proc.stdout.readline, b""):
        line = raw.decode("utf-8", "replace").strip()
        if line:
            tail = (tail + [line])[-12:]
        m = re.search(r"progress\s*=\s*(\d+)%", line)
        if m:
            say("Écoute des paroles…", int(m.group(1)))
        if time.time() > end:
            proc.kill()
            raise PromoError("la transcription a pris trop de temps")
    proc.wait(timeout=60)
    if proc.returncode != 0:
        C.log("whisper : " + " | ".join(tail[-6:]))
    return proc.returncode, tail


def audio_duration(path):
    d = C.audio_seconds(path)
    return round(d, 2) if d else None


def transcribe(audio, start=0.0, dur=None, vocals=None, progress=None, lang="fr", threads=None, mode="court",
               isolate=True, snap=True, quality=None, title="", slow=None):
    """Paroles de l'extrait [start, start+dur] : {words, lines} (temps depuis le début de l'extrait).

    Whisper écoute TA VOIX SEULE : ta piste voix si tu l'as donnée, sinon ta voix séparée du beat
    sur le PC (mf_sep). Chaque mot est ensuite recalé sur l'attaque réelle de ta voix."""
    say = progress or (lambda *_: None)
    quality = _quality(quality)
    exe, model = ensure_whisper(say, quality)
    ffmpeg = C.tool_path("ffmpeg.exe")
    if not ffmpeg:
        raise PromoError("ffmpeg manquant")
    total = audio_duration(vocals or audio) or 0
    start = max(0.0, float(start or 0))
    dur = float(dur) if dur else max(1.0, total - start)
    pad = min(start, 1.0)
    with tempfile.TemporaryDirectory(prefix="melofinds-paroles-", ignore_cleanup_errors=True) as tmp:
        voice, off, how = (Path(vocals), start - pad, "piste voix") if vocals else (Path(audio), start - pad, "mix")
        if not vocals and isolate:
            import mf_sep as S
            if S.available():
                try:
                    voice = S.separate(audio, start - pad, dur + pad + 0.5, Path(tmp) / "voix.wav", say)
                    off, how = 0.0, "voix séparée"
                except Exception as e:  # séparation impossible : Whisper écoute le mix (moins précis)
                    C.log(f"Promo : voix non séparée ({e})")
        wav = Path(tmp) / "extrait.wav"
        flt = "highpass=f=100,lowpass=f=7000,dynaudnorm=f=150" if how == "mix" else "highpass=f=70,dynaudnorm=f=150"
        # slow (< 1) : la voix est ralentie (même hauteur) pour que Whisper suive un débit rapide ;
        # les moments des mots sont ensuite remis à la vraie vitesse
        slow = MODELS[quality]["slow"] if slow is None else slow
        slow = float(slow) if slow and 0.5 <= float(slow) < 1 else 1.0
        if slow < 1:
            flt += f",atempo={slow:.3f}"
        r = subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{off:.3f}",
                            "-t", f"{dur + pad + 0.5:.3f}", "-i", str(voice), "-vn", "-ac", "1", "-ar", "16000",
                            "-af", flt, "-c:a", "pcm_s16le", str(wav)],
                           capture_output=True, timeout=300, creationflags=C.NO_WINDOW, stdin=subprocess.DEVNULL)
        if r.returncode != 0 or not wav.exists():
            raise PromoError(f"son illisible : {C.last_line(r.stderr)}")
        say("Écoute des paroles…", 0)
        base = [str(exe), "-m", str(model), "-f", str(wav), "-l", lang, "-ojf", "-of", str(Path(tmp) / "paroles"),
                "-t", str(threads or max(2, min(8, (os.cpu_count() or 4)))), "-pp", "--dtw", MODELS[quality]["dtw"],
                "-bs", "5", "-bo", "5", "--prompt", prompt_for(title)]
        out = Path(tmp) / "paroles.json"
        # « -nfa » : l'alignement mot à mot (DTW) ne marche pas avec l'accélération « flash attention »
        # (activée d'office dans les versions récentes) ; sans cette option si la version ne la connaît pas
        for cmd in (base + ["-nfa"], base):
            code, tail = _run_whisper(cmd, exe, dur, say)
            if code == 0 and out.exists():
                break
            if not any(re.search(r"unknown|invalid|usage", t, re.I) for t in tail):
                break
        if code != 0 or not out.exists():
            raise PromoError("transcription impossible : " + (tail[-1] if tail else f"code {code}"))
        data = json.loads(out.read_bytes().decode("utf-8", "surrogateescape"))
        dtw = sum(1 for seg in data.get("transcription") or [] for t in seg.get("tokens") or []
                  if isinstance(t.get("t_dtw"), (int, float)) and t["t_dtw"] >= 0)
        words = []
        for w in words_from_json(data):
            s, e = w["s"] * slow - pad, w["e"] * slow - pad
            if e <= 0 or s >= dur:
                continue
            words.append({"w": w["w"], "s": round(max(0.0, s), 2), "e": round(min(dur, e), 2), "g": w.get("g", 0)})
        if dtw:  # retard de Whisper corrigé (les mots restent dans l'ordre)
            for w in words:
                w["s"] = round(max(0.0, w["s"] - DTW_SHIFTS.get(quality, DTW_SHIFT)), 2)
        if how != "mix" and snap:  # voix seule : chaque mot recalé sur l'attaque réelle de la voix
            say("Calage des mots sur ta voix…", None)
            words = snap_words(words, voice, off + pad, dur)
    lines = lines_from_words(words, mode)
    return {"words": words, "lines": lines, "dur": round(dur, 2), "dtw": dtw, "voice": how, "quality": quality}


def _voice_env(voice, off, dur):
    """Énergie de la voix (dB) toutes les 10 ms, à partir de `off` secondes dans le fichier."""
    ffmpeg = C.tool_path("ffmpeg.exe")
    if not ffmpeg:
        return None
    try:
        r = subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.0, off):.3f}", "-t", f"{dur + 0.5:.3f}",
                            "-i", str(voice), "-ac", "1", "-ar", "8000", "-f", "s16le", "-"], capture_output=True, timeout=120,
                           creationflags=C.NO_WINDOW, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    import array
    import math
    pcm = array.array("h")
    pcm.frombytes(r.stdout[: len(r.stdout) // 2 * 2])
    hop = 80
    env = []
    for i in range(0, len(pcm) - hop, hop):
        e = sum(x * x for x in pcm[i:i + hop]) / hop
        env.append(10 * math.log10(e + 1.0))
    return env


def snap_words(words, voice, off, dur, reach=0.12, later=0.05):
    """Recale les mots sur les attaques de la voix seule (montées d'énergie). Mise en
    correspondance globale dans l'ordre (programmation dynamique) : chaque mot prend une attaque
    différente, la plus proche de son moment Whisper (jusqu'à `reach` s avant, `later` s après) ;
    sinon il garde ce moment. Mesuré (CI) : 0,05 s d'erreur moyenne → environ 0,03 s."""
    env = _voice_env(voice, off, dur)
    if not env or not words:
        return words
    srt = sorted(env)
    floor, peak = srt[len(env) // 10], srt[int(len(env) * 0.95)]
    if peak - floor < 12:  # pas de voix nette : on ne touche à rien
        return words
    strength = [0.0] * len(env)
    for t in range(3, len(env)):
        rise = env[t] - env[t - 3]
        if rise > 4 and env[t] > floor + (peak - floor) * 0.3:
            strength[t] = rise
    cands = []  # attaques : maxima locaux, au moins 60 ms d'écart
    for t in range(3, len(env) - 1):
        if strength[t] > 0 and strength[t] >= strength[t - 1] and strength[t] >= strength[t + 1]:
            if cands and t - cands[-1][0] < 6:
                if strength[t] > cands[-1][1]:
                    cands[-1] = (t, strength[t])
                continue
            cands.append((t, strength[t]))
    times = [(t - 2) / 100 for t, _ in cands]  # début de la montée
    n, m = len(words), len(times)
    if not m:
        return words
    big = 10 ** 9
    keep = reach * 0.9  # coût d'un mot laissé à son moment Whisper
    # best[i][j] : coût minimal des i premiers mots en n'utilisant que les j premières attaques
    best = [[0.0] * (m + 1)] + [[big] * (m + 1) for _ in range(n)]
    how = [[None] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        ws = words[i - 1]["s"]
        for j in range(0, m + 1):
            c = best[i - 1][j] + keep  # mot non recalé
            h = ("keep", j)
            if j > 0:
                c2 = best[i][j - 1]  # attaque j inutilisée
                if c2 < c:
                    c, h = c2, ("skip", j - 1)
                d = times[j - 1] - ws  # mesuré : avancer jusqu'à 0,12 s aide ; reculer de plus de 0,05 s non
                if -reach <= d <= later:
                    d = abs(d)
                    c3 = best[i - 1][j - 1] + d - 0.01 * min(cands[j - 1][1], 20) / 20
                    if c3 < c:
                        c, h = c3, ("take", j - 1)
            best[i][j], how[i][j] = c, h
    out = [dict(w) for w in words]
    i, j = n, m
    while i > 0:
        kind, jj = how[i][j]
        if kind == "take":
            out[i - 1]["s"] = round(max(0.0, times[jj]), 2)
            i, j = i - 1, jj
        elif kind == "skip":
            j = jj
        else:
            i, j = i - 1, jj
    for k in range(1, n):  # toujours dans l'ordre
        out[k]["s"] = round(max(out[k]["s"], out[k - 1]["s"] + 0.05), 2)
    for k in range(n - 1):
        out[k]["e"] = max(out[k]["s"] + 0.05, min(out[k]["e"], out[k + 1]["s"]))
    return out


# ---------------------------------------------------------------------------
# Sous-titres (ASS) et vidéo

def _ass_time(t):
    t = max(0.0, t)
    h, rem = divmod(int(round(t * 100)), 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_text(t, case):
    t = t.upper() if case == "upper" else t.lower() if case == "lower" else t
    return t.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def make_ass(lines, style="impact", pos="centre", scale=1.0):
    st = STYLES.get(style) or STYLES["impact"]
    align, margin = POSITIONS.get(pos) or POSITIONS["centre"]
    size = int(st["size"] * max(0.6, min(1.6, float(scale or 1))))
    head = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
            "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            f"Style: Promo,{st['font']},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H78000000,0,0,0,0,100,100,{st['spacing']},0,1,"
            f"{st['outline']},{st['shadow']},{align},90,90,{margin},1", "",
            "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    ev = []
    for x in lines:
        pop = r"{\fscx112\fscy112\t(0,90,\fscx100\fscy100)}"  # petite apparition « pop »
        ev.append(f"Dialogue: 0,{_ass_time(x['s'])},{_ass_time(x['e'])},Promo,,0,0,0,,{pop}{_ass_text(x['t'], st['case'])}")
    return "\n".join(head + ev) + "\n"


SPEEDS = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)


def media_duration(path):
    d = C.audio_seconds(path)
    return round(d, 2) if d else None


def clip_visual(bg, out, vstart=0.0, vlen=None, speed=1.0, w=W, h=H, fps=30, crf=18, total=None):
    """La partie choisie du visuel (à partir de `vstart` s, `vlen` s du visuel, vitesse `speed`)
    → clip propre en portrait w x h, images régulières, sans son : c'est lui qui tourne en boucle
    derrière les paroles (horodatage remis à zéro : la vidéo défile toujours, jamais figée)."""
    ffmpeg = C.tool_path("ffmpeg.exe")
    if not ffmpeg:
        raise PromoError("ffmpeg manquant")
    speed = min(4.0, max(0.25, float(speed or 1.0)))
    total = total if total is not None else (media_duration(bg) or 0.0)
    vstart = max(0.0, float(vstart or 0.0))
    if total:
        vstart = min(vstart, max(0.0, total - 0.3))
    span = float(vlen) if vlen else (total - vstart if total else 60.0)
    span = max(0.3, min(180.0 * speed, span, (total - vstart) if total else span))
    vf = (f"setpts=(PTS-STARTPTS)/{speed:.4f},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
          f"setsar=1,fps={fps},format=yuv420p")
    r = subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{vstart:.3f}", "-t", f"{span:.3f}",
                        "-i", str(bg), "-an", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), str(out)],
                       capture_output=True, timeout=600, creationflags=C.NO_WINDOW, stdin=subprocess.DEVNULL)
    if r.returncode != 0 or not Path(out).exists() or Path(out).stat().st_size < 500:
        raise PromoError(f"visuel illisible : {C.last_line(r.stderr)}")
    return Path(out), round(span / speed, 3)


def preview_stream(clip, offset=0.0, fps=12):
    """Images PNG du clip d'aperçu, au rythme réel et en boucle (pour l'aperçu qui bouge)."""
    ffmpeg = C.tool_path("ffmpeg.exe")
    if not ffmpeg:
        return None
    return subprocess.Popen([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-re", "-stream_loop", "-1",
                             "-ss", f"{max(0.0, offset):.3f}", "-i", str(clip), "-vf", f"fps={fps}", "-f", "image2pipe",
                             "-vcodec", "png", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                            creationflags=C.NO_WINDOW)


PNG_SIG = b"\x89PNG\r\n\x1a\n"


def png_frames(f):
    """Découpe un flux d'images PNG collées les unes aux autres (sortie de preview_stream)."""
    while True:
        sig = f.read(8)
        if len(sig) < 8 or sig != PNG_SIG:
            return
        parts = [sig]
        while True:
            head = f.read(8)
            if len(head) < 8:
                return
            n = int.from_bytes(head[:4], "big")
            if n > 50_000_000:
                return
            body = f.read(n + 4)
            if len(body) < n + 4:
                return
            parts += [head, body]
            if head[4:8] == b"IEND":
                break
        yield b"".join(parts)


def render(bg, audio, start, dur, lines, out, style="impact", pos="centre", scale=1.0, progress=None, visual=None):
    """Vidéo 1080x1920 : visuel (la partie choisie, recadré, en boucle) + extrait du son + paroles incrustées.
    visual : {"start": s dans la vidéo, "len": s utilisées (None : jusqu'à la fin), "speed": vitesse}."""
    say = progress or (lambda *_: None)
    ffmpeg = C.tool_path("ffmpeg.exe")
    if not ffmpeg:
        raise PromoError("ffmpeg manquant")
    fonts = ensure_fonts(say)
    dur = max(1.0, min(180.0, float(dur)))
    lines = clean_lines(lines, dur)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="melofinds-promo-", ignore_cleanup_errors=True) as tmp:
        tmp = Path(tmp)
        (tmp / "paroles.ass").write_text(make_ass(lines, style, pos, scale), encoding="utf-8")
        fd = tmp / "fonts"
        fd.mkdir()
        for f in Path(fonts).glob("*.ttf"):
            shutil.copyfile(f, fd / f.name)
        part = tmp / "promo.mp4"
        vis = visual or {}
        say("Préparation du visuel…", None)
        seg, _ = clip_visual(bg, tmp / "visuel.mp4", vis.get("start") or 0.0, vis.get("len"), vis.get("speed") or 1.0)
        vf = "ass=paroles.ass:fontsdir=fonts"
        af = f"afade=t=in:d=0.03,afade=t=out:st={max(0.0, dur - 0.4):.2f}:d=0.4"
        cmd = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-progress", "pipe:1", "-nostats",
               "-stream_loop", "-1", "-i", str(seg), "-ss", f"{float(start):.3f}", "-t", f"{dur:.3f}", "-i", str(audio),
               "-map", "0:v:0", "-map", "1:a:0", "-vf", vf, "-af", af, "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-t", f"{dur:.3f}", "-movflags", "+faststart",
               str(part)]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                creationflags=C.NO_WINDOW, cwd=str(tmp))
        for raw in iter(proc.stdout.readline, b""):
            m = re.match(rb"out_time_(?:us|ms)=(\d+)", raw)
            if m:
                say("Création de la vidéo…", min(99, int(int(m.group(1)) / 1e6 / dur * 100)))
        err = proc.stderr.read()
        proc.wait(timeout=60)
        if proc.returncode != 0 or not part.exists() or part.stat().st_size < 1000:
            raise PromoError(f"vidéo impossible : {C.last_line(err)}")
        shutil.move(str(part), str(out))
    say("Vidéo prête", 100)
    return out


def out_name(title, cfg=None):
    return videos_dir(cfg) / f"{safe_name(title)} - promo {datetime.now():%Y-%m-%d %H-%M-%S}.mp4"


def thumbnail(video, dest):
    ffmpeg = C.tool_path("ffmpeg.exe")
    if not ffmpeg:
        return None
    r = subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-ss", "0.8", "-i", str(video),
                        "-frames:v", "1", "-vf", "scale=360:-2", str(dest)], capture_output=True, timeout=60,
                       creationflags=C.NO_WINDOW, stdin=subprocess.DEVNULL)
    return Path(dest) if r.returncode == 0 and Path(dest).exists() else None


# ---------------------------------------------------------------------------
# Visuels : tes vidéos et celles d'Instagram (avec le nom du compte pour la mention)

def _visuals_db(cfg=None):
    return visuals_dir(cfg) / "visuels.json"


def visuals(cfg=None):
    """Visuels gardés : [{file, thumb, user, url, at}] (les plus récents d'abord, fichiers présents)."""
    try:
        db = json.loads(_visuals_db(cfg).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        db = []
    out = []
    for v in db if isinstance(db, list) else []:
        f = visuals_dir(cfg) / str(v.get("file") or "")
        if v.get("file") and f.exists() and f.parent == visuals_dir(cfg):
            out.append(v)
    return sorted(out, key=lambda v: -(v.get("at") or 0))


def _save_visual(entry, cfg=None):
    db = [v for v in visuals(cfg) if v.get("file") != entry["file"]]
    db.insert(0, entry)
    p = _visuals_db(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(db[:300], ensure_ascii=False, indent=1), encoding="utf-8")
    return entry


def ig_shortcode(url):
    m = IG_RE.match(str(url or "").strip())
    return m.group(1) if m else None


def ig_download(url, progress=None, cookies=None, cfg=None):
    """Télécharge la vidéo d'un post / reel Instagram (lien choisi par toi) dans Promo/Visuels."""
    say = progress or (lambda *_: None)
    url = str(url or "").strip()
    code = ig_shortcode(url)
    if not code:
        raise PromoError("colle le lien d'une vidéo Instagram (…instagram.com/reel/… ou /p/…)")
    have = next((v for v in visuals(cfg) if v.get("code") == code), None)
    if have:
        return have
    ytdlp, ffmpeg = C.tool_path("yt-dlp.exe"), C.tool_path("ffmpeg.exe")
    if not ytdlp:
        raise PromoError("yt-dlp manquant")
    dest = visuals_dir(cfg)
    dest.mkdir(parents=True, exist_ok=True)
    say("Téléchargement du visuel…", None)
    with tempfile.TemporaryDirectory(prefix="melofinds-visuel-", ignore_cleanup_errors=True) as tmp:
        cmd = [ytdlp, "--no-playlist", "--no-warnings", "--no-progress", "-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
               "--merge-output-format", "mp4", "--write-info-json", "-o", str(Path(tmp) / "v.%(ext)s"), "--max-filesize", "300M"]
        if ffmpeg:
            cmd += ["--ffmpeg-location", str(Path(ffmpeg).parent)]
        if cookies and Path(cookies).exists():
            cmd += ["--cookies", str(cookies)]
        r = C.run_tool(cmd + [f"https://www.instagram.com/p/{code}/"], 600)
        vids = [p for p in Path(tmp).iterdir() if p.suffix.lower() in VIDEO_EXT]
        if r.returncode != 0 or not vids:
            msg = C.last_line(r.stderr) or C.last_line(r.stdout)
            if re.search(r"login|log in|rate-limit|not available|private", msg, re.I):
                raise PromoError("Instagram demande d'être connecté : Réglages → Compte Instagram, puis réessaie")
            raise PromoError(f"téléchargement impossible : {msg[:160]}")
        info = {}
        for j in Path(tmp).glob("*.info.json"):
            try:
                info = json.loads(j.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        user = next((str(info.get(k)) for k in ("channel", "uploader_id", "uploader") if USER_RE.match(str(info.get(k) or ""))), "")
        name = f"{safe_name(user or 'instagram', 30)} - {code}.mp4"
        shutil.move(str(vids[0]), str(dest / name))
    th = thumbnail(dest / name, dest / f"{Path(name).stem}.jpg")
    return _save_visual({"file": name, "thumb": th.name if th else "", "user": user, "url": f"https://www.instagram.com/p/{code}/",
                         "code": code, "at": int(time.time())}, cfg)


def add_own_video(path, cfg=None):
    """Ta vidéo (choisie sur le PC) : copiée dans Promo/Visuels, sans mention."""
    src = Path(path)
    if src.suffix.lower() not in VIDEO_EXT or not src.is_file():
        raise PromoError("vidéo .mp4, .mov, .webm ou .mkv attendue")
    dest = visuals_dir(cfg)
    dest.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(f"{src.resolve()}|{src.stat().st_size}|{src.stat().st_mtime}".encode()).hexdigest()[:8]
    name = f"{safe_name(src.stem, 40)} - {digest}{src.suffix.lower()}"
    if not (dest / name).exists():
        shutil.copyfile(src, dest / name)
    th = thumbnail(dest / name, dest / f"{Path(name).stem}.jpg")
    return _save_visual({"file": name, "thumb": th.name if th else "", "user": "", "url": "", "code": "", "at": int(time.time())}, cfg)


def remove_visual(name, cfg=None):
    vs = visuals(cfg)
    v = next((x for x in vs if x.get("file") == name), None)
    if not v:
        return False
    for f in (v.get("file"), v.get("thumb")):
        if f:
            try:
                (visuals_dir(cfg) / f).unlink(missing_ok=True)
            except OSError:
                pass
    p = _visuals_db(cfg)
    p.write_text(json.dumps([x for x in vs if x.get("file") != name], ensure_ascii=False, indent=1), encoding="utf-8")
    return True


def description(title, tags, user="", extra=""):
    """Description à copier : titre, tes #, et « visuel : @compte » à la fin."""
    tags = [t if t.startswith("#") else f"#{t}" for t in (re.sub(r"[^\w#]", "", str(x)) for x in tags or []) if len(t.strip("#"))]
    parts = [p for p in (str(title or "").strip(), str(extra or "").strip(), " ".join(dict.fromkeys(tags))) if p]
    if user:
        parts.append(f"visuel : @{user.lstrip('@')}")
    return "\n\n".join(parts)


def project_sounds(cfg=None):
    """Tous tes projets FL, chacun avec ses sons : tes versions (avec ta voix) de la plus récente
    à la plus ancienne, tes exports, puis l'instru (sans voix) en dernier."""
    import mf_library as L
    cfg = cfg if cfg is not None else C.load_config()
    out = []
    for it in L.scan_projects(cfg)[:600]:
        af = [f for f in L.audio_files(it, 120) if f["kind"] != "fl" and f["ext"] in ("wav", "mp3", "m4a", "flac", "ogg")]
        if not af:
            continue
        vers = sorted((f for f in af if f["kind"] == "version"), key=lambda f: f["ver"], reverse=True)
        exps = sorted((f for f in af if f["kind"] == "export"), key=lambda f: -f["mtime"])
        ins = [f for f in af if f["instru"]]
        files = []
        for f in vers + exps + ins:
            label = f["label"] or (f["name"][:50] if f["kind"] == "export" else "Instru")
            files.append({"path": Path(f["path"]), "label": label, "kind": f["kind"], "ext": f["ext"],
                          "voice": not f["instru"], "latest": bool(f.get("latest")), "date": int(f["mtime"])})
        out.append({"title": it.title[:120], "key": it.key or "", "bpm": it.bpm or 0, "color": it.extra.get("color"),
                    "date": int(it.date or 0), "fl": bool(it.flp), "files": files[:40]})
    return out


VOCAL_RE = re.compile(r"(?:^|[\s_\-.(\[])(voix|vocals?|vox|voc|acap+ella|a\s?cap+ella|lead|chant|rap)(?:$|[\s_\-.)\]\d])", re.I)


def find_vocal_stem(audio):
    """Ta piste voix exportée dans le même projet (« LESGUI voix.wav », « Lead Vocal.wav »…), la plus
    récente, sinon None. Promo l'utilise toute seule : les paroles sont calées sur ta vraie voix."""
    audio = Path(audio)
    seen, found = set(), []
    for d in {audio.parent, audio.parent.parent} if audio.parent.name.lower() in ("exports", "export", "stems", "bounces") else {audio.parent}:
        try:
            for p in d.rglob("*"):
                if len(p.relative_to(d).parts) > 3 or p.suffix.lower() not in AUDIO_EXT or p == audio or p in seen:
                    continue
                seen.add(p)
                if VOCAL_RE.search(p.stem) and not re.search(r"instru|beat|prod|sans voix|no vocal", p.stem, re.I):
                    found.append(p)
        except OSError:
            continue
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def frame_png(video, dest, w=270, h=480, at=1.0):
    """Image du visuel recadrée en portrait (PNG : lisible par la fenêtre du logiciel)."""
    ffmpeg = C.tool_path("ffmpeg.exe")
    if not ffmpeg:
        return None
    for t in (at, 0):
        r = subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.2f}", "-i", str(video),
                            "-frames:v", "1", "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}", str(dest)],
                           capture_output=True, timeout=60, creationflags=C.NO_WINDOW, stdin=subprocess.DEVNULL)
        if r.returncode == 0 and Path(dest).exists():
            return Path(dest)
    return None


def new_token():
    return secrets.token_hex(12)


# ---------------------------------------------------------------------------
# Instagram : fenêtre normale où TU navigues (connecté ou non) ; Melofinds lit seulement
# l'adresse de la vidéo ouverte pour proposer « Utiliser cette vidéo ». Rien n'est aspiré.

def ig_profile_dir():
    return C.P.base / "instagram-profile"


def ig_cookies_file():
    return C.P.base / "instagram-cookies.txt"


IG_DOMAINS = (".instagram.com", "instagram.com")


class IGBrowser:
    def __init__(self, on_url=None):
        self.on_url = on_url or (lambda *_: None)
        self.proc = self.port = self.bpath = None
        self.last = None

    def running(self):
        if not (self.proc and self.port):
            return False
        if self.proc.poll() is None:
            return True
        try:  # le processus lancé a pu passer la main à un autre Edge : la fenêtre répond-elle ?
            import mf_tunebat as T
            T.local_get(f"http://127.0.0.1:{self.port}/json/version", 2)
            return True
        except OSError:
            return False

    def open(self, user=""):
        import threading
        import mf_tunebat as T
        user = user if USER_RE.match(str(user or "")) else ""
        url = f"https://www.instagram.com/{user}/" if user else "https://www.instagram.com/"
        if self.running():
            try:
                page = T._page(self.port, 5)
                c = T.CDP(page["webSocketDebuggerUrl"])
                try:
                    c.call("Page.navigate", {"url": url})
                finally:
                    c.close()
                return url
            except Exception:
                pass
        browser = T.find_browser()
        if not browser:
            raise PromoError("Edge ou Chrome introuvable sur ce PC")
        prof = ig_profile_dir()
        prof.mkdir(parents=True, exist_ok=True)
        T.kill_profile(prof)
        pf = prof / "DevToolsActivePort"
        try:
            pf.unlink(missing_ok=True)
        except OSError:
            pass
        self.proc = subprocess.Popen([browser, f"--user-data-dir={prof}", "--remote-debugging-port=0", "--no-first-run", *T.NO_BACKGROUND,
                                      "--no-default-browser-check", f"--app={url}", "--window-size=520,900"],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            self.port, self.bpath = T._wait_port(pf, self.proc, 30)
        except T.TunebatError as e:
            raise PromoError(str(e))
        threading.Thread(target=self._watch, daemon=True).start()
        return url

    def _watch(self):
        import mf_tunebat as T
        while self.running():
            for t in T._targets(self.port):
                u = str(t.get("url") or "")
                if t.get("type") == "page" and ig_shortcode(u) and u != self.last:
                    self.last = u
                    self.on_url(u)
            time.sleep(1.0)
        self.on_url(None)

    def cookies(self):
        """Cookies Instagram de la fenêtre (si tu t'y es connecté) pour yt-dlp, sinon None."""
        import mf_tunebat as T
        import mf_ytlogin as Y
        check = lambda text: "\tsessionid\t" in text
        try:
            if self.running():
                b = T.CDP(f"ws://127.0.0.1:{self.port}{self.bpath}")
                try:
                    cookies = (b.call("Storage.getCookies") or {}).get("cookies") or []
                finally:
                    b.close()
                text, n = Y._netscape(cookies, IG_DOMAINS)
                if n:
                    ig_cookies_file().write_text(text, encoding="utf-8")
                    return ig_cookies_file() if check(text) else None
                return None
            if ig_profile_dir().exists():
                return ig_cookies_file() if Y.export_cookies(prof=ig_profile_dir(), out=ig_cookies_file(), domains=IG_DOMAINS,
                                                             check=check) else None
        except Exception as e:
            C.log(f"Cookies Instagram : {e}")
        return None

    def close(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Service appelé par le site (page Promo dans Melofinds PC). Les fichiers ne sont jamais
# désignés par un chemin venu du site : seulement par un jeton donné par le PC.

class Service:
    def __init__(self, ask_file=None, emit=None, reveal=None):
        self.ask_file = ask_file or (lambda kind: None)
        self.emit = emit or (lambda ev: None)
        self.reveal = reveal or _reveal
        self.files = {}  # jeton → chemin
        self.ig = IGBrowser(lambda u: self.emit({"type": "ig-url", "url": u}))
        self.want_view = None  # page du site à ouvrir (bouton « Promo » du logiciel)

    def token_for(self, path):
        path = Path(path)
        for k, v in self.files.items():
            if v == path:
                return k
        k = new_token()
        self.files[k] = path
        return k

    def path_of(self, token, kinds=None):
        p = self.files.get(str(token or ""))
        if not p or not p.exists():
            raise PromoError("fichier introuvable (recharge la page Promo)")
        if kinds and p.suffix.lower() not in kinds:
            raise PromoError("type de fichier refusé")
        return p

    def media(self, p):
        return {"token": self.token_for(p), "name": Path(p).name}

    def _visual(self, v, cfg=None):
        d = visuals_dir(cfg)
        out = {**self.media(d / v["file"]), "user": v.get("user") or "", "url": v.get("url") or "", "file": v["file"]}
        if v.get("thumb") and (d / v["thumb"]).exists():
            out["thumb"] = self.token_for(d / v["thumb"])
        return out

    def call(self, cmd, args, progress):
        """Commande du site → résultat (dict / liste). Lève PromoError avec un message clair."""
        args = args if isinstance(args, dict) else {}
        cfg = C.load_config()
        if cmd == "hello":
            view, self.want_view = self.want_view, None
            return {"version": C.VERSION, "view": view, "ready": ready(), "accounts": ACCOUNTS, "styles": {k: v["label"] for k, v in STYLES.items()},
                    "folder": str(promo_dir(cfg))}
        if cmd == "projects":
            return self.projects(cfg)
        if cmd == "send":  # prod / commande du site : directement au programme en ligne, sans internet
            code = str(args.get("code") or "")
            if not any(d.get("code") == code for d in cfg.get("devices", [])):
                raise PromoError("appareil inconnu de ce PC")
            C.inbox_put(code, str(args.get("body") or ""))
            import mf_install as I
            return {"online": bool(I.worker_running())}
        if cmd == "pick":
            kind = "video" if args.get("kind") == "video" else "audio"
            p = self.ask_file(kind)
            if not p:
                return None
            p = Path(p)
            if kind == "video":
                return self._visual(add_own_video(p, cfg), cfg)
            if p.suffix.lower() not in AUDIO_EXT:
                raise PromoError("son .wav, .mp3, .m4a ou .flac attendu")
            return {**self.media(p), "title": p.stem, "dur": audio_duration(p)}
        if cmd == "info":
            p = self.path_of(args.get("token"), AUDIO_EXT)
            return {"dur": audio_duration(p), "title": p.stem}
        if cmd == "prepare":
            ensure_whisper(progress)
            ensure_fonts(progress)
            return ready()
        if cmd == "transcribe":
            audio = self.path_of(args.get("audio"), AUDIO_EXT)
            vocals = self.path_of(args["vocals"], AUDIO_EXT) if args.get("vocals") else None
            return transcribe(audio, float(args.get("start") or 0), float(args.get("dur") or 0) or None, vocals, progress,
                              quality=args.get("quality"), title=str(args.get("title") or "")[:80])
        if cmd == "render":
            audio = self.path_of(args.get("audio"), AUDIO_EXT)
            bg = self.path_of(args.get("bg"), VIDEO_EXT)
            out = render(bg, audio, float(args.get("start") or 0), float(args.get("dur") or 15), args.get("lines") or [],
                         out_name(args.get("title") or audio.stem, cfg), str(args.get("style") or "impact"),
                         str(args.get("pos") or "centre"), float(args.get("scale") or 1), progress,
                         visual={k: args["visual"].get(k) for k in ("start", "len", "speed")} if isinstance(args.get("visual"), dict) else None)
            return {**self.media(out), "path": str(out)}
        if cmd == "visuals":
            return [self._visual(v, cfg) for v in visuals(cfg)]
        if cmd == "ig.open":
            return {"url": self.ig.open(str(args.get("user") or ""))}
        if cmd == "ig.use":
            v = ig_download(str(args.get("url") or ""), progress, self.ig.cookies(), cfg)
            return self._visual(v, cfg)
        if cmd == "visual.remove":
            return remove_visual(str(args.get("file") or ""), cfg)
        if cmd == "reveal":
            p = self.path_of(args.get("token"))
            self.reveal(p)
            return True
        if cmd == "folder":
            d = promo_dir(cfg)
            d.mkdir(parents=True, exist_ok=True)
            self.reveal(d)
            return True
        raise PromoError("commande inconnue")

    def projects(self, cfg):
        out = project_sounds(cfg)
        for p in out:
            p["files"] = [{**{k: v for k, v in f.items() if k != "path"}, **self.media(f["path"])} for f in p["files"]]
        return out

    def close(self):
        self.ig.close()


def _reveal(p):
    p = Path(p)
    if C.WINDOWS:
        if p.is_file():
            subprocess.Popen(["explorer", "/select,", str(p)])
        else:
            os.startfile(str(p))  # noqa (Windows)
    else:
        subprocess.Popen(["xdg-open", str(p if p.is_dir() else p.parent)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
