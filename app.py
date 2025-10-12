import streamlit as st
import requests
import re
import random
import time
import json
import hashlib
import secrets
from datetime import datetime, timedelta
import uuid
import google.generativeai as genai
import pandas as pd
from PIL import Image
import io
from streamlit_drawable_canvas import st_canvas

# --- 页面基础设置 ---
st.set_page_config(page_title="在线作业平台", page_icon="📚", layout="centered")

# --- 全局常量 ---
BASE_ONEDRIVE_PATH = "root:/Apps/HomeworkPlatform"
COURSES_FILE_PATH = f"{BASE_ONEDRIVE_PATH}/all_courses.json"
HOMEWORK_FILE_PATH = f"{BASE_ONEDRIVE_PATH}/all_homework.json" # New constant for single homework file

# --- 初始化 Session State ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'user_email' not in st.session_state: st.session_state.user_email = ""
if 'login_step' not in st.session_state: st.session_state.login_step = "enter_email"
if 'selected_course_id' not in st.session_state: st.session_state.selected_course_id = None
if 'viewing_homework_id' not in st.session_state: st.session_state.viewing_homework_id = None
if 'grading_submission' not in st.session_state: st.session_state.grading_submission = None
if 'ai_grade_result' not in st.session_state: st.session_state.ai_grade_result = None

# --- API 配置 ---
MS_GRAPH_CONFIG = st.secrets["microsoft_graph"]
try:
    genai.configure(api_key=st.secrets["gemini_api"]["api_key"])
    MODEL = genai.GenerativeModel('models/gemini-2.5-flash')
    SAFETY_SETTINGS = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]
except Exception as e:
    st.error(f"Gemini API密钥配置失败: {e}")

# --- 核心功能函数定义 ---
def get_email_hash(email): return hashlib.sha256(email.lower().encode('utf-8')).hexdigest()

@st.cache_data(ttl=3500)
def get_ms_graph_token():
    url = f"https://login.microsoftonline.com/{MS_GRAPH_CONFIG['tenant_id']}/oauth2/v2.0/token"
    data = {"grant_type": "client_credentials", "client_id": MS_GRAPH_CONFIG['client_id'], "client_secret": MS_GRAPH_CONFIG['client_secret'], "scope": "https://graph.microsoft.com/.default"}
    resp = requests.post(url, data=data); resp.raise_for_status(); return resp.json()["access_token"]

def onedrive_api_request(method, path, headers, data=None, params=None):
    base_url = f"https://graph.microsoft.com/v1.0/users/{MS_GRAPH_CONFIG['sender_email']}/drive"
    url = f"{base_url}/{path}"
    if method.lower() == 'get': return requests.get(url, headers=headers, params=params, timeout=20)
    if method.lower() == 'put': return requests.put(url, headers=headers, data=data, timeout=20)
    if method.lower() == 'delete': return requests.delete(url, headers=headers, timeout=20)
    return None

def get_onedrive_data(path, is_json=True):
    try:
        token = get_ms_graph_token(); headers = {"Authorization": f"Bearer {token}"}
        resp = onedrive_api_request('get', f"{path}:/content", headers)
        if resp.status_code == 404: return None
        resp.raise_for_status()
        return resp.json() if is_json else resp.content
    except Exception: return None

def save_onedrive_data(path, data, is_json=True):
    try:
        token = get_ms_graph_token(); headers = {"Authorization": f"Bearer {token}"}
        if is_json:
            headers["Content-Type"] = "application/json"
            content = json.dumps(data, indent=2, ensure_ascii=False).encode('utf-8')
        else:
            headers["Content-Type"] = "application/octet-stream"
            content = data
        onedrive_api_request('put', f"{path}:/content", headers, data=content)
        return True
    except Exception: return False

def delete_onedrive_file(path):
    try:
        token = get_ms_graph_token(); headers = {"Authorization": f"Bearer {token}"}
        response = onedrive_api_request('delete', path, headers); response.raise_for_status(); return True
    except Exception: return False

def get_user_profile(email): return get_onedrive_data(f"{BASE_ONEDRIVE_PATH}/users/{get_email_hash(email)}.json")
def save_user_profile(email, data): return save_onedrive_data(f"{BASE_ONEDRIVE_PATH}/users/{get_email_hash(email)}.json", data, is_json=True)
def get_global_data(file_name): data = get_onedrive_data(f"{BASE_ONEDRIVE_PATH}/{file_name}.json"); return data if data else {}
def save_global_data(file_name, data): return save_onedrive_data(f"{BASE_ONEDRIVE_PATH}/{file_name}.json", data)

def handle_send_code(email):
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email): st.sidebar.error("请输入有效的邮箱地址。"); return
    codes = get_global_data("codes"); code = "111111"
    codes[email.lower()] = {"code": code, "expires_at": time.time() + 300}
    save_global_data("codes", codes)
    st.sidebar.success("测试模式：请输入 111111")
    st.session_state.login_step = "enter_code"; st.session_state.temp_email = email; st.rerun()

