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
    c.execute('''CREATE TABLE IF NOT EXISTS chat_logs 
             (id INTEGER PRIMARY KEY AUTOINCREMENT, 
              timestamp TEXT, 
              model TEXT, 
              role TEXT, 
              content TEXT,
              file_path TEXT,
              prompt_tokens INTEGER,
              completion_tokens INTEGER,
              total_tokens INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS model_list 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  model_id TEXT UNIQUE)''')
    c.execute("INSERT OR IGNORE INTO model_list (model_id) VALUES (?)", 
              ("qwen/qwen2.5-vl-72b-instruct",)) # Default fallback
    conn.commit()
    conn.close()

def save_to_db(model, role, content, file_path=None, p_tok=0, c_tok=0, t_tok=0):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO chat_logs (timestamp, model, role, content, file_path, prompt_tokens, completion_tokens, total_tokens) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
              (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), model, role, content, file_path, p_tok, c_tok, t_tok))
    conn.commit()
    conn.close()

def add_model(name):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO model_list (model_id) VALUES (?)", (name,))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()

def get_all_models():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT model_id FROM model_list")
    models = [row[0] for row in c.fetchall()]
    conn.close()
    return models

# 3. UI Layout
st.set_page_config(page_title="OpenRouter Pro", page_icon="📁", layout="wide")
init_db()

with st.sidebar:
    st.title("Settings & Vault")
    
    # --- MODEL SELECTION ---
    st.subheader("🤖 Model Management")
    available_models = get_all_models()
    model_name = st.selectbox("Choose Model", options=available_models)
    
    with st.expander("➕ Add New Model"):
        new_model_input = st.text_input("OpenRouter Model ID")
        if st.button("Add to List"):
            if new_model_input:
                add_model(new_model_input)
                st.rerun()
    
    st.divider()

    # --- MEMORY TOGGLE ---
    st.subheader("🧠 Conversation Memory")
    use_memory = st.toggle("Enable Chat Memory", value=True, help="If OFF, the AI won't remember previous messages in the current session.")
    
    st.divider()
    
    # --- FILE VAULT ---
    st.subheader("📁 File Vault")
    saved_files = os.listdir(UPLOAD_DIR)
    if saved_files:
        selected_vault_file = st.selectbox("Reuse a saved file:", ["None"] + saved_files)
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

    if prompt_data.get("files"):
        for uploaded_file in prompt_data["files"]:
            saved_path = os.path.join(UPLOAD_DIR, uploaded_file.name)
            with open(saved_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            try:
                content = uploaded_file.getvalue().decode("utf-8")
                context_from_file += f"\n\n[New Attachment: {uploaded_file.name}]\n{content}"
            except:
                context_from_file += f"\n\n[File saved: {uploaded_file.name} (Binary)]"

    elif selected_vault_file != "None":
        saved_path = os.path.join(UPLOAD_DIR, selected_vault_file)
        try:
            with open(saved_path, "r", encoding="utf-8") as f:
                vault_content = f.read()
                context_from_file += f"\n\n[Reused from Vault: {selected_vault_file}]\n{vault_content}"
        except:
            context_from_file += f"\n\n[Reusing: {selected_vault_file} (Binary)]"

    full_prompt = user_text + context_from_file
    st.session_state.messages.append({"role": "user", "content": full_prompt})
    
    with st.chat_message("user"):
        st.markdown(full_prompt)
    save_to_db(model_name, "user", user_text, saved_path)

    # 5. API Call with Memory Logic
    try:
        client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=API_KEY)
        
        # Prepare messages based on toggle
        if use_memory:
            api_messages = [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages]
        else:
            # Only send the VERY LAST message (the current one)
            api_messages = [{"role": "user", "content": full_prompt}]

        with st.chat_message("assistant"):
            resp_container = st.empty()
            full_response = ""
            
            stream = client.chat.completions.create(
                model=model_name,
                messages=api_messages,
                stream=True,
                stream_options={"include_usage": True}
            )

            completion_tokens = 0
            total_tokens = 0
            full_response = ""

            for chunk in stream:
                # 1. Handle Content
                if chunk.choices and chunk.choices[0].delta.content:
                    full_response += chunk.choices[0].delta.content
                    resp_container.markdown(full_response + "▌")
                
                # 2. Handle Usage (usually comes in the last chunk)
                if chunk.usage:
                    prompt_tokens = chunk.usage.prompt_tokens
                    completion_tokens = chunk.usage.completion_tokens
                    total_tokens = chunk.usage.total_tokens

            resp_container.markdown(full_response)

            # Save User message (approximate or leave 0 if you only care about total cost)
            save_to_db(model_name, "user", user_text, saved_path) 

            # Save Assistant message WITH exact tokens
            save_to_db(model_name, "assistant", full_response, p_tok=prompt_tokens, c_tok=completion_tokens, t_tok=total_tokens)
            st.session_state.messages.append({"role": "assistant", "content": full_response})

    except Exception as e:
        st.error(f"API Error: {str(e)}")