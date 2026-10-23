#教师组卷并发布，学生答题和查询成绩，管理员管理教师权限。
# frontend/streamlit_app.py
import json
import os
from pathlib import Path
import requests
import streamlit as st
from dotenv import load_dotenv
from auth_ui import show_auth_page
from question_import import parse_questions_csv
from ui_theme import apply_platform_theme, page_intro, sidebar_brand

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
DEFAULT_API_URL = "http://127.0.0.1:8000"

st.set_page_config(page_title="CoursePilot · 教学智能工作台", page_icon=":material/school:", layout="wide")


def initialize_api_url():
    """首次加载时将旧的默认端口切换到本机配置，之后尊重用户手动修改。"""
    if st.session_state.get("_api_url_initialized"):
        return
    preferred = os.getenv("COURSEPILOT_API_URL", DEFAULT_API_URL).rstrip("/")
    current = st.session_state.get("api_url")
    if current is None or current.rstrip("/") == DEFAULT_API_URL:
        st.session_state["api_url"] = preferred
    st.session_state["_api_url_initialized"] = True
def initialize_session_state():
    """集中初始化当前浏览器标签页使用的状态。"""

    st.session_state.setdefault(
        "agent_session_id",
        None,
    )
    st.session_state.setdefault(
        "agent_course_id",
        None,
    )
    st.session_state.setdefault(
        "agent_session_title",
        None,
    )
    st.session_state.setdefault(
        "agent_messages",
        [],
    )
    st.session_state.setdefault(
        "agent_history_loaded_for",
        None,
    )
    st.session_state.setdefault(
        "student_page",
        "课程中心",
    )
    st.session_state.setdefault(
        "pending_student_page",
        None,
    )
    st.session_state.setdefault(
        "attempt_id",
        None,
    )
    st.session_state.setdefault(
        "paper",
        None,
    )
    st.session_state.setdefault(
        "exam_result",
        None,
    )


def call_api(method, path, data=None,timeout=30,):
    """向 FastAPI 发请求，返回 JSON；失败时在页面显示原因。"""
    base_url = st.session_state.api_url.rstrip("/")
    token = st.session_state.token.strip()

    try:
        response = requests.request(
            method=method,
            url=f"{base_url}{path}",
            headers={"Authorization": f"Bearer {token}"},
            json=data,
            timeout=timeout,
        )
    except requests.RequestException as error:
        st.error(f"无法连接后端：{error}")
        return None

    try:
        result = response.json()
    except ValueError:
        st.error(f"后端返回了非 JSON 内容：HTTP {response.status_code}")
        return None

    if not response.ok:
        detail = result.get("detail", result)
        st.error(
            f"请求失败（HTTP {response.status_code}）：{detail}。"
            f"请求地址：{base_url}{path}"
        )
        return None

    return result


def upload_material_api(course_id, uploaded, title):
    """课程资料接口使用 multipart/form-data，不能复用 JSON 请求助手。"""
    if uploaded.size > 20 * 1024 * 1024:
        st.error("课程资料不能超过 20 MB")
        return None
    try:
        response = requests.post(
            f"{st.session_state.api_url.rstrip('/')}/api/teacher/course-materials/courses/{course_id}",
            headers={"Authorization": f"Bearer {st.session_state.token.strip()}"},
            files={"file": (uploaded.name, uploaded.getvalue(), uploaded.type or "application/octet-stream")},
            data={"title": title.strip()},
            timeout=120,
        )
    except requests.RequestException as error:
        st.error(f"上传失败：{error}")
        return None
    try:
        payload = response.json()
    except ValueError:
        st.error(f"上传接口返回了非 JSON 内容：HTTP {response.status_code}")
        return None
    if not response.ok:
        st.error(f"上传失败（HTTP {response.status_code}）：{payload.get('detail', payload)}")
        return None
    return payload


def clear_active_agent_session():
    """清除当前标签页选中的 Agent 会话。"""

    st.session_state.agent_session_id = None
    st.session_state.agent_course_id = None
    st.session_state.agent_session_title = None
    st.session_state.agent_messages = []
    st.session_state.agent_history_loaded_for = None


def activate_agent_session(session):
    """加载一段会话及其历史消息，并设为当前会话。"""

    session_id = session["session_id"]
    history = call_api(
        "GET",
        f"/api/sessions/{session_id}/messages?limit=100",
    )

    if history is None:
        return False

    st.session_state.agent_session_id = session_id
    st.session_state.agent_course_id = session.get(
        "course_id"
    )
    st.session_state.agent_session_title = session.get(
        "title"
    )
    st.session_state.agent_messages = [
        {
            "role": message["role"],
            "content": message["content"],
            "called_tools": message.get(
                "called_tools",
                [],
            ),
            "steps": message.get("steps"),
            "review_plan": message.get(
                "review_plan"
            ),
        }
        for message in history.get("messages", [])
        if message.get("role") in {
            "user",
            "assistant",
        }
    ]
    st.session_state.agent_history_loaded_for = (
        session_id
    )

    return True


def format_agent_session(session):
    """生成历史会话选择框中的显示文字。"""

    title = session.get("title") or "学习对话"
    course_id = session.get("course_id") or "未关联课程"
    return f"{title} · {course_id}"


