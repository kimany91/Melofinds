import hashlib, hmac, importlib.util, json, tempfile, time, unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("mpc", Path(__file__).with_name("melofinds-pc.py"))
mpc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mpc)
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


if __name__ == "__main__":
    unittest.main()
