package io.github.kimany91.melofinds;

import android.Manifest;
import android.app.Activity;
import android.app.PendingIntent;
import android.app.RecoverableSecurityException;
import android.content.ContentResolver;
import android.content.ContentUris;
import android.content.Context;
import android.content.Intent;
import android.content.IntentSender;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.provider.MediaStore;
import android.provider.OpenableColumns;
import android.provider.Settings;
import android.util.Base64;
import android.view.HapticFeedbackConstants;
import android.view.View;

import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PermissionState;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import org.schabi.newpipe.extractor.exceptions.AgeRestrictedContentException;
import org.schabi.newpipe.extractor.exceptions.ContentNotAvailableException;
import org.schabi.newpipe.extractor.exceptions.ReCaptchaException;
import org.schabi.newpipe.extractor.exceptions.SignInConfirmNotBotException;

/**
 * Pont entre l'app web Melofinds et Android.
 *
 * Sécurité :
 *  - sons : autorisation « Musique et audio » d'Android ; l'app ne regarde que les sons
 *    rangés dans Téléchargements (Download/), ajoutés depuis que la prod attend son MP3 ;
 *  - suppression : seulement un son de Téléchargements, via la demande officielle
 *    d'Android (confirmation, sauf si « Gestion des fichiers multimédias » est autorisée) ;
 *  - fichiers partagés vers Melofinds : copiés dans le cache de l'app, effacés après analyse ;
 *  - son d'une vidéo YouTube (ytAudio) : récupéré directement, gardé dans le cache de l'app
 *    le temps de l'analyse puis effacé ; jamais rangé dans les fichiers de l'utilisateur.
 */
@CapacitorPlugin(
    name = "MelofindsNative",
    permissions = {
        @Permission(alias = "audio", strings = { Manifest.permission.READ_MEDIA_AUDIO }),
        @Permission(alias = "storage", strings = { Manifest.permission.READ_EXTERNAL_STORAGE }),
        @Permission(alias = "write", strings = { Manifest.permission.WRITE_EXTERNAL_STORAGE })
    }
)
public class MelofindsNativePlugin extends Plugin {

    static final int REQ_DELETE = 7311;
    private static final int CHUNK_MAX = 1 << 20;            // 1 Mo par lecture
    private static final long SHARED_MAX = 60L * 1024 * 1024; // fichier partagé : 60 Mo max
    private static final String[] AUDIO_EXT = { ".mp3", ".m4a", ".aac", ".wav", ".ogg", ".opus", ".flac", ".webm", ".weba" };

    // Fichiers reçus par « Partager » avant que la page soit prête
    private static final ArrayList<JSObject> pending = new ArrayList<>();
    private static MelofindsNativePlugin instance;
    private String deleteCallId = null;

    @Override
    public void load() {
        instance = this;
    }

    // ------------------------------------------------------------------ accès aux sons

    private String readAlias() {
        return Build.VERSION.SDK_INT >= 33 ? "audio" : "storage";
    }

    private boolean canRead() {
        return getPermissionState(readAlias()) == PermissionState.GRANTED;
    }

    private boolean canManageMedia() {
        return Build.VERSION.SDK_INT >= 31 && MediaStore.canManageMedia(getContext());
    }

    private JSObject folderInfo() {
        JSObject o = new JSObject();
        o.put("granted", canRead());
        o.put("name", "Téléchargements");
        o.put("manageMedia", canManageMedia());
        o.put("manageMediaAvailable", Build.VERSION.SDK_INT >= 31);
        return o;
    }

    @PluginMethod
    public void folder(PluginCall call) {
        call.resolve(folderInfo());
    }

    /** Demande « Musique et audio » (Android 13+) ou « Stockage » (avant). */
    @PluginMethod
    public void pickFolder(PluginCall call) {
        if (canRead()) { call.resolve(folderInfo()); return; }
        requestPermissionForAlias(readAlias(), call, "readPermCallback");
    }