def handle_verify_code(email, code):
    email = email.lower()
    codes = get_global_data("codes"); code_info = codes.get(email)
    if not code_info or time.time() > code_info["expires_at"]: st.sidebar.error("验证码已过期或不存在。"); return
    if code_info["code"] == code:
        if not get_user_profile(email):
            new_profile = {"email": email, "created_at": datetime.utcnow().isoformat() + "Z"}
            save_user_profile(email, new_profile); st.toast("🎉 注册成功！请选择您的身份。")
        sessions, token = get_global_data("sessions"), secrets.token_hex(16)
        sessions[token] = {"email": email, "expires_at": time.time() + (7 * 24 * 60 * 60)}
        save_global_data("sessions", sessions); del codes[email]; save_global_data("codes", codes)
        st.session_state.logged_in, st.session_state.user_email, st.session_state.login_step = True, email, "logged_in"
        st.query_params["session_token"] = token
        st.rerun()
    else: st.sidebar.error("验证码错误。")

def check_session_from_query_params():
    if st.session_state.get('logged_in'): return
    token = st.query_params.get("session_token")
    if not token: return
    sessions = get_global_data("sessions"); session_info = sessions.get(token)
    if session_info and time.time() < session_info.get("expires_at", 0):
        st.session_state.logged_in, st.session_state.user_email, st.session_state.login_step = True, session_info["email"], "logged_in"
    elif "session_token" in st.query_params: st.query_params.clear()

def display_login_form():
    with st.sidebar:
        st.header("🔐 用户登录/注册")
        if st.session_state.login_step == "enter_email":
            email = st.text_input("邮箱地址", key="email_input")
            if st.button("发送验证码"): handle_send_code(email)
        elif st.session_state.login_step == "enter_code":
            email_display = st.session_state.get("temp_email", "")
            st.info(f"验证码将发送至: {email_display}")
            code = st.text_input("验证码", key="code_input")
            if st.button("登录或注册"): handle_verify_code(email_display, code)
            if st.button("返回"): st.session_state.login_step = "enter_email"; st.rerun()

def call_gemini_api(prompt_parts):
    try:
        if isinstance(prompt_parts, str): prompt_parts = [prompt_parts]
        response = MODEL.generate_content(prompt_parts, safety_settings=SAFETY_SETTINGS)
        return response.text
    except Exception as e:
        st.error(f"调用AI时出错: {e}")
        return None

@st.cache_data(ttl=60)
def get_all_courses():
    courses = get_onedrive_data(COURSES_FILE_PATH)
    return courses if courses else []

def save_all_courses(courses_data):
    return save_onedrive_data(COURSES_FILE_PATH, courses_data)

@st.cache_data(ttl=60)
def get_all_homework():
    homework = get_onedrive_data(HOMEWORK_FILE_PATH)
    return homework if homework else []

def save_all_homework(homework_data):
    return save_onedrive_data(HOMEWORK_FILE_PATH, homework_data)

def get_teacher_courses(teacher_email): return [c for c in get_all_courses() if c.get('teacher_email') == teacher_email]
def get_student_courses(student_email): return [c for c in get_all_courses() if student_email in c.get('student_emails', [])]

def get_course_homework(course_id):
    all_hw = get_all_homework()
    return [hw for hw in all_hw if hw.get('course_id') == course_id]

@st.cache_data(ttl=30)
def get_homework(homework_id):
    all_hw = get_all_homework()
    return next((hw for hw in all_hw if hw.get('homework_id') == homework_id), None)

@st.cache_data(ttl=30)
def get_submissions_for_homework(homework_id):
    submissions = []
    try:
        token = get_ms_graph_token(); headers = {"Authorization": f"Bearer {token}"}
        path = f"{BASE_ONEDRIVE_PATH}/submissions/{homework_id}:/children"
        response = onedrive_api_request('get', path, headers)
        if response.status_code == 404: return []
        response.raise_for_status()
        student_folders = response.json().get('value', [])
        for folder in student_folders:
            submission_path = f"{BASE_ONEDRIVE_PATH}/submissions/{homework_id}/{folder['name']}/submission.json"
            submission_data = get_onedrive_data(submission_path)
            if submission_data:
                submissions.append(submission_data)
    except Exception: return []
    return submissions

def get_student_submission(homework_id, student_email):
    path = f"{BASE_ONEDRIVE_PATH}/submissions/{homework_id}/{get_email_hash(student_email)}/submission.json"
    return get_onedrive_data(path)

