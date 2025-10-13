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
from itertools import combinations

# --- 页面基础设置 ---
st.set_page_config(page_title="在线作业平台", page_icon="📚", layout="centered")

# --- 全局常量 ---
BASE_ONEDRIVE_PATH = "root:/Apps/HomeworkPlatform"
COURSES_FILE_PATH = f"{BASE_ONEDRIVE_PATH}/all_courses.json"
HOMEWORK_FILE_PATH = f"{BASE_ONEDRIVE_PATH}/all_homework.json"

# --- 支持的文件类型 ---
SUPPORTED_FILE_TYPES = {
    "image": ['png', 'jpg', 'jpeg', 'webp', 'heic', 'heif'],
    "audio": ['mp3', 'wav', 'aac', 'flac', 'ogg'],
    "video": ['mp4', 'mov', 'avi', 'mpeg', 'webm'],
    "document": ['pdf', 'docx'],
    "code": ['py', 'js', 'html', 'css', 'java', 'cpp', 'c', 'cs', 'go', 'rb', 'php', 'sql', 'json', 'xml', 'md', 'ts'],
    "presentation": ['pptx'],
    "spreadsheet": ['xlsx']
}
ALL_SUPPORTED_EXTENSIONS = [ext for category in SUPPORTED_FILE_TYPES.values() for ext in category]


# --- 初始化 Session State ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'user_email' not in st.session_state: st.session_state.user_email = ""
if 'login_step' not in st.session_state: st.session_state.login_step = "enter_email"
if 'selected_course_id' not in st.session_state: st.session_state.selected_course_id = None
if 'viewing_homework_id' not in st.session_state: st.session_state.viewing_homework_id = None
if 'grading_submission' not in st.session_state: st.session_state.grading_submission = None
if 'ai_grade_result' not in st.session_state: st.session_state.ai_grade_result = None
if 'similarity_report' not in st.session_state: st.session_state.similarity_report = {}
if 'csv_data' not in st.session_state: st.session_state.csv_data = {}
if 'confirming_delete_course_id' not in st.session_state: st.session_state.confirming_delete_course_id = None


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

def delete_onedrive_item(path):
    try:
        token = get_ms_graph_token(); headers = {"Authorization": f"Bearer {token}"}
        # This API call works for both files and folders
        response = onedrive_api_request('delete', path, headers)
        if response.status_code in [204, 404]: # 204 is success, 404 means already deleted
            return True
        response.raise_for_status()
        return True
    except Exception:
        return False

def get_user_profile(email): return get_onedrive_data(f"{BASE_ONEDRIVE_PATH}/users/{get_email_hash(email)}.json")
def save_user_profile(email, data): return save_onedrive_data(f"{BASE_ONEDRIVE_PATH}/users/{get_email_hash(email)}.json", data, is_json=True)
def get_global_data(file_name): data = get_onedrive_data(f"{BASE_ONEDRIVE_PATH}/{file_name}.json"); return data if data else {}
def save_global_data(file_name, data): return save_onedrive_data(f"{BASE_ONEDRIVE_PATH}/{file_name}.json", data)

def get_mime_type(filename):
    ext = filename.split('.')[-1].lower()
    mime_map = {
        'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'webp': 'image/webp',
        'heic': 'image/heic', 'heif': 'image/heif',
        'mp3': 'audio/mpeg', 'wav': 'audio/wav', 'aac': 'audio/aac', 'flac': 'audio/flac', 'ogg': 'audio/ogg',
        'mp4': 'video/mp4', 'mov': 'video/quicktime', 'avi': 'video/x-msvideo', 'mpeg': 'video/mpeg', 'webm': 'video/webm',
        'pdf': 'application/pdf',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'py': 'text/x-python', 'js': 'application/javascript', 'html': 'text/html', 'css': 'text/css',
        'java': 'text/x-java-source', 'cpp': 'text/x-c', 'c': 'text/x-c', 'cs': 'text/plain',
        'go': 'text/x-go', 'rb': 'text/x-ruby', 'php': 'application/x-httpd-php', 'sql': 'application/sql',
        'json': 'application/json', 'xml': 'application/xml', 'md': 'text/markdown', 'ts': 'text/typescript'
    }
    return mime_map.get(ext)

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
            if st.button("发送验证码", use_container_width=True): handle_send_code(email)
        elif st.session_state.login_step == "enter_code":
            email_display = st.session_state.get("temp_email", "")
            st.info(f"验证码将发送至: {email_display}")
            code = st.text_input("验证码", key="code_input")
            if st.button("登录或注册", use_container_width=True): handle_verify_code(email_display, code)
            if st.button("返回", use_container_width=True): st.session_state.login_step = "enter_email"; st.rerun()

