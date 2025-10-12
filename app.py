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

# --- 页面基础设置 ---
st.set_page_config(page_title="在线作业平台", page_icon="📚", layout="centered")

# --- 全局常量 ---
BASE_ONEDRIVE_PATH = "root:/Apps/HomeworkPlatform"

# --- 初始化 Session State ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'user_email' not in st.session_state: st.session_state.user_email = ""
if 'login_step' not in st.session_state: st.session_state.login_step = "enter_email"
if 'selected_course_id' not in st.session_state: st.session_state.selected_course_id = None
if 'viewing_homework_id' not in st.session_state: st.session_state.viewing_homework_id = None
if 'grading_submission' not in st.session_state: st.session_state.grading_submission = None

# --- API 配置 ---
MS_GRAPH_CONFIG = st.secrets["microsoft_graph"]
try:
    genai.configure(api_key=st.secrets["gemini_api"]["api_key"])
    MODEL = genai.GenerativeModel('gemini-1.5-flash')
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
    if method.lower() == 'get': return requests.get(url, headers=headers, params=params, timeout=15)
    if method.lower() == 'put': return requests.put(url, headers=headers, data=data, timeout=15)
    if method.lower() == 'delete': return requests.delete(url, headers=headers, timeout=15)
    return None

def get_onedrive_data(path):
    try:
        token = get_ms_graph_token(); headers = {"Authorization": f"Bearer {token}"}
        resp = onedrive_api_request('get', f"{path}:/content", headers)
        if resp.status_code == 404: return None
        resp.raise_for_status(); return resp.json()
    except Exception: return None

def save_onedrive_data(path, data):
    try:
        token = get_ms_graph_token(); headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        json_data = json.dumps(data, indent=2, ensure_ascii=False)
        onedrive_api_request('put', f"{path}:/content", headers, data=json_data.encode('utf-8'))
        return True
    except Exception: return False

def delete_onedrive_file(path):
    try:
        token = get_ms_graph_token(); headers = {"Authorization": f"Bearer {token}"}
        response = onedrive_api_request('delete', path, headers); response.raise_for_status(); return True
    except Exception: return False

def get_user_profile(email): return get_onedrive_data(f"{BASE_ONEDRIVE_PATH}/users/{get_email_hash(email)}.json")
def save_user_profile(email, data): return save_onedrive_data(f"{BASE_ONEDRIVE_PATH}/users/{get_email_hash(email)}.json", data)
def get_global_data(file_name): data = get_onedrive_data(f"{BASE_ONEDRIVE_PATH}/{file_name}.json"); return data if data else {}
def save_global_data(file_name, data): return save_onedrive_data(f"{BASE_ONEDRIVE_PATH}/{file_name}.json", data)

def send_verification_code(email, code): return True
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
    try:
        response = MODEL.generate_content(prompt, safety_settings=SAFETY_SETTINGS)
        return response.text
    except Exception as e:
        st.error(f"调用AI时出错: {e}")
        return None

@st.cache_data(ttl=60)
def get_all_courses():
    all_courses = []
    try:
        token = get_ms_graph_token(); headers = {"Authorization": f"Bearer {token}"}
        path = f"{BASE_ONEDRIVE_PATH}/courses:/children"
        response = onedrive_api_request('get', path, headers)
        if response.status_code == 404: return []
        response.raise_for_status()
        files = response.json().get('value', [])
        for file in files:
            course_data = get_onedrive_data(f"{BASE_ONEDRIVE_PATH}/courses/{file['name']}")
            if course_data: all_courses.append(course_data)
    except Exception: return []
    return all_courses

def get_teacher_courses(teacher_email): return [c for c in get_all_courses() if c.get('teacher_email') == teacher_email]
def get_student_courses(student_email): return [c for c in get_all_courses() if student_email in c.get('student_emails', [])]

@st.cache_data(ttl=60)
def get_course_homework(course_id):
    homework_list = []
    try:
        token = get_ms_graph_token(); headers = {"Authorization": f"Bearer {token}"}
        path = f"{BASE_ONEDRIVE_PATH}/homework:/children"
        response = onedrive_api_request('get', path, headers)
        if response.status_code == 404: return []
        response.raise_for_status()
        files = response.json().get('value', [])
        for file in files:
            homework_data = get_onedrive_data(f"{BASE_ONEDRIVE_PATH}/homework/{file['name']}")
            if homework_data and homework_data.get('course_id') == course_id:
                homework_list.append(homework_data)
    except Exception: return []
    return homework_list

