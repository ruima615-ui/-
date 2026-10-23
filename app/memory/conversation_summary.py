"""在新一轮对话开始时压缩 LangGraph 的旧消息状态。"""

import json

from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.memory.tool_result_compaction import build_tool_reference_card


SUMMARY_TRIGGER_TOKENS = 4000
SUMMARY_MIN_MESSAGES = 12
SUMMARY_KEEP_TURNS = 3
SUMMARY_KEEP_TOKENS = 3000
SUMMARY_MAX_CHARS = 1600
SUMMARY_REFERENCE_MAX_CHARS = 1600
SUMMARY_REFERENCE_MAX_CARDS = 8
SUMMARY_REFERENCE_MARKER = "\n历史引用索引(JSON)："

STUDENT_SUMMARY_PROMPT = """你负责压缩学生课程助手的旧会话。请用中文写不超过 800 字的滚动摘要。
保留：当前学习目标、已讨论的课程与知识点、学生明确表达的学习偏好、
尚未解决的问题，以及后续可能需要重新查询的题目 ID、资料 chunk_id 和来源。
若历史中已有会话摘要，把它与新增内容合并，不要重复。
错误类型诊断或掌握程度若仅是推断，明确标为推断；不要把它写成既定事实。
不要复制完整题干、学生答案、正确答案或资料正文；需要精确证据时应重新调用工具。
不要编造历史中没有的信息。只输出摘要正文。

历史消息：
{messages}
"""


