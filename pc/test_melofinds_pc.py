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
# Mes projets FL : un dossier par prod (« Nom/Nom.wav » + « Nom/Nom.flp »)

import mf_library as L


class MesProjetsFL(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="mf-lib-"))
        mpc.P.set(self.d / "prog")
        self.root = self.d / "Projets FL"
        self.root.mkdir()
        tpl = self.d / "MODEL FL.flp"
        tpl.write_bytes(fake_flp())
        self.cfg = {"dossier": str(self.d / "Prods (ancien)"), "devices": [],
                    "flmake": {"on": True, "template": str(tpl), "dossier": str(self.root)}}
        mpc.save_config(self.cfg)
        self.name = "Lucki Type Beat - 'Haze' [C# min, 150 BPM] [FFP]"
        # comme un téléchargement : la prod arrive dans son propre dossier
        self.wav = mpc.unique_project(self.root, self.name)
        self.wav.parent.mkdir()
        self.wav.write_bytes(fake_wav(2))
        self.flp, _ = FM.make(self.wav, "C# min", 150, None, mpc.load_config())
        (self.flp.parent / f"{self.name} (autosave).flp").write_bytes(self.flp.read_bytes())
        (self.flp.parent / f"{self.name}.mp3").write_bytes(b"export")

    def project(self, name=None):
        return next(i for i in L.scan_projects() if i.name == (name or self.name))

    def test_un_dossier_par_prod(self):
        self.assertEqual(self.wav, self.root / self.name / f"{self.name}.wav")
        self.assertEqual(self.flp, self.root / self.name / f"{self.name}.flp")  # projet à côté de la prod
        self.assertIn(str(self.wav.resolve()), L._flp_samples(self.flp))
        self.assertEqual(mpc.unique_project(self.root, self.name), self.root / f"{self.name} (2)" / f"{self.name} (2).wav")
        self.assertEqual(mpc.projects_root(mpc.load_config()), self.root)

    def test_prod_venue_d_ailleurs_copiee_dans_son_projet(self):
        ext = self.d / "Ailleurs" / "Beat [D min, 90 BPM].wav"
        ext.parent.mkdir()
        ext.write_bytes(fake_wav(1))
        out, _ = FM.make(ext, "D min", 90, None, mpc.load_config())
        self.assertEqual(out.parent, self.root / ext.stem)
        copy = out.parent / f"{ext.stem}.wav"
        self.assertTrue(copy.exists() and ext.exists())
        self.assertIn(str(copy.resolve()), L._flp_samples(out))

    def test_noms(self):
        self.assertEqual(L.parse_name(self.name), ("Lucki Type Beat - 'Haze'", "[C# min, 150 BPM] [FFP]", "C# min", 150, "FFP"))
        self.assertEqual(L.parse_name("Prod [FFP, UPTO 5000] (2)")[1:], ("[FFP, UPTO 5000]", "", None, "FFP, UPTO 5000"))
        self.assertEqual(L.parse_name("Beat [Remix] [C min]")[:2], ("Beat [Remix]", "[C min]"))
        self.assertEqual(L.clean_new_title(' Ma prod: "finale"? '), "Ma prod finale")

    def test_liste_des_projets(self):
        perso = self.root / "Mon son perso"
        perso.mkdir()
        (perso / "Mon son perso.flp").write_bytes(fake_flp())
        (self.root / "Vieux projet.flp").write_bytes(fake_flp())
        seule = self.root / "Prod seule [140 BPM]"
        seule.mkdir()
        (seule / "Prod seule [140 BPM].wav").write_bytes(fake_wav(1))  # FLmake désactivé : la prod seule
        items = {i.name: i for i in L.scan_projects()}
        self.assertEqual(sorted(items), sorted([self.name, "Mon son perso", "Vieux projet", "Prod seule [140 BPM]"]))
        it = items[self.name]
        self.assertEqual((it.kind, it.key, it.bpm, it.extra["instru"], it.extra["files"]), ("project", "C# min", 150, "Lucki Type Beat - 'Haze'", 4))
        self.assertEqual(it.extra["instru_path"].resolve(), self.wav.resolve())
        self.assertIsNone(items["Vieux projet"].folder)
        self.assertIsNone(items["Prod seule [140 BPM]"].flp)
        # ouvrir un projet qui n'a que la prod : le projet FL est créé à côté
        out, _ = FM.make(items["Prod seule [140 BPM]"].extra["instru_path"], None, 140, None, mpc.load_config())
        self.assertEqual(out, seule / "Prod seule [140 BPM].flp")

    def test_favori_projet(self):
        L.toggle_fav(self.project())
        self.assertTrue(self.project().fav)
        self.assertEqual(mpc.load_config().get("fav_projects"), [f"p:{self.name.lower()}"])
        L.toggle_fav(self.project())
        self.assertFalse(self.project().fav)

    def test_renommer_tout_le_projet(self):
        L.toggle_fav(self.project())
        new = L.rename(self.project(), "Haze (finale)")
        self.assertEqual(new, "Haze (finale) [C# min, 150 BPM] [FFP]")
        folder = self.root / new
        self.assertEqual(sorted(p.name for p in folder.iterdir()),
                         sorted([f"{new}.flp", f"{new} (autosave).flp", f"{new}.mp3", f"{new}.wav"]))
        new_wav = folder / f"{new}.wav"
        for f in folder.glob("*.flp"):
            self.assertIn(str(new_wav.resolve()), L._flp_samples(f))  # l'instru suit
            titles = [FM._text(v, True) for e, v in FM.read_flp(f.read_bytes())[3] if e == FM.EV_TITLE]
            self.assertEqual(titles, [new])
        it = self.project(new)
        self.assertTrue(it.fav)
        # le PC ne retélécharge pas une prod dont le projet a été renommé
        st = {"files": {"jNQXAC9IVRw": str(self.wav.resolve())}}
        self.assertEqual(mpc.received_file(st, mpc.load_config(), "jNQXAC9IVRw", [self.root]).resolve(), new_wav.resolve())

    def test_renommer_annule_si_nom_pris(self):
        (self.root / "Pris [C# min, 150 BPM] [FFP]").mkdir()
        before = sorted(str(p.relative_to(self.d)) for p in self.d.rglob("*"))
        flp_bytes = self.flp.read_bytes()
        with self.assertRaises(L.LibError):
            L.rename(self.project(), "Pris")
        self.assertEqual(sorted(str(p.relative_to(self.d)) for p in self.d.rglob("*")), before)  # tout est remis
        self.assertEqual(self.flp.read_bytes(), flp_bytes)

    def test_prod_supprimee_retelechargee(self):
        st = {"files": {"jNQXAC9IVRw": str(self.wav)}}
        self.assertEqual(mpc.received_file(st, self.cfg, "jNQXAC9IVRw", [self.root]), self.wav)
        self.wav.unlink()
        self.assertIsNone(mpc.received_file(st, self.cfg, "jNQXAC9IVRw", [self.root]))
        self.assertIsNone(mpc.received_file({}, self.cfg, "jNQXAC9IVRw", [self.root]))
        # anciennes versions : nom seul, dans l'ancien dossier des prods
        old = Path(self.cfg["dossier"])
        old.mkdir()
        (old / "x.wav").write_bytes(fake_wav(1))
        self.assertEqual(mpc.received_file({"files": {"v": "x.wav"}}, self.cfg, "v", [self.root, old]), old / "x.wav")


