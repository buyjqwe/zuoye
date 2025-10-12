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
def save_user_profile(email, data): return save_onedrive_data(f"{BASE_ONEDRIVE_PATH}/users/{get_email_hash(email)}.json", is_json=True)
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
    all_homework = []
    for folder in ["homework", "remedial_homework"]:
        try:
            token = get_ms_graph_token(); headers = {"Authorization": f"Bearer {token}"}
            path = f"{BASE_ONEDRIVE_PATH}/{folder}:/children"
            response = onedrive_api_request('get', path, headers)
            if response.status_code == 404: continue
            response.raise_for_status()
            files = response.json().get('value', [])
            for file in files:
                hw_data = get_onedrive_data(f"{BASE_ONEDRIVE_PATH}/{folder}/{file['name']}")
                if hw_data and hw_data.get('course_id') == course_id:
                    all_homework.append(hw_data)
        except Exception: continue
    return all_homework

@st.cache_data(ttl=30)
def get_homework(homework_id):
    path = f"{BASE_ONEDRIVE_PATH}/homework/{homework_id}.json"
    hw = get_onedrive_data(path)
    if hw: return hw
    path_remedial = f"{BASE_ONEDRIVE_PATH}/remedial_homework/{homework_id}.json"
    return get_onedrive_data(path_remedial)

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
                        path = f"{BASE_ONEDRIVE_PATH}/homework/{hw['homework_id']}.json"
                        if delete_onedrive_file(path):
                            st.success("作业已删除！"); st.cache_data.clear(); time.sleep(1); st.rerun()
        st.divider()
        with st.expander("用AI生成并发布新作业"):
            topic = st.text_input("作业主题", key=f"topic_{course['course_id']}")
            details = st.text_area("具体要求", key=f"details_{course['course_id']}")
            if st.button("AI 生成作业题目", key=f"gen_hw_{course['course_id']}"):
                if topic and details:
                    with st.spinner("AI正在为您生成题目..."):
                        prompt = f"""你是一位教学经验丰富的老师。请为课程 '{course['course_name']}' 生成一份关于 '{topic}' 的作业。具体要求是: {details}。请严格按照以下JSON格式输出，不要有任何额外的解释文字：
                        {{ "title": "{topic} - 单元作业", "questions": [ {{"id":"q0", "type": "text", "question": "..."}}, {{"id":"q1", "type": "multiple_choice", "question": "...", "options": ["A", "B", "C"]}} ] }}"""
                        response_text = call_gemini_api(prompt)
                        if response_text: st.session_state.generated_homework = response_text; st.success("作业已生成！")
                else: st.warning("请输入作业主题和具体要求。")

            if 'generated_homework' in st.session_state:
                st.subheader("作业预览与发布")
                try:
                    # --- FIX: Escape backslashes before parsing JSON ---
                    json_str_raw = st.session_state.generated_homework.strip().replace("```json", "").replace("```", "")
                    json_str_fixed = json_str_raw.replace('\\', '\\\\')
                    homework_data = json.loads(json_str_fixed)

                    with st.container(border=True):
                        st.write(f"**标题:** {homework_data['title']}")
                        for i, q in enumerate(homework_data['questions']):
                            st.write(f"**第{i+1}题 ({q.get('type', 'text')}):** {q['question']}")
                    if st.button("确认发布", key=f"pub_hw_{course['course_id']}"):
                        homework_id = str(uuid.uuid4())
                        homework_to_save = {"homework_id": homework_id, "course_id": course['course_id'], "title": homework_data['title'], "questions": homework_data['questions']}
                        path = f"{BASE_ONEDRIVE_PATH}/homework/{homework_id}.json"
                        if save_onedrive_data(path, homework_to_save):
                            st.success(f"作业已成功发布！"); del st.session_state.generated_homework; st.cache_data.clear(); time.sleep(1); st.rerun()
                        else: st.error("作业发布失败。")
                except Exception as e:
                    st.error(f"AI返回格式有误: {e}"); st.code(st.session_state.generated_homework)

    with tab2: 
        st.subheader("学生管理")
        student_list = course.get('student_emails', [])
        if not student_list:
            st.info("目前还没有学生加入本课程。")
        else:
            for student_email in student_list:
                cols = st.columns([4, 1]); cols[0].write(f"- {student_email}")
                if cols[1].button("移除", key=f"remove_{get_email_hash(student_email)}", type="primary"):
                    course['student_emails'].remove(student_email)
                    path = f"{BASE_ONEDRIVE_PATH}/courses/{course['course_id']}.json"
                    if save_onedrive_data(path, course): st.success(f"已移除 {student_email}"); st.cache_data.clear(); time.sleep(1); st.rerun()
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
                pending_subs = [s for s in submissions if s.get('status') == 'submitted']

                if st.button(f"🤖 一键AI批改所有未批改作业 ({len(pending_subs)}份)", key=f"batch_grade_{hw['homework_id']}", disabled=not pending_subs):
                    progress_bar = st.progress(0, text="正在批量批改...")
                    for i, sub_to_grade in enumerate(pending_subs):
                        # ... (批量批改逻辑)
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
                                if cols[3].button("🤖 生成补习作业", key=f"remedial_{sub['submission_id']}"):
                                    # ... (补习作业生成逻辑)
                                    pass
                        else:
                            cols[1].error("未提交")
                            
    with tab4:
        st.subheader("📊 班级学情分析")
        homework_list = get_course_homework(course['course_id'])
        if not homework_list:
            st.info("本课程还没有已发布的作业，无法进行分析。"); return
        
        hw_options = {hw['title']: hw['homework_id'] for hw in homework_list}
        selected_hw_title = st.selectbox("请选择要分析的作业", options=hw_options.keys())
        
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
你是一位顶级的教育数据分析专家...
# 数据
## 作业题目
{json.dumps(homework['questions'], ensure_ascii=False)}
## 全班匿名批改数据汇总
{json.dumps(performance_summary, ensure_ascii=False)}
---
请开始生成您的学情分析报告。"""
                    analysis_report = call_gemini_api(prompt)
                    if analysis_report:
                        st.markdown("### 学情分析报告")
                        st.write(analysis_report)

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
        st.subheader("我加入的课程")
        if not my_courses:
            st.info("您还没有加入任何课程。请到“加入新课程”标签页输入邀请码。"); return
        
        for course in my_courses:
            with st.expander(f"**{course['course_name']}**", expanded=True):
                homeworks = get_course_homework(course['course_id'])
                if not homeworks:
                    st.write("这门课还没有发布任何作业。")
                else:
                    for hw in homeworks:
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
        st.session_state.viewing_homework_id = None; st.rerun()
        
    with st.form("homework_submission_form"):
        answers = {}; uploaded_files = {}
        for i, q in enumerate(homework['questions']):
            st.write(f"--- \n**第{i+1}题:** {q['question']}")
            question_key = q.get('id', f'q_{i}')
            
            if q.get('type') == 'text':
                answers[question_key] = st.text_area("输入文字回答", key=question_key, height=150)
                img_file_buffer = st.camera_input("拍照或上传手写答案", key=f"cam_{question_key}", help="如果上传图片，它将作为本题答案。")
                if img_file_buffer is not None:
                    img = Image.open(img_file_buffer); buf = io.BytesIO(); img.save(buf, format="JPEG"); img_bytes = buf.getvalue()
                    file_name = f"answer_{question_key}.jpg"
                    answers[question_key] = file_name
                    uploaded_files[file_name] = img_bytes
            elif q['type'] == 'multiple_choice':
                answers[question_key] = st.radio("你的选择", q['options'], key=question_key, horizontal=True)
        
        if st.form_submit_button("确认提交作业"):
            with st.spinner("正在提交您的作业..."):
                submission_path_prefix = f"{BASE_ONEDRIVE_PATH}/submissions/{homework['homework_id']}/{get_email_hash(student_email)}"
                for filename, filebytes in uploaded_files.items():
                    path = f"{submission_path_prefix}/{filename}"
                    save_onedrive_data(path, filebytes, is_json=False)

                submission_id = str(uuid.uuid4())
                submission_data = {"submission_id": submission_id, "homework_id": homework['homework_id'], "student_email": student_email, "answers": answers, "status": "submitted", "timestamp": datetime.utcnow().isoformat() + "Z"}
                path = f"{submission_path_prefix}/submission.json"
                if save_onedrive_data(path, submission_data, is_json=True):
                    st.success("作业提交成功！"); st.cache_data.clear(); time.sleep(2)
                    st.session_state.viewing_homework_id = None; st.rerun()
                else: st.error("提交失败，请稍后重试。")
                
def render_student_graded_view(submission, homework):
    st.header(f"作业结果: {homework['title']}")
    if st.button("返回课程列表"):
        st.session_state.viewing_homework_id = None; st.rerun()
    
    st.metric("最终得分", f"{submission.get('final_grade', 'N/A')} / 100")
    st.info(f"**教师总评:** {submission.get('final_feedback', '老师没有留下评语。')}")
    st.write("---")
    st.subheader("逐题分析与反馈")
    detailed_grades = submission.get('ai_detailed_grades', [])
    for i, q in enumerate(homework['questions']):
        question_key = q.get('id', f'q_{i}')
        st.write(f"**第{i+1}题:** {q['question']}")
        answer = submission['answers'].get(question_key, "未回答")
        
        if isinstance(answer, str) and (answer.endswith('.jpg') or answer.endswith('.png')):
            st.success("**你的回答 (图片):**")
            image_path = f"{BASE_ONEDRIVE_PATH}/submissions/{homework['homework_id']}/{get_email_hash(submission['student_email'])}/{answer}"
            image_bytes = get_onedrive_data(image_path, is_json=False)
            if image_bytes: st.image(image_bytes)
            else: st.warning("无法加载图片。")
        else:
            st.success(f"**你的回答:** {answer}")
        
        detail = next((g for g in detailed_grades if g.get('question_index') == i), None)
        if detail:
            st.warning(f"**AI反馈:** {detail.get('feedback', '无')}")

def render_teacher_grading_view(submission, homework):
    st.header("作业批改")
    if st.button("返回成绩册"):
        st.session_state.grading_submission = None; st.session_state.ai_grade_result = None; st.rerun()

    st.subheader(f"学生: {submission['student_email']}")
    st.write(f"作业: {homework['title']}")
    
    prompt_parts = ["""# 角色