def render_review_plan(review_plan):
    """使用原生 Streamlit 组件展示后端校验通过的结构化复习计划。"""

    if not review_plan:
        return

    status = review_plan.get("status")
    status_labels = {
        "success": "计划已生成",
        "partial": "部分计划已生成",
        "no_recorded_wrong_questions": "暂无错题记录",
        "course_materials_not_configured": "课程资料不足",
        "insufficient_evidence": "诊断证据不足",
    }

    st.subheader("结构化复习计划")
    with st.container(border=True):
        st.caption(
            f"状态：{status_labels.get(status, status)} · "
            f"课程：{review_plan['scope']['course_id']}"
        )

        limitations = review_plan.get(
            "limitations",
            [],
        )
        for limitation in limitations:
            st.warning(limitation)

        evidence_by_chunk = {
            item["chunk_id"]: item
            for item in review_plan.get(
                "material_evidence",
                [],
            )
        }

        tasks = review_plan.get("review_tasks", [])
        if not tasks:
            st.info("当前没有能够通过资料证据校验的复习任务。")
            return

        for task in tasks:
            with st.container(border=True):
                st.markdown(
                    f"### {task['priority_rank']}. "
                    f"{task['topic']}"
                )
                st.write(task["objective"])
                st.caption(
                    "错误类型："
                    + "、".join(
                        task["related_error_types"]
                    )
                )

                st.markdown("**执行步骤**")
                for index, step in enumerate(
                    task["action_steps"],
                    start=1,
                ):
                    st.write(f"{index}. {step}")

                st.markdown("**完成后自测**")
                for question in task[
                    "self_check_questions"
                ]:
                    st.write(f"- {question}")

                sources = [
                    evidence_by_chunk[chunk_id]
                    for chunk_id in task[
                        "material_chunk_ids"
                    ]
                    if chunk_id in evidence_by_chunk
                ]
                with st.expander(
                    f"查看资料依据（{len(sources)}）"
                ):
                    for source in sources:
                        st.markdown(
                            f"**{source['source_title']}**"
                        )
                        st.caption(
                            f"{source['source_type']} · "
                            f"{source['original_filename']} · "
                            f"{source.get('section') or '未标注章节'}"
                        )
                        st.write(source["content_excerpt"])


def show_admin_page():
    page_intro("平台管理", "审核教师账号并分配课程权限，为后续教学与测评建立清晰的管理边界。", "管理端 / 总览")

    st.subheader("教师注册审核")
    pending_teachers = call_api("GET", "/api/teachers/pending")

    if pending_teachers == []:
        st.info("当前没有待审核的教师账号")
    elif pending_teachers is not None:
        for teacher in pending_teachers:
            with st.container(
                border=True,
                horizontal=True,
                vertical_alignment="center",
            ):
                st.write(
                    f"{teacher['name']}（{teacher['user_id']}）"
                )
                if st.button(
                    "批准",
                    key=f"approve_teacher_{teacher['user_id']}",
                    icon=":material/check:",
                ):
                    result = call_api(
                        "POST",
                        f"/api/teachers/{teacher['user_id']}/approve",
                    )
                    if result is not None:
                        st.success("教师账号已批准")
                        st.rerun()

    st.subheader("分配教师课程")
    with st.form("assign_teacher_course"):
        teacher_id = st.text_input("教师 ID", key="assign_teacher_id")
        teacher_course_id = st.text_input(
            "课程 ID",
            key="assign_teacher_course_id",
        )
        assign_clicked = st.form_submit_button("分配课程")

    if assign_clicked:
        if not teacher_id.strip() or not teacher_course_id.strip():
            st.error("请填写教师 ID 和课程 ID")
        else:
            result = call_api(
                "POST",
                (
                    f"/api/teachers/{teacher_id.strip()}"
                    f"/courses/{teacher_course_id.strip()}"
                ),
            )
            if result is not None:
                st.success("课程分配成功")
                st.json(result)

