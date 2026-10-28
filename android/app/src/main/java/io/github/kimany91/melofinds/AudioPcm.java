package io.github.kimany91.melofinds;

import android.media.AudioFormat;
import android.media.MediaCodec;
import android.media.MediaExtractor;
import android.media.MediaFormat;

import java.io.BufferedOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;

/**
 * Décode le son téléchargé (AAC / Opus) avec le décodeur d'Android : en WAV mono 16 bits à la
 * fréquence d'origine (un fichier « normal » pour Tunebat Analyzer), ou en empreinte sonore
 * (pour savoir si un morceau est posé sur la prod).
 */
final class AudioPcm {

    static final class Out {
        int rate;
        int rateReported; // fréquence annoncée par le décodeur
        int rateMeasured; // fréquence mesurée (échantillons / temps réel)
        double seconds;   // durée gardée
        double duration;  // durée du morceau
    }

    /** Reçoit le son décodé, en mono, échantillon par échantillon. */
    private interface Sink {
        /** Fréquence annoncée par le décodeur (peut arriver avant le premier échantillon). */
        void rate(int rate, double keepSec);
        void sample(float v);
        int count();
    }

    private AudioPcm() { }

    // ------------------------------------------------------------------ WAV (Tunebat)

    /** Tout le morceau (10 min au plus), à la fréquence d'origine. */
    static Out toWav(File src, File dest) throws IOException {
        return toWav(src, dest, 600, 1);
    }

    /** {@code step} : 1 = fréquence d'origine, 0 = réduite à ~22–24 kHz. */
    static Out toWav(File src, File dest, double windowSec, int stepWanted) throws IOException {
        final class Wav implements Sink {
            short[] pcm = new short[0];
            int n = 0;
            int step = 1;
            float acc = 0;
            int accN = 0;

            @Override public void rate(int rate, double keepSec) {
                if (n > 0) return;
                step = stepWanted > 0 ? stepWanted : rate >= 32000 ? 2 : 1;
                pcm = new short[(int) (keepSec * rate / step) + rate];
            }

            @Override public void sample(float v) {
                acc += v;
                if (++accN == step) {
                    if (n < pcm.length) {
                        float x = Math.max(-1f, Math.min(1f, acc / step));
                        pcm[n++] = (short) Math.round(x * 32767f);
                    }
                    acc = 0;
                    accN = 0;
                }
            }

            @Override public int count() { return n * step; }
        }
        Wav w = new Wav();
        Out o = decode(src, windowSec, w);
        if (w.n < o.rateReported / w.step * 5) throw new IOException("son trop court");
        int realRate = o.rateReported;
        if (o.rateMeasured > 0 && Math.abs(o.rateMeasured / (double) o.rateReported - 1) > 0.03) realRate = nearestRate(o.rateMeasured);
        int outRate = Math.round(realRate / (float) w.step);
        writeWav(dest, w.pcm, w.n, outRate);
        o.rate = outRate;
        o.seconds = w.n / (double) outRate;
        return o;
    }

    // ------------------------------------------------------------------ empreinte

    /** Empreinte sonore de {@code windowSec} secondes au milieu du son. */
    static SoundPrint print(File src, double windowSec) throws IOException {
        final class Prints implements Sink {
            SoundPrint.Resampler rs;
            int seen = 0;

            @Override public void rate(int rate, double keepSec) {
                if (seen > 0 && rs != null) return;
                rs = new SoundPrint.Resampler(rate, (int) (keepSec * SoundPrint.SR) + SoundPrint.SR);
            }

            @Override public void sample(float v) {
                seen++;
                if (rs != null) rs.push(v);
            }

            @Override public int count() { return seen; }
        }
        Prints p = new Prints();
        Out o = decode(src, windowSec, p);
        if (p.rs == null || p.rs.length() < SoundPrint.SR * 5) throw new IOException("son trop court");
        // un décodeur qui annonce la mauvaise fréquence fausserait tout : on ne compare pas
        if (o.rateMeasured > 0 && Math.abs(o.rateMeasured / (double) o.rateReported - 1) > 0.03) throw new IOException("vitesse du son douteuse");
        return SoundPrint.of(p.rs.samples(), p.rs.length());
    }

    // ------------------------------------------------------------------ décodage