你是一位经验丰富、耐心且善于引导的教学助手... (完整的批改Prompt)
"""]
    
    for i, q in enumerate(homework['questions']):
        with st.container(border=True):
            st.write(f"**第{i+1}题:** {q['question']}")
            question_key = q.get('id', f'q_{i}')
            answer = submission['answers'].get(question_key, "学生未回答此题")
            
            if isinstance(answer, str) and (answer.endswith('.jpg') or answer.endswith('.png')):
                st.info(f"**学生回答 (图片):**")
                image_path = f"{BASE_ONEDRIVE_PATH}/submissions/{homework['homework_id']}/{get_email_hash(submission['student_email'])}/{answer}"
                with st.spinner("正在从OneDrive加载图片..."):
                    image_bytes = get_onedrive_data(image_path, is_json=False)
                if image_bytes: 
                    st.image(image_bytes)
                    prompt_parts.append(f"\n--- 第{i+1}题图片回答 ---")
                    prompt_parts.append(Image.open(io.BytesIO(image_bytes)))
                else: 
                    st.warning("无法加载图片。")
                    prompt_parts.append(f"\n--- 第{i+1}题图片回答 ---\n[无法加载图片]")
            else:
                st.info(f"**学生回答:** {answer}")
    
    st.write("---")
    if submission.get('status') != 'feedback_released':
        if st.button("🤖 AI自动批改"):
            with st.spinner("AI正在进行多模态分析与批改..."):
                final_prompt = [f"""...
