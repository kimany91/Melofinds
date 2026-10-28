package io.github.kimany91.melofinds;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.util.Random;

import org.junit.Test;

/**
 * L'empreinte reconnaît une prod dans un morceau (voix par-dessus, autre volume, autre
 * fréquence d'échantillonnage) et ne se laisse pas avoir par une autre prod qui a la même
 * batterie, le même tempo et la même clé.
 */
public class SoundPrintTest {

    static final int RATE = 44100;

    /** Petite prod : accords, mélodie, 808, kick / snare / charley (même batterie si drumSeed égal). */
    static float[] beat(long seed, long drumSeed, double secs, int rate) {
        Random r = new Random(seed);
        Random dr = new Random(drumSeed);
        int n = (int) (secs * rate);
        float[] x = new float[n];
        double bpm = 140;
        double beatS = 60 / bpm;
        int[] minor = { 0, 2, 3, 5, 7, 8, 10 };
        int[] prog = new int[4];
        for (int i = 0; i < 4; i++) prog[i] = minor[r.nextInt(7)];
        int[] mel = new int[16];
        for (int i = 0; i < 16; i++) mel[i] = minor[r.nextInt(7)] + 12 * r.nextInt(2);
        float[] snare = new float[(int) (0.2 * rate)];
        for (int i = 0; i < snare.length; i++) snare[i] = (float) ((dr.nextGaussian() * 0.6 + Math.sin(2 * Math.PI * 190 * i / rate)) * Math.exp(-i / (double) rate * 18));
        double bar = 4 * beatS;
        for (int b = 0; b * bar < secs; b++) {
            double t0 = b * bar;
            double f = 220 * Math.pow(2, prog[b % 4] / 12.0);
            for (int k = 0; k < 3; k++) add(x, rate, t0, bar, f * Math.pow(2, new int[] { 0, 3, 7 }[k] / 12.0), 0.12, 0.7);
            for (int i = 0; i < 16; i++) if (i % 3 == 0) add(x, rate, t0 + i * beatS / 4, 0.4, 880 * Math.pow(2, mel[i] / 12.0), 0.15, 5);
            add(x, rate, t0, bar * 0.9, f / 4, 0.3, 1.2);
            for (int s = 0; s < 4; s++) add(x, rate, t0 + s * beatS, 0.3, 50, 0.4, 10);
            for (int s : new int[] { 1, 3 }) mix(x, snare, (int) ((t0 + s * beatS) * rate), 0.3f);
        }
        return x;
    }

    static void add(float[] x, int rate, double at, double dur, double f, double g, double decay) {
        int a = (int) (at * rate);
        int len = (int) (dur * rate);
        for (int i = 0; i < len && a + i < x.length; i++) {
            double t = i / (double) rate;
            x[a + i] += (float) (g * Math.sin(2 * Math.PI * f * t) * Math.exp(-t * decay) * Math.min(1, t * 200));
        }
    }

    static void mix(float[] x, float[] s, int at, float g) {
        for (int i = 0; i < s.length && at + i < x.length; i++) x[at + i] += g * s[i];
    }

    /** « Voix » : un son riche qui glisse, coupé en syllabes. */
    static float[] voice(long seed, int n, int rate) {
        Random r = new Random(seed);
        float[] v = new float[n];
        double f0 = 150;
        double ph = 0;
        for (int i = 0; i < n; i++) {
            if (i % (rate / 6) == 0) f0 = 110 + r.nextInt(120);
            ph += 2 * Math.PI * f0 / rate;
            double s = 0;
            for (int h = 1; h < 12; h++) s += Math.sin(h * ph) / h;
            double env = Math.pow(Math.sin(Math.PI * (i % (rate / 6)) / (rate / 6.0)), 0.7);
            v[i] = (float) (s * env * 0.35);
        }
        return v;
    }

    static SoundPrint print(float[] x, int from, int to, int rate) {
        SoundPrint.Resampler rs = new SoundPrint.Resampler(rate, (int) ((to - from) / (double) rate * SoundPrint.SR) + 8);
        for (int i = from; i < to; i++) rs.push(x[i]);
        return SoundPrint.of(rs.samples(), rs.length());
    }

