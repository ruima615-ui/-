import requests
import streamlit as st
from ui_theme import page_intro


def show_auth_page(api_url):
    page_intro("让教学反馈形成闭环",
               "教师管理课程资料与考试，学生完成测评后查看证据驱动的复习建议。",
               "COURSEPILOT / 教学智能工作台")
    showcase, access = st.columns([1, 1.15], gap="large")
    with showcase:
        st.subheader("从课程到个性化复习")
        st.caption("面向教学场景构建的课程、测评与学习助手工作台。")
        for title, detail, icon in [
            ("课程与资料", "教师上传讲义并核对片段知识点。", ":material/menu_book:"),
            ("考试与反馈", "从题库组卷，完成答题、判分与批改。", ":material/assignment_turned_in:"),
            ("AI 学习助手", "结合真实错题和课程资料给出复习建议。", ":material/auto_awesome:"),
        ]:
            with st.container(border=True):
                st.markdown(f"#### {icon} {title}")
                st.caption(detail)
    with access:
        st.subheader("进入工作台")
        st.caption("使用已有账号登录；首次使用可在下方申请学生或教师账号。")
        _show_auth_forms(api_url)


def _show_auth_forms(api_url):
    login_tab, student_tab, teacher_tab = st.tabs(
        ["登录", "学生注册", "教师注册"]
    )

    with login_tab:
        with st.form("login_form"):
            user_id = st.text_input("用户 ID")
            password = st.text_input("密码", type="password")
            login_clicked = st.form_submit_button("登录工作台", type="primary")

        if login_clicked:
            try:
                response = requests.post(
                    f"{api_url.rstrip('/')}/api/auth/login",
                    data={
                        "username": user_id.strip(),
                        "password": password,
                    },
                    timeout=20,
                )
                result = response.json()

                if not response.ok:
                    st.error(result.get("detail", "登录失败"))
                else:
                    st.session_state["token"] = result["access_token"]
                    st.session_state["user_id"] = result["user_id"]
                    st.session_state["role"] = result["role"]
                    st.rerun()

            except requests.RequestException as error:
                st.error(f"无法连接 FastAPI：{error}")
            except (ValueError, KeyError) as error:
                st.error(f"登录接口返回格式不符合预期：{error}")

    with student_tab:
        with st.form("register_form"):
            new_id = st.text_input("新用户 ID")
            name = st.text_input("姓名")
            new_password = st.text_input("设置密码", type="password")
            register_clicked = st.form_submit_button("注册学生账号")

        if register_clicked:
            try:
                response = requests.post(
                    f"{api_url.rstrip('/')}/api/auth/register",
                    json={
                        "user_id": new_id.strip(),
                        "name": name.strip(),
                        "password": new_password,
                    },
                    timeout=20,
                )
                result = response.json()

                if response.ok:
                    st.success("注册成功，请切换到「登录」并登录")
                else:
                    st.error(result.get("detail", "注册失败"))

            except requests.RequestException as error:
                st.error(f"无法连接 FastAPI：{error}")
            except ValueError:
                st.error("注册接口没有返回合法 JSON")

    with teacher_tab:
        st.caption("教师注册后需要管理员审核，审核通过后才能登录。")
        with st.form("teacher_register_form"):
            teacher_id = st.text_input("教师 ID")
            teacher_name = st.text_input("教师姓名")
            teacher_password = st.text_input(
                "设置教师密码",
                type="password",
            )
            teacher_register_clicked = st.form_submit_button(
                "提交教师注册"
            )

        if teacher_register_clicked:
            try:
                response = requests.post(
                    f"{api_url.rstrip('/')}/api/auth/register/teacher",
                    json={
                        "user_id": teacher_id.strip(),
                        "name": teacher_name.strip(),
                        "password": teacher_password,
                    },
                    timeout=20,
                )
                result = response.json()

                if response.ok:
                    st.success("注册申请已提交，请等待管理员审核")
                else:
                    st.error(result.get("detail", "教师注册失败"))

            except requests.RequestException as error:
                st.error(f"无法连接 FastAPI：{error}")
            except ValueError:
                st.error("注册接口没有返回合法 JSON")