def render_teacher_dashboard(teacher_email):
    teacher_courses = get_teacher_courses(teacher_email)
    if st.session_state.selected_course_id:
        selected_course = next((c for c in teacher_courses if c['course_id'] == st.session_state.selected_course_id), None)
        if selected_course: render_course_management_view(selected_course, teacher_email); return
    st.header("教师仪表盘")
    with st.expander("创建新课程"):
        with st.form("create_course_form", clear_on_submit=True):
            course_name = st.text_input("课程名称")
            if st.form_submit_button("创建课程"):
                if course_name.strip():
                    teacher_course_names = [c['course_name'] for c in get_teacher_courses(teacher_email)]
                    if course_name in teacher_course_names:
                        st.error("您已经创建过同名课程，请使用其他名称。")
                    else:
                        all_courses = get_all_courses()
                        course_id, join_code = str(uuid.uuid4()), secrets.token_hex(3).upper()
                        new_course = {"course_id": course_id, "course_name": course_name, "teacher_email": teacher_email, "join_code": join_code, "student_emails": []}
                        all_courses.append(new_course)
                        if save_all_courses(all_courses):
                            st.success(f"课程 '{course_name}' 创建成功！加入代码: **{join_code}**"); st.cache_data.clear()
                        else: st.error("课程创建失败。")
    st.subheader("我的课程列表")
    if not teacher_courses:
        st.info("您还没有创建任何课程。请在上方创建您的第一门课程。")
    else:
        for course in teacher_courses:
            with st.container(border=True):
                st.markdown(f"#### {course['course_name']}")
                st.write(f"邀请码: `{course['join_code']}` | 学生人数: {len(course.get('student_emails', []))}")
                if st.button("进入管理", key=f"manage_{course['course_id']}"):
                    st.session_state.selected_course_id = course['course_id']; st.rerun()

