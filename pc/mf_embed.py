"""Le site Melofinds DANS le logiciel (page « Rechercher » de Melofinds PC, Windows).

Le vrai moteur de prods Melofinds (le même site que sur le téléphone) est ouvert par Edge /
Chrome en mode application (profil à part, ton navigateur n'est pas touché), puis sa fenêtre
est rangée dans la page « Rechercher » du logiciel : plus de fenêtre séparée. La barre de titre
du navigateur est cachée, il ne reste que le site, qui suit la taille du logiciel.

La première fois, cette page est reliée à ce PC comme un téléphone : le bouton « Sur mon PC »
d'une prod la télécharge ici. Le protocole DevTools (local, 127.0.0.1) sert seulement à mesurer
la barre de titre et à fermer proprement le navigateur avec le logiciel.
"""

import json
import os
import subprocess
import threading
import time
import urllib.request

import mf_core as C
import mf_install as I
import mf_tunebat as T
import mf_webwin as WW

WINDOWS = os.name == "nt"
CHROME_CLASS = "Chrome_WidgetWin_1"


class EmbedError(Exception):
    pass


def profile_dir():
    return C.P.base / "web-panel"


def log(msg):
    try:
        C.log(f"[recherche] {msg}")
    except Exception:
        pass


def allow_mixed_dpi():
    """À appeler AVANT de créer la fenêtre Tk : Windows accepte alors d'y ranger la fenêtre
    du navigateur (réglage d'échelle différent)."""
    if not WINDOWS:
        return False
    try:
        import ctypes
        ctypes.windll.user32.SetThreadDpiHostingBehavior(1)  # DPI_HOSTING_BEHAVIOR_MIXED
        return True
    except Exception:
        return False


def start_url(cfg=None, online=True):
    """Adresse du site ; la première fois, avec la clé qui relie la page à ce PC (après « # »)."""
    cfg = cfg if cfg is not None else C.load_config()
    pairing = None
    if not cfg.get("panel_paired"):
        pairing = WW.window_device(cfg)
        C.save_config(cfg)
        try:
            if online:
                I.go_online()  # le programme en ligne répond à la page comme à un téléphone
        except Exception:
            pass
    return WW.window_url("", pairing)


def launch_args(browser, url, x=None, y=None, w=1100, h=760):
    a = [browser, f"--user-data-dir={profile_dir()}", f"--app={url}", "--remote-debugging-port=0",
         "--no-first-run", "--no-default-browser-check", "--hide-crash-restore-bubble",
         "--disable-session-crashed-bubble", "--lang=fr", "--accept-lang=fr-FR,fr",
         "--disable-features=Translate,msTranslateOnLoad", f"--window-size={max(200, int(w))},{max(200, int(h))}"]
    if x is not None and y is not None:  # la fenêtre apparaît déjà à la place de la page
        a.append(f"--window-position={int(x)},{int(y)}")
    return a


def frame_sizes(m, host_w):
    """(barre de titre, bord) du navigateur en pixels de la page Tk, à partir des mesures du
    site : outer/inner (px CSS). Indépendant de l'échelle de Windows."""
    try:
        ow, oh, iw, ih = (float(m[k]) for k in ("ow", "oh", "iw", "ih"))
    except (KeyError, TypeError, ValueError):
        return 0, 0
    if ow <= 0 or host_w <= 0:
        return 0, 0
    ratio = host_w / ow  # px Tk par px CSS
    border = min(max(0.0, (ow - iw) / 2), 20)
    top = min(max(0.0, oh - ih - border), 120)
    return int(round(top * ratio)), int(round(border * ratio))


def title_offset(m, host_w):
    return frame_sizes(m, host_w)[0]


