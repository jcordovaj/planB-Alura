import streamlit as st
import os
import gc
import psycopg2
import google.generativeai as genai
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv(override=True)

# Configuración de la interfaz Streamlit con optimización de memoria
st.set_page_config(
    page_title="DocuMind RAG Assistant MVP",
    page_icon="🤖",
    layout="centered"
)

# Constante del mensaje de rechazo estándar para el Guardrail estricto de dominio
OUT_OF_DOMAIN_REFUSAL = "Su pregunta está fuera del alcance de este servicio asistencial. ¿Puedo ayudarle con otra pregunta relacionada con los documentos internos?"

# Inicialización segura de las credenciales de API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    st.error("🚨 **Error de Configuración**: La variable de entorno `GEMINI_API_KEY` no está configurada.")
    st.stop()

# Configurar el SDK oficial de Google Generative AI
genai.configure(api_key=GEMINI_API_KEY)

# Recuperación de datos desde OCI PostgreSQL de manera 100% nativa (libre de LangChain)
def retrieve_relevant_chunks(user_query, k=3):
    try:
        # 1. Generar embedding de la consulta usando la API oficial
        response = genai.embed_content(
            model="models/text-embedding-004",
            content=user_query,
            task_type="retrieval_query"
        )
        query_embedding = response['embedding']
        
        # 2. Conexión nativa a la base de datos de OCI PostgreSQL
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", 5432)),
            database=os.getenv("DB_NAME", "ragdb"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", "postgres")
        )
        cursor = conn.cursor()
        
        # Formatear el vector para pgvector
        vector_str = "[" + ",".join(map(str, query_embedding)) + "]"
        
        # Consulta semántica directa usando el operador de distancia de coseno <=> de pgvector
        cursor.execute(
            """
            SELECT document 
            FROM langchain_pg_embedding 
            ORDER BY embedding <=> %s 
            LIMIT %s;
            """,
            (vector_str, k)
        )
        rows = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        # Retornar los fragmentos de texto
        return [row[0] for row in rows]
    except Exception as e:
        st.error(f"⚠️ Error de base de datos o recuperación vectorial: {e}")
        return []

# Generación nativa de respuestas con Gemini 2.5 Flash
def generate_response(system_prompt, user_query):
    try:
        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            generation_config={"temperature": 0.1}  # Ultra-bajo para máxima fidelidad
        )
        full_prompt = f"{system_prompt}\n\nPregunta del usuario: {user_query}"
        response = model.generate_content(full_prompt)
        return response.text
    except Exception as e:
        return f"🚨 Error en la API de inferencia de Gemini: {e}"

# Encabezado visual de la interfaz Streamlit
st.title("🤖 Chatbot Inteligente - DocuMind")
st.caption("Filtros de Seguridad Inteligentes • Desplegado en OCI Compute • 100% Nativo sin Dependencias de LangChain")

# Inicialización de historial de chat con memoria persistente por sesión
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "Bienvenido al asistente de conocimiento interno de DocuMind. He indexado tus manuales, políticas y reportes. Pregúntame lo que necesites sobre los documentos corporativos cargados."}
    ]

# Renderizar el historial de conversación en la pantalla de Streamlit
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Captura de preguntas de usuario
if user_query := st.chat_input("Escribe tu consulta sobre los documentos..."):
    # Renderizar la pregunta del usuario en el chat
    with st.chat_message("user"):
        st.markdown(user_query)
    st.session_state.messages.append({"role": "user", "content": user_query})
    
    # Procesar la respuesta a través del pipeline RAG con Guardrails Strict Mode
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        
        # 1. Recuperar contexto semántico nativo usando pgvector
        relevant_chunks = retrieve_relevant_chunks(user_query, k=3)
        
        # Consolidar los fragmentos recuperados
        context = "\n\n".join(relevant_chunks) if relevant_chunks else "No se encontraron fragmentos relevantes."
        
        # Definición del prompt restrictivo con regla estricta de no alucinación (Guardrails)
        system_prompt = f"""
        Eres un asistente de IA corporativo ultra-restringido para consulta de documentos internos.
        Tu tarea es responder a la pregunta del usuario utilizando ÚNICAMENTE la información del contexto provisto:
        
        CONTEXTO:
        {context}
        
        REGLAS CRÍTICAS DE GUARDRAILS:
        - Responde ÚNICAMENTE basándote en el contexto anterior.
        - Si la pregunta NO se puede responder de manera directa con los datos provistos en el contexto (por ejemplo, temas ajenos a la empresa, chistes, deportes, cultura general o información histórica que no esté en los documentos), debes rechazar la respuesta EXACTAMENTE con este mensaje:
          "{OUT_OF_DOMAIN_REFUSAL}"
        - No inventes, deduzcas ni supongas datos. La precisión de los datos y el rechazo estricto fuera de dominio son obligatorios.
        """
        
        # 2. Generar respuesta utilizando el SDK nativo
        answer = generate_response(system_prompt, user_query)
        
        # Mostrar respuesta final en la pantalla
        message_placeholder.markdown(answer)
        st.session_state.messages.append({"role": "assistant", "content": answer})
        
        # Forzar recolección de basura para conservar la RAM en la VM de OCI
        gc.collect()
        