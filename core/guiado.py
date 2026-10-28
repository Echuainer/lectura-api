"""Motor guiado: wav2vec2 CTC en dos pasadas sobre las mismas emisiones (libre y guiada por el texto).
La lógica usa solo numpy; torch/transformers se importan dentro de `emisiones`."""
import copy
import itertools
import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from core import analisis

RAIZ = Path(__file__).resolve().parent.parent


def cargar_config() -> dict:
    return json.loads((RAIZ / "config" / "motor.json").read_text(encoding="utf-8"))


def decodificar_ctc(logp, vocab, seg_por_frame):
    """Decodificación voraz: argmax por frame, colapsa repetidos, quita blank; '|' separa palabras."""
    letras = {i: c for c, i in vocab.items() if len(c) == 1 and c != "|"}
    blank, sep = vocab["<pad>"], vocab["|"]
    ids = np.asarray(logp).argmax(axis=1)
    palabras, chars, ini, ult = [], [], None, None

    def cerrar():
        if chars:
            palabras.append({"palabra": "".join(chars), "inicio": round(ini * seg_por_frame, 3),
                             "fin": round((ult + 1) * seg_por_frame, 3)})
        chars.clear()

    prev = None
    for t, i in enumerate(ids):
        if i == sep:
            cerrar()
        elif i != blank and i in letras:
            if not chars:
                ini = t
            if i != prev:
                chars.append(letras[i])
            ult = t
        prev = i
    cerrar()
    return palabras


def ids_palabra(palabra, vocab):
    import unicodedata

    ids = []
    for c in palabra.lower():
        if c not in vocab:
            c = "".join(x for x in unicodedata.normalize("NFD", c) if unicodedata.category(x) != "Mn")
        if c in vocab:
            ids.append(vocab[c])
    return ids


def puntaje_ctc(logp_seg, ids, blank):
    """log P(ids | segmento) por forward de CTC en log-espacio, por frame."""
    T, L = len(logp_seg), len(ids)
    if L == 0 or T < L:
        return -np.inf
    ext = np.full(2 * L + 1, blank)
    ext[1::2] = ids
    # el salto s-2 solo vale entre etiquetas distintas (no blank)
    salto = np.zeros(len(ext), bool)
    salto[2:] = (ext[2:] != blank) & (ext[2:] != ext[:-2])
    alfa = np.full(len(ext), -np.inf)
    alfa[0] = logp_seg[0, blank]
    alfa[1] = logp_seg[0, ext[1]]
    for t in range(1, T):
        nuevo = np.logaddexp(alfa, np.concatenate(([-np.inf], alfa[:-1])))
        a2 = np.concatenate(([-np.inf, -np.inf], alfa[:-2]))
        nuevo = np.where(salto, np.logaddexp(nuevo, a2), nuevo)
        alfa = nuevo + logp_seg[t, ext]
    return float(np.logaddexp(alfa[-1], alfa[-2])) / T


def puntaje_libre(logp_seg):
    return float(np.max(logp_seg, axis=1).mean())


def variantes(norm, max_var=16):
    """La palabra con cada letra débil (s de coda, j, d final o entre vocales) presente u omitida; la original va primero."""
    voc = "aeiouáéíóúü"
    pos = [i for i, c in enumerate(norm)
           if (c == "s" and (i + 1 == len(norm) or norm[i + 1] not in voc)) or c == "j"
           or (c == "d" and (i + 1 == len(norm) or (i > 0 and norm[i - 1] in voc and norm[i + 1] in voc)))]
    out = []
    for quedan in itertools.product((True, False), repeat=len(pos)):
        quitar = {i for i, q in zip(pos, quedan) if not q}
        v = "".join(c for i, c in enumerate(norm) if i not in quitar)
        if v not in out:
            out.append(v)
        if len(out) == max_var:
            break
    return out


def _termina_en_una_letra(leido, ref):
    """True si lo leído y la referencia suenan igual salvo una letra agregada o quitada al final."""
    a, b = (analisis.fonetico(analisis.normalizar(x)) for x in (leido, ref))
    a, b = sorted((a, b), key=len)
    return len(b) - len(a) == 1 and b.startswith(a)


