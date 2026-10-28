package io.github.kimany91.melofinds;

import android.content.Intent;
import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {

    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(MelofindsNativePlugin.class);
        super.onCreate(savedInstanceState);
        // ouverte par « Partager → Melofinds » (son téléchargé)
        MelofindsNativePlugin.receive(this, getIntent());
    }

    // Réponse d'Android à « supprimer ce son ? » (demande officielle de suppression)
    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == MelofindsNativePlugin.REQ_DELETE) MelofindsNativePlugin.onDeleteResult(resultCode);
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        MelofindsNativePlugin.receive(this, intent);
    }
}
