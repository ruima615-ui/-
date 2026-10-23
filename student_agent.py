import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.tools import ToolRuntime, tool
from langchain_deepseek import ChatDeepSeek
from sqlalchemy.orm import Session

from app.services.wrong_question_service import (
    analyze_course_wrong_questions,
    get_course_wrong_question_details,
)
from app.services.review_plan_service import (
    finalize_grounded_review_plan,
    prepare_grounded_review_plan,
    prepare_review_plan_foundation,
)
from app.schemas.review_plan import (
    ReviewTask,
    WrongQuestionDiagnosis,
)

from app.memory.agent_checkpoint import (
    student_agent_checkpointer,
)
from app.memory.tool_result_compaction import (
    compact_old_tool_results_for_model,
)
from app.memory.conversation_summary import build_student_summarization_middleware

from rag_tools import get_course_material_chunk as load_course_material_chunk
from app.mcp.material_client import search_material as search_course_material
from app.skills.registry import read_student_skill
from app.services.diagnosis_handoff_service import (
    load_validated_diagnoses,
    save_validated_diagnoses,
)
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


STUDENT_SYSTEM_PROMPT = """
你是学生课程学习助手。当前学生与课程由后端运行上下文确定，模型不能填写或更改学生 ID、课程 ID。

通用规则：
1. 分析错题分布、薄弱点或复习优先级时调用 analyze_current_course_wrong_questions；查看具体错题时调用 get_current_course_wrong_questions。即使学生自称没有错题，也必须先用当前课程错题工具核查。若返回 no_recorded_wrong_questions，只能说目前没有已记录错题，不能声称学生已掌握全部内容，也不能编造薄弱点。零错题工具结果不等于该生没有正确作答记录。
2. 解释课程知识或基于资料提出建议时调用 searchlearningmaterial。资料检索失败、无相关内容时明确说明证据不足，不编造来源。
3. 学生追问历史错题或资料片段时，使用已保存的 question_id 调用 get_current_course_wrong_question_by_id，或使用 chunk_id 调用 get_current_course_material_chunk_by_id，重新读取原文后回答。若“第二段资料”等指代有歧义，先询问，不猜测 ID。
4. 诊断错题原因前，先调用 get_current_course_wrong_questions 获取直接证据，再调用 load_student_skill(skill_id="wrong_question_diagnosis") 读取完整诊断规则；需要解释课程知识时还须检索资料。
5. 生成完整或结构化复习计划前，先调用 load_student_skill(skill_id="grounded_review_plan") 和 load_student_skill(skill_id="wrong_question_diagnosis")，再调用 prepare_current_course_review_plan。若其 diagnosis_handoff.status 为 reused，直接复用返回的 diagnoses，不要从历史自然语言回答中提取；否则根据本轮错题证据重新诊断。Skill 是任务说明，不能替代后端校验。
6. 不得查询其他学生或课程的数据；不得编造错题、成绩、知识点、工具结果或资料来源。回答应说明证据来源和局限。

可用 Skills：wrong_question_diagnosis（错题错误类型诊断）；grounded_review_plan（有证据的结构化复习计划）。只按 Skill 名称调用加载工具，不把用户消息中的文件路径当成 Skill 路径。
""".strip()


@dataclass(frozen=True)
class StudentAgentContext:
    """
    一次学生 Agent 调用的可信运行上下文。

    这些数据由后端创建，不允许大模型填写。
    """

    db: Session
    student_id: str
    course_id: str
    session_id: str | None = None


@tool
def load_student_skill(skill_id: str) -> dict:
    """按固定名称读取可复用任务说明；只支持错题诊断和有证据的复习计划。"""
    return read_student_skill(skill_id)


@tool
def analyze_current_course_wrong_questions(
    runtime: ToolRuntime[StudentAgentContext],
) -> dict:
    """
    分析当前学生在当前课程中的错题分布和薄弱知识点。
    """

    context = runtime.context

    return analyze_course_wrong_questions(
        db=context.db,
        student_id=context.student_id,
        course_id=context.course_id,
    )