if WINDOWS:
    import ctypes
    from ctypes import wintypes

    _U = ctypes.WinDLL("user32", use_last_error=True)
    _ENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _U.EnumWindows.argtypes = [_ENUM, wintypes.LPARAM]
    _U.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _U.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _U.IsWindowVisible.argtypes = [wintypes.HWND]
    _U.IsWindow.argtypes = [wintypes.HWND]
    _U.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
    _U.SetParent.restype = wintypes.HWND
    _GETL = getattr(_U, "GetWindowLongPtrW", None) or _U.GetWindowLongW
    _SETL = getattr(_U, "SetWindowLongPtrW", None) or _U.SetWindowLongW
    _GETL.argtypes = [wintypes.HWND, ctypes.c_int]
    _GETL.restype = ctypes.c_ssize_t
    _SETL.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    _SETL.restype = ctypes.c_ssize_t
    _U.MoveWindow.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.BOOL]
    _U.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    _U.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _U.PostMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
    _U.SetFocus.argtypes = [wintypes.HWND]

    GWL_STYLE, GWL_EXSTYLE = -16, -20
    WS_CHILD, WS_POPUP, WS_CAPTION, WS_THICKFRAME = 0x40000000, 0x80000000, 0x00C00000, 0x00040000
    WS_SYSMENU, WS_MINIMIZEBOX, WS_MAXIMIZEBOX = 0x00080000, 0x00020000, 0x00010000
    WS_EX_APPWINDOW, WS_EX_WINDOWEDGE, WS_EX_CLIENTEDGE, WS_EX_DLGMODALFRAME = 0x40000, 0x100, 0x200, 0x1
    SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED, SWP_SHOWWINDOW = 0x4, 0x10, 0x20, 0x40


def browser_windows(pid):
    """Fenêtres visibles du navigateur lancé (processus pid)."""
    if not WINDOWS:
        return []
    out = []

    def cb(h, _):
        p = wintypes.DWORD()
        _U.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and _U.IsWindowVisible(h):
            buf = ctypes.create_unicode_buffer(64)
            _U.GetClassNameW(h, buf, 64)
            if buf.value == CHROME_CLASS:
                out.append(h)
        return True
    _U.EnumWindows(_ENUM(cb), 0)
    return out


