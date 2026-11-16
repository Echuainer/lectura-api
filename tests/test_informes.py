from types import SimpleNamespace

import pytest

from core import informes, redactores
from core.redactores import Resultado


class Falso:
    """Redactor de prueba: entrega los resultados en orden y guarda lo que recibió."""
    def __init__(self, *resultados):
        self.resultados, self.llamadas = list(resultados), []

    def completar(self, rol, sistema, contenido, max_tokens):
        self.llamadas.append((rol, max_tokens, contenido))
        return self.resultados.pop(0)


def _usar(monkeypatch, falso):
    monkeypatch.setattr(informes, "redactor", lambda proveedor=None: falso)


def test_informe_cortado_se_reintenta_con_mas_margen(monkeypatch):
    falso = Falso(Resultado("a medias", True, "m"), Resultado("completo", False, "m"))
    _usar(monkeypatch, falso)
    assert informes._generar("curso", "s", {"x": 1}, 100) == "completo"
    assert [c[1] for c in falso.llamadas] == [100, 200]
    assert "más breve" in falso.llamadas[1][2]


def test_si_el_reintento_tambien_se_corta_avisa(monkeypatch):
    _usar(monkeypatch, Falso(Resultado("a", True, "m"), Resultado("b", True, "m")))
    assert "quedó cortado" in informes._generar("curso", "s", {}, 10)


def test_llamada_a_ia_deja_una_linea_sin_contenido(monkeypatch, caplog):
    import logging
    caplog.set_level(logging.INFO)
    _usar(monkeypatch, Falso(Resultado("texto secreto", False, "m", 11, 7)))
    informes._generar("alumno", "prompt secreto", {"x": 1}, 100, "student_report")
    [rec] = [r for r in caplog.records if r.name == "lectura.ai"]
    assert rec.getMessage() == "ai call" and rec.op == "student_report" and rec.model == "m"
    assert rec.inputTokens == 11 and rec.outputTokens == 7 and rec.durationMs >= 0
    assert "secreto" not in str(rec.__dict__)


def test_el_proveedor_se_elige_por_variable(monkeypatch):
    monkeypatch.delenv("LECTURA_AI_PROVIDER", raising=False)
    assert isinstance(redactores.redactor(), redactores.RedactorClaude)
    monkeypatch.setenv("LECTURA_AI_PROVIDER", " DeepSeek ")
    assert isinstance(redactores.redactor(), redactores.RedactorDeepSeek)
    monkeypatch.setenv("LECTURA_AI_PROVIDER", "otro")
    with pytest.raises(RuntimeError, match="desconocido"):
        redactores.redactor()


def test_deepseek_envia_el_modelo_sin_pensar_y_lee_la_respuesta(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    visto = {}

    def post(url, **kw):
        visto.update(url=url, **kw)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
            "choices": [{"message": {"content": "texto"}, "finish_reason": "length"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3}})

    monkeypatch.setattr(redactores.httpx, "post", post)
    r = redactores.RedactorDeepSeek().completar("curso", "sistema", "datos", 800)
    assert r == Resultado("texto", True, "deepseek-flash", 5, 3)
    assert visto["json"]["thinking"] == {"type": "disabled"} and visto["json"]["max_tokens"] == 800
    assert visto["json"]["messages"][0] == {"role": "system", "content": "sistema"}


def test_deepseek_sin_clave_falla_visible(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        redactores.RedactorDeepSeek().completar("alumno", "s", "c", 10)


def test_la_institucion_manda_sobre_la_variable(monkeypatch):
    monkeypatch.setenv("LECTURA_AI_PROVIDER", "claude")
    assert isinstance(redactores.redactor("deepseek"), redactores.RedactorDeepSeek)
    assert isinstance(redactores.redactor("anthropic"), redactores.RedactorClaude)
    monkeypatch.setenv("LECTURA_AI_PROVIDER", "deepseek")
    assert isinstance(redactores.redactor("kimi"), redactores.RedactorDeepSeek)  # no soportado aquí: cae al valor por defecto
    assert isinstance(redactores.redactor(None), redactores.RedactorDeepSeek)


def _datos(**metricas):
    m = {"pcpm": 26, "precision_pct": 90.9, "errores": 4, "palabras_leidas": 44, "sustituciones": 3, "omisiones": 1,
         "inserciones": 7, "pausas_inesperadas": 22} | metricas
    return {"nivel": 1, "categoria": "Lenta", "expresion": 1, "marco": "Astoreca", "fluidez_categoria": "Lectura silábica",
            "metricas": m, "sustituciones": [{"texto": "bote", "leido": "voel"}], "omisiones": ["tomate"]}


def test_informe_estandar_bajo_lo_esperado():
    perfil = {"Velocidad": 90, "Precisión": 96, "Fluidez": 33, "Continuidad": 45}
    texto = informes.informe_estandar(_datos(), perfil)
    assert "Velocidad: 26 palabras correctas por minuto" in texto and "90 % de lo esperado (bajo lo esperado)" in texto
    assert "Fluidez: lectura silábica, 33 % de lo esperado (muy por debajo de lo esperado)" in texto
    assert "El eje más descendido es fluidez (33 %)" in texto
    # solo los dos patrones de mayor tasa, sin ejemplos del estudiante
    assert "Predominan las pausas inesperadas (50 por cada 100 palabras, tasa alta)" in texto
    assert "Le siguen las inserciones (16 por cada 100 palabras, tasa alta)" in texto
    assert "sustituciones (" not in texto and "bote" not in texto and "tomate" not in texto
    assert "1) Fraseo" in texto and "(3 veces por semana, 15 minutos)" in texto and "2) Lectura atenta" in texto
    assert "3) Fluidez:" in texto and "4)" not in texto
    assert "especialista" in texto


def test_informe_estandar_logrado_sin_patrones():
    perfil = {"Velocidad": 120, "Precisión": 104, "Fluidez": 100, "Continuidad": 101}
    m = dict(pcpm=80, precision_pct=99.0, errores=0, sustituciones=0, omisiones=0, inserciones=1, pausas_inesperadas=2,
             palabras_leidas=80)
    texto = informes.informe_estandar(_datos(**m), perfil)
    assert "cumple lo esperado para el curso en todos los ejes" in texto
    assert "No hay tipos de error con una tasa relevante" in texto
    assert "1) Enriquecimiento" in texto and "especialista" not in texto


def test_estrategia_nivel_segun_tasa():
    e = informes.ESTRATEGIAS["sustituciones"]
    assert [e.nivel(t) for t in (2, 3, 8)] == [0, 1, 2]
    assert e.plan(4).endswith("(2 veces por semana, 10 minutos).") and e.plan(9).endswith("(diaria, 10 minutos).")