def show_exam_management(courses):
    """教师为已授权课程组卷并发布考试。"""

    st.subheader("课程题库与组卷")

    course_options = {
        f"{course['code']} · {course['name']}": course["course_id"]
        for course in courses
    }

    selected_course = st.selectbox("课程", options=list(course_options), key="teacher_exam_course")
    course_id = course_options[selected_course]

    st.markdown("#### 1. 批量导入题目")
    st.caption("上传 UTF-8 CSV；选择题 options 和所有题型的 answer_key 使用 JSON 格式。填空题自动判分，简答题由教师批改。任一题错误则整批不入库。")
    template = (
        'question_type,topic,stem,options,answer_key,explanation,max_score,knowledge_count_level,reasoning_level,transfer_level,distractor_level\n'
        'single_choice,Python列表,列表首个元素的下标是什么？,"{""A"":""0"",""B"":""1""}","""A""",下标从零开始,1,0,0,0,0\n'
        'true_false,Python列表,列表可以通过下标读取元素吗？,,true,可以通过下标读取,1,0,0,0,0\n'
        'fill_blank,Python列表,列表首个元素的下标是几？,,"""0""",从零开始,1,0,0,0,0\n'
        'short_answer,Python列表,解释列表索引从零开始的含义。,,"""首个元素的索引为0""",依据要点人工给分,3,0,1,0,0\n'
    )
    st.download_button("下载 CSV 模板", template.encode("utf-8-sig"), "questions_template.csv", "text/csv")
    uploaded = st.file_uploader("上传题目 CSV", type="csv", key=f"questions_csv_{course_id}")
    if uploaded is not None:
        try:
            import_items = parse_questions_csv(uploaded.getvalue(), course_id)
        except ValueError as error:
            st.error(str(error))
        else:
            st.write(f"待导入 {len(import_items)} 道题")
            st.dataframe([
                {"题型": item["question_type"], "知识点": item["topic"], "题干": item["stem"]}
                for item in import_items
            ], width="stretch", hide_index=True)
            if st.button("确认导入题库", key=f"import_questions_{course_id}"):
                result = call_api("POST", f"/api/teacher/courses/{course_id}/questions/batch", {"items": import_items})
                if result is not None:
                    st.success(f"已导入 {result['count']} 道题")
                    st.rerun()

    st.markdown("#### 2. 从题库组卷")
    questions = call_api("GET", f"/api/teacher/courses/{course_id}/questions")
    if questions is None:
        return
    if not questions:
        st.info("本课程题库为空，请先批量导入题目。")
        return
    topics = sorted({question["topic"] for question in questions})
    topic_filter = st.multiselect("按知识点筛选", topics, key=f"topic_filter_{course_id}")
    visible = [question for question in questions if not topic_filter or question["topic"] in topic_filter]
    question_map = {question["question_id"]: question for question in questions}
    selected_key = f"selected_questions_{course_id}"
    available_ids = list(dict.fromkeys(
        [question["question_id"] for question in visible]
        + [question_id for question_id in st.session_state.get(selected_key, []) if question_id in question_map]
    ))
    selected_ids = st.multiselect(
        "勾选题目（可多选）",
        available_ids,
        format_func=lambda question_id: f"{question_map[question_id]['topic']} · {question_map[question_id]['stem'][:70]} · {question_id}",
        key=selected_key,
    )
    st.caption("下表可调整试卷内的题目顺序和每题分值。")
    rows = [
        {"题目 ID": question_id, "知识点": question_map[question_id]["topic"],
         "题干": question_map[question_id]["stem"], "顺序": index, "分值": float(question_map[question_id]["max_score"])}
        for index, question_id in enumerate(selected_ids, start=1)
    ]
    edited = st.data_editor(
        rows, key=f"exam_items_{course_id}", width="stretch", hide_index=True,
        disabled=["题目 ID", "知识点", "题干"], num_rows="fixed",
    ) if rows else []

    with st.form("create_exam"):
        title = st.text_input("试卷名称")
        duration = st.number_input(
            "考试时长（分钟）",
            min_value=1,
            value=30,
            step=1,
        )
        create_clicked = st.form_submit_button("创建试卷草稿")

    if create_clicked:
        if not title.strip():
            st.error("请填写试卷名称")
        elif not edited:
            st.error("请先从题库勾选题目")
        else:
            try:
                if any(type(row["顺序"]) is not int for row in edited):
                    raise ValueError("顺序必须为整数")
                positions = [int(row["顺序"]) for row in edited]
                if sorted(positions) != list(range(1, len(edited) + 1)) or any(
                    float(row["分值"]) <= 0 for row in edited
                ):
                    raise ValueError("顺序须为从 1 开始且不重复的连续整数；分值须大于 0")
                ordered = sorted(edited, key=lambda row: int(row["顺序"]))
                body = {"course_id": course_id, "title": title.strip(),
                        "duration_minutes": int(duration),
                        "items": [{"question_id": row["题目 ID"], "points": float(row["分值"])} for row in ordered]}
            except (ValueError, TypeError) as error:
                st.error(f"请检查顺序和分值：{error}")
            else:
                result = call_api("POST", "/api/exams/drafts", body)
                if result is not None:
                    st.session_state.teacher_preview_exam_id = result["exam_id"]
                    st.success("草稿创建成功，请在下方核对预览后发布")

    st.divider()
    st.subheader("试卷管理与发布")
    exams = call_api("GET", f"/api/exams/teacher?course_id={course_id}")
    if exams is None:
        return
    if not exams:
        st.info("当前课程没有你创建的试卷草稿")
        return
    exam_ids = [item["exam_id"] for item in exams]
    preview_key = f"teacher_preview_{course_id}"
    new_id = st.session_state.pop("teacher_preview_exam_id", None)
    if new_id in exam_ids:
        st.session_state[preview_key] = new_id
    selected_exam_id = st.selectbox(
        "查看试卷", exam_ids,
        format_func=lambda exam_id: next(
            f"{item['title']} · {item['status']} · {exam_id}"
            for item in exams if item["exam_id"] == exam_id
        ),
        key=preview_key,
    )
    exam_detail = call_api("GET", f"/api/exams/teacher/{selected_exam_id}")
    if exam_detail is None:
        return
    st.caption(f"{exam_detail['status']} · {exam_detail['duration_minutes']} 分钟 · 总分 {exam_detail['total_points']}")
    for item in exam_detail["questions"]:
        with st.expander(f"第 {item['position']} 题 · {item['stem']} · {item['points']} 分"):
            st.write("题型：", item["question_type"])
            st.write("知识点：", item["topic"])
            st.write("选项：", item["options"] or "无")
            st.write("标准/参考答案：", item["answer_key"])
            st.write("解析：", item["explanation"] or "无")
    if st.button("发布这张试卷", disabled=exam_detail["status"] != "draft"):
        result = call_api("POST", f"/api/exams/{selected_exam_id}/publish")
        if result is not None:
            st.success("试卷已发布")
            st.rerun()


