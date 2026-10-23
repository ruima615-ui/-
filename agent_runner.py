# agent_runner.py
# 确定本次可用工具 → 请求模型 → 执行工具 → 回传结果 → 保存对话
import json

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    ToolMessage,
)

from app.core.database import SessionLocal
from app.harness.runtime import AgentRuntimeHarness
from app.services.memory_service import (
    load_context,
    save_message,
)
from student_agent import (
    StudentAgentContext,
    student_agent,
)

def run_agent_with_memory(user_id, session_id, user_input, *, workflow="single",
                          capture_failure_diagnostics=False):
    """兼容入口；每次构造依赖以便生产和评测替换模型与数据库。"""
    harness = AgentRuntimeHarness(
        session_factory=SessionLocal, single_agent=student_agent,
        load_context=load_context, save_message=save_message,
        run_single=run_agent, run_multi=run_multi_agent_review,
    )
    return harness.run(
        user_id=user_id, session_id=session_id, user_input=user_input,
        workflow=workflow, capture_failure_diagnostics=capture_failure_diagnostics,
    )


def run_multi_agent_review(*, db, student_id, course_id, session_id=None, model=None,
                           capture_failure_diagnostics=False):
    """Opt-in LangGraph review route; existing single-Agent route remains intact."""
    from langchain_deepseek import ChatDeepSeek
    from app.workflows.student_multi_agent import run_student_multi_agent_review
    import os

    if model is None:
        key = os.getenv("DEEPSEEK_API_KEY")
        if not key:
            raise ValueError("没有读取到 DEEPSEEK_API_KEY")
        model = ChatDeepSeek(model="deepseek-chat", api_key=key,
                             temperature=0, max_retries=2)
    result = run_student_multi_agent_review(
        db=db, student_id=student_id, course_id=course_id,
        session_id=session_id,
        diagnosis_model=model, plan_model=model,
        capture_failure_diagnostics=capture_failure_diagnostics,
    )
    plan = result["review_plan"]
    if plan["status"] == "no_recorded_wrong_questions":
        answer = "当前课程没有已记录的错题，暂时无法依据错题制定复习计划。"
    elif plan["status"] in {"success", "partial"}:
        answer = ("已根据当前课程的错题诊断和课程资料生成复习计划。"
                  if plan["status"] == "success" else
                  "部分知识点有可用课程资料，已生成有依据的部分复习计划。")
    elif plan["status"] == "material_retrieval_failed":
        answer = "课程资料检索服务暂时不可用，无法生成有资料依据的复习计划。"
    elif plan["status"] == "course_materials_not_configured":
        answer = "当前课程或相关知识点尚无已索引资料，暂时无法生成有资料依据的复习计划。"
    elif plan["status"] == "course_materials_insufficient":
        answer = "当前检索没有找到足够相关的课程资料，暂时无法生成有资料依据的复习计划。"
    elif plan["status"] == "foundation_failed":
        answer = "当前错题数据暂时无法读取，请稍后重试。"
    elif plan["status"] == "diagnosis_failed":
        answer = "错题诊断暂时未通过校验，无法据此制定复习计划，请稍后重试。"
    elif plan["status"] == "plan_failed":
        answer = "复习计划生成或校验失败，请稍后重试。"
    elif plan["status"] == "insufficient_evidence":
        answer = "当前错题证据不足，暂时无法生成可靠的复习计划。"
    else:
        answer = "暂时无法生成复习计划，请稍后重试。"
    trace = result["tool_trace"]
    response = {"answer": answer, "review_plan": plan,
            "called_tools": [item["tool_name"] for item in trace],
            "tool_trace": trace, "steps": len(trace)}
    if capture_failure_diagnostics:
        response["failure_diagnostic"] = result.get("failure_diagnostic")
    return response
