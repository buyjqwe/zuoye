import streamlit as st
import requests
import re
import random
import time
import json
import hashlib
import secrets
from datetime import datetime
import uuid
import google.generativeai as genai # 使用官方SDK

# --- 页面基础设置 ---
st.set_page_config(page_title="在线作业平台", page_icon="📚", layout="centered")

# --- 全局常量 ---
BASE_ONEDRIVE_PATH = "root:/Apps/HomeworkPlatform"

# --- 初始化 Session State ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'user_email' not in st.session_state: st.session_state.user_email = ""
if 'login_step' not in st.session_state: st.session_state.login_step = "enter_email"
if 'selected_course_id' not in st.session_state: st.session_state.selected_course_id = None

# --- API 配置 ---
MS_GRAPH_CONFIG = st.secrets["microsoft_graph"]
# --- Gemini SDK 配置 ---
try:
    genai.configure(api_key=st.secrets["gemini_api"]["api_key"])
    MODEL = genai.GenerativeModel('gemini-1.5-flash-latest')
    SAFETY_SETTINGS = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]
except Exception as e:
    st.error(f"Gemini API密钥配置失败: {e}")


# --- 核心功能函数定义 ---

def get_email_hash(email): 
    return hashlib.sha256(email.lower().encode('utf-8')).hexdigest()

@st.cache_data(ttl=3500)
def get_ms_graph_token():
    url = f"https://login.microsoftonline.com/{MS_GRAPH_CONFIG['tenant_id']}/oauth2/v2.0/token"
    data = {"grant_type": "client_credentials", "client_id": MS_GRAPH_CONFIG['client_id'], "client_secret": MS_GRAPH_CONFIG['client_secret'], "scope": "https://graph.microsoft.com/.default"}
    resp = requests.post(url, data=data); resp.raise_for_status(); return resp.json()["access_token"]

def onedrive_api_request(method, path, headers, data=None, params=None):
    base_url = f"https://graph.microsoft.com/v1.0/users/{MS_GRAPH_CONFIG['sender_email']}/drive"
    url = f"{base_url}/{path}"
    if method.lower() == 'get': return requests.get(url, headers=headers, params=params, timeout=15)
    if method.lower() == 'put': return requests.put(url, headers=headers, data=data, timeout=15)
    return None

def get_onedrive_data(path):
    try:
        token = get_ms_graph_token(); headers = {"Authorization": f"Bearer {token}"}
        resp = onedrive_api_request('get', f"{path}:/content", headers)
        if resp.status_code == 404: return None
        resp.raise_for_status(); return resp.json()
    except Exception as e:
        if "404" not in str(e): st.error(f"从 OneDrive 加载数据失败 ({path}): {e}")
        return None

def save_onedrive_data(path, data):
    try:
        token = get_ms_graph_token(); headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        json_data = json.dumps(data, indent=2, ensure_ascii=False)
        onedrive_api_request('put', f"{path}:/content", headers, data=json_data.encode('utf-8'))
        return True
    except Exception as e: st.error(f"保存数据到 OneDrive 失败 ({path}): {e}"); return False

def get_user_profile(email): return get_onedrive_data(f"{BASE_ONEDRIVE_PATH}/users/{get_email_hash(email)}.json")
def save_user_profile(email, data): return save_onedrive_data(f"{BASE_ONEDRIVE_PATH}/users/{get_email_hash(email)}.json", data)
def get_global_data(file_name): data = get_onedrive_data(f"{BASE_ONEDRIVE_PATH}/{file_name}.json"); return data if data else {}
def save_global_data(file_name, data): return save_onedrive_data(f"{BASE_ONEDRIVE_PATH}/{file_name}.json", data)