    @Test
    public void reconnaitLaProdSousLaVoix() {
        float[] prod = beat(1, 9, 100, RATE);
        SoundPrint p = print(prod, 0, prod.length, RATE);
        // le morceau : la prod 12 s plus loin (et pas pile sur un pas d'analyse), plus basse,
        // voix par-dessus, saturée
        int from = 12 * RATE + 97;
        int n = 70 * RATE; // l'appli compare 90 s de chaque morceau
        float[] song = new float[n];
        float[] v = voice(5, n, RATE);
        for (int i = 0; i < n; i++) song[i] = (float) Math.tanh(0.5 * prod[from + i] + 0.4 * v[i]);
        SoundPrint.Match m = SoundPrint.compare(p, print(song, 0, n, RATE));
        assertTrue("score " + m.score + " ratio " + m.ratio, m.same);
        // la prod commence 12 s avant le morceau (à un tour de boucle près : une mesure = 1,71 s)
        double loop = 4 * 60 / 140.0;
        double d = Math.abs(-12 - m.offset) % loop;
        assertTrue("décalage " + m.offset, Math.min(d, loop - d) < 0.1);
    }

    @Test
    public void reconnaitLaProdA48kHz() {
        float[] prod = beat(1, 9, 60, RATE);
        SoundPrint p = print(prod, 0, prod.length, RATE);
        // même prod refaite à 48 kHz (comme une vidéo en Opus) : la caisse claire n'a pas
        // exactement le même bruit, le reste est pareil
        float[] p48 = beat(1, 9, 60, 48000);
        int n = 35 * 48000;
        float[] song = new float[n];
        for (int i = 0; i < n; i++) song[i] = 0.7f * p48[12 * 48000 + i];
        assertTrue(SoundPrint.compare(p, print(song, 0, n, 48000)).same);
    }

    @Test
    public void autreProdMemeBatterie() {
        float[] prod = beat(1, 9, 100, RATE);
        SoundPrint p = print(prod, 0, prod.length, RATE);
        int n = 70 * RATE;
        float[] other = beat(2, 9, 75, RATE);
        float[] v = voice(6, n, RATE);
        float[] song = new float[n];
        for (int i = 0; i < n; i++) song[i] = (float) Math.tanh(0.5 * other[i] + v[i]);
        SoundPrint.Match m = SoundPrint.compare(p, print(song, 0, n, RATE));
        assertFalse("score " + m.score + " ratio " + m.ratio, m.same);
    }

    @Test
    public void silenceEtSonTropCourt() {
        float[] prod = beat(1, 9, 30, RATE);
        SoundPrint p = print(prod, 0, prod.length, RATE);
        float[] silence = new float[20 * RATE];
        assertFalse(SoundPrint.compare(p, print(silence, 0, silence.length, RATE)).same);
        SoundPrint tiny = print(prod, 0, 1000, RATE);
        assertEquals(0, tiny.size());
        assertFalse(SoundPrint.compare(p, tiny).same);
    }

    @Test
    public void reechantillonnageGardeLaNote() {
        // un la (440 Hz) à 48 kHz reste un la à 11 025 Hz ; un 9 kHz (au-dessus) disparaît
        int n = 48000;
        SoundPrint.Resampler a = new SoundPrint.Resampler(48000, 20000);
        SoundPrint.Resampler b = new SoundPrint.Resampler(48000, 20000);
        for (int i = 0; i < n; i++) {
            a.push((float) Math.sin(2 * Math.PI * 440 * i / 48000.0));
            b.push((float) Math.sin(2 * Math.PI * 9000 * i / 48000.0));
        }
        float[] x = a.samples();
        int len = a.length();
        assertTrue(Math.abs(len - SoundPrint.SR) < 200);
        int cross = 0;
        for (int i = 1000; i < len - 1000; i++) if (x[i - 1] < 0 && x[i] >= 0) cross++;
        double f = cross / ((len - 2000) / (double) SoundPrint.SR);
        assertEquals(440, f, 3);
        double e = 0;
        for (int i = 1000; i < b.length() - 1000; i++) e += b.samples()[i] * b.samples()[i];
        assertTrue("9 kHz pas filtré : " + e, e / (b.length() - 2000) < 0.01);
    }
}
