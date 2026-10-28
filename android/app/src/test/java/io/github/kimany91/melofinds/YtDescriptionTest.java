package io.github.kimany91.melofinds;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class YtDescriptionTest {

    @Test
    public void refuseLesIdentifiantsBizarres() {
        assertFalse(YtDescription.VIDEO_ID.matcher("../../etc").matches());
        assertFalse(YtDescription.VIDEO_ID.matcher("abc").matches());
        assertTrue(YtDescription.VIDEO_ID.matcher("jNQXAC9IVRw").matches());
        assertNull(YtDescription.description("../etc"));
    }

    @Test
    public void descriptionDeLaPage() {
        assertEquals("FREE & more\nBPM: 140\n\"Key\" / C#m", YtDescription.unescapeJson("FREE \\u0026 more\\nBPM: 140\\n\\\"Key\\\" \\/ C#m"));
        assertEquals("FREE for profit\nYT & SC only <3", YtDescription.htmlToText("FREE <b>for</b> profit<br>YT &amp; SC only &lt;3"));
    }
}