class StudentConversationSummarizationMiddleware(SummarizationMiddleware):
    """仅在学生开启新一轮时摘要，保护本轮工具链的完整性。"""

    def _determine_cutoff_index(self, messages):
        """保留最近的完整问答轮次，并给保留的旧轮次设置 token 上限。"""
        starts = [
            index for index, message in enumerate(messages)
            if isinstance(message, HumanMessage)
            and message.additional_kwargs.get("lc_source") != "summarization"
        ]
        if len(starts) <= 1:
            return 0

        cutoff = starts[-1]  # 本轮用户问题必须原样保留，即使它单独超出预算。
        for start in reversed(starts[max(0, len(starts) - SUMMARY_KEEP_TURNS):-1]):
            if self._partial_token_counter(messages[start:]) > SUMMARY_KEEP_TOKENS:
                break
            cutoff = start
        return cutoff

    @staticmethod
    def _is_new_user_turn(state):
        messages = state.get("messages") or []
        return bool(messages) and isinstance(messages[-1], HumanMessage)

    def before_model(self, state, runtime):
        if not self._is_new_user_turn(state):
            return None
        update = super().before_model(state, runtime)
        return self._add_reference_index(state, update)

    async def abefore_model(self, state, runtime):
        if not self._is_new_user_turn(state):
            return None
        update = await super().abefore_model(state, runtime)
        return self._add_reference_index(state, update)

    @staticmethod
    def _add_reference_index(state, update):
        """将被移除消息里的定位 ID 合并进摘要，限制索引总长度。"""
        if not update:
            return None
        replacements = update["messages"]
        preserved_count = len(replacements) - 2  # RemoveMessage、摘要、保留的近况
        removed = state["messages"][:len(state["messages"]) - preserved_count]
        references = []
        tool_args_by_id = {}
        for message in removed:
            if isinstance(message, HumanMessage) and message.additional_kwargs.get("lc_source") == "summarization":
                if SUMMARY_REFERENCE_MARKER in str(message.content):
                    try:
                        prior = json.loads(str(message.content).rsplit(SUMMARY_REFERENCE_MARKER, 1)[1])
                    except (TypeError, ValueError):
                        prior = []
                    if isinstance(prior, list):
                        references.extend(item for item in prior if isinstance(item, dict))
            if isinstance(message, AIMessage):
                for tool_call in message.tool_calls:
                    if tool_call.get("id"):
                        tool_args_by_id[tool_call["id"]] = tool_call.get("args") or {}
            if isinstance(message, ToolMessage):
                card = json.loads(build_tool_reference_card(
                    message, tool_args_by_id.get(message.tool_call_id, {}),
                ))
                if card.get("question_ids") or card.get("material_chunks"):
                    references.append({
                        key: value for key, value in card.items()
                        if key in {"tool", "course_id", "topic", "source", "question_ids", "material_chunks"}
                    })

        if not references:
            return update
        # 滚动摘要可能再次带入同一引用，只保留它最近的一次出现。
        unique_references = {}
        for item in references:
            key = json.dumps(item, ensure_ascii=False, sort_keys=True)
            unique_references.pop(key, None)
            unique_references[key] = item
        references = list(unique_references.values())
        latest_question = next(
            (
                str(message.content) for message in reversed(state["messages"])
                if isinstance(message, HumanMessage)
                and message.additional_kwargs.get("lc_source") != "summarization"
            ),
            "",
        ).lower()
        for item in references:
            item["question_ids"] = item.get("question_ids", [])[-4:]
            # 保留检索结果的开头，"第二段资料"仍能指向 position=2。
            item["material_chunks"] = item.get("material_chunks", [])[:4]
        def priority(index, item):
            ids = [str(value).lower() for value in item.get("question_ids", [])]
            ids.extend(
                str(chunk.get("chunk_id", "")).lower()
                for chunk in item.get("material_chunks", [])
            )
            explicit_id = any(identifier and identifier in latest_question for identifier in ids)
            topic = str(item.get("topic", "")).lower()
            topic_match = bool(topic and topic in latest_question)
            is_material = bool(item.get("material_chunks"))
            is_question = bool(item.get("question_ids"))
            type_match = (
                (is_material and any(word in latest_question for word in ("资料", "片段", "文档")))
                or (is_question and any(word in latest_question for word in ("错题", "那道题", "题目")))
            )
            return (explicit_id, topic_match, type_match, index)

        ranked = sorted(enumerate(references), key=lambda pair: priority(*pair), reverse=True)
        selected = []
        for _, item in ranked:
            if len(selected) >= SUMMARY_REFERENCE_MAX_CARDS:
                break
            candidate = {**item, "question_ids": list(item.get("question_ids", [])),
                         "material_chunks": list(item.get("material_chunks", []))}
            while candidate["question_ids"] or candidate["material_chunks"]:
                encoded = json.dumps(selected + [candidate], ensure_ascii=False, separators=(",", ":"))
                if len(encoded) <= SUMMARY_REFERENCE_MAX_CHARS:
                    selected.append(candidate)
                    break
                if len(candidate["material_chunks"]) > 1:
                    candidate["material_chunks"].pop()
                elif len(candidate["question_ids"]) > 1:
                    candidate["question_ids"].pop(0)
                else:
                    break
        if selected:
            summary = replacements[1]
            replacements[1] = summary.model_copy(update={
                "content": str(summary.content) + SUMMARY_REFERENCE_MARKER
                + json.dumps(selected, ensure_ascii=False, separators=(",", ":")),
            })
        return update

    @staticmethod
    def _build_new_messages(summary):
        return [HumanMessage(
            content="此前会话摘要（精确证据请重新查询工具）：\n" + summary[:SUMMARY_MAX_CHARS],
            additional_kwargs={"lc_source": "summarization"},
        )]


def build_student_summarization_middleware(model):
    """达到约 4000 token 且至少 12 条消息时，保留至多三轮完整对话。"""
    return StudentConversationSummarizationMiddleware(
        model=model,
        trigger={"tokens": SUMMARY_TRIGGER_TOKENS, "messages": SUMMARY_MIN_MESSAGES},
        keep=("messages", 8),  # 实际保留边界由 _determine_cutoff_index 决定。
        summary_prompt=STUDENT_SUMMARY_PROMPT,
        trim_tokens_to_summarize=6000,
    )