def call_gemini_api(prompt_parts):
    try:
        if isinstance(prompt_parts, str): prompt_parts = [prompt_parts]
        response = MODEL.generate_content(prompt_parts, safety_settings=SAFETY_SETTINGS, request_options={"timeout": 600})
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

@st.cache_data(ttl=120)
def get_student_profiles_for_course(student_emails):
    profiles = {}
    for email in student_emails:
        profile = get_user_profile(email)
        if profile:
            profiles[email] = profile
    return profiles

def calculate_jaccard_similarity(text1, text2):
    if not text1 or not text2: return 0.0
    set1, set2 = set(text1.split()), set(text2.split())
    intersection = len(set1.intersection(set2))
    union = len(set1.union(set2))
    return intersection / union if union != 0 else 0.0

def handle_delete_course(course_id_to_delete):
    with st.spinner("正在删除课程及其所有相关数据..."):
        # 1. Get all homework for the course
        all_hw = get_all_homework()
        course_hws = [hw for hw in all_hw if hw.get('course_id') == course_id_to_delete]

        # 2. Delete submission folders for each homework
        for hw in course_hws:
            submission_folder_path = f"{BASE_ONEDRIVE_PATH}/submissions/{hw['homework_id']}"
            delete_onedrive_item(submission_folder_path)

        # 3. Filter out the homework from the main list
        remaining_hw = [hw for hw in all_hw if hw.get('course_id') != course_id_to_delete]
        save_all_homework(remaining_hw)

        # 4. Filter out the course from the main course list
        all_courses = get_all_courses()
        remaining_courses = [c for c in all_courses if c.get('course_id') != course_id_to_delete]
        save_all_courses(remaining_courses)

        # 5. Clear caches and show success
        st.cache_data.clear()
        st.success("课程及所有相关数据已成功删除。")
        time.sleep(2)

def render_teacher_dashboard(teacher_email):
    teacher_courses = get_teacher_courses(teacher_email)
    if st.session_state.selected_course_id:
        selected_course = next((c for c in teacher_courses if c['course_id'] == st.session_state.selected_course_id), None)
        if selected_course: render_course_management_view(selected_course, teacher_email); return
    
    st.header("教师仪表盘")
    with st.expander("创建新课程"):
        with st.form("create_course_form", clear_on_submit=True):
            course_name = st.text_input("课程名称")
            if st.form_submit_button("创建课程", use_container_width=True):
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
            if st.session_state.confirming_delete_course_id == course['course_id']:
                with st.container(border=True):
                    st.warning(f"**确认删除课程: {course['course_name']}?**")
                    st.error("此操作将永久删除该课程、其所有作业以及所有学生的提交内容。此操作无法撤销。")
                    col1, col2 = st.columns(2)
                    if col1.button("✅ 是的，确认删除", key=f"confirm_del_{course['course_id']}", use_container_width=True):
                        handle_delete_course(course['course_id'])
                        st.session_state.confirming_delete_course_id = None
                        st.rerun()
                    if col2.button("❌ 取消", key=f"cancel_del_{course['course_id']}", use_container_width=True):
                        st.session_state.confirming_delete_course_id = None
                        st.rerun()
            else:
                with st.container(border=True):
                    st.markdown(f"#### {course['course_name']}")
                    st.write(f"邀请码: `{course['join_code']}` | 学生人数: {len(course.get('student_emails', []))}")
                    col1, col2 = st.columns(2)
                    if col1.button("进入管理", key=f"manage_{course['course_id']}", use_container_width=True):
                        st.session_state.selected_course_id = course['course_id']; st.rerun()
                    if col2.button("删除课程", key=f"delete_{course['course_id']}", type="primary", use_container_width=True):
                        st.session_state.confirming_delete_course_id = course['course_id']
                        st.rerun()

