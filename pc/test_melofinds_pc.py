import hashlib, hmac, importlib.util, json, tempfile, time, unittest
from pathlib import Path

import os, sys
os.environ.setdefault("MELOFINDS_HOME", tempfile.mkdtemp(prefix="mf-test-"))
sys.path.insert(0, str(Path(__file__).parent))
import mf_core as mpc
import mf_install as inst
KEY = "ab" * 32


def signed(payload, key=KEY):
    p = json.dumps(payload)
    return json.dumps({"p": p, "s": hmac.new(bytes.fromhex(key), p.encode(), hashlib.sha256).hexdigest()})


class Names(unittest.TestCase):
    def test_jamais_free(self):
        cases = {
            '[FREE FOR PROFIT] Lil Uzi Vert Type Beat - "bankroll"': "Lil Uzi Vert Type Beat - 'bankroll'",
            "(FREE) Luther x Summrs Type Beat": "Luther x Summrs Type Beat",
            "FREE Lucki Type Beat | Free For Profit": "Lucki Type Beat",
            "[FREE] FFP Pluggnb Type Beat": "Pluggnb Type Beat",
            "Free For Profit Beats - Dark Trap Type Beat": "Dark Trap Type Beat",
            'Lil Uzi Type Beat - "Free"': "Lil Uzi Type Beat",
            "Damso Type Beat (Free for non profit) 100% FREE": "Damso Type Beat",
            "Instru rap gratuite | Royalty Free": "Instru rap",
            "【FREE】 Yeat Type Beat": "Yeat Type Beat",
        }
        for inp, out in cases.items():
            self.assertEqual(mpc.clean_title(inp), out, inp)
            self.assertNotRegex(mpc.clean_title(inp).lower(), r"free|ffp|gratuit")

    def test_cle_et_bpm(self):
        self.assertEqual(mpc.build_name("[FREE] Luther Type Beat - TREE", "F# min", 140), "Luther Type Beat - TREE [F# min, 140 BPM]")
        self.assertEqual(mpc.build_name("Luther Type Beat", None, 150), "Luther Type Beat [150 BPM]")
        self.assertEqual(mpc.build_name("Luther Type Beat", "C maj", None), "Luther Type Beat [C maj]")
        self.assertEqual(mpc.build_name("Luther Type Beat"), "Luther Type Beat")

    def test_etiquette_licence(self):
        self.assertEqual(mpc.build_name("[FREE FOR PROFIT] Luther Type Beat - TREE", "F# min", 140, "ffp"), "Luther Type Beat - TREE [F# min, 140 BPM] [FFP]")
        self.assertEqual(mpc.build_name("(FREE) Damso Type Beat", None, None, "fnp"), "Damso Type Beat [F]")
        self.assertEqual(mpc.build_name("Luther Type Beat", None, 150, "upto", 5000), "Luther Type Beat [150 BPM] [FFP, UPTO 5000]")
        self.assertEqual(mpc.build_name("Luther Type Beat", None, None, "upto", "pas un nombre"), "Luther Type Beat [FFP, UPTO]")
        self.assertEqual(mpc.build_name("Luther Type Beat", None, None, "paid"), "Luther Type Beat")
        self.assertEqual(mpc.build_name("Luther Type Beat", None, None, "../../evil"), "Luther Type Beat")

    def test_caracteres_dangereux(self):
        n = mpc.build_name('..\\..\\Windows\\system32/evil:*?"<>|.exe')
        for ch in '\\/:*?"<>|':
            self.assertNotIn(ch, n)
        self.assertEqual(mpc.build_name("CON"), "Prod CON")

    def test_detection_cle_bpm(self):
        self.assertEqual(mpc.find_key("bpm: 155 key: B min"), "B min")
        self.assertEqual(mpc.find_key("Tonalité : F# mineur"), "F# min")
        self.assertEqual(mpc.find_bpm("prod. wondor D# Minor | 155 BPM"), 155)
        self.assertIsNone(mpc.find_bpm("12 bpm"))
        self.assertIsNone(mpc.valid_key("F# min; rm -rf /"))
        self.assertEqual(mpc.valid_key("C# min"), "C# min")
        self.assertIsNone(mpc.valid_bpm("999"))


