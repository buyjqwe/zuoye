import streamlit as st
from supabase import create_client, Client
import time

# --- Supabase 连接诊断程序 ---

st.set_page_config(layout="wide")
st.title("Supabase 连接诊断")

# 步骤 1: 读取 Secrets
st.header("步骤 1: 读取 Secrets")
try:
    supabase_secrets = st.secrets["supabase"]
    st.success("✅ 成功读取 `supabase` 配置！")
    # 为了安全，不完全显示密钥
    st.json({
        "url": supabase_secrets.get("url"),
        "anon_key (前15位)": supabase_secrets.get("anon_key", "")[:15] + "...",
        "service_key (前15位)": supabase_secrets.get("service_key", "")[:15] + "..."
    })
except Exception as e:
    st.error(f"❌ 读取 `secrets.toml` 文件中的 `[supabase]` 部分失败: {e}")
    st.stop()

# 步骤 2: 初始化 Supabase 客户端
st.header("步骤 2: 初始化 Supabase 客户端")
supabase: Client = None
try:
    with st.spinner("正在初始化 Supabase 客户端..."):
        SUPABASE_URL = supabase_secrets["url"]
        SUPABASE_KEY = supabase_secrets["service_key"]
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    if supabase:
        st.success("✅ Supabase 客户端初始化成功！")
    else:
        st.error("❌ Supabase 客户端初始化失败，返回了空对象。")
        st.stop()
except Exception as e:
    st.error(f"❌ 在初始化 Supabase 客户端时发生崩溃: {e}")
    st.stop()

# 步骤 3: 尝试从数据库读取数据
st.header("步骤 3: 尝试从数据库读取数据")
try:
    with st.spinner("正在尝试连接数据库并查询 `users` 表..."):
        # 我们尝试从'users'表中获取数据，即使表是空的，这个查询本身也应该成功
        response = supabase.table('users').select('*', count='exact').limit(1).execute()

    st.success("✅ 成功连接到 Supabase 数据库并执行了查询！")
    st.write(f"查询到 `users` 表中共有 {response.count} 条记录。")
    st.balloons()
    st.info("诊断通过！您的 Supabase 配置和网络连接均正常。现在您可以将代码换回主程序了。")

except Exception as e:
    st.error(f"❌ 访问 Supabase 数据库时发生崩溃: {e}")
    st.write("这通常意味着您的 `service_key` 不正确，或者数据库的网络访问策略限制了连接。")
    st.stop()
