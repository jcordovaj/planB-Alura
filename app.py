import streamlit as st
from dotenv import load_dotenv
import os
from google import genai
from langchain_google_genai import GoogleGenAI
from langchain_core.messages import HumanMessage, AIMessage
from dotenv import load_dotenv

# 0. Configuración del Modelo (Desacoplado)
load_dotenv()

# Para cambiar de modelo, solo se modifica esta instancia y se puede crear
# un menu para escoger entre varios modelos

llm_client = client = genai.Client(
    api_key=os.environ.get("GEMINI_API_KEY"),
    model='models/gemini-3-flash-preview',
    temperature=0.9,
    max_output_tokens=65536,
    top_p=0.95,
)

# 1. Inicialización de la aplicación Streamlit
st.set_page_config(page_title="MVP Alura Challenge", page_icon="🤖")
st.title("Desafío Alura - MVP Intelligent Chatbot")

# 2. Initialize chat history in the session
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# 3. Mostrar historial
for message in st.session_state.chat_history:
    role = "user" if isinstance(message, HumanMessage) else "assistant"
    with st.chat_message(role):
        st.markdown(message.content)        
        

# 4. Lógica de Chat
if prompt := st.chat_input("Como te puedo ayudar?"):
    # Display user message
    st.chat_message("user").markdown(prompt)
    # Add user message to history
    st.session_state.messages.append({"role": "user", "content": prompt})
    # Guardar mensaje del usuario como objeto HumanMessage
    st.session_state.chat_history.append(HumanMessage(content=prompt))

    # 5. Get response from AI
    with st.chat_message("assistant"):
        # LangChain procesa la lista de objetos de mensaje
        response = llm_client.invoke(st.session_state.chat_history)
        st.markdown(response.content)

    # Guardar respuesta de la IA como objeto AIMessage
    st.session_state.chat_history.append(AIMessage(content=response.content))