def show_teacher_materials(courses):
    """教师上传课程资料，并查看解析与两套索引的状态。"""
    st.subheader("课程资料")
    options = {f"{course['code']} · {course['name']}": course["course_id"] for course in courses}
    selected = st.selectbox("资料所属课程", list(options), key="teacher_material_course")
    course_id = options[selected]
    st.caption("支持 md、txt、pdf、docx、pptx，最大 20 MB。系统读取资料内容生成片段知识点建议，上传后请逐段核对。")
    with st.container(border=True):
        st.markdown("#### 上传课程资料")
        with st.form(f"teacher_material_upload_{course_id}"):
            uploaded = st.file_uploader("选择课程资料", type=["md", "txt", "pdf", "docx", "pptx"], max_upload_size=20)
            title = st.text_input("资料标题")
            submitted = st.form_submit_button("上传并解析资料", type="primary")
    if submitted:
        if uploaded is None or not title.strip():
            st.error("请选择文件并填写资料标题")
        else:
            result = upload_material_api(course_id, uploaded, title)
            if result is not None:
                st.success(f"资料已接收：{result['material_id']}。请在下方逐段核对知识点。")
    st.subheader("资料与索引状态")
    if st.button("刷新状态", key=f"refresh_materials_{course_id}", icon=":material/refresh:"):
        st.rerun()
    materials = call_api("GET", f"/api/teacher/course-materials/courses/{course_id}/index-status")
    if materials is None:
        return
    if not materials:
        st.info("当前课程尚未上传资料")
        return
    indexed_count = sum(1 for material in materials if material["indexes"] and
                        all(item.get("status") in ("indexed", "already_indexed")
                            for item in material["indexes"].values()))
    count_a, count_b = st.columns(2)
    count_a.metric("课程资料", len(materials))
    count_b.metric("索引就绪", indexed_count)
    rows = []
    for material in materials:
        indexes = material["indexes"] or {"—": {"status": "等待索引", "chunk_count": 0}}
        for backend, index in indexes.items():
            rows.append({"资料": material["title"], "来源": material["source_type"],
                         "文件": material["filename"],
                         "解析": material["parse_status"], "向量后端": backend,
                         "索引": index["status"], "片段数": index["chunk_count"],
                         "错误": material["parse_error"] or index.get("index_error") or ""})
    st.dataframe(rows, width="stretch", hide_index=True)
    own_materials = [item for item in materials
                     if item["source_type"] == "teacher"
                     and item.get("uploaded_by") == st.session_state.get("user_id")
                     and item["parse_status"] == "ready_for_indexing"]
    if own_materials:
        with st.expander("核对片段知识点", icon=":material/rule:"):
            material_map = {f"{item['title']} · {item['material_id']}": item["material_id"]
                            for item in own_materials}
            chosen = st.selectbox("选择自己上传的资料", list(material_map), key=f"chunk_material_{course_id}")
            material_id = material_map[chosen]
            page = st.number_input("片段页码（每页 50 段）", min_value=1, value=1,
                                   key=f"chunk_page_{course_id}_{material_id}")
            result = call_api("GET", f"/api/teacher/course-materials/{material_id}/chunk-topics?offset={(page - 1) * 50}&limit=50")
            if result and result["chunks"]:
                reviewed_on_page = sum(1 for item in result["chunks"] if item["reviewed"])
                st.caption(f"本页已核对 {reviewed_on_page} / {len(result['chunks'])} 段 · 全文共 {result['total']} 段")
                chunks = {item["chunk_index"]: item for item in result["chunks"]}
                position = st.selectbox("选择资料片段", list(chunks),
                                        format_func=lambda index: f"第 {index + 1} 段 · {chunks[index]['section']}",
                                        key=f"chunk_position_{material_id}_{page}")
                chunk = chunks[position]
                st.badge("已核对" if chunk["reviewed"] else "待核对",
                         color="green" if chunk["reviewed"] else "orange")
                st.text_area("片段原文", chunk["content"], disabled=True,
                             key=f"chunk_content_{material_id}_{position}")
                with st.form(f"chunk_topics_{material_id}_{position}"):
                    selected_topics = st.multiselect(
                        "片段知识点", result["available_topics"], default=chunk["topics"],
                        accept_new_options=True,
                        help="核对正文后选择建议标签，也可以直接输入新标签。每段最多 4 个知识点。")
                    saved = st.form_submit_button("保存标签并重建索引")
                if saved:
                    if not selected_topics or len(selected_topics) > 4:
                        st.error("请选择 1～4 个知识点")
                    elif call_api("PUT", f"/api/teacher/course-materials/{material_id}/chunk-topics/{position}",
                                  {"topics": selected_topics}) is not None:
                        st.success("片段标签已保存，正在重建索引；完成前暂不可检索这份资料。")
                        st.rerun()
            elif result:
                st.info("这一页没有片段")


