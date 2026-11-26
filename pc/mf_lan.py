"""Canal direct téléphone ↔ PC quand ils sont sur le même Wi-Fi (sans ntfy.sh).

ntfy.sh limite les envois PAR CONNEXION INTERNET : chez toi, le téléphone et le PC partagent la
même limite, et quand elle est épuisée plus rien ne passe (« PC hors ligne », versions qui
n'arrivent plus, QR code refusé). Sur le même Wi-Fi, l'appli Android parle donc directement au
programme du PC :

- seulement depuis le réseau local (adresses privées : box, Wi-Fi), jamais depuis internet ;
- seulement pour un appareil relié (son code), et chaque envoi reste signé par sa clé : il est
  vérifié exactement comme ceux qui passent par ntfy.sh (boîte locale du programme en ligne) ;
- les réponses du PC (et les sons, la liste des projets) attendent ici que le téléphone les
  relève ; pas relevées à temps (téléphone parti du Wi-Fi) : elles repartent par ntfy.sh.
"""

import http.server
import ipaddress
import json
import secrets
import socket
import socketserver
import threading
import time
import urllib.parse

import mf_core as C

PORT = 47833
EV_MAX = 300
FILES_MAX = 60_000_000
ACTIVE = 45      # s : le téléphone a relevé il y a moins de 45 s → on lui parle en direct
RESEND = 90      # s : réponse pas relevée → elle repart par ntfy.sh
WAIT_MAX = 25    # s : attente d'une réponse (le téléphone relève en continu)


def private(ip):
    try:
        a = ipaddress.ip_address(str(ip).split("%")[0])
    except ValueError:
        return False
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped:
        a = a.ipv4_mapped
    return a.is_loopback or (a.is_private and not a.is_link_local and not a.is_unspecified)


def lan_ips():
    """Adresses IPv4 privées de ce PC (box, Wi-Fi), la principale d'abord."""
    out = []
    try:  # aucune donnée n'est envoyée : juste la route choisie par Windows
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.168.1.1", 9))
        out.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            out.append(info[4][0])
    except OSError:
        pass
    seen = []
    for ip in out:
        a = ipaddress.ip_address(ip)
        if a.is_private and not a.is_loopback and not a.is_link_local and ip not in seen:
            seen.append(ip)
    return seen[:4]


class Hub:
    """Réponses du PC qui attendent que le téléphone les relève (en mémoire)."""

    def __init__(self):
        self.cv = threading.Condition()
        self.seq = 0
        self.events = {}   # code → [évènement]
        self.files = {}    # id → (code, octets, heure)
        self.seen = {}     # code → dernière relève
        self.port = None

    def addresses(self):
        return [f"{ip}:{self.port}" for ip in lan_ips()] if self.port else []

    def active(self, code):
        return time.time() - self.seen.get(code, 0) < ACTIVE

    def push(self, code, payload, data=None, filename=""):
        with self.cv:
            self.seq += 1
            ev = {"id": f"lan-{self.seq}", "seq": self.seq, "time": int(time.time()), "event": "message",
                  "message": json.dumps(payload, ensure_ascii=False, separators=(",", ":")), "_at": time.time(), "_got": False}
            if data is not None:
                fid = secrets.token_hex(12)
                self.files[fid] = (code, bytes(data), time.time())
                ev["attachment"] = {"name": str(filename)[:80], "size": len(data), "lan": fid}
                total = sum(len(v[1]) for v in self.files.values())
                for k in sorted(self.files, key=lambda k: self.files[k][2]):
                    if total <= FILES_MAX:
                        break
                    total -= len(self.files.pop(k)[1])
            lst = self.events.setdefault(code, [])
            lst.append(ev)
            del lst[:-EV_MAX]
            self.cv.notify_all()
        return True

    def take(self, code, since, wait):
        end = time.time() + max(0.0, min(WAIT_MAX, wait))
        with self.cv:
            while True:
                self.seen[code] = time.time()
                new = [e for e in self.events.get(code, []) if e["seq"] > since]
                if new or time.time() >= end:
                    break
                self.cv.wait(min(5.0, max(0.1, end - time.time())))
            for e in new:
                e["_got"] = True
            self.seen[code] = time.time()
            return [{k: v for k, v in e.items() if not k.startswith("_")} for e in new], self.seq

    def file(self, code, fid):
        with self.cv:
            v = self.files.get(fid)
            return v[1] if v and v[0] == code else None

    def unfetched(self, older=RESEND):
        """Réponses jamais relevées (téléphone parti du Wi-Fi) : à renvoyer par ntfy.sh."""
        out = []
        now = time.time()
        with self.cv:
            for code, lst in self.events.items():
                for e in lst:
                    if not e["_got"] and now - e["_at"] > older:
                        e["_got"] = True
                        out.append((code, e))
        return out


