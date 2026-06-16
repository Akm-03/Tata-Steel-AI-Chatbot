import streamlit as st
import requests

st.set_page_config(page_title="Factory AI", page_icon="🏭")
st.title("🏭 Factory Operations AI")
st.write("Ask me about machine operations, threshold deviations, or hardware status.")

# Keep memory of the chat
if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if user_query := st.chat_input("E.g., Which machines had high voltage deviations?"):
    # Show user message
    st.session_state.messages.append({"role": "user", "content": user_query})
    with st.chat_message("user"):
        st.markdown(user_query)

    # Show AI response
    with st.chat_message("assistant"):
        with st.spinner("Analyzing Snowflake data..."):
            try:
                response = requests.post("http://localhost:8000/chat", json={"message": user_query})
                if response.status_code == 200:
                    res = response.json()
                    answer = res["answer"]
                    
                    st.markdown(answer)
                    with st.expander("🔍 View Backend Diagnostics"):
                        st.code(res["generated_query"], language="sql")
                        st.write("Raw Data Array:", res["data"])
                    
                    st.session_state.messages.append({"role": "assistant", "content": answer})
                else:
                    st.error(f"Server error: {response.text}")
            except Exception as e:
                st.error("Could not connect to the Brain. Is main.py running?")