def show_teacher_page(section="总览"):
    """教师登录后查看自己有权管理的课程。"""
    descriptions = {
        "总览": "查看负责课程，并从这里进入资料、题库和批改工作。",
        "课程资料": "上传讲义、核对片段知识点，并查看主备向量索引状态。",
        "题库与考试": "批量导入题目，按课程组卷，预览并发布考试。",
        "主观题批改": "核对学生简答题作答并提交最终得分。",
    }
    page_intro(section if section != "总览" else "教师工作台",
               descriptions.get(section, descriptions["总览"]), "教师端 / 课程管理")

    courses = call_api("GET", "/api/teachers/me/courses")
    if courses is None:
        return
    if not courses:
        st.info("管理员尚未给你分配课程")
        return

    if section == "课程资料":
        show_teacher_materials(courses)
        return
    if section == "题库与考试":
        show_exam_management(courses)
        return
    if section == "主观题批改":
        show_teacher_reviews(courses)
        return

    total = len(courses)
    st.metric("我负责的课程", total)
    st.subheader("我的课程")
    for course in courses:
        with st.container(border=True):
            st.markdown(f"#### {course['name']}")
            st.caption(f"课程代码 {course['code']} · 课程 ID {course['course_id']}")
    st.subheader("常用工作")
    columns = st.columns(3, gap="medium")
    for column, (target, detail, icon) in zip(columns, [
        ("课程资料", "上传与核对资料标签", ":material/menu_book:"),
        ("题库与考试", "导入题目并发布试卷", ":material/assignment:"),
        ("主观题批改", "处理待批改作答", ":material/rate_review:"),
    ]):
        with column, st.container(border=True):
            st.markdown(f"#### {icon} {target}")
            st.caption(detail)
            if st.button("进入", key=f"teacher_go_{target}", width="stretch"):
                st.session_state.teacher_page = target
                st.rerun()


def show_teacher_reviews(courses):
    """教师按课程批改已提交的简答题。"""
    st.subheader("简答题待批改")
    course_options = {f"{course['code']} · {course['name']}": course["course_id"] for course in courses}
    selected_course = st.selectbox("批改课程", list(course_options), key="review_course")
    course_id = course_options[selected_course]
    pending = call_api("GET", f"/api/exams/review/pending?course_id={course_id}")
    if pending is None:
        return
    if not pending:
        st.info("当前课程没有待批改试卷")
        return
    labels = {f"记录 {item['attempt_id']} · 学生 {item['student_id']}": item["attempt_id"] for item in pending}
    chosen = st.selectbox("选择考试记录", list(labels), key=f"review_attempt_{course_id}")
    detail = call_api("GET", f"/api/exams/review/{labels[chosen]}")
    if detail is None:
        return
    st.caption(f"{detail['exam_title']} · 学生 {detail['student_id']}")
    with st.form(f"grade_short_answers_{detail['attempt_id']}"):
        grades = []
        for question in detail["questions"]:
            st.markdown(f"**第 {question['position']} 题：{question['stem']}**")
            st.write("学生作答：", question["answer"])
            st.write("参考答案：", question["reference_answer"])
            st.write("解析：", question["explanation"] or "无")
            score = st.number_input(
                f"本题得分（满分 {question['points']}）", min_value=0.0,
                max_value=float(question["points"]), value=0.0, step=0.5,
                key=f"grade_{detail['attempt_id']}_{question['question_id']}",
            )
            grades.append({"question_id": question["question_id"], "score": score})
        submitted = st.form_submit_button("确认批改并生成最终成绩")
    if submitted:
        result = call_api("POST", f"/api/exams/review/{detail['attempt_id']}/grades", {"grades": grades})
        if result is not None:
            st.success(f"批改完成，最终得分 {result['total_score']}")
            st.rerun()

def enter_course_agent(course):
    """进入课程 Agent；优先恢复该课程的活动会话。"""

    course_id = course["course_id"]
    active_session_id = st.session_state.get(
        "agent_session_id"
    )
    active_course_id = st.session_state.get(
        "agent_course_id"
    )

    # 当前已经选中同一课程会话，确保历史消息已加载。
    if (
        active_session_id is not None
        and active_course_id == course_id
    ):
        if (
            st.session_state.get(
                "agent_history_loaded_for"
            )
            != active_session_id
        ):
            sessions = call_api(
                "GET",
                "/api/sessions",
            )
            if sessions is None:
                return

            active_session = next(
                (
                    session
                    for session in sessions
                    if (
                        session["session_id"]
                        == active_session_id
                    )
                ),
                None,
            )
            if (
                active_session is None
                or not activate_agent_session(
                    active_session
                )
            ):
                return

    else:
        sessions = call_api(
            "GET",
            "/api/sessions",
        )
        if sessions is None:
            return

        matching_session = next(
            (
                session
                for session in sessions
                if (
                    session.get("status") == "active"
                    and session.get("course_id")
                    == course_id
                )
            ),
            None,
        )

        # 该课程已有活动会话，恢复历史后继续。
        if matching_session is not None:
            if not activate_agent_session(
                matching_session
            ):
                return

        # 该课程没有活动会话，再向后端创建。
        else:
            result = call_api(
                "POST",
                "/api/sessions",
                {
                    "course_id": course_id,
                    "title": f"{course['name']}学习对话",
                },
            )

            if result is None:
                return

            st.session_state.agent_session_id = (
                result["session_id"]
            )
            st.session_state.agent_course_id = (
                result["course_id"]
            )
            st.session_state.agent_session_title = (
                result.get("title")
            )
            st.session_state.agent_messages = []
            st.session_state.agent_history_loaded_for = (
                result["session_id"]
            )

    # 下一次重新运行时切换到 Agent 页面。
    st.session_state.pending_student_page = (
        "AI 学习助手"
    )
    st.rerun()

