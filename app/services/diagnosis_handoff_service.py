"""Persist validated diagnoses for reuse in the same student course session."""

import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    ChatSession, Exam, ExamAnswer, ExamAttempt, StudentSessionDiagnosis,
)
from app.services.review_plan_service import (
    associate_diagnoses_with_weak_topics,
    prepare_review_plan_foundation,
)


DIAGNOSIS_MAX_AGE = timedelta(hours=24)


def _utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _fingerprint(db: Session, *, user_id: str, course_id: str, foundation: dict) -> str:
    # The complete selected evidence detects changed answers, grading, stems,
    # explanations and Top-K rank/score, not just unchanged question IDs.
    payload = {
        "scope": foundation["scope"],
        "weak_topics": foundation["weak_topics"],
        "wrong_question_evidence": foundation["wrong_question_evidence"],
        "exam_answers": [
            {
                "attempt_id": row.attempt_id, "attempt_status": row.attempt_status,
                "submitted_at": row.submitted_at,
                "answer_id": row.answer_id, "question_id": row.question_id,
                "answer": row.answer, "grading_status": row.grading_status,
                "is_correct": row.is_correct, "score": row.score,
            }
            for row in db.execute(
                select(
                    ExamAttempt.id.label("attempt_id"),
                    ExamAttempt.status.label("attempt_status"),
                    ExamAttempt.submitted_at.label("submitted_at"),
                    ExamAnswer.id.label("answer_id"),
                    ExamAnswer.question_id.label("question_id"),
                    ExamAnswer.answer.label("answer"),
                    ExamAnswer.grading_status.label("grading_status"),
                    ExamAnswer.is_correct.label("is_correct"),
                    ExamAnswer.score.label("score"),
                )
                .join(Exam, Exam.id == ExamAttempt.exam_id)
                .outerjoin(ExamAnswer, ExamAnswer.exam_attempt_id == ExamAttempt.id)
                .where(ExamAttempt.student_id == user_id, Exam.course_id == course_id)
                .order_by(ExamAttempt.id, ExamAnswer.id)
            )
        ],
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _check_scope(db: Session, *, user_id: str, course_id: str, session_id: str) -> bool:
    session = db.get(ChatSession, session_id)
    return bool(session and session.status == "active"
                and session.user_id == user_id and session.course_id == course_id)


def save_validated_diagnoses(
    db: Session, *, user_id: str, course_id: str, session_id: str,
    diagnoses: list[dict], foundation: dict | None = None,
) -> dict:
    """Validate against fresh Top-2 evidence before writing a structured record."""
    if not _check_scope(db, user_id=user_id, course_id=course_id, session_id=session_id):
        raise PermissionError("诊断所属学生、课程或会话不匹配")
    foundation = foundation or prepare_review_plan_foundation(db, user_id, course_id)
    # A material lookup may be partial/unavailable while the wrong-question
    # diagnosis has already passed structural evidence validation.
    if foundation["status"] not in {
        "success", "partial", "course_materials_not_configured",
    }:
        return {"status": foundation["status"], "diagnoses": []}
    validated = associate_diagnoses_with_weak_topics(
        weak_topics=foundation["weak_topics"],
        wrong_question_evidence=foundation["wrong_question_evidence"],
        diagnoses=diagnoses,
    )
    validated_at = _utc_naive()
    record = StudentSessionDiagnosis(
        user_id=user_id, course_id=course_id, session_id=session_id,
        diagnoses_json=json.dumps(validated, ensure_ascii=False),
        evidence_fingerprint=_fingerprint(
            db, user_id=user_id, course_id=course_id, foundation=foundation),
        validated_at=validated_at,
    )
    db.merge(record)
    db.commit()
    return {
        "status": "success", "course_id": course_id,
        "diagnoses": validated, "evidence_question_ids": [
            item["question_id"] for item in foundation["wrong_question_evidence"]
        ],
        "validated_at": validated_at.isoformat() + "Z",
    }


def load_validated_diagnoses(
    db: Session, *, user_id: str, course_id: str, session_id: str,
    foundation: dict | None = None,
    now: datetime | None = None,
) -> dict:
    """Reuse only when scope, TTL and current database evidence all match."""
    if not _check_scope(db, user_id=user_id, course_id=course_id, session_id=session_id):
        return {"status": "scope_mismatch", "diagnoses": []}
    record = db.get(StudentSessionDiagnosis, (user_id, course_id, session_id))
    if record is None:
        return {"status": "missing", "diagnoses": []}
    now = now or _utc_naive()
    if record.validated_at > now or now - record.validated_at > DIAGNOSIS_MAX_AGE:
        return {"status": "expired", "diagnoses": []}
    foundation = foundation or prepare_review_plan_foundation(db, user_id, course_id)
    if foundation["status"] != "success" or _fingerprint(
        db, user_id=user_id, course_id=course_id, foundation=foundation,
    ) != record.evidence_fingerprint:
        return {"status": "evidence_changed", "diagnoses": []}
    try:
        saved = json.loads(record.diagnoses_json)
        validated = associate_diagnoses_with_weak_topics(
            weak_topics=foundation["weak_topics"],
            wrong_question_evidence=foundation["wrong_question_evidence"],
            diagnoses=saved,
        )
    except (ValueError, TypeError, KeyError):
        return {"status": "invalid_record", "diagnoses": []}
    return {"status": "reused", "diagnoses": validated,
            "validated_at": record.validated_at.isoformat() + "Z"}