def verificar(resultado, logp, vocab, seg_por_frame, umbral_ok, umbral_error):
    r = copy.deepcopy(resultado)
    items, T = r["detalle"], len(logp)
    blank, sep = vocab["<pad>"], vocab["|"]
    malo = lambda it: it["tipo"] in ("sustitucion", "omision")

    def medir(i, j):
        """(margen por letra, frame inicial, ventana confiable) de la racha items[i:j]; None si no se puede medir."""
        ant = next((x["fin"] for x in reversed(items[:i]) if x.get("fin") is not None), None)
        sig = next((x["inicio"] for x in items[j:] if x["leido"] is not None and x["inicio"] is not None), None)
        a = 0 if ant is None else round(ant / seg_por_frame) + 1
        # sin palabra siguiente: hasta el fin del audio, salvo que el propio item tenga tiempo (el silencio final diluiría el margen)
        fin = items[j - 1]["fin"]
        b = round(sig / seg_por_frame) if sig is not None else T if fin is None else round(fin / seg_por_frame) + 1
        a, b = max(a, 0), min(b, T)
        combos = itertools.islice(itertools.product(*(variantes(analisis.normalizar(it["ref"])) for it in items[i:j])), 16)
        cands = [[x for w in c for x in ids_palabra(w, vocab)] for c in combos]
        if b - a < 3 or not cands[0]:
            return None
        seg = logp[a:b]
        # los separadores de palabra dentro de la ventana no deben castigar a la palabra de referencia
        seg_ref = seg.copy()
        seg_ref[:, blank] = np.logaddexp(seg[:, blank], seg[:, sep])
        ctc = max(puntaje_ctc(seg_ref, ids, blank) for ids in cands)
        if not np.isfinite(ctc):
            return None
        letras = len(cands[0])
        # dividir por letras evita que las palabras largas diluyan el error; con pocos frames por letra el margen engaña
        return (puntaje_libre(seg) - ctc) * (b - a) / letras, a, (b - a) >= 1.5 * letras

    def aplicar(i, j, medida):
        margen, a, _ = medida
        for it in items[i:j]:
            it["margen"] = round(margen, 2)
            if j - i > 1:
                it["margen_grupo"] = it["margen"]
            if margen <= umbral_ok:
                sustitucion = it["tipo"] == "sustitucion"
                it["tipo"] = "revisar" if sustitucion and _termina_en_una_letra(it["leido"], it["ref"]) else "correcta"
                if it["inicio"] is None:
                    it["inicio"] = round(a * seg_por_frame, 3)
            elif margen < umbral_error:
                it["tipo"] = "revisar"

    k = 0
    while k < len(items):
        if not malo(items[k]):
            k += 1
            continue
        j = k
        while j < len(items) and malo(items[j]):
            j += 1
        medida = medir(k, j) if j - k > 1 else None
        if medida and medida[0] < umbral_error:
            aplicar(k, j, medida)
        else:
            poco = False
            for i in range(k, j):
                medida = medir(i, i + 1)
                # solo es sospechoso si el motor escuchó algo: sin audio donde iba la palabra, la omisión es clara
                if items[i]["tipo"] == "sustitucion":
                    poco |= medida is None or not medida[2]
                if medida and medida[0] < umbral_error:
                    aplicar(i, i + 1, medida)
                elif medida:
                    items[i]["margen"] = round(medida[0], 2)
            if poco:  # ventana poco confiable en la racha: nada queda como error
                for it in items[k:j]:
                    if malo(it):
                        it["tipo"] = "revisar"
        k = j
    for it in items:  # palabras de <=2 letras: el modelo no discrimina
        if malo(it) and len(analisis.normalizar(it["ref"])) <= 2:
            it["tipo"] = "revisar"
    return analisis.recalcular(r)


def evaluar_logp(texto_ref, logp, vocab, cfg):
    palabras = decodificar_ctc(logp, vocab, cfg["seg_por_frame"])
    r = analisis.analizar(texto_ref, palabras, fonetica=True)
    r = verificar(r, logp, vocab, cfg["seg_por_frame"], cfg["umbral_ok"], cfg["umbral_error"])
    r["texto"] = " ".join(p["palabra"] for p in palabras)
    return r


@lru_cache(maxsize=1)
def _cargar_modelo(nombre):
    # Import perezoso: la app abre aunque torch/transformers no estén instalados.
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

    return Wav2Vec2Processor.from_pretrained(nombre), Wav2Vec2ForCTC.from_pretrained(nombre).eval()


def emisiones(ruta_audio, cfg):
    import torch
    from faster_whisper.audio import decode_audio

    proc, modelo = _cargar_modelo(cfg["modelo_literal"])
    vocab = proc.tokenizer.get_vocab()
    audio = decode_audio(ruta_audio)  # 16 kHz float32
    sr, trozo, ctx, hop = 16000, 20 * 16000, 2 * 16000, 320  # 320 muestras por frame = 50 frames/s
    partes = []
    with torch.inference_mode():
        for s in range(0, len(audio), trozo):
            lo, hi = max(0, s - ctx), min(len(audio), s + trozo + ctx)
            x = proc(audio[lo:hi], sampling_rate=sr, return_tensors="pt").input_values
            lp = torch.log_softmax(modelo(x).logits[0], dim=-1).numpy()
            ini = (s - lo) // hop
            partes.append(lp[ini:ini + -(-min(trozo, len(audio) - s) // hop)])
    logp = np.concatenate(partes).astype(np.float32) if partes else np.zeros((0, len(vocab)), np.float32)
    return logp, vocab


def evaluar(ruta_audio, texto_ref, cfg=None):
    cfg = cfg or cargar_config()
    logp, vocab = emisiones(ruta_audio, cfg)
    return evaluar_logp(texto_ref, logp, vocab, cfg)