class StyleDesProjets(MesProjetsFL):
    def test_couleur_auto_stable_puis_choisie(self):
        it = self.project()
        color, icon, styled = it.extra["color"], it.extra["icon"], it.extra["styled"]
        self.assertIn(color, L.PALETTE)
        self.assertEqual((icon, styled), (L.ICONS[0], False))
        self.assertEqual(self.project().extra["color"], color)  # toujours la même couleur
        L.set_style(it, "#ec4899", "☾")
        it = self.project()
        self.assertEqual((it.extra["color"], it.extra["icon"], it.extra["styled"]), ("#ec4899", "☾", True))
        L.set_style(it, None, None)  # par défaut
        self.assertEqual((self.project().extra["color"], self.project().extra["icon"]), (color, L.ICONS[0]))

    def test_style_suit_le_renommage(self):
        L.set_style(self.project(), "#22d3ee", "⚡")
        new = L.rename(self.project(), "Autre nom")
        it = self.project(new)
        self.assertEqual((it.extra["color"], it.extra["icon"]), ("#22d3ee", "⚡"))

    def test_style_inconnu_ignore(self):
        cfg = mpc.load_config()
        cfg["project_style"] = {self.project().id: {"color": "red; rm -rf", "icon": "<script>"}}
        mpc.save_config(cfg)
        it = self.project()
        self.assertIn(it.extra["color"], L.PALETTE)
        self.assertEqual(it.extra["icon"], L.ICONS[0])


class Tunebat(unittest.TestCase):
    """Clé / BPM trouvés avec Tunebat : bon morceau seulement, marqués [TB …] dans le nom."""
    ITEMS = [
        {"n": "COLD", "as": ["Nemzzz"], "d": 160000, "k": "A♯ minor", "b": 142},
        {"n": "NEMZZZ TYPE BEAT", "as": ["Nemzzz"], "d": 173000, "k": "D major", "b": 145},
        {"n": "Haze", "as": ["Kxvi Beats"], "d": 151000, "k": "C♯ Minor", "b": 150.2},
        {"n": "Haze", "as": ["Someone Else"], "d": 200000, "k": "E minor", "b": 90},
    ]

    def test_meme_choix_que_l_app_web(self):
        self.assertEqual(mpc.beat_name('[FREE] Lucki Type Beat "Haze" | Free For Profit'), "Haze")
        self.assertEqual(mpc.beat_name("Don't Stop Type Beat 'Nuit'"), "Nuit")
        self.assertEqual(mpc.tb_queries('[FREE] Lucki Type Beat "Haze"', "Kxvi Beats"), ["Haze Kxvi", "Haze"])
        self.assertEqual([mpc.tb_key("A♯ minor"), mpc.tb_key("D Major"), mpc.tb_key("B♭ minor"), mpc.tb_key("???")],
                         ["A# min", "D maj", "Bb min", None])
        p = mpc.tb_pick(self.ITEMS, 'Lucki Type Beat "Haze"', "Kxvi Beats", 152)
        self.assertEqual((p["key"], p["bpm"]), ("C# min", 150))
        self.assertIsNone(mpc.tb_pick([self.ITEMS[3]], 'Lucki Type Beat "Haze"', "Kxvi Beats", 152))
        self.assertEqual(mpc.tb_pick(self.ITEMS, "NEMZZZ TYPE BEAT", "", 175)["bpm"], 145)
        self.assertIsNone(mpc.tb_pick(self.ITEMS, 'Pop Smoke Type Beat "Dior"', "Random", 120))
        self.assertIsNone(mpc.tb_pick("pas une liste", "x", "", 0))
        # valeurs bizarres renvoyées par le site : ignorées
        self.assertIsNone(mpc.tb_pick([{"n": "Haze", "as": ["Kxvi"], "d": 151000, "k": "<script>", "b": "abc"}], '"Haze"', "Kxvi", 151))

    def test_nom_avec_tb(self):
        t = '[FREE] Lucki Type Beat "Haze"'
        self.assertEqual(mpc.build_name(t, "C# min", 150, "ffp", tb_key=True, tb_bpm=True), "Lucki Type Beat 'Haze' [TB C# min, 150 BPM] [FFP]")
        self.assertEqual(mpc.build_name(t, "C# min", 150, tb_bpm=True), "Lucki Type Beat 'Haze' [C# min] [TB 150 BPM]")
        self.assertEqual(mpc.build_name(t, "C# min", None, tb_key=True), "Lucki Type Beat 'Haze' [TB C# min]")
        self.assertEqual(mpc.build_name(t, "C# min", 150), "Lucki Type Beat 'Haze' [C# min, 150 BPM]")
        self.assertNotIn("free", mpc.build_name(t, "C# min", 150, "fnp", tb_key=True).lower())

    def test_priorite(self):
        self.assertEqual(mpc.pick_value("C min", False, "D min"), ("C min", False))   # précisée dans l'app
        self.assertEqual(mpc.pick_value("C min", True, "D min"), ("D min", False))    # description > Tunebat
        self.assertEqual(mpc.pick_value("C min", True, None), ("C min", True))        # Tunebat (téléphone)
        self.assertEqual(mpc.pick_value(None, True, None), (None, False))

    def test_lecture_du_nom(self):
        r = L.parse_name_tb("Haze [C# min] [TB 150 BPM] [FFP]")
        self.assertEqual(r, ("Haze", "[C# min] [TB 150 BPM] [FFP]", "C# min", 150, "FFP", {"bpm"}))
        self.assertEqual(L.parse_name_tb("Haze [TB C# min, 150 BPM]")[5], {"key", "bpm"})
        self.assertEqual(L.parse_name("Haze [TB C# min, 150 BPM] [F]"), ("Haze", "[TB C# min, 150 BPM] [F]", "C# min", 150, "F"))
        self.assertEqual(L.parse_name_tb("Haze [TB toto]")[:2], ("Haze [TB toto]", ""))

    def test_renommer_garde_le_tb(self):
        d = Path(tempfile.mkdtemp(prefix="mf-tb-"))
        mpc.P.set(d / "prog")
        root = d / "Projets FL"
        root.mkdir()
        mpc.save_config({"dossier": str(root), "devices": [], "flmake": {"on": False, "dossier": str(root)}})
        name = "Haze [TB C# min, 150 BPM]"
        wav = mpc.unique_project(root, name)
        wav.parent.mkdir()
        wav.write_bytes(fake_wav(1))
        it = next(x for x in L.scan_projects() if x.name == name)
        self.assertEqual((it.key, it.bpm, it.extra["tb"]), ("C# min", 150, {"key", "bpm"}))
        self.assertEqual(L.rename(it, "Brume"), "Brume [TB C# min, 150 BPM]")
        self.assertTrue((root / "Brume [TB C# min, 150 BPM]" / "Brume [TB C# min, 150 BPM].wav").exists())