def show_course_center():
    """显示可选课程、我的课程，并允许当前学生选课。"""

    page_intro("课程中心", "选择课程、查看学习范围，并从已选课程进入 AI 学习助手。", "学生端 / 我的学习")

    available_courses = call_api(
        "GET",
        "/api/courses",
    )
    my_courses = call_api(
        "GET",
        "/api/courses/mine",
    )

    if available_courses is None or my_courses is None:
        return

    enrolled_course_ids = {
        course["course_id"]
        for course in my_courses
    }

    metric_a, metric_b = st.columns(2)
    metric_a.metric("已选课程", len(my_courses))
    metric_b.metric("可选课程", len(available_courses))
    st.subheader("我的课程")

    if not my_courses:
        st.info("你还没有选择课程。")
    else:
        course_columns = st.columns(2, gap="medium")
        for index, course in enumerate(my_courses):
            with course_columns[index % 2], st.container(border=True):
                st.markdown(
                    f"### {course['name']}"
                )
                st.caption(
                    f"课程代码：{course['code']} · "
                    f"课程 ID：{course['course_id']}"
                )
                st.write(
                    course.get("description")
                    or "暂无课程介绍"
                )
                course_id = course["course_id"]

                active_session_id = st.session_state.get(
                    "agent_session_id"
                )
                active_course_id = st.session_state.get(
                    "agent_course_id"
                )

                if active_session_id is None:
                    button_label = "进入 AI 学习助手"
                elif active_course_id == course_id:
                    button_label = "继续 AI 学习助手"
                else:
                    button_label = "切换至此课程的 AI 助手"

                if st.button(
                    button_label,
                    key=f"open_agent_{course_id}",
                    type="primary",
                ):
                    enter_course_agent(course)

    st.subheader("可选课程")

    if not available_courses:
        st.info("当前没有可选课程。")
        return

    available_columns = st.columns(2, gap="medium")
    for index, course in enumerate(available_courses):
        course_id = course["course_id"]
        already_enrolled = (
            course_id in enrolled_course_ids
        )

        with available_columns[index % 2], st.container(border=True):
            st.markdown(
                f"### {course['name']}"
            )
            st.caption(
                f"课程代码：{course['code']} · "
                f"课程 ID：{course_id}"
            )
            st.write(
                course.get("description")
                or "暂无课程介绍"
            )

            if already_enrolled:
                st.button(
                    "已选择",
                    key=f"enrolled_{course_id}",
                    disabled=True,
                )
            elif st.button(
                "选择课程",
                key=f"enroll_{course_id}",
                type="primary",
            ):
                result = call_api(
                    "POST",
                    f"/api/courses/{course_id}/enroll",
                )

                if result is not None:
                    st.success(
                        f"已成功选择课程：{course['name']}"
                    )
                    st.rerun()

def show_student_agent_page():
    """学生 AI 学习助手页面。"""

    page_intro("AI 学习助手", "围绕当前课程的错题与资料提问，查看有证据来源的诊断和复习建议。", "学生端 / 学习对话")

    sessions = call_api(
        "GET",
        "/api/sessions",
    )
    if sessions is None:
        return

    active_sessions = [
        session
        for session in sessions
        if (
            session.get("status") == "active"
            and session.get("course_id") is not None
        )
    ]
    session_by_id = {
        session["session_id"]: session
        for session in active_sessions
    }

    session_id = st.session_state.get(
        "agent_session_id"
    )

    # 当前浏览器保存的会话可能已在其他页面被关闭。
    if (
        session_id is not None
        and session_id not in session_by_id
    ):
        clear_active_agent_session()
        session_id = None

    with st.expander("历史学习会话", icon=":material/history:"):
        st.subheader("历史学习会话")

        if active_sessions:
            session_ids = [
                session["session_id"]
                for session in active_sessions
            ]
            selected_index = (
                session_ids.index(session_id)
                if session_id in session_ids
                else 0
            )
            selected_session_id = st.selectbox(
                "选择要继续的会话",
                session_ids,
                index=selected_index,
                format_func=lambda value: (
                    format_agent_session(
                        session_by_id[value]
                    )
                ),
                key="agent_history_session_selector",
            )

            if st.button(
                "加载所选会话",
                key="load_agent_history",
                type=(
                    "primary"
                    if selected_session_id != session_id
                    else "secondary"
                ),
            ):
                if activate_agent_session(
                    session_by_id[selected_session_id]
                ):
                    st.rerun()

        else:
            st.info("当前没有可以继续的历史会话。")

        closed_count = sum(
            1
            for session in sessions
            if session.get("status") == "closed"
        )
        if closed_count:
            st.caption(
                f"已结束的会话：{closed_count} 个"
            )

    # 尚未从课程中心进入，也没有选择历史会话。
    if session_id is None:
        st.info(
            "请从“课程中心”的“我的课程”进入 AI 学习助手，"
            "或在上方选择一段历史会话。"
        )

        if st.button(
            "返回课程中心",
            key="return_to_course_center_from_agent",
        ):
            st.session_state.pending_student_page = (
                "课程中心"
            )
            st.rerun()

        return

    if (
        st.session_state.get(
            "agent_history_loaded_for"
        )
        != session_id
    ):
        if not activate_agent_session(
            session_by_id[session_id]
        ):
            return

    title = (
        st.session_state.get("agent_session_title")
        or "学习对话"
    )
    course_id = st.session_state.get(
        "agent_course_id"
    )

    st.subheader(title)
    st.caption(
        f"课程：{course_id} · 会话：{session_id}"
    )

    if st.button(
        "结束当前对话",
        key="close_agent_session",
    ):
        result = call_api(
            "PATCH",
            f"/api/sessions/{session_id}/close",
        )

        if result is not None:
            clear_active_agent_session()

            st.rerun()

    # 显示当前聊天历史。
    for message in st.session_state.agent_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

            render_review_plan(
                message.get("review_plan")
            )

            called_tools = message.get(
                "called_tools",
                [],
            )
            steps = message.get("steps")

            if called_tools:
                st.caption(
                    "调用工具："
                    + " → ".join(called_tools)
                )

            if steps is not None:
                st.caption(
                    f"Agent 决策轮数：{steps}"
                )

    prompt = st.chat_input(
        "询问错题、薄弱知识点或复习建议",
        key=f"agent_chat_input_{session_id}",
        submit_mode="disable",
    )

    if not prompt:
        return

    user_message = {
        "role": "user",
        "content": prompt,
    }

    st.session_state.agent_messages.append(
        user_message
    )

    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("学习助手正在分析..."):
            result = call_api(
                "POST",
                "/api/chat",
                {
                    "session_id": session_id,
                    "message": prompt,
                },
                timeout=120,
            )

        if result is None:
            # 后端失败时撤销本地消息，避免前后端历史不一致。
            st.session_state.agent_messages.pop()
            return

        answer = result["answer"]
        called_tools = result.get(
            "called_tools",
            [],
        )
        steps = result.get("steps")
        review_plan = result.get("review_plan")

        st.markdown(answer)
        render_review_plan(review_plan)

        if called_tools:
            st.caption(
                "调用工具："
                + " → ".join(called_tools)
            )

        if steps is not None:
            st.caption(
                f"Agent 决策轮数：{steps}"
            )

    st.session_state.agent_messages.append({
        "role": "assistant",
        "content": answer,
        "called_tools": called_tools,
        "steps": steps,
        "review_plan": review_plan,
    })
    st.session_state.agent_history_loaded_for = (
        session_id
    )


