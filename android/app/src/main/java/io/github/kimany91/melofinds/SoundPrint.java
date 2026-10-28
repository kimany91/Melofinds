package io.github.kimany91.melofinds;

import java.util.Arrays;

/**
 * Empreinte d'un son, pour savoir si un morceau est posé sur une prod (comme Shazam) :
 * les pics du spectre (les notes et les frappes qui dépassent) sont reliés deux à deux, et
 * chaque paire donne un code. Si le morceau contient la prod, beaucoup de codes se
 * retrouvent avec le même décalage dans le temps, même avec une voix par-dessus.
 * Pas d'Android ici (testé sur un ordinateur).
 */
final class SoundPrint {

    /** Fréquence de travail : assez pour les notes, les basses et les frappes. */
    static final int SR = 11025;
    static final int N = 1024;          // fenêtre de 93 ms
    static final int HOP = 256;         // un pas toutes les 23 ms
    static final int FMIN = 5;          // ~54 Hz
    static final int FMAX = 372;        // ~4 kHz
    static final int NB = FMAX - FMIN;
    private static final int TW = 6;       // voisinage d'un pic : ±140 ms
    private static final int FW = 10;      //                     ±108 Hz
    private static final int PER_SEC = 30; // pics gardés par seconde
    private static final int FAN = 5;      // paires par pic
    private static final int CAP = 40;     // code plus fréquent dans la prod (une frappe qui revient) : ignoré
    private static final int DT_MAX = 40;
    private static final int DF_MAX = 80;

    /** Codes triés : (code << 32) | instant (en pas de 23 ms). */
    final long[] keys;
    final int frames;

    private SoundPrint(long[] keys, int frames) {
        this.keys = keys;
        this.frames = frames;
    }

    int size() { return keys.length; }

    // ------------------------------------------------------------------ calcul

    /** Empreinte d'un son mono à {@link #SR} Hz. */
    static SoundPrint of(float[] x, int n) {
        int frames = n < N ? 0 : 1 + (n - N) / HOP;
        if (frames < 2 * TW + 2) return new SoundPrint(new long[0], frames);
        float[] s = spectrogram(x, frames);
        int[] peaks = peaks(s, frames);
        return new SoundPrint(hashes(peaks), frames);
    }

    private static float[] spectrogram(float[] x, int frames) {
        float[] win = new float[N];
        for (int i = 0; i < N; i++) win[i] = (float) (0.5 - 0.5 * Math.cos(2 * Math.PI * i / N));
        float[] s = new float[frames * NB];
        double[] re = new double[N];
        double[] im = new double[N];
        for (int t = 0; t < frames; t++) {
            int at = t * HOP;
            for (int i = 0; i < N; i++) { re[i] = x[at + i] * win[i]; im[i] = 0; }
            fft(re, im);
            int o = t * NB;
            for (int f = 0; f < NB; f++) {
                int b = f + FMIN;
                s[o + f] = (float) Math.log(re[b] * re[b] + im[b] * im[b] + 1e-9);
            }
        }
        return s;
    }

    /** Pics : plus forts que tout leur voisinage, assez au-dessus du silence. */
    private static int[] peaks(float[] s, int frames) {
        float top = -Float.MAX_VALUE;
        for (float v : s) if (v > top) top = v;
        final float floor = top - (float) Math.log(1e6); // 60 dB sous le plus fort
        // maximum glissant en fréquence, puis en temps
        float[] mf = new float[s.length];
        for (int t = 0; t < frames; t++) {
            int o = t * NB;
            for (int f = 0; f < NB; f++) {
                float m = -Float.MAX_VALUE;
                for (int g = Math.max(0, f - FW); g <= Math.min(NB - 1, f + FW); g++) m = Math.max(m, s[o + g]);
                mf[o + f] = m;
            }
        }
        int perBlock = PER_SEC; // un bloc = 43 pas = 1 s
        int[] out = new int[Math.max(16, frames * PER_SEC / 40)];
        int count = 0;
        int blockLen = 43;
        int[] cand = new int[blockLen * NB];
        float[] candV = new float[blockLen * NB];
        for (int b0 = 0; b0 < frames; b0 += blockLen) {
            int nc = 0;
            for (int t = b0; t < Math.min(frames, b0 + blockLen); t++) {
                for (int f = 0; f < NB; f++) {
                    float v = s[t * NB + f];
                    if (v < floor || v < mf[t * NB + f]) continue;
                    boolean ok = true;
                    for (int u = Math.max(0, t - TW); u <= Math.min(frames - 1, t + TW) && ok; u++) {
                        if (u != t && mf[u * NB + f] >= v) ok = false;
                    }
                    if (!ok) continue;
                    cand[nc] = t * NB + f;
                    candV[nc] = v;
                    nc++;
                }
            }
            // les plus forts du bloc seulement (densité régulière)
            int keep = Math.min(nc, perBlock);
            Integer[] idx = new Integer[nc];
            for (int i = 0; i < nc; i++) idx[i] = i;
            final float[] cv = candV;
            Arrays.sort(idx, (a, c) -> Float.compare(cv[c], cv[a]));
            for (int i = 0; i < keep; i++) {
                if (count == out.length) out = Arrays.copyOf(out, out.length * 2);
                out[count++] = cand[idx[i]];
            }
        }
        int[] p = Arrays.copyOf(out, count);
        Arrays.sort(p); // par instant, puis fréquence
        return p;
    }

