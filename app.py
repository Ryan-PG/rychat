import os
import sqlite3
import streamlit as st
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime

# 1. Load Environment Variables
load_dotenv()
API_KEY = os.getenv("OPENROUTER_API_KEY")

# 2. Database Setup
def init_db():
    conn = sqlite3.connect('chat_history.db')
    c = conn.cursor()
    # Table for storing user-assistant turns
    c.execute('''CREATE TABLE IF NOT EXISTS chat_logs 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  timestamp TEXT, 
                  model TEXT, 
                  role TEXT, 
                  content TEXT,
                  file_name TEXT)''')
    conn.commit()
    conn.close()

def save_to_db(model, role, content, file_name=None):
    conn = sqlite3.connect('chat_history.db')
    c = conn.cursor()
    c.execute("INSERT INTO chat_logs (timestamp, model, role, content, file_name) VALUES (?, ?, ?, ?, ?)",
              (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), model, role, content, file_name))
    conn.commit()
    conn.close()

# 3. Streamlit UI Configuration
st.set_page_config(page_title="OpenRouter Chat", page_icon="🤖")
st.title("OpenRouter Chat Interface")

# Sidebar for configuration
with st.sidebar:
    st.header("Settings")
    model_name = st.text_input("Model Name", value="google/gemini-2.0-flash-lite-preview-02-05:free")
    st.info("Example models: \n- `openai/gpt-4o` \n- `anthropic/claude-3-sonnet` \n- `meta-llama/llama-3-8b-instruct`")
    if st.button("Clear History"):
        st.session_state.messages = []
        st.rerun()

# Initialize Chat Session State
if "messages" not in st.session_state:
    st.session_state.messages = []

# Initialize DB
init_db()

# Display Chat History
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 4. Chat Input with Attachment Support
# Note: accept_file=True adds the paperclip icon inside the chat bar
prompt = st.chat_input("Type your message...", accept_file=True)

if prompt:
    # Handle File Attachment logic
    file_info = ""
    file_name = None
    if prompt.get("files"):
        for uploaded_file in prompt["files"]:
            file_name = uploaded_file.name
            # For this demo, we read text content. For images, you'd handle base64.
            try:
                content = uploaded_file.read().decode("utf-8")
                file_info += f"\n\n[Attached File: {file_name}]\n{content}"
            except:
                file_info += f"\n\n[Attached File: {file_name} (Binary/Non-text)]"

    full_user_input = prompt.text + file_info

    # Display User Message
    st.session_state.messages.append({"role": "user", "content": full_user_input})
    with st.chat_message("user"):
        st.markdown(full_user_input)
    
    # Save User Request to DB
    save_to_db(model_name, "user", prompt.text, file_name)

    # 5. Call OpenRouter API
    try:
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=API_KEY,
        )

        with st.chat_message("assistant"):
            response_container = st.empty()
            full_response = ""
            
            # Request completion
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": m["role"], "content": m["content"]}
                    for m in st.session_state.messages
                ],
                stream=True
            )

            for chunk in response:
                if chunk.choices[0].delta.content:
                    full_response += chunk.choices[0].delta.content
                    response_container.markdown(full_response + "▌")
            
            response_container.markdown(full_response)
            
            # Save Assistant Response to DB & Session
            st.session_state.messages.append({"role": "assistant", "content": full_response})
            save_to_db(model_name, "assistant", full_response)

    except Exception as e:
        st.error(f"Error: {str(e)}")