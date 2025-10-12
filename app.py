import streamlit as st
from supabase import create_client, Client

# 从 secrets.toml 加载密钥
SUPABASE_URL = st.secrets["supabase"]["url"]
SUPABASE_KEY = st.secrets["supabase"]["service_key"] # 后端统一使用拥有更高权限的 service_key

# 创建 Supabase 客户端，这个 supabase 对象将贯穿整个应用
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
