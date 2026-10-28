package io.github.kimany91.melofinds;

import org.schabi.newpipe.extractor.MediaFormat;
import org.schabi.newpipe.extractor.NewPipe;
import org.schabi.newpipe.extractor.ServiceList;
import org.schabi.newpipe.extractor.downloader.Downloader;
import org.schabi.newpipe.extractor.downloader.Request;
import org.schabi.newpipe.extractor.downloader.Response;
import org.schabi.newpipe.extractor.exceptions.ReCaptchaException;
import org.schabi.newpipe.extractor.stream.AudioStream;
import org.schabi.newpipe.extractor.stream.AudioTrackType;
import org.schabi.newpipe.extractor.stream.DeliveryMethod;
import org.schabi.newpipe.extractor.stream.Description;
import org.schabi.newpipe.extractor.stream.StreamExtractor;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.RandomAccessFile;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Son d'une vidéo YouTube, récupéré directement par le téléphone (comme NewPipe), sans
 * site intermédiaire : NewPipe Extractor (libre, gratuit) trouve le flux audio, puis on le
 * télécharge par morceaux en parallèle. Rien n'est rangé dans les fichiers de l'utilisateur :
 * le son va dans le cache de l'app et il est effacé après l'analyse.
 *
 * Pas d'Android ici (testable sur un ordinateur) ; le décodage est dans AudioPcm.
 */
public final class YtAudio {

