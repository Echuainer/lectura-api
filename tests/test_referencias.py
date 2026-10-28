import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import referencias as r


def test_momento_del_anio_escolar():
    assert r.momento("2026-04-10") == "inicio"
    assert r.momento("2026-07-01") == "mitad"
    assert r.momento("2026-10-23") == "fin" and r.momento("2027-01-15") == "fin"


def test_percentil_ht():
    assert r.percentil_ht(146, 5, "2026-10-23") == ("P50", "fin", 146)
    assert r.percentil_ht(80, 5, "2026-10-23")[0] == "<P10"
    assert r.percentil_ht(250, 5, "2026-10-23")[0] == ">P90"
    assert r.percentil_ht(159, 8, "2026-04-01") == ("P75", "inicio", 132)  # 8° usa la norma de 6°
    assert r.percentil_ht(30, 1, "2026-04-01") is None  # 1° no tiene norma de inicio de año
    assert r.percentil_ht(float("nan"), 5, "2026-10-23") is None


def test_rasinski():
    assert r.interpretar_rasinski([3, 3, 2, 2]) == (10, "Buen progreso")
    assert r.interpretar_rasinski([2, 2, 2, 2]) == (8, "En desarrollo")
    assert r.interpretar_rasinski([1, 2, 2, 2])[1] == "Requiere apoyo en fluidez"
    assert r.interpretar_rasinski([3, None, 2, 2]) is None
    assert all(len(v) == 4 for v in r.RASINSKI.values())
