package io.github.kimany91.melofinds;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.ServiceInfo;
import android.media.AudioAttributes;
import android.media.AudioFocusRequest;
import android.media.AudioManager;
import android.media.MediaMetadata;
import android.media.MediaPlayer;
import android.media.session.MediaSession;
import android.media.session.PlaybackState;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;

import com.getcapacitor.JSObject;

import java.util.ArrayList;
import java.util.List;

/**
 * Lecteur des prods du dossier « Melofinds Instru », hors connexion, qui continue écran
 * verrouillé : service au premier plan (notification avec lecture / pause / suivante), commandes
 * sur l'écran verrouillé et sur le casque (MediaSession), pause si le casque est débranché.
 */
public class PhonePlayerService extends Service implements AudioManager.OnAudioFocusChangeListener {

    static final class Track {
        final Uri uri;
        final String name;
        final String title;
        final String id;   // vidéo YouTube (miniature), ou ""
        final Uri art;     // miniature gardée dans le dossier, ou null
        Track(Uri uri, String name, String title, String id, Uri art) { this.uri = uri; this.name = name; this.title = title; this.id = id; this.art = art; }
    }

    /** Modes de lecture : à la suite, aléatoire, la prod en boucle. */
    static volatile String mode = "suite";
    private static final java.util.ArrayDeque<Integer> history = new java.util.ArrayDeque<>();
    private static final java.util.Random random = new java.util.Random();

    interface Listener { void state(JSObject s); }

    static volatile Listener listener;
    static final List<Track> queue = new ArrayList<>();
    static int index = 0;
    private static volatile PhonePlayerService running;

    private static final String CHANNEL = "melofinds_player";
    private static final int NOTIF = 4107;

    private MediaPlayer mp;
    private MediaSession session;
    private boolean prepared;
    private long pendingSeek = -1;
    private boolean retried;
    static volatile String lastError = "";
    private android.graphics.Bitmap art;
    private Uri artFor;
    private boolean resumeOnFocus;
    private AudioFocusRequest focusRequest;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final Runnable ticker = new Runnable() {
        @Override public void run() {
            report();
            if (mp != null && prepared && mp.isPlaying()) ui.postDelayed(this, 1000);
        }
    };
    private final BroadcastReceiver noisy = new BroadcastReceiver() {
        @Override public void onReceive(Context c, Intent i) {
            if (AudioManager.ACTION_AUDIO_BECOMING_NOISY.equals(i.getAction())) pause();  // casque débranché
        }
    };
    private boolean noisyOn;

    // ------------------------------------------------------------------ commandes

    static void command(Context c, String cmd, long ms) {
        // lecteur arrêté (bouton Stop, ou fermé par Android) : relancer = rejouer la prod choisie
        if (running == null && ("toggle".equals(cmd) || "resume".equals(cmd))) cmd = "play";
        Intent i = new Intent(c, PhonePlayerService.class);
        i.putExtra("cmd", cmd);
        i.putExtra("ms", ms);
        if ("play".equals(cmd) && Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) c.startForegroundService(i);
        else if (running != null || "play".equals(cmd)) c.startService(i);
    }

    static JSObject snapshot() {
        PhonePlayerService s = running;
        JSObject o = new JSObject();
        synchronized (queue) {
            Track t = index >= 0 && index < queue.size() ? queue.get(index) : null;
            o.put("name", t != null ? t.name : "");
            o.put("title", t != null ? t.title : "");
            o.put("index", index);
            o.put("count", queue.size());
            o.put("id", t != null ? t.id : "");
        }
        boolean ok = s != null && s.mp != null && s.prepared;
        o.put("active", s != null);
        o.put("mode", mode);
        o.put("error", lastError);
        o.put("playing", ok && s.mp.isPlaying());
        o.put("position", ok ? s.mp.getCurrentPosition() : 0);
        o.put("duration", ok ? s.mp.getDuration() : 0);
        return o;
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        running = this;
        if (session == null) setupSession();
        String cmd = intent != null ? intent.getStringExtra("cmd") : null;
        long ms = intent != null ? intent.getLongExtra("ms", 0) : 0;
        if ("play".equals(cmd)) {
            startFg();  // tout de suite : Android l'exige pour un service lancé au premier plan
            retried = false;
            lastError = "";
            load();
        } else if ("toggle".equals(cmd)) {
            if (mp != null && prepared && mp.isPlaying()) pause(); else resume();
        } else if ("pause".equals(cmd)) pause();
        else if ("resume".equals(cmd)) resume();
        else if ("next".equals(cmd)) skip(1);
        else if ("prev".equals(cmd)) {
            if (mp != null && prepared && mp.getCurrentPosition() > 4000) seek(0); else skip(-1);
        } else if ("seek".equals(cmd)) seek(ms);
        else if ("mode".equals(cmd)) {
            if (mp != null) mp.setLooping("boucle".equals(mode));
            refresh();
        } else if ("stop".equals(cmd)) stopAll();
        return START_NOT_STICKY;
    }

