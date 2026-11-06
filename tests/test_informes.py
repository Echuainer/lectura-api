from types import SimpleNamespace

from core import informes


def _respuesta(texto, stop):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=texto)], stop_reason=stop)


def _cliente(respuestas, llamadas):
    def create(**kw):
        llamadas.append(kw)
        return respuestas.pop(0)
    return SimpleNamespace(messages=SimpleNamespace(create=create))


def test_informe_cortado_se_reintenta_con_mas_margen(monkeypatch):
    llamadas = []
    cliente = _cliente([_respuesta("a medias", "max_tokens"), _respuesta("completo", "end_turn")], llamadas)
    monkeypatch.setattr(informes, "_cliente", lambda: cliente)
    assert informes._generar("m", "s", {"x": 1}, 100) == "completo"
    assert [c["max_tokens"] for c in llamadas] == [100, 200]
    assert "más breve" in llamadas[1]["messages"][0]["content"]


def test_si_el_reintento_tambien_se_corta_avisa(monkeypatch):
    cliente = _cliente([_respuesta("a", "max_tokens"), _respuesta("b", "max_tokens")], [])
    monkeypatch.setattr(informes, "_cliente", lambda: cliente)
    assert "quedó cortado" in informes._generar("m", "s", {}, 10)
