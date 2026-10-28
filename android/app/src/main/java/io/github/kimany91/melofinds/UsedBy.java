package io.github.kimany91.melofinds;

import org.schabi.newpipe.extractor.Image;
import org.schabi.newpipe.extractor.InfoItem;
import org.schabi.newpipe.extractor.MediaFormat;
import org.schabi.newpipe.extractor.ServiceList;
import org.schabi.newpipe.extractor.StreamingService;
import org.schabi.newpipe.extractor.search.SearchExtractor;
import org.schabi.newpipe.extractor.services.soundcloud.linkHandler.SoundcloudSearchQueryHandlerFactory;
import org.schabi.newpipe.extractor.services.youtube.linkHandler.YoutubeSearchQueryHandlerFactory;
import org.schabi.newpipe.extractor.stream.AudioStream;
import org.schabi.newpipe.extractor.stream.DeliveryMethod;
import org.schabi.newpipe.extractor.stream.StreamExtractor;
import org.schabi.newpipe.extractor.stream.StreamInfoItem;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * « Déjà posé dessus » : cherche sur YouTube et SoundCloud les morceaux qui citent la prod
 * (NewPipe Extractor, libre et gratuit, sans clé), puis télécharge le son d'un morceau dans le
 * cache de l'app pour comparer son empreinte à celle de la prod. Le fichier est effacé aussitôt.
 */
final class UsedBy {

    static final Pattern SC_URL = Pattern.compile("^https://(?:m\\.)?soundcloud\\.com/[\\w.-]+/[\\w.-]+/?$");
    private static final Pattern YT_ID = Pattern.compile("[?&]v=([A-Za-z0-9_-]{11})");
    /** Un morceau de plus de 8 min n'est pas un son posé sur une prod (mix, live…). */
    static final long MAX_SECONDS = 8 * 60;

    private UsedBy() { }

    static final class Hit {
        String service;   // "yt" ou "sc"
        String id;        // identifiant YouTube (yt)
        String url;
        String title;
        String uploader;
        String uploaderUrl;
        long duration;
        long views;
        String thumb;
    }

    // ------------------------------------------------------------------ recherche

    /** Résultats d'une recherche sur YouTube (« yt ») ou SoundCloud (« sc »). */
    static List<Hit> search(String service, String query, int max) throws Exception {
        YtDescription.init();
        boolean yt = "yt".equals(service);
        StreamingService s = yt ? ServiceList.YouTube : ServiceList.SoundCloud;
        String filter = yt ? YoutubeSearchQueryHandlerFactory.VIDEOS : SoundcloudSearchQueryHandlerFactory.TRACKS;
        SearchExtractor ex = s.getSearchExtractor(query, Collections.singletonList(filter), "");
        ex.fetchPage();
        List<Hit> out = new ArrayList<>();
        for (InfoItem it : ex.getInitialPage().getItems()) {
            if (!(it instanceof StreamInfoItem) || out.size() >= max) continue;
            StreamInfoItem si = (StreamInfoItem) it;
            Hit h = new Hit();
            h.service = service;
            h.url = si.getUrl();
            if (yt) {
                Matcher m = YT_ID.matcher(h.url == null ? "" : h.url);
                if (!m.find()) continue;
                h.id = m.group(1);
            } else if (h.url == null || !SC_URL.matcher(h.url).matches()) {
                continue;
            }
            h.title = cut(si.getName(), 200);
            h.uploader = cut(si.getUploaderName(), 100);
            h.uploaderUrl = cut(si.getUploaderUrl(), 300);
            h.duration = si.getDuration();
            h.views = si.getViewCount();
            List<Image> th = si.getThumbnails();
            if (th != null && !th.isEmpty()) h.thumb = cut(th.get(0).getUrl(), 500);
            out.add(h);
        }
        return out;
    }

    private static String cut(String s, int n) {
        if (s == null) return "";
        return s.length() > n ? s.substring(0, n) : s;
    }

    // ------------------------------------------------------------------ empreintes