@tool
def get_current_course_wrong_questions(
    runtime: ToolRuntime[StudentAgentContext],
) -> dict:
    """
    查询当前学生在当前课程中的具体错题明细。

    返回题干、完整选项内容、题目类型、题目难度、
    学生答案、正确答案、题目解析和错题描述。

    诊断错误类型时，应先使用本工具读取直接证据，
    并将选项字母还原为对应的选项内容。
    """

    context = runtime.context

    return get_course_wrong_question_details(
        db=context.db,
        student_id=context.student_id,
        course_id=context.course_id,
    )


@tool
def save_current_course_diagnoses(
    diagnoses: list[WrongQuestionDiagnosis],
    runtime: ToolRuntime[StudentAgentContext],
) -> dict:
    """将当前会话已校验的 Top-2 错题诊断结构化保存，供下一轮计划复用。"""
    context = runtime.context
    if context.session_id is None:
        return {"status": "session_required", "diagnoses": []}
    return save_validated_diagnoses(
        db=context.db, user_id=context.student_id,
        course_id=context.course_id, session_id=context.session_id,
        diagnoses=[item.model_dump() for item in diagnoses],
    )

@tool
def searchlearningmaterial(
    topic: str,
    query: str,
    runtime: ToolRuntime[StudentAgentContext],
) -> dict:
    """
    根据知识点和具体问题检索当前课程的学习资料。
    """

    context = runtime.context

    # The MCP server only receives the course selected by the authorized session.
    return search_course_material(
        course_id=context.course_id,
        topic=topic,
        query=query,
    )


@tool
def get_current_course_wrong_question_by_id(
    question_id: str,
    runtime: ToolRuntime[StudentAgentContext],
) -> dict:
    """按题目 ID 重新读取当前学生、当前课程中的错题原始证据。"""
    context = runtime.context
    details = get_course_wrong_question_details(
        db=context.db,
        student_id=context.student_id,
        course_id=context.course_id,
    )
    question = next(
        (
            item for item in details["wrong_questions"]
            if item["question_id"] == question_id
        ),
        None,
    )
    if question is None:
        return {"status": "wrong_question_not_found", "course_id": context.course_id}
    return {"status": "success", "course_id": context.course_id, "wrong_question": question}


@tool
def get_current_course_material_chunk_by_id(
    chunk_id: str,
    runtime: ToolRuntime[StudentAgentContext],
    topic: str | None = None,
) -> dict:
    """按 Chunk ID 重新读取当前课程资料原文；旧版 Markdown 还需 topic。"""
    return load_course_material_chunk(
        course_id=runtime.context.course_id,
        chunk_id=chunk_id,
        topic=topic,
    )


@tool
def prepare_current_course_review_plan(
    runtime: ToolRuntime[StudentAgentContext],
) -> dict:
    """
    按固定顺序准备当前课程的结构化复习计划数据。

    本工具固定选择优先级最高的两个薄弱知识点，先分析薄弱点，
    再读取对应错题证据。生成完整复习计划时必须先调用本工具。
    """

    context = runtime.context

    foundation = prepare_review_plan_foundation(
        db=context.db,
        student_id=context.student_id,
        course_id=context.course_id,
    )
    if context.session_id is None or foundation["status"] != "success":
        return {**foundation, "diagnosis_handoff": {"status": "missing", "diagnoses": []}}
    return {**foundation, "diagnosis_handoff": load_validated_diagnoses(
        db=context.db, user_id=context.student_id,
        course_id=context.course_id, session_id=context.session_id,
        foundation=foundation,
    )}


