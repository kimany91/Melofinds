package io.github.kimany91.melofinds;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {

    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(MelofindsNativePlugin.class);
        super.onCreate(savedInstanceState);
    }
}