    private static long[] hashes(int[] p) {
        long[] k = new long[p.length * FAN];
        int n = 0;
        for (int i = 0; i < p.length; i++) {
            int t1 = p[i] / NB;
            int f1 = p[i] % NB;
            int fan = 0;
            for (int j = i + 1; j < p.length && fan < FAN; j++) {
                int t2 = p[j] / NB;
                int dt = t2 - t1;
                if (dt < 1) continue;
                if (dt > DT_MAX) break;
                int f2 = p[j] % NB;
                if (Math.abs(f2 - f1) > DF_MAX) continue;
                long h = ((long) f1 << 15) | ((long) f2 << 6) | dt;
                k[n++] = (h << 32) | t1;
                fan++;
            }
        }
        long[] r = Arrays.copyOf(k, n);
        Arrays.sort(r);
        return r;
    }

    // ------------------------------------------------------------------ comparaison

    static final class Match {
        int score;        // codes retrouvés au meilleur décalage
        int hashes;       // codes du morceau
        double offset;    // le morceau = la prod décalée de tant de secondes
        double ratio;     // score / codes du morceau
        int spread;       // secondes du morceau couvertes par les codes retrouvés
        boolean same;     // c'est la même prod
    }

    /** Le morceau {@code song} contient-il la prod {@code prod} ? */
    static Match compare(SoundPrint prod, SoundPrint song) {
        Match m = new Match();
        m.hashes = song.keys.length;
        if (prod.keys.length == 0 || song.keys.length == 0) return m;
        int span = prod.frames + song.frames + 1;
        int[] hist = new int[span];
        long[] pk = prod.keys;
        int i = 0;
        long[] sk = fuzzy(song.keys);
        int j = 0;
        while (i < pk.length && j < sk.length) {
            long hp = pk[i] >>> 32;
            long hs = sk[j] >>> 32;
            if (hp < hs) { i++; continue; }
            if (hs < hp) { j++; continue; }
            int i2 = i;
            while (i2 < pk.length && (pk[i2] >>> 32) == hp) i2++;
            int j2 = j;
            while (j2 < sk.length && (sk[j2] >>> 32) == hs) j2++;
            // code trop courant dans la prod (une frappe répétée) : il ne dit rien
            if (i2 - i <= CAP) {
                for (int a = j; a < j2; a++) {
                    int ts = (int) sk[a];
                    for (int b = i; b < i2; b++) hist[ts - (int) pk[b] + prod.frames]++;
                }
            }
            i = i2;
            j = j2;
        }
        int best = 0;
        int at = 0;
        for (int o = 1; o < span - 1; o++) {
            int v = hist[o - 1] + hist[o] + hist[o + 1];
            if (v > best) { best = v; at = o; }
        }
        m.score = best;
        int off = at - prod.frames;
        m.offset = off * (double) HOP / SR;
        m.ratio = best / (double) m.hashes;
        // les codes retrouvés couvrent-ils une bonne partie du morceau ? (pas un seul bruit)
        boolean[] sec = new boolean[song.frames / 43 + 2];
        i = 0;
        j = 0;
        while (i < pk.length && j < sk.length) {
            long hp = pk[i] >>> 32;
            long hs = sk[j] >>> 32;
            if (hp < hs) { i++; continue; }
            if (hs < hp) { j++; continue; }
            int i2 = i;
            while (i2 < pk.length && (pk[i2] >>> 32) == hp) i2++;
            int j2 = j;
            while (j2 < sk.length && (sk[j2] >>> 32) == hs) j2++;
            if (i2 - i <= CAP) {
                for (int a = j; a < j2; a++) {
                    int ts = (int) sk[a];
                    for (int b = i; b < i2; b++) {
                        if (Math.abs(ts - (int) pk[b] - off) <= 1) sec[ts / 43] = true;
                    }
                }
            }
            i = i2;
            j = j2;
        }
        int spread = 0;
        for (boolean b : sec) if (b) spread++;
        m.spread = spread;
        m.same = isSame(m, song.frames);
        return m;
    }

    /**
     * Seuils réglés sur des essais (prods synthétiques, voix par-dessus, réencodage AAC / Opus,
     * et pièges : autre prod avec la même batterie, le même tempo et la même clé). Les vrais
     * morceaux font de 0,017 à 0,15, les pièges 0,011 au plus
     * (0,014 sur 30 s d'extrait) : dans le doute, « pas sûr ».
     */
    static boolean isSame(Match m, int songFrames) {
        double secs = songFrames * (double) HOP / SR;
        // sur un court extrait, le hasard pèse plus : plus exigeant
        double need = secs >= 60 ? 0.014 : 0.02;
        return m.score >= 50 && m.ratio >= need && m.spread >= Math.min(15, secs * 0.3);
    }