HUB = None


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = False


class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = "Melofinds"
    sys_version = ""
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):  # pas de journal par requête
        pass

    def _send(self, status, body=b"", ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _route(self):
        if not private(self.client_address[0]):
            self._send(403, {"err": "réseau local seulement"})
            return None
        u = urllib.parse.urlsplit(self.path)
        parts = u.path.strip("/").split("/")
        if len(parts) < 3 or parts[0] != "mf" or not C.CODE_RE.match(parts[1]):
            self._send(404, {"err": "?"})
            return None
        code = parts[1]
        try:
            known = any(d.get("code") == code for d in C.load_config().get("devices") or [])
        except Exception:
            known = False
        if not known:
            self._send(403, {"err": "appareil inconnu : rescanne le QR code du PC"})
            return None
        return code, parts[2:], urllib.parse.parse_qs(u.query)

    def do_GET(self):
        r = self._route()
        if not r:
            return
        code, rest, q = r
        hub = HUB
        if rest == ["recv"]:
            try:
                since = int((q.get("since") or ["0"])[0])
                wait = float((q.get("wait") or ["0"])[0])
            except ValueError:
                since, wait = 0, 0.0
            evs, last = hub.take(code, since, wait)
            self._send(200, {"v": C.VERSION, "seq": last, "ev": evs})
        elif len(rest) == 2 and rest[0] == "file" and len(rest[1]) == 24:
            data = hub.file(code, rest[1])
            if data is None:
                self._send(404, {"err": "fichier expiré"})
            else:
                self._send(200, data, "application/octet-stream")
        else:
            self._send(404, {"err": "?"})

    def do_POST(self):
        r = self._route()
        if not r:
            return
        code, rest, _ = r
        if rest != ["send"]:
            self._send(404, {"err": "?"})
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if n <= 0 or n > C.INBOX_MAX:
            self._send(413, {"err": "envoi refusé"})
            return
        body = self.rfile.read(n).decode("utf-8", "replace")
        try:
            C.inbox_put(code, body, lan=True)  # vérifié (signature) par le programme en ligne
        except (ValueError, OSError):
            self._send(400, {"err": "envoi refusé"})
            return
        HUB.seen[code] = time.time()
        self._send(200, {"ok": True, "v": C.VERSION})


def start(port=PORT):
    """Démarre le canal direct (programme en ligne). Renvoie le Hub, ou None si impossible."""
    global HUB
    hub = Hub()
    for p in range(port, port + 5):
        try:
            srv = _Server(("0.0.0.0", p), _Handler)
        except OSError:
            continue
        hub.port = srv.server_address[1]
        HUB = hub
        threading.Thread(target=srv.serve_forever, daemon=True, name="melofinds-wifi").start()
        try:
            C._write_json(C.P.base / "wifi.json", {"port": hub.port, "at": int(time.time())})
        except OSError:
            pass
        C.LAN = hub
        hub.server = srv
        return hub
    return None


def stop():
    global HUB
    if HUB is not None and getattr(HUB, "server", None):
        HUB.server.shutdown()
        HUB.server.server_close()
    HUB = None
    C.LAN = None


def resend_unfetched(hub=None):
    """Réponses pas relevées (téléphone parti) : renvoyées par ntfy.sh (sons : redemandés par la synchro)."""
    hub = hub or HUB
    if hub is None:
        return 0
    n = 0
    for code, ev in hub.unfetched():
        if "attachment" in ev:
            continue
        try:
            payload = json.loads(ev["message"])
        except ValueError:
            continue
        C.reply_ntfy(code, payload)
        n += 1
    return n


def pairing_addresses():
    """Adresses à mettre dans le QR code (port du programme en ligne, sinon celui par défaut)."""
    port = (C._read_json(C.P.base / "wifi.json") or {}).get("port") or PORT
    return [f"{ip}:{int(port)}" for ip in lan_ips()]
