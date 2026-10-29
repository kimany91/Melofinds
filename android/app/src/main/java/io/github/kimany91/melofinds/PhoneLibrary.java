package io.github.kimany91.melofinds;

import android.content.ContentResolver;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.UriPermission;
import android.media.MediaCodec;
import android.media.MediaExtractor;
import android.media.MediaFormat;
import android.media.MediaMuxer;
import android.net.Uri;
import android.util.Base64;

import androidx.documentfile.provider.DocumentFile;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.Iterator;
import java.util.List;
import java.util.Locale;
import java.util.regex.Pattern;

/**
 * Les prods téléchargées sur le téléphone, dans le dossier « Melofinds Instru » (Musique) :
 * un vrai dossier du téléphone, gardé si l'appli est désinstallée. L'appli n'a accès qu'au
 * dossier que tu lui as donné (sélecteur d'Android), à rien d'autre ; elle n'y écrit que des
 * sons (.m4a / .webm), leurs miniatures (.thumbs/) et son index (.melofinds.json : lien de la
 * vidéo, clé, BPM, favoris…), qui suivent le dossier même après une réinstallation.
 */
final class PhoneLibrary {

    static final String FOLDER = "Melofinds Instru";
    static final String INDEX = ".melofinds.json";
    static final String THUMBS = ".thumbs";
    /** Sons lus dans le dossier (ceux que Melofinds y met, et ceux que tu y ajoutes). */
    static final Pattern AUDIO = Pattern.compile("(?i).+\\.(m4a|webm|mp3|wav|ogg|opus|aac|flac)$");
    private static final Pattern VIDEO_ID = Pattern.compile("^[A-Za-z0-9_-]{11}$");
    private static final String PREFS = "melofinds_phone";
    private static final String KEY_TREE = "tree";
    /** Une seule écriture de l'index à la fois (téléchargements, favoris, réparations). */
    private static final Object INDEX_LOCK = new Object();

    private PhoneLibrary() { }

    // ------------------------------------------------------------------ dossier

    static void saveTree(Context c, Uri tree) {
        c.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(KEY_TREE, tree.toString()).apply();
    }

    private static Uri savedTree(Context c) {
        SharedPreferences sp = c.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        String s = sp.getString(KEY_TREE, null);
        if (s == null) return null;
        Uri u = Uri.parse(s);
        for (UriPermission p : c.getContentResolver().getPersistedUriPermissions()) {
            if (p.getUri().equals(u) && p.isReadPermission() && p.isWritePermission()) return u;
        }
        return null; // permission perdue (appli réinstallée…) : il faut rechoisir le dossier
    }

    /** Le dossier « Melofinds Instru » (le dossier choisi, ou son sous-dossier), ou null. */
    static DocumentFile folder(Context c, boolean create) {
        Uri tree = savedTree(c);
        if (tree == null) return null;
        DocumentFile root = DocumentFile.fromTreeUri(c, tree);
        if (root == null || !root.isDirectory()) return null;
        if (FOLDER.equalsIgnoreCase(String.valueOf(root.getName()))) return root;
        DocumentFile f = root.findFile(FOLDER);
        if (f != null && f.isDirectory()) return f;
        return create ? root.createDirectory(FOLDER) : null;
    }

    // ------------------------------------------------------------------ index

    static JSONObject readIndex(Context c, DocumentFile dir) {
        DocumentFile f = dir.findFile(INDEX);
        if (f == null || !f.isFile()) return new JSONObject();
        try {
            return new JSONObject(new String(readAll(c, f.getUri(), 4_000_000), StandardCharsets.UTF_8));
        } catch (Exception e) {
            return new JSONObject();
        }
    }

    private static void writeIndex(Context c, DocumentFile dir, JSONObject idx) throws IOException {
        DocumentFile f = dir.findFile(INDEX);
        if (f == null) f = dir.createFile("application/octet-stream", INDEX);
        if (f == null) throw new IOException("index impossible à créer");
        try (OutputStream os = c.getContentResolver().openOutputStream(f.getUri(), "wt")) {
            if (os == null) throw new IOException("index impossible à écrire");
            os.write(idx.toString().getBytes(StandardCharsets.UTF_8));
        }
    }

