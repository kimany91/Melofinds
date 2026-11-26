"""Page « Promo » du logiciel (Tk, sans navigateur) : ton son → paroles écrites par Whisper
(au mot près, corrigeables) → visuel → style → vidéo TikTok / Reels + description à copier.

Le travail lourd est dans mf_promo (Whisper, ffmpeg) ; cette page n'est que l'interface. Les
tâches longues tournent en arrière-plan et rendent la main à Tk par une file (jamais d'appel à
Tk depuis un autre fil).
"""

import base64
import queue
import re
import tempfile
import threading
from pathlib import Path

import mf_core as C
import mf_promo as PM

PREVIEW_W, PREVIEW_H = 270, 480
DURS = (10, 15, 20, 30, 45, 60)
STYLE_FONTS = {"impact": ("Anton", "Impact"), "pixel": ("Silkscreen", "Consolas"), "bold": ("Archivo Black", "Arial Black")}
DEFAULT_TAGS = "#rap #rapfr #spotify"


def _mmss(t):
    t = max(0.0, float(t or 0))
    return f"{int(t // 60)}:{int(t % 60):02d}.{int((t % 1) * 10)}"


def parse_time(text):
    m = re.fullmatch(r"\s*(?:(\d+):)?(\d+(?:[.,]\d+)?)\s*", str(text or ""))
    return int(m.group(1) or 0) * 60 + float(m.group(2).replace(",", ".")) if m else None


def norm_lines(lines, dur):
    """Lignes rangées dans l'ordre ; chacune reste jusqu'à la suivante (pas de trou)."""
    lines.sort(key=lambda x: x["s"])
    for i, ln in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        if nxt and (ln["e"] > nxt["s"] or nxt["s"] - ln["e"] <= 1.2):
            ln["e"] = nxt["s"]
        if not nxt:
            ln["e"] = min(dur, max(ln["e"], ln["s"] + 0.3))
    return lines


def description(title, tags, user):
    return PM.description(title, str(tags or "").split(), user)


def register_fonts():
    """Polices des sous-titres utilisables dans la fenêtre (Windows : pour ce programme seulement)."""
    if not C.WINDOWS:
        return
    try:
        import ctypes
        for f in Path(PM.fonts_dir()).glob("*.ttf"):
            ctypes.windll.gdi32.AddFontResourceExW(str(f), 0x10, 0)  # FR_PRIVATE
    except Exception:
        pass


