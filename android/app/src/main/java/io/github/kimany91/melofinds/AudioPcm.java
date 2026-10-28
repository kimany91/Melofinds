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
 * Décode un son (AAC / Opus…) avec le décodeur d'Android et en garde le milieu, en mono,
 * dans un petit WAV (16 bits, ~22–24 kHz) : c'est ce que l'app web analyse ensuite.
 */
final class AudioPcm {

    static final class Out {
        int rate;
        double seconds;   // durée gardée
        double duration;  // durée du morceau
    }

    private AudioPcm() { }

    static Out toWav(File src, File dest, double windowSec) throws IOException {
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
            int step = rate >= 32000 ? 2 : 1; // 44,1 / 48 kHz → 22 / 24 kHz : bien assez pour le BPM et la clé
            short[] pcm = new short[(int) (windowSec * rate / step) + rate];
            int n = 0;
            float acc = 0;
            int accN = 0;
            boolean inDone = false;
            boolean outDone = false;
            MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
            long guard = System.currentTimeMillis() + 30000;

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
                    int s2 = rate >= 32000 ? 2 : 1;
                    if (n == 0) {
                        step = s2;
                        pcm = new short[(int) (windowSec * rate / step) + rate];
                    }
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
                    double usPerFrame = 1e6 / rate;
                    for (int f = 0; f < frames; f++) {
                        long t = info.presentationTimeUs + (long) (f * usPerFrame);
                        if (t >= endUs) { outDone = true; break; }
                        float m = 0;
                        for (int c = 0; c < ch; c++) {
                            int at = (f * ch + c) * bytes;
                            m += isFloat ? b.getFloat(at) : b.getShort(at) / 32768f;
                        }
                        if (t < startUs) continue;
                        acc += m / ch;
                        if (++accN == step) {
                            if (n < pcm.length) {
                                float v = Math.max(-1f, Math.min(1f, acc / step));
                                pcm[n++] = (short) Math.round(v * 32767f);
                            }
                            acc = 0;
                            accN = 0;
                        }
                    }
                }
                dec.releaseOutputBuffer(oi, false);
            }
            if (n < rate / step * 5) throw new IOException("son trop court");
            int outRate = rate / step;
            writeWav(dest, pcm, n, outRate);
            Out o = new Out();
            o.rate = outRate;
            o.seconds = n / (double) outRate;
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