import http.client
import threading
from unittest import mock
import mf_worker as W
import melofinds_pc as MAIN


class Reconnexion(unittest.TestCase):
    """Le PC reste en ligne : plantages évités, réannonce, seul « Mettre hors ligne » l'arrête."""
    CODE = "melofinds-" + "a" * 32

    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="mf-reco-"))
        mpc.P.set(self.d)
        self.cfg = {"dossier": str(self.d / "Prods"), "devices": [{"id": "d1", "name": "Tel", "code": self.CODE, "cle": "b" * 64}],
                    "flmake": {"on": False, "dossier": str(self.d / "Projets")}}
        mpc.save_config(self.cfg)
        self.replies = []
        self.patches = [mock.patch.object(mpc, "ensure_tools", lambda *a: []),
                        mock.patch.object(mpc, "update_ytdlp", lambda: None),
                        mock.patch.object(mpc, "resolve_install_dir", lambda: self.d),
                        mock.patch.object(mpc, "reply", lambda code, p: self.replies.append(p) or True)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_en_ligne_voulu(self):
        self.assertTrue(inst.wants_online())
        with mock.patch.object(inst, "stop_worker", lambda **k: True):
            inst.go_offline()
        self.assertFalse(inst.wants_online())
        with mock.patch.object(inst, "start_worker", lambda: True):
            inst.go_online()
        self.assertTrue(inst.wants_online())
        self.assertFalse(inst.wants_online({"devices": [], "online": True}))

    def test_demarrage_windows_respecte_hors_ligne(self):
        mpc.save_config({**mpc.load_config(), "online": False})
        with mock.patch.object(MAIN, "worker", side_effect=AssertionError("ne doit pas se mettre en ligne")):
            self.assertEqual(MAIN.main(["--background"]), 0)
        mpc.save_config({**mpc.load_config(), "online": True})
        with mock.patch.object(MAIN, "worker", return_value=0) as w:
            MAIN.main(["--background"])
            w.assert_called_once()

    def test_ancien_reglage_autostart_oublie(self):
        mpc.save_config({**mpc.load_config(), "autostart": False})
        cfg = inst.configure()
        self.assertNotIn("autostart", cfg)
        self.assertTrue(inst.wants_online(cfg))

    def test_erreurs_reseau_et_prod_qui_plante_sans_arret(self):
        msg = {"mf": 2, "n": "f" * 16, "v": "jNQXAC9IVRw", "t": "Prod"}
        calls = {"n": 0}

        def poll(code, since):
            calls["n"] += 1
            if calls["n"] == 1:
                raise http.client.IncompleteRead(b"")  # réseau coupé en pleine réponse
            return [{"id": "e1", "event": "message", "message": "x"}]
        with mock.patch.object(mpc, "poll", poll), mock.patch.object(mpc, "verify", lambda raw, key: dict(msg)), \
                mock.patch.object(mpc, "download", side_effect=RuntimeError("boum")):
            self.assertEqual(W.worker(once=True), 0)  # 1er tour : coupure réseau
            self.assertEqual(W.worker(once=True), 0)  # 2e tour : la prod plante
        st = mpc.load_state()
        self.assertIn("f" * 16, st["seen"])  # pas retentée en boucle
        self.assertFalse(st["history"][0]["ok"])
        self.assertTrue(any(p.get("v") == "jNQXAC9IVRw" and p.get("ok") is False for p in self.replies))

    def test_reannonce_tant_que_le_reseau_ne_repond_pas(self):
        tries = []

        def reply(code, p):
            if p.get("pc") == "online":
                tries.append(1)
                if len(tries) >= 3:
                    mpc.P.stop.write_text("stop", encoding="utf-8")
                return len(tries) >= 3
            return True
        with mock.patch.object(mpc, "reply", reply), mock.patch.object(mpc, "poll", lambda c, s: []), \
                mock.patch.object(mpc, "POLL_SECONDS", 0):
            t = threading.Thread(target=W.worker)
            t.start()
            t.join(20)
        self.assertFalse(t.is_alive())
        self.assertEqual(len(tries), 3)

    def test_mise_a_jour_ne_dit_pas_hors_ligne(self):
        with mock.patch.object(mpc, "poll", lambda c, s: []), mock.patch.object(mpc, "POLL_SECONDS", 0):
            t = threading.Thread(target=W.worker)
            t.start()
            for _ in range(100):
                if mpc.lock_held():
                    break
                time.sleep(0.05)
            self.assertTrue(mpc.running())
            inst.stop_worker(timeout=10, reason="update")
            t.join(10)
        self.assertFalse(mpc.lock_held())
        self.assertFalse(any(p.get("pc") == "offline" for p in self.replies))
        self.assertTrue(inst.update_in_progress())  # le panneau ne le relance pas pendant la mise à jour
        # arrêt normal (« Mettre hors ligne ») : le téléphone est prévenu
        self.replies.clear()
        with mock.patch.object(mpc, "poll", lambda c, s: []), mock.patch.object(mpc, "POLL_SECONDS", 0):
            t = threading.Thread(target=W.worker)
            t.start()
            for _ in range(100):
                if any(p.get("pc") == "online" for p in self.replies):
                    break
                time.sleep(0.05)
            inst.stop_worker(timeout=10)
            t.join(10)
        self.assertTrue(any(p.get("pc") == "offline" for p in self.replies))
        self.assertFalse(mpc.P.stop.exists())


class EcouteEtGestionDepuisLApp(unittest.TestCase):
    """Onglet « File d'attente » de l'app web : liste des projets, sons par version, commandes."""
    CODE = "melofinds-" + "c" * 32

    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="mf-remote-"))
        mpc.P.set(self.d / "prog")
        self.root = self.d / "Projets FL"
        self.root.mkdir()
        mpc.save_config({"dossier": str(self.root), "devices": [{"id": "d1", "name": "Tel", "code": self.CODE, "cle": "b" * 64}],
                         "flmake": {"on": False, "dossier": str(self.root)}})
        self.name = "Haze [C# min, 150 BPM] [FFP]"
        p = self.root / self.name
        p.mkdir()
        for n in (f"{self.name}.wav", "Haze 1.3.3.wav", "Haze 0.1.wav", "Haze v1.0 (mix).mp3", "Haze 0.2.wav", "voix brute.wav"):
            (p / n).write_bytes(fake_wav(1))
        (p / "notes.txt").write_text("x")
        self.sent, self.files = [], []
        self.patches = [mock.patch.object(mpc, "reply", lambda code, m: self.sent.append(m) or True),
                        mock.patch.object(mpc, "publish_attachment", lambda code, data, fn, meta, timeout=60: self.files.append((fn, meta, len(data))) or True),
                        mock.patch.object(mpc, "make_preview", lambda src, out: (Path(out).write_bytes(b"a" * 4_000_000), Path(out))[1])]
        for x in self.patches:
            x.start()

    def tearDown(self):
        for x in self.patches:
            x.stop()

    def project(self):
        return next(i for i in L.scan_projects() if i.name == self.name)

    def test_versions(self):
        self.assertEqual([L.version_of(n) for n in ("Haze 1.3.3", "Haze v2", "Haze_v0.1 (mix)", "Haze [C# min, 150 BPM]", "Haze 140 bpm")],
                         [(1, 3, 3), (2,), (0, 1), None, None])
        files = L.audio_files(self.project())
        self.assertEqual([f["name"] for f in files][:5], [self.name, "Haze 0.1", "Haze 0.2", "Haze v1.0 (mix)", "Haze 1.3.3"])
        self.assertTrue(files[0]["instru"])
        self.assertEqual([f["name"] for f in files if f.get("latest")], ["Haze 1.3.3"])
        self.assertNotIn("notes", [f["name"] for f in files])

    def test_liste_pour_l_app(self):
        lib = L.library_index()
        p = lib["projects"][0]
        self.assertEqual((p["t"], p["k"], p["b"], p["lic"]), ("Haze", "C# min", 150, "FFP"))
        self.assertEqual(p["files"][0]["i"], 1)
        self.assertEqual(p["files"][4]["v"], "v1.3.3")
        self.assertIn(p["c"], lib["palette"])
        json.dumps(lib)  # envoyable tel quel
        # un identifiant inconnu ne donne jamais de chemin
        self.assertEqual(L.find_audio("deadbeef0000"), (None, None))

    def test_commandes(self):
        r = W.Remote(mpc.load_state())
        cfg = mpc.load_config()
        pid = self.project().id
        r.command(self.CODE, {"cmd": "fav", "p": pid, "on": True}, cfg)
        self.assertTrue(self.project().fav)
        r.command(self.CODE, {"cmd": "style", "p": pid, "c": "#bad", "i": "x"}, mpc.load_config())
        self.assertFalse(self.sent[-1]["ok"])
        r.command(self.CODE, {"cmd": "style", "p": pid, "c": L.PALETTE[3], "i": L.ICONS[5]}, mpc.load_config())
        self.assertEqual((self.project().extra["color"], self.project().extra["icon"]), (L.PALETTE[3], L.ICONS[5]))
        r.command(self.CODE, {"cmd": "ren", "p": pid, "t": "Brume / ../.."}, mpc.load_config())
        self.assertTrue(self.sent[-1]["ok"], self.sent[-1])
        new = self.sent[-1]["new"]
        self.assertTrue((self.root / new / f"{new}.wav").exists())
        self.assertTrue((self.root / new / "Haze 1.3.3.wav").exists())  # les versions restent
        it = next(i for i in L.scan_projects() if i.name == new)
        self.assertTrue(it.fav)
        self.assertEqual(it.extra["color"], L.PALETTE[3])
        r.command(self.CODE, {"cmd": "ren", "p": "p:inconnu"}, mpc.load_config())
        self.assertFalse(self.sent[-1]["ok"])
        # la liste part à l'appareil qui l'a demandée
        r.tick(mpc.load_config()["devices"], mpc.load_config())
        self.assertEqual(self.files[-1][0], "projets.json")
        self.assertEqual(self.files[-1][1]["lib"], 1)

    def test_copie_d_ecoute_decoupee_et_limitee(self):
        r = W.Remote(mpc.load_state())
        f = L.audio_files(self.project())[4]
        r.command(self.CODE, {"cmd": "play", "f": f["id"]}, mpc.load_config())
        parts = [m for _, m, _ in self.files]
        self.assertEqual([(m["i"], m["of"]) for m in parts], [(0, 3), (1, 3), (2, 3)])  # 4 Mo → 3 pièces de 1,9 Mo max
        self.assertTrue(all(n <= mpc.ATTACH_MAX for _, _, n in self.files))
        self.assertEqual((parts[0]["aud"], parts[0]["v"], parts[0]["len"]), (f["id"], "v1.3.3", 4_000_000))
        for _ in range(5):  # 17 Mo max par 3 h (ntfy.sh : 20 Mo)
            r.command(self.CODE, {"cmd": "play", "f": f["id"]}, mpc.load_config())
        self.assertIn("limite", self.sent[-1]["err"])
        r.command(self.CODE, {"cmd": "play", "f": "../../etc"}, mpc.load_config())
        self.assertIn("introuvable", self.sent[-1]["err"])

    def test_desactive_sur_le_pc(self):
        mpc.save_config({**mpc.load_config(), "remote": False})
        r = W.Remote(mpc.load_state())
        r.command(self.CODE, {"cmd": "fav", "p": self.project().id, "on": True}, mpc.load_config())
        self.assertFalse(self.sent[-1]["ok"])
        self.assertFalse(self.project().fav)