    /** Décode {@code windowSec} secondes au milieu du son (tout s'il est plus court). */
    private static Out decode(File src, double windowSec, Sink sink) throws IOException {
        MediaExtractor ex = new MediaExtractor();
        MediaCodec dec = null;
        try {
            ex.setDataSource(src.getAbsolutePath());
            int track = -1;
            MediaFormat fmt = null;
            for (int i = 0; i < ex.getTrackCount(); i++) {
                MediaFormat f = ex.getTrackFormat(i);
                String mime = f.getString(MediaFormat.KEY_MIME);
                if (mime != null && mime.startsWith("audio/")) { track = i; fmt = f; break; }
            }
            if (track < 0) throw new IOException("pas de piste audio");
            ex.selectTrack(track);
            long durUs = fmt.containsKey(MediaFormat.KEY_DURATION) ? fmt.getLong(MediaFormat.KEY_DURATION) : 0;
            long winUs = (long) (windowSec * 1e6);
            long startUs = durUs > winUs ? (durUs - winUs) / 2 : 0;
            long endUs = startUs + winUs;
            if (startUs > 0) ex.seekTo(startUs, MediaExtractor.SEEK_TO_PREVIOUS_SYNC);

            dec = MediaCodec.createDecoderByType(fmt.getString(MediaFormat.KEY_MIME));
            dec.configure(fmt, null, null, 0);
            dec.start();

            int rate = fmt.getInteger(MediaFormat.KEY_SAMPLE_RATE);
            int ch = fmt.getInteger(MediaFormat.KEY_CHANNEL_COUNT);
            int enc = AudioFormat.ENCODING_PCM_16BIT;
            // durée connue : tampon à la bonne taille (pas 10 min de mémoire pour une prod de 3 min)
            double keep = durUs > 0 ? Math.min(windowSec, durUs / 1e6 + 2) : windowSec;
            sink.rate(rate, keep);
            boolean inDone = false;
            boolean outDone = false;
            MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
            long guard = System.currentTimeMillis() + 90000;
            // contrôle de vitesse : un son lu à la mauvaise fréquence fausse la clé et le BPM
            long firstPts = -1;
            long lastPts = -1;
            long framesBeforeLast = 0;
            long framesTotal = 0;

            while (!outDone) {
                if (System.currentTimeMillis() > guard) throw new IOException("décodage trop long");
                if (!inDone) {
                    int ii = dec.dequeueInputBuffer(10000);
                    if (ii >= 0) {
                        ByteBuffer ib = dec.getInputBuffer(ii);
                        int size = ib == null ? -1 : ex.readSampleData(ib, 0);
                        if (size < 0 || ex.getSampleTime() > endUs + 500000) {
                            dec.queueInputBuffer(ii, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM);
                            inDone = true;
                        } else {
                            dec.queueInputBuffer(ii, 0, size, ex.getSampleTime(), 0);
                            ex.advance();
                        }
                    }
                }
                int oi = dec.dequeueOutputBuffer(info, 10000);
                if (oi == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    MediaFormat of = dec.getOutputFormat();
                    rate = of.getInteger(MediaFormat.KEY_SAMPLE_RATE);
                    ch = of.getInteger(MediaFormat.KEY_CHANNEL_COUNT);
                    if (of.containsKey(MediaFormat.KEY_PCM_ENCODING)) enc = of.getInteger(MediaFormat.KEY_PCM_ENCODING);
                    if (sink.count() == 0) sink.rate(rate, keep);
                    continue;
                }
                if (oi < 0) continue;
                if ((info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0) outDone = true;
                ByteBuffer ob = dec.getOutputBuffer(oi);
                if (ob != null && info.size > 0) {
                    ob.position(info.offset);
                    ob.limit(info.offset + info.size);
                    ByteBuffer b = ob.slice().order(ByteOrder.nativeOrder());
                    boolean isFloat = enc == AudioFormat.ENCODING_PCM_FLOAT;
                    int bytes = isFloat ? 4 : 2;
                    int frames = info.size / (bytes * ch);
                    if (firstPts < 0) firstPts = info.presentationTimeUs;
                    lastPts = info.presentationTimeUs;
                    framesBeforeLast = framesTotal;
                    framesTotal += frames;
                    double usPerFrame = 1e6 / rate;
                    for (int f = 0; f < frames; f++) {
                        long t = info.presentationTimeUs + (long) (f * usPerFrame);
                        if (t >= endUs) { outDone = true; break; }
                        if (t < startUs) continue;
                        float m = 0;
                        for (int c = 0; c < ch; c++) {
                            int at = (f * ch + c) * bytes;
                            m += isFloat ? b.getFloat(at) : b.getShort(at) / 32768f;
                        }
                        sink.sample(m / ch);
                    }
                }
                dec.releaseOutputBuffer(oi, false);
            }
            int measured = 0;
            if (lastPts - firstPts > 2_000_000 && framesBeforeLast > 0) {
                measured = (int) Math.round(framesBeforeLast / ((lastPts - firstPts) / 1e6));
            }
            Out o = new Out();
            o.rateReported = rate;
            o.rateMeasured = measured;
            o.duration = durUs / 1e6;
            return o;
        } finally {
            if (dec != null) {
                try { dec.stop(); } catch (Exception ignored) { }
                dec.release();
            }
            ex.release();
        }
    }

    private static int nearestRate(int r) {
        int best = r;
        int[] std = { 8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000, 88200, 96000 };
        double d = 1e9;
        for (int s : std) {
            double e = Math.abs(Math.log(r / (double) s));
            if (e < d) { d = e; best = s; }
        }
        return d < 0.02 ? best : r;
    }

    private static void writeWav(File dest, short[] pcm, int n, int rate) throws IOException {
        ByteBuffer h = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN);
        int data = n * 2;
        h.put(new byte[] { 'R', 'I', 'F', 'F' }).putInt(36 + data).put(new byte[] { 'W', 'A', 'V', 'E' });
        h.put(new byte[] { 'f', 'm', 't', ' ' }).putInt(16).putShort((short) 1).putShort((short) 1)
            .putInt(rate).putInt(rate * 2).putShort((short) 2).putShort((short) 16);
        h.put(new byte[] { 'd', 'a', 't', 'a' }).putInt(data);
        ByteBuffer body = ByteBuffer.allocate(data).order(ByteOrder.LITTLE_ENDIAN);
        for (int i = 0; i < n; i++) body.putShort(pcm[i]);
        try (OutputStream os = new BufferedOutputStream(new FileOutputStream(dest))) {
            os.write(h.array());
            os.write(body.array());
        }
    }
}