    private void setupSession() {
        session = new MediaSession(this, "Melofinds");
        session.setCallback(new MediaSession.Callback() {
            @Override public void onPlay() { resume(); }
            @Override public void onPause() { pause(); }
            @Override public void onSkipToNext() { skip(1); }
            @Override public void onSkipToPrevious() { skip(-1); }
            @Override public void onSeekTo(long pos) { seek(pos); }
            @Override public void onStop() { stopAll(); }
        });
        session.setActive(true);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel ch = new NotificationChannel(CHANNEL, "Lecture des prods", NotificationManager.IMPORTANCE_LOW);
            ch.setShowBadge(false);
            getSystemService(NotificationManager.class).createNotificationChannel(ch);
        }
    }

    private Track current() {
        synchronized (queue) {
            return index >= 0 && index < queue.size() ? queue.get(index) : null;
        }
    }

    private void load() {
        Track t = current();
        if (t == null) { stopAll(); return; }
        releasePlayer();
        mp = new MediaPlayer();
        mp.setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build());
        mp.setWakeMode(getApplicationContext(), PowerManager.PARTIAL_WAKE_LOCK);  // continue écran éteint
        mp.setOnPreparedListener(p -> {
            prepared = true;
            retried = false;
            p.setLooping("boucle".equals(mode));
            if (pendingSeek > 0) { p.seekTo((int) Math.min(pendingSeek, p.getDuration())); pendingSeek = -1; }
            resume();
        });
        mp.setOnCompletionListener(p -> skip(1));
        mp.setOnErrorListener((p, what, extra) -> {
            prepared = false;
            if (!retried) { retried = true; ui.postDelayed(this::load, 400); return true; }  // une 2e chance
            lastError = (t.title.length() > 60 ? t.title.substring(0, 60) : t.title) + " (erreur " + what + ")";
            report();
            skip(1);
            return true;
        });
        try {
            mp.setDataSource(this, t.uri);
            mp.prepareAsync();
        } catch (Exception e) {
            prepared = false;
            if (!retried) { retried = true; ui.postDelayed(this::load, 400); return; }
            lastError = t.title + " : " + e.getMessage();
            report();
            skip(1);
            return;
        }
        loadArt(t);
        updateMeta(t);
        refresh();
    }

    private void loadArt(Track t) {
        if (t.art == null) { art = null; artFor = null; return; }
        if (t.art.equals(artFor)) return;
        artFor = t.art;
        art = null;
        try (java.io.InputStream in = getContentResolver().openInputStream(t.art)) {
            if (in != null) art = android.graphics.BitmapFactory.decodeStream(in);
        } catch (Exception ignored) { }
    }

    private void resume() {
        if (mp == null) { load(); return; }
        if (!prepared) return;
        if (!requestFocus()) return;
        mp.start();
        if (!noisyOn) {
            registerReceiver(noisy, new IntentFilter(AudioManager.ACTION_AUDIO_BECOMING_NOISY));
            noisyOn = true;
        }
        startFg();
        ui.removeCallbacks(ticker);
        ui.post(ticker);
        refresh();
    }

    private void pause() {
        if (mp != null && prepared && mp.isPlaying()) mp.pause();
        if (noisyOn) {
            try { unregisterReceiver(noisy); } catch (Exception ignored) { }
            noisyOn = false;
        }
        // la notification reste (on peut relancer depuis l'écran verrouillé), sans bloquer Android
        stopForeground(Service.STOP_FOREGROUND_DETACH);
        refresh();
    }

    private void skip(int d) {
        synchronized (queue) {
            if (queue.isEmpty()) { stopAll(); return; }
            if ("aleatoire".equals(mode) && queue.size() > 1) {
                if (d < 0 && !history.isEmpty()) {
                    index = history.pop();
                } else if (d > 0) {
                    history.push(index);
                    while (history.size() > 200) history.removeLast();
                    int n;
                    do { n = random.nextInt(queue.size()); } while (n == index);
                    index = n;
                }
            } else {
                int n = index + d;
                if (n >= queue.size()) {  // fin de la liste : on s'arrête sur la dernière
                    if (mp != null && prepared) { mp.pause(); mp.seekTo(0); }
                    refresh();
                    return;
                }
                index = Math.max(0, n);
            }
        }
        load();
    }

    private void seek(long ms) {
        if (mp != null && prepared) {
            mp.seekTo((int) Math.max(0, Math.min(ms, mp.getDuration())));
            ui.postDelayed(this::refresh, 250);  // position à jour une fois l'avance faite
        } else {
            pendingSeek = ms;  // le son se prépare encore : l'avance se fera juste après
        }
        refresh();
    }

    private void stopAll() {
        ui.removeCallbacks(ticker);
        if (noisyOn) {
            try { unregisterReceiver(noisy); } catch (Exception ignored) { }
            noisyOn = false;
        }
        releasePlayer();
        abandonFocus();
        stopForeground(Service.STOP_FOREGROUND_REMOVE);
        if (session != null) { session.setActive(false); session.release(); session = null; }
        running = null;
        report();
        stopSelf();
    }

    private void releasePlayer() {
        prepared = false;
        if (mp != null) {
            try { mp.release(); } catch (Exception ignored) { }
            mp = null;
        }
    }

    // ------------------------------------------------------------------ focus audio (appel, autre appli)

    private boolean requestFocus() {
        AudioManager am = (AudioManager) getSystemService(AUDIO_SERVICE);
        int r;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            if (focusRequest == null) {
                focusRequest = new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN)
                    .setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build())
                    .setOnAudioFocusChangeListener(this).build();
            }
            r = am.requestAudioFocus(focusRequest);
        } else {
            r = am.requestAudioFocus(this, AudioManager.STREAM_MUSIC, AudioManager.AUDIOFOCUS_GAIN);
        }
        return r == AudioManager.AUDIOFOCUS_REQUEST_GRANTED;
    }

    private void abandonFocus() {
        AudioManager am = (AudioManager) getSystemService(AUDIO_SERVICE);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            if (focusRequest != null) am.abandonAudioFocusRequest(focusRequest);
        } else {
            am.abandonAudioFocus(this);
        }
    }

    @Override
    public void onAudioFocusChange(int change) {
        if (mp == null || !prepared) return;
        if (change == AudioManager.AUDIOFOCUS_LOSS) { resumeOnFocus = false; pause(); }
        else if (change == AudioManager.AUDIOFOCUS_LOSS_TRANSIENT) { resumeOnFocus = mp.isPlaying(); pause(); }
        else if (change == AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK) mp.setVolume(0.3f, 0.3f);
        else if (change == AudioManager.AUDIOFOCUS_GAIN) {
            mp.setVolume(1f, 1f);
            if (resumeOnFocus) { resumeOnFocus = false; resume(); }
        }
    }

    // ------------------------------------------------------------------ écran verrouillé, notification

    private void updateMeta(Track t) {
        if (session == null) return;
        MediaMetadata.Builder b = new MediaMetadata.Builder()
            .putString(MediaMetadata.METADATA_KEY_TITLE, t.title)
            .putString(MediaMetadata.METADATA_KEY_ARTIST, "Melofinds Instru");
        if (art != null) b.putBitmap(MediaMetadata.METADATA_KEY_ALBUM_ART, art);
        session.setMetadata(b.build());
    }

    private void refresh() {
        boolean playing = mp != null && prepared && mp.isPlaying();
        if (session != null) {
            Track t = current();
            if (t != null && mp != null && prepared) {
                MediaMetadata.Builder b = new MediaMetadata.Builder()
                    .putString(MediaMetadata.METADATA_KEY_TITLE, t.title)
                    .putString(MediaMetadata.METADATA_KEY_ARTIST, "Melofinds Instru")
                    .putLong(MediaMetadata.METADATA_KEY_DURATION, mp.getDuration());
                if (art != null) b.putBitmap(MediaMetadata.METADATA_KEY_ALBUM_ART, art);
                session.setMetadata(b.build());
            }
            session.setPlaybackState(new PlaybackState.Builder()
                .setActions(PlaybackState.ACTION_PLAY | PlaybackState.ACTION_PAUSE | PlaybackState.ACTION_PLAY_PAUSE
                    | PlaybackState.ACTION_SKIP_TO_NEXT | PlaybackState.ACTION_SKIP_TO_PREVIOUS | PlaybackState.ACTION_SEEK_TO | PlaybackState.ACTION_STOP)
                .setState(playing ? PlaybackState.STATE_PLAYING : PlaybackState.STATE_PAUSED, mp != null && prepared ? mp.getCurrentPosition() : 0, playing ? 1f : 0f)
                .build());
        }
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (running != null) nm.notify(NOTIF, buildNotification());
        report();
    }

    private void startFg() {
        Notification n = buildNotification();
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) startForeground(NOTIF, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK);
            else startForeground(NOTIF, n);
        } catch (RuntimeException e) {
            // Android refuse parfois depuis l'arrière-plan : la lecture continue, notification simple
            ((NotificationManager) getSystemService(NOTIFICATION_SERVICE)).notify(NOTIF, n);
        }
    }

    private PendingIntent action(String cmd, int code) {
        Intent i = new Intent(this, PhonePlayerService.class).putExtra("cmd", cmd);
        return PendingIntent.getService(this, code, i, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    @SuppressWarnings("deprecation")
    private Notification buildNotification() {
        Track t = current();
        boolean playing = mp != null && prepared && mp.isPlaying();
        Notification.Builder b = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O ? new Notification.Builder(this, CHANNEL) : new Notification.Builder(this);
        Intent open = new Intent(this, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP);
        b.setSmallIcon(android.R.drawable.ic_media_play)
            .setContentTitle(t != null ? t.title : "Melofinds")
            .setContentText("Melofinds Instru")
            .setLargeIcon(art)
            .setVisibility(Notification.VISIBILITY_PUBLIC)  // visible écran verrouillé
            .setOngoing(playing)
            .setShowWhen(false)
            .setContentIntent(PendingIntent.getActivity(this, 1, open, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE))
            .setDeleteIntent(action("stop", 5))
            .addAction(new Notification.Action.Builder(android.R.drawable.ic_media_previous, "Précédente", action("prev", 2)).build())
            .addAction(new Notification.Action.Builder(playing ? android.R.drawable.ic_media_pause : android.R.drawable.ic_media_play, playing ? "Pause" : "Lecture", action("toggle", 3)).build())
            .addAction(new Notification.Action.Builder(android.R.drawable.ic_media_next, "Suivante", action("next", 4)).build());
        Notification.MediaStyle style = new Notification.MediaStyle().setShowActionsInCompactView(0, 1, 2);
        if (session != null) style.setMediaSession(session.getSessionToken());
        b.setStyle(style);
        return b.build();
    }

    private void report() {
        Listener l = listener;
        if (l != null) l.state(snapshot());
    }

    @Override
    public void onTaskRemoved(Intent rootIntent) {
        // appli fermée depuis les applis récentes : on continue si ça joue, sinon on s'arrête
        if (mp == null || !prepared || !mp.isPlaying()) stopAll();
    }

    @Override
    public void onDestroy() {
        ui.removeCallbacks(ticker);
        releasePlayer();
        if (session != null) { session.release(); session = null; }
        running = null;
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }
}