class Panel:
    """Le site rangé dans un cadre Tk (host_hwnd). start() en arrière-plan ; resize() depuis Tk."""

    def __init__(self, on_state=None):
        self.on_state = on_state or (lambda *_: None)
        self.state, self.detail = "idle", ""
        self.proc = self.hwnd = self.port = self.bpath = None
        self.top = self.border = 0
        self.size = (0, 0)
        self.lock = threading.Lock()
        self.online = True  # (tests : ne pas mettre le PC en ligne)
        self.service = None  # Promo (mf_promo.Service), branché par le logiciel
        self.bridge = None

    def _set(self, state, detail=""):
        self.state, self.detail = state, detail
        log(f"{state} {detail}".strip())
        try:
            self.on_state(state, detail)
        except Exception:
            pass

    def alive(self):
        return bool(self.proc and self.proc.poll() is None and self.hwnd and WINDOWS and _U.IsWindow(self.hwnd))

    # --- démarrage
    def start(self, host_hwnd, screen_xy, size, browser=None, url=None):
        if self.state == "loading" or self.alive():
            return
        self.size = size
        self._set("loading")
        threading.Thread(target=self._start, args=(host_hwnd, screen_xy, size, browser, url), daemon=True).start()

    def _close_old(self):
        """Un ancien navigateur de cette page encore ouvert (logiciel fermé brutalement) : fermé."""
        pf = profile_dir() / "DevToolsActivePort"
        try:
            port, bpath = pf.read_text(encoding="utf-8").splitlines()[:2]
            with urllib.request.urlopen(f"http://127.0.0.1:{int(port)}/json/version", timeout=2):
                pass
            b = T.CDP(f"ws://127.0.0.1:{int(port)}{bpath.strip()}")
            try:
                b.ws.send(json.dumps({"id": 1, "method": "Browser.close"}))
            finally:
                b.close()
            time.sleep(1.5)
            log("ancien navigateur de la page fermé")
        except Exception:
            pass
        try:
            pf.unlink(missing_ok=True)
        except OSError:
            pass

    def _start(self, host_hwnd, screen_xy, size, browser, url):
        try:
            if not WINDOWS:
                raise EmbedError("seulement sur Windows")
            browser = browser or T.find_browser()
            if not browser:
                raise EmbedError("Edge ou Chrome introuvable sur ce PC")
            first = not C.load_config().get("panel_paired")
            url = url or start_url(online=self.online)
            profile_dir().mkdir(parents=True, exist_ok=True)
            self._close_old()
            w, h = size
            self.proc = subprocess.Popen(launch_args(browser, url, *screen_xy, w, h), stdin=subprocess.DEVNULL,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                self.port, self.bpath = T._wait_port(profile_dir() / "DevToolsActivePort", self.proc, 30)
            except T.TunebatError as e:
                raise EmbedError(str(e))
            hwnd, end = None, time.time() + 20
            while not hwnd and time.time() < end:
                wins = browser_windows(self.proc.pid)
                hwnd = wins[0] if wins else None
                if not hwnd:
                    if self.proc.poll() is not None:
                        raise EmbedError("le navigateur s'est fermé")
                    time.sleep(0.05)
            if not hwnd:
                raise EmbedError("fenêtre du navigateur introuvable")
            self.hwnd = hwnd
            self._attach(host_hwnd)
            self._measure()
            self._bridge()
            if first:
                try:
                    cfg = C.load_config()
                    cfg["panel_paired"] = True
                    C.save_config(cfg)
                except OSError as e:  # réglage non noté : la page sera simplement reliée de nouveau
                    log(f"réglage non enregistré : {e}")
            self._set("ready")
        except Exception as e:
            self._set("error", str(e)[:200])
            self.close()

    def _attach(self, host):
        h = self.hwnd
        st = _GETL(h, GWL_STYLE)
        st = (st & ~(WS_POPUP | WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX)) | WS_CHILD
        _SETL(h, GWL_STYLE, st)
        ex = _GETL(h, GWL_EXSTYLE)
        _SETL(h, GWL_EXSTYLE, ex & ~(WS_EX_APPWINDOW | WS_EX_WINDOWEDGE | WS_EX_CLIENTEDGE | WS_EX_DLGMODALFRAME))
        ctypes.set_last_error(0)
        if not _U.SetParent(h, host) and ctypes.get_last_error():
            raise EmbedError(f"rangement de la fenêtre refusé par Windows (erreur {ctypes.get_last_error()})")
        w, h_ = self.size
        _U.SetWindowPos(h, None, 0, 0, w, h_, SWP_NOZORDER | SWP_FRAMECHANGED | SWP_SHOWWINDOW | SWP_NOACTIVATE)
        _U.ShowWindow(h, 5)  # SW_SHOW

    def _eval(self, expr):
        page = T._page(self.port, 15)
        c = T.CDP(page["webSocketDebuggerUrl"])
        try:
            return c.eval(expr)
        finally:
            c.close()

    def _measure(self):
        """Mesure la barre de titre du navigateur pour la cacher (au-dessus du cadre)."""
        try:
            time.sleep(0.4)
            r = self._eval("JSON.stringify({ow: outerWidth, oh: outerHeight, iw: innerWidth, ih: innerHeight})")
            m = json.loads(r) if isinstance(r, str) else r
            self.top, self.border = frame_sizes(m, self.size[0])
            log(f"mesures {m} → barre de titre {self.top}px, bord {self.border}px")
        except Exception as e:
            self.top = self.border = 0
            log(f"mesure impossible : {e}")
        self.resize(*self.size)

    def _bridge(self):
        if not self.service:
            return
        try:
            self.bridge = Bridge(self.port, self.service, C.WEB_APP)
            self.service.emit = self.bridge.event
            log("pont Promo prêt")
        except Exception as e:
            self.bridge = None
            log(f"pont Promo impossible : {e}")

    def event(self, ev):
        if self.bridge and self.bridge.alive:
            self.bridge.event(ev)
            return True
        return False

    def open_view(self, view):
        """Affiche une page du site (Rechercher / Promo) : directement dans la page (sans passer
        par le pont), et le pont est recréé s'il n'est plus là."""
        if not self.alive():
            return False
        view = view if view in ("search", "promo") else "search"

        def go():
            if self.service and not (self.bridge and self.bridge.alive):
                self._bridge()
            try:
                self._eval(f"(window.mfShowView ? (mfShowView('{view}'), 1) : (location.hash = '{view}', 0))")
            except Exception as e:
                log(f"page {view} non affichée : {e}")
        threading.Thread(target=go, daemon=True).start()
        return True

    # --- depuis Tk
    def resize(self, w, h):
        self.size = (int(w), int(h))
        if WINDOWS and self.hwnd:
            try:
                b = self.border  # bords et barre de titre du navigateur : hors du cadre (cachés)
                _U.MoveWindow(self.hwnd, -b, -self.top, int(w) + 2 * b, int(h) + self.top + b, True)
            except Exception:
                pass

    def focus(self):
        if WINDOWS and self.alive():
            try:
                _U.SetFocus(self.hwnd)
            except Exception:
                pass

    def navigate(self, url):
        """Ouvre une adresse du site (recherche, lien de prod) dans la page."""
        if not self.alive():
            return False
        try:
            self._eval(f"location.href = {json.dumps(url)}; 1")
            return True
        except Exception as e:
            log(f"navigation impossible : {e}")
            return False

    def close(self):
        """Ferme proprement le navigateur de la page (avec le logiciel)."""
        with self.lock:
            proc, port, bpath = self.proc, self.port, self.bpath
            self.proc = self.hwnd = None
            br, self.bridge = self.bridge, None
        if br:
            br.close()
        if not proc:
            return
        try:
            if port and proc.poll() is None:
                b = T.CDP(f"ws://127.0.0.1:{port}{bpath}")
                try:
                    b.ws.send(json.dumps({"id": 1, "method": "Browser.close"}))
                finally:
                    b.close()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Pont site ↔ logiciel (page Promo) : le site appelle window.mfPc.call(cmd, args) ; les sons
# et vidéos du PC lui sont servis à l'adresse …/__mfpc/<jeton> (interceptée ici, jamais sur
# internet). Seulement pour le site Melofinds, dans la fenêtre du logiciel.

SHIM = r"""(() => {
  if (window.mfPc || typeof mfPcBridge !== 'function') return;
  const wait = new Map(); const fns = new Set(); let n = 0;
  window.mfPc = {
    call(cmd, args) { return new Promise((ok, no) => { const id = ++n; wait.set(id, { ok, no }); mfPcBridge(JSON.stringify({ id, cmd, args: args || {} })); }); },
    on(fn) { fns.add(fn); return () => fns.delete(fn); },
    url(token) { return `${location.origin}${location.pathname.replace(/[^/]*$/, '')}__mfpc/${token}`; },
  };
  window.__mfPcReply = (id, ok, data) => { const w = wait.get(id); if (!w) return; wait.delete(id); if (ok) w.ok(data); else w.no(new Error(String(data || 'erreur'))); };
  window.__mfPcEvent = (e) => { fns.forEach((f) => { try { f(e); } catch (x) { /* rien */ } }); };
  window.dispatchEvent(new Event('mfpc-ready'));
})();"""

MIME = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".mkv": "video/x-matroska",
        ".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".flac": "audio/flac", ".ogg": "audio/ogg",
        ".aac": "audio/aac", ".jpg": "image/jpeg", ".png": "image/png"}
