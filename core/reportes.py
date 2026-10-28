"""Cálculos de los reportes de curso y de coordinación (sin interfaz, testeables)."""
import json

import pandas as pd

from core import escalas

GRUPOS = {
    "ambos": ("Ambos adecuados", "Enriquecimiento: lectura expresiva, teatro leído y comprensión", "En clase regular"),
    "velocidad": ("Solo velocidad baja", "Lecturas repetidas cronometradas con texto del nivel", "Diaria, 10 min"),
    "fluidez": ("Solo fluidez baja", "Lectura en eco, fraseo y uso de la puntuación", "2 veces por semana"),
    "ninguno": ("Bajo lo esperado en ambas", "Apoyo intensivo en grupo pequeño; evaluar derivación", "3 veces por semana"),
    "incompleto": ("Sin fluidez registrada", "Completar la categoría de fluidez en la evaluación", "—"),
}
TIPOS_ERROR = {"sustitucion": "Sustituciones", "omision": "Omisiones", "repeticion": "Repeticiones",
               "autocorreccion": "Autocorrecciones", "insercion": "Inserciones"}


def _grupo(rango_v, rango_f):
    if rango_v is None or rango_f is None:
        return "incompleto"
    v, f = rango_v == "Adecuado", rango_f == "Adecuado"
    return "ambos" if v and f else "fluidez" if v else "velocidad" if f else "ninguno"


def preparar(df: pd.DataFrame, marcos: dict, precision_minima: float) -> pd.DataFrame:
    """Agrega a las evaluaciones: PPM efectivo, rangos, fluidez, grupo de apoyo, avance y palabras por revisar."""
    df = df.copy()
    if df.empty:
        return df
    df["categoria"] = df["categoria"].fillna("Sin clasificar")
    df["pcpm_efectivo"] = df["pcpm_ajustado"].fillna(df["pcpm"])
    # evaluaciones anteriores a los marcos (o con clave desconocida) se leen con Mineduc
    df["marco"] = df["marco"].map(lambda m: m if isinstance(m, str) and m in marcos else "mineduc")
    expresion = [None if pd.isna(x) else int(x) for x in df["expresion"]]
    rango_v = [escalas.rango_velocidad(c, n, marcos[m]) for c, n, m in zip(df["categoria"], df["nivel"], df["marco"])]
    rango_f = [escalas.rango_fluidez(x, n, marcos[m]) for x, n, m in zip(expresion, df["nivel"], df["marco"])]
    # el grupo se calcula con las listas: al pasar a la columna, None se vuelve NaN
    df["grupo"] = [_grupo(v, f) for v, f in zip(rango_v, rango_f)]
    df["rango_velocidad"], df["rango_fluidez"] = rango_v, rango_f
    df["fluidez"] = [None if x is None else marcos[m]["fluidez"][x - 1] for x, m in zip(expresion, df["marco"])]
    # precisión NaN no cuenta como riesgo: la comparación da False
    df["riesgo"] = (df["rango_velocidad"] == "Bajo lo esperado") | (df["rango_fluidez"] == "Bajo lo esperado") | (
        df["precision_pct"] < precision_minima)
    df["revisar"] = [int(json.loads(r).get("revisar", 0)) if isinstance(r, str) else 0 for r in df["resultado_json"]]
    df = df.sort_values("fecha")
    df["delta"] = df.groupby("estudiante_id")["pcpm_efectivo"].diff().round(1)  # avance respecto de la evaluación anterior
    return df.sort_values("fecha", ascending=False)


def ultima_por_estudiante(df: pd.DataFrame) -> pd.DataFrame:
    """Una fila por estudiante: su evaluación más reciente dentro de df."""
    return df.sort_values("fecha", ascending=False).drop_duplicates("estudiante_id")


def pct_adecuado(rangos) -> float | None:
    validos = pd.Series(rangos).dropna()
    return round(float((validos == "Adecuado").mean() * 100)) if len(validos) else None


