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
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.appcompat.app.AppCompatActivity;

import com.getcapacitor.JSObject;
import com.getcapacitor.PluginCall;

import org.json.JSONTokener;

import java.net.URLEncoder;

/**
 * Tunebat dans une fenêtre visible, comme dans Chrome : si Tunebat demande de vérifier qu'on
 * n'est pas un robot, c'est TOI qui le fais (rien n'est contourné). Dès que la réponse de
 * Tunebat s'affiche, la fenêtre la lit et se ferme toute seule.
 */
public class TunebatActivity extends AppCompatActivity {

    static PluginCall pending;
    static final String API = "https://api.tunebat.com/api/tracks/search?term=";

    private WebView web;
    private TextView info;
    private boolean done = false;
    private final Handler ui = new Handler(Looper.getMainLooper());

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        String term = getIntent().getStringExtra("term");
        if (term == null || term.trim().isEmpty() || term.length() > 120) { finishWith(null, "Recherche vide"); return; }

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
        info.setText("Tunebat : je cherche « " + term + " »…\nSi Tunebat demande une vérification, fais-la : je lis le résultat tout seul.");
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

            @Override
            public void onPageFinished(WebView view, String url) {
                if (done || url == null) return;
                Uri u = Uri.parse(url);
                if (!"api.tunebat.com".equals(u.getHost())) return;
                view.evaluateJavascript("document.body ? document.body.innerText : ''", (val) -> {
                    String text = "";
                    try { Object o = new JSONTokener(val).nextValue(); if (o instanceof String) text = (String) o; } catch (Exception ignored) { }
                    String t = text.trim();
                    if (t.startsWith("{") && t.contains("\"data\"")) finishWith(t, null);
                    else info.setText("Tunebat demande une vérification : fais-la ci-dessous, je lis le résultat tout seul.");
                });
            }
        });
        root.addView(web, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        setContentView(root);
        try {
            web.loadUrl(API + URLEncoder.encode(term.trim(), "UTF-8"));
        } catch (Exception e) {
            finishWith(null, "Recherche impossible");
            return;
        }
        ui.postDelayed(() -> finishWith(null, "Tunebat n'a pas répondu"), 120000);
    }

    static boolean allowed(Uri u) {
        String h = u == null ? null : u.getHost();
        if (h == null || !"https".equals(u.getScheme())) return false;
        return h.equals("tunebat.com") || h.endsWith(".tunebat.com") || h.equals("challenges.cloudflare.com");
    }

    private void finishWith(String body, String err) {
        if (done) return;
        done = true;
        ui.removeCallbacksAndMessages(null);
        PluginCall c = pending;
        pending = null;
        if (c != null) {
            if (body != null) {
                JSObject r = new JSObject();
                r.put("status", 200);
                r.put("body", body.length() > 2_000_000 ? "" : body);
                c.resolve(r);
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