    /** Modifie l'entrée d'un fichier dans l'index (relu juste avant : rien n'est perdu). */
    interface Edit { void apply(JSONObject meta) throws Exception; }

    static void editMeta(Context c, DocumentFile dir, String name, Edit e) throws Exception {
        synchronized (INDEX_LOCK) {
            JSONObject idx = readIndex(c, dir);
            JSONObject m = idx.optJSONObject(name);
            if (m == null) m = new JSONObject();
            e.apply(m);
            idx.put(name, m);
            writeIndex(c, dir, idx);
        }
    }

    /** Étiquettes (« Luther type beat », « Énergique »…) et couleur, si elle n'existe pas encore. */
    static void setInfo(Context c, DocumentFile dir, String name, JSONArray tags, JSONObject color) throws Exception {
        if (find(dir, name) == null) throw new IOException("prod introuvable");
        JSONArray clean = new JSONArray();
        for (int i = 0; tags != null && i < tags.length() && clean.length() < 12; i++) {
            String t = tags.optString(i, "").replaceAll("\\p{Cntrl}", "").trim();
            if (!t.isEmpty() && t.length() <= 40) clean.put(t);
        }
        JSONObject col = null;
        if (color != null && color.has("h")) {
            col = new JSONObject();
            col.put("h", Math.max(0, Math.min(360, color.optInt("h"))));
            col.put("s", Math.max(0, Math.min(100, color.optInt("s", 60))));
        }
        final JSONObject fc = col;
        editMeta(c, dir, name, m -> {
            if (clean.length() > 0) m.put("tags", clean);
            if (fc != null && !m.has("color")) m.put("color", fc);
        });
    }

    // ------------------------------------------------------------------ liste

    static JSONArray list(Context c, DocumentFile dir) throws Exception {
        JSONObject idx = readIndex(c, dir);
        JSONArray out = new JSONArray();
        for (DocumentFile f : dir.listFiles()) {
            String name = f.getName();
            if (name == null || !f.isFile() || !AUDIO.matcher(name).matches() || f.length() <= 0) continue;
            JSONObject o = new JSONObject();
            o.put("name", name);
            o.put("size", f.length());
            o.put("at", f.lastModified());
            JSONObject meta = idx.optJSONObject(name);
            if (meta != null) o.put("meta", meta);
            out.put(o);
        }
        return out;
    }

    static DocumentFile find(DocumentFile dir, String name) {
        if (name == null || !AUDIO.matcher(name).matches() || name.contains("/")) return null;
        DocumentFile f = dir.findFile(name);
        return f != null && f.isFile() ? f : null;
    }

    // ------------------------------------------------------------------ miniatures

    private static DocumentFile thumbDir(DocumentFile dir, boolean create) {
        DocumentFile t = dir.findFile(THUMBS);
        if (t != null && t.isDirectory()) return t;
        return create ? dir.createDirectory(THUMBS) : null;
    }

    static DocumentFile thumbFile(DocumentFile dir, String id) {
        if (id == null || !VIDEO_ID.matcher(id).matches()) return null;
        DocumentFile t = thumbDir(dir, false);
        if (t == null) return null;
        DocumentFile f = t.findFile(id + ".jpg");
        return f != null && f.isFile() && f.length() > 0 ? f : null;
    }

    /**
     * Couleur de la prod, tirée de sa miniature (teinte dominante et vive) : { h, s }, ou null.
     * Calculée une fois au téléchargement puis gardée : elle ne change plus.
     */
    static JSONObject colorOf(byte[] img) {
        try {
            android.graphics.Bitmap b = android.graphics.BitmapFactory.decodeByteArray(img, 0, img.length);
            if (b == null) return null;
            android.graphics.Bitmap s = android.graphics.Bitmap.createScaledBitmap(b, 32, 18, true);
            double x = 0, y = 0, w = 0, ls = 0;
            float[] hsv = new float[3];
            for (int j = 0; j < 18; j++) {
                for (int i = 0; i < 32; i++) {
                    int px = s.getPixel(i, j);
                    android.graphics.Color.RGBToHSV((px >> 16) & 255, (px >> 8) & 255, px & 255, hsv);
                    double sat = hsv[1];
                    double val = hsv[2];
                    if (sat * val < 0.04) continue;  // gris, noir, blanc : ne compte pas
                    double wt = sat * sat * (0.3 + val);
                    x += Math.cos(Math.toRadians(hsv[0])) * wt;
                    y += Math.sin(Math.toRadians(hsv[0])) * wt;
                    w += wt;
                    ls += sat * wt;
                }
            }
            if (w < 0.5) return null;
            JSONObject o = new JSONObject();
            o.put("h", (int) Math.round((Math.toDegrees(Math.atan2(y, x)) + 360) % 360));
            o.put("s", (int) Math.round(Math.max(45, Math.min(85, ls / w * 100 + 15))));
            return o;
        } catch (Exception e) {
            return null;
        }
    }

