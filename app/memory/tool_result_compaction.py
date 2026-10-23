"""将旧工具结果改为可定位的索引卡，仅缩短模型输入。"""

import json

from langchain.agents.middleware import ModelRequest, ModelResponse, wrap_model_call
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


OLD_TOOL_RESULT_CHAR_LIMIT = 500
MAX_REFERENCES_PER_KIND = 12


def _short_text(value, limit=100):
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:limit] if value else None


def _collect_references(value, question_ids, material_chunks):
    """仅提取定位字段，不把正文、答案或解释复制进索引卡。"""
    if isinstance(value, list):
        for item in value:
            _collect_references(item, question_ids, material_chunks)
        return
    if not isinstance(value, dict):
        return

    question_id = _short_text(value.get("question_id"))
    if question_id and question_id not in question_ids:
        if len(question_ids) < MAX_REFERENCES_PER_KIND:
            question_ids.append(question_id)

    chunk_id = value.get("chunk_id")
    if isinstance(chunk_id, (str, int)) and len(material_chunks) < MAX_REFERENCES_PER_KIND:
        reference = {"chunk_id": str(chunk_id)[:120]}
        for key in ("topic", "material_id", "original_filename", "source"):
            field = _short_text(value.get(key))
            if field:
                reference[key] = field
        source_id = _short_text(value.get("source_id"))
        if source_id and "material_id" not in reference:
            reference["material_id"] = source_id
        if not any(item["chunk_id"] == reference["chunk_id"] for item in material_chunks):
            reference["position"] = len(material_chunks) + 1
            material_chunks.append(reference)

    for key, nested in value.items():
        if key in {"content", "stem", "options", "student_answer", "correct_answer", "explanation"}:
            continue
        if isinstance(nested, (dict, list)):
            _collect_references(nested, question_ids, material_chunks)


def build_tool_reference_card(message, tool_args):
    try:
        result = json.loads(message.text)
    except (TypeError, ValueError):
        result = {}
    if not isinstance(result, dict):
        result = {}

    question_ids = []
    material_chunks = []
    _collect_references(result, question_ids, material_chunks)

    card = {
        "note": "历史工具正文已省略；需要精确证据时按下面的 ID 重新调用工具。",
        "tool": message.name or "unknown_tool",
    }
    for key in ("status", "course_id", "topic", "requested_topic"):
        field = _short_text(result.get(key))
        if field:
            card[key] = field
    if "course_id" not in card and isinstance(result.get("scope"), dict):
        scope_course_id = _short_text(result["scope"].get("course_id"))
        if scope_course_id:
            card["course_id"] = scope_course_id
    for key in ("topic", "query"):
        field = _short_text(tool_args.get(key))
        if field and key not in card:
            card[key] = field
    source = _short_text(result.get("source"))
    if source:
        card["source"] = source
        for reference in material_chunks:
            reference.setdefault("source", source)
            if card.get("topic"):
                reference.setdefault("topic", card["topic"])
    if question_ids:
        card["question_ids"] = question_ids
    if material_chunks:
        card["material_chunks"] = material_chunks
    return json.dumps(card, ensure_ascii=False, separators=(",", ":"))


def compact_old_tool_results(messages):
    """本轮结果保留原文；历史长结果改为带来源 ID 的索引卡。"""
    latest_user_index = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if isinstance(messages[index], HumanMessage)
        ),
        None,
    )
    if latest_user_index is None:
        return list(messages)

    tool_args_by_id = {}
    compacted = []
    for index, message in enumerate(messages):
        if isinstance(message, AIMessage):
            for tool_call in message.tool_calls:
                if tool_call.get("id"):
                    tool_args_by_id[tool_call["id"]] = tool_call.get("args") or {}

        if (
            index < latest_user_index
            and isinstance(message, ToolMessage)
            and len(str(message.content)) > OLD_TOOL_RESULT_CHAR_LIMIT
        ):
            compacted.append(message.model_copy(update={
                "content": build_tool_reference_card(
                    message,
                    tool_args_by_id.get(message.tool_call_id, {}),
                ),
            }))
        else:
            compacted.append(message)
    return compacted


@wrap_model_call
def compact_old_tool_results_for_model(
    request: ModelRequest,
    handler,
) -> ModelResponse:
    """不修改 checkpoint，只在本次模型请求中使用索引卡。"""
    return handler(request.override(
        messages=compact_old_tool_results(request.messages),
    ))
