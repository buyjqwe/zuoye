import streamlit as st
import requests
import time

# --- OneDrive 连接诊断程序 ---

# 原封不动地复制您项目中的这两个函数
@st.cache_data(ttl=3500)
def get_ms_graph_token():
    # 这个函数直接从您的项目中复制过来，确保逻辑一致
    ms_secrets = st.secrets["microsoft_graph"]
    url = f"https://login.microsoftonline.com/{ms_secrets['tenant_id']}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": ms_secrets['client_id'],
        "client_secret": ms_secrets['client_secret'],
        "scope": "https://graph.microsoft.com/.default"
    }
    resp = requests.post(url, data=data, timeout=20)
    resp.raise_for_status()
    return resp.json()

# --- 主测试逻辑 ---
st.set_page_config(layout="wide")
st.title("OneDrive 连接诊断")

# 步骤 1: 读取 Secrets
st.header("步骤 1: 读取 Secrets")
try:
    ms_secrets = st.secrets["microsoft_graph"]
    st.success("✅ 成功读取 `microsoft_graph` 配置！")
    # 为了安全，不显示 client_secret
    st.json({
        "tenant_id": ms_secrets.get("tenant_id"),
        "client_id": ms_secrets.get("client_id"),
        "sender_email": ms_secrets.get("sender_email"),
        "admin_email": ms_secrets.get("admin_email"),
    })
except Exception as e:
    st.error(f"❌ 读取 `secrets.toml` 文件中的 `[microsoft_graph]` 部分失败: {e}")
    st.stop()

# 步骤 2: 获取 Access Token
st.header("步骤 2: 获取 Access Token")
token_data = None
try:
    with st.spinner("正在向 Microsoft Graph API 请求访问令牌..."):
        token_data = get_ms_graph_token()
    
    if token_data and "access_token" in token_data:
        st.success("✅ 成功获取 Access Token！")
        st.write(f"令牌 (前15位): `{token_data['access_token'][:15]}...`")
    else:
        st.error("❌ 获取 Access Token 失败，返回的数据不包含令牌。")
        st.json(token_data)
        st.stop()
except Exception as e:
    st.error(f"❌ 在获取 Access Token 时发生崩溃: {e}")
    # 尝试显示更详细的API错误信息
    if hasattr(e, 'response') and e.response is not None:
        st.write("API返回的详细错误信息:")
        st.json(e.response.json())
    st.stop()

# 步骤 3: 尝试访问 OneDrive
st.header("步骤 3: 尝试访问 OneDrive 文件")
try:
    with st.spinner("正在尝试访问 OneDrive 根目录..."):
        token = token_data["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        # 我们不访问具体文件，只访问App根目录，这总应该是成功的
        url = f"https://graph.microsoft.com/v1.0/users/{ms_secrets['sender_email']}/drive/root:/Apps/StreamlitDashboard"
        
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()

    st.success("✅ 成功连接到 OneDrive 并访问应用文件夹！")
    st.write("诊断通过！您的 Microsoft Graph API 配置和网络连接均正常。")
    st.balloons()

except requests.exceptions.HTTPError as e:
    if e.response.status_code == 404:
        st.warning("⚠️ OneDrive 连接成功，但找不到 `/Apps/StreamlitDashboard` 文件夹 (404)。")
        st.info("这通常是正常的，说明文件夹尚未创建。**诊断通过！**")
        st.balloons()
    else:
        st.error(f"❌ 访问 OneDrive 时发生 HTTP 错误 (状态码: {e.response.status_code})")
        st.write("API返回的详细错误信息:")
        st.json(e.response.json())
except Exception as e:
    st.error(f"❌ 访问 OneDrive 时发生未知崩溃: {e}")
    st.stop()