def render_course_management_view(course, teacher_email):
    st.header(f"课程管理: {course['course_name']}")
    if st.button("返回课程列表"):
        st.session_state.selected_course_id = None; st.rerun()

    tab1, tab2, tab3, tab4 = st.tabs(["作业管理", "学生管理", "成绩册", "📊 学情分析"])

    with tab1:
        st.subheader("已发布的作业")
        course_homeworks = get_course_homework(course['course_id'])
        if not course_homeworks:
            st.info("本课程暂无作业。")
        else:
            for hw in course_homeworks:
                with st.container(border=True):
                    st.write(f"**{hw['title']}**")
                    with st.expander("查看题目"):
                        for i, q in enumerate(hw['questions']):
                            st.write(f"**第{i+1}题 ({q.get('type', 'text')}):** {q['question']}")
                    if st.button("删除此作业", key=f"del_{hw['homework_id']}", type="primary"):
                        all_hw = get_all_homework()
                        new_hw_list = [h for h in all_hw if h['homework_id'] != hw['homework_id']]
                        if save_all_homework(new_hw_list):
                            st.success("作业已删除！"); st.cache_data.clear(); time.sleep(1); st.rerun()
                        else:
                            st.error("删除失败。")
        st.divider()

        st.subheader("用AI生成并发布新作业")
        topic = st.text_input("作业主题", key=f"topic_{course['course_id']}")
        details = st.text_area("具体要求", key=f"details_{course['course_id']}")
        if st.button("AI 生成作业题目", key=f"gen_hw_{course['course_id']}"):
            if topic and details:
                with st.spinner("AI正在为您生成题目..."):
                    prompt = f"""# 角色
你是一位教学经验丰富的老师。
# 任务
为课程“{course['course_name']}”创建一份关于“{topic}”的作业。
作业要求如下：{details}
# 输出格式要求
你必须严格遵循以下JSON格式。整个输出必须是一个可以被直接解析的JSON对象，不包含任何解释性文字或Markdown标记。
**核心规则：**
- 作业必须包含 3 到 5 个**独立的问题**。
- 每一个问题都必须是`questions`列表中的一个**独立JSON对象**。
- **绝对不能**将多个题目的文本合并到单个`"question"`字段中。
**JSON格式模板：**
{{
  "title": "{topic} - 单元作业",
  "questions": [
    {{"id": "q0", "type": "text", "question": "这里是第一道独立的题目内容..."}},
    {{"id": "q1", "type": "multiple_choice", "question": "这里是第二道独立的题目内容...", "options": ["选项A", "选项B", "选项C"]}},
    {{"id": "q2", "type": "text", "question": "这里是第三道独立的题目内容..."}}
  ]
}}"""
                    response_text = call_gemini_api(prompt)
                    if response_text: 
                        st.session_state.generated_homework = response_text
                        st.success("作业已生成！请在下方编辑和发布。")
            else: st.warning("请输入作业主题和具体要求。")

        if 'generated_homework' in st.session_state and 'editable_homework' not in st.session_state:
            try:
                json_str_raw = re.sub(r'```json\s*|\s*```', '', st.session_state.generated_homework.strip())
                st.session_state.editable_homework = json.loads(json_str_raw)
            except Exception as e:
                st.error(f"AI返回格式有误，无法编辑: {e}")
                st.code(st.session_state.generated_homework)
            finally:
                if 'generated_homework' in st.session_state:
                    del st.session_state.generated_homework

        if 'editable_homework' in st.session_state:
            cols_header = st.columns([3, 1])
            with cols_header[0]:
                st.subheader("作业预览与发布 (可编辑)")
            with cols_header[1]:
                if st.button("❌ 取消编辑"):
                    del st.session_state.editable_homework
                    st.rerun()

            with st.form("edit_homework_form"):
                editable_data = st.session_state.editable_homework
                # Widgets are just for display. We'll get the real values from session_state on submit.
                st.text_input("作业标题", value=editable_data.get('title', ''), key=f"edited_title_{course['course_id']}")
                
                for i, q in enumerate(editable_data.get('questions', [])):
                    st.markdown(f"--- \n#### 第{i+1}题")
                    st.text_area("题目内容", value=q.get('question', ''), key=f"q_text_{i}", height=100)
                    
                    if q.get('type') == 'multiple_choice':
                        st.text_input("选项 (用英文逗号,分隔)", value=", ".join(q.get('options', [])), key=f"q_opts_{i}")
                
                submitted = st.form_submit_button("✅ 确认发布作业")
                if submitted:
                    # --- FIXED: Process form data *after* submission ---
                    edited_title = st.session_state[f"edited_title_{course['course_id']}"]
                    
                    course_hw_titles = [hw['title'] for hw in get_course_homework(course['course_id'])]
                    if edited_title in course_hw_titles:
                        st.error("本课程中已存在同名作业，请修改标题后发布。")
                    else:
                        # Rebuild questions list from session_state here
                        final_questions = []
                        for i, q in enumerate(editable_data.get('questions', [])):
                            question_text = st.session_state[f"q_text_{i}"]
                            question_type = q.get('type', 'text')
                            current_q = {'id': q.get('id', f'q_{i}'), 'type': question_type, 'question': question_text}
                            if question_type == 'multiple_choice':
                                options_str = st.session_state[f"q_opts_{i}"]
                                current_q['options'] = [opt.strip() for opt in options_str.split(',') if opt.strip()]
                            final_questions.append(current_q)

                        all_hw = get_all_homework()
                        homework_to_save = {
                            "homework_id": str(uuid.uuid4()), "course_id": course['course_id'],
                            "title": edited_title, "questions": final_questions
                        }
                        all_hw.append(homework_to_save)
                        if save_all_homework(all_hw):
                            st.success(f"作业已成功发布！")
                            del st.session_state.editable_homework
                            st.cache_data.clear()
                            time.sleep(1); st.rerun()
                        else:
                            st.error("作业发布失败。")

    with tab2:
        st.subheader("学生管理")
        student_list = course.get('student_emails', [])
        if not student_list:
            st.info("目前还没有学生加入本课程。")
        else:
            for student_email in student_list:
                cols = st.columns([4, 1]); cols[0].write(f"- {student_email}")
                if cols[1].button("移除", key=f"remove_{get_email_hash(student_email)}", type="primary"):
                    all_courses = get_all_courses()
                    target_course = next((c for c in all_courses if c['course_id'] == course['course_id']), None)
                    if target_course and student_email in target_course['student_emails']:
                        target_course['student_emails'].remove(student_email)
                        if save_all_courses(all_courses):
                             st.success(f"已移除 {student_email}"); st.cache_data.clear(); time.sleep(1); st.rerun()
                        else: st.error("操作失败。")
    
    with tab3:
        st.subheader("成绩册")
        homework_list = get_course_homework(course['course_id'])
        if not homework_list:
            st.info("本课程还没有已发布的作业。"); return

        for hw in homework_list:
            with st.expander(f"**{hw['title']}**", expanded=True):
                submissions = get_submissions_for_homework(hw['homework_id'])
                submissions_map = {sub['student_email']: sub for sub in submissions}
                
                all_students = course.get('student_emails', [])
                if not all_students:
                    st.write("本课程暂无学生。")
                else:
                    for student_email in all_students:
                        sub = submissions_map.get(student_email)
                        cols = st.columns([3, 2, 2, 3])
                        cols[0].write(student_email)
                        if sub:
                            status = sub.get("status", "submitted")
                            if status == "submitted":
                                cols[1].info("已提交")
                                if cols[2].button("批改", key=f"grade_{sub['submission_id']}"):
                                    st.session_state.grading_submission = sub; st.rerun()
                            elif status == "ai_graded":
                                cols[1].warning("AI已批改")
                                if cols[2].button("审核", key=f"review_{sub['submission_id']}"):
                                    st.session_state.grading_submission = sub; st.rerun()
                            elif status == "feedback_released":
                                cols[1].success("已反馈")
                                cols[2].metric("得分", sub.get('final_grade', 'N/A'))
                                if cols[3].button("🤖 生成补习作业", key=f"remedial_{sub['submission_id']}"):
                                    with st.spinner(f"正在为 {sub['student_email']} 生成个性化补习作业..."):
                                        original_homework = get_homework(sub['homework_id'])
                                        if not original_homework:
                                            st.error("找不到原始作业，无法生成补习作业。")
                                        else:
                                            prompt = f"""# 角色
你是一位顶级的个性化教育导师。你的任务是根据学生过去的作业表现，为他们量身定制一份补习作业。
# 背景信息
学生 ({sub['student_email']}) 刚刚完成了名为《{original_homework['title']}》的作业。以下是原始作业的题目、学生的回答、以及系统给出的逐题反馈。
## 原始作业题目
{json.dumps(original_homework['questions'], ensure_ascii=False)}
## 学生的回答与反馈
{json.dumps(sub.get('ai_detailed_grades', []), ensure_ascii=False)}
# 任务
请仔细分析学生在哪些知识点上表现薄弱。然后，生成一份全新的、有针对性的补习作业，帮助学生巩固这些薄弱环节。
# 要求
1. **个性化**: 新题目必须与学生答错或表现不佳的题目相关。
2. **难度适中**: 题目应该旨在巩固基础，而不是增加难度。
3. **格式严格**: 输出必须是严格的JSON格式，与原始作业格式完全相同。不要包含任何额外的解释或文本。
## JSON输出格式示例
{{
  "title": "针对《{original_homework['title']}》的个性化补习作业",
  "questions": [
    {{"id": "remedial_q0", "type": "text", "question": "这是一个新的、针对性的问题..."}},
    {{"id": "remedial_q1", "type": "multiple_choice", "question": "这是另一个新的、针对性的选择题...", "options": ["选项A", "选项B", "选项C"]}}
  ]
}}
---
请现在开始生成补习作业的JSON内容。"""
                                            remedial_hw_text = call_gemini_api(prompt)
                                            if remedial_hw_text:
                                                try:
                                                    json_str = remedial_hw_text.strip().replace("```json", "").replace("```", "")
                                                    remedial_hw_data = json.loads(json_str)
                                                    all_hw = get_all_homework()
                                                    new_hw_id = "remedial_" + str(uuid.uuid4())
                                                    homework_to_save = {
                                                        "homework_id": new_hw_id, "course_id": original_homework['course_id'],
                                                        "student_email": sub['student_email'], "original_homework_id": original_homework['homework_id'],
                                                        "title": remedial_hw_data.get('title', f"补习作业 for {original_homework['title']}"),
                                                        "questions": remedial_hw_data.get('questions', [])
                                                    }
                                                    all_hw.append(homework_to_save)
                                                    if save_all_homework(all_hw):
                                                        st.success(f"已为 {sub['student_email']} 生成补习作业！"); st.cache_data.clear(); time.sleep(2); st.rerun()
                                                    else: st.error("保存补习作业失败。")
                                                except Exception as e:
                                                    st.error(f"AI返回的补习作业格式有误: {e}"); st.code(remedial_hw_text)
                                            else: st.error("AI未能生成补习作业。")
                        else:
                            cols[1].error("未提交")

    with tab4:
        st.subheader("📊 班级学情分析")
        homework_list = get_course_homework(course['course_id'])
        if not homework_list:
            st.info("本课程还没有已发布的作业，无法进行分析。"); return

        hw_options = {hw['title']: hw['homework_id'] for hw in homework_list}
        selected_hw_title = st.selectbox("请选择要分析的作业", options=list(hw_options.keys()))

        if st.button("开始分析", key=f"analyze_{hw_options[selected_hw_title]}"):
            with st.spinner("AI正在汇总分析全班的作业情况..."):
                selected_hw_id = hw_options[selected_hw_title]
                homework = get_homework(selected_hw_id)
                submissions = get_submissions_for_homework(selected_hw_id)
                graded_submissions = [s for s in submissions if s.get('status') == 'feedback_released']

                if len(graded_submissions) < 2:
                    st.warning("已批改的提交人数过少（少于2人），无法进行有意义的分析。")
                else:
                    performance_summary = [{"grade": sub['final_grade'], "detailed_grades": sub.get('ai_detailed_grades', [])} for sub in graded_submissions]
                    prompt = f"""# 角色
你是一位顶级的教育数据分析专家，任务是根据全班的作业提交数据，生成一份学情分析报告。
# 数据
## 作业题目
{json.dumps(homework['questions'], ensure_ascii=False)}
## 全班匿名批改数据汇总
{json.dumps(performance_summary, ensure_ascii=False)}
# 任务
请根据以上数据，生成一份学情分析报告，包含以下内容：
1.  **总体表现总结**: 班级整体得分情况（平均分、高分段、低分段分布）。
2.  **知识点掌握情况**: 分析哪些题目（知识点）学生普遍掌握得好，哪些掌握得不好。
3.  **典型错误分析**: 总结学生们出现的常见错误类型。
4.  **教学建议**: 基于以上分析，给老师提出后续的教学建议，比如需要重点讲解哪些内容。
---
请开始生成您的学情分析报告。"""
                    analysis_report = call_gemini_api(prompt)
                    if analysis_report:
                        st.markdown("### 学情分析报告")
                        st.markdown(analysis_report)