def render_course_management_view(course, teacher_email):
    st.header(f"课程管理: {course['course_name']}")
    st.caption(f"课程邀请码: `{course.get('join_code', 'N/A')}`")
    if st.button("返回课程列表", use_container_width=True):
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
                    if st.button("删除此作业", key=f"del_{hw['homework_id']}", type="primary", use_container_width=True):
                        all_hw = get_all_homework()
                        new_hw_list = [h for h in all_hw if h['homework_id'] != hw['homework_id']]
                        if save_all_homework(new_hw_list):
                            # Also delete submission folder for this homework
                            delete_onedrive_item(f"{BASE_ONEDRIVE_PATH}/submissions/{hw['homework_id']}")
                            st.success("作业已删除！"); st.cache_data.clear(); time.sleep(1); st.rerun()
                        else:
                            st.error("删除失败。")
        st.divider()

        st.subheader("用AI生成并发布新作业")
        topic = st.text_input("作业主题", key=f"topic_{course['course_id']}")
        details = st.text_area("具体要求", key=f"details_{course['course_id']}")
        if st.button("AI 生成作业题目", key=f"gen_hw_{course['course_id']}", use_container_width=True):
            if 'editable_homework' in st.session_state: del st.session_state.editable_homework
            if 'generated_homework' in st.session_state: del st.session_state.generated_homework

            if topic and details:
                with st.spinner("AI正在为您生成题目..."):
                    prompt = f"""# 角色: 教学经验丰富的老师.
# 任务: 为课程“{course['course_name']}”创建关于“{topic}”的作业。要求: {details}
# 输出格式要求: 严格遵循以下JSON格式，不含任何解释性文字或Markdown标记.
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
                json_data = json.loads(json_str_raw)
                st.session_state.editable_homework = json_data
            except Exception as e:
                st.error(f"AI返回格式有误，无法编辑: {e}")
                st.code(st.session_state.generated_homework)
            finally:
                if 'generated_homework' in st.session_state: del st.session_state.generated_homework

        if 'editable_homework' in st.session_state:
            with st.form("edit_homework_form"):
                editable_data = st.session_state.editable_homework
                st.text_input("作业标题", value=editable_data.get('title', ''), key=f"edited_title_{course['course_id']}")
                for i, q in enumerate(editable_data.get('questions', [])):
                    st.markdown(f"--- \n#### 第{i+1}题")
                    st.text_area("题目内容", value=q.get('question', ''), key=f"q_text_{i}", height=100)
                    if q.get('type') == 'multiple_choice':
                        st.text_input("选项 (用英文逗号,分隔)", value=", ".join(q.get('options', [])), key=f"q_opts_{i}")
                
                submitted = st.form_submit_button("✅ 确认发布作业", use_container_width=True)
                if submitted:
                    edited_title = st.session_state[f"edited_title_{course['course_id']}"]
                    if edited_title in [hw['title'] for hw in get_course_homework(course['course_id'])]:
                        st.error("本课程中已存在同名作业，请修改标题后发布。")
                    else:
                        final_questions = []
                        for i, q in enumerate(editable_data.get('questions', [])):
                            q_text = st.session_state[f"q_text_{i}"]
                            q_type = q.get('type', 'text')
                            current_q = {'id': q.get('id', f'q_{i}'), 'type': q_type, 'question': q_text}
                            if q_type == 'multiple_choice':
                                opts_str = st.session_state[f"q_opts_{i}"]
                                current_q['options'] = [opt.strip() for opt in opts_str.split(',') if opt.strip()]
                            final_questions.append(current_q)

                        all_hw = get_all_homework()
                        all_hw.append({"homework_id": str(uuid.uuid4()), "course_id": course['course_id'], "title": edited_title, "questions": final_questions})
                        if save_all_homework(all_hw):
                            st.success("作业已成功发布！")
                            del st.session_state.editable_homework
                            st.cache_data.clear(); time.sleep(1); st.rerun()
                        else: st.error("作业发布失败。")
    with tab2:
        st.subheader("学生管理")
        student_list = course.get('student_emails', [])
        if not student_list: st.info("目前还没有学生加入本课程。")
        else:
            for student_email in student_list:
                cols = st.columns([4, 1]); cols[0].write(f"- {student_email}")
                if cols[1].button("移除", key=f"remove_{get_email_hash(student_email)}", type="primary", use_container_width=True):
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
        if not homework_list: st.info("本课程还没有已发布的作业。"); return

        for hw in homework_list:
            with st.expander(f"**{hw['title']}**", expanded=True):
                submissions = get_submissions_for_homework(hw['homework_id'])
                submissions_map = {sub['student_email']: sub for sub in submissions}
                pending_subs = [s for s in submissions if s.get('status') == 'submitted']
                graded_subs_for_remedial = [s for s in submissions if s.get('status') == 'feedback_released' and s.get('final_grade', 100) < 80]

                action_cols = st.columns(2)
                with action_cols[0]:
                    if st.button(f"🤖 一键AI批改并反馈 ({len(pending_subs)}份)", key=f"batch_grade_review_{hw['homework_id']}", disabled=not pending_subs, use_container_width=True):
                        with st.spinner(f"正在一键处理 {len(pending_subs)} 份作业..."):
                            progress_bar = st.progress(0, text="开始处理...")
                            for i, sub in enumerate(pending_subs):
                                progress_bar.progress((i + 1) / len(pending_subs), text=f"处理中: {sub['student_email']}")
                                try:
                                    all_answers = sub.get('answers', {})
                                    text_data_part = f"【题目】: {json.dumps(hw['questions'], ensure_ascii=False)}\n【回答】: {json.dumps(all_answers, ensure_ascii=False)}"
                                    api_prompt_parts = ["""# 角色: 全能教学助手... # 指令: 综合分析所有附件... # 输出格式: 严格JSON...""", text_data_part]
                                    
                                    for q_key, answer_data in all_answers.items():
                                        if answer_data.get('attachments'):
                                            for filename in answer_data['attachments']:
                                                file_path = f"{BASE_ONEDRIVE_PATH}/submissions/{hw['homework_id']}/{get_email_hash(sub['student_email'])}/{filename}"
                                                file_bytes = get_onedrive_data(file_path, is_json=False)
                                                if file_bytes:
                                                    api_prompt_parts.append(f"--- 附件 '{filename}' ---")
                                                    mime_type = get_mime_type(filename)
                                                    if mime_type and mime_type.startswith('image/'):
                                                        api_prompt_parts.append(Image.open(io.BytesIO(file_bytes)))
                                                    elif mime_type:
                                                        api_prompt_parts.append(genai.Part(inline_data=file_bytes, mime_type=mime_type))

                                    ai_result_text = call_gemini_api(api_prompt_parts)
                                    if ai_result_text:
                                        ai_result = json.loads(re.sub(r'```json\s*|\s*```', '', ai_result_text.strip()))
                                        sub.update({
                                            'ai_grade': ai_result.get('overall_grade'), 'ai_feedback': ai_result.get('overall_feedback'),
                                            'ai_detailed_grades': ai_result.get('detailed_grades'), 'status': "feedback_released",
                                            'final_grade': ai_result.get('overall_grade'), 'final_feedback': ai_result.get('overall_feedback', 'AI 自动评语。')
                                        })
                                        save_onedrive_data(f"{BASE_ONEDRIVE_PATH}/submissions/{sub['homework_id']}/{get_email_hash(sub['student_email'])}/submission.json", sub)
                                except Exception as e:
                                    st.toast(f"❌ 处理 {sub['student_email']} 时出错: {e}")
                            
                            st.success("所有作业已处理完毕！"); st.cache_data.clear(); time.sleep(1); st.rerun()

                with action_cols[1]:
                    if 'remedial_report' in st.session_state and st.session_state.remedial_report['homework_id'] == hw['homework_id']:
                        with st.container(border=True):
                            st.markdown("#### **补习作业生成报告**")
                            success = st.session_state.remedial_report['success']
                            failed = st.session_state.remedial_report['failed']
                            if success: st.success(f"**成功 {len(success)} 份:**\n" + "\n".join([f"- {s}" for s in success]))
                            if failed: st.error(f"**失败 {len(failed)} 份:**\n" + "\n".join([f"- {s}: *{r}*" for s, r in failed.items()]))
                            if st.button("关闭报告", key=f"close_report_{hw['homework_id']}"):
                                del st.session_state.remedial_report; st.rerun()
                    else:
                        if st.button(f"📚 一键生成补习作业 ({len(graded_subs_for_remedial)}份)", key=f"batch_remedial_{hw['homework_id']}", disabled=not graded_subs_for_remedial, use_container_width=True):
                            with st.spinner(f"正在为 {len(graded_subs_for_remedial)} 名学生生成作业..."):
                                all_hw, new_hw, success_list, failed_dict = get_all_homework(), [], [], {}
                                for sub in graded_subs_for_remedial:
                                    try:
                                        student_email = sub['student_email']
                                        score_per_q = 100 / len(hw['questions'])
                                        weak_points = [
                                            {"question": hw['questions'][g['question_index']]['question'], "answer": sub['answers'].get(hw['questions'][g['question_index']]['id'], {}).get('text'), "feedback": g.get('feedback')}
                                            for g in sub.get('ai_detailed_grades', []) if g.get('grade', 0) < score_per_q
                                        ]
                                        if not weak_points: continue
                                        prompt = f"""# 角色: 个性化辅导老师. # 任务: 根据学生薄弱点创建新的补习作业. # 薄弱点: {json.dumps(weak_points, ensure_ascii=False)} # 要求: 1-2道新题, 严格JSON输出.
{{
"title": "个性化补习 - {hw['title']}", "questions": [{{"id": "remedial_q0", "type": "text", "question": "这里是新的补习题目..."}}]
}}"""
                                        ai_response = call_gemini_api(prompt)
                                        if not ai_response: failed_dict[student_email] = "AI未返回内容"; continue
                                        new_hw_data = json.loads(re.sub(r'```json\s*|\s*```', '', ai_response.strip()))
                                        new_hw_data.update({"homework_id": str(uuid.uuid4()), "course_id": course['course_id'], "student_email": student_email, "original_hw_id": hw['homework_id']})
                                        new_hw.append(new_hw_data); success_list.append(student_email)
                                    except Exception as e: failed_dict[student_email] = f"出错: {e}"
                                if new_hw: save_all_homework(all_hw + new_hw)
                                st.session_state.remedial_report = {'homework_id': hw['homework_id'], 'success': success_list, 'failed': failed_dict}
                                st.cache_data.clear(); st.rerun()

                if st.button("导出成绩 (CSV)", key=f"export_{hw['homework_id']}", use_container_width=True):
                    student_profiles = get_student_profiles_for_course(tuple(course.get('student_emails', [])))
                    grades_data = [{"学号": student_profiles.get(email, {}).get('student_id', 'N/A'), "姓名": student_profiles.get(email, {}).get('name', email), "分数": submissions_map.get(email, {}).get('final_grade', 'N/A')} for email in course.get('student_emails', [])]
                    df = pd.DataFrame(grades_data)
                    st.download_button(label="点击下载", data=df.to_csv(index=False).encode('utf-8-sig'), file_name=f"{hw['title']}_grades.csv", mime='text/csv')
                
                st.divider()
                student_profiles = get_student_profiles_for_course(tuple(course.get('student_emails', [])))
                for student_email in course.get('student_emails', []):
                    profile = student_profiles.get(student_email, {})
                    sub = submissions_map.get(student_email)
                    cols = st.columns([3, 2, 2, 3])
                    cols[0].write(f"{profile.get('name') or student_email} ({profile.get('class_name', 'N/A')} - {profile.get('student_id', 'N/A')})")
                    if sub:
                        status = sub.get("status", "submitted")
                        if status == "submitted": cols[1].info("已提交"); cols[2].button("批改", key=f"grade_{sub['submission_id']}", on_click=lambda s=sub: st.session_state.update(grading_submission=s))
                        elif status == "feedback_released":
                            cols[1].success("已反馈"); cols[2].metric("得分", sub.get('final_grade', 'N/A'))
                            if cols[3].button("编辑", key=f"edit_{sub['submission_id']}"): 
                                st.session_state.grading_submission = sub
                                if sub.get('ai_detailed_grades'): st.session_state.ai_grade_result = {"overall_grade": sub.get('ai_grade'), "overall_feedback": sub.get('ai_feedback'), "detailed_grades": sub.get('ai_detailed_grades')}
                                st.rerun()
                    else: cols[1].error("未提交")

    with tab4:
        st.subheader("📊 班级学情分析")
        homework_list = get_course_homework(course['course_id'])
        if not homework_list: st.info("本课程还没有已发布的作业，无法进行分析。")
        else:
            hw_options = {hw['title']: hw['homework_id'] for hw in homework_list}
            selected_hw_title = st.selectbox("请选择要分析的作业", options=list(hw_options.keys()))
            if st.button("开始分析", key=f"analyze_{hw_options[selected_hw_title]}", use_container_width=True):
                with st.spinner("AI正在汇总分析全班的作业情况..."):
                    homework = get_homework(hw_options[selected_hw_title])
                    submissions = get_submissions_for_homework(hw_options[selected_hw_title])
                    graded_submissions = [s for s in submissions if s.get('status') == 'feedback_released']
                    if len(graded_submissions) < 2: st.warning("已批改的提交人数过少，无法进行有意义的分析。")
                    else:
                        summary = [{"grade": s['final_grade'], "details": s.get('ai_detailed_grades', [])} for s in graded_submissions]
                        prompt = f"""# 角色: 教育数据分析专家. # 数据: 作业题目: {json.dumps(homework['questions'], ensure_ascii=False)}, 全班匿名批改数据: {json.dumps(summary, ensure_ascii=False)}. # 任务: 生成详细的学情分析报告，包含: 1. 总体表现总结 (平均/最高/最低分, 分数段分布). 2. 知识点掌握情况 (逐题得分率, 优劣势分析). 3. 典型错误分析. 4. 教学建议."""
                        analysis_report = call_gemini_api(prompt)
                        if analysis_report: st.markdown("### 学情分析报告\n" + analysis_report)
                        else: st.error("无法生成学情分析报告。")

