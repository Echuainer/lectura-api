"""Transcripción local con faster-whisper. El audio nunca sale del equipo."""
import os
from functools import lru_cache

PROMPT_LITERAL = (
    "Transcripción literal de un estudiante leyendo en voz alta, con errores, "
    "repeticiones y palabras cortadas: la, la casa es... eh, gran- grande."
)
MODELO_POR_DEFECTO = "large-v3-turbo"


@lru_cache(maxsize=1)
def _cargar_modelo(nombre: str):
    # Import perezoso: la app abre aunque faster-whisper no esté instalado.
    from faster_whisper import WhisperModel

    # int8 en CPU: ~0,9 GB de RAM en vez de ~3 GB (fp32), con pérdida de precisión mínima
    return WhisperModel(nombre, device="auto", compute_type=os.environ.get("LECTURA_WHISPER_COMPUTE", "int8"))


def transcribir(ruta_audio: str) -> dict:
    nombre = os.environ.get("LECTURA_WHISPER_MODELO") or MODELO_POR_DEFECTO
    modelo = _cargar_modelo(nombre)
    segmentos, info = modelo.transcribe(
        ruta_audio,
        language="es",
        word_timestamps=True,
        condition_on_previous_text=False,
        temperature=0.0,
        beam_size=5,
        vad_filter=False,
        initial_prompt=PROMPT_LITERAL,
    )
    segmentos = list(segmentos)  # transcribe() es un generador: se recorre una sola vez
    palabras = [
        {"palabra": w.word.strip(), "inicio": w.start, "fin": w.end, "prob": w.probability}
        for s in segmentos
        for w in (s.words or [])
    ]
    texto = "".join(s.text for s in segmentos).strip()
    return {"texto": texto, "palabras": palabras, "duracion": info.duration}