def send_verification_code(email, code):
    try:
        token = get_ms_graph_token(); url = f"https://graph.microsoft.com/v1.0/users/{MS_GRAPH_CONFIG['sender_email']}/sendMail"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {"message": {"subject": f"[{code}] 您的登录验证码", "body": {"contentType": "Text", "content": f"您在在线作业平台的验证码是：{code}，5分钟内有效。"}, "toRecipients": [{"emailAddress": {"address": email}}]}, "saveToSentItems": "true"}
        requests.post(url, headers=headers, json=payload, timeout=10).raise_for_status(); return True
    except Exception as e: st.error(f"邮件发送失败: {e}"); return False

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
        st.session_state.logged_in, st.session_state.user_email, st.session_state.login_step, st.query_params["session_token"] = True, email, "logged_in", token
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

def call_gemini_api(prompt):
    """使用 Gemini SDK 调用 API"""
    try:
        response = MODEL.generate_content(prompt, safety_settings=SAFETY_SETTINGS)
        return response.text
    except Exception as e:
        st.error(f"调用AI时出错: {e}")
        return None

@st.cache_data(ttl=600)
def get_teacher_courses(teacher_email):
    courses = []
    try:
        token = get_ms_graph_token(); headers = {"Authorization": f"Bearer {token}"}
        path = f"{BASE_ONEDRIVE_PATH}/courses:/children"
        response = onedrive_api_request('get', path, headers)
        if response.status_code == 404: return []
        response.raise_for_status()
        files = response.json().get('value', [])
        for file in files:
            file_path = f"{BASE_ONEDRIVE_PATH}/courses/{file['name']}"
            course_data = get_onedrive_data(file_path)
            if course_data and course_data.get('teacher_email') == teacher_email:
                courses.append(course_data)
    except Exception: return []
    return courses

def render_course_management_view(course, teacher_email):
    st.header(f"课程管理: {course['course_name']}")
    st.info(f"学生加入代码: **{course['join_code']}**")
    if st.button("返回课程列表"):
        st.session_state.selected_course_id = None; st.rerun()

    tab1, tab2, tab3 = st.tabs(["作业管理", "学生管理", "成绩册"])
    with tab1:
        st.subheader("用AI生成并发布作业")
        topic = st.text_input("作业主题", key=f"topic_{course['course_id']}")
        details = st.text_area("具体要求", key=f"details_{course['course_id']}")
        if st.button("AI 生成作业题目", key=f"gen_hw_{course['course_id']}"):
            if topic and details:
                with st.spinner("AI正在为您生成题目..."):
                    prompt = f"""你是一位教学经验丰富的老师。请为课程 '{course['course_name']}' 生成一份关于 '{topic}' 的作业。具体要求是: {details}。请严格按照以下JSON格式输出，不要有任何额外的解释文字：
                    {{ "title": "{topic} - 单元作业", "questions": [ {{"type": "text", "question": "请在这里生成第一个问题"}}, {{"type": "multiple_choice", "question": "请在这里生成第二个问题", "options": ["选项A", "选项B", "选项C", "选项D"]}} ] }}"""
                    response_text = call_gemini_api(prompt)
                    if response_text:
                        st.session_state.generated_homework = response_text
                        st.success("作业已生成！请在下方预览和发布。")
            else: st.warning("请输入作业主题和具体要求。")

        if 'generated_homework' in st.session_state:
            st.subheader("作业预览与发布")
            try:
                json_str = st.session_state.generated_homework.strip().replace("```json", "").replace("```", "")
                homework_data = json.loads(json_str)
                with st.container(border=True):
                    st.write(f"**标题:** {homework_data['title']}")
                    for i, q in enumerate(homework_data['questions']):
                        st.write(f"**第{i+1}题 ({'简答题' if q['type'] == 'text' else '选择题'}):** {q['question']}")
                        if q['type'] == 'multiple_choice': st.write(f"   选项: {', '.join(q['options'])}")
                
                if st.button("确认发布", key=f"pub_hw_{course['course_id']}"):
                    homework_id = str(uuid.uuid4())
                    homework_to_save = {"homework_id": homework_id, "course_id": course['course_id'], "title": homework_data['title'], "questions": homework_data['questions']}
                    path = f"{BASE_ONEDRIVE_PATH}/homework/{homework_id}.json"
                    if save_onedrive_data(path, homework_to_save):
                        st.success(f"作业已成功发布到本课程！"); del st.session_state.generated_homework; st.rerun()
                    else: st.error("作业发布失败，请稍后重试。")
            except Exception as e:
                st.error(f"AI返回的格式有误，无法解析。请尝试重新生成。错误: {e}"); st.code(st.session_state.generated_homework)

    with tab2: st.subheader("学生管理 (开发中)"); st.write("这里将显示所有已加入本课程的学生名单。")
    with tab3: st.subheader("成绩册 (开发中)"); st.write("这里将显示本课程所有作业的提交情况和学生成绩。")