def render_student_dashboard(student_email, user_profile):
    st.header("学生仪表盘")
    tab1, tab2, tab3 = st.tabs(["我的课程", "加入新课程", "个人信息"])
    with tab2:
        with st.form("join_course_form", clear_on_submit=True):
            join_code = st.text_input("请输入课程邀请码").upper()
            if st.form_submit_button("加入课程", use_container_width=True):
                if not join_code: st.warning("请输入邀请码。")
                else:
                    all_courses = get_all_courses()
                    target_course = next((c for c in all_courses if c.get('join_code') == join_code), None)
                    if not target_course: st.error("邀请码无效。")
                    elif student_email in target_course.get('student_emails', []): st.info("您已经加入此课程。")
                    else:
                        target_course.setdefault('student_emails', []).append(student_email)
                        if save_all_courses(all_courses): st.success(f"成功加入课程 '{target_course['course_name']}'！"); st.cache_data.clear(); st.rerun()
                        else: st.error("加入课程失败。")
    with tab1:
        st.subheader("我加入的课程")
        my_courses = get_student_courses(student_email)
        if not my_courses: st.info("您还没有加入任何课程。"); return
        for course in my_courses:
            with st.expander(f"**{course['course_name']}**", expanded=True):
                all_hw = get_course_homework(course['course_id'])
                student_hw = [hw for hw in all_hw if 'student_email' not in hw or hw.get('student_email') == student_email]
                if not student_hw: st.write("这门课还没有发布任何作业。")
                else:
                    for hw in student_hw:
                        submission = get_student_submission(hw['homework_id'], student_email)
                        cols = st.columns([3,2,2])
                        cols[0].write(f"{hw['title']}")
                        if submission:
                            if submission.get('status') == 'feedback_released':
                                cols[1].success(f"已批改: {submission.get('final_grade', 'N/A')}/100")
                                if cols[2].button("查看结果", key=f"view_{hw['homework_id']}"): st.session_state.viewing_homework_id = hw['homework_id']; st.rerun()
                            else: cols[1].info("已提交"); cols[2].write("待批改")
                        else:
                            cols[1].warning("待完成")
                            if cols[2].button("开始作业", key=f"do_{hw['homework_id']}"): st.session_state.viewing_homework_id = hw['homework_id']; st.rerun()
    with tab3:
        st.subheader("个人信息设置")
        if user_profile:
            with st.form("profile_form"):
                name = st.text_input("姓名", value=user_profile.get("name", ""))
                class_name = st.text_input("班级", value=user_profile.get("class_name", ""))
                student_id = st.text_input("学号", value=user_profile.get("student_id", ""))
                if st.form_submit_button("保存信息", use_container_width=True):
                    user_profile.update(name=name, class_name=class_name, student_id=student_id)
                    if save_user_profile(student_email, user_profile): st.success("个人信息已更新！"); st.cache_data.clear(); time.sleep(1); st.rerun()
                    else: st.error("保存失败。")

