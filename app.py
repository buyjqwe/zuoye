import streamlit as st
import requests
import re
import random
import time
import json
import hashlib
import secrets
from datetime import datetime

# --- 页面基础设置 ---
st.set_page_config(page_title="在线作业平台", page_icon="📚", layout="centered")

# --- 全局常量 ---
BASE_ONEDRIVE_PATH = "root:/Apps/HomeworkPlatform" # 为新应用设置独立的OneDrive路径

# --- 初始化 Session State ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'user_email' not in st.session_state: st.session_state.user_email = ""
if 'login_step' not in st.session_state: st.session_state.login_step = "enter_email"

# --- API 配置 ---
MS_GRAPH_CONFIG = st.secrets["microsoft_graph"]

# --- 核心功能函数定义 ---

def get_email_hash(email): 
    return hashlib.sha256(email.lower().encode('utf-8')).hexdigest()

@st.cache_data(ttl=3500)
def get_ms_graph_token():
    url = f"https://login.microsoftonline.com/{MS_GRAPH_CONFIG['tenant_id']}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials", 
        "client_id": MS_GRAPH_CONFIG['client_id'], 
        "client_secret": MS_GRAPH_CONFIG['client_secret'], 
        "scope": "https://graph.microsoft.com/.default"
    }
    resp = requests.post(url, data=data)
    resp.raise_for_status()
    return resp.json()["access_token"]

def onedrive_api_request(method, path, headers, data=None):
    base_url = f"https://graph.microsoft.com/v1.0/users/{MS_GRAPH_CONFIG['sender_email']}/drive"
    url = f"{base_url}/{path}"
    if method.lower() == 'get': return requests.get(url, headers=headers, timeout=15)
    if method.lower() == 'put': return requests.put(url, headers=headers, data=data, timeout=15)
    return None

def get_onedrive_data(path):
    try:
        token = get_ms_graph_token()
        headers = {"Authorization": f"Bearer {token}"}
        resp = onedrive_api_request('get', f"{path}:/content", headers)
        if resp.status_code == 404: return None
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        if "404" not in str(e): st.error(f"从 OneDrive 加载数据失败 ({path}): {e}")
        return None

def save_onedrive_data(path, data):
    try:
        token = get_ms_graph_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        json_data = json.dumps(data, indent=2, ensure_ascii=False)
        onedrive_api_request('put', f"{path}:/content", headers, data=json_data.encode('utf-8'))
        return True
    except Exception as e:
        st.error(f"保存数据到 OneDrive 失败 ({path}): {e}")
        return False

def get_user_profile(email): 
    return get_onedrive_data(f"{BASE_ONEDRIVE_PATH}/users/{get_email_hash(email)}.json")

def save_user_profile(email, data): 
    return save_onedrive_data(f"{BASE_ONEDRIVE_PATH}/users/{get_email_hash(email)}.json", data)

def get_global_data(file_name): 
    data = get_onedrive_data(f"{BASE_ONEDRIVE_PATH}/{file_name}.json")
    return data if data else {}

def save_global_data(file_name, data): 
    return save_onedrive_data(f"{BASE_ONEDRIVE_PATH}/{file_name}.json", data)

def send_verification_code(email, code):
    try:
        token = get_ms_graph_token()
        url = f"https://graph.microsoft.com/v1.0/users/{MS_GRAPH_CONFIG['sender_email']}/sendMail"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {"message": {"subject": f"[{code}] 您的登录验证码", "body": {"contentType": "Text", "content": f"您在在线作业平台的验证码是：{code}，5分钟内有效。"}, "toRecipients": [{"emailAddress": {"address": email}}]}, "saveToSentItems": "true"}
        requests.post(url, headers=headers, json=payload, timeout=10).raise_for_status()
        return True
    except Exception as e:
        st.error(f"邮件发送失败: {e}")
        return False

def handle_send_code(email):
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        st.sidebar.error("请输入有效的邮箱地址。")
        return
    
    codes = get_global_data("codes")
    code = str(random.randint(100000, 999999))
    codes[email.lower()] = {"code": code, "expires_at": time.time() + 300} # 统一使用小写邮箱
    
    if not save_global_data("codes", codes) or not send_verification_code(email, code): return
    
    st.sidebar.success("验证码已发送，请查收。")
    st.session_state.login_step = "enter_code"
    st.session_state.temp_email = email
    st.rerun()