    @PermissionCallback
    private void readPermCallback(PluginCall call) {
        call.resolve(folderInfo());
    }

    /** Ouvre le réglage « Gestion des fichiers multimédias » (suppression sans confirmation). */
    @PluginMethod
    public void openManageMedia(PluginCall call) {
        if (Build.VERSION.SDK_INT < 31) { call.resolve(folderInfo()); return; }
        try {
            Intent i = new Intent(Settings.ACTION_REQUEST_MANAGE_MEDIA, Uri.parse("package:" + getContext().getPackageName()));
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            getContext().startActivity(i);
        } catch (Exception e) {
            call.reject("Réglage introuvable sur ce téléphone");
            return;
        }
        call.resolve(folderInfo());
    }

    private static boolean isAudio(String name, String mime) {
        String n = name == null ? "" : name.toLowerCase(Locale.ROOT);
        for (String e : AUDIO_EXT) if (n.endsWith(e)) return true;
        return mime != null && mime.startsWith("audio/");
    }

    private static Uri audioCollection() {
        return Build.VERSION.SDK_INT >= 29 ? MediaStore.Audio.Media.getContentUri(MediaStore.VOLUME_EXTERNAL)
                : MediaStore.Audio.Media.EXTERNAL_CONTENT_URI;
    }

    /** Le son est-il rangé directement dans Téléchargements ? (ses infos, ou null) */
    private String[] downloadAudio(Uri uri) {
        String[] cols = Build.VERSION.SDK_INT >= 29
                ? new String[] { MediaStore.MediaColumns.DISPLAY_NAME, MediaStore.MediaColumns.MIME_TYPE, MediaStore.MediaColumns.RELATIVE_PATH }
                : new String[] { MediaStore.MediaColumns.DISPLAY_NAME, MediaStore.MediaColumns.MIME_TYPE, MediaStore.MediaColumns.DATA };
        try (Cursor c = getContext().getContentResolver().query(uri, cols, null, null, null)) {
            if (c == null || !c.moveToFirst()) return null;
            String name = c.getString(0);
            String mime = c.getString(1);
            String where = c.getString(2) == null ? "" : c.getString(2);
            boolean inDownload = Build.VERSION.SDK_INT >= 29
                    ? where.equalsIgnoreCase("Download/")
                    : where.toLowerCase(Locale.ROOT).matches(".*/download/[^/]+$");
            if (!inDownload || !isAudio(name, mime)) return null;
            return new String[] { name, mime };
        } catch (Exception e) {
            return null;
        }
    }