class Signature(unittest.TestCase):
    def ok(self, **kw):
        m = {"mf": 2, "v": "r_RyAVAUr5w", "ts": int(time.time() * 1000), "n": "0123456789abcdef"}
        m.update(kw)
        return m

    def test_envoi_signe_accepte(self):
        self.assertEqual(mpc.verify(signed(self.ok()), KEY)["v"], "r_RyAVAUr5w")

    def test_mauvaise_cle_refusee(self):
        self.assertIsNone(mpc.verify(signed(self.ok(), "cd" * 32), KEY))

    def test_contenu_modifie_refuse(self):
        env = json.loads(signed(self.ok()))
        env["p"] = env["p"].replace("r_RyAVAUr5w", "XXXXXXXXXXX")
        self.assertIsNone(mpc.verify(json.dumps(env), KEY))

    def test_sans_signature_refuse(self):
        self.assertIsNone(mpc.verify(json.dumps(self.ok()), KEY))
        self.assertIsNone(mpc.verify("pas du json", KEY))

    def test_trop_vieux_refuse(self):
        self.assertIsNone(mpc.verify(signed(self.ok(ts=int((time.time() - 3 * 86400) * 1000))), KEY))

    def test_mauvaise_version_refusee(self):
        self.assertIsNone(mpc.verify(signed(self.ok(mf=1)), KEY))


class Fichiers(unittest.TestCase):
    def test_wav_et_dossier(self):
        with tempfile.TemporaryDirectory() as d:
            good = Path(d) / "a.wav"
            good.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")
            fake = Path(d) / "b.wav"
            fake.write_bytes(b"MZ\x90\x00 pas un wav")
            self.assertTrue(mpc.is_wav(good))
            self.assertFalse(mpc.is_wav(fake))
            self.assertTrue(mpc.inside(Path(d) / "x.wav", d))
            self.assertFalse(mpc.inside(Path(d) / ".." / "x.wav", d))
            self.assertEqual(mpc.unique_path(d, "a").name, "a (2).wav")


class Installation(unittest.TestCase):
    def test_code_appairage(self):
        tok = "melofinds-" + "0a" * 16 + "." + "5b" * 32
        self.assertEqual(mpc.parse_pairing(tok), ("melofinds-" + "0a" * 16, "5b" * 32))
        self.assertEqual(mpc.parse_pairing("  " + tok.upper() + "\n"), ("melofinds-" + "0a" * 16, "5b" * 32))
        self.assertIsNone(mpc.parse_pairing("melofinds-123.abc"))
        self.assertIsNone(mpc.parse_pairing(tok + "; del C:"))

    def test_versions(self):
        self.assertGreater(mpc.version_tuple("2.0.10"), mpc.version_tuple("2.0.9"))
        self.assertEqual(mpc.version_tuple("v2.1.0"), (2, 1, 0))


class MiseAJour(unittest.TestCase):
    def manifest(self, **kw):
        m = {"version": "9.9.9", "url": f"{mpc.RELEASES}/download/pc-v9.9.9/MelofindsPC.exe", "sha256": "ab" * 32}
        m.update(kw)
        old = mpc.http_get
        mpc.http_get = lambda url, timeout=40: json.dumps(m).encode()
        try:
            return mpc.check_update()
        finally:
            mpc.http_get = old

    def test_version_officielle_acceptee(self):
        self.assertEqual(self.manifest()[0], "9.9.9")

    def test_deja_a_jour(self):
        self.assertIsNone(self.manifest(version=mpc.VERSION))

    def test_autre_site_refuse(self):
        with self.assertRaises(ValueError):
            self.manifest(url="https://evil.example/MelofindsPC.exe")
        with self.assertRaises(ValueError):
            self.manifest(url="https://github.com/pirate/Melofinds/releases/download/x/MelofindsPC.exe")

    def test_sans_empreinte_refuse(self):
        with self.assertRaises(ValueError):
            self.manifest(sha256="pas-une-empreinte")


