"""Ta voix séparée du beat, sur le PC (pour caler les sous-titres de Promo au bon moment).

Whisper écoute mal le moment exact des mots quand la batterie et les basses sont mélangées à
la voix. On isole d'abord la voix avec un modèle MDX-Net (Kim_Vocal_2, de l'outil libre
Ultimate Vocal Remover), qui tourne sur le PC (onnxruntime), téléchargé une fois (~66 Mo) et
vérifié par son empreinte. Rien n'est envoyé nulle part.
"""

import hashlib
import subprocess
import wave
from pathlib import Path

import mf_core as C

MODEL = "Kim_Vocal_2.onnx"
MODEL_URL = "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/Kim_Vocal_2.onnx"
MODEL_SHA256 = "ce74ef3b6a6024ce44211a07be9cf8bc6d87728cc852a68ab34eb8e58cde9c8b"
SR = 44100
N_FFT, HOP, DIM_F, DIM_T = 7680, 1024, 3072, 256
COMPENSATE = 1.009


class SepError(Exception):
    pass


def model_path():
    return C.P.tools / "sep" / MODEL


def available():
    try:
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def ensure_model(progress=None):
    p = model_path()
    if p.exists():
        return p
    say = progress or (lambda *_: None)
    say("Téléchargement du séparateur de voix (une seule fois, ~66 Mo)…", None)
    p.parent.mkdir(parents=True, exist_ok=True)
    part = p.with_suffix(".part")
    got = C.download_file(MODEL_URL, part, lambda s: say(s, None), "séparateur de voix")
    if got != MODEL_SHA256:
        part.unlink(missing_ok=True)
        raise SepError("séparateur de voix : empreinte différente, fichier refusé")
    part.replace(p)
    return p


def _decode(src, start, dur):
    import numpy as np
    ffmpeg = C.tool_path("ffmpeg.exe")
    if not ffmpeg:
        raise SepError("ffmpeg manquant")
    r = subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.0, start):.3f}", "-t", f"{dur:.3f}",
                        "-i", str(src), "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True, timeout=300,
                       creationflags=C.NO_WINDOW, stdin=subprocess.DEVNULL)
    if r.returncode != 0 or len(r.stdout) < SR * 8:
        raise SepError("son illisible")
    return np.frombuffer(r.stdout, dtype="<f4").reshape(-1, 2).T.astype(np.float32)  # [2, N]


def _stft(x, win):
    import numpy as np
    pad = N_FFT // 2
    xp = np.pad(x, ((0, 0), (pad, pad)), mode="reflect")
    frames = 1 + (xp.shape[1] - N_FFT) // HOP
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(frames)[:, None]
    return np.fft.rfft(xp[:, idx] * win, axis=-1).transpose(0, 2, 1)  # [2, bins, frames]


def _istft(spec, win, length):
    import numpy as np
    fr = np.fft.irfft(spec.transpose(0, 2, 1), n=N_FFT, axis=-1) * win  # [2, frames, n_fft]
    n = N_FFT + HOP * (fr.shape[1] - 1)
    out = np.zeros((fr.shape[0], n), dtype=np.float64)
    norm = np.zeros(n, dtype=np.float64)
    for f in range(fr.shape[1]):
        out[:, f * HOP:f * HOP + N_FFT] += fr[:, f]
        norm[f * HOP:f * HOP + N_FFT] += win ** 2
    out /= np.maximum(norm, 1e-8)
    pad = N_FFT // 2
    return out[:, pad:pad + length]


def separate(src, start, dur, out_wav, progress=None):
    """Voix seule de l'extrait [start, start+dur] de `src` → out_wav (16 bits, 44,1 kHz, stéréo)."""
    import numpy as np
    import onnxruntime as ort
    say = progress or (lambda *_: None)
    model = ensure_model(progress)
    mix = _decode(src, start, dur)
    n = mix.shape[1]
    so = ort.SessionOptions()
    so.log_severity_level = 3
    sess = ort.InferenceSession(str(model), so, providers=["CPUExecutionProvider"])
    name = sess.get_inputs()[0].name
    win = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(N_FFT) / N_FFT)).astype(np.float64)  # Hann périodique
    trim = N_FFT // 2
    chunk = HOP * (DIM_T - 1)
    gen = chunk - 2 * trim
    pad = gen - n % gen
    mixp = np.concatenate([np.zeros((2, trim)), mix, np.zeros((2, pad)), np.zeros((2, trim))], axis=1)
    parts = []
    steps = list(range(0, n + pad, gen))
    for k, i in enumerate(steps):
        say("Isolation de ta voix…", int(k / len(steps) * 100))
        spec = _stft(mixp[:, i:i + chunk], win)  # [2, bins, 256]
        x = np.stack([spec[0].real, spec[0].imag, spec[1].real, spec[1].imag])[:, :DIM_F, :].astype(np.float32)[None]
        y = sess.run(None, {name: x})[0][0]  # [4, dim_f, 256]
        full = np.zeros((2, N_FFT // 2 + 1, DIM_T), dtype=np.complex128)
        full[0, :DIM_F] = y[0] + 1j * y[1]
        full[1, :DIM_F] = y[2] + 1j * y[3]
        parts.append(_istft(full, win, chunk)[:, trim:-trim])
    voc = np.concatenate(parts, axis=1)[:, :n] * COMPENSATE
    pcm = (np.clip(voc.T, -1, 1) * 32767).astype("<i2").tobytes()
    out_wav = Path(out_wav)
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm)
    return out_wav


def file_sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()
