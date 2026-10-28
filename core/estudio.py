"""Estudio de validación de prosodia: puntajes Rasinski de docentes frente a un modelo acústico ciego.

El modelo corre en segundo plano (app/worker.py) y su salida se guarda en la base; la interfaz de Evaluar nunca la muestra.
Los informes de avance no incluyen puntajes ni medidas del modelo, para mantener el ciego.
"""
import json
import math
import statistics
from collections import Counter
from datetime import datetime

import pandas as pd

from core import referencias

HITOS = (30, 100)
DIMENSIONES = list(referencias.RASINSKI)
MEDIDAS_INFORME = ("pct_pausa_en_punto", "palabras_por_grupo", "pausas_intra_por_100", "cv_velocidad",
                   "rango_f0_st", "rango_intensidad_db")
ETIQUETA = {"VALIDO": "VÁLIDO", "NO_VALIDO": "NO VÁLIDO", "UTIL_COMO_SUGERENCIA": "ÚTIL COMO SUGERENCIA"}
BLINDAJE = "Este informe no incluye los puntajes del modelo para mantener el ciego."

# Criterio preregistrado: fijado el 2026-10-27, antes de recoger datos. No cambiarlo tras ver resultados.
KAPPA_VALIDO = 0.60
KAPPA_NO_DELEGABLE = 0.40
ACUERDO_MAS_MENOS_1_MIN = 90.0
CRITERIO = ("**Criterio preregistrado** (fijado el 27/10/2026, antes de recoger datos). "
            "**Válido:** todas las dimensiones con κ ponderado ≥ 0,60 y acuerdo ±1 punto ≥ 90 %. "
            "**No válido:** alguna dimensión con κ ponderado < 0,40 (esa dimensión queda como no delegable). "
            "**Útil como sugerencia:** el resto, que el docente confirma.")


def _prosodia():
    from core import prosodia  # importación diferida: el módulo puede no existir todavía
    return prosodia


def _json(texto, tipo):
    if not isinstance(texto, str):
        return None
    try:
        valor = json.loads(texto)
    except ValueError:
        return None
    return valor if isinstance(valor, tipo) else None


