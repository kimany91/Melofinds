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

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        MelofindsNativePlugin.receive(this, intent);
    }
}