class Appareils(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="mf-cfg-"))
        mpc.P.set(self.d)

    def test_migration_2x(self):
        code, key = "melofinds-" + "1a" * 16, "2b" * 32
        (self.d / "config.json").write_text(json.dumps({"code": code, "cle": key, "dossier": "/x", "since": "m9", "done": ["abcdefghijk"], "history": [{"t": "a"}]}))
        cfg = mpc.load_config()
        self.assertEqual(len(cfg["devices"]), 1)
        self.assertEqual(cfg["devices"][0]["code"], code)
        self.assertNotIn("cle", cfg)
        st = mpc.load_state()
        self.assertEqual(st["since"][code], "m9")
        self.assertEqual(st["done"], ["abcdefghijk"])

    def test_plusieurs_appareils(self):
        cfg = mpc.load_config()
        a = inst.add_device(cfg, "melofinds-" + "1a" * 16 + "." + "2b" * 32, "iPhone")
        b = inst.add_device(cfg, "melofinds-" + "3c" * 16 + "." + "4d" * 32, "")
        self.assertEqual([d["name"] for d in cfg["devices"]], ["iPhone", "Appareil 2"])
        inst.add_device(cfg, "melofinds-" + "1a" * 16 + "." + "5e" * 32, "")  # même téléphone, nouvelle clé
        self.assertEqual(len(cfg["devices"]), 2)
        self.assertEqual(cfg["devices"][0]["cle"], "5e" * 32)
        with self.assertRaises(ValueError):
            inst.add_device(cfg, "n'importe quoi", "")
        mpc.save_config(cfg)
        self.assertEqual(len(mpc.load_config()["devices"]), 2)
        self.assertNotEqual(a["id"], b["id"])

    def test_appareil_invalide_ignore(self):
        (self.d / "config.json").write_text(json.dumps({"devices": [{"code": "x", "cle": "y"}, {"code": "melofinds-" + "1a" * 16, "cle": "2b" * 32, "id": "d1"}]}))
        self.assertEqual(len(mpc.load_config()["devices"]), 1)


class Configuration(unittest.TestCase):
    def test_reprise_ancienne_version_et_configuration(self):
        old = Path(tempfile.mkdtemp(prefix="mf-old-"))
        new = Path(tempfile.mkdtemp(prefix="mf-new-"))
        code, key = "melofinds-" + "6f" * 16, "7a" * 32
        (old / "config.json").write_text(json.dumps({"code": code, "cle": key, "dossier": str(old / "Prods")}))
        (old / "tools").mkdir()
        (old / "tools" / "yt-dlp.exe").write_text("x")
        orig = mpc.previous_install_dirs
        mpc.previous_install_dirs = lambda: [old]
        try:
            mpc.P.set(new)
            cfg = inst.configure(dossier=str(new / "Mes prods"), pairing="melofinds-" + "8b" * 16 + "." + "9c" * 32, device_name="PC portable")
        finally:
            mpc.previous_install_dirs = orig
        self.assertEqual([d["code"] for d in cfg["devices"]], [code, "melofinds-" + "8b" * 16])  # ancien téléphone gardé
        self.assertEqual(cfg["dossier"], str(new / "Mes prods"))
        self.assertTrue((new / "Mes prods").is_dir())
        self.assertTrue((new / "tools" / "yt-dlp.exe").exists())  # outils repris, pas retéléchargés
        self.assertTrue((old / "config.json").exists())  # l'ancien dossier n'est pas modifié

    def test_code_invalide_refuse(self):
        mpc.P.set(Path(tempfile.mkdtemp(prefix="mf-cfg-")))
        with self.assertRaises(ValueError):
            inst.configure(pairing="pas un code")


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# FLmake : projet FL Studio préparé à partir du modèle

import struct
import mf_flmake as FM


def _ev(eid, val):
    if eid >= 192:
        return bytes([eid]) + FM._varint(len(val)) + val
    return bytes([eid]) + val


def _u16(s):
    return (s + "\0").encode("utf-16-le")