class EnvoiAutomatiqueALApp(EcouteEtGestionDepuisLApp):
    """Le PC tient l'app à jour tout seul : liste au démarrage, à chaque changement, à
    l'arrêt ; les nouveaux sons (versions exportées) partent en copie d'écoute."""

    def devices(self):
        return mpc.load_config()["devices"]

    def test_liste_au_demarrage_puis_seulement_si_ca_change(self):
        r = W.Remote(mpc.load_state())
        r.want.add(self.CODE)  # annoncé en ligne → liste tout de suite
        r.tick(self.devices(), mpc.load_config())
        libs = lambda: [m for fn, m, _ in self.files if fn == "projets.json"]
        self.assertEqual(len(libs()), 1)
        r.checked = 0
        r.tick(self.devices(), mpc.load_config())
        self.assertEqual(len(libs()), 1)  # rien n'a changé
        # sauvegarde auto de FL (dates seulement) : pas de renvoi
        os.utime(self.root / self.name / f"{self.name}.wav", (time.time() + 50, time.time() + 50))
        r.checked, r.sent_at[self.CODE] = 0, 0
        r.tick(self.devices(), mpc.load_config())
        self.assertEqual(len(libs()), 1)
        # nouveau projet : renvoyée (au plus toutes les 3 min)
        (self.root / "Nuit").mkdir()
        (self.root / "Nuit" / "Nuit.wav").write_bytes(fake_wav(1))
        r.checked, r.sent_at[self.CODE] = 0, time.time() - 60
        r.tick(self.devices(), mpc.load_config())
        self.assertEqual(len(libs()), 1)  # envoyée il y a moins de 3 min
        r.checked, r.sent_at[self.CODE] = 0, 0
        r.tick(self.devices(), mpc.load_config())
        self.assertEqual(len(libs()), 2)
        # arrêt : dernière liste si elle a changé
        (self.root / "Brume").mkdir()
        (self.root / "Brume" / "Brume 0.1.mp3").write_bytes(b"x")  # projet sans .wav ni .flp : compté quand même
        r.tick(self.devices(), mpc.load_config(), final=True)
        self.assertEqual(len(libs()), 3)
        self.assertIn("Brume", [p["t"] for p in L.library_index()["projects"]])

    def test_nouvelle_version_envoyee_toute_seule(self):
        r = W.Remote(mpc.load_state())
        r.tick(self.devices(), mpc.load_config())  # 1er passage : l'existant est noté, rien n'est envoyé
        self.assertFalse([m for _, m, _ in self.files if "aud" in m])
        new = self.root / self.name / "Haze 1.4.wav"
        new.write_bytes(fake_wav(1))
        old = time.time() - 60
        os.utime(new, (old, old))
        r.checked = 0
        r.tick(self.devices(), mpc.load_config())
        sent = [m for _, m, _ in self.files if "aud" in m]
        self.assertEqual({(m["n"], m["v"]) for m in sent}, {("Haze 1.4", "v1.4")})
        r.checked = 0
        n = len(self.files)
        r.tick(self.devices(), mpc.load_config())
        self.assertEqual(len([1 for _, m, _ in self.files[n:] if "aud" in m]), 0)  # pas deux fois

    def test_versions_fl(self):
        self.assertEqual(L.version_of("Haze_2"), (2,))
        self.assertEqual(L.version_of("Haze_2 [C# min, 150 BPM]"), (2,))