def render_homework_submission_view(homework, student_email):
    st.header(f"作业: {homework['title']}")
    if st.button("返回课程列表"): st.session_state.viewing_homework_id = None; st.rerun()
    
    with st.form("submission_form"):
        for i, q in enumerate(homework['questions']):
            q_key = q.get('id', f'q_{i}'); st.divider(); st.subheader(f"第{i+1}题"); st.write(q['question'])
            if q.get('type') == 'multiple_choice': st.radio("选择", q['options'], key=f"mc_{q_key}", horizontal=True)
            else: 
                st.text_area("回答", key=f"text_{q_key}", height=150)
                st.file_uploader("添加附件", accept_multiple_files=True, type=ALL_SUPPORTED_EXTENSIONS, key=f"files_{q_key}", help=f"支持格式: {', '.join(ALL_SUPPORTED_EXTENSIONS)}")

        if st.form_submit_button("确认提交", use_container_width=True):
            with st.spinner("正在提交..."):
                final_answers, processed_files = {}, {}
                for i, q in enumerate(homework['questions']):
                    q_key = q.get('id', f'q_{i}')
                    if q.get('type') == 'multiple_choice': final_answers[q_key] = {"text": st.session_state[f"mc_{q_key}"], "attachments": []}
                    else:
                        attachments = []
                        for uploaded_file in st.session_state[f"files_{q_key}"]:
                            safe_name = f"{q_key}_{uuid.uuid4().hex}.{uploaded_file.name.split('.')[-1]}"
                            attachments.append(safe_name); processed_files[safe_name] = uploaded_file.getvalue()
                        final_answers[q_key] = {"text": st.session_state[f"text_{q_key}"], "attachments": attachments}
                
                prefix = f"{BASE_ONEDRIVE_PATH}/submissions/{homework['homework_id']}/{get_email_hash(student_email)}"
                for filename, filebytes in processed_files.items(): save_onedrive_data(f"{prefix}/{filename}", filebytes, is_json=False)
                submission_data = {"submission_id": str(uuid.uuid4()), "homework_id": homework['homework_id'], "student_email": student_email, "answers": final_answers, "status": "submitted", "timestamp": datetime.utcnow().isoformat() + "Z"}
                if save_onedrive_data(f"{prefix}/submission.json", submission_data):
                    st.success("提交成功！"); st.cache_data.clear(); time.sleep(2); st.session_state.viewing_homework_id = None; st.rerun()
                else: st.error("提交失败。")

