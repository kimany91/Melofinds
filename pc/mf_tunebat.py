"""Tunebat Analyzer sur le PC, comme dans l'appli Android.

La prod (.wav) est donnée à la page tunebat.com/Analyzer, ouverte dans une petite fenêtre
Edge (toujours présent sur Windows) ou Chrome, comme si tu l'avais choisie avec « Select
Files ». Tunebat l'analyse dans le navigateur (le fichier n'est envoyé à aucun serveur) ;
la clé et le BPM sont lus dans son tableau, puis la fenêtre se ferme et la copie est effacée.

La fenêtre est visible : si Tunebat demande une vérification (« Je ne suis pas un robot »),
c'est toi qui la fais. Rien n'est contourné. Le navigateur a son propre profil, à part
(dans le dossier du programme) : tes onglets, comptes et historique ne sont pas touchés.
Pilotage par le protocole DevTools d'Edge / Chrome, en local seulement (127.0.0.1).
"""

import base64
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

import mf_core as C

ANALYZER = "https://tunebat.com/Analyzer"
TIMEOUT = 240  # le temps de faire une éventuelle vérification Tunebat


class TunebatError(Exception):
    pass


def find_browser():
    """Edge (toujours là sur Windows 10 / 11), sinon Chrome. MELOFINDS_BROWSER pour forcer."""
    env = os.environ.get("MELOFINDS_BROWSER")
    if env:
        return env if Path(env).exists() else None
    if C.WINDOWS:
        bases = [os.environ.get(k) for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
        for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
            for b in bases:
                if b and (Path(b) / rel).exists():
                    return str(Path(b) / rel)
        return None
    for n in ("microsoft-edge", "google-chrome", "chromium", "chromium-browser"):
        p = shutil.which(n)
        if p:
            return p
    return None


# ---------------------------------------------------------------------------
# WebSocket minimal (bibliothèque standard) : juste ce qu'il faut pour DevTools

class WS:
    def __init__(self, url, timeout=10):
        u = urllib.parse.urlparse(url)
        if u.scheme != "ws" or u.hostname not in ("127.0.0.1", "localhost"):
            raise TunebatError("adresse DevTools inattendue")  # jamais ailleurs que sur ce PC
        self.sock = socket.create_connection((u.hostname, u.port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise TunebatError("DevTools a refusé la connexion")
            head += chunk
        head, self.buf = head.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise TunebatError("DevTools a refusé la connexion")

    def send(self, text):
        data = text.encode("utf-8")
        n = len(data)
        head = bytes([0x81])
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)
        m = int.from_bytes((mask * (n // 4 + 1))[:n], "big") if n else 0
        body = (int.from_bytes(data, "big") ^ m).to_bytes(n, "big") if n else b""
        self.sock.sendall(head + mask + body)

    def _take(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("DevTools fermé")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self):
        parts = []
        while True:
            b0, b1 = self._take(2)
            op, n = b0 & 0x0F, b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._take(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._take(8))[0]
            mask = self._take(4) if b1 & 0x80 else None
            data = self._take(n)
            if mask:
                data = bytes(c ^ mask[i % 4] for i, c in enumerate(data))
            if op == 8:
                raise ConnectionError("DevTools fermé")
            if op == 9:  # ping → pong
                self.sock.sendall(bytes([0x8A, 0x80 | len(data)]) + b"\0\0\0\0" + data)
                continue
            if op in (0, 1, 2):
                parts.append(data)
                if b0 & 0x80:
                    return b"".join(parts).decode("utf-8", "replace")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class CDP:
    def __init__(self, ws_url):
        self.ws = WS(ws_url)
        self.n = 0

    def call(self, method, params=None, timeout=15):
        self.n += 1
        i = self.n
        self.ws.send(json.dumps({"id": i, "method": method, "params": params or {}}))
        end = time.time() + timeout
        while time.time() < end:
            self.ws.sock.settimeout(max(0.2, end - time.time()))
            try:
                msg = json.loads(self.ws.recv())
            except socket.timeout:
                break
            if msg.get("id") == i:
                if "error" in msg:
                    raise TunebatError(str(msg["error"].get("message") or "erreur DevTools")[:120])
                return msg.get("result") or {}
        raise TunebatError("le navigateur ne répond pas")

    def eval(self, expr, timeout=15):
        r = self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True}, timeout)
        return (r.get("result") or {}).get("value")

    def close(self):
        self.ws.close()


# ---------------------------------------------------------------------------
# Lecture du résultat (mêmes règles que l'appli : TunebatActivity / tbParse)

READ_JS = """(()=>{const n=%s;const o={};
for(const t of document.querySelectorAll('table')){const hs=[...t.querySelectorAll('th')].map(x=>x.innerText.trim().toLowerCase());
for(const tr of t.querySelectorAll('tr')){const c=[...tr.querySelectorAll('td')].map(x=>x.innerText.trim());if(!c.length)continue;
const row=c.join(' | ');if(!row.toLowerCase().includes(n))continue;o.row=row;
hs.forEach((h,k)=>{if(/key|clé|tonalit/.test(h))o.key=c[k];if(/bpm|tempo/.test(h))o.bpm=c[k];if(/camelot/.test(h))o.camelot=c[k];});}}
if(!o.row){const x=document.body?document.body.innerText:'';const k=x.toLowerCase().indexOf(n);if(k>=0)o.row=x.slice(k,k+240);}
return JSON.stringify(o);})()"""

_KEY_IN_ROW = re.compile(r"\b[A-G][#♯b♭]?\s*(?:major|minor|maj|min)\b", re.I)


def _num(v):
    m = re.search(r"\d{2,3}(?:[.,]\d+)?", str(v or ""))
    if not m:
        return None
    n = round(float(m.group(0).replace(",", ".")))
    return n if 50 <= n <= 220 else None


def parse_result(o, name):
    """{key, bpm, camelot} si Tunebat a donné la clé ET le BPM, sinon None."""
    if not isinstance(o, dict):
        return None
    row = str(o.get("row") or "")
    m = _KEY_IN_ROW.search(row)
    key = C.tb_key(o.get("key")) or (C.tb_key(m.group(0)) if m else None)
    bpm = _num(o.get("bpm"))
    if not bpm:
        rest = row.replace(name, " ").replace(Path(name).stem, " ")
        rest = re.sub(r"\b\d{1,2}:\d{2}\b", " ", rest)
        bpm = next((b for b in (_num(x) for x in re.findall(r"\b\d{2,3}(?:\.\d+)?\b", rest)) if b), None)
    if not key or not bpm:
        return None
    cam = str(o.get("camelot") or "").strip()
    return {"key": key, "bpm": bpm, "camelot": cam[:8] if re.fullmatch(r"\d{1,2}[ABab]", cam) else ""}


# ---------------------------------------------------------------------------

def _wait_port(port_file, proc, seconds=25):
    end = time.time() + seconds
    while time.time() < end:
        try:
            lines = port_file.read_text(encoding="utf-8").splitlines()
            if len(lines) >= 2 and lines[0].strip().isdigit():
                return int(lines[0]), lines[1].strip()
        except OSError:
            pass
        if proc.poll() not in (None, 0):
            raise TunebatError("le navigateur n'a pas démarré")
        time.sleep(0.2)
    raise TunebatError("le navigateur n'a pas démarré")


def _page(port, seconds=20):
    end = time.time() + seconds
    while time.time() < end:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3) as r:
                pages = [p for p in json.loads(r.read()) if p.get("type") == "page" and p.get("webSocketDebuggerUrl")]
            if pages:
                return pages[0]
        except (OSError, ValueError):
            pass
        time.sleep(0.3)
    raise TunebatError("la fenêtre Tunebat ne s'est pas ouverte")


def analyze(wav, tag="prod", progress=None, timeout=TIMEOUT, url=ANALYZER, browser=None, extra_args=None):
    """Clé et BPM d'un .wav par Tunebat Analyzer → {"key": "F# min", "bpm": 140, "camelot": "11A"}.
    Lève TunebatError (navigateur absent, pas de résultat, fenêtre fermée…)."""
    step = progress or (lambda *_: None)
    src = Path(wav)
    if not C.is_wav(src):
        raise TunebatError("fichier non WAV")
    browser = browser or find_browser()
    if not browser:
        raise TunebatError("Edge ou Chrome introuvable sur ce PC")
    profile = C.P.base / "tunebat-profile"  # profil à part : rien de ton navigateur n'est touché
    profile.mkdir(parents=True, exist_ok=True)
    port_file = profile / "DevToolsActivePort"
    try:
        port_file.unlink(missing_ok=True)
    except OSError:
        pass
    tag = re.sub(r"[^A-Za-z0-9_-]", "", str(tag))[:20] or "prod"
    name = f"Melofinds-{tag}.wav"
    step("open")
    with tempfile.TemporaryDirectory(prefix="melofinds-tb-", ignore_cleanup_errors=True) as tmp:
        f = Path(tmp) / name
        shutil.copyfile(src, f)
        args = [browser, f"--user-data-dir={profile}", "--remote-debugging-port=0", "--no-first-run",
                "--no-default-browser-check", "--disable-features=Translate", f"--app={url}",
                "--window-size=980,820", *(extra_args or [])]
        proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=C.NO_WINDOW)
        cdp = browser_ws = None
        try:
            port, bpath = _wait_port(port_file, proc)
            browser_ws = f"ws://127.0.0.1:{port}{bpath}"
            cdp = CDP(_page(port)["webSocketDebuggerUrl"])
            needle = json.dumps(Path(name).stem.lower())
            end = time.time() + timeout
            injected_at, polls = None, 0
            while time.time() < end:
                try:
                    st = json.loads(cdp.eval("JSON.stringify({o:performance.timeOrigin,f:!!document.querySelector('input[type=file]'),"
                                             "i:!!window.__mfInjected})") or "{}")
                except (TunebatError, ValueError):
                    st = {}
                if st.get("f") and not st.get("i"):
                    # le .wav est donné au champ « Select Files » (aussi après une vérification Tunebat)
                    r = cdp.call("Runtime.evaluate", {"expression": "document.querySelector('input[type=file]')"})
                    oid = (r.get("result") or {}).get("objectId")
                    if oid:
                        cdp.call("DOM.setFileInputFiles", {"files": [str(f)], "objectId": oid})
                        cdp.eval("window.__mfInjected=1")
                        injected_at, polls = time.time(), 0
                        step("analyze")
                if injected_at:
                    polls += 1
                    if polls == 8:  # repli : certains champs attendent l'évènement « change »
                        cdp.eval("(()=>{const i=document.querySelector('input[type=file]');"
                                 "if(i){i.dispatchEvent(new Event('change',{bubbles:true}))}})()")
                    try:
                        hit = parse_result(json.loads(cdp.eval(READ_JS % needle) or "{}"), name)
                    except (TunebatError, ValueError):
                        hit = None
                    if hit:
                        return hit
                time.sleep(1.2)
            raise TunebatError("Tunebat n'a pas donné de résultat")
        except (ConnectionError, OSError) as e:
            raise TunebatError("fenêtre Tunebat fermée" if isinstance(e, ConnectionError) else f"navigateur : {e}"[:120])
        finally:
            if cdp:
                cdp.close()
            if browser_ws:  # la fenêtre se ferme toute seule
                try:
                    b = CDP(browser_ws)
                    b.ws.send(json.dumps({"id": 1, "method": "Browser.close"}))
                    b.close()
                except Exception:
                    pass
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
            time.sleep(0.3)  # le fichier est libéré avant d'être effacé (Windows)
