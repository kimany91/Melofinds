package io.github.kimany91.melofinds;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.view.HapticFeedbackConstants;
import android.view.View;

import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.google.mlkit.vision.barcode.common.Barcode;
import com.google.mlkit.vision.codescanner.GmsBarcodeScanner;
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions;
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning;

import android.os.Environment;
import android.provider.DocumentsContract;

import androidx.activity.result.ActivityResult;
import androidx.documentfile.provider.DocumentFile;

import com.getcapacitor.annotation.ActivityCallback;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Pont entre l'app web Melofinds et Android : retour haptique, liens, clé et BPM par l'outil
 * Analyzer de Tunebat (la prod est téléchargée dans le cache de l'app puis effacée),
 * descriptions complètes des vidéos, scanner du QR code de Melofinds PC, « déjà posé dessus »
 * (recherche YouTube / SoundCloud + comparaison du son). Aucun accès aux fichiers du téléphone.
 */
@CapacitorPlugin(name = "MelofindsNative")
public class MelofindsNativePlugin extends Plugin {

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

    /** Ouvre un lien (YouTube, Tunebat…) dans le navigateur ou l'appli du téléphone. */
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
        features.put("ytDesc");
        features.put("scanQr");
        features.put("tbAnalyzer");
        features.put("usedBy");
        features.put("ytPlaylist");
        features.put("phone");
        r.put("features", features);
        call.resolve(r);
    }

    // ------------------------------------------------------------------ Tunebat Analyzer

    /**
     * Clé et BPM par l'outil Analyzer de Tunebat : la prod est téléchargée, donnée à la page
     * tunebat.com/Analyzer (fenêtre visible), puis effacée. { key, bpm, camelot, row }.
     */
    @PluginMethod
    public void tunebatAnalyze(PluginCall call) {
        String id = call.getString("id", "");
        if (!YtStream.VIDEO_ID.matcher(id).matches()) { call.reject("Vidéo invalide"); return; }
        Activity a = getActivity();
        if (a == null) { call.reject("Appli pas prête"); return; }
        if (TunebatActivity.pending != null) TunebatActivity.pending.reject("Remplacée", "cancel");
        TunebatActivity.pending = call;
        Intent i = new Intent(a, TunebatActivity.class);
        i.putExtra("id", id);
        a.startActivity(i);
    }

    // ------------------------------------------------------------------ QR code du PC

    /**
     * Scanne un QR code avec le scanner de Google (services Google Play) : pas besoin de
     * donner l'accès à l'appareil photo à Melofinds. Renvoie { text }.
     */
    @PluginMethod
    public void scanQr(PluginCall call) {
        Activity a = getActivity();
        if (a == null) { call.reject("Appli pas prête", "fail"); return; }
        GmsBarcodeScannerOptions opts = new GmsBarcodeScannerOptions.Builder()
            .setBarcodeFormats(Barcode.FORMAT_QR_CODE)
            .build();
        GmsBarcodeScanner scanner = GmsBarcodeScanning.getClient(a, opts);
        scanner.startScan()
            .addOnSuccessListener(b -> {
                JSObject r = new JSObject();
                String raw = b.getRawValue();
                r.put("text", raw == null ? "" : raw.length() > 500 ? raw.substring(0, 500) : raw);
                call.resolve(r);
            })
            .addOnCanceledListener(() -> call.reject("Annulé", "cancel"))
            .addOnFailureListener(e -> call.reject("Scanner indisponible : " + e.getMessage(), "fail"));
    }

    // descriptions complètes : 6 à la fois
    private static final ExecutorService DESC = Executors.newFixedThreadPool(6);

    /** Descriptions complètes de vidéos YouTube : { d: { id: texte } } (60 au plus). */
    @PluginMethod
    public void ytDescriptions(PluginCall call) {
        JSArray arr = call.getArray("ids", new JSArray());
        List<String> ids = new ArrayList<>();
        for (int i = 0; i < arr.length() && ids.size() < 60; i++) {
            String id = arr.optString(i, "");
            if (YtDescription.VIDEO_ID.matcher(id).matches() && !ids.contains(id)) ids.add(id);
        }
        new Thread(() -> {
            JSObject d = new JSObject();
            List<java.util.concurrent.Future<String>> jobs = new ArrayList<>();
            for (String id : ids) jobs.add(DESC.submit(() -> YtDescription.description(id)));
            for (int i = 0; i < ids.size(); i++) {
                try {
                    String t = jobs.get(i).get(40, java.util.concurrent.TimeUnit.SECONDS);
                    if (t != null) d.put(ids.get(i), t);
                } catch (Exception ignored) { }
            }
            JSObject r = new JSObject();
            r.put("d", d);
            call.resolve(r);
        }).start();
    }

    // ------------------------------------------------------------------ déjà posé dessus

    private static final ExecutorService SEARCH = Executors.newFixedThreadPool(4);
    // 2 comparaisons à la fois : chaque son est téléchargé puis décodé
    private static final ExecutorService MATCH = Executors.newFixedThreadPool(2);
    private static final Object PROD_LOCK = new Object();
    private static String prodId = null;
    private static SoundPrint prodPrint = null;

    /**
     * Cherche les morceaux qui citent la prod : { queries: [...] (4 au plus) } →
     * { items: [{ service, id, url, title, uploader, uploaderUrl, duration, views, thumb }], errors }.
     */
    @PluginMethod
    public void usedBySearch(PluginCall call) {
        JSArray arr = call.getArray("queries", new JSArray());
        List<String> qs = new ArrayList<>();
        for (int i = 0; i < arr.length() && qs.size() < 4; i++) {
            String q = arr.optString(i, "").trim();
            if (q.length() >= 2 && q.length() <= 120 && !qs.contains(q)) qs.add(q);
        }
        boolean sc = Boolean.TRUE.equals(call.getBoolean("sc", true));
        new Thread(() -> {
            List<String> jobsWhat = new ArrayList<>();
            List<java.util.concurrent.Future<List<UsedBy.Hit>>> jobs = new ArrayList<>();
            for (String q : qs) {
                jobsWhat.add("yt");
                jobs.add(SEARCH.submit(() -> UsedBy.search("yt", q, 20)));
                if (sc) {
                    jobsWhat.add("sc");
                    jobs.add(SEARCH.submit(() -> UsedBy.search("sc", q, 10)));
                }
            }
            JSArray items = new JSArray();
            JSObject errors = new JSObject();
            java.util.Set<String> seen = new java.util.HashSet<>();
            for (int i = 0; i < jobs.size(); i++) {
                try {
                    for (UsedBy.Hit h : jobs.get(i).get(30, java.util.concurrent.TimeUnit.SECONDS)) {
                        String k = h.service + ":" + (h.id != null ? h.id : h.url);
                        if (!seen.add(k)) continue;
                        JSObject o = new JSObject();
                        o.put("service", h.service);
                        if (h.id != null) o.put("id", h.id);
                        o.put("url", h.url);
                        o.put("title", h.title);
                        o.put("uploader", h.uploader);
                        o.put("uploaderUrl", h.uploaderUrl);
                        o.put("duration", h.duration);
                        o.put("views", h.views);
                        if (h.thumb != null) o.put("thumb", h.thumb);
                        items.put(o);
                    }
                } catch (Exception e) {
                    Throwable c = e.getCause() != null ? e.getCause() : e;
                    String m = c.getMessage();
                    errors.put(jobsWhat.get(i), m == null ? c.getClass().getSimpleName() : m.length() > 160 ? m.substring(0, 160) : m);
                }
            }
            JSObject r = new JSObject();
            r.put("items", items);
            r.put("errors", errors);
            call.resolve(r);
        }).start();
    }

    /**
     * Le morceau est-il posé sur la prod ? { prod: id YouTube, service: "yt" | "sc", id | url }
     * → { status: "ok", same, score, ratio, offset, spread } ou { status: "noaudio" | "fail", err }.
     * Les sons ne vont que dans le cache de l'app et sont effacés aussitôt.
     */
    @PluginMethod
    public void soundMatch(PluginCall call) {
        String prod = call.getString("prod", "");
        String service = call.getString("service", "yt");
        String id = call.getString("id", "");
        String url = call.getString("url", "");
        if (!YtStream.VIDEO_ID.matcher(prod).matches()) { call.reject("Prod invalide"); return; }
        if ("yt".equals(service) ? !YtStream.VIDEO_ID.matcher(id).matches() : !"sc".equals(service) || !UsedBy.SC_URL.matcher(url).matches()) {
            call.reject("Morceau invalide");
            return;
        }
        File dir = new File(getContext().getCacheDir(), "usedby");
        dir.mkdirs();
        MATCH.submit(() -> {
            JSObject r = new JSObject();
            try {
                SoundPrint p;
                synchronized (PROD_LOCK) {
                    if (!prod.equals(prodId) || prodPrint == null) {
                        prodPrint = null;
                        prodId = prod;
                        prodPrint = UsedBy.youtubePrint(prod, dir, 300);
                    }
                    p = prodPrint;
                }
                SoundPrint s = "yt".equals(service) ? UsedBy.youtubePrint(id, dir, 90) : UsedBy.soundcloudPrint(url, dir, 90);
                if (s == null) {
                    r.put("status", "noaudio");
                } else {
                    SoundPrint.Match m = SoundPrint.compare(p, s);
                    r.put("status", "ok");
                    r.put("same", m.same);
                    r.put("score", m.score);
                    r.put("ratio", m.ratio);
                    r.put("offset", m.offset);
                    r.put("spread", m.spread);
                }
            } catch (Throwable e) {
                String m = e.getMessage();
                r.put("status", "fail");
                r.put("err", m == null ? e.getClass().getSimpleName() : m.length() > 160 ? m.substring(0, 160) : m);
            }
            call.resolve(r);
        });
    }

    // ------------------------------------------------------------------ playlist collée

    /**
     * Vidéos d'une playlist (même non répertoriée) : { id } →
     * { name, uploader, count, more, items: [{ id, title, duration, views, uploader, uploaderUrl }] }.
     */
    @PluginMethod
    public void ytPlaylist(PluginCall call) {
        String id = call.getString("id", "");
        if (!YtPlaylist.LIST_ID.matcher(id).matches()) { call.reject("Playlist invalide"); return; }
        new Thread(() -> {
            try {
                YtPlaylist.Result res = YtPlaylist.fetch(id);
                JSObject r = new JSObject();
                r.put("name", res.name);
                r.put("uploader", res.uploader);
                r.put("count", res.count);
                r.put("more", res.more);
                JSArray items = new JSArray();
                for (YtPlaylist.Video v : res.items) {
                    JSObject o = new JSObject();
                    o.put("id", v.id);
                    o.put("title", v.title);
                    o.put("duration", v.duration);
                    o.put("views", v.views);
                    o.put("uploader", v.uploader);
                    o.put("uploaderUrl", v.uploaderUrl);
                    items.put(o);
                }
                r.put("items", items);
                call.resolve(r);
            } catch (Throwable e) {
                String m = e.getMessage();
                call.reject(m == null ? e.getClass().getSimpleName() : m.length() > 200 ? m.substring(0, 200) : m);
            }
        }).start();
    }

    // ------------------------------------------------------------------ onglet Téléphone

    private static final ExecutorService PHONE = Executors.newFixedThreadPool(2);

    @Override
    public void load() {
        PhonePlayerService.listener = st -> notifyListeners("phonePlayer", st);
        String m = getContext().getSharedPreferences("melofinds_phone", android.content.Context.MODE_PRIVATE).getString("mode", "suite");
        PhonePlayerService.mode = m;
    }

    private static void fail(PluginCall call, Throwable e) {
        String m = e.getMessage();
        call.reject(m == null ? e.getClass().getSimpleName() : m.length() > 200 ? m.substring(0, 200) : m);
    }

    /** Le dossier « Melofinds Instru » est-il relié ? { linked, name } */
    @PluginMethod
    public void phoneInfo(PluginCall call) {
        PHONE.submit(() -> {
            DocumentFile d = PhoneLibrary.folder(getContext(), false);
            JSObject r = new JSObject();
            r.put("linked", d != null);
            r.put("name", d != null ? d.getName() : "");
            r.put("player", PhonePlayerService.snapshot());
            call.resolve(r);
        });
    }

    /**
     * Choisir (ou retrouver après une réinstallation) le dossier : le sélecteur d'Android s'ouvre
     * sur Musique / Melofinds Instru. L'appli n'aura accès qu'à ce dossier.
     */
    @PluginMethod
    public void phonePickFolder(PluginCall call) {
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION
            | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION | Intent.FLAG_GRANT_PREFIX_URI_PERMISSION);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            File music = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MUSIC);
            String doc = new File(music, PhoneLibrary.FOLDER).exists() ? "primary:Music/" + PhoneLibrary.FOLDER : "primary:Music";
            i.putExtra(DocumentsContract.EXTRA_INITIAL_URI, DocumentsContract.buildDocumentUri("com.android.externalstorage.documents", doc));
        }
        try {
            startActivityForResult(call, i, "folderPicked");
        } catch (Exception e) {
            call.reject("Sélecteur de dossier indisponible");
        }
    }

    @ActivityCallback
    private void folderPicked(PluginCall call, ActivityResult result) {
        if (call == null) return;
        Intent data = result.getData();
        if (result.getResultCode() != Activity.RESULT_OK || data == null || data.getData() == null) {
            call.reject("Annulé", "cancel");
            return;
        }
        Uri tree = data.getData();
        int rw = Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION;
        try {
            getContext().getContentResolver().takePersistableUriPermission(tree, rw);
        } catch (SecurityException e) {
            call.reject("Android n'a pas donné l'accès à ce dossier : choisis-en un autre (pas la racine ni Téléchargements)");
            return;
        }
        // un seul dossier autorisé : les anciens accès sont rendus
        for (android.content.UriPermission p : getContext().getContentResolver().getPersistedUriPermissions()) {
            if (!p.getUri().equals(tree)) {
                try { getContext().getContentResolver().releasePersistableUriPermission(p.getUri(), rw); } catch (Exception ignored) { }
            }
        }
        PhoneLibrary.saveTree(getContext(), tree);
        PHONE.submit(() -> {
            try {
                DocumentFile d = PhoneLibrary.folder(getContext(), true);
                if (d == null) { call.reject("Impossible de créer « " + PhoneLibrary.FOLDER + " » ici : choisis le dossier Musique"); return; }
                JSObject r = new JSObject();
                r.put("linked", true);
                r.put("name", d.getName());
                r.put("files", PhoneLibrary.list(getContext(), d));
                call.resolve(r);
            } catch (Throwable e) {
                fail(call, e);
            }
        });
    }

    /** Prods du dossier : { files: [{ name, size, at, meta: { id, title, key, bpm, lic… } }] } */
    @PluginMethod
    public void phoneList(PluginCall call) {
        PHONE.submit(() -> {
            try {
                DocumentFile d = PhoneLibrary.folder(getContext(), false);
                if (d == null) { call.reject("Dossier pas relié", "nofolder"); return; }
                JSObject r = new JSObject();
                r.put("files", PhoneLibrary.list(getContext(), d));
                call.resolve(r);
                backfill(d);
            } catch (Throwable e) {
                fail(call, e);
            }
        });
    }

    private static volatile boolean backfilling = false;

    /** Miniatures manquantes et anciens .m4a à réparer (avance rapide), une fois à la fois. */
    private void backfill(DocumentFile d) {
        if (backfilling) return;
        backfilling = true;
        new Thread(() -> {
            try {
                String playing = PhonePlayerService.snapshot().optString("name", "");
                if (PhoneLibrary.backfill(getContext(), d, playing)) notifyListeners("phoneChanged", new JSObject());
            } catch (Throwable ignored) {
            } finally {
                backfilling = false;
            }
        }).start();
    }

    /** Miniatures gardées dans le dossier : { ids } → { t: { id: "data:image/jpeg;base64,…" } } */
    @PluginMethod
    public void phoneThumbs(PluginCall call) {
        JSArray ids = call.getArray("ids", new JSArray());
        PHONE.submit(() -> {
            DocumentFile d = PhoneLibrary.folder(getContext(), false);
            JSObject r = new JSObject();
            r.put("t", d == null ? new JSObject() : PhoneLibrary.thumbs(getContext(), d, ids));
            call.resolve(r);
        });
    }

    /** Favori (gardé dans le dossier, même après une réinstallation) : { name, fav } */
    @PluginMethod
    public void phoneFav(PluginCall call) {
        String name = call.getString("name", "");
        boolean fav = Boolean.TRUE.equals(call.getBoolean("fav", false));
        PHONE.submit(() -> {
            try {
                DocumentFile d = PhoneLibrary.folder(getContext(), false);
                if (d == null) { call.reject("Dossier pas relié", "nofolder"); return; }
                if (PhoneLibrary.find(d, name) == null) { call.reject("Prod introuvable"); return; }
                PhoneLibrary.editMeta(getContext(), d, name, m -> m.put("fav", fav));
                call.resolve();
            } catch (Throwable e) {
                fail(call, e);
            }
        });
    }

    /** Mode de lecture : { mode: suite | aleatoire | boucle } */
    @PluginMethod
    public void phoneMode(PluginCall call) {
        String m = call.getString("mode", "suite");
        if (!java.util.Arrays.asList("suite", "aleatoire", "boucle").contains(m)) { call.reject("Mode inconnu"); return; }
        PhonePlayerService.mode = m;
        getContext().getSharedPreferences("melofinds_phone", android.content.Context.MODE_PRIVATE).edit().putString("mode", m).apply();
        PhonePlayerService.command(getContext(), "mode", 0);
        call.resolve(PhonePlayerService.snapshot());
    }

    /** Télécharge une prod dans le dossier : { id, name (sans extension), meta } → { name } */
    @PluginMethod
    public void phoneDownload(PluginCall call) {
        String id = call.getString("id", "");
        String name = call.getString("name", "");
        JSObject meta = call.getObject("meta", new JSObject());
        if (!YtStream.VIDEO_ID.matcher(id).matches()) { call.reject("Vidéo invalide"); return; }
        PHONE.submit(() -> {
            try {
                DocumentFile d = PhoneLibrary.folder(getContext(), true);
                if (d == null) { call.reject("Dossier pas relié", "nofolder"); return; }
                JSONObject m = new JSONObject(meta.toString());
                String got = PhoneLibrary.download(getContext(), d, id, name, m);
                JSObject r = new JSObject();
                r.put("name", got);
                call.resolve(r);
            } catch (Throwable e) {
                fail(call, e);
            }
        });
    }

    @PluginMethod
    public void phoneDelete(PluginCall call) {
        String name = call.getString("name", "");
        PHONE.submit(() -> {
            try {
                DocumentFile d = PhoneLibrary.folder(getContext(), false);
                if (d == null) { call.reject("Dossier pas relié", "nofolder"); return; }
                JSObject r = new JSObject();
                r.put("ok", PhoneLibrary.delete(getContext(), d, name));
                call.resolve(r);
            } catch (Throwable e) {
                fail(call, e);
            }
        });
    }

    /** Lecture hors connexion (continue écran verrouillé) : { names: [...], index } */
    @PluginMethod
    public void phonePlay(PluginCall call) {
        JSArray names = call.getArray("names", new JSArray());
        int index = call.getInt("index", 0);
        PHONE.submit(() -> {
            try {
                DocumentFile d = PhoneLibrary.folder(getContext(), false);
                if (d == null) { call.reject("Dossier pas relié", "nofolder"); return; }
                java.util.Map<String, DocumentFile> byName = new java.util.HashMap<>();
                for (DocumentFile f : d.listFiles()) if (f.getName() != null && f.isFile()) byName.put(f.getName(), f);
                JSONObject idx = PhoneLibrary.readIndex(getContext(), d);
                List<PhonePlayerService.Track> q = new ArrayList<>();
                int start = 0;
                for (int i = 0; i < names.length() && q.size() < 1000; i++) {
                    String n = names.optString(i, "");
                    DocumentFile f = byName.get(n);
                    if (f == null || !PhoneLibrary.AUDIO.matcher(n).matches()) continue;
                    if (i == index) start = q.size();
                    JSONObject meta = idx.optJSONObject(n);
                    String vid = meta != null ? meta.optString("id", "") : "";
                    DocumentFile th = PhoneLibrary.thumbFile(d, vid);
                    q.add(new PhonePlayerService.Track(f.getUri(), n, n.replaceAll("\\.[A-Za-z0-9]+$", ""), vid, th != null ? th.getUri() : null));
                }
                if (q.isEmpty()) { call.reject("Prod introuvable dans le dossier"); return; }
                synchronized (PhonePlayerService.queue) {
                    PhonePlayerService.queue.clear();
                    PhonePlayerService.queue.addAll(q);
                    PhonePlayerService.index = start;
                }
                Activity a = getActivity();
                Runnable go = () -> PhonePlayerService.command(getContext(), "play", 0);
                if (a != null) a.runOnUiThread(go); else go.run();
                call.resolve();
            } catch (Throwable e) {
                fail(call, e);
            }
        });
    }

    /** { cmd: toggle | pause | resume | next | prev | seek | stop, ms } */
    @PluginMethod
    public void phoneControl(PluginCall call) {
        String cmd = call.getString("cmd", "");
        if (!java.util.Arrays.asList("toggle", "pause", "resume", "next", "prev", "seek", "stop").contains(cmd)) { call.reject("Commande inconnue"); return; }
        if ("seek".equals(cmd) && !call.getData().has("ms")) { call.reject("Position manquante"); return; }
        long ms = Math.round(call.getData().optDouble("ms", 0));
        PhonePlayerService.command(getContext(), cmd, ms);
        call.resolve();
    }

    @PluginMethod
    public void phoneState(PluginCall call) {
        call.resolve(PhonePlayerService.snapshot());
    }
}