    static final String USER_AGENT =
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:153.0) Gecko/20100101 Firefox/153.0";
    static final Pattern VIDEO_ID = Pattern.compile("^[A-Za-z0-9_-]{11}$");
    /** Au-delà, ce n'est plus une prod (mix, live…) : on ne télécharge pas. */
    static final long MAX_BYTES = 25L * 1024 * 1024;
    private static final int PART = 512 * 1024;
    private static boolean ready = false;

    private YtAudio() { }

    /** Flux audio choisi. */
    public static final class Pick {
        public final String url;
        public final String format;   // "m4a" ou "webm"
        public final int bitrate;
        public final long length;     // octets, 0 si inconnu
        Pick(String url, String format, int bitrate, long length) {
            this.url = url; this.format = format; this.bitrate = bitrate; this.length = length;
        }
    }

    static synchronized void init() {
        if (!ready) {
            NewPipe.init(new Http());
            ready = true;
        }
    }

    /** Flux audio de la vidéo, du plus pratique au moins pratique (AAC d'abord, puis Opus). */
    public static List<Pick> streams(String videoId) throws Exception {
        if (videoId == null || !VIDEO_ID.matcher(videoId).matches()) throw new IllegalArgumentException("identifiant de vidéo invalide");
        init();
        StreamExtractor ex = ServiceList.YouTube.getStreamExtractor("https://www.youtube.com/watch?v=" + videoId);
        ex.fetchPage();
        List<Pick> m4a = new ArrayList<>();
        List<Pick> webm = new ArrayList<>();
        for (AudioStream s : ex.getAudioStreams()) {
            if (s.getDeliveryMethod() != DeliveryMethod.PROGRESSIVE_HTTP || !s.isUrl()) continue;
            AudioTrackType t = s.getAudioTrackType();
            if (t != null && t != AudioTrackType.ORIGINAL) continue; // pas les doublages
            MediaFormat f = s.getFormat();
            String url = s.getContent();
            long len = clen(url);
            if (len > MAX_BYTES) continue;
            int br = s.getAverageBitrate() > 0 ? s.getAverageBitrate() : s.getBitrate();
            if (f == MediaFormat.M4A) m4a.add(new Pick(url, "m4a", br, len));
            else if (f == MediaFormat.WEBMA_OPUS || f == MediaFormat.WEBMA) webm.add(new Pick(url, "webm", br, len));
        }
        // AAC ~128 kb/s (itag 140) : lu par tous les Android ; le plus léger d'abord
        m4a.sort((a, b) -> Integer.compare(score(a), score(b)));
        webm.sort((a, b) -> Integer.compare(score(a), score(b)));
        List<Pick> all = new ArrayList<>(m4a);
        all.addAll(webm);
        if (all.isEmpty()) throw new IOException("aucun flux audio");
        return all;
    }

    // Débit le plus proche de 128 kb/s (assez net pour la clé, léger à télécharger)
    private static int score(Pick p) {
        int kb = p.bitrate > 0 ? p.bitrate / 1000 : 128;
        return Math.abs(kb - 128) + (kb < 40 ? 200 : 0);
    }

    static long clen(String url) {
        Matcher m = Pattern.compile("[?&]clen=(\\d+)").matcher(url);
        return m.find() ? Long.parseLong(m.group(1)) : 0;
    }

    /**
     * Télécharge le flux dans {@code dest} : 4 morceaux à la fois quand la taille est
     * connue (le plus rapide), sinon à la suite.
     */
    public static long download(Pick p, File dest) throws Exception {
        long total = p.length;
        if (total <= 0) return downloadSequential(p.url, dest);
        if (total > MAX_BYTES) throw new IOException("fichier trop lourd");
        try (RandomAccessFile raf = new RandomAccessFile(dest, "rw")) { raf.setLength(total); }
        ExecutorService pool = Executors.newFixedThreadPool(4);
        try {
            List<Future<Void>> jobs = new ArrayList<>();
            int n = 0;
            for (long from = 0; from < total; from += PART) {
                final long a = from;
                final long b = Math.min(total, from + PART) - 1;
                final int rn = ++n;
                jobs.add(pool.submit(() -> { fetchRange(p.url, a, b, rn, dest); return null; }));
            }
            for (Future<Void> j : jobs) j.get();
        } finally {
            pool.shutdownNow();
        }
        return total;
    }

    private static long downloadSequential(String url, File dest) throws Exception {
        long pos = 0;
        int rn = 0;
        try (RandomAccessFile raf = new RandomAccessFile(dest, "rw")) {
            raf.setLength(0);
            while (pos < MAX_BYTES) {
                byte[] got = rangeBytes(url, pos, pos + PART - 1, ++rn);
                raf.seek(pos);
                raf.write(got);
                pos += got.length;
                if (got.length < PART) break;
            }
        }
        if (pos == 0) throw new IOException("son vide");
        return pos;
    }

    private static void fetchRange(String url, long a, long b, int rn, File dest) throws IOException {
        byte[] got = null;
        IOException last = null;
        for (int attempt = 0; attempt < 3 && got == null; attempt++) {
            try { got = rangeBytes(url, a, b, rn); } catch (IOException e) { last = e; }
        }
        if (got == null) throw last != null ? last : new IOException("morceau manquant");
        if (got.length != b - a + 1) throw new IOException("morceau incomplet");
        synchronized (YtAudio.class) {
            try (RandomAccessFile raf = new RandomAccessFile(dest, "rw")) {
                raf.seek(a);
                raf.write(got);
            }
        }
    }

    // Même requête que le lecteur de NewPipe : POST « x\0 », plage dans l'adresse (&range=)
    private static byte[] rangeBytes(String url, long a, long b, int rn) throws IOException {
        String u = url + "&range=" + a + "-" + b + "&rn=" + rn;
        HttpURLConnection c = (HttpURLConnection) new URL(u).openConnection();
        c.setConnectTimeout(10000);
        c.setReadTimeout(15000);
        c.setRequestProperty("User-Agent", USER_AGENT);
        c.setRequestProperty("Accept-Encoding", "identity");
        if (url.contains("c=WEB")) {
            c.setRequestProperty("Origin", "https://www.youtube.com");
            c.setRequestProperty("Referer", "https://www.youtube.com/");
        }
        c.setRequestMethod("POST");
        c.setDoOutput(true);
        byte[] body = { 0x78, 0 };
        c.setFixedLengthStreamingMode(body.length);
        try {
            try (OutputStream os = c.getOutputStream()) { os.write(body); }
            int code = c.getResponseCode();
            if (code != 200 && code != 206) throw new IOException("YouTube a refusé le son (HTTP " + code + ")");
            try (InputStream in = c.getInputStream()) { return readAll(in, (int) (b - a + 1)); }
        } finally {
            c.disconnect();
        }
    }

    private static byte[] readAll(InputStream in, int hint) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream(Math.max(1024, hint));
        byte[] buf = new byte[64 * 1024];
        int n;
        while ((n = in.read(buf)) > 0) {
            out.write(buf, 0, n);
            if (out.size() > MAX_BYTES) throw new IOException("trop lourd");
        }
        return out.toByteArray();
    }

    // ------------------------------------------------------------ description complète

    static final int DESC_MAX = 5000;
    private static final String PAGE_UA =
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36";
    private static final Pattern SHORT_DESC = Pattern.compile("\"shortDescription\":\"((?:[^\"\\\\]|\\\\.)*)\"");

    /**
     * Description complète d'une vidéo (celle que YouTube cache parfois à l'app web), lue sur
     * la page de la vidéo comme le fait Melofinds PC ; null si illisible.
     */
    public static String description(String videoId) {
        if (videoId == null || !VIDEO_ID.matcher(videoId).matches()) return null;
        String d = pageDescription(videoId);
        return d != null ? d : newPipeDescription(videoId);
    }

    /** Secours : la description par NewPipe Extractor (API de l'appli YouTube). */
    static String newPipeDescription(String videoId) {
        try {
            init();
            StreamExtractor ex = ServiceList.YouTube.getStreamExtractor("https://www.youtube.com/watch?v=" + videoId);
            ex.fetchPage();
            Description d = ex.getDescription();
            if (d == null || d.content().isEmpty()) return null;
            String t = d.type() == Description.Type.HTML ? htmlToText(d.content()) : d.content();
            return t.length() > DESC_MAX ? t.substring(0, DESC_MAX) : t;
        } catch (Throwable e) {
            return null;
        }
    }

    static String htmlToText(String html) {
        String t = html.replaceAll("(?i)<br\\s*/?>", "\n").replaceAll("<[^>]+>", "");
        return t.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", "\"").replace("&#39;", "'").replace("&nbsp;", " ");
    }

    private static String pageDescription(String videoId) {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL("https://www.youtube.com/watch?v=" + videoId + "&hl=en").openConnection();
            c.setConnectTimeout(10000);
            c.setReadTimeout(15000);
            c.setRequestProperty("User-Agent", PAGE_UA);
            c.setRequestProperty("Accept-Language", "en-US,en;q=0.9,fr;q=0.8");
            c.setRequestProperty("Cookie", "SOCS=CAI; CONSENT=YES+cb");
            if (c.getResponseCode() != 200) return null;
            String html;
            try (InputStream in = c.getInputStream()) { html = new String(readAll(in, 1 << 20), StandardCharsets.UTF_8); }
            Matcher m = SHORT_DESC.matcher(html);
            if (!m.find()) return null;
            String d = unescapeJson(m.group(1));
            return d.length() > DESC_MAX ? d.substring(0, DESC_MAX) : d;
        } catch (Exception e) {
            return null;
        } finally {
            if (c != null) c.disconnect();
        }
    }

    static String unescapeJson(String s) {
        StringBuilder out = new StringBuilder(s.length());
        for (int i = 0; i < s.length(); i++) {
            char ch = s.charAt(i);
            if (ch != '\\' || i + 1 >= s.length()) { out.append(ch); continue; }
            char n = s.charAt(++i);
            switch (n) {
                case 'n': out.append('\n'); break;
                case 't': out.append('\t'); break;
                case 'r': out.append('\r'); break;
                case 'b': out.append('\b'); break;
                case 'f': out.append('\f'); break;
                case 'u':
                    if (i + 4 < s.length()) {
                        try { out.append((char) Integer.parseInt(s.substring(i + 1, i + 5), 16)); i += 4; }
                        catch (NumberFormatException e) { out.append(n); }
                    }
                    break;
                default: out.append(n); // " \ /
            }
        }
        return out.toString();
    }

    /** Accès réseau de NewPipe Extractor (pages et API de YouTube). */
    static final class Http extends Downloader {
        @Override
        public Response execute(Request request) throws IOException, ReCaptchaException {
            String url = request.url();
            HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
            c.setConnectTimeout(10000);
            c.setReadTimeout(15000);
            c.setRequestMethod(request.httpMethod());
            c.setRequestProperty("User-Agent", USER_AGENT);
            for (Map.Entry<String, List<String>> h : request.headers().entrySet()) {
                if (h.getValue() == null || h.getValue().isEmpty()) continue;
                // la compression est gérée par la connexion elle-même
                if ("accept-encoding".equalsIgnoreCase(h.getKey())) continue;
                c.setRequestProperty(h.getKey(), String.join(", ", h.getValue()));
            }
            byte[] data = request.dataToSend();
            try {
                if (data != null) {
                    c.setDoOutput(true);
                    c.setFixedLengthStreamingMode(data.length);
                    try (OutputStream os = c.getOutputStream()) { os.write(data); }
                }
                int code = c.getResponseCode();
                if (code == 429) throw new ReCaptchaException("YouTube demande une vérification", url);
                InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
                String body = "";
                if (in != null && !"HEAD".equals(request.httpMethod())) {
                    try (InputStream s = in) { body = new String(readAll(s, 64 * 1024), StandardCharsets.UTF_8); }
                }
                Map<String, List<String>> headers = new HashMap<>();
                for (Map.Entry<String, List<String>> h : c.getHeaderFields().entrySet()) {
                    if (h.getKey() != null) headers.put(h.getKey(), h.getValue());
                }
                return new Response(code, c.getResponseMessage(), headers, body, c.getURL().toString());
            } finally {
                c.disconnect();
            }
        }
    }
}