@st.cache_data(ttl=30)
def get_homework(homework_id):
    return get_onedrive_data(f"{BASE_ONEDRIVE_PATH}/homework/{homework_id}.json")

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
                    course_id, join_code = str(uuid.uuid4()), secrets.token_hex(3).upper()
                    course_data = {"course_id": course_id, "course_name": course_name, "teacher_email": teacher_email, "join_code": join_code, "student_emails": []}
                    path = f"{BASE_ONEDRIVE_PATH}/courses/{course_id}.json"
                    if save_onedrive_data(path, course_data):
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
                    st.session_state.selected_course_id = course['course_id']
                    st.rerun()

def render_course_management_view(course, teacher_email):
    st.header(f"课程管理: {course['course_name']}")
    if st.button("返回课程列表"):
        st.session_state.selected_course_id = None; st.rerun()

    tab1, tab2, tab3 = st.tabs(["作业管理", "学生管理", "成绩册"])
    with tab1:
        # ... (作业管理功能, 与上一版相同)
        pass
    with tab2: 
        st.subheader("学生管理")
        student_list = course.get('student_emails', [])
        if not student_list:
            st.info("目前还没有学生加入本课程。")
        else:
            for student_email in student_list:
                cols = st.columns([4, 1])
                cols[0].write(student_email)
                if cols[1].button("移除", key=f"remove_{get_email_hash(student_email)}", type="primary"):
                    course['student_emails'].remove(student_email)
                    path = f"{BASE_ONEDRIVE_PATH}/courses/{course['course_id']}.json"
                    if save_onedrive_data(path, course):
                        st.success(f"已将 {student_email} 移出课程。"); st.cache_data.clear(); time.sleep(1); st.rerun()
                    else:
                        st.error("操作失败。")

    with tab3:
        st.subheader("成绩册")
        homework_list = get_course_homework(course['course_id'])
        if not homework_list:
            st.info("本课程还没有已发布的作业。"); return
        
        for hw in homework_list:
            with st.expander(f"**{hw['title']}**"):
                submissions = get_submissions_for_homework(hw['homework_id'])
                submissions_map = {sub['student_email']: sub for sub in submissions}
                
                # 找到所有待批改的作业
                pending_subs = [s for s in submissions if s.get('status') == 'submitted']
                if st.button(f"🤖 一键AI批改所有未批改作业 ({len(pending_subs)}份)", key=f"batch_grade_{hw['homework_id']}", disabled=not pending_subs):
                    progress_bar = st.progress(0, text="正在批量批改...")
                    for i, sub_to_grade in enumerate(pending_subs):
                        prompt = f"""...""" # 省略批改prompt
                        ai_result_text = call_gemini_api(prompt)
                        if ai_result_text:
                            try:
                                json_str = ai_result_text.strip().replace("```json", "").replace("```", "")
                                ai_result = json.loads(json_str)
                                sub_to_grade['status'] = 'ai_graded'
                                sub_to_grade['ai_grade'] = ai_result.get('overall_grade')
                                sub_to_grade['ai_feedback'] = ai_result.get('overall_feedback')
                                path = f"{BASE_ONEDRIVE_PATH}/submissions/{sub_to_grade['homework_id']}/{get_email_hash(sub_to_grade['student_email'])}/submission.json"
                                save_onedrive_data(path, sub_to_grade)
                            except Exception: pass # 单个失败不中断
                        progress_bar.progress((i + 1) / len(pending_subs), text=f"正在批量批改... {i+1}/{len(pending_subs)}")
                    st.success("批量批改完成！"); st.cache_data.clear(); time.sleep(1); st.rerun()

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
                        else:
                            cols[1].error("未提交")

# ... (学生仪表盘和主程序的其余部分，需要完整粘贴)

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
                        target_course['student_emails'].append(student_email)
                        path = f"{BASE_ONEDRIVE_PATH}/courses/{target_course['course_id']}.json"
                        if save_onedrive_data(path, target_course):
                            st.success(f"成功加入课程 '{target_course['course_name']}'！"); st.cache_data.clear()
                        else: st.error("加入课程失败，请稍后再试。")
    with tab1:
        if not my_courses:
            st.info("您还没有加入任何课程。请到“加入新课程”标签页输入邀请码。"); return
        selected_course_name = st.selectbox("选择一门课程查看作业", [c['course_name'] for c in my_courses])
        selected_course = next((c for c in my_courses if c['course_name'] == selected_course_name), None)
        if selected_course:
            st.subheader(f"'{selected_course['course_name']}' 的作业列表")
            homeworks = get_course_homework(selected_course['course_id'])
            if not homeworks:
                st.write("这门课还没有发布任何作业。")
            else:
                for hw in homeworks:
                    with st.container(border=True):
                        submission = get_student_submission(hw['homework_id'], student_email)
                        cols = st.columns([3,2,2])
                        cols[0].write(f"**{hw['title']}**")
                        if submission:
                            status = submission.get('status', 'submitted')
                            if status == 'feedback_released':
                                cols[1].success("已批改")
                                if cols[2].button("查看结果", key=f"view_{hw['homework_id']}"):
                                    st.session_state.viewing_homework_id = hw['homework_id']
                                    st.rerun()
                            else:
                                cols[1].info("已提交")
                                cols[2].write("待批改")
                        else:
                            cols[1].warning("待完成")
                            if cols[2].button("开始作业", key=f"do_{hw['homework_id']}"):
                                st.session_state.viewing_homework_id = hw['homework_id']
                                st.rerun()