def render_student_dashboard(student_email):
    st.header("学生仪表盘")
    my_courses = get_student_courses(student_email)
    tab1, tab2 = st.tabs(["我的课程", "加入新课程"])
    with tab2:
        with st.form("join_course_form", clear_on_submit=True):
            join_code = st.text_input("请输入课程邀请码").upper()
            if st.form_submit_button("加入课程"):
                if not join_code: st.warning("请输入邀请码。")
                else:
                    all_courses = get_all_courses()
                    target_course = next((c for c in all_courses if c.get('join_code') == join_code), None)
                    if not target_course: st.error("邀请码无效，未找到对应课程。")
                    elif student_email in target_course.get('student_emails', []): st.info("您已经加入此课程。")
                    else:
                        target_course.setdefault('student_emails', []).append(student_email)
                        if save_all_courses(all_courses):
                            st.success(f"成功加入课程 '{target_course['course_name']}'！"); st.cache_data.clear(); st.rerun()
                        else: st.error("加入课程失败，请稍后再试。")
    with tab1:
        st.subheader("我加入的课程")
        if not my_courses:
            st.info("您还没有加入任何课程。请到“加入新课程”标签页输入邀请码。"); return

        for course in my_courses:
            with st.expander(f"**{course['course_name']}**", expanded=False):
                all_course_homeworks = get_course_homework(course['course_id'])
                student_homeworks = [hw for hw in all_course_homeworks if 'student_email' not in hw or hw.get('student_email') == student_email]

                if not student_homeworks:
                    st.write("这门课还没有发布任何作业。")
                else:
                    for hw in student_homeworks:
                        submission = get_student_submission(hw['homework_id'], student_email)
                        cols = st.columns([3,2,2])
                        cols[0].write(f"{hw['title']}")
                        if submission:
                            status = submission.get('status', 'submitted')
                            if status == 'feedback_released':
                                cols[1].success(f"已批改: {submission.get('final_grade', 'N/A')}/100")
                                if cols[2].button("查看结果", key=f"view_{hw['homework_id']}"):
                                    st.session_state.viewing_homework_id = hw['homework_id']; st.rerun()
                            else:
                                cols[1].info("已提交"); cols[2].write("待批改")
                        else:
                            cols[1].warning("待完成")
                            if cols[2].button("开始作业", key=f"do_{hw['homework_id']}"):
                                st.session_state.viewing_homework_id = hw['homework_id']; st.rerun()