    static JSONObject thumbColor(Context c, DocumentFile dir, String id) {
        DocumentFile f = thumbFile(dir, id);
        if (f == null) return null;
        try { return colorOf(readAll(c, f.getUri(), 400_000)); } catch (Exception e) { return null; }
    }

    /** Miniature YouTube de la vidéo (320×180), gardée dans le dossier : elle s'affiche hors connexion. */
    static boolean saveThumb(Context c, DocumentFile dir, String id) {
        if (id == null || !VIDEO_ID.matcher(id).matches() || thumbFile(dir, id) != null) return thumbFile(dir, id) != null;
        HttpURLConnection h = null;
        try {
            h = (HttpURLConnection) new URL("https://i.ytimg.com/vi/" + id + "/mqdefault.jpg").openConnection();
            h.setConnectTimeout(8000);
            h.setReadTimeout(10000);
            if (h.getResponseCode() != 200) return false;
            byte[] img;
            try (InputStream in = h.getInputStream()) { img = readStream(in, 400_000); }
            if (img.length < 500) return false;
            DocumentFile t = thumbDir(dir, true);
            if (t == null) return false;
            DocumentFile f = t.createFile("application/octet-stream", id + ".jpg");
            if (f == null) return false;
            try (OutputStream os = c.getContentResolver().openOutputStream(f.getUri(), "w")) {
                if (os == null) return false;
                os.write(img);
            }
            return true;
        } catch (Exception e) {
            return false;
        } finally {
            if (h != null) h.disconnect();
        }
    }

    /** Miniatures en « data: » (l'appli les affiche et en tire la couleur), hors connexion. */
    static JSONObject thumbs(Context c, DocumentFile dir, JSONArray ids) {
        JSONObject out = new JSONObject();
        DocumentFile t = thumbDir(dir, false);
        if (t == null) return out;
        java.util.Map<String, DocumentFile> files = new java.util.HashMap<>();
        for (DocumentFile f : t.listFiles()) if (f.getName() != null) files.put(f.getName(), f);
        for (int i = 0; i < ids.length() && i < 300; i++) {
            String id = ids.optString(i, "");
            if (!VIDEO_ID.matcher(id).matches()) continue;
            DocumentFile f = files.get(id + ".jpg");
            if (f == null) continue;
            try {
                out.put(id, "data:image/jpeg;base64," + Base64.encodeToString(readAll(c, f.getUri(), 400_000), Base64.NO_WRAP));
            } catch (Exception ignored) { }
        }
        return out;
    }

    // ------------------------------------------------------------------ lecture avec avance rapide

    /**
     * Le son AAC de YouTube est un MP4 « en morceaux » (DASH) : le lecteur d'Android ne sait pas
     * y avancer et repart de zéro. On le réécrit en MP4 normal (mêmes données, rien de réencodé).
     */
    static boolean remux(File src, File dst) {
        MediaExtractor ex = new MediaExtractor();
        MediaMuxer mux = null;
        boolean started = false;
        try {
            ex.setDataSource(src.getAbsolutePath());
            int track = -1;
            MediaFormat fmt = null;
            for (int i = 0; i < ex.getTrackCount(); i++) {
                MediaFormat f = ex.getTrackFormat(i);
                String mime = f.getString(MediaFormat.KEY_MIME);
                if (mime != null && mime.startsWith("audio/")) { track = i; fmt = f; break; }
            }
            if (track < 0) return false;
            ex.selectTrack(track);
            mux = new MediaMuxer(dst.getAbsolutePath(), MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4);
            int out = mux.addTrack(fmt);
            mux.start();
            started = true;
            ByteBuffer buf = ByteBuffer.allocate(1 << 20);
            MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
            long n = 0;
            while (true) {
                int size = ex.readSampleData(buf, 0);
                if (size < 0) break;
                info.set(0, size, ex.getSampleTime(), (ex.getSampleFlags() & MediaExtractor.SAMPLE_FLAG_SYNC) != 0 ? MediaCodec.BUFFER_FLAG_KEY_FRAME : 0);
                mux.writeSampleData(out, buf, info);
                n++;
                ex.advance();
            }
            mux.stop();
            started = false;
            return n > 100 && dst.length() > 10_000;
        } catch (Exception e) {
            return false;
        } finally {
            try { if (mux != null) { if (started) mux.stop(); mux.release(); } } catch (Exception ignored) { }
            ex.release();
        }
    }

