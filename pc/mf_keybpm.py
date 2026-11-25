"""Clé et BPM d'une prod, calculés sur le PC, sans site web ni vérification humaine.

Tunebat (mode standard) analyse le son dans le navigateur avec la technologie de recherche
de l'UPF (Essentia). Quand tunebat.com bloque Melofinds avec sa vérification « je ne suis
pas un robot », le PC fait la même chose lui-même : Essentia (essentia.js, UPF / MTG,
licence AGPL-3.0, inclus dans le dossier des outils) tourne dans un Edge invisible, sur une
page servie par Melofinds en local (127.0.0.1, rien n'est envoyé nulle part).

Clé : KeyExtractor (profil « bgate », pensé pour la musique actuelle avec basses et
batteries). BPM : RhythmExtractor2013 (multifeature).
"""

import json
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import mf_core as C
import mf_tunebat as T

FILES = {"essentia-wasm.web.js": "application/javascript", "essentia-wasm.web.wasm": "application/wasm",
         "essentia.js-core.js": "application/javascript"}
SR = 44100
MAX_SECONDS = 120

PAGE = """<!doctype html><meta charset="utf-8"><title>Melofinds · analyse</title>
<script src="essentia-wasm.web.js"></script><script src="essentia.js-core.js"></script>
<script>
(async () => {
  const send = (o) => fetch('result', { method: 'POST', body: JSON.stringify(o) });
  try {
    const mod = await EssentiaWASM({ locateFile: (p) => p });
    const ess = new Essentia(mod);
    const x = new Float32Array(await (await fetch('pcm')).arrayBuffer());
    const sig = ess.arrayToVector(x);
    const k = ess.KeyExtractor(sig, true, 4096, 4096, 12, 3500, 60, 25, 0.2, 'bgate', %(sr)d);
    const r = ess.RhythmExtractor2013(sig, 208, 'multifeature', 50);
    await send({ key: k.key, scale: k.scale, strength: k.strength, bpm: r.bpm, confidence: r.confidence });
  } catch (e) { await send({ err: String(e && e.message || e).slice(0, 200) }); }
})();
</script>""" % {"sr": SR}


class KeyBpmError(Exception):
    pass


def essentia_dir():
    return C.P.tools


def available(folder=None):
    d = Path(folder or essentia_dir())
    return all((d / n).exists() for n in FILES)


def decode(wav, ffmpeg=None, seconds=MAX_SECONDS):
    """Le son en échantillons float32 mono 44,1 kHz (au plus `seconds`, en sautant l'intro)."""
    ffmpeg = ffmpeg or C.tool_path("ffmpeg.exe")
    if not ffmpeg:
        raise KeyBpmError("ffmpeg manquant")
    r = subprocess.run([ffmpeg, "-v", "error", "-ss", "5", "-t", str(seconds), "-i", str(wav), "-ac", "1", "-ar", str(SR),
                        "-f", "f32le", "-"], capture_output=True, timeout=120, creationflags=C.NO_WINDOW,
                       stdin=subprocess.DEVNULL)
    pcm = r.stdout
    if r.returncode != 0 or len(pcm) < SR * 4 * 8:  # moins de 8 s (prod très courte) : depuis le début
        r = subprocess.run([ffmpeg, "-v", "error", "-t", str(seconds), "-i", str(wav), "-ac", "1", "-ar", str(SR),
                            "-f", "f32le", "-"], capture_output=True, timeout=120, creationflags=C.NO_WINDOW,
                           stdin=subprocess.DEVNULL)
        pcm = r.stdout
    if r.returncode != 0 or len(pcm) < SR * 4 * 3:
        raise KeyBpmError("son illisible")
    return pcm


def to_result(o):
    """Réponse d'Essentia → {key: « F# min », bpm: 140, camelot: ""} (même forme que Tunebat)."""
    if not isinstance(o, dict) or o.get("err"):
        raise KeyBpmError(f"analyse impossible : {o.get('err') if isinstance(o, dict) else '?'}")
    key = C.tb_key(f"{o.get('key', '')} {o.get('scale', '')}")
    try:
        bpm = float(o.get("bpm"))
    except (TypeError, ValueError):
        bpm = 0
    # tempo moitié / double (trap à 140 lue « 70 ») : ramené entre 85 et 172, comme les logiciels de DJ
    while bpm and bpm < 85:
        bpm *= 2
    while bpm > 172:
        bpm /= 2
    bpm = C.valid_bpm(round(bpm))
    if not key or not bpm:
        raise KeyBpmError("analyse sans résultat")
    return {"key": key, "bpm": bpm, "camelot": ""}


def analyze(wav, progress=None, timeout=150, browser=None, extra_args=None, folder=None, ffmpeg=None):
    """Clé et BPM d'un .wav, sur le PC. Lève KeyBpmError."""
    step = progress or (lambda *_: None)
    folder = Path(folder or essentia_dir())
    if not available(folder):
        raise KeyBpmError("moteur d'analyse absent (réinstalle Melofinds PC)")
    browser = browser or T.find_browser()
    if not browser:
        raise KeyBpmError("Edge ou Chrome introuvable sur ce PC")
    step("local")
    pcm = decode(wav, ffmpeg)
    token = secrets.token_hex(12)
    done = threading.Event()
    box = {}

    class H(BaseHTTPRequestHandler):
        def _ok(self, body, ctype):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parts = self.path.split("?")[0].strip("/").split("/")
            if len(parts) < 1 or parts[0] != token:
                self.send_error(404)
                return
            name = parts[1] if len(parts) > 1 else ""
            if name in ("", "index.html"):
                self._ok(PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif name == "pcm":
                self._ok(pcm, "application/octet-stream")
            elif name in FILES:
                self._ok((folder / name).read_bytes(), FILES[name])
            else:
                self.send_error(404)

        def do_POST(self):
            if self.path.strip("/") != f"{token}/result":
                self.send_error(404)
                return
            n = min(int(self.headers.get("Content-Length") or 0), 10_000)
            try:
                box["r"] = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                box["r"] = {"err": "réponse illisible"}
            self._ok(b"ok", "text/plain")
            done.set()

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    prof = Path(tempfile.mkdtemp(prefix="melofinds-analyse-"))
    proc = None
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/{token}/"
        proc = subprocess.Popen([browser, "--headless=new", f"--user-data-dir={prof}", "--no-first-run",
                                 "--no-default-browser-check", "--disable-extensions", *(extra_args or []), url],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=C.NO_WINDOW)
        if not done.wait(timeout):
            raise KeyBpmError("l'analyse a pris trop de temps")
        return to_result(box.get("r"))
    finally:
        if proc:
            proc.kill()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        srv.shutdown()
        srv.server_close()
        time.sleep(0.3)
        shutil.rmtree(prof, ignore_errors=True)