class SynchroDuTelephone(unittest.TestCase):
    """Le téléphone garde la dernière version de chaque projet : il dit ce qui lui manque,
    le PC l'envoie petit à petit sans dépasser les limites de ntfy.sh."""
    CODE = EcouteEtGestionDepuisLApp.CODE
    tearDown = EcouteEtGestionDepuisLApp.tearDown

    def setUp(self):
        EcouteEtGestionDepuisLApp.setUp(self)
        for x in self.patches:  # copies d'écoute de 1,5 Mo (une seule pièce jointe)
            x.stop()
        self.patches = [mock.patch.object(mpc, "reply", lambda code, m: self.sent.append(m) or True),
                        mock.patch.object(mpc, "publish_attachment", lambda code, data, fn, meta, timeout=60: self.files.append((fn, meta, len(data))) or True),
                        mock.patch.object(mpc, "make_preview", lambda src, out: (Path(out).write_bytes(b"a" * 1_500_000), Path(out))[1])]
        for x in self.patches:
            x.start()
        for n in ("Nuit", "Brume", "Ciel"):
            (self.root / n).mkdir()
            (self.root / n / f"{n}.wav").write_bytes(fake_wav(1))

    def targets(self):
        fmap = {}
        L.library_index(files_out=fmap)
        return fmap, W.phone_targets(fmap)

    def test_cible_derniere_version_sinon_instru(self):
        fmap, t = self.targets()
        names = sorted(fmap[f][1]["name"] for f in t)
        self.assertEqual(names, ["Brume", "Ciel", "Haze 1.3.3", "Nuit"])

    def test_envoi_petit_a_petit(self):
        r = W.Remote(mpc.load_state())
        devs = mpc.load_config()["devices"]
        _, t = self.targets()
        r.command(self.CODE, {"cmd": "sync", "f": sorted(t) + ["zz", 5]}, mpc.load_config())
        r.tick(devs, mpc.load_config())
        auds = [m for _, m, _ in self.files if "aud" in m]
        self.assertEqual(len(auds), W.Remote.SYNC_PER_TICK)  # 3 par tour
        self.assertEqual(self.sent[-1]["sync"]["left"], 1)
        r.checked = 0
        r.tick(devs, mpc.load_config())
        self.assertEqual(len([m for _, m, _ in self.files if "aud" in m]), 4)
        self.assertEqual(self.sent[-1], {"sync": {"left": 0, "wait": 0}})
        # redemandés tout de suite (le téléphone ne les a pas encore récupérés) : pas renvoyés
        r.command(self.CODE, {"cmd": "sync", "f": sorted(t)}, mpc.load_config())
        r.checked = 0
        r.tick(devs, mpc.load_config())
        self.assertEqual(len([m for _, m, _ in self.files if "aud" in m]), 4)

    def test_vider_et_retelecharger(self):
        r = W.Remote(mpc.load_state())
        devs = mpc.load_config()["devices"]
        _, t = self.targets()
        r.command(self.CODE, {"cmd": "sync", "f": sorted(t)}, mpc.load_config())
        for _ in range(2):
            r.checked = 0
            r.tick(devs, mpc.load_config())
        auds = lambda: len([m for _, m, _ in self.files if "aud" in m])
        self.assertEqual(auds(), 4)
        # le téléphone a tout effacé : sans « reset », le PC croirait qu'il les a encore
        r.command(self.CODE, {"cmd": "sync", "f": sorted(t), "reset": 1}, mpc.load_config())
        for _ in range(2):
            r.checked = 0
            r.tick(devs, mpc.load_config())
        self.assertEqual(auds(), 8)

    def test_limite_ntfy_attente_annoncee(self):
        r = W.Remote(mpc.load_state())
        r.audio = [(time.time() - 3600, 16_000_000)]  # 16 Mo déjà envoyés il y a 1 h
        devs = mpc.load_config()["devices"]
        _, t = self.targets()
        r.command(self.CODE, {"cmd": "sync", "f": sorted(t)}, mpc.load_config())
        r.tick(devs, mpc.load_config())
        self.assertFalse([m for _, m, _ in self.files if "aud" in m])
        st = self.sent[-1]["sync"]
        self.assertEqual(st["left"], 4)
        self.assertTrue(7000 < st["wait"] <= 7300)  # ~2 h : quand les 16 Mo expirent

    def test_debit_adapte(self):
        self.assertEqual(mpc.preview_kbps(180), 73)
        self.assertEqual(mpc.preview_kbps(120), 96)
        self.assertEqual(mpc.preview_kbps(330), 64)
        self.assertEqual(mpc.preview_kbps(None), 80)