def render_homework_submission_view(homework, student_email):
    st.header(f"作业: {homework['title']}")
    if st.button("返回课程列表"):
        st.session_state.viewing_homework_id = None
        st.rerun()

    with st.expander("查看题目要求", expanded=True):
        for i, q in enumerate(homework['questions']):
             st.write(f"**第{i+1}题:** {q['question']}")
             if q.get('type') == 'multiple_choice':
                 st.write(f"选项: {', '.join(q.get('options', []))}")

    st.divider()
    
    with st.form("email_submission_form"):
        st.subheader("撰写回答")
        main_text_answer = st.text_area("正文", height=250, placeholder="在此输入您的主要文字回答...")
        uploaded_files = st.file_uploader(
            "添加附件 (图片、录音、视频)",
            accept_multiple_files=True,
            type=['png', 'jpg', 'jpeg', 'mp3', 'wav', 'm4a', 'mp4', 'mov']
        )
        
        submitted = st.form_submit_button("确认提交作业")
        if submitted:
            with st.spinner("正在处理并提交您的作业..."):
                final_answers = {'main_text': main_text_answer, 'attachments': []}
                processed_files = {}

                if uploaded_files:
                    for uploaded_file in uploaded_files:
                        safe_filename = f"{uuid.uuid4().hex}_{uploaded_file.name}"
                        final_answers['attachments'].append(safe_filename)
                        processed_files[safe_filename] = uploaded_file.getvalue()

                submission_path_prefix = f"{BASE_ONEDRIVE_PATH}/submissions/{homework['homework_id']}/{get_email_hash(student_email)}"
                for filename, filebytes in processed_files.items():
                    path = f"{submission_path_prefix}/{filename}"
                    save_onedrive_data(path, filebytes, is_json=False)

                submission_id = str(uuid.uuid4())
                submission_data = {
                    "submission_id": submission_id, "homework_id": homework['homework_id'],
                    "student_email": student_email, "answers": final_answers,
                    "status": "submitted", "timestamp": datetime.utcnow().isoformat() + "Z"
                }
                path = f"{submission_path_prefix}/submission.json"
                if save_onedrive_data(path, submission_data, is_json=True):
                    st.success("作业提交成功！"); st.cache_data.clear(); time.sleep(2)
                    st.session_state.viewing_homework_id = None; st.rerun()
                else:
                    st.error("提交失败，请稍后重试。")

def render_attachment(file_path, file_name):
    file_extension = file_name.split('.')[-1].lower()
    with st.spinner(f"正在加载附件: {file_name}..."):
        file_bytes = get_onedrive_data(file_path, is_json=False)
        if file_bytes:
            if file_extension in ['png', 'jpg', 'jpeg']: st.image(file_bytes, caption=file_name)
            elif file_extension in ['mp3', 'wav', 'm4a']: st.audio(file_bytes, format=f'audio/{file_extension}')
            elif file_extension in ['mp4', 'mov']: st.video(file_bytes, format=f'video/{file_extension}')
            else: st.warning(f"不支持预览此附件类型: {file_name}")
        else: st.error(f"无法加载附件: {file_name}")

def render_student_graded_view(submission, homework):
    st.header(f"作业结果: {homework['title']}")
    if st.button("返回课程列表"):
        st.session_state.viewing_homework_id = None; st.rerun()

    st.metric("最终得分", f"{submission.get('final_grade', 'N/A')} / 100")
    st.info(f"**教师总评:** {submission.get('final_feedback', '老师没有留下评语。')}")
    st.divider()

    st.subheader("我的提交")
    answers = submission.get('answers', {})
    st.info(f"**文字回答:**\n\n{answers.get('main_text', '无')}")

    attachments = answers.get('attachments', [])
    if attachments:
        st.write("**附件:**")
        for filename in attachments:
            file_path = f"{BASE_ONEDRIVE_PATH}/submissions/{homework['homework_id']}/{get_email_hash(submission['student_email'])}/{filename}"
            render_attachment(file_path, filename)
    
    st.divider()
    st.subheader("逐题分析与反馈")
    detailed_grades = submission.get('ai_detailed_grades', [])
    if detailed_grades:
        for detail in detailed_grades:
            q_index = detail.get('question_index', -1)
            feedback = detail.get('feedback', '无反馈')
            if q_index != -1 and q_index < len(homework['questions']):
                question_text = homework['questions'][q_index]['question']
                with st.container(border=True):
                    st.write(f"**题目 {q_index + 1}:** {question_text}")
                    st.warning(f"**AI反馈:** {feedback}")
    else:
        st.info("暂无逐题的AI反馈。")

