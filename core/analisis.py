"""Normalización, alineación y métricas de una lectura en voz alta. Solo librería estándar."""
import copy
import difflib
import re
import unicodedata

CIERRES = "\"'»”’)]}" + "¡¿"
FIN_FRASE = (".", ",", ";", ":", "!", "?", "…")


def normalizar(palabra: str) -> str:
    # ñ se protege antes de NFD: si no, la tilde se separa como marca combinante y se descarta con las demás
    s = unicodedata.normalize("NFC", palabra).lower().replace("ñ", "\u0001")
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return "".join(c for c in s.replace("\u0001", "ñ") if c.isalnum())


def fonetico(norm: str) -> str:
    """Iguala grafías que suenan igual en español de Chile (b/v, s/z/c, ll/y, h muda...)."""
    p = norm.replace("ch", "#").replace("h", "").replace("#", "ch")
    p = re.sub(r"g([ei])", r"j\1", p)
    p = re.sub(r"gu([ei])", r"g\1", p)
    p = p.replace("qu", "k")
    p = re.sub(r"c([ei])", r"s\1", p)
    p = p.replace("c", "k").replace("v", "b").replace("z", "s").replace("ll", "y").replace("x", "ks")
    p = re.sub(r"y$", "i", p)
    return re.sub(r"(.)\1+", r"\1", p)


# autoverificación: lo que suena igual coincide; lo que suena distinto no
assert fonetico("vapor") == fonetico("bapor")
assert fonetico("hacia") == fonetico("asia")
assert fonetico("lluvia") == fonetico("yubia")
assert fonetico("valores") != fonetico("valles")
assert fonetico("hacia") != fonetico("hasta")


def tokenizar_referencia(texto: str) -> list[dict]:
    tokens = []
    for tok in texto.split():
        norm = normalizar(tok)
        if norm:
            fin = tok.rstrip(CIERRES).endswith(FIN_FRASE)
            tokens.append({"original": tok, "norm": norm, "fin_frase": fin})
    return tokens


def _pieza(h, texto, inicio, fin):
    return dict(h, palabra=texto, nrm=texto, norm=fonetico(texto), inicio=inicio, fin=fin)


def _separar(h, vocab):
    """Parte una palabra pegada en dos del vocabulario, o en tres con una letra suelta al medio (se descarta)."""
    s, n = h["nrm"], len(h["nrm"])
    cortes = [(s[:i], None, s[i:]) for i in range(1, n)] + [(s[:i], s[i], s[i + 1:]) for i in range(1, n - 1)]
    for a, medio, b in cortes:
        if fonetico(a) in vocab and fonetico(b) in vocab:
            dur = h["fin"] - h["inicio"]
            t1 = h["inicio"] + dur * len(a) / n
            t2 = h["fin"] - dur * len(b) / n
            return [_pieza(h, a, h["inicio"], t1), _pieza(h, b, t2, h["fin"])]
    return [h]


def _reparar_segmentacion(hyp, vocab):
    out, j = [], 0
    while j < len(hyp):
        h = hyp[j]
        if j + 1 < len(hyp):
            g = hyp[j + 1]
            unido = fonetico(h["nrm"] + g["nrm"])
            if unido in vocab and not (h["norm"] in vocab and g["norm"] in vocab):
                out.append(dict(h, palabra=h["palabra"] + g["palabra"], nrm=h["nrm"] + g["nrm"], norm=unido, fin=g["fin"]))
                j += 2
                continue
        out += _separar(h, vocab) if h["norm"] not in vocab else [h]
        j += 1
    return out