def render_teacher_dashboard(teacher_email):
    teacher_courses = get_teacher_courses(teacher_email)
    
    if st.session_state.selected_course_id:
        selected_course = next((c for c in teacher_courses if c['course_id'] == st.session_state.selected_course_id), None)
        if selected_course: render_course_management_view(selected_course, teacher_email); return

    st.header("教师仪表盘")
    with st.expander("创建新课程", expanded=False):
        with st.form("create_course_form", clear_on_submit=True):
            course_name = st.text_input("课程名称")
            if st.form_submit_button("创建课程"):
                if course_name.strip():
                    course_id, join_code = str(uuid.uuid4()), secrets.token_hex(3).upper()
                    course_data = {"course_id": course_id, "course_name": course_name, "teacher_email": teacher_email, "join_code": join_code, "student_emails": []}
                    path = f"{BASE_ONEDRIVE_PATH}/courses/{course_id}.json"
                    if save_onedrive_data(path, course_data):
                        st.success(f"课程 '{course_name}' 创建成功！加入代码: **{join_code}**"); st.cache_data.clear()
                    else: st.error("课程创建失败。")

    st.subheader("我的课程")
    if not teacher_courses:
        st.info("您还没有创建任何课程。请在上方创建您的第一门课程。")
    else:
        course_names = [course['course_name'] for course in teacher_courses]
        selected_course_name = st.selectbox("选择一门课程进行管理", options=course_names)
        if st.button("进入课程管理"):
            selected_course = next((c for c in teacher_courses if c['course_name'] == selected_course_name), None)
            if selected_course: st.session_state.selected_course_id = selected_course['course_id']; st.rerun()

def render_student_dashboard(student_email):
    st.header("学生仪表盘")
    st.write("您已作为学生登录。后续我们将在这里实现加入课程、完成和提交作业等功能。")

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
            st.session_state.selected_course_id = None
            token_to_remove = st.query_params.get("session_token")
            if token_to_remove:
                sessions = get_global_data("sessions")
                if token_to_remove in sessions: del sessions[token_to_remove]; save_global_data("sessions", sessions)
            for key in list(st.session_state.keys()): del st.session_state[key]
            st.query_params.clear(); st.rerun()

    user_profile = get_user_profile(user_email)

    if not user_profile:
        st.error("无法加载您的用户配置，请尝试重新登录。")
    elif 'role' not in user_profile:
        st.subheader("首次登录：请选择您的身份")
        st.info("这个选择是永久性的，之后将无法更改。")
        col1, col2 = st.columns(2)
        if col1.button("我是教师 👩‍🏫", use_container_width=True, type="primary"):
            user_profile['role'] = 'teacher'
            if save_user_profile(user_email, user_profile):
                st.balloons(); st.success("身份已确认为【教师】！页面将在2秒后刷新..."); time.sleep(2); st.rerun()
            else: st.error("身份设置失败。")
        if col2.button("我是学生 👨‍🎓", use_container_width=True, type="primary"):
            user_profile['role'] = 'student'
            if save_user_profile(user_email, user_profile):
                st.balloons(); st.success("身份已确认为【学生】！页面将在2秒后刷新..."); time.sleep(2); st.rerun()
            else: st.error("身份设置失败。")
    else:
        user_role = user_profile['role']
        if user_role == 'teacher':
            render_teacher_dashboard(user_email)
        elif user_role == 'student':
            render_student_dashboard(student_email)