def fake_flp(version="25.2.4.4960", tempo=130, clip=False, ppq=96, tracks=("INSTRU", "VOICE", "")):
    """Petit projet au format FL : version, tempo, un canal « Kick » (sampler), le
    mixer avec un plugin (Graillon…), un arrangement avec des pistes nommées."""
    evs = [_ev(199, (version + "\0").encode()), _ev(172, b"\x01"), _ev(1, b"\0"), _ev(194, _u16("MODEL FL"))]
    if tempo:
        evs.append(_ev(156, struct.pack("<I", tempo * 1000)))
    evs += [_ev(64, struct.pack("<H", 0)), _ev(21, b"\0"), _ev(201, _u16("")), _ev(203, _u16("Kick")),
            _ev(212, bytes(36) + struct.pack("<II", 7, 9) + bytes(8)), _ev(196, _u16(r"%FLStudioFactoryData%\Kick.wav"))]
    nchan = 1
    if clip:  # un son déjà posé sur la piste INSTRU
        evs += [_ev(64, struct.pack("<H", 1)), _ev(21, b"\4"), _ev(201, _u16("")), _ev(203, _u16("placeholder")),
                _ev(212, bytes(44)), _ev(196, _u16(r"C:\Sons\placeholder.wav"))]
        nchan = 2
    major = int(version.split(".")[0])
    size = 80 if major >= 25 else 60 if major >= 21 else 32
    rec = b""
    if clip:
        rec = FM._clip_record(size, 96, 1, 1234, 499, 1)
    evs += [_ev(99, struct.pack("<H", 0)), _ev(241, _u16("Arrangement")), _ev(233, rec)]
    for n, name in enumerate(tracks, 1):
        evs.append(_ev(238, struct.pack("<I", n) + bytes(66)))
        if name:
            evs.append(_ev(239, _u16(name)))
    evs += [_ev(236, bytes(12)), _ev(213, bytes(range(256)) * 2), _ev(203, _u16("Graillon 3"))]  # mixer : insert 2
    body = b"".join(evs)
    return struct.pack("<4sIhHH", b"FLhd", 6, 0, nchan, ppq) + b"FLdt" + struct.pack("<I", len(body)) + body


def fake_wav(seconds=10, rate=48000, ch=2):
    data = b"\0" * (rate * ch * 2 * seconds)
    fmt = struct.pack("<HHIIHH", 1, ch, rate, rate * ch * 2, ch * 2, 16)
    return b"RIFF" + struct.pack("<I", 36 + len(data) + 12) + b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt \
        + b"LIST" + struct.pack("<I", 4) + b"INFO" + b"data" + struct.pack("<I", len(data)) + data


