"""Imports a lectura_app database (datos/lectura.db of a teacher's PC) into lectura-api.

Dry run by default: shows what would be imported and writes the matching report, without touching anything.

    python scripts/migrate_lectura_app.py --sqlite /ruta/datos/lectura.db --institution-id 12 \\
        --audios /ruta/datos/audios --report emparejamiento.csv
    # revise emparejamiento.csv; complete student_id where it says "ambiguo" or "sin pareja"
    python scripts/migrate_lectura_app.py ... --mapping emparejamiento.csv --apply

Needs DATABASE_URL (and R2_* to upload the audio), the same as the service.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app import legacy  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sqlite", required=True, help="lectura.db de lectura_app")
    p.add_argument("--institution-id", required=True, type=int, help="institución de Colegio Smart")
    p.add_argument("--audios", help="carpeta datos/audios del PC (opcional)")
    p.add_argument("--mapping", help="CSV legacy_id,student_id con emparejamientos manuales")
    p.add_argument("--evaluator-user-id", type=int, help="usuario de Colegio Smart dueño de las evaluaciones importadas")
    p.add_argument("--report", default="emparejamiento.csv", help="CSV de salida con el emparejamiento")
    p.add_argument("--apply", action="store_true", help="escribe en la base y sube los audios (sin esto, solo simula)")
    a = p.parse_args(argv)

    summary = legacy.import_legacy(a.sqlite, a.institution_id, audios_dir=a.audios, mapping_path=a.mapping,
                                   evaluator_user_id=a.evaluator_user_id, apply=a.apply)
    legacy.write_report(summary, a.report)
    counts = summary.counts()
    print("APLICADO" if summary.applied else "SIMULACIÓN (nada se escribió; use --apply para importar)")
    print(f"Estudiantes locales: {len(summary.students)} · "
          + " · ".join(f"{legacy.STATUS_ES[k]}: {v}" for k, v in sorted(counts.items())))
    print(f"Evaluaciones importadas: {summary.assessments_imported} · ya importadas antes: "
          f"{sum(s.skipped_existing for s in summary.students)} · borradores omitidos: {sum(s.drafts for s in summary.students)}")
    print(f"Textos creados: {summary.texts_created} · audios subidos: {summary.audio_uploaded} · "
          f"audios no encontrados: {summary.audio_missing}")
    pending = counts.get("ambiguous", 0) + counts.get("unmatched", 0)
    if pending:
        print(f"{pending} estudiante(s) sin emparejar: complete student_id en {a.report} y páselo con --mapping.")
    print(f"Reporte: {a.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