def distribucion(df: pd.DataFrame, marco: dict, nivel: int) -> list[dict]:
    """Conteo por categoría de velocidad, de menor a mayor, según los cortes del nivel."""
    nombres = [c for c, _ in reversed(marco["niveles"].get(str(nivel), []))]
    conteo = df["categoria"].value_counts()
    total = int(conteo.sum()) or 1
    filas = []
    for i, nombre in enumerate(nombres):
        minimo = dict(marco["niveles"][str(nivel)])[nombre]
        siguiente = dict(marco["niveles"][str(nivel)]).get(nombres[i + 1]) if i + 1 < len(nombres) else None
        filas.append({"categoria": nombre, "n": int(conteo.get(nombre, 0)), "pct": round(conteo.get(nombre, 0) / total * 100),
                      "rango": f"{minimo}–{siguiente - 1}" if siguiente else f"{minimo}+",
                      "adecuado": escalas.rango_velocidad(nombre, nivel, marco) == "Adecuado"})
    return filas


def conteo_grupos(df: pd.DataFrame) -> dict[str, int]:
    conteo = df["grupo"].value_counts()
    return {g: int(conteo.get(g, 0)) for g in GRUPOS}


def errores_frecuentes(df: pd.DataFrame) -> list[dict]:
    """Proporción de cada tipo de error sobre el total de marcas del grupo (de más a menos frecuente)."""
    cuenta = {t: 0 for t in TIPOS_ERROR}
    for r in df["resultado_json"].dropna():
        for it in json.loads(r).get("detalle", []):
            if it.get("tipo") in cuenta:
                cuenta[it["tipo"]] += 1
    total = sum(cuenta.values())
    if not total:
        return []
    return sorted(({"tipo": TIPOS_ERROR[t], "n": n, "pct": round(n / total * 100)} for t, n in cuenta.items() if n),
                  key=lambda x: -x["n"])


def evolucion(df: pd.DataFrame) -> pd.DataFrame:
    """% de estudiantes con velocidad adecuada por nivel (filas) y medición (columnas, en orden)."""
    if df.empty:
        return pd.DataFrame()
    tabla = df.groupby(["nivel", "periodo"])["rango_velocidad"].apply(pct_adecuado).unstack("periodo")
    return tabla.reindex(sorted(tabla.columns), axis=1)


def alertas(df: pd.DataFrame, inscritos: dict[str, int]) -> list[dict]:
    """Alertas para coordinación sobre la medición filtrada en df (una fila por estudiante).
    inscritos: curso -> estudiantes activos."""
    salida = []
    for curso, g in df.groupby("curso"):
        flu, vel = pct_adecuado(g["rango_fluidez"]), pct_adecuado(g["rango_velocidad"])
        if flu is not None and flu < 50:
            salida.append({"titulo": f"{curso} · fluidez", "texto": f"Solo {flu}% con fluidez adecuada.", "nivel": "alta"})
        if vel is not None and vel < 50:
            salida.append({"titulo": f"{curso} · velocidad", "texto": f"Solo {vel}% con velocidad adecuada.", "nivel": "media"})
    retroceden = int((df["delta"] < 0).sum())
    if retroceden:
        salida.append({"titulo": "Retrocesos", "texto": f"{retroceden} estudiante(s) bajaron su PPM respecto de la medición anterior.",
                       "nivel": "media"})
    sin_evaluar = sum(max(n - int((df["curso"] == c).sum()), 0) for c, n in inscritos.items())
    por_revisar = int((df["revisar"] > 0).sum())
    if sin_evaluar or por_revisar:
        salida.append({"titulo": "Pendientes", "texto": f"{sin_evaluar} estudiante(s) sin evaluar y {por_revisar} "
                       "evaluación(es) con palabras por revisar.", "nivel": "info"})
    return salida