    /** Répare un .m4a déjà téléchargé (avant la réécriture) : il devient lisible avec avance rapide. */
    static boolean fixSeek(Context c, DocumentFile dir, String name) throws Exception {
        DocumentFile f = find(dir, name);
        if (f == null || !name.toLowerCase(Locale.ROOT).endsWith(".m4a")) return false;
        File cache = new File(c.getCacheDir(), "phone");
        cache.mkdirs();
        File a = new File(cache, "fix-" + System.nanoTime() + ".m4a");
        File b = new File(cache, "fix-" + System.nanoTime() + "-ok.m4a");
        try {
            try (InputStream in = c.getContentResolver().openInputStream(f.getUri()); OutputStream os = new FileOutputStream(a)) {
                if (in == null) return false;
                copy(in, os);
            }
            if (!remux(a, b)) return false;
            try (InputStream in = new FileInputStream(b); OutputStream os = c.getContentResolver().openOutputStream(f.getUri(), "wt")) {
                if (os == null) return false;
                copy(in, os);
            }
            editMeta(c, dir, name, m -> m.put("seek", 1));
            return true;
        } finally {
            a.delete();
            b.delete();
        }
    }

    /**
     * Après la liste, en arrière-plan : miniatures manquantes (si internet) et anciens .m4a à
     * réparer (pas celui qui joue). Renvoie true si quelque chose a changé.
     */
    static boolean backfill(Context c, DocumentFile dir, String playing) {
        boolean changed = false;
        JSONObject idx = readIndex(c, dir);
        Iterator<String> it = idx.keys();
        java.util.List<String> names = new java.util.ArrayList<>();
        while (it.hasNext()) names.add(it.next());
        for (String name : names) {
            JSONObject m = idx.optJSONObject(name);
            if (m == null || find(dir, name) == null) continue;
            String id = m.optString("id", "");
            if (VIDEO_ID.matcher(id).matches() && thumbFile(dir, id) == null && saveThumb(c, dir, id)) changed = true;
            if (!m.has("color") && thumbFile(dir, id) != null) {
                JSONObject col = thumbColor(c, dir, id);
                if (col != null) {
                    try { editMeta(c, dir, name, x -> { if (!x.has("color")) x.put("color", col); }); changed = true; } catch (Exception ignored) { }
                }
            }
            if (m.optInt("seek", 0) != 1 && name.toLowerCase(Locale.ROOT).endsWith(".m4a") && !name.equals(playing)) {
                try { if (fixSeek(c, dir, name)) changed = true; } catch (Exception ignored) { }
            }
        }
        return changed;
    }

    // ------------------------------------------------------------------ téléchargement

    /** Nom sûr : pas de séparateur ni de caractère interdit, 140 caractères au plus. */
    static String safeBase(String s) {
        String t = String.valueOf(s == null ? "" : s).replaceAll("[\\\\/:*?\"<>|\\p{Cntrl}]", " ").replaceAll("\\s{2,}", " ").trim();
        t = t.replaceAll("^[.\\s]+|[.\\s]+$", "");
        if (t.length() > 140) t = t.substring(0, 140).trim();
        return t.isEmpty() ? "Prod" : t;
    }