def get_mime_type(filename):
    ext = filename.split('.')[-1].lower()
    types = {
        'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
        'mp3': 'audio/mpeg', 'wav': 'audio/wav', 'm4a': 'audio/m4a',
        'mp4': 'video/mp4', 'mov': 'video/quicktime'
    }
    return types.get(ext, None)

def render_teacher_grading_view(submission, homework):
    st.header("作业批改")
    if st.button("返回成绩册"):
        st.session_state.grading_submission = None; st.session_state.ai_grade_result = None; st.rerun()

    st.subheader(f"学生: {submission['student_email']}")
    st.write(f"作业: {homework['title']}"); st.divider()
    
    st.subheader("学生提交的内容")
    answers = submission.get('answers', {})
    st.info(f"**文字回答:**\n\n{answers.get('main_text', '无')}")
    
    attachments = answers.get('attachments', [])
    if attachments:
        st.write("**附件:**")
        for filename in attachments:
            file_path = f"{BASE_ONEDRIVE_PATH}/submissions/{homework['homework_id']}/{get_email_hash(submission['student_email'])}/{filename}"
            render_attachment(file_path, filename)
    st.divider()

    if submission.get('status') != 'feedback_released':
        if st.button("🤖 AI自动批改", key=f"ai_grade_{submission['submission_id']}"):
            with st.spinner("AI正在进行多模态分析与批改..."):
                instruction_prompt = """# 角色
你是一位经验丰富、耐心且善于引导的教学助手。你的专长是分析多媒体作业提交，包括文本、图片、音频和视频。
# 任务
请根据【作业题目】、【学生文字回答】和【附件内容】批改作业。
# 核心指令：多模态内容分析
1.  **综合分析**: 将学生的文字回答和所有附件内容作为一个整体来理解和评分。
2.  **图片附件**: 直接分析图片中的手写文字、图表或图像，并评价其正确性。
3.  **音频/视频附件**:
    * **转写与分析**: 如果附件是音频或视频，并且题目要求朗诵、背诵或口头回答，请先**转写**学生所说的内容。然后，将转写内容与题目要求（如原文）进行比对，指出其中的错误、遗漏或不流畅之处。
    * **时间戳标记**: 在提供反馈时，如果可能，请使用 **[HH:MM:SS]** 格式的时间戳来指出具体问题发生在哪一秒。例如：“[00:00:15] ‘pronunciation’ 这个单词的发音不准确。”
    * **内容理解**: 如果视频内容是过程演示（如解题、实验操作），请描述学生的步骤并评价其方法的正确性。
4.  **给出分数和评语**: 基于以上综合分析，为每个问题提供反馈，并给出最终的总分和总体评语。
# 输出格式
请严格以JSON格式输出，不要包含任何额外说明或markdown标记。
{
  "overall_grade": 85,
  "overall_feedback": "同学，你做得很好！文字部分回答清晰，知识点掌握扎实。背诵录音整体流畅，但在[00:00:21]处有一个明显的发音错误，请注意。",
  "detailed_grades": [
    {"question_index": 0, "grade": 20, "feedback": "第一题的图片解答步骤清晰，结果正确。"},
    {"question_index": 1, "grade": 15, "feedback": "第二题的背诵很流利，但在[00:01:10]将‘persistent’读成了‘pro-sistent’，请多加练习。"}
  ]
}"""
                
                text_data_part = f"""
【作业题目】: {json.dumps(homework['questions'], ensure_ascii=False, indent=2)}
【学生文字回答】: {answers.get('main_text', '')}
【附件列表】: {json.dumps(attachments, ensure_ascii=False)}
(附件的具体内容将在后面提供)
---
请开始你的批改工作。"""
                
                api_prompt_parts = [instruction_prompt, text_data_part]

                for filename in attachments:
                    file_path = f"{BASE_ONEDRIVE_PATH}/submissions/{homework['homework_id']}/{get_email_hash(submission['student_email'])}/{filename}"
                    mime_type = get_mime_type(filename)
                    if not mime_type: 
                        st.toast(f"不支持的文件类型: {filename}，已跳过", icon="⚠️")
                        continue

                    file_bytes = get_onedrive_data(file_path, is_json=False)
                    if file_bytes:
                        api_prompt_parts.append(f"--- 附件 '{filename}' 内容 ---")
                        if mime_type.startswith('video/') or mime_type.startswith('audio/'):
                            api_prompt_parts.append(genai.Part.from_data(mime_type=mime_type, data=file_bytes))
                        elif mime_type.startswith('image/'):
                             api_prompt_parts.append(Image.open(io.BytesIO(file_bytes)))
                    else:
                        api_prompt_parts.append(f"--- 附件 '{filename}' 无法加载 ---")


                ai_result_text = call_gemini_api(api_prompt_parts)
                if ai_result_text:
                    try:
                        json_str = ai_result_text.strip().replace("```json", "").replace("```", "")
                        ai_result = json.loads(json_str)
                        st.session_state.ai_grade_result = ai_result; st.rerun()
                    except Exception as e:
                        st.error("AI返回结果格式有误，请手动批改。"); st.code(ai_result_text)
                        st.session_state.ai_grade_result = None
                else: st.error("AI调用失败，没有返回结果。")
    
    ai_result = st.session_state.get('ai_grade_result')
    if not ai_result and submission.get('status') == 'ai_graded':
        ai_result = {"overall_grade": submission.get('ai_grade'), "overall_feedback": submission.get('ai_feedback'), "detailed_grades": submission.get('ai_detailed_grades')}

    if ai_result:
        st.subheader("AI 批改建议")
        detailed_grades = ai_result.get('detailed_grades', [])
        if detailed_grades:
            for detail in detailed_grades:
                q_index = detail.get('question_index', -1)
                feedback = detail.get('feedback', '无')
                if q_index != -1 and q_index < len(homework['questions']):
                    question_text = homework['questions'][q_index]['question']
                    with st.container(border=True):
                        st.write(f"**题目 {q_index + 1}:** {question_text}")
                        st.warning(f"**AI反馈:** {feedback}")
        st.divider()

    initial_grade, initial_feedback = (ai_result.get('overall_grade', 0), ai_result.get('overall_feedback', "")) if ai_result else (0, "")
    st.subheader("教师最终审核")
    try: initial_grade_value = int(float(initial_grade))
    except (ValueError, TypeError): initial_grade_value = 0
    final_grade = st.number_input("最终得分", min_value=0, max_value=100, value=initial_grade_value)
    final_feedback = st.text_area("最终评语", value=initial_feedback, height=200)

    if st.button("✅ 确认并将结果反馈给学生", type="primary"):
        submission['status'] = "feedback_released"; submission['final_grade'] = final_grade; submission['final_feedback'] = final_feedback
        if ai_result:
            submission['ai_grade'] = ai_result.get('overall_grade'); submission['ai_feedback'] = ai_result.get('overall_feedback'); submission['ai_detailed_grades'] = ai_result.get('detailed_grades')

        path = f"{BASE_ONEDRIVE_PATH}/submissions/{submission['homework_id']}/{get_email_hash(submission['student_email'])}/submission.json"
        if save_onedrive_data(path, submission):
            st.success("成绩和评语已成功反馈给学生！")
            st.session_state.grading_submission = None; st.session_state.ai_grade_result = None
            st.cache_data.clear(); time.sleep(1); st.rerun()
        else: st.error("反馈失败。")

