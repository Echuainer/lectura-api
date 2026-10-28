import wave

import numpy as np


def test_faster_whisper_lee_audio(tmp_path):
    # regresión: PyAV incompatible rompía la lectura de audio antes de transcribir
    from faster_whisper.audio import decode_audio

    ruta = tmp_path / "silencio.wav"
    with wave.open(str(ruta), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(np.zeros(16000, dtype=np.int16).tobytes())
    assert decode_audio(str(ruta)).shape == (16000,)
