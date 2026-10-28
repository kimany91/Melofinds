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

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Pont entre l'app web Melofinds et Android : retour haptique, liens, clé et BPM par l'outil
 * Analyzer de Tunebat (la prod est téléchargée dans le cache de l'app puis effacée),
 * descriptions complètes des vidéos, scanner du QR code de Melofinds PC. Aucun accès aux
 * fichiers du téléphone.
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
}