【作业题目】: {json.dumps(homework['questions'], ensure_ascii=False)}
【学生回答】: {json.dumps(submission['answers'], ensure_ascii=False)}
...(请注意，部分回答在后面的图片中)
---
请开始你的批改工作。"""] + prompt_parts[1:]
                
                ai_result_text = call_gemini_api(final_prompt)
                if ai_result_text:
                    try:
                        json_str = ai_result_text.strip().replace("```json", "").replace("```", "")
                        ai_result = json.loads(json_str)
                        st.session_state.ai_grade_result = ai_result; st.rerun()
                    except Exception: st.error("AI返回结果格式有误，请手动批改。"); st.code(ai_result_text)

    ai_result = st.session_state.get('ai_grade_result')
    if not ai_result and submission.get('status') == 'ai_graded':
        ai_result = {"overall_grade": submission.get('ai_grade'), "overall_feedback": submission.get('ai_feedback'), "detailed_grades": submission.get('ai_detailed_grades')}

    if ai_result:
        st.subheader("AI 批改建议")
        for detail in ai_result.get('detailed_grades', []):
            st.warning(f"**第{detail.get('question_index', -1) + 1}题 AI反馈:** {detail.get('feedback')}")

    initial_grade, initial_feedback = (ai_result.get('overall_grade', 0), ai_result.get('overall_feedback', "")) if ai_result else (0, "")

    st.subheader("教师最终审核")
    final_grade = st.number_input("最终得分", min_value=0, max_value=100, value=initial_grade)
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
        # ... Role selection logic ...
        pass
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
                else: render_homework_submission_view(homework, student_email)
            else: st.error("找不到作业。"); st.session_state.viewing_homework_id = None; st.rerun()
        elif user_role == 'teacher':
            render_teacher_dashboard(user_email)
        elif user_role == 'student':
            render_student_dashboard(student_email)