class FLmake(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="mf-fl-"))
        self.wav = self.d / "Prod [C# min, 150 BPM].wav"
        self.wav.write_bytes(fake_wav(10))

    def tpl(self, **kw):
        p = self.d / f"tpl{len(list(self.d.glob('tpl*')))}.flp"
        p.write_bytes(fake_flp(**kw))
        return p

    def build(self, **kw):
        out = self.d / "out" / "Prod.flp"
        FM.build_project(self.tpl(**kw), self.wav, out, bpm=150, title="Prod")
        return FM.Project(out.read_bytes())

    def instru(self, pr):
        size, blob, clips = pr.clips()
        ch = pr.channels()
        return size, [(c, ch[c["item"]]) for c in clips if c["item"] < FM.PATTERN_BASE and ch.get(c["item"], {}).get("sample") == str(self.wav.resolve())]

    def test_lecture_ecriture_identique(self):
        for v in ("25.2.4.4960", "21.2.3.4004", "20.8.4.2576"):
            data = fake_flp(version=v, clip=True)
            self.assertEqual(FM.write_flp(*FM.read_flp(data)), data)

    def test_evenement_172_fl25(self):
        fmt, nchan, ppq, evs = FM.read_flp(fake_flp())
        self.assertEqual(nchan, 1)
        self.assertEqual(evs[1], [172, b"\x01"])  # 1 octet, pas 4 (sinon tout se décale)

    def test_modele_fl25_sans_son_instru_creee_sur_la_piste_instru(self):
        pr = self.build(tracks=("VOICE", "INSTRU", ""))
        size, mine = self.instru(pr)
        self.assertEqual(size, 80)
        self.assertEqual(len(mine), 1)
        clip, ch = mine[0]
        self.assertEqual((clip["track"], clip["pos"], clip["len"]), (2, 0, 10 * 150 / 60 * 96))
        self.assertEqual((ch["type"], ch["name"]), (4, "Prod [C# min, 150 BPM]"))
        self.assertEqual(pr.nchan, 2)
        blob = pr.clips()[1]
        self.assertEqual(struct.unpack_from("<ff", blob, 24), (-1.0, -1.0))  # clip entier
        self.assertEqual(struct.unpack_from("<f", blob, 52)[0], 1.0)
        self.assertEqual(struct.unpack_from("<d", blob, 64)[0], 1.0)
        rt = [v for e, v in pr.events[ch["start"]:ch["end"]] if e == FM.EV_CHANNEL_RUNTIME][0]
        self.assertEqual(struct.unpack_from("<II", rt, 36), (8, 10))  # identifiants de voix uniques

    def test_piste_du_haut_par_defaut(self):
        pr = self.build(tracks=("", "VOICE"))
        self.assertEqual(self.instru(pr)[1][0][0]["track"], 1)

    def test_formats_fl21_et_fl20(self):
        for v, size in (("21.2.3.4004", 60), ("20.8.4.2576", 32)):
            got, mine = self.instru(self.build(version=v))
            self.assertEqual((got, len(mine)), (size, 1), v)

    def test_tempo(self):
        pr = self.build(tempo=130)
        self.assertEqual([struct.unpack("<I", v)[0] for e, v in pr.events if e == 156], [150000])
        pr = self.build(tempo=None)  # FL n'écrit pas le tempo par défaut : on l'ajoute
        self.assertEqual([struct.unpack("<I", v)[0] for e, v in pr.events if e == 156], [150000])
        self.assertEqual(pr.events[-1][0], 156)

    def test_son_deja_pose_remplace(self):
        pr = self.build(clip=True)
        size, mine = self.instru(pr)
        self.assertEqual(pr.nchan, 2)  # pas de canal en plus
        self.assertEqual(len(mine), 1)
        self.assertEqual((mine[0][0]["pos"], mine[0][0]["len"]), (0, 2400))

    def test_reste_du_modele_intact(self):
        pr = self.build()
        self.assertIn([213, bytes(range(256)) * 2], pr.events)  # plugins du mixer (preset de voix)
        self.assertEqual([FM._text(v, True) for e, v in pr.events if e == 194], ["Prod"])
        kick = pr.channels()[0]
        self.assertEqual(kick["sample"], r"%FLStudioFactoryData%\Kick.wav")

    def test_duree_wav(self):
        self.assertAlmostEqual(FM.wav_seconds(self.wav), 10.0)

    def test_modeles_refuses(self):
        self.assertFalse(FM.inspect_template(self.d / "absent.flp")["ok"])
        (self.d / "faux.flp").write_bytes(b"MThd pas un projet")
        self.assertFalse(FM.inspect_template(self.d / "faux.flp")["ok"])
        t = FM.inspect_template(self.tpl())
        self.assertTrue(t["ok"], t["msg"])
        self.assertEqual((t["track"], t["track_name"]), (1, "INSTRU"))

    def test_make_dossier_au_nom_de_la_prod(self):
        tpl = self.tpl()
        cfg = {"dossier": str(self.d), "flmake": {"on": True, "template": str(tpl), "dossier": str(self.d / "FL")}}
        out, msg = FM.make(self.wav, "C# min", 150, None, cfg)
        self.assertEqual(out, self.d / "FL" / "Prod [C# min, 150 BPM]" / "Prod [C# min, 150 BPM].flp")
        out2, _ = FM.make(self.wav, "C# min", 150, None, cfg)
        self.assertEqual(out2, self.d / "FL" / "Prod [C# min, 150 BPM] (2)" / "Prod [C# min, 150 BPM] (2).flp")
        self.assertIn("C# min", msg)
        self.assertEqual([p.name for p in FM.recent_projects(cfg)][:1], [out2.name])
        self.assertEqual(FM.split_key("Bb maj"), ("Bb", "maj"))
        self.assertEqual(FM.maybe_make(self.wav, None, None, None, {"flmake": {"on": False}}), (None, None))

    def test_script_fl_valide(self):
        compile(FM.script_text(), "device_MelofindsFLmake.py", "exec")
        self.assertIn("# name=Melofinds FLmake", FM.script_text().splitlines()[0])


# ---------------------------------------------------------------------------
# Mes prods : liste, favoris, renommage, prods déjà reçues

import mf_library as L