    /**
     * Télécharge la prod (son YouTube d'origine : AAC, sinon Opus) dans le dossier, sous le nom
     * donné, avec sa miniature. Si elle y est déjà (même vidéo), rien n'est retéléchargé.
     */
    static String download(Context c, DocumentFile dir, String videoId, String wanted, JSONObject meta) throws Exception {
        JSONObject idx = readIndex(c, dir);
        Iterator<String> it = idx.keys();
        while (it.hasNext()) {
            String k = it.next();
            JSONObject m = idx.optJSONObject(k);
            if (m != null && videoId.equals(m.optString("id")) && find(dir, k) != null) return k;
        }
        List<YtStream.Pick> picks = YtStream.streams(videoId);
        File cache = new File(c.getCacheDir(), "phone");
        cache.mkdirs();
        Exception last = null;
        for (int i = 0; i < Math.min(3, picks.size()); i++) {
            YtStream.Pick p = picks.get(i);
            File raw = new File(cache, videoId + "." + p.format);
            File fixed = new File(cache, videoId + "-ok." + p.format);
            try {
                YtStream.download(p, raw);
                boolean seekable = "m4a".equals(p.format) && remux(raw, fixed);
                File src = seekable ? fixed : raw;
                String base = safeBase(wanted);
                String name = base + "." + p.format.toLowerCase(Locale.ROOT);
                for (int n = 2; dir.findFile(name) != null && n < 100; n++) name = base + " (" + n + ")." + p.format;
                // octet-stream : Android garde le nom tel quel (pas d'extension ajoutée)
                DocumentFile out = dir.createFile("application/octet-stream", name);
                if (out == null) throw new IOException("fichier impossible à créer dans « " + FOLDER + " »");
                ContentResolver cr = c.getContentResolver();
                try (InputStream in = new FileInputStream(src); OutputStream os = cr.openOutputStream(out.getUri(), "w")) {
                    if (os == null) throw new IOException("écriture refusée");
                    copy(in, os);
                }
                String got = out.getName() != null ? out.getName() : name;
                final JSONObject src0 = meta != null ? meta : new JSONObject();
                final boolean sk = seekable || !"m4a".equals(p.format);
                editMeta(c, dir, got, m -> {
                    Iterator<String> ks = src0.keys();
                    while (ks.hasNext()) { String k = ks.next(); m.put(k, src0.get(k)); }
                    m.put("id", videoId);
                    m.put("at", System.currentTimeMillis());
                    if (sk) m.put("seek", 1);
                });
                if (saveThumb(c, dir, videoId)) {
                    JSONObject col = thumbColor(c, dir, videoId);
                    if (col != null) editMeta(c, dir, got, x -> { if (!x.has("color")) x.put("color", col); });
                }
                return got;
            } catch (Exception e) {
                last = e;
            } finally {
                raw.delete();
                fixed.delete();
            }
        }
        throw last != null ? last : new IOException("aucun son");
    }

    static boolean delete(Context c, DocumentFile dir, String name) throws Exception {
        DocumentFile f = find(dir, name);
        if (f == null) return false;
        boolean ok = f.delete();
        synchronized (INDEX_LOCK) {
            JSONObject idx = readIndex(c, dir);
            JSONObject m = idx.optJSONObject(name);
            if (m != null) {
                idx.remove(name);
                writeIndex(c, dir, idx);
                // miniature retirée si plus aucune prod ne l'utilise
                String id = m.optString("id", "");
                boolean used = false;
                Iterator<String> it = idx.keys();
                while (it.hasNext()) { JSONObject o = idx.optJSONObject(it.next()); if (o != null && id.equals(o.optString("id"))) used = true; }
                DocumentFile t = used ? null : thumbFile(dir, id);
                if (t != null) t.delete();
            }
        }
        return ok;
    }

    // ------------------------------------------------------------------ outils

    private static void copy(InputStream in, OutputStream os) throws IOException {
        byte[] buf = new byte[65536];
        int n;
        while ((n = in.read(buf)) > 0) os.write(buf, 0, n);
    }

    private static byte[] readStream(InputStream in, int max) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[16384];
        int n;
        while ((n = in.read(buf)) > 0) {
            out.write(buf, 0, n);
            if (out.size() > max) throw new IOException("trop lourd");
        }
        return out.toByteArray();
    }

    private static byte[] readAll(Context c, Uri u, int max) throws IOException {
        try (InputStream in = c.getContentResolver().openInputStream(u)) {
            if (in == null) throw new IOException("illisible");
            return readStream(in, max);
        }
    }
}