    /**
     * Les pics d'une même note peuvent tomber un pas plus tôt ou plus tard d'un enregistrement
     * à l'autre : on cherche aussi chaque code avec l'écart d'un pas en plus ou en moins.
     */
    private static long[] fuzzy(long[] keys) {
        long[] out = new long[keys.length * 3];
        int n = 0;
        for (long k : keys) {
            long h = k >>> 32;
            long t = k & 0xffffffffL;
            int dt = (int) (h & 63);
            out[n++] = k;
            if (dt > 1) out[n++] = ((h - 1) << 32) | t;
            if (dt < DT_MAX) out[n++] = ((h + 1) << 32) | t;
        }
        long[] r = Arrays.copyOf(out, n);
        Arrays.sort(r);
        return r;
    }

    // ------------------------------------------------------------------ FFT

    private static void fft(double[] re, double[] im) {
        int n = re.length;
        for (int i = 1, j = 0; i < n; i++) {
            int bit = n >> 1;
            for (; (j & bit) != 0; bit >>= 1) j ^= bit;
            j ^= bit;
            if (i < j) {
                double t = re[i]; re[i] = re[j]; re[j] = t;
                t = im[i]; im[i] = im[j]; im[j] = t;
            }
        }
        for (int len = 2; len <= n; len <<= 1) {
            double ang = -2 * Math.PI / len;
            double wr = Math.cos(ang);
            double wi = Math.sin(ang);
            for (int i = 0; i < n; i += len) {
                double cr = 1;
                double ci = 0;
                for (int k = 0; k < len / 2; k++) {
                    int a = i + k;
                    int b = a + len / 2;
                    double xr = re[b] * cr - im[b] * ci;
                    double xi = re[b] * ci + im[b] * cr;
                    re[b] = re[a] - xr; im[b] = im[a] - xi;
                    re[a] += xr; im[a] += xi;
                    double nr = cr * wr - ci * wi;
                    ci = cr * wi + ci * wr;
                    cr = nr;
                }
            }
        }
    }

    // ------------------------------------------------------------------ rééchantillonnage

    /**
     * Passe un son de n'importe quelle fréquence (44,1 / 48 kHz…) à {@link #SR} Hz, échantillon
     * par échantillon (pas tout le morceau en mémoire), avec un vrai filtre (sinc fenêtré) :
     * les cymbales ne se replient pas dans les notes.
     */
    static final class Resampler {
        private static final int TAB = 256;
        private final double step;      // échantillons d'entrée par échantillon de sortie
        private final int half;
        private final float[] table;    // filtre, échantillonné tous les 1/TAB
        private float[] buf = new float[1 << 14];
        private int len = 0;
        private long base = 0;          // indice absolu de buf[0]
        private double pos = 0;
        private final float[] out;
        private int n = 0;

        Resampler(int inRate, int maxOutSamples) {
            step = inRate / (double) SR;
            double scale = Math.min(1.0, SR / (double) inRate) * 0.9;
            half = (int) Math.ceil(7 / scale);
            table = new float[(half + 1) * TAB + 1];
            for (int i = 0; i < table.length; i++) {
                double d = i / (double) TAB;
                double u = scale * d;
                double sinc = u == 0 ? 1 : Math.sin(Math.PI * u) / (Math.PI * u);
                double w = d >= half ? 0 : 0.42 + 0.5 * Math.cos(Math.PI * d / half) + 0.08 * Math.cos(2 * Math.PI * d / half);
                table[i] = (float) (scale * sinc * w);
            }
            out = new float[Math.max(1, maxOutSamples)];
        }

        boolean full() { return n >= out.length; }

        void push(float v) {
            if (n >= out.length) return;
            if (len == buf.length) compact();
            buf[len++] = v;
            while (n < out.length && pos + half < base + len) emit();
        }

        private void compact() {
            long keepFrom = Math.max(base, (long) Math.floor(pos) - half - 1);
            int drop = (int) (keepFrom - base);
            if (drop <= 0) { buf = Arrays.copyOf(buf, buf.length * 2); return; }
            System.arraycopy(buf, drop, buf, 0, len - drop);
            len -= drop;
            base += drop;
        }

        private void emit() {
            long i0 = Math.max(base, (long) Math.ceil(pos - half));
            long i1 = (long) Math.floor(pos + half);
            float acc = 0;
            int k = (int) (i0 - base);
            float d = (float) ((i0 - pos) * TAB);
            for (long i = i0; i <= i1; i++, k++, d += TAB) {
                int t = (int) (d < 0 ? -d : d);
                acc += buf[k] * table[t];
            }
            out[n++] = acc;
            pos += step;
        }

        int length() { return n; }

        float[] samples() { return out; }
    }
}