def format_exam_option(value, options):
    """把选项值转换成适合学生阅读的文字。"""

    if isinstance(options, dict):
        return f"{value}. {options[value]}"

    return str(value)


def show_exam_result(result):
    """显示一次已经完成判分的考试结果。"""

    st.success("试卷提交成功")
    if result["status"] == "pending_review":
        st.info(result.get("message") or "简答题待教师批改，最终成绩尚未生成")
        if st.button("刷新批改状态", key="refresh_exam_review"):
            updated = call_api("GET", f"/api/exams/attempts/{result['attempt_id']}/result")
            if updated is not None:
                st.session_state.exam_result = updated
                st.rerun()
        if st.button("返回考试列表", key="return_pending_exam_list"):
            st.session_state.attempt_id = None
            st.session_state.paper = None
            st.session_state.exam_result = None
            st.rerun()
        return
    st.metric(
        "考试得分",
        f"{result['total_score']} / {result['full_score']}",
    )
    st.subheader("逐题结果")
    display_answers = [
        {**item, "answer": json.dumps(item["answer"], ensure_ascii=False)}
        for item in result["answers"]
    ]
    st.dataframe(
        display_answers,
        width="stretch",
    )

    if st.button(
        "返回考试列表",
        key="return_to_exam_list",
    ):
        st.session_state.attempt_id = None
        st.session_state.paper = None
        st.session_state.exam_result = None
        st.rerun()


def render_exam_question(question, attempt_id):
    """根据题型渲染一道题，并返回学生当前选择的答案。"""

    question_id = question["question_id"]
    question_type = question["question_type"]
    options = question.get("options") or {}
    widget_key = f"exam_answer_{attempt_id}_{question_id}"

    st.markdown(
        f"### {question['position']}. {question['stem']}"
    )
    st.caption(f"本题 {question['points']} 分")

    if question_type == "single_choice":
        option_values = (
            list(options.keys())
            if isinstance(options, dict)
            else list(options)
        )
        return st.radio(
            "请选择一个答案",
            option_values,
            index=None,
            format_func=lambda value: format_exam_option(
                value,
                options,
            ),
            key=widget_key,
        )

    if question_type == "multiple_choice":
        option_values = (
            list(options.keys())
            if isinstance(options, dict)
            else list(options)
        )
        return st.multiselect(
            "请选择所有正确答案",
            option_values,
            format_func=lambda value: format_exam_option(
                value,
                options,
            ),
            key=widget_key,
        )

    if question_type == "true_false":
        return st.radio(
            "请选择",
            [True, False],
            index=None,
            format_func=lambda value: "正确" if value else "错误",
            key=widget_key,
        )

    if question_type == "fill_blank":
        return st.text_input("请填写答案", key=widget_key)
    return st.text_area("请输入简答内容", key=widget_key)