def palabras_con_error(df: pd.DataFrame, limite: int = 15) -> list[dict]:
    """Palabras del texto que más se leyeron mal (sustitución u omisión), con cuántos estudiantes y qué leyeron."""
    from core.analisis import normalizar
    conteo = {}
    for est, r in zip(df["estudiante_id"], df["resultado_json"]):
        if not isinstance(r, str):
            continue
        for it in json.loads(r).get("detalle", []):
            if it.get("tipo") not in ("sustitucion", "omision") or not it.get("ref"):
                continue
            x = conteo.setdefault(normalizar(it["ref"]), {"palabra": it["ref"].strip(".,;:¡!¿?«»\"()"), "errores": 0,
                                                          "estudiantes": set(), "leido": []})
            x["errores"] += 1
            x["estudiantes"].add(est)
            leido = it.get("leido") or "(omitida)"
            if leido not in x["leido"]:
                x["leido"].append(leido)
    filas = sorted(conteo.values(), key=lambda x: (-len(x["estudiantes"]), -x["errores"], x["palabra"]))[:limite]
    return [{**x, "estudiantes": len(x["estudiantes"])} for x in filas]


def resumen_textos(df: pd.DataFrame) -> pd.DataFrame:
    """Una fila por texto: cuántos lo leyeron y su PPM y precisión promedio (para comparar dificultad)."""
    ultima = df.sort_values("fecha").groupby(["texto_id", "estudiante_id"]).tail(1)
    return (ultima.groupby(["texto_id", "titulo"])
            .agg(estudiantes=("estudiante_id", "nunique"), ppm=("pcpm_efectivo", "mean"), precision=("precision_pct", "mean"))
            .astype({"ppm": float, "precision": float}).round(1).reset_index().sort_values("ppm"))


EJES_RADAR = ["Velocidad", "Precisión", "Fluidez", "Continuidad"]
TOPE_RADAR = 150


def perfil_radar(fila, marco: dict, precision_minima: float) -> dict:
    """Logro de una evaluación por eje, en % de la expectativa del nivel (100 = la cumple; tope 150; None = sin dato).
    Continuidad: % de palabras leídas sin repetir, autocorregir, insertar ni pausar fuera de puntuación,
    frente a una referencia interna de 95% (no hay norma oficial para este eje)."""
    nivel = str(int(fila["nivel"]))
    tope = lambda v: None if v is None or pd.isna(v) else round(min(max(float(v), 0), TOPE_RADAR))
    minimo = dict(marco["niveles"].get(nivel, [])).get(marco["adecuado_desde"])
    flu_ref = (marco.get("fluidez_minima") or {}).get(nivel) or len(marco["fluidez"])
    r = json.loads(fila["resultado_json"]) if isinstance(fila["resultado_json"], str) else {}
    leidas = r.get("palabras_leidas")
    cortes = sum(r.get(k, 0) or 0 for k in ("repeticiones", "autocorrecciones", "inserciones", "pausas_inesperadas"))
    continuidad = 100 * (1 - cortes / leidas) if leidas else None
    return {
        "Velocidad": tope(fila["pcpm_efectivo"] / minimo * 100) if minimo else None,
        "Precisión": tope(fila["precision_pct"] / precision_minima * 100) if pd.notna(fila["precision_pct"]) else None,
        "Fluidez": tope(fila["expresion"] / flu_ref * 100) if pd.notna(fila["expresion"]) else None,
        "Continuidad": tope(continuidad / 95 * 100) if continuidad is not None else None,
    }


def resumen_rasinski(df: pd.DataFrame) -> dict | None:
    """Promedios de la escala de Rasinski entre quienes la tienen registrada (None si nadie la tiene)."""
    from core.referencias import RASINSKI
    filas = [json.loads(x) for x in df.get("rasinski", pd.Series(dtype=object)).dropna()]
    filas = [f for f in filas if len(f) == 4 and all(f)]
    if not filas:
        return None
    dims = {d: round(sum(f[j] for f in filas) / len(filas), 1) for j, d in enumerate(RASINSKI)}
    totales = [sum(f) for f in filas]
    return {"n": len(filas), "total_promedio": round(sum(totales) / len(filas), 1),
            "pct_buen_progreso": round(sum(t >= 10 for t in totales) / len(filas) * 100),
            "por_dimension": dims, "dimension_mas_baja": min(dims, key=dims.get)}