class OrdreLienEtDuree(unittest.TestCase):
    """Mes projets FL : ordre au glisser-déposer, lien de la vidéo YouTube, durée."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="mf-ordre-"))
        mpc.P.set(self.d / "prog")
        self.root = self.d / "Projets FL"
        self.root.mkdir()
        mpc.save_config({"dossier": str(self.root), "devices": [], "flmake": {"on": False, "dossier": str(self.root)}})
        for n, age in (("Aube", 300), ("Brume", 200), ("Ciel", 100)):
            p = self.root / n
            p.mkdir()
            (p / f"{n}.wav").write_bytes(fake_wav(3))
            os.utime(p / f"{n}.wav", (time.time() - age, time.time() - age))

    def titles(self):
        return [i.title for i in L.scan_projects()]

    def test_ordre(self):
        self.assertEqual(self.titles(), ["Ciel", "Brume", "Aube"])  # sans ordre : les plus récents d'abord
        L.move_project("p:ciel", "p:aube")  # vers le bas : après la cible
        self.assertEqual(self.titles(), ["Brume", "Aube", "Ciel"])
        L.move_project("p:ciel", "p:brume")  # vers le haut : avant la cible
        self.assertEqual(self.titles(), ["Ciel", "Brume", "Aube"])
        L.move_project("p:aube", "p:ciel")
        self.assertEqual(self.titles(), ["Aube", "Ciel", "Brume"])
        (self.root / "Dune").mkdir()
        (self.root / "Dune" / "Dune.wav").write_bytes(fake_wav(1))
        self.assertEqual(self.titles(), ["Dune", "Aube", "Ciel", "Brume"])  # nouveau projet : en haut
        L.rename(next(i for i in L.scan_projects() if i.title == "Ciel"), "Cendre")
        self.assertEqual(self.titles(), ["Dune", "Aube", "Cendre", "Brume"])  # garde sa place
        self.assertEqual([p["t"] for p in L.library_index()["projects"]], ["Dune", "Aube", "Cendre", "Brume"])  # même ordre dans l'app web

    def test_lien_youtube_et_duree(self):
        mpc.save_state({**mpc.load_state(), "files": {"jNQXAC9IVRw": str((self.root / "Brume" / "Brume.wav").resolve())}})
        it = next(i for i in L.scan_projects() if i.title == "Brume")
        self.assertEqual((it.extra.get("yt"), it.extra.get("dur")), ("jNQXAC9IVRw", 3))
        self.assertNotIn("yt", next(i for i in L.scan_projects() if i.title == "Aube").extra)
        L.rename(it, "Brouillard")
        it = next(i for i in L.scan_projects() if i.title == "Brouillard")
        self.assertEqual(it.extra.get("yt"), "jNQXAC9IVRw")  # le lien suit le renommage
        p = next(x for x in L.library_index()["projects"] if x["t"] == "Brouillard")
        self.assertEqual((p["y"], p["du"]), ("jNQXAC9IVRw", 3))

    def test_plus_d_icones(self):
        self.assertGreaterEqual(len(L.ICONS), 50)
        self.assertEqual(len(set(L.ICONS)), len(L.ICONS))


class SonsDeFL(unittest.TestCase):
    """Comme sur la capture : enregistrements automatiques de FL et samples mis à part,
    pas pris pour l'instru ni pour une version."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="mf-fl-"))
        mpc.P.set(self.d / "prog")
        self.root = self.d / "Projets FL"
        self.root.mkdir()
        mpc.save_config({"dossier": str(self.root), "devices": [], "flmake": {"on": False, "dossier": str(self.root)}})
        p = self.root / "Project Supernova"
        p.mkdir()
        (p / "Project Supernova.flp").write_bytes(fake_flp())
        for n in ("NSupernova 0.1", "NSupernova 0.2", "Basic 808 Clap", "Project Supernova_2026-09-20 14-12-20_ON YOUR SIDE",
                  "Project Supernova_2026-09-20 14-06-35_ON YOUR SIDE", "Supernova mix final"):
            (p / f"{n}.wav").write_bytes(fake_wav(1 if n == "Basic 808 Clap" else 4, rate=8000))
        (p / "Recorded").mkdir()
        (p / "Recorded" / "Vocal take.wav").write_bytes(fake_wav(1))

    def files(self):
        it = next(i for i in L.scan_projects() if i.title == "Project Supernova")
        return it, L.audio_files(it)

    def test_tri(self):
        it, files = self.files()
        self.assertIsNone(it.extra.get("instru"))  # pas de prod reçue : pas d'instru (le clap n'en est pas une)
        kinds = {f["name"]: f["kind"] for f in files}
        self.assertEqual(kinds["NSupernova 0.2"], "version")
        self.assertEqual(kinds["Supernova mix final"], "export")
        self.assertEqual(kinds["Project Supernova_2026-09-20 14-12-20_ON YOUR SIDE"], "fl")
        self.assertEqual(kinds["Vocal take"], "fl")  # dossier Recorded de FL
        self.assertEqual(kinds["Basic 808 Clap"], "fl")  # un sample de 1 s
        self.assertEqual([f["name"] for f in files if f.get("main")], ["NSupernova 0.2"])
        self.assertEqual([f["name"] for f in files][:3], ["NSupernova 0.1", "NSupernova 0.2", "Supernova mix final"])

    def test_sans_version_l_export_le_plus_recent(self):
        for n in ("NSupernova 0.1", "NSupernova 0.2"):
            (self.root / "Project Supernova" / f"{n}.wav").unlink()
        _, files = self.files()
        self.assertEqual([f["name"] for f in files if f.get("main")], ["Supernova mix final"])

    def test_prod_recue_reste_l_instru(self):
        p = self.root / "Haze [C# min, 150 BPM]"
        p.mkdir()
        (p / "Haze [C# min, 150 BPM].wav").write_bytes(fake_wav(1))
        (p / "Kick 01.wav").write_bytes(fake_wav(1))
        it = next(i for i in L.scan_projects() if i.title == "Haze")
        files = L.audio_files(it)
        self.assertEqual(it.extra.get("instru"), "Haze")
        self.assertEqual([f["name"] for f in files if f.get("main")], ["Haze [C# min, 150 BPM]"])


