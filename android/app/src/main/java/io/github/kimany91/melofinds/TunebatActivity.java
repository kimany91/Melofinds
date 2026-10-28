package io.github.kimany91.melofinds;

import android.annotation.SuppressLint;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.appcompat.app.AppCompatActivity;

import com.getcapacitor.JSObject;
import com.getcapacitor.PluginCall;

import org.json.JSONObject;
import org.json.JSONTokener;

import java.io.File;
import java.io.FileInputStream;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * L'outil Analyzer de Tunebat (tunebat.com/Analyzer) dans une fenêtre visible : la prod est
 * téléchargée dans le cache de l'app, convertie en WAV, puis donnée à la page comme si on
 * l'avait déposée. Tunebat l'analyse dans le navigateur (le fichier n'est envoyé à aucun
 * serveur) ; la fenêtre lit la clé et le BPM dans le tableau des résultats, efface le
 * fichier et se ferme. Si Tunebat demande une vérification, c'est l'utilisateur qui la fait.
 */
public class TunebatActivity extends AppCompatActivity {

    static PluginCall pending;
    static final String ANALYZER = "https://tunebat.com/Analyzer";
    private static final String FILE_PATH = "/__melofinds__/";

    private WebView web;
    private TextView info;
    private File dir;
    private File wav;
    private String fileName;
    private volatile boolean fileReady = false;
    private boolean pageReady = false;
    private boolean injected = false;
    private boolean done = false;
    private int polls = 0;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final Runnable pollTask = this::poll;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        String id = getIntent().getStringExtra("id");
        if (id == null || !YtStream.VIDEO_ID.matcher(id).matches()) { finishWith(null, "Vidéo invalide"); return; }
        fileName = "Melofinds-" + id + ".wav";
        dir = new File(getCacheDir(), "tunebat");
        dir.mkdirs();
        wav = new File(dir, fileName);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.parseColor("#0f1014"));
        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setPadding(32, 24, 24, 24);
        info = new TextView(this);
        info.setTextColor(Color.WHITE);
        info.setTextSize(14);
        info.setText("Téléchargement de la prod…");
        bar.addView(info, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        Button close = new Button(this);
        close.setText("Fermer");
        close.setOnClickListener(v -> finishWith(null, "Annulé"));
        bar.addView(close);
        root.addView(bar);

        web = new WebView(this);
        WebSettings ws = web.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, true);
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                return !allowed(req.getUrl()); // seulement Tunebat et sa page de vérification
            }

            // le fichier de la prod, servi à la page Tunebat (et à elle seule)
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest req) {
                Uri u = req.getUrl();
                if (u != null && "tunebat.com".equals(u.getHost()) && (FILE_PATH + fileName).equals(u.getPath()) && fileReady) {
                    try {
                        Map<String, String> h = new HashMap<>();
                        h.put("Cache-Control", "no-store");
                        return new WebResourceResponse("audio/wav", null, 200, "OK", h, new FileInputStream(wav));
                    } catch (Exception e) {
                        return null;
                    }
                }
                return null;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                Uri u = url == null ? null : Uri.parse(url);
                if (u != null && "tunebat.com".equals(u.getHost()) && u.getPath() != null && u.getPath().toLowerCase().startsWith("/analyzer")) {
                    // aussi après une vérification Tunebat (la page se recharge) : on redonne le fichier
                    pageReady = true;
                    injected = false;
                    polls = 0;
                    maybeInject();
                }
            }
        });
        root.addView(web, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        setContentView(root);
        web.loadUrl(ANALYZER);
        new Thread(() -> prepare(id)).start();
        ui.postDelayed(() -> finishWith(null, "Tunebat n'a pas donné de résultat"), 240000);
    }

    // téléchargement + WAV, en arrière-plan pendant que la page Tunebat s'ouvre
    private void prepare(String id) {
        File raw = null;
        try {
            List<YtStream.Pick> picks = YtStream.streams(id);
            Exception last = null;
            for (int i = 0; i < Math.min(3, picks.size()) && !done; i++) {
                YtStream.Pick p = picks.get(i);
                raw = new File(dir, id + "." + p.format);
                try {
                    YtStream.download(p, raw);
                    say("Préparation du fichier…");
                    AudioPcm.toWav(raw, wav);
                    raw.delete();
                    fileReady = true;
                    ui.post(this::maybeInject);
                    return;
                } catch (Exception e) {
                    last = e;
                    raw.delete();
                }
            }
            throw last != null ? last : new Exception("aucun son");
        } catch (Throwable e) {
            if (raw != null) raw.delete();
            String m = e.getMessage();
            ui.post(() -> finishWith(null, "Téléchargement impossible" + (m != null && m.length() < 120 ? " : " + m : "")));
        }
    }

    private void say(String t) { ui.post(() -> { if (info != null) info.setText(t); }); }

    private void maybeInject() {
        if (done || injected || !pageReady || !fileReady) return;
        injected = true;
        say("Tunebat analyse la prod…");
        String n = JSONObject.quote(fileName);
        // le fichier est donné au champ « Select Files » de la page, comme un dépôt à la main
        web.evaluateJavascript("(async()=>{try{const n=" + n + ";const b=await (await fetch('" + FILE_PATH + "'+n)).blob();"
            + "const f=new File([b],n,{type:'audio/wav'});const dt=new DataTransfer();dt.items.add(f);"
            + "const i=document.querySelector('input[type=file]');"
            + "if(i){i.files=dt.files;i.dispatchEvent(new Event('change',{bubbles:true}));i.dispatchEvent(new Event('input',{bubbles:true}));}"
            + "window.__mfDrop=()=>{const z=(i&&(i.closest('[class*=rop]')||i.parentElement))||document.body;"
            + "for(const t of ['dragenter','dragover','drop'])z.dispatchEvent(new DragEvent(t,{bubbles:true,cancelable:true,dataTransfer:dt}));};"
            + "}catch(e){window.__mfErr=String(e)}})()", null);
        ui.removeCallbacks(pollTask);
        ui.postDelayed(pollTask, 2000);
    }

    // lecture du tableau des résultats (ligne du fichier : colonnes « Key », « BPM », « Camelot »)
    private void poll() {
        if (done) return;
        polls++;
        if (polls == 6) web.evaluateJavascript("window.__mfDrop&&window.__mfDrop()", null); // repli : dépôt glissé
        String n = JSONObject.quote(fileName.replace(".wav", ""));
        web.evaluateJavascript("(()=>{const n=" + n + ".toLowerCase();const o={};"
            + "for(const t of document.querySelectorAll('table')){const hs=[...t.querySelectorAll('th')].map(x=>x.innerText.trim().toLowerCase());"
            + "for(const tr of t.querySelectorAll('tr')){const c=[...tr.querySelectorAll('td')].map(x=>x.innerText.trim());if(!c.length)continue;"
            + "const row=c.join(' | ');if(!row.toLowerCase().includes(n))continue;o.row=row;"
            + "hs.forEach((h,k)=>{if(/key|clé|tonalit/.test(h))o.key=c[k];if(/bpm|tempo/.test(h))o.bpm=c[k];if(/camelot/.test(h))o.camelot=c[k];});}}"
            + "if(!o.row){const x=document.body.innerText;const k=x.toLowerCase().indexOf(n);if(k>=0)o.row=x.slice(k,k+240);}"
            + "if(window.__mfErr)o.err=window.__mfErr;return JSON.stringify(o);})()", (val) -> {
                try {
                    Object s = new JSONTokener(val).nextValue();
                    JSONObject o = new JSONObject(s instanceof String ? (String) s : "{}");
                    String key = o.optString("key", "");
                    String row = o.optString("row", "");
                    boolean hasKey = key.matches("(?i).*[A-G].*(maj|min).*") || row.matches("(?is).*\\b[A-G][#♯b♭]?\\s*(major|minor|maj|min)\\b.*");
                    if (hasKey && (!o.optString("bpm", "").isEmpty() || row.matches("(?s).*\\b\\d{2,3}(\\.\\d+)?\\b.*"))) {
                        finishWith(o.toString(), null);
                        return;
                    }
                } catch (Exception ignored) { }
                if (polls < 120) { ui.removeCallbacks(pollTask); ui.postDelayed(pollTask, 1500); }
                else finishWith(null, "Tunebat n'a pas donné de résultat");
            });
    }

    static boolean allowed(Uri u) {
        String h = u == null ? null : u.getHost();
        if (h == null || !"https".equals(u.getScheme())) return false;
        return h.equals("tunebat.com") || h.endsWith(".tunebat.com") || h.equals("challenges.cloudflare.com");
    }

    private void cleanup() {
        if (dir == null) return;
        File[] fs = dir.listFiles();
        if (fs != null) for (File f : fs) f.delete();
    }

    private void finishWith(String result, String err) {
        if (done) return;
        done = true;
        ui.removeCallbacksAndMessages(null);
        cleanup(); // le fichier de la prod est effacé dans tous les cas
        PluginCall c = pending;
        pending = null;
        if (c != null) {
            if (result != null) {
                try { c.resolve(new JSObject(result)); } catch (Exception e) { c.reject("Résultat illisible", "fail"); }
            } else {
                c.reject(err == null ? "Annulé" : err, "Annulé".equals(err) ? "cancel" : "fail");
            }
        }
        finish();
    }

    @Override
    protected void onDestroy() {
        if (!done) finishWith(null, "Annulé");
        if (web != null) web.destroy();
        super.onDestroy();
    }
}