def render_attachment(file_path, file_name):
    ext = file_name.split('.')[-1].lower()
    with st.spinner(f"加载中: {file_name}..."):
        file_bytes = get_onedrive_data(file_path, is_json=False)
        if not file_bytes: st.error(f"无法加载: {file_name}"); return
        try:
            if ext in SUPPORTED_FILE_TYPES['image']: st.image(file_bytes, caption=file_name)
            elif ext in SUPPORTED_FILE_TYPES['audio']: st.audio(file_bytes, format=f'audio/{ext}')
            elif ext in SUPPORTED_FILE_TYPES['video']: st.video(file_bytes, format=f'video/{ext}')
            else: st.download_button(f"下载附件: {file_name}", file_bytes, file_name, use_container_width=True)
        except Exception as e:
            st.error(f"渲染附件 {file_name} 出错: {e}"); st.download_button(f"下载: {file_name}", file_bytes, file_name, use_container_width=True)

def render_student_graded_view(submission, homework):
    st.header(f"作业结果: {homework['title']}")
    if st.button("返回课程列表"): st.session_state.viewing_homework_id = None; st.rerun()

    st.metric("最终得分", f"{submission.get('final_grade', 'N/A')} / 100")
    st.info(f"**总评:** {submission.get('final_feedback', '无')}"); st.divider()
    st.subheader("我的提交与AI反馈")
    all_answers = submission.get('answers', {})
    grades_map = {g['question_index']: g for g in submission.get('ai_detailed_grades', [])}
    for i, q in enumerate(homework['questions']):
        q_key = q.get('id', f'q_{i}'); answer_data = all_answers.get(q_key)
        with st.container(border=True):
            st.write(f"**题目 {i + 1}:** {q['question']}")
            if answer_data:
                st.info(f"**我的回答:**\n\n{answer_data.get('text', '无')}")
                for filename in answer_data.get('attachments', []):
                    render_attachment(f"{BASE_ONEDRIVE_PATH}/submissions/{homework['homework_id']}/{get_email_hash(submission['student_email'])}/{filename}", filename)
            else: st.info("未回答此题")
            ai_feedback = grades_map.get(i)
            if ai_feedback:
                st.warning(f"**AI反馈:** {ai_feedback.get('feedback', '无')}")
                st.info(f"**AI建议得分:** {ai_feedback.get('grade', 'N/A')}")