    /** Sons de Téléchargements ajoutés après `since` (ms). */
    @PluginMethod
    public void listAudio(PluginCall call) {
        if (!canRead()) { call.reject("Accès aux sons pas autorisé"); return; }
        long sinceSec = call.getLong("since", 0L) / 1000L;
        String[] cols = { MediaStore.MediaColumns._ID, MediaStore.MediaColumns.DISPLAY_NAME, MediaStore.MediaColumns.SIZE,
                MediaStore.MediaColumns.DATE_ADDED, MediaStore.MediaColumns.DATE_MODIFIED, MediaStore.MediaColumns.MIME_TYPE };
        String sel = Build.VERSION.SDK_INT >= 29
                ? MediaStore.MediaColumns.RELATIVE_PATH + "=? AND " + MediaStore.MediaColumns.DATE_ADDED + ">=?"
                : MediaStore.MediaColumns.DATA + " LIKE ? AND " + MediaStore.MediaColumns.DATE_ADDED + ">=?";
        String[] args = { Build.VERSION.SDK_INT >= 29 ? "Download/" : "%/Download/%", String.valueOf(sinceSec) };
        Uri coll = audioCollection();
        JSArray out = new JSArray();
        try (Cursor c = getContext().getContentResolver().query(coll, cols, sel, args, MediaStore.MediaColumns.DATE_ADDED + " ASC")) {
            while (c != null && c.moveToNext()) {
                String name = c.getString(1);
                if (!isAudio(name, c.getString(5))) continue;
                JSObject o = new JSObject();
                o.put("uri", ContentUris.withAppendedId(coll, c.getLong(0)).toString());
                o.put("name", name);
                o.put("size", c.isNull(2) ? 0 : c.getLong(2));
                long added = c.isNull(3) ? 0 : c.getLong(3);
                long modified = c.isNull(4) ? 0 : c.getLong(4);
                o.put("modified", Math.max(added, modified) * 1000L);
                out.put(o);
            }
        } catch (Exception e) {
            call.reject("Lecture des sons impossible : " + e.getMessage());
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
            Uri u = Uri.parse(ref);
            if (downloadAudio(u) == null) throw new IOException("pas un son de Téléchargements");
            InputStream in = getContext().getContentResolver().openInputStream(u);
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

    /**
     * Supprime UN son rangé directement dans Téléchargements, par la demande officielle
     * d'Android (Android 11+ : confirmation, sauf « Gestion des fichiers multimédias »).
     */
    @PluginMethod
    public void deleteFile(PluginCall call) {
        String ref = call.getString("uri", "");
        if (!ref.startsWith("content://media/")) { call.reject("Refusé"); return; }
        Uri uri = Uri.parse(ref);
        String[] info = downloadAudio(uri);
        if (info == null) { call.reject("Pas un son de Téléchargements"); return; }
        ContentResolver cr = getContext().getContentResolver();
        try {
            if (Build.VERSION.SDK_INT >= 30) {
                PendingIntent pi = MediaStore.createDeleteRequest(cr, Collections.singletonList(uri));
                askDelete(call, pi.getIntentSender());
                return;
            }
            if (Build.VERSION.SDK_INT <= 28 && getPermissionState("write") != PermissionState.GRANTED) {
                requestPermissionForAlias("write", call, "writePermCallback");
                return;
            }
            int n = cr.delete(uri, null, null);
            resolveDelete(call, n > 0, info[0]);
        } catch (RecoverableSecurityException e) { // Android 10
            askDelete(call, e.getUserAction().getActionIntent().getIntentSender());
        } catch (Exception e) {
            call.reject("Suppression impossible : " + e.getMessage());
        }
    }

    @PermissionCallback
    private void writePermCallback(PluginCall call) {
        if (getPermissionState("write") != PermissionState.GRANTED) { call.reject("Suppression pas autorisée"); return; }
        deleteFile(call);
    }

    private void askDelete(PluginCall call, IntentSender sender) {
        call.setKeepAlive(true);
        getBridge().saveCall(call);
        deleteCallId = call.getCallbackId();
        try {
            getActivity().startIntentSenderForResult(sender, REQ_DELETE, null, 0, 0, 0);
        } catch (Exception e) {
            deleteCallId = null;
            getBridge().releaseCall(call);
            call.reject("Suppression impossible : " + e.getMessage());
        }
    }

    private static void resolveDelete(PluginCall call, boolean ok, String name) {
        JSObject r = new JSObject();
        r.put("ok", ok);
        if (name != null) r.put("name", name);
        call.resolve(r);
    }

    /** Réponse d'Android à la demande de suppression (relayée par MainActivity). */
    static void onDeleteResult(int resultCode) {
        MelofindsNativePlugin p = instance;
        if (p == null || p.deleteCallId == null) return;
        PluginCall call = p.getBridge().getSavedCall(p.deleteCallId);
        p.deleteCallId = null;
        if (call == null) return;
        resolveDelete(call, resultCode == Activity.RESULT_OK, null);
        p.getBridge().releaseCall(call);
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
        JSArray features = new JSArray();
        features.put("ytAudio");
        r.put("features", features);
        call.resolve(r);
    }

    // ------------------------------------------------------------------ son YouTube direct

    // une prod à la fois : les demandes suivantes attendent leur tour
    private static final ExecutorService YT = Executors.newSingleThreadExecutor();

    /**
     * Son d'une vidéo YouTube pour l'analyse (BPM / clé), sans site intermédiaire :
     * { path, size, rate, seconds, duration, format, kbps, ms }. Le WAV (mono, milieu du
     * morceau) est dans le cache de l'app ; l'app web le lit puis l'efface (dropShared).
     */
    @PluginMethod
    public void ytAudio(PluginCall call) {
        String id = call.getString("id", "");
        double window = Math.max(20, Math.min(90, call.getDouble("seconds", 60.0)));
        if (!YtAudio.VIDEO_ID.matcher(id).matches()) { call.reject("Vidéo invalide"); return; }
        YT.execute(() -> {
            long t0 = System.currentTimeMillis();
            File dir = sharedDir();
            cleanOld(dir);
            try {
                ytStep(id, "find");
                List<YtAudio.Pick> picks = YtAudio.streams(id);
                long t1 = System.currentTimeMillis();
                Exception last = null;
                for (int i = 0; i < Math.min(3, picks.size()); i++) {
                    YtAudio.Pick p = picks.get(i);
                    File raw = new File(dir, "yt-" + id + "." + p.format);
                    File wav = new File(dir, "yt-" + id + ".wav");
                    try {
                        ytStep(id, "download");
                        long size = YtAudio.download(p, raw);
                        long t2 = System.currentTimeMillis();
                        ytStep(id, "decode");
                        AudioPcm.Out o = AudioPcm.toWav(raw, wav, window);
                        long t3 = System.currentTimeMillis();
                        JSObject r = new JSObject();
                        r.put("path", wav.getAbsolutePath());
                        r.put("size", wav.length());
                        r.put("rate", o.rate);
                        r.put("seconds", o.seconds);
                        r.put("duration", o.duration);
                        r.put("format", p.format);
                        r.put("kbps", p.bitrate / 1000);
                        r.put("bytes", size);
                        JSObject ms = new JSObject();
                        ms.put("find", t1 - t0);
                        ms.put("download", t2 - t1);
                        ms.put("decode", t3 - t2);
                        ms.put("total", t3 - t0);
                        r.put("ms", ms);
                        call.resolve(r);
                        return;
                    } catch (Exception e) {
                        last = e;
                        wav.delete();
                    } finally {
                        raw.delete();
                    }
                }
                throw last != null ? last : new IOException("aucun son lisible");
            } catch (ReCaptchaException e) {
                call.reject("YouTube demande une vérification (trop de demandes depuis ce réseau). Réessaie dans un moment.", "captcha");
            } catch (SignInConfirmNotBotException e) {
                call.reject("YouTube demande de confirmer que tu n'es pas un robot sur ce réseau (souvent un VPN ou un Wi-Fi public). Essaie avec une autre connexion (4G ou Wi-Fi de la maison).", "bot");
            } catch (AgeRestrictedContentException e) {
                call.reject("Vidéo réservée aux adultes : YouTube ne donne pas le son sans compte.", "age");
            } catch (ContentNotAvailableException e) {
                call.reject("Vidéo indisponible (supprimée, privée ou bloquée).", "gone");
            } catch (Throwable e) {
                String m = e.getMessage();
                call.reject("Son introuvable" + (m != null && m.length() < 160 ? " : " + m : ""), "fail");
            }
        });
    }

    private void ytStep(String id, String step) {
        JSObject o = new JSObject();
        o.put("id", id);
        o.put("step", step);
        notifyListeners("ytProgress", o);
    }

    // restes d'une analyse interrompue (plus de 10 min)
    private static void cleanOld(File dir) {
        File[] files = dir.listFiles();
        if (files == null) return;
        long old = System.currentTimeMillis() - 10 * 60 * 1000;
        for (File f : files) if (f.getName().startsWith("yt-") && f.lastModified() < old) f.delete();
    }
}
