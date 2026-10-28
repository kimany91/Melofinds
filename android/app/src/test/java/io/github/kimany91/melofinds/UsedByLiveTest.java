package io.github.kimany91.melofinds;

import static org.junit.Assume.assumeTrue;

import java.util.List;

import org.junit.Test;

/**
 * Vraie recherche YouTube / SoundCloud (réseau) : seulement avec MF_LIVE=1, pour voir sur
 * GitHub que NewPipe répond bien. N'empêche jamais de construire l'APK.
 */
public class UsedByLiveTest {

    private static void show(String service, String q) throws Exception {
        List<UsedBy.Hit> hits = UsedBy.search(service, q, 10);
        System.out.println("== " + service + " « " + q + " » : " + hits.size() + " résultats");
        for (int i = 0; i < Math.min(5, hits.size()); i++) {
            UsedBy.Hit h = hits.get(i);
            System.out.println("   " + (h.id != null ? h.id : h.url) + " | " + h.title + " | " + h.uploader + " | " + h.duration + " s | " + h.views + " vues");
        }
    }

    @Test
    public void rechercheYouTube() throws Exception {
        assumeTrue("1".equals(System.getenv("MF_LIVE")));
        show("yt", "prod. Pyrex Whippa");
    }

    @Test
    public void rechercheSoundCloud() throws Exception {
        assumeTrue("1".equals(System.getenv("MF_LIVE")));
        show("sc", "prod by Pyrex");
    }
}