def handle_verify_code(email, code):
    email = email.lower()
    codes = get_global_data("codes")
    code_info = codes.get(email)
    
    if not code_info or time.time() > code_info["expires_at"]:
        st.sidebar.error("验证码已过期或不存在。")
        return

    if code_info["code"] == code:
        user_profile = get_user_profile(email)
        if not user_profile:
            # 创建一个没有角色的新用户
            user_profile = {
                "email": email,
                "created_at": datetime.utcnow().isoformat() + "Z",
            }
            save_user_profile(email, user_profile)
            st.toast("🎉 注册成功！请选择您的身份。")
        
        sessions = get_global_data("sessions")
        token = secrets.token_hex(16)
        sessions[token] = {"email": email, "expires_at": time.time() + (7 * 24 * 60 * 60)} # 7天有效期
        save_global_data("sessions", sessions)
        
        del codes[email]
        save_global_data("codes", codes)
        
        st.session_state.logged_in = True
        st.session_state.user_email = email
        st.session_state.login_step = "logged_in"
        st.query_params["session_token"] = token
        st.rerun()
    else:
        st.sidebar.error("验证码错误。")

def check_session_from_query_params():
    if st.session_state.get('logged_in'): return
    token = st.query_params.get("session_token")
    if not token: return
    
    sessions = get_global_data("sessions")
    session_info = sessions.get(token)

    if session_info and time.time() < session_info.get("expires_at", 0):
        st.session_state.logged_in = True
        st.session_state.user_email = session_info["email"]
        st.session_state.login_step = "logged_in"
    elif "session_token" in st.query_params:
        st.query_params.clear()

def display_login_form():
    with st.sidebar:
        st.header("🔐 用户登录/注册")
        if st.session_state.login_step == "enter_email":
            email = st.text_input("邮箱地址", key="email_input")
            if st.button("发送验证码"):
                handle_send_code(email)
        elif st.session_state.login_step == "enter_code":
            email_display = st.session_state.get("temp_email", "")
            st.info(f"验证码已发送至: {email_display}")
            code = st.text_input("验证码", key="code_input")
            if st.button("登录或注册"):
                handle_verify_code(email_display, code)
            if st.button("返回"):
                st.session_state.login_step = "enter_email"
                st.rerun()

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
            token_to_remove = st.query_params.get("session_token")
            if token_to_remove:
                sessions = get_global_data("sessions")
                if token_to_remove in sessions:
                    del sessions[token_to_remove]
                    save_global_data("sessions", sessions)
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.query_params.clear()
            st.rerun()

    user_profile = get_user_profile(user_email)

    if not user_profile:
        st.error("无法加载您的用户配置，请尝试重新登录。")
    elif 'role' not in user_profile:
        # --- 身份选择 ---
        st.subheader("首次登录：请选择您的身份")
        st.info("这个选择是永久性的，之后将无法更改。")
        
        col1, col2 = st.columns(2)
        
        if col1.button("我是教师 👩‍🏫", use_container_width=True, type="primary"):
            user_profile['role'] = 'teacher'
            if save_user_profile(user_email, user_profile):
                st.balloons()
                st.success("身份已确认为【教师】！页面将在2秒后刷新...")
                time.sleep(2)
                st.rerun()
            else:
                st.error("身份设置失败，请稍后重试。")

        if col2.button("我是学生 👨‍🎓", use_container_width=True, type="primary"):
            user_profile['role'] = 'student'
            if save_user_profile(user_email, user_profile):
                st.balloons()
                st.success("身份已确认为【学生】！页面将在2秒后刷新...")
                time.sleep(2)
                st.rerun()
            else:
                st.error("身份设置失败，请稍后重试。")
    else:
        # --- 根据身份显示不同的仪表盘 ---
        user_role = user_profile['role']
        if user_role == 'teacher':
            st.header("教师仪表盘 (开发中)")
            st.write("您已作为教师登录。后续我们将在这里实现创建课程、发布作业等功能。")
        elif user_role == 'student':
            st.header("学生仪表盘 (开发中)")
            st.write("您已作为学生登录。后续我们将在这里实现加入课程、完成和提交作业等功能。")
