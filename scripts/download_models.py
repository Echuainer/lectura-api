"""Downloads the voice models into the image at build time (HF_HOME), so the container starts without internet.
The guided engine (wav2vec2) is always downloaded; Whisper only with --whisper (optional engine)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import guiado  # noqa: E402


def main(argv):
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

    name = guiado.cargar_config()["modelo_literal"]
    print(f"Downloading {name} (~1.2 GB)...")
    Wav2Vec2Processor.from_pretrained(name)
    Wav2Vec2ForCTC.from_pretrained(name)
    if "--whisper" in argv:
        from core import transcribir
        print("Downloading Whisper...")
        transcribir._cargar_modelo(transcribir.MODELO_POR_DEFECTO)
    print("Models ready.")


if __name__ == "__main__":
    main(sys.argv[1:])