    /** Empreinte d'une vidéo YouTube (le son le plus léger suffit). */
    static SoundPrint youtubePrint(String videoId, File dir, double windowSec) throws Exception {
        List<YtStream.Pick> picks = YtStream.streams(videoId);
        // le plus léger d'abord (≥ 40 kb/s) : assez pour l'empreinte, rapide à télécharger
        List<YtStream.Pick> order = new ArrayList<>(picks);
        order.sort((a, b) -> Integer.compare(light(a), light(b)));
        Exception last = null;
        for (int i = 0; i < Math.min(2, order.size()); i++) {
            YtStream.Pick p = order.get(i);
            File raw = new File(dir, "ub-" + videoId + "-" + System.nanoTime() + "." + p.format);
            try {
                YtStream.download(p, raw);
                return AudioPcm.print(raw, windowSec);
            } catch (Exception e) {
                last = e;
            } finally {
                raw.delete();
            }
        }
        throw last != null ? last : new IOException("aucun son");
    }

    private static int light(YtStream.Pick p) {
        int kb = p.bitrate > 0 ? p.bitrate / 1000 : 128;
        return kb < 40 ? 1000 + kb : kb;
    }

    /**
     * Empreinte d'un morceau SoundCloud : fichier MP3 direct, ou liste de morceaux (HLS) en
     * MP3 recollés. Null si SoundCloud ne donne que des formats protégés ou illisibles.
     */
    static SoundPrint soundcloudPrint(String url, File dir, double windowSec) throws Exception {
        if (url == null || !SC_URL.matcher(url).matches()) throw new IllegalArgumentException("lien SoundCloud invalide");
        YtDescription.init();
        StreamExtractor ex = ServiceList.SoundCloud.getStreamExtractor(url);
        ex.fetchPage();
        AudioStream progressive = null;
        AudioStream hls = null;
        for (AudioStream s : ex.getAudioStreams()) {
            if (!s.isUrl() || s.getFormat() != MediaFormat.MP3) continue;
            if (s.getDeliveryMethod() == DeliveryMethod.PROGRESSIVE_HTTP && progressive == null) progressive = s;
            if (s.getDeliveryMethod() == DeliveryMethod.HLS && hls == null) hls = s;
        }
        if (progressive == null && hls == null) return null;
        File raw = new File(dir, "ub-sc-" + System.nanoTime() + ".mp3");
        try {
            if (progressive != null) getTo(progressive.getContent(), raw);
            else hlsTo(hls.getContent(), raw);
            return AudioPcm.print(raw, windowSec);
        } finally {
            raw.delete();
        }
    }

    private static void getTo(String url, File dest) throws IOException {
        if (!url.startsWith("https://")) throw new IOException("lien refusé");
        try (OutputStream os = new FileOutputStream(dest)) {
            os.write(get(url, YtStream.MAX_BYTES));
        }
    }

    /** Liste HLS de morceaux MP3 : on les recolle (un MP3 se lit morceau après morceau). */
    private static void hlsTo(String playlist, File dest) throws IOException {
        if (!playlist.startsWith("https://")) throw new IOException("lien refusé");
        String m3u = new String(get(playlist, 1 << 20), StandardCharsets.UTF_8);
        URL base = new URL(playlist);
        long total = 0;
        try (OutputStream os = new FileOutputStream(dest)) {
            for (String line : m3u.split("\n")) {
                line = line.trim();
                if (line.isEmpty() || line.startsWith("#")) continue;
                String seg = new URL(base, line).toString();
                if (!seg.startsWith("https://")) continue;
                byte[] b = get(seg, YtStream.MAX_BYTES);
                total += b.length;
                if (total > YtStream.MAX_BYTES) break;
                os.write(b);
            }
        }
        if (total == 0) throw new IOException("son vide");
    }

    private static byte[] get(String url, long max) throws IOException {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setConnectTimeout(10000);
        c.setReadTimeout(15000);
        c.setRequestProperty("User-Agent", YtStream.USER_AGENT);
        try {
            int code = c.getResponseCode();
            if (code != 200) throw new IOException("HTTP " + code);
            try (InputStream in = c.getInputStream()) {
                ByteArrayOutputStream out = new ByteArrayOutputStream(64 * 1024);
                byte[] buf = new byte[64 * 1024];
                int n;
                while ((n = in.read(buf)) > 0) {
                    out.write(buf, 0, n);
                    if (out.size() > max) throw new IOException("trop lourd");
                }
                return out.toByteArray();
            }
        } finally {
            c.disconnect();
        }
    }
}