def show_student_page():
    """显示可参加考试、答题表单和提交结果。"""

    page_intro("课程考试", "参加已发布的考试；提交后可查看客观题结果，简答题由教师批改。", "学生端 / 测评")

    result = st.session_state.get("exam_result")
    if result is not None:
        show_exam_result(result)
        return

    paper = st.session_state.get("paper")
    attempt_id = st.session_state.get("attempt_id")

    if paper is None:
        exams = call_api(
            "GET",
            "/api/exams/available",
        )

        if exams is None:
            return

        if not exams:
            st.info("当前没有可以参加的考试。")
            return

        exam_columns = st.columns(2, gap="medium")
        for index, exam in enumerate(exams):
            exam_id = exam["exam_id"]

            with exam_columns[index % 2], st.container(border=True):
                st.subheader(exam["title"])
                st.write(f"课程：{exam['course_name']}")
                st.caption(
                    f"考试 ID：{exam_id} · "
                    f"限时 {exam['duration_minutes']} 分钟"
                )

                if st.button(
                    "开始考试",
                    key=f"start_exam_{exam_id}",
                    type="primary",
                ):
                    attempt = call_api(
                        "POST",
                        f"/api/exams/{exam_id}/attempts",
                    )

                    if attempt is None:
                        return

                    paper_result = call_api(
                        "GET",
                        (
                            "/api/exams/attempts/"
                            f"{attempt['attempt_id']}/paper"
                        ),
                    )

                    if paper_result is None:
                        return

                    st.session_state.attempt_id = (
                        attempt["attempt_id"]
                    )
                    st.session_state.paper = paper_result
                    st.session_state.exam_result = None
                    st.rerun()

        return

    st.subheader(paper["exam_title"])
    st.caption(f"提交截止时间：{paper['deadline']}")

    collected_answers = []

    with st.form(f"exam_form_{attempt_id}"):
        for question in paper["questions"]:
            answer = render_exam_question(
                question,
                attempt_id,
            )
            collected_answers.append({
                "question_id": question["question_id"],
                "answer": answer,
            })
            st.divider()

        submitted = st.form_submit_button(
            "提交试卷",
            type="primary",
        )

    if not submitted:
        return

    unanswered_question_ids = [
        item["question_id"]
        for item in collected_answers
        if item["answer"] is None
        or item["answer"] == []
        or item["answer"] == ""
    ]

    if unanswered_question_ids:
        st.error(
            "还有题目没有作答："
            + "、".join(unanswered_question_ids)
        )
        return

    result = call_api(
        "POST",
        f"/api/exams/attempts/{attempt_id}/submit",
        {
            "answers": collected_answers,
        },
    )

    if result is not None:
        st.session_state.paper = None
        st.session_state.exam_result = result
        st.rerun()


def show_result_page():
    page_intro("考试成绩", "按考试记录查询成绩与逐题反馈。", "学生端 / 测评结果")

    previous_attempt_id = st.session_state.get("attempt_id")
    attempt_id = st.number_input(
        "考试记录 ID",
        min_value=1,
        value=int(previous_attempt_id or 1),
        step=1,
    )

    if st.button("查询结果"):
        result = call_api(
            "GET",
            f"/api/exams/attempts/{attempt_id}/result",
        )
        if result is not None:
            st.session_state.exam_result = result

    result = st.session_state.get("exam_result")
    if result is not None:
        if result["status"] == "pending_review":
            st.info(result.get("message") or "简答题待教师批改，最终成绩尚未生成")
            return
        st.metric(
            "考试得分",
            f"{result['total_score']} / {result['full_score']}",
        )
        st.subheader("逐题结果")
        st.dataframe(result["answers"],
    width="stretch",)


def main():
    initialize_session_state()
    initialize_api_url()
    apply_platform_theme()
    with st.sidebar:
        sidebar_brand()
        st.caption("从课程到反馈，每一步都可追溯。")
        with st.expander("连接设置", icon=":material/settings:"):
            st.text_input(
                "后端 API 地址",
                key="api_url",
            )

    if not st.session_state.get("token"):
        show_auth_page(st.session_state.api_url)
        return

    role = st.session_state["role"]
    user_id = st.session_state["user_id"]
    current_page = None
    if role == "teacher":
        current_page = st.sidebar.radio(
            "教师工作区",
            ["总览", "课程资料", "题库与考试", "主观题批改"],
            key="teacher_page",
        )
    elif role == "student":
        pending_page = st.session_state.pop("pending_student_page", None)
        if pending_page is not None:
            st.session_state.student_page = pending_page
        current_page = st.sidebar.radio(
            "学生工作区",
            ["课程中心", "AI 学习助手", "学生考试", "查询成绩"],
            key="student_page",
        )

    role_label = {"admin": "管理员", "teacher": "教师", "student": "学生"}.get(role, role)
    with st.sidebar:
        st.caption("当前账号")
        st.markdown(f"**{user_id}**")
        st.badge(role_label, color="blue")

    if st.sidebar.button("退出登录", icon=":material/logout:", width="stretch"):
        for key in (
            "token",
            "role",
            "user_id",
            "attempt_id",
            "paper",
            "exam_result",
            "created_exam",
            "agent_session_id",
            "agent_course_id",
            "agent_session_title",
            "agent_messages",
            "agent_history_loaded_for",
            "student_page",
            "pending_student_page",
            "teacher_page",
        ):
            st.session_state.pop(key, None)

        st.rerun()
        return

    if role == "admin":
        show_admin_page()
    elif role == "teacher":
        show_teacher_page(current_page)
    elif role == "student":
        if current_page == "课程中心":
            show_course_center()
        elif current_page == "AI 学习助手":
            show_student_agent_page()
        elif current_page == "学生考试":
            show_student_page()
        else:
            show_result_page()
    else:
        st.error(f"未识别的角色：{role}")


if __name__ == "__main__":
    main()