def run_agent(
    messages,
    db,
    student_id,
    course_id,
    session_id=None,
    max_steps=5,
    verbose=True,
):
    """
    使用 LangChain create_agent 执行学生单 Agent。
    """

    if max_steps < 1:
        raise ValueError("max_steps 必须大于 0")

    if course_id is None:
        raise ValueError(
            "学生 Agent 会话必须关联课程"
        )

    context = StudentAgentContext(
        db=db,
        student_id=student_id,
        course_id=course_id,
        session_id=session_id,
    )

    agent_config={
        "recursion_limit":(
            max_steps*3+2  # 每轮最多经过摘要检查、模型和工具三个图节点。
        ),
    }
    if session_id is not None:
        agent_config["configurable"]={
            "thread_id":session_id,
        }
    elif getattr(student_agent,"checkpointer",None,) is not None:
        raise ValueError(
        "启用 checkpoint 后必须提供 session_id"
    )
    result=student_agent.invoke(
        {
          "messages": messages,
        },
        config=agent_config,
        context=context,
    )
    result_messages = result.get(
        "messages",
        [],
    )

    # 摘要会删除旧消息并插入摘要，消息数量不再只增不减。
    # 本轮用户消息之后的 AI/Tool 消息才属于本次调用。
    current_user_index = next(
        (
            index
            for index in range(len(result_messages) - 1, -1, -1)
            if isinstance(result_messages[index], HumanMessage)
            and result_messages[index].additional_kwargs.get("lc_source") != "summarization"
        ),
        None,
    )
    if current_user_index is None:
        raise RuntimeError("LangChain Agent 结果缺少本轮用户消息")
    new_messages = result_messages[current_user_index + 1:]

    called_tools = []
    tool_calls_by_id = {}
    tool_trace = []
    review_plan = None

    for message in new_messages:
        if isinstance(message, AIMessage):
            for tool_call in message.tool_calls:
                tool_name = tool_call["name"]
                tool_call_id = tool_call.get("id")
                arguments = tool_call.get(
                    "args",
                    {},
                )

                called_tools.append(tool_name)

                if tool_call_id:
                    tool_calls_by_id[
                        tool_call_id
                    ] = {
                        "tool_name": tool_name,
                        "arguments": arguments,
                    }

        elif isinstance(message, ToolMessage):
            call_info = tool_calls_by_id.get(
                message.tool_call_id,
                {},
            )

            tool_name = (
                message.name
                or call_info.get("tool_name")
                or "unknown_tool"
            )
            arguments = call_info.get(
                "arguments",
                {},
            )

            content_text = message.text

            try:
                parsed_result = json.loads(
                    content_text
                )
            except (
                json.JSONDecodeError,
                TypeError,
            ):
                parsed_result = content_text

            if isinstance(parsed_result, str):
                result_preview = (
                    parsed_result[:500]
                )
            else:
                result_preview = json.dumps(
                    parsed_result,
                    ensure_ascii=False,
                    default=str,
                )[:500]

            execution_status = (
                message.status or "success"
            )

            tool_trace.append({
                "tool_name": tool_name,
                "arguments": arguments,
                "status": execution_status,
                "duration_ms": None,
                "error": (
                    result_preview
                    if execution_status == "error"
                    else None
                ),
                "result_preview": result_preview,
            })

            if (
                tool_name
                == "finalize_current_course_review_plan"
                and execution_status == "success"
                and isinstance(parsed_result, dict)
            ):
                review_plan = parsed_result

    final_message = next(
        (
            message
            for message in reversed(
                new_messages
            )
            if (
                isinstance(message, AIMessage)
                and not message.tool_calls
            )
        ),
        None,
    )

    if final_message is None:
        raise RuntimeError(
            "LangChain Agent 未生成最终回答"
        )

    answer = (
        final_message.text
        or "模型未生成可用回答。"
    )

    steps = sum(
        1
        for message in new_messages
        if isinstance(message, AIMessage)
    )

    if verbose:
        print(
            "LangChain Agent 调用工具：",
            called_tools,
        )
        print(
            "LangChain Agent 模型轮数：",
            steps,
        )

    return {
        "answer": answer,
        "called_tools": called_tools,
        "tool_trace": tool_trace,
        "steps": steps,
        "review_plan": review_plan,
    }
