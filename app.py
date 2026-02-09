import os
import sqlite3
import streamlit as st
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime

# 1. Setup and Environment
load_dotenv()
API_KEY = os.getenv("OPENROUTER_API_KEY")
UPLOAD_DIR = "uploaded_files"
DB_NAME = "chat_history.db"

if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

# 2. Database Management
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Stores chat turns and references to saved files
    c.execute('''CREATE TABLE IF NOT EXISTS chat_logs 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  timestamp TEXT, 
                  model TEXT, 
                  role TEXT, 
                  content TEXT,
                  file_path TEXT)''')


    # Models Table
    c.execute('''CREATE TABLE IF NOT EXISTS model_list 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  model_id TEXT UNIQUE)''')
    
    # Default model if the table is empty
    c.execute("INSERT OR IGNORE INTO model_list (model_id) VALUES (?)", 
              ("openai/gpt-oss-120b:free",))
    conn.commit()
    conn.close()

def save_to_db(model, role, content, file_path=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO chat_logs (timestamp, model, role, content, file_path) VALUES (?, ?, ?, ?, ?)",
              (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), model, role, content, file_path))
    conn.commit()
    conn.close()

# 3. UI Layout
st.set_page_config(page_title="OpenRouter Pro", page_icon="📁", layout="wide")
init_db()

def add_model(name):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO model_list (model_id) VALUES (?)", (name,))
        conn.commit()
    except sqlite3.IntegrityError:
        pass # Model already exists
    conn.close()

def get_all_models():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT model_id FROM model_list")
    models = [row[0] for row in c.fetchall()]
    conn.close()
    return models

# Sidebar: Configuration & File Vault
with st.sidebar:
    st.title("Settings & Vault")
    
    # --- MODEL SELECTION ---
    st.subheader("🤖 Model Management")
    available_models = get_all_models()
    model_name = st.selectbox("Choose Model", options=available_models)
    
    # Form to add new models
    with st.expander("➕ Add New Model"):
        new_model_input = st.text_input("OpenRouter Model ID")
        if st.button("Add to List"):
            if new_model_input:
                add_model(new_model_input)
                st.rerun() # Refresh to show in selectbox
    
    st.divider()
    
    # --- FILE VAULT ---
    st.subheader("📁 File Vault")
    saved_files = os.listdir(UPLOAD_DIR)
    
    if saved_files:
        selected_vault_file = st.selectbox("Reuse a saved file:", ["None"] + saved_files)
        if selected_vault_file != "None":
            st.info(f"Using: {selected_vault_file}")
    else:
        st.write("No files saved yet.")
        selected_vault_file = "None"
    
    st.divider()
    if st.button("Clear Chat History"):
        st.session_state.messages = []
        st.rerun()

# Initialize Session State
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display Chat History
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 4. Input Logic
prompt_data = st.chat_input("Ask anything...", accept_file=True)

if prompt_data:
    user_text = prompt_data.text
    context_from_file = ""
    saved_path = None

    # Handle NEW File Uploads
    if prompt_data.get("files"):
        for uploaded_file in prompt_data["files"]:
            saved_path = os.path.join(UPLOAD_DIR, uploaded_file.name)
            # Save actual file to disk
            with open(saved_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            # Extract content for AI
            try:
                content = uploaded_file.getvalue().decode("utf-8")
                context_from_file += f"\n\n[New Attachment: {uploaded_file.name}]\n{content}"
            except:
                context_from_file += f"\n\n[File saved: {uploaded_file.name} (Binary)]"

    # Handle REUSING File from Vault
    elif selected_vault_file != "None":
        saved_path = os.path.join(UPLOAD_DIR, selected_vault_file)
        try:
            with open(saved_path, "r", encoding="utf-8") as f:
                vault_content = f.read()
                context_from_file += f"\n\n[Reused from Vault: {selected_vault_file}]\n{vault_content}"
        except:
            context_from_file += f"\n\n[Reusing: {selected_vault_file} (Binary)]"

    full_prompt = user_text + context_from_file

    # Update UI & DB (User side)
    st.session_state.messages.append({"role": "user", "content": full_prompt})
    with st.chat_message("user"):
        st.markdown(full_prompt)
    save_to_db(model_name, "user", user_text, saved_path)

    # 5. OpenRouter API Call
    try:
        client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=API_KEY)
        
        with st.chat_message("assistant"):
            resp_container = st.empty()
            full_response = ""
            
            stream = client.chat.completions.create(
                model=model_name,
                messages=[{"role": m["role"], "content": m["content"]} for m in st.session_state.messages],
                stream=True
            )

            for chunk in stream:
                if chunk.choices[0].delta.content:
                    full_response += chunk.choices[0].delta.content
                    resp_container.markdown(full_response + "▌")
            
            resp_container.markdown(full_response)
            
            # Save Assistant Response
            st.session_state.messages.append({"role": "assistant", "content": full_response})
            save_to_db(model_name, "assistant", full_response)

    except Exception as e:
        st.error(f"API Error: {str(e)}")