def render_teacher_grading_view(submission, homework):
    st.header("作业批改")
    if st.button("返回成绩册"): st.session_state.grading_submission = None; st.session_state.ai_grade_result = None; st.rerun()

    st.subheader(f"学生: {submission['student_email']}")
    if st.button("🤖 AI自动批改", key=f"ai_grade_{submission['submission_id']}", use_container_width=True):
        with st.spinner("AI分析中..."):
            all_answers = submission.get('answers', {})
            text_part = f"【题目】:{json.dumps(homework['questions'], ensure_ascii=False)}\n【回答】:{json.dumps(all_answers, ensure_ascii=False)}"
            prompt_parts = ["""# 角色: 全能教学助手... # 指令: 综合分析所有附件... # 输出格式: 严格JSON...""", text_part]
            for q_key, answer_data in all_answers.items():
                for filename in answer_data.get('attachments', []):
                    file_path = f"{BASE_ONEDRIVE_PATH}/submissions/{homework['homework_id']}/{get_email_hash(submission['student_email'])}/{filename}"
                    file_bytes = get_onedrive_data(file_path, is_json=False)
                    if file_bytes:
                        prompt_parts.append(f"--- 附件 '{filename}' ---")
                        mime_type = get_mime_type(filename)
                        if mime_type and mime_type.startswith('image/'): prompt_parts.append(Image.open(io.BytesIO(file_bytes)))
                        elif mime_type: prompt_parts.append(genai.Part(inline_data=file_bytes, mime_type=mime_type))
            ai_result_text = call_gemini_api(prompt_parts)
            if ai_result_text:
                try: st.session_state.ai_grade_result = json.loads(re.sub(r'```json\s*|\s*```', '', ai_result_text.strip())); st.rerun()
                except Exception as e: st.error(f"AI返回格式错误: {e}"); st.code(ai_result_text)
            else: st.error("AI调用失败。")
    
    st.divider(); st.subheader("学生提交及AI建议")
    all_answers = submission.get('answers', {})
    ai_result = st.session_state.get('ai_grade_result') or ({"overall_grade": s.get('ai_grade'), "overall_feedback": s.get('ai_feedback'), "detailed_grades": s.get('ai_detailed_grades')} if submission.get('ai_detailed_grades') else {})
    grades_map = {g['question_index']: g for g in ai_result.get('detailed_grades', [])} if ai_result else {}
    for i, q in enumerate(homework['questions']):
        answer_data = all_answers.get(q.get('id', f'q_{i}'))
        with st.container(border=True):
            st.write(f"**题目 {i + 1}:** {q['question']}")
            if answer_data:
                st.info(f"**回答:** {answer_data.get('text', '无')}")
                for filename in answer_data.get('attachments', []):
                    render_attachment(f"{BASE_ONEDRIVE_PATH}/submissions/{homework['homework_id']}/{get_email_hash(submission['student_email'])}/{filename}", filename)
            else: st.info("未回答")
            ai_feedback = grades_map.get(i)
            if ai_feedback: st.warning(f"**AI反馈:** {ai_feedback.get('feedback', '无')}\n**建议得分:** {ai_feedback.get('grade', 'N/A')}")
    
    st.divider(); st.subheader("教师最终审核")
    initial_grade = submission.get('final_grade', ai_result.get('overall_grade', 0))
    initial_feedback = submission.get('final_feedback', ai_result.get('overall_feedback', ""))
    final_grade = st.number_input("最终得分", 0, 100, int(float(initial_grade or 0)), key=f"final_grade_{submission['submission_id']}")
    final_feedback = st.text_area("最终评语", initial_feedback, height=200, key=f"final_feedback_{submission['submission_id']}")
    button_text = "✅ 更新并反馈" if submission.get('status') == 'feedback_released' else "✅ 确认并反馈"
    if st.button(button_text, type="primary", use_container_width=True):
        submission.update(status="feedback_released", final_grade=final_grade, final_feedback=final_feedback)
        if ai_result: submission.update(ai_grade=ai_result.get('overall_grade'), ai_feedback=ai_result.get('overall_feedback'), ai_detailed_grades=ai_result.get('detailed_grades'))
        if save_onedrive_data(f"{BASE_ONEDRIVE_PATH}/submissions/{submission['homework_id']}/{get_email_hash(submission['student_email'])}/submission.json", submission):
            st.success("反馈成功！"); st.session_state.grading_submission = None; st.session_state.ai_grade_result = None; st.cache_data.clear(); time.sleep(1); st.rerun()
        else: st.error("反馈失败。")

