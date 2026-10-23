"""Add the structured diagnosis handoff table without changing existing data."""

from sqlalchemy import inspect

from app.core.database import engine
from app.models.entities import StudentSessionDiagnosis


def main() -> None:
    StudentSessionDiagnosis.__table__.create(bind=engine, checkfirst=True)
    assert inspect(engine).has_table(StudentSessionDiagnosis.__tablename__)
    print("student_session_diagnoses ready")


if __name__ == "__main__":
    main()