class LienYouTubeGarde(unittest.TestCase):
    """Le lien de la vidéo est gardé à la réception : dans le .wav et dans les réglages."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="mf-lien-"))
        mpc.P.set(self.d / "prog")
        self.root = self.d / "Projets FL"
        self.root.mkdir()
        mpc.save_config({"dossier": str(self.root), "devices": [], "flmake": {"on": False, "dossier": str(self.root)}})

    def project(self, name):
        p = self.root / name
        p.mkdir()
        (p / f"{name}.wav").write_bytes(fake_wav(4, rate=8000))
        return p / f"{name}.wav"

    @unittest.skipUnless(mpc.tool_path("ffmpeg.exe"), "ffmpeg absent")
    def test_lien_dans_le_wav_suit_un_renommage_a_la_main(self):
        wav = self.project("Haze [C# min]")
        tagged = mpc.tag_wav_link(mpc.tool_path("ffmpeg.exe"), wav, self.d / "t.wav", "jNQXAC9IVRw", "Haze")
        self.assertTrue(tagged and mpc.is_wav(tagged))
        self.assertEqual(mpc.wav_link(tagged), "jNQXAC9IVRw")
        os.replace(tagged, wav)
        # renommé dans l'Explorateur Windows (pas dans le panneau) : le lien suit quand même
        os.replace(wav, wav.with_name("Brume.wav"))
        os.replace(wav.parent, self.root / "Brume")
        it = next(i for i in L.scan_projects() if i.title == "Brume")
        self.assertEqual(it.extra.get("yt"), "jNQXAC9IVRw")

    def test_lecture_wav_sans_lien(self):
        wav = self.project("Nuit")
        self.assertIsNone(mpc.wav_link(wav))
        self.assertIsNone(mpc.wav_link(self.d / "absent.wav"))
        (self.d / "faux.wav").write_bytes(b"RIFF\x00\x00\x00\x00WAVELIST\xff\xff\xff\x7f")
        self.assertIsNone(mpc.wav_link(self.d / "faux.wav"))

    def test_lien_garde_a_la_reception_et_au_renommage(self):
        self.project("Haze [C# min]")
        L.remember_link("p:haze [c# min]", "jNQXAC9IVRw")
        it = next(i for i in L.scan_projects() if i.title == "Haze")
        self.assertEqual(it.extra.get("yt"), "jNQXAC9IVRw")
        L.rename(it, "Brume")
        it = next(i for i in L.scan_projects() if i.title == "Brume")
        self.assertEqual(it.extra.get("yt"), "jNQXAC9IVRw")

    def test_liens_envoyes_par_le_telephone(self):
        self.project("Haze [C# min]")
        self.project("Nuit [F min]")
        it = next(i for i in L.scan_projects() if i.title == "Nuit")
        L.rename(it, "Lune")  # renommé dans le panneau avant que le téléphone envoie les liens
        n = L.remember_links({"jNQXAC9IVRw": "Haze [C# min].wav", "AAAAAAAAAA1": "Nuit [F min].wav",
                              "BBBBBBBBBB1": "inconnu.wav", "pas-un-id": "x.wav", "CCCCCCCCCC1": "pas un wav.mp3"})
        self.assertEqual(n, 2)
        got = {i.title: i.extra.get("yt") for i in L.scan_projects()}
        self.assertEqual(got, {"Haze": "jNQXAC9IVRw", "Lune": "AAAAAAAAAA1"})


class AppWebAJourEtVersions(unittest.TestCase):
    """Un changement fait dans le panneau part tout de suite vers l'app web ; une version
    reste « la suivante » même si le projet a changé de nom (Project Core 0.6 → Vertige 0.7)."""
    CODE = "melofinds-" + "d" * 32

    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="mf-ajour-"))
        mpc.P.set(self.d / "prog")
        self.root = self.d / "Projets FL"
        self.root.mkdir()
        mpc.save_config({"dossier": str(self.root), "devices": [{"id": "d1", "name": "Tel", "code": self.CODE, "cle": "b" * 64}],
                         "flmake": {"on": False, "dossier": str(self.root)}})
        p = self.root / "Project Core"
        p.mkdir()
        (p / "Project Core.flp").write_bytes(fake_flp())
        for n in ("Project Core 0.5", "Project Core 0.6"):
            (p / f"{n}.wav").write_bytes(fake_wav(4, rate=8000))

    def test_changement_dans_le_panneau_reveille_le_programme(self):
        it = next(i for i in L.scan_projects() if i.title == "Project Core")
        L.set_style(it, L.PALETTE[2], L.ICONS[3])
        self.assertTrue(mpc.P.kick.exists())
        mpc.P.kick.unlink()
        L.rename(it, "Vertige")
        self.assertTrue(mpc.P.kick.exists())
        # le programme en ligne se réveille et envoie la liste à tous les appareils, sans attendre
        sent = []
        with mock.patch.object(mpc, "ensure_tools", lambda *a: []), mock.patch.object(mpc, "update_ytdlp", lambda: None), \
                mock.patch.object(mpc, "reply", lambda c, m: True), mock.patch.object(mpc, "poll", lambda c, s: []), \
                mock.patch.object(mpc, "publish_attachment", lambda c, data, fn, meta, timeout=60: sent.append(json.loads(data)) or True), \
                mock.patch.object(mpc, "resolve_install_dir", lambda: self.d / "prog"):
            W.worker(once=True)
        self.assertFalse(mpc.P.kick.exists())
        self.assertEqual([p["t"] for p in sent[-1]["projects"]], ["Vertige"])
        self.assertEqual(sent[-1]["projects"][0]["c"], L.PALETTE[2])

    def test_version_suivante_meme_avec_un_autre_nom(self):
        it = next(i for i in L.scan_projects() if i.title == "Project Core")
        L.rename(it, "Vertige")
        (self.root / "Vertige" / "Vertige 0.7.wav").write_bytes(fake_wav(4, rate=8000))
        it = next(i for i in L.scan_projects() if i.title == "Vertige")
        files = L.audio_files(it)
        self.assertEqual([f["label"] for f in files if f["kind"] == "version"], ["v0.5", "v0.6", "v0.7"])
        self.assertEqual([f["name"] for f in files if f.get("main")], ["Vertige 0.7"])
        # même sans renommer les anciennes versions (exportées sous l'ancien nom)
        (self.root / "Vertige" / "Vertige 0.6.wav").rename(self.root / "Vertige" / "Core old 0.6.wav")
        files = L.audio_files(next(i for i in L.scan_projects() if i.title == "Vertige"))
        self.assertEqual([f["name"] for f in files if f.get("main")], ["Vertige 0.7"])

    def test_envois_gardes_apres_un_redemarrage(self):
        st = mpc.load_state()
        r = W.Remote(st)
        r._note(15_000_000)
        r2 = W.Remote(st)  # programme redémarré (mise à jour) : il se souvient des 15 Mo envoyés
        self.assertFalse(r2._budget(1_000_000 + W.Remote.LIB_RESERVE))
        self.assertTrue(r2._budget(1_000_000))  # la liste et les sons demandés passent encore
