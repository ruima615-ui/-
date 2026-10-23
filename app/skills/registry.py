"""Allowlisted, read-only loader for student Agent skill documents."""

from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent
SKILLS = {
    "wrong_question_diagnosis": "wrong_question_diagnosis/SKILL.md",
    "grounded_review_plan": "grounded_review_plan/SKILL.md",
}


def read_student_skill(skill_id: str) -> dict:
    """Return instructions only for registered skills; never accept arbitrary paths."""
    relative_path = SKILLS.get(skill_id)
    if relative_path is None:
        return {"status": "skill_not_found", "available_skills": sorted(SKILLS)}
    path = SKILL_ROOT / relative_path
    return {
        "status": "success",
        "skill_id": skill_id,
        "version": "1.0",
        "instructions": path.read_text(encoding="utf-8"),
    }