def analizar(texto_ref: str, palabras: list[dict], umbral_pausa: float = 0.8, ventana_s: float = 60.0,
             fonetica: bool = False) -> dict:
    ref = tokenizar_referencia(texto_ref)
    hyp = [dict(p, palabra=p["palabra"].strip(), nrm=normalizar(p["palabra"])) for p in palabras]
    hyp = [dict(h, norm=fonetico(h["nrm"]) if fonetica else h["nrm"]) for h in hyp if h["nrm"]]
    if fonetica:
        for t in ref:
            t["norm"] = fonetico(t["norm"])
        hyp = _reparar_segmentacion(hyp, {t["norm"] for t in ref})

    ops = difflib.SequenceMatcher(
        None, [t["norm"] for t in ref], [h["norm"] for h in hyp], autojunk=False
    ).get_opcodes()

    items = []  # entradas de detalle, en orden de lectura
    toks = []  # token de referencia de cada item (None en inserciones)
    normas = []  # forma de comparación de cada item
    item_de_hyp = [None] * len(hyp)

    def agregar(tipo, tok=None, j=None):
        h = hyp[j] if j is not None else None
        if j is not None:
            item_de_hyp[j] = len(items)
        items.append({
            "tipo": tipo,
            "ref": tok["original"] if tok else None,
            "leido": h["palabra"] if h else None,
            "inicio": h["inicio"] if h else None,
            "fin": h["fin"] if h else None,
            "pausa_despues": None,
        })
        toks.append(tok)
        normas.append(tok["norm"] if tok else h["norm"])

    for k, (tag, i1, i2, j1, j2) in enumerate(ops):
        if tag == "equal":
            for n in range(i2 - i1):
                agregar("correcta", ref[i1 + n], j1 + n)
        elif tag == "replace":
            pares = min(i2 - i1, j2 - j1)
            for n in range(pares):
                agregar("sustitucion", ref[i1 + n], j1 + n)
            for i in range(i1 + pares, i2):
                agregar("omision", ref[i])
            for j in range(j1 + pares, j2):
                agregar("insercion", None, j)
        elif tag == "delete":
            # el alumno no llegó al final del texto: lo no leído no es omisión
            ultimo = k == len(ops) - 1 and i2 == len(ref)
            for i in range(i1, i2):
                agregar("no_leida" if ultimo else "omision", ref[i])
        elif tag == "insert":
            for j in range(j1, j2):
                agregar("insercion", None, j)

    # Post-proceso de inserciones: repetición o autocorrección según la palabra vecina
    for j, idx in enumerate(item_de_hyp):
        if items[idx]["tipo"] != "insercion":
            continue
        norm = hyp[j]["norm"]
        anterior = hyp[j - 1]["norm"] if j > 0 else None
        siguiente = toks[idx + 1] if idx + 1 < len(items) and items[idx + 1]["tipo"] == "correcta" else None
        if norm == anterior or (siguiente and norm == siguiente["norm"]):
            items[idx]["tipo"] = "repeticion"
        elif siguiente and (
            siguiente["norm"].startswith(norm)
            or difflib.SequenceMatcher(None, norm, siguiente["norm"]).ratio() >= 0.6
        ):
            items[idx]["tipo"] = "autocorreccion"

    # Repetición de frase: una racha de items sin referencia que copia 2+ palabras seguidas de la referencia vecina
    k, grupo = 0, 0
    while k < len(items):
        if toks[k] is not None:
            k += 1
            continue
        j = k
        while j < len(items) and toks[j] is None:
            j += 1
        n, racha = j - k, normas[k:j]
        vecinas = [[t["norm"] for t in toks[:k] if t][-n:], [t["norm"] for t in toks[j:] if t][:n]]
        if n >= 2 and any(
            difflib.SequenceMatcher(None, v, racha, autojunk=False).find_longest_match(0, len(v), 0, n).size >= 2
            for v in vecinas
        ):
            grupo += 1
            for it in items[k:j]:
                it.update(tipo="repeticion", grupo=grupo)
        k = j

    pausas_largas = pausas_inesperadas = 0
    for j in range(len(hyp) - 1):
        gap = hyp[j + 1]["inicio"] - hyp[j]["fin"]
        if gap < umbral_pausa:
            continue
        idx = item_de_hyp[j]
        items[idx]["pausa_despues"] = round(gap, 2)
        pausas_largas += 1
        if items[idx]["tipo"] in ("correcta", "sustitucion") and not toks[idx]["fin_frase"]:
            pausas_inesperadas += 1

    t0 = hyp[0]["inicio"] if hyp else 0.0
    tiempo = round(hyp[-1]["fin"] - t0, 2) if hyp else 0.0
    return recalcular({
        "palabras_texto": len(ref),
        "palabras_leidas": len(hyp),
        "tiempo_lectura_s": tiempo,
        "ppm": round(len(hyp) / (tiempo / 60), 1) if tiempo else 0,
        "pausas_largas": pausas_largas,
        "pausas_inesperadas": pausas_inesperadas,
        "detalle": items,
    }, ventana_s)


def recalcular(resultado: dict, ventana_s: float = 60.0) -> dict:
    """Recalcula conteos y métricas desde `detalle` (devuelve un dict nuevo). `revisar` cuenta como correcta
    en PCPM y precisión (beneficio de la duda); tiempo, ppm y pausas se conservan."""
    r = copy.deepcopy(resultado)
    items = r["detalle"]
    tipos = [it["tipo"] for it in items]
    n = tipos.count
    buenas = n("correcta") + n("revisar")
    evaluadas = buenas + n("sustitucion") + n("omision")
    tiempo = r["tiempo_lectura_s"]
    # el inicio de la lectura es la primera palabra realmente leída (no una omisión rescatada por la verificación)
    t0 = next((it["inicio"] for it in items if it["leido"] is not None and it["inicio"] is not None), 0.0)
    ventana = min(ventana_s, tiempo)
    en_ventana = sum(
        1 for it in items
        if it["tipo"] in ("correcta", "revisar") and it["inicio"] is not None and it["inicio"] <= t0 + ventana
    )
    r.update({
        "correctas": n("correcta"),
        "sustituciones": n("sustitucion"),
        "omisiones": n("omision"),
        "inserciones": n("insercion"),
        "repeticiones": sum(1 for it in items if it["tipo"] == "repeticion" and "grupo" not in it)
        + len({it["grupo"] for it in items if it["tipo"] == "repeticion" and "grupo" in it}),
        "autocorrecciones": n("autocorreccion"),
        "no_leidas": n("no_leida"),
        "revisar": n("revisar"),
        "errores": n("sustitucion") + n("omision"),
        "pcpm": round(en_ventana / (ventana / 60), 1) if ventana else 0,
        "precision_pct": round(buenas / evaluadas * 100, 1) if evaluadas else 0,
        "texto_completo": n("no_leida") == 0,
    })
    return r