# --- 主程序 ---
st.title("📚 在线作业平台 (Gemini 2.5 Flash 驱动)")
check_session_from_query_params()
if not st.session_state.get('logged_in'):
    display_login_form()
    st.info("👈 请在左侧侧边栏使用您的邮箱登录或注册。")
else:
    user_email = st.session_state.user_email
    with st.sidebar:
        st.success(f"欢迎, {user_email}")
        if st.button("退出登录", use_container_width=True):
            for key in list(st.session_state.keys()): del st.session_state[key]
            st.query_params.clear(); st.rerun()

    user_profile = get_user_profile(user_email)
    if not user_profile: st.error("无法加载您的用户配置，请尝试重新登录。")
    elif 'role' not in user_profile:
        st.subheader("请选择您的身份")
        col1, col2 = st.columns(2)
        if col1.button("我是老师", use_container_width=True):
            user_profile['role'] = 'teacher'; save_user_profile(user_email, user_profile); st.rerun()
        if col2.button("我是学生", use_container_width=True):
            user_profile['role'] = 'student'; save_user_profile(user_email, user_profile); st.rerun()
    else:
        user_role = user_profile['role']
        if st.session_state.grading_submission:
            homework = get_homework(st.session_state.grading_submission['homework_id'])
            if homework: render_teacher_grading_view(st.session_state.grading_submission, homework)
        elif st.session_state.viewing_homework_id:
            homework = get_homework(st.session_state.viewing_homework_id)
            if homework:
                submission = get_student_submission(homework['homework_id'], user_email)
                if submission and submission.get('status') == 'feedback_released':
                    render_student_graded_view(submission, homework)
                else: render_homework_submission_view(homework, user_email)
        elif user_role == 'teacher': render_teacher_dashboard(user_email)
        elif user_role == 'student': render_student_dashboard(user_email, user_profile)

