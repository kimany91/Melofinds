package io.github.kimany91.melofinds;

import org.schabi.newpipe.extractor.ListExtractor;
import org.schabi.newpipe.extractor.Page;
import org.schabi.newpipe.extractor.ServiceList;
import org.schabi.newpipe.extractor.playlist.PlaylistExtractor;
import org.schabi.newpipe.extractor.stream.StreamInfoItem;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Vidéos d'une playlist YouTube, lues depuis le téléphone (NewPipe Extractor, sans clé). Les
 * playlists non répertoriées marchent aussi : il suffit du lien. Pas d'Android ici.
 */
final class YtPlaylist {

    /** Identifiant de playlist (pas les « mix » automatiques RD…). */
    static final Pattern LIST_ID = Pattern.compile("^(?!RD|UL)[A-Za-z0-9_-]{10,64}$");
    private static final Pattern VIDEO = Pattern.compile("[?&]v=([A-Za-z0-9_-]{11})");
    /** Au plus : assez pour une grosse playlist de prods, pas une liste sans fin. */
    static final int MAX = 500;

    private YtPlaylist() { }

    static final class Video {
        String id;
        String title;
        long duration;
        long views;
        String uploader;
        String uploaderUrl;
    }

    static final class Result {
        String name = "";
        String uploader = "";
        long count = -1;
        final List<Video> items = new ArrayList<>();
        boolean more;
    }

    static Result fetch(String listId) throws Exception {
        if (listId == null || !LIST_ID.matcher(listId).matches()) throw new IllegalArgumentException("playlist invalide");
        YtDescription.init();
        PlaylistExtractor ex = ServiceList.YouTube.getPlaylistExtractor("https://www.youtube.com/playlist?list=" + listId);
        ex.fetchPage();
        Result r = new Result();
        try { r.name = cut(ex.getName(), 150); } catch (Exception ignored) { }
        try { r.uploader = cut(ex.getUploaderName(), 100); } catch (Exception ignored) { }
        try { r.count = ex.getStreamCount(); } catch (Exception ignored) { }
        ListExtractor.InfoItemsPage<StreamInfoItem> page = ex.getInitialPage();
        java.util.Set<String> seen = new java.util.HashSet<>();
        boolean stopped = false;
        for (int guard = 0; guard < 30; guard++) {
            for (StreamInfoItem it : page.getItems()) {
                if (r.items.size() >= MAX) break;
                Matcher m = VIDEO.matcher(it.getUrl() == null ? "" : it.getUrl());
                if (!m.find() || !seen.add(m.group(1))) continue;
                Video v = new Video();
                v.id = m.group(1);
                v.title = cut(it.getName(), 200);
                v.duration = it.getDuration();
                v.views = it.getViewCount();
                v.uploader = cut(it.getUploaderName(), 100);
                v.uploaderUrl = cut(it.getUploaderUrl(), 300);
                r.items.add(v);
            }
            if (r.items.size() >= MAX || !page.hasNextPage()) break;
            Page next = page.getNextPage();
            try {
                page = ex.getPage(next);
            } catch (Exception e) {  // la suite ne vient pas : on garde ce qu'on a
                stopped = true;
                break;
            }
        }
        r.more = stopped || r.items.size() >= MAX;
        return r;
    }

    private static String cut(String s, int n) {
        if (s == null) return "";
        return s.length() > n ? s.substring(0, n) : s;
    }
}