def render_homework_submission_view(homework, student_email):
    st.header(f"作业: {homework['title']}")
    if st.button("返回课程"):
        st.session_state.viewing_homework_id = None
        st.rerun()
        
    with st.form("homework_submission_form"):
        answers = {}
        for i, q in enumerate(homework['questions']):
            st.write(f"--- \n**第{i+1}题:** {q['question']}")
            question_key = f'question_{i}'
            if q['type'] == 'text':
                answers[question_key] = st.text_area("你的回答", key=question_key, height=150)
            elif q['type'] == 'multiple_choice':
                answers[question_key] = st.radio("你的选择", q['options'], key=question_key, horizontal=True)
        
        if st.form_submit_button("确认提交作业"):
            with st.spinner("正在提交您的作业..."):
                submission_id = str(uuid.uuid4())
                submission_data = {
                    "submission_id": submission_id,
                    "homework_id": homework['homework_id'],
                    "student_email": student_email,
                    "answers": answers,
                    "status": "submitted", # 初始状态
                    "timestamp": datetime.utcnow().isoformat() + "Z"
                }
                path = f"{BASE_ONEDRIVE_PATH}/submissions/{homework['homework_id']}/{get_email_hash(student_email)}/submission.json"
                if save_onedrive_data(path, submission_data):
                    st.success("作业提交成功！请等待老师批改。")
                    st.cache_data.clear(); time.sleep(2)
                    st.session_state.viewing_homework_id = None
                    st.rerun()
                else: st.error("提交失败，请稍后重试。")

def render_student_graded_view(submission, homework):
    st.header(f"作业结果: {homework['title']}")
    if st.button("返回课程"):
        st.session_state.viewing_homework_id = None
        st.rerun()
    
    st.metric("最终得分", f"{submission.get('final_grade', 'N/A')} / 100")
    st.info(f"**教师评语:** {submission.get('final_feedback', '老师没有留下评语。')}")
    st.write("---")
    st.subheader("你的回答详情")
    for i, q in enumerate(homework['questions']):
        st.write(f"**第{i+1}题:** {q['question']}")
        answer = submission['answers'].get(f'question_{i}', "未回答")
        st.success(f"**你的回答:** {answer}")

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
        st.subheader("首次登录：请选择您的身份")
        st.info("这个选择是永久性的，之后将无法更改。")
        col1, col2 = st.columns(2)
        if col1.button("我是教师 👩‍🏫", use_container_width=True, type="primary"):
            user_profile['role'] = 'teacher'
            if save_user_profile(user_email, user_profile):
                st.balloons(); st.success("身份已确认为【教师】！页面将在2秒后刷新..."); time.sleep(2); st.rerun()
        if col2.button("我是学生 👨‍🎓", use_container_width=True, type="primary"):
            user_profile['role'] = 'student'
            if save_user_profile(user_email, user_profile):
                st.balloons(); st.success("身份已确认为【学生】！页面将在2秒后刷新..."); time.sleep(2); st.rerun()
    else:
        user_role = user_profile['role']
        # --- 视图路由逻辑 ---
        if st.session_state.grading_submission:
            all_homeworks = get_course_homework(st.session_state.grading_submission['course_id'])
            render_teacher_grading_view(st.session_state.grading_submission, all_homeworks)
        elif st.session_state.viewing_homework_id:
            all_courses = get_all_courses()
            homework = None
            for c in all_courses:
                for hw in get_course_homework(c['course_id']):
                    if hw['homework_id'] == st.session_state.viewing_homework_id:
                        homework = hw; break
                if homework: break
            
            if homework:
                submission = get_student_submission(homework['homework_id'], user_email)
                if submission and submission.get('status') == 'feedback_released':
                    render_student_graded_view(submission, homework)
                else:
                    render_homework_submission_view(homework, user_email)
            else:
                st.error("找不到作业。"); st.session_state.viewing_homework_id = None
        elif user_role == 'teacher':
            render_teacher_dashboard(user_email)
        elif user_role == 'student':
            render_student_dashboard(user_email)
