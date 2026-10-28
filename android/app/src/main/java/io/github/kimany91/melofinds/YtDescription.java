package io.github.kimany91.melofinds;

import org.schabi.newpipe.extractor.NewPipe;
import org.schabi.newpipe.extractor.ServiceList;
import org.schabi.newpipe.extractor.downloader.Downloader;
import org.schabi.newpipe.extractor.downloader.Request;
import org.schabi.newpipe.extractor.downloader.Response;
import org.schabi.newpipe.extractor.exceptions.ReCaptchaException;
import org.schabi.newpipe.extractor.stream.Description;
import org.schabi.newpipe.extractor.stream.StreamExtractor;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Description complète d'une vidéo YouTube (celle que YouTube cache parfois à l'app web),
 * lue depuis le téléphone : la page de la vidéo, sinon NewPipe Extractor (libre, gratuit).
 * Pas d'Android ici (testable sur un ordinateur).
 */
public final class YtDescription {

    static final String USER_AGENT =
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:153.0) Gecko/20100101 Firefox/153.0";
    static final Pattern VIDEO_ID = Pattern.compile("^[A-Za-z0-9_-]{11}$");
    static final long MAX_BYTES = 25L * 1024 * 1024;
    private static boolean ready = false;

    private YtDescription() { }

    static synchronized void init() {
        if (!ready) {
            NewPipe.init(new Http());
            ready = true;
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