class MesProds(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="mf-lib-"))
        mpc.P.set(self.d / "prog")
        self.beats = self.d / "Prods"
        self.beats.mkdir()
        tpl = self.d / "MODEL FL.flp"
        tpl.write_bytes(fake_flp())
        self.cfg = {"dossier": str(self.beats), "devices": [],
                    "flmake": {"on": True, "template": str(tpl), "dossier": str(self.d / "Projets FL")}}
        mpc.save_config(self.cfg)
        self.name = "Lucki Type Beat - 'Haze' [C# min, 150 BPM] [FFP]"
        self.wav = self.beats / f"{self.name}.wav"
        self.wav.write_bytes(fake_wav(2))
        (self.beats / "Autre [140 BPM].wav").write_bytes(fake_wav(1))
        self.flp, _ = FM.make(self.wav, "C# min", 150, None, mpc.load_config())
        (self.flp.parent / f"{self.name} (autosave).flp").write_bytes(self.flp.read_bytes())
        (self.flp.parent / f"{self.name}.mp3").write_bytes(b"export")

    def item(self):
        return next(i for i in L.scan() if i.flp)

    def test_noms(self):
        self.assertEqual(L.parse_name(self.name), ("Lucki Type Beat - 'Haze'", "[C# min, 150 BPM] [FFP]", "C# min", 150, "FFP"))
        self.assertEqual(L.parse_name("Prod [FFP, UPTO 5000] (2)")[1:], ("[FFP, UPTO 5000]", "", None, "FFP, UPTO 5000"))
        self.assertEqual(L.parse_name("Beat [Remix] [C min]")[:2], ("Beat [Remix]", "[C min]"))
        self.assertEqual(L.clean_new_title(' Ma prod: "finale"? '), "Ma prod finale")

    def test_liste_avec_projet_fl(self):
        items = L.scan()
        self.assertEqual(len(items), 2)
        it = self.item()
        self.assertEqual((it.wav, it.flp, it.key, it.bpm, it.lic), (self.wav, self.flp, "C# min", 150, "FFP"))
        self.assertIsNone(next(i for i in items if not i.flp).folder)

    def test_favori(self):
        it = self.item()
        L.toggle_fav(it)
        self.assertTrue(self.item().fav)
        L.toggle_fav(self.item())
        self.assertFalse(self.item().fav)

    def test_renommer_tout(self):
        it = self.item()
        L.toggle_fav(it)
        new = L.rename(self.item(), "Haze (finale)")
        self.assertEqual(new, "Haze (finale) [C# min, 150 BPM] [FFP]")
        folder = self.d / "Projets FL" / new
        self.assertEqual(sorted(p.name for p in folder.iterdir()), sorted([f"{new}.flp", f"{new} (autosave).flp", f"{new}.mp3"]))
        self.assertFalse(self.wav.exists())
        new_wav = self.beats / f"{new}.wav"
        self.assertTrue(new_wav.exists())
        for f in folder.glob("*.flp"):
            self.assertIn(str(new_wav.resolve()), L._flp_samples(f))
            titles = [FM._text(v, True) for e, v in FM.read_flp(f.read_bytes())[3] if e == FM.EV_TITLE]
            self.assertEqual(titles, [new])
        it2 = self.item()
        self.assertEqual((it2.name, it2.fav, it2.wav), (new, True, new_wav))
        # le PC ne retélécharge pas une prod renommée
        st = {"files": {"jNQXAC9IVRw": f"{self.name}.wav"}}
        self.assertEqual(mpc.received_file(st, mpc.load_config(), "jNQXAC9IVRw", self.beats), new_wav)

    def test_renommer_annule_si_nom_pris(self):
        taken = self.d / "Projets FL" / "Pris [C# min, 150 BPM] [FFP]"
        taken.mkdir()
        before = sorted(str(p.relative_to(self.d)) for p in self.d.rglob("*"))
        flp_bytes = self.flp.read_bytes()
        with self.assertRaises(L.LibError):
            L.rename(self.item(), "Pris")
        self.assertEqual(sorted(str(p.relative_to(self.d)) for p in self.d.rglob("*")), before)  # tout est remis
        self.assertEqual(self.flp.read_bytes(), flp_bytes)

    def test_prod_supprimee_retelechargee(self):
        st = {"files": {"jNQXAC9IVRw": f"{self.name}.wav"}}
        self.assertEqual(mpc.received_file(st, self.cfg, "jNQXAC9IVRw", self.beats), self.wav)
        self.wav.unlink()
        self.assertIsNone(mpc.received_file(st, self.cfg, "jNQXAC9IVRw", self.beats))
        self.assertIsNone(mpc.received_file({}, self.cfg, "jNQXAC9IVRw", self.beats))