def build(ctx):
    """ctx : tk, root, page, Btn, card, label, entry, scroll_area, toast, PLAYER, colors, ico, filedialog, on_show."""
    tk, root, Btn, card, label = ctx.tk, ctx.root, ctx.Btn, ctx.card, ctx.label
    BG, PANEL, PANEL2, PANEL3, FG, MUTED, FAINT, ACCENT, LINE, FONT, MONO = (
        ctx.colors[k] for k in ("BG", "PANEL", "PANEL2", "PANEL3", "FG", "MUTED", "FAINT", "ACCENT", "LINE", "FONT", "MONO"))
    PLAYER = ctx.PLAYER
    content = ctx.page("promo", "Promo", "Ta vidéo TikTok / Reels : tes paroles en sous-titres, au mot près, sur le visuel que tu choisis.")

    cfg0 = C.load_config()
    st = {"projects": None, "q": "", "more": False, "audio": None, "title": "", "label": "", "voice": True, "dur_total": 0.0,
          "vocals": None, "vocals_auto": False, "start": 0.0, "dur": 20, "lines": [], "words": [], "mode": cfg0.get("promo_mode", "court"), "quality": cfg0.get("promo_quality", PM.QUALITY), "visuals": None, "bg": None, "style": cfg0.get("promo_style", "impact"),
          "pos": cfg0.get("promo_pos", "centre"), "scale": float(cfg0.get("promo_scale", 1.0) or 1.0), "busy": None, "result": None,
          "ig_url": None, "accounts": list(cfg0.get("promo_accounts") or PM.ACCOUNTS), "tags": cfg0.get("promo_tags", DEFAULT_TAGS),
          "keep": cfg0.get("promo_keep_tags", True), "frame": None, "playing": False, "cur": -1, "thumbs": {}, "fonts": False,
          # partie du visuel : début dans la vidéo, durée utilisée (None : jusqu'à la fin), vitesse
          "vis": {"start": 0.0, "len": None, "speed": 1.0}, "vdur": 0.0, "pclip": None, "vstream": None, "vimg": None}
    q = queue.Queue()
    tmpdir = Path(tempfile.mkdtemp(prefix="melofinds-promo-ui-"))

    # ---------- tâches en arrière-plan → retour dans Tk
    def bg(fn, done=None, fail=None, busy=None):
        if busy:
            if st["busy"]:
                ctx.toast("Attends la fin de l'opération en cours")
                return
            st["busy"] = busy
            set_busy(busy, None)

        def run():
            try:
                q.put(("ok", done, fn(), busy))
            except Exception as e:  # message clair, jamais de plantage de la fenêtre
                q.put(("err", fail, e, busy))
        threading.Thread(target=run, daemon=True).start()

    def progress(text="", pct=None):
        q.put(("prog", None, (text, pct), None))

    def pump():
        try:
            while True:
                kind, cb, val, busy = q.get_nowait()
                if kind == "prog":
                    if st["busy"]:
                        set_busy(val[0] or st["busy"], val[1])
                    continue
                if busy:
                    st["busy"] = None
                    set_busy(None, None)
                if kind == "ok" and cb:
                    cb(val)
                elif kind == "err":
                    (cb or (lambda e: ctx.toast(f"Promo : {e}"[:200])))(val)
                elif kind == "call" and cb:
                    cb(val)
        except queue.Empty:
            pass
        root.after(120, pump)
    pump()

    def save_cfg(**kw):
        def w():
            cfg = C.load_config()
            cfg.update(kw)
            C.save_config(cfg)
        threading.Thread(target=w, daemon=True).start()

    # ---------- mise en page : étapes à gauche (défilent), aperçu à droite (fixe)
    cols = tk.Frame(content, bg=BG)
    cols.pack(fill="both", expand=True)
    right = tk.Frame(cols, bg=BG, width=PREVIEW_W + 20)
    right.pack(side="right", fill="y", padx=(16, 0))
    left_wrap = tk.Frame(cols, bg=BG)
    left_wrap.pack(side="left", fill="both", expand=True)
    left = ctx.scroll_area(left_wrap)

    def step(n, title):
        c = card(left, padx=16, pady=12)
        c.pack(fill="x", pady=(0, 10), padx=(0, 6))
        head = tk.Frame(c, bg=PANEL)
        head.pack(fill="x")
        tk.Label(head, text=str(n), bg=PANEL3, fg=ACCENT, font=(MONO, 9, "bold"), width=2).pack(side="left")
        label(head, title, 12, bold=True).pack(side="left", padx=(8, 0))
        body = tk.Frame(c, bg=PANEL)
        body.pack(fill="x", pady=(8, 0))
        return body

    def clear(fr):
        for w in fr.winfo_children():
            w.destroy()

    def chip(parent, text, cmd, on=False, dim=False):
        b = tk.Label(parent, text=text, bg=ACCENT if on else PANEL3, fg="#1b1204" if on else (FAINT if dim else FG),
                     font=(FONT, 9, "bold"), padx=9, pady=3, cursor="hand2")
        b.bind("<Button-1>", lambda e: cmd())
        return b

    s_sound = step(1, "Ton son")
    s_lyr = step(2, "Les paroles")
    s_vis = step(3, "Le visuel")
    s_sty = step(4, "Le style")
    s_out = step(5, "La vidéo")
    s_desc = step(6, "La description")

    # ---------- aperçu (droite)
    prev = tk.Canvas(right, width=PREVIEW_W, height=PREVIEW_H, bg="#000000", highlightthickness=1, highlightbackground=LINE)
    prev.pack(pady=(0, 8))
    ctl = tk.Frame(right, bg=BG)
    ctl.pack(fill="x")
    play_btn = Btn(ctl, "▶  Aperçu", lambda: toggle_play(), kind="primary", padx=14, pady=6)
    play_btn.pack(side="left")
    time_lbl = label(ctl, "", 9, MUTED, mono=True)
    time_lbl.pack(side="right")
    busy_lbl = label(right, "", 9, ACCENT, wrap=PREVIEW_W)
    busy_lbl.pack(fill="x", pady=(10, 2))
    busy_bar = ctx.Bar(right)
    st["bar"] = busy_bar

    def set_busy(text, pct):
        if not text:
            busy_lbl.configure(text="")
            busy_bar.pack_forget()
            for b in st.get("busy_btns", []):
                b.set(enabled=True)
            return
        busy_lbl.configure(text=text if pct is None else f"{text} {int(pct)} %")
        if not busy_bar.winfo_ismapped():
            busy_bar.pack(fill="x")
        busy_bar.set(None if pct is None else pct)

    def bar_tick():
        if st["busy"] and busy_bar.winfo_ismapped():
            busy_bar.tick()
        root.after(40, bar_tick)
    bar_tick()

    def font_for(px):
        names = STYLE_FONTS.get(st["style"], STYLE_FONTS["impact"])
        fam = names[0] if st["fonts"] else names[1]
        return (fam, -max(8, int(px)))

    def draw_preview():
        prev.delete("all")
        if st["frame"]:
            prev.create_image(0, 0, image=st["frame"], anchor="nw")
        else:
            prev.create_text(PREVIEW_W / 2, PREVIEW_H / 2, text="Aperçu\n(choisis un visuel)", fill="#6f727b", font=(FONT, 11), justify="center")
        draw_sub()

    def draw_sub():
        prev.delete("sub")
        i = st["cur"]
        if not (0 <= i < len(st["lines"])):
            if st["lines"] and not st["playing"]:
                i = 0
            else:
                return
        sty = PM.STYLES.get(st["style"], PM.STYLES["impact"])
        text = st["lines"][i]["t"]
        text = text.upper() if sty["case"] == "upper" else text.lower() if sty["case"] == "lower" else text
        k = PREVIEW_W / PM.W
        px = sty["size"] * st["scale"] * k
        f = font_for(px)
        ow = max(1, round(sty["outline"] * k))
        if st["pos"] == "bas":
            x, y, anchor = PREVIEW_W / 2, PREVIEW_H - 430 * k, "s"
        elif st["pos"] == "haut":
            x, y, anchor = PREVIEW_W / 2, 360 * k, "n"
        else:
            x, y, anchor = PREVIEW_W / 2, PREVIEW_H / 2, "center"
        width = PREVIEW_W - 2 * 90 * k
        for dx in range(-ow, ow + 1):
            for dy in range(-ow, ow + 1):
                if dx or dy:
                    prev.create_text(x + dx, y + dy, text=text, fill="#000000", font=f, width=width, justify="center", anchor=anchor, tags="sub")
        prev.create_text(x, y, text=text, fill="#ffffff", font=f, width=width, justify="center", anchor=anchor, tags="sub")

    def load_frame():
        if not st["bg"]:
            st["frame"] = None
            draw_preview()
            return
        path = PM.visuals_dir() / st["bg"]["file"]
        at = float(st["vis"]["start"] or 0.0)
        dest = tmpdir / f"frame-{abs(hash(str(path)))}-{int(at * 10)}.png"

        def done(p):
            try:
                st["frame"] = tk.PhotoImage(file=str(p)) if p else None
            except Exception:
                st["frame"] = None
            draw_preview()
        bg(lambda: dest if dest.exists() else PM.frame_png(path, dest, at=at + 0.05), done)

    def toggle_play():
        if not st["audio"]:
            ctx.toast("Choisis d'abord ton son")
            return
        if st["playing"]:
            stop_play()
            return
        if not PLAYER.play_at(st["audio"], st["start"]):
            ctx.toast("Lecture impossible ici")
            return
        st["playing"] = True
        play_btn.configure(text="❚❚  Pause")
        start_video(0.0)
        tick_play()

    # ---------- l'aperçu bouge : la partie choisie du visuel défile derrière les paroles
    def vis_key():
        v = st["vis"]
        return (st["bg"]["file"], round(float(v["start"] or 0), 2), v["len"] and round(float(v["len"]), 2), float(v["speed"] or 1))

    def start_video(t):
        stop_video()
        if not st["bg"]:
            return
        key, path, vis, total = vis_key(), PM.visuals_dir() / st["bg"]["file"], dict(st["vis"]), st["vdur"] or None
        token = object()
        st["vstream"] = {"token": token, "proc": None, "data": None, "n": 0, "shown": 0}

        def run():
            vs = st["vstream"]
            try:
                if not (st["pclip"] and st["pclip"][0] == key and Path(st["pclip"][1]).exists()):
                    dest = tmpdir / f"apercu-{abs(hash(key))}.mp4"
                    clip, length = PM.clip_visual(path, dest, vis["start"], vis["len"], vis["speed"], PREVIEW_W, PREVIEW_H,
                                                  fps=15, crf=30, total=total)
                    st["pclip"] = (key, clip, length)
                _, clip, length = st["pclip"]
                if not vs or vs["token"] is not token:
                    return
                proc = PM.preview_stream(clip, (t % length) if length else 0.0, fps=15)
                if not proc:
                    return
                vs["proc"] = proc
                for png in PM.png_frames(proc.stdout):
                    if st["vstream"] is not vs:
                        break
                    vs["data"] = png
                    vs["n"] += 1
            except Exception as e:
                C.log(f"Promo : aperçu du visuel impossible ({e})")
            finally:
                p = vs.get("proc") if vs else None
                if p and p.poll() is None:
                    p.kill()
        threading.Thread(target=run, daemon=True).start()

    def stop_video():
        vs, st["vstream"] = st["vstream"], None
        if vs and vs.get("proc") and vs["proc"].poll() is None:
            try:
                vs["proc"].kill()
            except OSError:
                pass
        if st["vimg"] is not None:
            st["vimg"] = None
            draw_preview()

    def show_video_frame():
        vs = st["vstream"]
        if not vs or vs["n"] == vs["shown"] or not vs["data"]:
            return
        vs["shown"] = vs["n"]
        try:
            st["vimg"] = tk.PhotoImage(data=base64.b64encode(vs["data"]).decode("ascii"))
        except Exception:
            return
        prev.delete("vid")
        prev.create_image(0, 0, image=st["vimg"], anchor="nw", tags="vid")
        prev.tag_raise("sub")
    ctx.on_close.append(stop_video)

    def stop_play():
        st["playing"] = False
        play_btn.configure(text="▶  Aperçu")
        stop_video()
        if PLAYER.path and st["audio"] and PLAYER.is_(st["audio"]):
            PLAYER.stop()

    def tick_play():
        if not st["playing"]:
            return
        t = PLAYER.position() / 1000 - st["start"]
        if t >= st["dur"] or PLAYER.mode() not in ("playing", "seeking"):
            stop_play()
            st["cur"] = -1
            draw_sub()
            time_lbl.configure(text="")
            return
        show_video_frame()
        i = next((n for n, ln in enumerate(st["lines"]) if ln["s"] <= t < ln["e"]), -1)
        if i != st["cur"]:
            st["cur"] = i
            draw_sub()
        time_lbl.configure(text=f"{_mmss(t)[:-2]} / {_mmss(st['dur'])[:-2]}")
        root.after(50, tick_play)

    # ---------- 1. le son
    def set_audio(path, title, label_, voice):
        stop_play()
        st.update(audio=Path(path), title=title, label=label_, voice=voice, lines=[], words=[], result=None, cur=-1, dur_total=0.0,
                  vocals=None, vocals_auto=False)
        bg(lambda: PM.audio_duration(path) or 0.0, lambda d: (st.update(dur_total=d), render_sound()))

        def stem(found):  # ta piste voix exportée dans le projet : utilisée toute seule
            if found and st["audio"] == Path(path):
                st.update(vocals=found, vocals_auto=True)
                render_sound()
        bg(lambda: PM.find_vocal_stem(path), stem)
        render_all()

    def render_sound():
        clear(s_sound)
        if st["audio"]:
            top = tk.Frame(s_sound, bg=PANEL)
            top.pack(fill="x")
            label(top, st["title"], 11, bold=True).pack(side="left")
            if st["label"]:
                chip(top, st["label"], lambda: None, on=True).pack(side="left", padx=8)
            label(top, f"{_mmss(st['dur_total'])[:-2]} au total" if st["dur_total"] else "…", 9, MUTED).pack(side="left")
            Btn(top, "Changer de son", lambda: (stop_play(), st.update(audio=None, lines=[]), render_all()), kind="subtle", padx=0, pady=0).pack(side="right")
            if not st["voice"]:
                label(s_sound, "C'est l'instru (sans ta voix) : choisis plutôt une version pour que les paroles soient écrites.", 9, "#e8894a",
                      wrap=390).pack(anchor="w", pady=(6, 0))
            rng = tk.Frame(s_sound, bg=PANEL)
            rng.pack(fill="x", pady=(8, 0))
            start_lbl = label(rng, f"Début {_mmss(st['start'])[:-2]}", 9, FG, bold=True)
            start_lbl.pack(anchor="w")
            sc = tk.Scale(rng, from_=0, to=max(1, int(st["dur_total"] - 1)), orient="horizontal", resolution=0.5, showvalue=False,
                          bg=PANEL, troughcolor=PANEL3, highlightthickness=0, bd=0, sliderrelief="flat", activebackground=ACCENT)
            sc.set(st["start"])
            sc.pack(fill="x")

            def on_start(v):
                st["start"] = float(v)
                start_lbl.configure(text=f"Début {_mmss(st['start'])[:-2]}")
                if st["lines"]:
                    st["lines"], st["words"] = [], []
                    render_lyrics()
            sc.configure(command=on_start)
            durs = tk.Frame(s_sound, bg=PANEL)
            durs.pack(anchor="w", pady=(6, 0))
            for d in DURS:
                chip(durs, f"{d} s", lambda d=d: (st.update(dur=d, lines=[ln for ln in st["lines"] if ln["s"] < d]), render_all()),
                     on=st["dur"] == d).pack(side="left", padx=(0, 4))
            voc = tk.Frame(s_sound, bg=PANEL)
            voc.pack(fill="x", pady=(8, 0))
            if st["vocals"]:
                label(voc, ("Ta piste voix trouvée : " if st.get("vocals_auto") else "Voix seule : ") + Path(st["vocals"]).name[:40],
                      9, FG).pack(side="left")
                Btn(voc, "Retirer", lambda: (st.update(vocals=None, vocals_auto=False), render_sound()), kind="subtle", padx=8, pady=0).pack(side="left")
            else:
                label(voc, "Ta voix sera séparée du beat sur le PC pour caler les paroles.", 9, MUTED).pack(side="left")
                Btn(voc, "ou choisir ta piste voix…", pick_vocals, kind="subtle", padx=8, pady=0).pack(side="left")
            return
        label(s_sound, "Choisis la version de ton son (le .wav avec ta voix) : les paroles seront écrites à partir d'elle.", 9, MUTED,
              wrap=390).pack(anchor="w")
        bar = tk.Frame(s_sound, bg=PANEL)
        bar.pack(fill="x", pady=(8, 6))
        qv = tk.StringVar(value=st["q"])
        qe = ctx.entry(bar, qv, width=30)
        qe.pack(side="left", ipady=4)
        Btn(bar, "Autre fichier…", pick_audio, padx=10, pady=4).pack(side="left", padx=8)
        Btn(bar, "Actualiser", lambda: load_projects(True), kind="subtle", padx=4, pady=4).pack(side="right")
        lst = tk.Frame(s_sound, bg=PANEL)
        lst.pack(fill="x")

        def fill():
            clear(lst)
            if st["projects"] is None:
                label(lst, "Lecture de tes projets FL…", 9, MUTED).pack(anchor="w")
                return
            needle = st["q"].strip().lower()
            items = [p for p in st["projects"] if not needle or needle in p["title"].lower()]
            for p in items[: (600 if st["more"] else 30)]:
                row = tk.Frame(lst, bg=PANEL2, padx=10, pady=6)
                row.pack(fill="x", pady=2)
                top = tk.Frame(row, bg=PANEL2)
                top.pack(fill="x")
                tk.Frame(top, bg=p.get("color") or ACCENT, width=8, height=8).pack(side="left", padx=(0, 8))
                tk.Label(top, text=p["title"][:60], bg=PANEL2, fg=FG, font=(FONT, 10, "bold"), anchor="w").pack(side="left")
                meta = " · ".join(x for x in (p["key"], f"{p['bpm']} BPM" if p["bpm"] else "", "FL" if p["fl"] else "") if x)
                tk.Label(top, text=meta, bg=PANEL2, fg=FAINT, font=(MONO, 8)).pack(side="right")
                fr = tk.Frame(row, bg=PANEL2)
                fr.pack(fill="x", pady=(4, 0), padx=(16, 0))
                for f in p["files"][:10]:
                    txt = ("Instru" if f["kind"] == "instru" else f["label"][:28]) + ("  dernière" if f["latest"] else "")
                    chip(fr, txt, lambda p=p, f=f: set_audio(f["path"], p["title"], f["label"], f["voice"]), on=f["latest"],
                         dim=not f["voice"]).pack(side="left", padx=(0, 4), pady=1)
            if not items:
                label(lst, "Aucun projet trouvé." if needle else "Aucun son dans tes projets FL.", 9, MUTED).pack(anchor="w")
            elif len(items) > 30 and not st["more"]:
                Btn(lst, f"Voir les {len(items)} projets", lambda: (st.update(more=True), fill()), kind="subtle", padx=0, pady=4).pack(anchor="w")
        qv.trace_add("write", lambda *_: (st.update(q=qv.get()), fill()))
        fill()

    def load_projects(force=False):
        if st["projects"] is not None and not force:
            return
        st["projects"] = None
        render_sound()
        bg(lambda: PM.project_sounds(), lambda ps: (st.update(projects=ps), render_sound() if not st["audio"] else None))

    def pick_audio():
        p = ctx.filedialog.askopenfilename(parent=root, title="Choisis ton son", filetypes=[("Sons", "*.wav *.mp3 *.m4a *.flac *.ogg")])
        if p and Path(p).suffix.lower() in PM.AUDIO_EXT:
            set_audio(p, Path(p).stem, "", True)

    def pick_vocals():
        p = ctx.filedialog.askopenfilename(parent=root, title="Ta piste voix (seule)", filetypes=[("Sons", "*.wav *.mp3 *.m4a *.flac")])
        if p and Path(p).suffix.lower() in PM.AUDIO_EXT:
            st["vocals"] = Path(p)
            render_sound()

    # ---------- 2. les paroles
    def transcribe():
        if not st["audio"]:
            return
        stop_play()
        audio, vocals, start, dur = st["audio"], st["vocals"], st["start"], st["dur"]

        def done(r):
            st["words"] = list(r.get("words") or [])
            st["lines"] = norm_lines([dict(x) for x in r.get("lines") or []], st["dur"])
            st["result"], st["cur"] = None, -1
            if not st["lines"]:
                ctx.toast("Aucune parole entendue sur cet extrait : choisis un autre début, ou ajoute la voix seule")
            render_all()
        mode, quality, title = st["mode"], st["quality"], st["title"]
        bg(lambda: PM.transcribe(audio, start, dur, vocals, progress, mode=mode, quality=quality, title=title), done,
           busy="Écoute des paroles…")

    def set_quality(q):
        st["quality"] = q
        save_cfg(promo_quality=q)
        render_lyrics()

    def set_mode(mode):
        st["mode"] = mode
        save_cfg(promo_mode=mode)
        if not st["words"]:
            render_lyrics()
            return
        words, vocals, start, dur = st["words"], st["vocals"], st["start"], st["dur"]

        def cut():
            lines = PM.lines_from_words(words, mode)
            return PM.snap_to_voice(lines, vocals, start, dur) if vocals else lines
        bg(cut, lambda lines: (st.update(lines=norm_lines(lines, st["dur"]), result=None, cur=-1), render_all()))

    def render_lyrics():
        clear(s_lyr)
        if not st["audio"]:
            label(s_lyr, "Choisis d'abord ton son.", 9, MUTED).pack(anchor="w")
            return
        top = tk.Frame(s_lyr, bg=PANEL)
        top.pack(fill="x")
        b = Btn(top, "Réécouter les paroles" if st["lines"] else "Écrire les paroles automatiquement", transcribe, kind="primary", padx=14, pady=6)
        b.pack(side="left")
        st["busy_btns"] = [b]
        label(s_lyr, "Whisper, sur ton PC : chaque phrase arrive au moment où tu la dis. Corrige un mot ou recale une ligne si besoin : "
                     "les mots que tu corriges sont retenus pour la prochaine fois.",
              9, MUTED, wrap=390).pack(anchor="w", pady=(6, 0))
        md = tk.Frame(s_lyr, bg=PANEL)
        md.pack(anchor="w", pady=(6, 0))
        label(md, "Découpage", 9, MUTED).pack(side="left", padx=(0, 8))
        for k, m in PM.MODES.items():
            chip(md, m["label"], lambda k=k: set_mode(k), on=st["mode"] == k).pack(side="left", padx=(0, 4))
        qd = tk.Frame(s_lyr, bg=PANEL)
        qd.pack(anchor="w", pady=(4, 0))
        label(qd, "Écoute", 9, MUTED).pack(side="left", padx=(0, 8))
        for k, m in PM.MODELS.items():
            chip(qd, m["label"], lambda k=k: set_quality(k), on=st["quality"] == k).pack(side="left", padx=(0, 4))
        label(qd, "gros modèle : comprend le rap rapide, plus lent" if st["quality"] == "precise" else "modèle léger : rapide, se trompe plus",
              9, MUTED).pack(side="left", padx=(6, 0))
        lex = PM.lexicon()
        if lex:
            lx = tk.Frame(s_lyr, bg=PANEL)
            lx.pack(fill="x", pady=(4, 0))
            label(lx, f"Tes mots ({len(lex)})", 9, MUTED).pack(side="left", padx=(0, 8))
            for w in lex[-12:][::-1]:
                chip(lx, f"{w}  ×", lambda w=w: (PM.forget_word(w), render_lyrics())).pack(side="left", padx=(0, 3))
        rows = tk.Frame(s_lyr, bg=PANEL)
        rows.pack(fill="x", pady=(8, 0))
        for i, ln in enumerate(st["lines"]):
            r = tk.Frame(rows, bg=PANEL)
            r.pack(fill="x", pady=1)
            tv = tk.StringVar(value=_mmss(ln["s"]))
            te = tk.Entry(r, textvariable=tv, width=7, bg=PANEL2, fg=FG, insertbackground=FG, relief="flat", font=(MONO, 9),
                          justify="center", highlightthickness=1, highlightbackground=LINE)
            te.pack(side="left", ipady=3)

            def set_t(e=None, ln=ln, tv=tv):
                v = parse_time(tv.get())
                if v is not None and 0 <= v < st["dur"]:
                    ln["s"] = v
                    norm_lines(st["lines"], st["dur"])
                    render_lyrics()
                else:
                    tv.set(_mmss(ln["s"]))
            te.bind("<Return>", set_t)
            te.bind("<FocusOut>", set_t)
            for sym, dv in (("−", -0.1), ("+", 0.1)):
                chip(r, sym, lambda ln=ln, dv=dv: (ln.update(s=min(st["dur"] - 0.1, max(0.0, ln["s"] + dv))),
                                                     norm_lines(st["lines"], st["dur"]), render_lyrics())).pack(side="left", padx=(3, 0))
            xv = tk.StringVar(value=ln["t"])
            xe = tk.Entry(r, textvariable=xv, bg=PANEL2, fg=FG, insertbackground=FG, relief="flat", font=(FONT, 10),
                          highlightthickness=1, highlightbackground=LINE)
            xe.pack(side="left", fill="x", expand=True, padx=6, ipady=3)
            xv.trace_add("write", lambda *_, ln=ln, xv=xv: (ln.update(t=xv.get()), st.update(result=None), draw_sub()))
            xe.bind("<FocusIn>", lambda e, i=i: (st.update(cur=i), draw_sub()))
            chip(r, "▶", lambda ln=ln: (stop_play(), st.update(start_tmp=None), play_from(ln["s"]))).pack(side="left")
            chip(r, "×", lambda i=i: (st["lines"].pop(i), norm_lines(st["lines"], st["dur"]), render_lyrics(), draw_sub())).pack(side="left", padx=(3, 0))
        Btn(s_lyr, "+ Ajouter une ligne", add_line, kind="subtle", padx=0, pady=4).pack(anchor="w", pady=(6, 0))
        render_out()

    def play_from(t):
        if not st["audio"]:
            return
        if PLAYER.play_at(st["audio"], st["start"] + t):
            st["playing"] = True
            play_btn.configure(text="❚❚  Pause")
            start_video(t)
            tick_play()

    def add_line():
        last = st["lines"][-1] if st["lines"] else None
        st["lines"].append({"t": "", "s": min(st["dur"] - 0.5, last["s"] + 1.5) if last else 0.0, "e": st["dur"]})
        norm_lines(st["lines"], st["dur"])
        render_lyrics()

    # ---------- 3. le visuel
    def thumb(v):
        key = v["file"]
        if key in st["thumbs"]:
            return st["thumbs"][key]
        st["thumbs"][key] = None
        src = PM.visuals_dir() / v["file"]
        dest = tmpdir / f"thumb-{abs(hash(key))}.png"

        def done(p):
            try:
                st["thumbs"][key] = tk.PhotoImage(file=str(p)) if p else None
            except Exception:
                st["thumbs"][key] = None
            render_visuals()
        bg(lambda: PM.frame_png(src, dest, 72, 128), done)
        return None

    def choose_visual(v):
        if st["playing"]:
            stop_play()
        st.update(bg=v, result=None, vis={"start": 0.0, "len": None, "speed": 1.0}, vdur=0.0, pclip=None)
        load_frame()
        render_visuals()
        render_out()
        render_desc()
        path = PM.visuals_dir() / v["file"]
        bg(lambda: PM.media_duration(path) or 0.0,
           lambda d: (st.update(vdur=d), render_visuals()) if st["bg"] is v else None)

    def vis_changed(refresh_frame=False):
        st["result"], st["pclip"] = None, None
        if st["playing"]:  # pendant que tu bouges le curseur : l'aperçu repart une fois arrêté
            if st.get("video_job"):
                root.after_cancel(st["video_job"])
            st["video_job"] = root.after(450, lambda: st["playing"] and start_video(max(0.0, PLAYER.position() / 1000 - st["start"])))
        if refresh_frame:
            if st.get("frame_job"):
                root.after_cancel(st["frame_job"])
            st["frame_job"] = root.after(250, load_frame)

    def render_cut():
        """Moment, durée et vitesse du visuel derrière les paroles."""
        box = tk.Frame(s_vis, bg=PANEL2, padx=10, pady=8)
        box.pack(fill="x", pady=(8, 0))
        vd, v = st["vdur"], st["vis"]
        label(box, "Partie du visuel", 10, FG, bold=True).pack(anchor="w")
        if not vd:
            label(box, "Lecture de la vidéo…", 9, MUTED).pack(anchor="w")
            return
        start_lbl = label(box, "", 9, FG, wrap=370)
        start_lbl.pack(anchor="w", pady=(4, 0))
        sc = tk.Scale(box, from_=0, to=max(0.1, vd - 0.3), orient="horizontal", resolution=0.1, showvalue=False,
                      bg=PANEL2, troughcolor=PANEL3, highlightthickness=0, bd=0, sliderrelief="flat", activebackground=ACCENT)
        sc.set(v["start"])
        sc.pack(fill="x")
        len_lbl = label(box, "", 9, FG, wrap=370)
        len_lbl.pack(anchor="w", pady=(6, 0))
        sl = tk.Scale(box, from_=0.5, to=max(0.6, vd), orient="horizontal", resolution=0.1, showvalue=False,
                      bg=PANEL2, troughcolor=PANEL3, highlightthickness=0, bd=0, sliderrelief="flat", activebackground=ACCENT)
        sl.set(v["len"] or vd)
        sl.pack(fill="x")

        def texts():
            left_ = max(0.3, vd - v["start"])
            used = min(v["len"] or left_, left_)
            start_lbl.configure(text=f"Commence à {_mmss(v['start'])[:-2]} de la vidéo (sur {_mmss(vd)[:-2]})")
            loop = used / (v["speed"] or 1)
            len_lbl.configure(text=f"Durée utilisée : {used:.1f} s" + ("" if v["len"] else " (jusqu'à la fin)")
                                   + (f" · tourne en boucle toutes les {loop:.1f} s" if loop < st["dur"] else ""))

        def on_start(x):
            x = float(x)
            if abs(x - v["start"]) < 0.05:
                return
            v["start"] = x
            texts()
            vis_changed(refresh_frame=True)

        def on_len(x):
            x = float(x)
            new = None if x >= vd - 0.05 else x
            if new == v["len"]:
                return
            v["len"] = new
            texts()
            vis_changed()
        sc.configure(command=on_start)
        sl.configure(command=on_len)
        texts()
        sp = tk.Frame(box, bg=PANEL2)
        sp.pack(anchor="w", pady=(6, 0))
        label(sp, "Vitesse", 9, MUTED).pack(side="left", padx=(0, 8))
        for k in PM.SPEEDS:
            chip(sp, f"x{k:g}", lambda k=k: (v.update(speed=k), vis_changed(), render_visuals()), on=float(v["speed"]) == k).pack(side="left", padx=(0, 3))
        label(box, "Lance l'aperçu pour voir la vidéo défiler derrière tes paroles.", 8, FAINT).pack(anchor="w", pady=(6, 0))

    def render_visuals():
        clear(s_vis)
        if st["ig_url"]:
            ig = tk.Frame(s_vis, bg=PANEL2, padx=10, pady=8)
            ig.pack(fill="x", pady=(0, 8))
            label(ig, "Vidéo ouverte dans Instagram", 10, FG, bold=True).pack(side="left")
            Btn(ig, "Utiliser cette vidéo", lambda: use_ig(st["ig_url"]), kind="primary", padx=12, pady=4).pack(side="right")
        grid = tk.Frame(s_vis, bg=PANEL)
        grid.pack(fill="x")
        vs = st["visuals"]
        if vs is None:
            label(grid, "Chargement…", 9, MUTED).pack(anchor="w")
        elif not vs:
            label(grid, "Tes visuels s'afficheront ici.", 9, MUTED).pack(anchor="w")
        for n, v in enumerate((vs or [])[:24]):
            on = st["bg"] and st["bg"]["file"] == v["file"]
            cell = tk.Frame(grid, bg=ACCENT if on else PANEL, padx=2, pady=2, cursor="hand2")
            cell.grid(row=n // 6, column=n % 6, padx=3, pady=3)
            img = thumb(v)
            pic = tk.Label(cell, image=img, bg="#000000", width=72, height=128) if img else tk.Label(cell, text="…", bg="#000000", fg=FAINT, width=9, height=8)
            pic.pack()
            tk.Label(cell, text=(f"@{v['user']}" if v.get("user") else "Ma vidéo")[:12], bg=ACCENT if on else PANEL,
                     fg="#1b1204" if on else MUTED, font=(FONT, 7, "bold")).pack(fill="x")
            for w in (cell, pic):
                w.bind("<Button-1>", lambda e, v=v: choose_visual(v))
                w.bind("<Button-3>", lambda e, v=v: remove_visual(v))
        if st["bg"]:
            render_cut()
        row = tk.Frame(s_vis, bg=PANEL)
        row.pack(fill="x", pady=(8, 0))
        Btn(row, "Ma vidéo…", pick_video, padx=10, pady=4).pack(side="left")
        lv = tk.StringVar()
        le = ctx.entry(row, lv, width=34)
        le.pack(side="left", padx=8, ipady=4)
        le.insert(0, "")
        Btn(row, "Utiliser le lien", lambda: use_ig(lv.get().strip()), padx=10, pady=4).pack(side="left")
        label(s_vis, "Colle le lien d'une vidéo Instagram (reel ou post), ou ouvre un compte et choisis une vidéo. Clic droit sur un "
                     "visuel pour le retirer. Le nom du compte va dans la description.", 8, FAINT, wrap=390).pack(anchor="w", pady=(6, 4))
        acc = tk.Frame(s_vis, bg=PANEL)
        acc.pack(fill="x")
        for n, u in enumerate(st["accounts"]):
            a = tk.Frame(acc, bg=PANEL2, padx=8, pady=6)
            a.grid(row=n // 3, column=n % 3, padx=3, pady=3, sticky="we")
            tk.Label(a, text=f"@{u}", bg=PANEL2, fg=FG, font=(FONT, 9, "bold")).pack(side="left")
            chip(a, "Voir", lambda u=u: open_ig(u)).pack(side="left", padx=6)
            chip(a, "×", lambda u=u: (st["accounts"].remove(u), save_cfg(promo_accounts=st["accounts"]), render_visuals())).pack(side="left")
        add = tk.Frame(s_vis, bg=PANEL)
        add.pack(fill="x", pady=(6, 0))
        av = tk.StringVar()
        ctx.entry(add, av, width=24).pack(side="left", ipady=3)

        def add_acc():
            u = re.sub(r"^https?://(www\.)?instagram\.com/", "", av.get().strip()).strip("/@ ").split("/")[0]
            if PM.USER_RE.match(u) and u not in st["accounts"]:
                st["accounts"].append(u)
                save_cfg(promo_accounts=st["accounts"])
                render_visuals()
        Btn(add, "Ajouter un compte", add_acc, kind="subtle", padx=8, pady=3).pack(side="left")

    ig = PM.IGBrowser(lambda u: q.put(("call", lambda u_: (st.update(ig_url=u_), render_visuals()), u, None)))
    ctx.on_close.append(ig.close)

    def open_ig(user):
        bg(lambda: ig.open(user), lambda _: ctx.toast("Instagram ouvert : choisis une vidéo, puis « Utiliser cette vidéo »"))

    def use_ig(url):
        if not PM.ig_shortcode(url):
            ctx.toast("Colle le lien d'une vidéo Instagram (…/reel/… ou …/p/…)")
            return

        def done(v):
            st.update(bg=v, ig_url=None, result=None)
            load_visuals()
            load_frame()
            render_desc()
            ctx.toast(f"Visuel de @{v['user']} prêt" if v.get("user") else "Visuel prêt")
        bg(lambda: PM.ig_download(url, progress, ig.cookies()), done, busy="Téléchargement du visuel…")

    def pick_video():
        p = ctx.filedialog.askopenfilename(parent=root, title="Choisis ta vidéo", filetypes=[("Vidéos", "*.mp4 *.mov *.webm *.mkv *.m4v")])
        if p:
            bg(lambda: PM.add_own_video(p), lambda v: (st.update(bg=v, result=None), load_visuals(), load_frame(), render_desc()),
               busy="Ajout de ta vidéo…")

    def remove_visual(v):
        if ctx.messagebox.askyesno("Promo", "Retirer ce visuel ?", parent=root):
            PM.remove_visual(v["file"])
            if st["bg"] and st["bg"]["file"] == v["file"]:
                st["bg"], st["frame"] = None, None
                draw_preview()
            load_visuals()

    def load_visuals():
        bg(lambda: PM.visuals(), lambda vs: (st.update(visuals=vs), render_visuals()))

    # ---------- 4. le style
    def render_style():
        clear(s_sty)
        r1 = tk.Frame(s_sty, bg=PANEL)
        r1.pack(anchor="w")
        for k, v in PM.STYLES.items():
            chip(r1, v["label"], lambda k=k: (st.update(style=k, result=None), save_cfg(promo_style=k), render_style(), draw_sub()),
                 on=st["style"] == k).pack(side="left", padx=(0, 4))
        tk.Frame(r1, bg=PANEL, width=16).pack(side="left")
        for k, lab in (("haut", "Haut"), ("centre", "Milieu"), ("bas", "Bas")):
            chip(r1, lab, lambda k=k: (st.update(pos=k, result=None), save_cfg(promo_pos=k), render_style(), draw_sub()),
                 on=st["pos"] == k).pack(side="left", padx=(0, 4))
        r2 = tk.Frame(s_sty, bg=PANEL)
        r2.pack(fill="x", pady=(8, 0))
        label(r2, "Taille", 9, MUTED).pack(side="left")
        sc = tk.Scale(r2, from_=0.7, to=1.4, resolution=0.05, orient="horizontal", showvalue=False, bg=PANEL, troughcolor=PANEL3,
                      highlightthickness=0, bd=0, sliderrelief="flat", activebackground=ACCENT)
        sc.set(st["scale"])
        sc.pack(side="left", fill="x", expand=True, padx=8)
        sc.configure(command=lambda v: (st.update(scale=float(v), result=None), draw_sub()))
        sc.bind("<ButtonRelease-1>", lambda e: save_cfg(promo_scale=st["scale"]))

    # ---------- 5. la vidéo
    def make_video():
        lines = [{"t": ln["t"].strip(), "s": ln["s"], "e": ln["e"]} for ln in st["lines"] if ln["t"].strip()]
        if not (st["audio"] and st["bg"] and lines):
            ctx.toast("Son, paroles et visuel d'abord")
            return
        stop_play()
        audio, bgv = st["audio"], PM.visuals_dir() / st["bg"]["file"]
        args = (st["start"], st["dur"], lines, PM.out_name(st["title"] or audio.stem), st["style"], st["pos"], st["scale"])
        vis = dict(st["vis"])

        heard = list(st["words"])

        def done(out):
            st["result"] = out
            if heard:  # mots corrigés à la main : Whisper les connaîtra la prochaine fois
                try:
                    PM.learn_words(heard, lines)
                except OSError:
                    pass
            render_out()
            ctx.toast("Vidéo prête : dans le dossier Promo de tes projets")
        bg(lambda: PM.render(bgv, audio, args[0], args[1], args[2], args[3], args[4], args[5], args[6], progress, visual=vis), done,
           busy="Création de la vidéo…")

    def render_out():
        clear(s_out)
        ok = bool(st["audio"] and st["bg"] and any(ln["t"].strip() for ln in st["lines"]))
        row = tk.Frame(s_out, bg=PANEL)
        row.pack(fill="x")
        b = Btn(row, "Créer la vidéo (1080x1920)", make_video, kind="primary", padx=14, pady=6)
        b.pack(side="left")
        b.set(enabled=ok)
        label(row, f"{st['dur']} s · {len(st['lines'])} lignes" if ok else "Son, paroles et visuel d'abord.", 9, MUTED).pack(side="left", padx=10)
        if st["result"]:
            res = tk.Frame(s_out, bg=PANEL2, padx=10, pady=8)
            res.pack(fill="x", pady=(8, 0))
            label(res, Path(st["result"]).name, 10, FG, bold=True).pack(anchor="w")
            br = tk.Frame(res, bg=PANEL2)
            br.pack(anchor="w", pady=(6, 0))
            Btn(br, "▶ Voir la vidéo", lambda: ctx.open_path(st["result"]), kind="primary", padx=12, pady=4).pack(side="left")
            Btn(br, "Montrer dans le dossier", lambda: PM._reveal(st["result"]), padx=12, pady=4).pack(side="left", padx=8)

    # ---------- 6. la description
    def render_desc():
        clear(s_desc)
        r = tk.Frame(s_desc, bg=PANEL)
        r.pack(fill="x")
        label(r, "Tes #", 9, MUTED).pack(side="left")
        tv = tk.StringVar(value=st["tags"])
        ctx.entry(r, tv, width=40).pack(side="left", padx=8, ipady=3, fill="x", expand=True)
        keep = tk.BooleanVar(value=bool(st["keep"]))
        tk.Checkbutton(s_desc, text="Toujours mettre ces #", variable=keep, bg=PANEL, fg=FG, selectcolor=PANEL3, activebackground=PANEL,
                       activeforeground=FG, font=(FONT, 9), command=lambda: (st.update(keep=keep.get()),
                                                                              save_cfg(promo_keep_tags=keep.get(), **({"promo_tags": st["tags"]} if keep.get() else {})))
                       ).pack(anchor="w", pady=(4, 0))
        txt = tk.Text(s_desc, height=5, bg=PANEL2, fg=FG, insertbackground=FG, relief="flat", font=(FONT, 10), wrap="word",
                      highlightthickness=1, highlightbackground=LINE, padx=8, pady=6)
        txt.pack(fill="x", pady=(6, 0))

        def refill(*_):
            txt.delete("1.0", "end")
            txt.insert("1.0", description(st["title"], st["tags"], (st["bg"] or {}).get("user", "")))
        refill()

        def on_tags(*_):
            st["tags"] = tv.get()
            if st["keep"]:
                save_cfg(promo_tags=st["tags"])
            refill()
        tv.trace_add("write", on_tags)

        def copy():
            root.clipboard_clear()
            root.clipboard_append(txt.get("1.0", "end").strip())
            ctx.toast("Description copiée")
        Btn(s_desc, "Copier la description", copy, kind="primary", padx=14, pady=6).pack(anchor="w", pady=(8, 0))

    def render_all():
        render_sound()
        render_lyrics()
        render_style()
        render_out()
        render_desc()
        draw_preview()

    def on_show():
        load_projects()
        if st["visuals"] is None:
            load_visuals()
        if not st["fonts"]:
            def fonts():
                PM.ensure_fonts()
                register_fonts()
                return True
            bg(fonts, lambda ok: (st.update(fonts=bool(ok)), draw_sub()))
    ctx.on_show["promo"] = on_show
    render_all()
    render_visuals()
    # (tests / captures : actions de la page)
    st["api"] = {"set_audio": set_audio, "render_all": render_all, "load_frame": load_frame, "draw_preview": draw_preview,
                 "render_visuals": render_visuals, "norm": lambda: norm_lines(st["lines"], st["dur"]),
                 "choose_visual": choose_visual, "start_video": start_video, "stop_video": stop_video, "show_frame": show_video_frame}
    ctx.root._promo = st
    return st
