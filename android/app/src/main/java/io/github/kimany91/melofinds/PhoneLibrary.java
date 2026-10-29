package io.github.kimany91.melofinds;

import android.content.ContentResolver;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.UriPermission;
import android.net.Uri;

import androidx.documentfile.provider.DocumentFile;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Locale;
import java.util.regex.Pattern;

/**
 * Les prods téléchargées sur le téléphone, dans le dossier « Melofinds Instru » (Musique) :
 * un vrai dossier du téléphone, gardé si l'appli est désinstallée. L'appli n'a accès qu'au
 * dossier que tu lui as donné (sélecteur d'Android), à rien d'autre ; elle n'y écrit que des
 * sons (.m4a / .webm) et son index (.melofinds.json).
 */
final class PhoneLibrary {

    static final String FOLDER = "Melofinds Instru";
    static final String INDEX = ".melofinds.json";
    /** Sons lus dans le dossier (ceux que Melofinds y met, et ceux que tu y ajoutes). */
    static final Pattern AUDIO = Pattern.compile("(?i).+\\.(m4a|webm|mp3|wav|ogg|opus|aac|flac)$");
    /** Ce que Melofinds écrit lui-même. */
    static final Pattern OWN = Pattern.compile("(?i).+\\.(m4a|webm)$");
    private static final String PREFS = "melofinds_phone";
    private static final String KEY_TREE = "tree";

    private PhoneLibrary() { }

    // ------------------------------------------------------------------ dossier

    static void saveTree(Context c, Uri tree) {
        c.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(KEY_TREE, tree.toString()).apply();
    }

    private static Uri savedTree(Context c) {
        String s = c.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY_TREE, null);
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

    // ------------------------------------------------------------------ index (lien, titre, clé…)

    static JSONObject readIndex(Context c, DocumentFile dir) {
        DocumentFile f = dir.findFile(INDEX);
        if (f == null || !f.isFile()) return new JSONObject();
        try (InputStream in = c.getContentResolver().openInputStream(f.getUri())) {
            if (in == null) return new JSONObject();
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[16384];
            int n;
            while ((n = in.read(buf)) > 0) {
                out.write(buf, 0, n);
                if (out.size() > 4_000_000) break;
            }
            return new JSONObject(new String(out.toByteArray(), StandardCharsets.UTF_8));
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
     * donné. Si elle y est déjà (même vidéo), rien n'est retéléchargé. Renvoie le nom du fichier.
     */
    static String download(Context c, DocumentFile dir, String videoId, String wanted, JSONObject meta) throws Exception {
        JSONObject idx = readIndex(c, dir);
        java.util.Iterator<String> it = idx.keys();
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
            try {
                YtStream.download(p, raw);
                String base = safeBase(wanted);
                String name = base + "." + p.format.toLowerCase(Locale.ROOT);
                for (int n = 2; dir.findFile(name) != null && n < 100; n++) name = base + " (" + n + ")." + p.format;
                // octet-stream : Android garde le nom tel quel (pas d'extension ajoutée)
                DocumentFile out = dir.createFile("application/octet-stream", name);
                if (out == null) throw new IOException("fichier impossible à créer dans « " + FOLDER + " »");
                ContentResolver cr = c.getContentResolver();
                try (InputStream in = new FileInputStream(raw); OutputStream os = cr.openOutputStream(out.getUri(), "w")) {
                    if (os == null) throw new IOException("écriture refusée");
                    byte[] buf = new byte[65536];
                    int n;
                    while ((n = in.read(buf)) > 0) os.write(buf, 0, n);
                }
                String got = out.getName() != null ? out.getName() : name;
                JSONObject m = meta != null ? meta : new JSONObject();
                m.put("id", videoId);
                m.put("at", System.currentTimeMillis());
                idx.put(got, m);
                writeIndex(c, dir, idx);
                return got;
            } catch (Exception e) {
                last = e;
            } finally {
                raw.delete();
            }
        }
        throw last != null ? last : new IOException("aucun son");
    }

    static boolean delete(Context c, DocumentFile dir, String name) throws Exception {
        DocumentFile f = find(dir, name);
        if (f == null) return false;
        boolean ok = f.delete();
        JSONObject idx = readIndex(c, dir);
        if (idx.has(name)) {
            idx.remove(name);
            writeIndex(c, dir, idx);
        }
        return ok;
    }
}
