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

    @Test
    public void playlist() throws Exception {
        assumeTrue("1".equals(System.getenv("MF_LIVE")));
        YtDescription.init();
        org.schabi.newpipe.extractor.search.SearchExtractor ex = org.schabi.newpipe.extractor.ServiceList.YouTube
            .getSearchExtractor("ninho type beat playlist", java.util.Collections.singletonList("playlists"), "");
        ex.fetchPage();
        String id = null;
        for (org.schabi.newpipe.extractor.InfoItem it : ex.getInitialPage().getItems()) {
            java.util.regex.Matcher m = java.util.regex.Pattern.compile("[?&]list=([A-Za-z0-9_-]+)").matcher(String.valueOf(it.getUrl()));
            if (m.find() && YtPlaylist.LIST_ID.matcher(m.group(1)).matches()) { id = m.group(1); break; }
        }
        System.out.println("== playlist trouvée : " + id);
        if (id == null) return;
        YtPlaylist.Result r = YtPlaylist.fetch(id);
        System.out.println("== « " + r.name + " » de " + r.uploader + " : " + r.items.size() + " vidéos (annoncées : " + r.count + ", suite coupée : " + r.more + ")");
        for (int i = 0; i < Math.min(3, r.items.size()); i++) System.out.println("   " + r.items.get(i).id + " | " + r.items.get(i).title + " | " + r.items.get(i).uploader);
    }
}
