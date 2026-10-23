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