def _punto(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 4 else None


def _lista4(v):
    return isinstance(v, list) and len(v) == 4 and all(_punto(x) is not None for x in v)


def _modelo4(v):
    return isinstance(v, list) and len(v) == 4 and all(x is None or _punto(x) is not None for x in v) and any(
        x is not None for x in v)


def formatear(x, dec=1):
    """Número con coma decimal (estilo chileno); None se muestra como guion."""
    if x is None:
        return "—"
    return f"{0.0 if round(x, dec) == 0 else x:.{dec}f}".replace(".", ",")  # evita «-0,00»


def _celda(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return formatear(v) if isinstance(v, float) else v


def _pct(x):
    return "—" if x is None else f"{formatear(x)} %"


def _fecha(iso):
    return "/".join(reversed(str(iso)[:10].split("-")))


def _tabla(encabezados, filas):
    lineas = ["| " + " | ".join(encabezados) + " |", "|" + "|".join("---" for _ in encabezados) + "|"]
    lineas += ["| " + " | ".join(str(c) for c in f) + " |" for f in filas]
    return "\n".join(lineas)


# --- Pares humano / modelo ---------------------------------------------------------------------

def pares(df):
    """Lecturas completas con puntaje humano (4 dimensiones) y puntaje del modelo. Solo códigos anónimos, nunca nombres."""
    salida = []
    if df is None or df.empty:
        return salida
    for _, f in df.iterrows():
        if isinstance(f.get("estado"), str) and f["estado"] != "completa":
            continue
        humano = _json(f.get("rasinski"), list)
        modelo = _json(f.get("prosodia_modelo"), dict) or {}
        if not _lista4(humano) or not _modelo4(modelo.get("puntajes")):
            continue
        humano2 = _json(f.get("rasinski_2"), list)
        salida.append({
            "codigo": f"E{int(f['id']):04d}", "curso": f["curso"], "nivel": int(f["nivel"]), "fecha": f["fecha"],
            "texto_id": int(f["texto_id"]), "humano": humano, "humano2": humano2 if _lista4(humano2) else None,
            "modelo": modelo["puntajes"], "medidas": modelo.get("medidas") or {},
            "calidad": modelo.get("calidad") or {}, "version": modelo.get("version")})
    return sorted(salida, key=lambda p: p["fecha"])


def muestra_hito(pares_, hito):
    """Las primeras `hito` lecturas por fecha (el informe de 100 incluye las 30 primeras)."""
    return sorted(pares_, key=lambda p: p["fecha"])[:hito]


# --- Métricas de acuerdo -----------------------------------------------------------------------

def kappa_ponderado(a, b, categorias=(1, 2, 3, 4)):
    """Kappa de Cohen con pesos cuadráticos. None si hay menos de 2 pares o no hay desacuerdo esperable."""
    pts = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    n = len(pts)
    if n < 2:
        return None
    k = len(categorias)
    idx = {c: i for i, c in enumerate(categorias)}
    observada = [[0] * k for _ in range(k)]
    for x, y in pts:
        observada[idx[x]][idx[y]] += 1
    filas = [sum(r) for r in observada]
    columnas = [sum(observada[i][j] for i in range(k)) for j in range(k)]
    peso = lambda i, j: ((i - j) / (k - 1)) ** 2  # peso de desacuerdo cuadrático
    desacuerdo_obs = sum(peso(i, j) * observada[i][j] for i in range(k) for j in range(k))
    desacuerdo_esp = sum(peso(i, j) * filas[i] * columnas[j] for i in range(k) for j in range(k)) / n
    if desacuerdo_esp == 0:
        return None
    return 1 - desacuerdo_obs / desacuerdo_esp


def _contra(p, contra):
    return p["modelo"] if contra == "modelo" else p["humano2"]


def metricas(pares_, dim_index, contra="modelo"):
    """Acuerdo en una dimensión entre el humano principal y `contra` ("modelo" o "humano2")."""
    pts = []
    for p in pares_:
        v = _contra(p, contra)
        if v is None or _punto(v[dim_index]) is None:
            continue
        pts.append((p["humano"][dim_index], v[dim_index]))
    n = len(pts)
    matriz = [[0] * 4 for _ in range(4)]
    for x, y in pts:
        matriz[x - 1][y - 1] += 1
    if n == 0:
        return {"n": 0, "acuerdo_exacto_pct": None, "acuerdo_mas_menos_1_pct": None, "kappa_ponderado": None,
                "matriz": matriz}
    kappa = kappa_ponderado([x for x, _ in pts], [y for _, y in pts])
    return {
        "n": n,
        "acuerdo_exacto_pct": round(100 * sum(x == y for x, y in pts) / n, 1),
        "acuerdo_mas_menos_1_pct": round(100 * sum(abs(x - y) <= 1 for x, y in pts) / n, 1),
        "kappa_ponderado": None if kappa is None else round(kappa, 3),
        "matriz": matriz,
    }


def _pearson(x, y):
    n = len(x)
    if n < 3:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def metricas_total(pares_, contra="modelo"):
    """Puntaje total (4 a 16): r de Pearson, diferencia media (contra − humano) y su desviación estándar."""
    x, y = [], []
    for p in pares_:
        v = _contra(p, contra)
        if v is None or any(_punto(d) is None for d in v):
            continue
        x.append(sum(p["humano"]))
        y.append(sum(v))
    difs = [b - a for a, b in zip(x, y)]
    n = len(difs)
    r = _pearson(x, y)
    return {"n": n, "r": None if r is None else round(r, 3),
            "dif_media": round(statistics.mean(difs), 2) if n else None,
            "dif_sd": round(statistics.stdev(difs), 2) if n >= 2 else None}


def veredicto(metricas_por_dim):
    """Aplica el criterio preregistrado. Devuelve (estado, texto en español, dimensiones no delegables)."""
    no_delegables = [d for d, m in metricas_por_dim.items()
                     if m["kappa_ponderado"] is not None and m["kappa_ponderado"] < KAPPA_NO_DELEGABLE]
    if no_delegables:
        return ("NO_VALIDO",
                f"Al menos una dimensión tiene κ ponderado < {formatear(KAPPA_NO_DELEGABLE, 2)}. "
                f"Dimensiones no delegables al modelo: {', '.join(no_delegables)}.", no_delegables)
    valido = all(m["kappa_ponderado"] is not None and m["kappa_ponderado"] >= KAPPA_VALIDO
                 and m["acuerdo_mas_menos_1_pct"] is not None and m["acuerdo_mas_menos_1_pct"] >= ACUERDO_MAS_MENOS_1_MIN
                 for m in metricas_por_dim.values())
    if valido:
        return ("VALIDO",
                f"Todas las dimensiones alcanzan κ ponderado ≥ {formatear(KAPPA_VALIDO, 2)} y acuerdo ±1 punto ≥ "
                f"{formatear(ACUERDO_MAS_MENOS_1_MIN, 0)} %. Según el criterio preregistrado, el modelo puede "
                "delegarse en estas cuatro dimensiones.", [])
    sin_kappa = [d for d, m in metricas_por_dim.items() if m["kappa_ponderado"] is None]
    nota = f" No se pudo calcular κ en: {', '.join(sin_kappa)}." if sin_kappa else ""
    return ("UTIL_COMO_SUGERENCIA",
            "Ninguna dimensión queda bajo κ ponderado 0,40, pero no todas cumplen el umbral de validez "
            f"(κ ≥ {formatear(KAPPA_VALIDO, 2)} y acuerdo ±1 ≥ {formatear(ACUERDO_MAS_MENOS_1_MIN, 0)} %)."
            + nota + " El modelo sirve como sugerencia que el docente confirma, no como puntaje delegado.", [])


def analizar(muestra):
    """Todas las métricas de una muestra, con el veredicto. Lo usan los informes y la pantalla de Coordinación."""
    por_dim = {d: metricas(muestra, i) for i, d in enumerate(DIMENSIONES)}
    tiene_h2 = any(p["humano2"] for p in muestra)
    return {
        "por_dim": por_dim,
        "inter": {d: metricas(muestra, i, "humano2") for i, d in enumerate(DIMENSIONES)} if tiene_h2 else None,
        "total": metricas_total(muestra),
        "total_inter": metricas_total(muestra, "humano2") if tiene_h2 else None,
        "veredicto": veredicto(por_dim),
    }


# --- Tablas y reportes -------------------------------------------------------------------------

def tabla_datos(muestra):
    """Una fila por lectura con puntajes humanos, del modelo y medidas. Para el anexo y la descarga en Excel."""
    filas = []
    for p in muestra:
        fila = {"Código": p["codigo"], "Curso": p["curso"], "Nivel": p["nivel"], "Fecha": _fecha(p["fecha"])}
        fila.update({f"Humano · {d}": v for d, v in zip(DIMENSIONES, p["humano"])})
        fila.update({f"Modelo · {d}": v for d, v in zip(DIMENSIONES, p["modelo"])})
        fila.update({k: p["medidas"].get(k) for k in MEDIDAS_INFORME})
        fila["SNR (dB)"] = p["calidad"].get("snr_db")
        filas.append(fila)
    return pd.DataFrame(filas)


def _version():
    try:
        return _prosodia().VERSION
    except Exception:
        return "—"


def _encabezado(titulo):
    hoy = datetime.now().strftime("%d/%m/%Y")
    return f"# {titulo}\n\nFecha del informe: {hoy} · Versión del análisis acústico: {_version()}\n\n"


def _muestra_texto(pares_):
    cursos = ", ".join(f"{c} ({k})" for c, k in sorted(Counter(p["curso"] for p in pares_).items())) or "—"
    niveles = ", ".join(f"{n}° básico ({k})" for n, k in sorted(Counter(p["nivel"] for p in pares_).items())) or "—"
    fechas = sorted(p["fecha"] for p in pares_)
    rango = f"del {_fecha(fechas[0])} al {_fecha(fechas[-1])}" if fechas else "—"
    return f"**Cursos:** {cursos}. **Niveles:** {niveles}. **Fechas:** {rango}."


def _calidad(pares_):
    """(mediana de SNR en dB, % de lecturas con SNR < 15 dB, cuántas tienen dato)."""
    snr = [p["calidad"]["snr_db"] for p in pares_ if p["calidad"].get("snr_db") is not None]
    if not snr:
        return None, None, 0
    return statistics.median(snr), 100 * sum(s < 15 for s in snr) / len(snr), len(snr)


def informe_avance_md(pares_todos, total_con_rasinski):
    """Avance del estudio. Ciego: no incluye puntajes ni medidas del modelo."""
    n = len(pares_todos)
    mediana, pct_bajo, con_dato = _calidad(pares_todos)
    calidad = ("Sin datos de calidad de audio todavía." if not con_dato else
               f"Mediana del SNR: {formatear(mediana)} dB. Lecturas con SNR < 15 dB: {_pct(pct_bajo)} "
               f"(de {con_dato} con dato).")
    tiene_h2 = any(p["humano2"] for p in pares_todos)
    encabezados = ["Código", "Curso", "Nivel", "Fecha"] + [f"Humano · {d}" for d in DIMENSIONES] + ["Humano · Total"]
    if tiene_h2:
        encabezados += [f"2.º evaluador · {d}" for d in DIMENSIONES] + ["2.º evaluador · Total"]
    encabezados += ["SNR (dB)"]
    filas = []
    for p in pares_todos:
        fila = [p["codigo"], p["curso"], f"{p['nivel']}°", _fecha(p["fecha"])] + p["humano"] + [sum(p["humano"])]
        if tiene_h2:
            h2 = p["humano2"] or [None] * 4
            fila += [v if v is not None else "—" for v in h2] + [sum(p["humano2"]) if p["humano2"] else "—"]
        fila.append(formatear(p["calidad"].get("snr_db")))
        filas.append(fila)
    cursos = Counter(p["curso"] for p in pares_todos)
    niveles = Counter(p["nivel"] for p in pares_todos)
    return "\n".join([
        _encabezado("Estudio de validación de prosodia · Avance"),
        f"**Progreso:** {n} de {HITOS[0]} (hito 1) / {n} de {HITOS[1]} (hito 2). "
        f"Lecturas con puntaje humano registrado: {total_con_rasinski}.",
        "", CRITERIO, "", BLINDAJE, "",
        "## Lecturas por curso", _tabla(["Curso", "Lecturas"], sorted(cursos.items())) if cursos else "Sin lecturas aún.",
        "", "## Lecturas por nivel",
        _tabla(["Nivel", "Lecturas"], [(f"{k}° básico", v) for k, v in sorted(niveles.items())]) if niveles else "Sin lecturas aún.",
        "", "## Calidad del audio", calidad, "",
        "## Lecturas incluidas", _tabla(encabezados, filas) if filas else "Sin lecturas aún.", "",
    ])


def informe_final_md(pares_, hito):
    """Informe del hito (30 o 100 lecturas): las primeras `hito` por fecha, con métricas, veredicto y anexo de datos."""
    muestra = muestra_hito(pares_, hito)
    a = analizar(muestra)
    mediana, pct_bajo, _ = _calidad(muestra)
    estado, texto, no_delegables = a["veredicto"]
    datos = tabla_datos(muestra)
    incompleta = " **Muestra incompleta: este informe es provisional.**" if len(muestra) < hito else ""
    partes = [
        _encabezado(f"Estudio de validación de prosodia · Informe final ({hito} lecturas)"),
        CRITERIO, "",
        f"**Muestra:** {len(muestra)} de {hito} lecturas, ordenadas por fecha (acumulativo).{incompleta} "
        f"{_muestra_texto(muestra)}", "",
        "## Concordancia por dimensión · humano frente a modelo", _tabla(
            ["Dimensión", "n", "Acuerdo exacto", "Acuerdo ±1", "κ ponderado"],
            [[d, m["n"], _pct(m["acuerdo_exacto_pct"]), _pct(m["acuerdo_mas_menos_1_pct"]),
              formatear(m["kappa_ponderado"], 2)] for d, m in a["por_dim"].items()]), "",
    ]
    if a["inter"]:
        partes += ["## Concordancia entre evaluadores humanos", _tabla(
            ["Dimensión", "n", "Acuerdo exacto", "Acuerdo ±1", "κ ponderado"],
            [[d, m["n"], _pct(m["acuerdo_exacto_pct"]), _pct(m["acuerdo_mas_menos_1_pct"]),
              formatear(m["kappa_ponderado"], 2)] for d, m in a["inter"].items()]),
            "Referencia: concordancia entre dos docentes en las mismas lecturas.", ""]
    total = [["Humano frente a modelo", a["total"]["n"], formatear(a["total"]["r"], 2),
              formatear(a["total"]["dif_media"], 2), formatear(a["total"]["dif_sd"], 2)]]
    if a["total_inter"]:
        t = a["total_inter"]
        total.append(["Humano frente a 2.º evaluador", t["n"], formatear(t["r"], 2), formatear(t["dif_media"], 2),
                      formatear(t["dif_sd"], 2)])
    partes += ["## Puntaje total (4 a 16)", _tabla(
        ["Comparación", "n", "r de Pearson", "Diferencia media", "DE de la diferencia"], total),
        "La diferencia se calcula como segundo puntaje menos humano principal.", ""]
    partes.append("## Matrices de confusión (filas: humano · columnas: modelo)")
    for d, m in a["por_dim"].items():
        partes += [f"### {d}", _tabla(["Humano \\ modelo", "1", "2", "3", "4"],
                                      [[i + 1] + fila for i, fila in enumerate(m["matriz"])]), ""]
    partes += ["## Veredicto", f"**{ETIQUETA[estado]}.** {texto}"]  # el texto ya nombra las dimensiones no delegables
    partes += ["", "## Limitaciones", "- Un solo evaluador humano principal. La concordancia con un segundo "
               "evaluador existe solo en las lecturas donde se registró y no reemplaza un diseño con varios evaluadores.",
               f"- Tamaño de muestra: {len(muestra)} lecturas. Con muestras pequeñas, κ y los porcentajes tienen intervalos amplios.",
               (f"- Calidad de audio: mediana de SNR {formatear(mediana)} dB; {_pct(pct_bajo)} de las lecturas con SNR < 15 dB. "
                "El ruido afecta las medidas acústicas." if mediana is not None else
                "- Calidad de audio: sin datos de SNR en esta muestra."),
               "- Las reglas del modelo se fijaron antes de recoger los datos y no se ajustaron con esta muestra. "
               "Cualquier cambio posterior debe declararse.",
               "- La escala de Rasinski describe lo que el oyente percibe y el modelo mide rasgos acústicos. "
               "Un desacuerdo no indica por sí solo que uno de los dos esté equivocado.", "",
               "## Anexo · datos por lectura", _tabla(list(datos.columns), [[_celda(v) for v in f] for f in datos.values.tolist()])
               if len(datos) else "Sin lecturas.", ""]
    return "\n".join(partes)
