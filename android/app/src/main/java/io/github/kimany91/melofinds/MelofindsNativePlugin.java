package io.github.kimany91.melofinds;

import android.app.Activity;
import android.content.ContentResolver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.provider.DocumentsContract;
import android.provider.OpenableColumns;
import android.util.Base64;
import android.view.HapticFeedbackConstants;
import android.view.View;

import androidx.activity.result.ActivityResult;

import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.ActivityCallback;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.Locale;

/**
 * Pont entre l'app web Melofinds et Android.
 *
 * Sécurité :
 *  - un seul dossier, choisi par toi (Téléchargements par défaut), via le sélecteur
 *    d'Android : l'app ne voit rien d'autre de ton téléphone ;
 *  - suppression : seulement un fichier AUDIO placé directement dans ce dossier ;
 *  - fichiers partagés vers Melofinds : copiés dans le cache de l'app, effacés après analyse.
 */
@CapacitorPlugin(name = "MelofindsNative")
public class MelofindsNativePlugin extends Plugin {

    private static final String PREFS = "melofinds";
    private static final String KEY_TREE = "tree";
    private static final int CHUNK_MAX = 1 << 20;            // 1 Mo par lecture
    private static final long SHARED_MAX = 60L * 1024 * 1024; // fichier partagé : 60 Mo max
    private static final String[] AUDIO_EXT = { ".mp3", ".m4a", ".aac", ".wav", ".ogg", ".opus", ".flac", ".webm", ".weba" };

    // Fichiers reçus par « Partager » avant que la page soit prête
    private static final ArrayList<JSObject> pending = new ArrayList<>();
    private static MelofindsNativePlugin instance;

    @Override
    public void load() {
        instance = this;
    }

    // ------------------------------------------------------------------ dossier

