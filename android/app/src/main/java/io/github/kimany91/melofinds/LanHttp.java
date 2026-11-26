package io.github.kimany91.melofinds;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.regex.Pattern;

/**
 * Canal direct avec Melofinds PC sur le même Wi-Fi (sans ntfy.sh et sa limite d'envois).
 * Uniquement vers une adresse du réseau local (10.x, 172.16-31.x, 192.168.x) et un chemin
 * « /mf/… » : rien d'autre n'est joignable par ici. Requête HTTP minimale sur un socket.
 */
final class LanHttp {
    static final Pattern HOST = Pattern.compile(
        "^(10\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}|192\\.168\\.\\d{1,3}\\.\\d{1,3}|172\\.(1[6-9]|2\\d|3[01])\\.\\d{1,3}\\.\\d{1,3})$");
    static final Pattern PATH = Pattern.compile("^/mf/melofinds-[a-f0-9]{32}/(send|recv(\\?since=\\d{1,12}&wait=\\d{1,2})?|file/[a-f0-9]{24})$");
    static final int MAX = 20_000_000;

    static final class Res {
        int status;
        byte[] body;
    }

    private LanHttp() { }

    static boolean allowed(String host, int port, String path) {
        if (host == null || path == null || !HOST.matcher(host).matches() || port < 1024 || port > 65535) return false;
        for (String p : host.split("\\.")) if (Integer.parseInt(p) > 255) return false;
        return PATH.matcher(path).matches();
    }

    static Res request(String host, int port, String method, String path, byte[] body, int timeoutMs) throws IOException {
        if (!allowed(host, port, path)) throw new IOException("adresse refusée");
        try (Socket s = new Socket()) {
            s.connect(new InetSocketAddress(host, port), Math.min(timeoutMs, 2500));
            s.setSoTimeout(timeoutMs);
            OutputStream out = s.getOutputStream();
            StringBuilder h = new StringBuilder();
            h.append(method).append(' ').append(path).append(" HTTP/1.0\r\n");
            h.append("Host: ").append(host).append(':').append(port).append("\r\n");
            h.append("User-Agent: Melofinds-Android\r\n");
            if (body != null) {
                h.append("Content-Type: text/plain; charset=utf-8\r\n");
                h.append("Content-Length: ").append(body.length).append("\r\n");
            }
            h.append("Connection: close\r\n\r\n");
            out.write(h.toString().getBytes(StandardCharsets.US_ASCII));
            if (body != null) out.write(body);
            out.flush();
            InputStream in = s.getInputStream();
            ByteArrayOutputStream all = new ByteArrayOutputStream();
            byte[] buf = new byte[65536];
            int n;
            while ((n = in.read(buf)) > 0) {
                all.write(buf, 0, n);
                if (all.size() > MAX) throw new IOException("réponse trop grosse");
            }
            byte[] raw = all.toByteArray();
            int split = -1;
            for (int i = 0; i + 3 < raw.length; i++) {
                if (raw[i] == '\r' && raw[i + 1] == '\n' && raw[i + 2] == '\r' && raw[i + 3] == '\n') { split = i; break; }
            }
            if (split < 0) throw new IOException("réponse incomplète");
            String head = new String(raw, 0, split, StandardCharsets.ISO_8859_1);
            String[] first = head.split("\r\n", 2)[0].split(" ");
            Res r = new Res();
            r.status = first.length > 1 ? Integer.parseInt(first[1]) : 0;
            r.body = java.util.Arrays.copyOfRange(raw, split + 4, raw.length);
            return r;
        }
    }
}