CHUNK = 2 * 1024 * 1024


def parse_range(header, size):
    """« bytes=a-b » → (début, fin incluse) bornés, ou None."""
    import re
    m = re.match(r"bytes=(\d*)-(\d*)$", str(header or "").strip())
    if not m or size <= 0:
        return None
    a, b = m.group(1), m.group(2)
    if a == "":
        n = int(b or 0)
        start, end = max(0, size - n), size - 1
    else:
        start = int(a)
        end = min(size - 1, int(b) if b else start + CHUNK - 1)
    if start >= size or end < start:
        return None
    return start, min(end, start + CHUNK - 1)


class Bridge:
    def __init__(self, port, service, allowed_prefix, log_fn=log):
        import base64
        self.b64 = base64.b64encode
        self.service, self.allowed, self.log = service, allowed_prefix, log_fn
        page = T._page(port, 15)
        self.ws = T.WS(page["webSocketDebuggerUrl"])
        self.lock = threading.Lock()
        self.n = 0
        self.wait = {}
        self.alive = True
        threading.Thread(target=self._read, daemon=True).start()
        self.call("Runtime.enable")
        self.call("Runtime.addBinding", {"name": "mfPcBridge"})
        self.call("Page.enable")
        self.call("Page.addScriptToEvaluateOnNewDocument", {"source": SHIM})
        self.call("Fetch.enable", {"patterns": [{"urlPattern": "*__mfpc/*", "requestStage": "Request"}]})
        self.call("Runtime.evaluate", {"expression": SHIM})

    def send(self, method, params=None):
        with self.lock:
            self.n += 1
            i = self.n
            self.ws.send(json.dumps({"id": i, "method": method, "params": params or {}}))
        return i

    def call(self, method, params=None, timeout=15):
        ev = threading.Event()
        box = {}
        with self.lock:
            self.n += 1
            i = self.n
            self.wait[i] = (ev, box)
            self.ws.send(json.dumps({"id": i, "method": method, "params": params or {}}))
        if not ev.wait(timeout):
            self.wait.pop(i, None)
            raise EmbedError(f"{method} : pas de réponse")
        if "error" in box:
            raise EmbedError(str(box["error"]))
        return box.get("result") or {}

    def _read(self):
        while self.alive:
            try:
                msg = json.loads(self.ws.recv())
            except Exception:
                self.alive = False
                break
            if "id" in msg:
                w = self.wait.pop(msg["id"], None)
                if w:
                    ev, box = w
                    if "error" in msg:
                        box["error"] = (msg["error"] or {}).get("message")
                    else:
                        box["result"] = msg.get("result")
                    ev.set()
                continue
            method, p = msg.get("method"), msg.get("params") or {}
            if method == "Runtime.bindingCalled" and p.get("name") == "mfPcBridge":
                threading.Thread(target=self._command, args=(p.get("payload"),), daemon=True).start()
            elif method == "Fetch.requestPaused":
                threading.Thread(target=self._serve, args=(p,), daemon=True).start()

    def _page_ok(self):
        try:
            r = self.call("Runtime.evaluate", {"expression": "location.href", "returnByValue": True}, 5)
            return str((r.get("result") or {}).get("value") or "").startswith(self.allowed)
        except EmbedError:
            return False

    def js(self, expr):
        try:
            self.send("Runtime.evaluate", {"expression": expr})
        except Exception:
            pass

    def event(self, ev):
        self.js(f"window.__mfPcEvent && __mfPcEvent({json.dumps(ev, ensure_ascii=True)})")

    def _command(self, payload):
        try:
            req = json.loads(payload)
            rid, cmd, args = int(req["id"]), str(req["cmd"])[:40], req.get("args") or {}
        except (ValueError, KeyError, TypeError):
            return
        if not self._page_ok():  # seulement le site Melofinds
            self.js(f"__mfPcReply({rid}, false, {json.dumps('page non autorisée')})")
            return

        def progress(text="", pct=None):
            self.event({"type": "progress", "id": rid, "cmd": cmd, "text": str(text)[:200], "pct": pct})
        try:
            res = self.service.call(cmd, args, progress)
            self.js(f"__mfPcReply({rid}, true, {json.dumps(res, ensure_ascii=True)})")
        except Exception as e:
            self.log(f"Promo {cmd} : {e}")
            self.js(f"__mfPcReply({rid}, false, {json.dumps(str(e)[:300], ensure_ascii=True)})")

    def _serve(self, p):
        rid = p.get("requestId")
        req = p.get("request") or {}
        url = str(req.get("url") or "")
        token = url.split("__mfpc/", 1)[-1].split("?", 1)[0].split("/", 1)[0]
        path = self.service.files.get(token) if url.startswith(self.allowed) else None
        try:
            if not path or not path.exists():
                self.send("Fetch.fulfillRequest", {"requestId": rid, "responseCode": 404, "body": ""})
                return
            size = path.stat().st_size
            headers = {k.lower(): v for k, v in (req.get("headers") or {}).items()}
            rng = parse_range(headers.get("range"), size)
            if rng is None and size > CHUNK and path.suffix.lower() not in (".jpg", ".png"):
                rng = (0, CHUNK - 1)  # gros fichier : par morceaux (le lecteur redemande la suite)
            with open(path, "rb") as f:
                if rng:
                    f.seek(rng[0])
                    data = f.read(rng[1] - rng[0] + 1)
                else:
                    data = f.read()
            hs = [{"name": "Content-Type", "value": MIME.get(path.suffix.lower(), "application/octet-stream")},
                  {"name": "Accept-Ranges", "value": "bytes"}, {"name": "Cache-Control", "value": "no-store"},
                  {"name": "Content-Length", "value": str(len(data))}]
            if rng:
                hs.append({"name": "Content-Range", "value": f"bytes {rng[0]}-{rng[0] + len(data) - 1}/{size}"})
            self.send("Fetch.fulfillRequest", {"requestId": rid, "responseCode": 206 if rng else 200, "responseHeaders": hs,
                                               "body": self.b64(data).decode()})
        except Exception as e:
            self.log(f"Promo : fichier non servi ({e})")
            try:
                self.send("Fetch.failRequest", {"requestId": rid, "errorReason": "Failed"})
            except Exception:
                pass

    def close(self):
        self.alive = False
        self.ws.close()
