"""Applicability of the canonical Lesson lifecycle, independent of Content validity."""
from lifecycle_digest import LifecycleContractError
from package_common import validate_content_v2_input

APPLICABLE = "APPLICABLE"
NOT_APPLICABLE_TO_LESSON_LIFECYCLE = "NOT_APPLICABLE_TO_LESSON_LIFECYCLE"


def lesson_lifecycle_applicability(content):
    """Validate formal Content first; valid zero-Lesson Content remains legal."""
    validate_content_v2_input(content)
    count = len(content["lessons"])
    return {
        "status": APPLICABLE if count else NOT_APPLICABLE_TO_LESSON_LIFECYCLE,
        "lesson_count": count,
        "content_contract_version": content["content_contract_version"],
    }


def require_lesson_lifecycle_applicable(content):
    result = lesson_lifecycle_applicability(content)
    if result["status"] != APPLICABLE:
        message = "Content is valid but contains zero Lessons and is outside the canonical Lesson lifecycle."
        if content.get("delivery_plan", {}).get("mode") == "practice_only":
            message += " practice_only remains valid Content 2.3 and should use the Practice Task / WorkOrder workflow where applicable."
        raise LifecycleContractError(message)
    return result
