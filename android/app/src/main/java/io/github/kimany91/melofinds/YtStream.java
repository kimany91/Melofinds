package io.github.kimany91.melofinds;

import org.schabi.newpipe.extractor.MediaFormat;
import org.schabi.newpipe.extractor.ServiceList;
import org.schabi.newpipe.extractor.stream.AudioStream;
import org.schabi.newpipe.extractor.stream.AudioTrackType;
import org.schabi.newpipe.extractor.stream.DeliveryMethod;
import org.schabi.newpipe.extractor.stream.StreamExtractor;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.RandomAccessFile;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Son d'une vidéo YouTube, téléchargé par le téléphone (NewPipe Extractor, libre et gratuit),
 * pour le donner à l'outil Analyzer de Tunebat. Il ne va que dans le cache de l'app et il est
 * effacé dès que Tunebat a donné la clé et le BPM. Pas d'Android ici.
 */
public final class YtStream {

    static final String USER_AGENT = YtDescription.USER_AGENT;
    static final Pattern VIDEO_ID = YtDescription.VIDEO_ID;
    /** Au-delà, ce n'est plus une prod (mix, live…) : on ne télécharge pas. */
    static final long MAX_BYTES = 25L * 1024 * 1024;
    private static final int PART = 512 * 1024;

    private YtStream() { }

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

    /** Flux audio de la vidéo, du plus pratique au moins pratique (AAC d'abord, puis Opus). */
    public static List<Pick> streams(String videoId) throws Exception {
        if (videoId == null || !VIDEO_ID.matcher(videoId).matches()) throw new IllegalArgumentException("identifiant de vidéo invalide");
        YtDescription.init();
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
        synchronized (YtStream.class) {
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

}