    private Uri treeUri() {
        String s = getContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY_TREE, null);
        if (s == null) return null;
        Uri tree = Uri.parse(s);
        // la permission a pu être retirée dans les réglages d'Android
        for (android.content.UriPermission p : getContext().getContentResolver().getPersistedUriPermissions()) {
            if (p.getUri().equals(tree) && p.isReadPermission()) return tree;
        }
        return null;
    }

    private JSObject folderInfo() {
        JSObject o = new JSObject();
        Uri tree = treeUri();
        o.put("granted", tree != null);
        if (tree != null) {
            String id = DocumentsContract.getTreeDocumentId(tree);
            o.put("name", id.contains(":") ? id.substring(id.indexOf(':') + 1) : id);
        }
        return o;
    }

    @PluginMethod
    public void folder(PluginCall call) {
        call.resolve(folderInfo());
    }

    @PluginMethod
    public void pickFolder(PluginCall call) {
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION | Intent.FLAG_GRANT_PREFIX_URI_PERMISSION);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            i.putExtra(DocumentsContract.EXTRA_INITIAL_URI,
                    DocumentsContract.buildDocumentUri("com.android.externalstorage.documents", "primary:Download"));
        }
        startActivityForResult(call, i, "folderPicked");
    }

    @ActivityCallback
    private void folderPicked(PluginCall call, ActivityResult result) {
        if (call == null) return;
        if (result.getResultCode() != Activity.RESULT_OK || result.getData() == null || result.getData().getData() == null) {
            call.resolve(folderInfo());
            return;
        }
        Uri tree = result.getData().getData();
        try {
            getContext().getContentResolver().takePersistableUriPermission(tree,
                    Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
        } catch (SecurityException e) {
            call.reject("Autorisation refusée par Android");
            return;
        }
        getContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(KEY_TREE, tree.toString()).apply();
        call.resolve(folderInfo());
    }

    private static boolean isAudio(String name, String mime) {
        String n = name == null ? "" : name.toLowerCase(Locale.ROOT);
        for (String e : AUDIO_EXT) if (n.endsWith(e)) return true;
        return mime != null && mime.startsWith("audio/");
    }

    /** Fichiers audio du dossier (pas les sous-dossiers), modifiés après `since` (ms). */
    @PluginMethod
    public void listAudio(PluginCall call) {
        Uri tree = treeUri();
        if (tree == null) { call.reject("Dossier pas autorisé"); return; }
        long since = call.getLong("since", 0L);
        Uri children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, DocumentsContract.getTreeDocumentId(tree));
        String[] cols = { DocumentsContract.Document.COLUMN_DOCUMENT_ID, DocumentsContract.Document.COLUMN_DISPLAY_NAME,
                DocumentsContract.Document.COLUMN_SIZE, DocumentsContract.Document.COLUMN_LAST_MODIFIED,
                DocumentsContract.Document.COLUMN_MIME_TYPE };
        JSArray out = new JSArray();
        try (Cursor c = getContext().getContentResolver().query(children, cols, null, null, null)) {
            while (c != null && c.moveToNext()) {
                String id = c.getString(0);
                String name = c.getString(1);
                long size = c.isNull(2) ? 0 : c.getLong(2);
                long modified = c.isNull(3) ? 0 : c.getLong(3);
                String mime = c.getString(4);
                if (DocumentsContract.Document.MIME_TYPE_DIR.equals(mime) || !isAudio(name, mime) || modified < since) continue;
                JSObject o = new JSObject();
                o.put("uri", DocumentsContract.buildDocumentUriUsingTree(tree, id).toString());
                o.put("name", name);
                o.put("size", size);
                o.put("modified", modified);
                out.put(o);
            }
        } catch (Exception e) {
            call.reject("Lecture du dossier impossible : " + e.getMessage());
            return;
        }
        JSObject r = new JSObject();
        r.put("files", out);
        call.resolve(r);
    }

    // ------------------------------------------------------------------ lecture

    private File sharedDir() {
        File d = new File(getContext().getCacheDir(), "shared");
        if (!d.exists()) d.mkdirs();
        return d;
    }

    private boolean inSharedDir(File f) {
        try {
            return f.getCanonicalPath().startsWith(sharedDir().getCanonicalPath() + File.separator);
        } catch (IOException e) {
            return false;
        }
    }

    private InputStream open(String ref) throws IOException {
        if (ref.startsWith("content://")) {
            InputStream in = getContext().getContentResolver().openInputStream(Uri.parse(ref));
            if (in == null) throw new IOException("illisible");
            return in;
        }
        File f = new File(ref);
        if (!inSharedDir(f)) throw new IOException("fichier hors de l'app");
        return new FileInputStream(f);
    }

    /** Morceau d'un fichier, en base64 : { data, eof }. */
    @PluginMethod
    public void readChunk(PluginCall call) {
        String ref = call.getString("uri", "");
        long offset = Math.max(0, call.getLong("offset", 0L));
        int length = Math.min(CHUNK_MAX, Math.max(1, call.getInt("length", CHUNK_MAX)));
        try (InputStream in = open(ref)) {
            long skipped = 0;
            while (skipped < offset) {
                long n = in.skip(offset - skipped);
                if (n <= 0) break;
                skipped += n;
            }
            byte[] buf = new byte[length];
            int got = 0;
            while (got < length) {
                int n = in.read(buf, got, length - got);
                if (n < 0) break;
                got += n;
            }
            JSObject r = new JSObject();
            r.put("data", Base64.encodeToString(buf, 0, got, Base64.NO_WRAP));
            r.put("eof", got < length);
            call.resolve(r);
        } catch (Exception e) {
            call.reject("Lecture impossible : " + e.getMessage());
        }
    }

    // ------------------------------------------------------------------ suppression

    /** Supprime un fichier AUDIO placé directement dans le dossier autorisé, rien d'autre. */
    @PluginMethod
    public void deleteFile(PluginCall call) {
        Uri tree = treeUri();
        String ref = call.getString("uri", "");
        if (tree == null || !ref.startsWith("content://")) { call.reject("Refusé"); return; }
        Uri doc = Uri.parse(ref);
        try {
            String treeId = DocumentsContract.getTreeDocumentId(tree);
            String docId = DocumentsContract.getDocumentId(doc);
            String parent = docId.contains("/") ? docId.substring(0, docId.lastIndexOf('/')) : "";
            boolean sameRoot = tree.getAuthority() != null && tree.getAuthority().equals(doc.getAuthority());
            if (!sameRoot || !parent.equals(treeId)) { call.reject("Fichier hors du dossier autorisé"); return; }
            String name = null;
            String mime = null;
            try (Cursor c = getContext().getContentResolver().query(doc, new String[] {
                    DocumentsContract.Document.COLUMN_DISPLAY_NAME, DocumentsContract.Document.COLUMN_MIME_TYPE }, null, null, null)) {
                if (c != null && c.moveToFirst()) { name = c.getString(0); mime = c.getString(1); }
            }
            if (!isAudio(name, mime)) { call.reject("Pas un fichier audio"); return; }
            boolean ok = DocumentsContract.deleteDocument(getContext().getContentResolver(), doc);
            JSObject r = new JSObject();
            r.put("ok", ok);
            r.put("name", name);
            call.resolve(r);
        } catch (Exception e) {
            call.reject("Suppression impossible : " + e.getMessage());
        }
    }

    // ------------------------------------------------------------------ partage

    /** Appelé par MainActivity quand on partage un son vers Melofinds. */
    static void receive(Context ctx, Intent intent) {
        if (intent == null) return;
        String action = intent.getAction();
        if (!Intent.ACTION_SEND.equals(action) && !Intent.ACTION_SEND_MULTIPLE.equals(action)) return;
        ArrayList<JSObject> got = new ArrayList<>();
        ArrayList<Uri> uris = new ArrayList<>();
        if (Intent.ACTION_SEND.equals(action)) {
            Uri u = intent.getParcelableExtra(Intent.EXTRA_STREAM);
            if (u != null) uris.add(u);
        } else {
            ArrayList<Uri> list = intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM);
            if (list != null) uris.addAll(list);
        }
        for (Uri u : uris) {
            JSObject o = copyShared(ctx, u);
            if (o != null) got.add(o);
        }
        if (got.isEmpty()) return;
        synchronized (pending) { pending.addAll(got); }
        MelofindsNativePlugin p = instance;
        if (p != null) {
            JSObject ev = new JSObject();
            ev.put("count", got.size());
            p.notifyListeners("shared", ev, true);
        }
    }

    private static JSObject copyShared(Context ctx, Uri u) {
        ContentResolver cr = ctx.getContentResolver();
        String name = "son";
        long size = -1;
        try (Cursor c = cr.query(u, new String[] { OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE }, null, null, null)) {
            if (c != null && c.moveToFirst()) {
                if (!c.isNull(0)) name = c.getString(0);
                if (!c.isNull(1)) size = c.getLong(1);
            }
        } catch (Exception ignored) { }
        String mime = cr.getType(u);
        if (!isAudio(name, mime) || size > SHARED_MAX) return null;
        File dir = new File(ctx.getCacheDir(), "shared");
        if (!dir.exists()) dir.mkdirs();
        String safe = name.replaceAll("[^\\w .()\\[\\]-]", "_");
        File dest = new File(dir, System.currentTimeMillis() + "-" + safe);
        long total = 0;
        try (InputStream in = cr.openInputStream(u); OutputStream out = new FileOutputStream(dest)) {
            if (in == null) return null;
            byte[] buf = new byte[65536];
            int n;
            while ((n = in.read(buf)) > 0) {
                total += n;
                if (total > SHARED_MAX) throw new IOException("trop lourd");
                out.write(buf, 0, n);
            }
        } catch (Exception e) {
            dest.delete();
            return null;
        }
        JSObject o = new JSObject();
        o.put("path", dest.getAbsolutePath());
        o.put("name", name);
        o.put("size", total);
        return o;
    }

    /** Ce qui a été partagé vers Melofinds et pas encore traité (vidé à la lecture). */
    @PluginMethod
    public void takeShared(PluginCall call) {
        JSArray arr = new JSArray();
        synchronized (pending) {
            for (JSObject o : pending) arr.put(o);
            pending.clear();
        }
        JSObject r = new JSObject();
        r.put("items", arr);
        call.resolve(r);
    }

    /** Efface la copie d'un fichier partagé (seulement dans le cache de l'app). */
    @PluginMethod
    public void dropShared(PluginCall call) {
        File f = new File(call.getString("path", ""));
        JSObject r = new JSObject();
        r.put("ok", inSharedDir(f) && f.delete());
        call.resolve(r);
    }

    // ------------------------------------------------------------------ divers

    /** Léger retour haptique (suit le réglage « vibrations au toucher » du téléphone). */
    @PluginMethod
    public void haptic(PluginCall call) {
        String kind = call.getString("kind", "tap");
        Activity a = getActivity();
        if (a == null) { call.resolve(); return; }
        a.runOnUiThread(() -> {
            View v = bridge.getWebView();
            int c;
            if ("success".equals(kind)) c = Build.VERSION.SDK_INT >= Build.VERSION_CODES.R ? HapticFeedbackConstants.CONFIRM : HapticFeedbackConstants.LONG_PRESS;
            else if ("warn".equals(kind)) c = Build.VERSION.SDK_INT >= Build.VERSION_CODES.R ? HapticFeedbackConstants.REJECT : HapticFeedbackConstants.LONG_PRESS;
            else c = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1 ? HapticFeedbackConstants.KEYBOARD_PRESS : HapticFeedbackConstants.KEYBOARD_TAP;
            if (v != null) v.performHapticFeedback(c);
            call.resolve();
        });
    }

    /** Ouvre un lien (noTube, YouTube…) dans le navigateur ou l'appli du téléphone. */
    @PluginMethod
    public void openUrl(PluginCall call) {
        String url = call.getString("url", "");
        if (!url.startsWith("https://") && !url.startsWith("http://")) { call.reject("Lien refusé"); return; }
        try {
            Intent i = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            getContext().startActivity(i);
            call.resolve();
        } catch (Exception e) {
            call.reject("Aucune appli pour ouvrir ce lien");
        }
    }

    @PluginMethod
    public void info(PluginCall call) {
        JSObject r = new JSObject();
        r.put("version", BuildConfig.VERSION_NAME);
        r.put("android", Build.VERSION.SDK_INT);
        call.resolve(r);
    }
}