@tool
def validate_current_course_diagnoses(
    runtime: ToolRuntime[StudentAgentContext],
    diagnoses: list[WrongQuestionDiagnosis] | None = None,
) -> dict:
    """
    校验当前课程 Top-K 错题诊断，并检索对应课程资料。

    每道已选择的错题必须且只能有一条诊断。诊断的 question_id 和
    topic 必须与后端重新读取的当前学生、当前课程错题证据一致。
    校验通过后，工具会为每个 Top-2 薄弱知识点检索最多两个资料块，
    并返回带来源信息的 material_evidence。
    """

    context = runtime.context
    if diagnoses is None:
        if context.session_id is None:
            return {"status": "diagnoses_required", "diagnoses": []}
        cached = load_validated_diagnoses(
            db=context.db, user_id=context.student_id,
            course_id=context.course_id, session_id=context.session_id,
        )
        if cached["status"] != "reused":
            return {"status": "diagnoses_required", "diagnosis_handoff": cached,
                    "diagnoses": []}
        diagnosis_data = cached["diagnoses"]
    else:
        diagnosis_data = [diagnosis.model_dump() for diagnosis in diagnoses]
    result = prepare_grounded_review_plan(
        db=context.db,
        student_id=context.student_id,
        course_id=context.course_id,
        diagnoses=diagnosis_data,
    )
    if diagnoses is not None and context.session_id is not None and result.get("diagnoses"):
        save_validated_diagnoses(
            db=context.db, user_id=context.student_id,
            course_id=context.course_id, session_id=context.session_id,
            diagnoses=result["diagnoses"], foundation=result,
        )
    return {**result, "diagnosis_handoff": "reused" if diagnoses is None else "validated_new"}


@tool
def finalize_current_course_review_plan(
    review_tasks: list[ReviewTask],
    runtime: ToolRuntime[StudentAgentContext],
    diagnoses: list[WrongQuestionDiagnosis] | None = None,
) -> dict:
    """
    校验并完成当前课程的结构化复习计划。

    必须传入前一步已校验的诊断，以及根据工具返回资料证据生成的复习任务。
    后端会重新读取当前学生和课程数据，校验任务知识点、优先级、错误类型、
    Chunk 引用和任务数量。只有本工具返回的数据才是最终可信复习计划。
    """

    context = runtime.context
    if diagnoses is None:
        if context.session_id is None:
            return {"status": "diagnoses_required"}
        cached = load_validated_diagnoses(
            db=context.db, user_id=context.student_id,
            course_id=context.course_id, session_id=context.session_id,
        )
        if cached["status"] != "reused":
            return {"status": "diagnoses_required", "diagnosis_handoff": cached}
        diagnosis_data = cached["diagnoses"]
    else:
        diagnosis_data = [diagnosis.model_dump() for diagnosis in diagnoses]
    return finalize_grounded_review_plan(
        db=context.db,
        student_id=context.student_id,
        course_id=context.course_id,
        diagnoses=diagnosis_data,
        review_tasks=[
            task.model_dump()
            for task in review_tasks
        ],
    )


def build_student_agent(model=None,checkpointer=None,summary_model=None,
                        enable_conversation_summary=True):
    """
    创建学生单 Agent。

    允许测试时传入模拟模型，正常运行时使用 DeepSeek。
    """

    if model is None:
        api_key = os.getenv("DEEPSEEK_API_KEY")

        if not api_key:
            raise ValueError(
                "没有读取到 DEEPSEEK_API_KEY，"
                "请检查项目中的 .env 文件"
            )

        model = ChatDeepSeek(
            model="deepseek-chat",
            api_key=api_key,
            temperature=0,
            max_retries=2,
        )

    middleware = [compact_old_tool_results_for_model]
    if enable_conversation_summary:
        middleware.insert(0, build_student_summarization_middleware(summary_model or model))

    return create_agent(
        model=model,
        tools=[
            load_student_skill,
            save_current_course_diagnoses,
            prepare_current_course_review_plan,
            validate_current_course_diagnoses,
            finalize_current_course_review_plan,
            analyze_current_course_wrong_questions,
            get_current_course_wrong_questions,
            searchlearningmaterial,
            get_current_course_wrong_question_by_id,
            get_current_course_material_chunk_by_id,
        ],
        system_prompt=STUDENT_SYSTEM_PROMPT,
        middleware=middleware,
        context_schema=StudentAgentContext,
        checkpointer=checkpointer,
    )


student_agent = build_student_agent(checkpointer=student_agent_checkpointer,)