# --- 主程序 ---
st.title("📚 在线作业平台")
check_session_from_query_params()
if not st.session_state.get('logged_in'):
    display_login_form()
    st.info("👈 请在左侧侧边栏使用您的邮箱登录或注册。")
else:
    user_email = st.session_state.user_email
    with st.sidebar:
        st.success(f"欢迎, {user_email}")
        if st.button("退出登录"):
            for key in list(st.session_state.keys()): del st.session_state[key]
            st.query_params.clear(); st.rerun()

    user_profile = get_user_profile(user_email)
    if not user_profile: st.error("无法加载您的用户配置，请尝试重新登录。")
    elif 'role' not in user_profile:
        st.subheader("请选择您的身份")
        col1, col2 = st.columns(2)
        if col1.button("我是老师", use_container_width=True):
            user_profile['role'] = 'teacher'
            if save_user_profile(user_email, user_profile): st.success("身份已设置为老师！"); time.sleep(1); st.rerun()
            else: st.error("设置失败，请重试。")
        if col2.button("我是学生", use_container_width=True):
            user_profile['role'] = 'student'
            if save_user_profile(user_email, user_profile): st.success("身份已设置为学生！"); time.sleep(1); st.rerun()
            else: st.error("设置失败，请重试。")
    else:
        user_role = user_profile['role']
        if st.session_state.grading_submission:
            homework = get_homework(st.session_state.grading_submission['homework_id'])
            if homework: render_teacher_grading_view(st.session_state.grading_submission, homework)
            else: st.error("找不到对应的作业文件。"); st.session_state.grading_submission = None; st.rerun()
        elif st.session_state.viewing_homework_id:
            homework = get_homework(st.session_state.viewing_homework_id)
            if homework:
                submission = get_student_submission(homework['homework_id'], user_email)
                if submission and submission.get('status') == 'feedback_released':
                    render_student_graded_view(submission, homework)
                else: render_homework_submission_view(homework, user_email)
            else: st.error("找不到作业。"); st.session_state.viewing_homework_id = None; st.rerun()
        elif user_role == 'teacher':
            render_teacher_dashboard(user_email)
        elif user_role == 'student':
            render_student_dashboard(user_email)

