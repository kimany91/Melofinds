package io.github.kimany91.melofinds;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.io.File;
import java.io.FileInputStream;
import java.util.List;

import org.junit.Assume;
import org.junit.Test;

public class YtAudioTest {

    @Test
    public void refuseLesIdentifiantsBizarres() {
        assertFalse(YtAudio.VIDEO_ID.matcher("../../etc").matches());
        assertFalse(YtAudio.VIDEO_ID.matcher("abc").matches());
        assertTrue(YtAudio.VIDEO_ID.matcher("jNQXAC9IVRw").matches());
        assertEquals(1234L, YtAudio.clen("https://x.googlevideo.com/videoplayback?itag=140&clen=1234&dur=1"));
        assertEquals(0L, YtAudio.clen("https://x.googlevideo.com/videoplayback?itag=140"));
    }

    /** Vraie vidéo YouTube : seulement si MF_NET_TEST=1 (réseau). */
    @Test
    public void sonDUneVraieVideo() throws Exception {
        Assume.assumeTrue("1".equals(System.getenv("MF_NET_TEST")));
        // sur un ordinateur, Java bloque l'en-tête Origin que NewPipe envoie (pas sur Android)
        System.setProperty("sun.net.http.allowRestrictedHeaders", "true");
        String id = System.getenv().getOrDefault("MF_NET_VIDEO", "jNQXAC9IVRw");
        long t0 = System.currentTimeMillis();
        List<YtAudio.Pick> picks = YtAudio.streams(id);
        long t1 = System.currentTimeMillis();
        YtAudio.Pick p = picks.get(0);
        System.out.println("flux : " + picks.size() + " ; choisi " + p.format + " " + p.bitrate / 1000 + " kb/s, " + p.length + " octets, trouvé en " + (t1 - t0) + " ms");
        File f = File.createTempFile("yt", "." + p.format);
        try {
            long n = YtAudio.download(p, f);
            long t2 = System.currentTimeMillis();
            System.out.println("téléchargé " + n + " octets en " + (t2 - t1) + " ms (total " + (t2 - t0) + " ms)");
            assertTrue(n > 10000);
            byte[] head = new byte[12];
            try (FileInputStream in = new FileInputStream(f)) { assertEquals(12, in.read(head)); }
            String h = new String(head, 4, 4, "ISO-8859-1");
            // MP4 (« ftyp ») ou WebM (EBML 1A 45 DF A3)
            assertTrue("en-tête inattendu", "ftyp".equals(h) || (head[0] == 0x1A && head[1] == 0x45));
        } finally {
            f.delete();
        }
    }
}
