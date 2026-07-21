import streamlit as st
import os
import gc
from langchain.chains import ConversationalRetrievalChain
from langchain.memory import ConversationBufferWindowMemory
from langchain_community.vectorstores import PGVector
from langchain_google_genai import GoogleGenAIEmbeddings, ChatGoogleGenAI
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Configuración de página con optimización de memoria
st.set_page_config(
    page_title="DocuMind RAG Assistant",
    page_icon="🤖",
    layout="centered"
)

# Constantes de control y mensaje fuera de dominio
OUT_OF_DOMAIN_REFUSAL = "Su pregunta está fuera del alcance de este servicio asistencial. ¿Puedo ayudarle con otra pregunta relacionada con los documentos internos?"

# Lazy Loading de Recursos para ahorrar RAM en OCI Compute (1GB max)
@st.cache_resource(ttl="1h")
def init_rag_system():
    """Inicializa de forma diferida los embeddings, el LLM y la conexión a pgvector"""
    try:
        # Usar embeddings livianos del API de Gemini (gratuita)
        embeddings = GoogleGenAIEmbeddings(
            model="models/text-embedding-004",
            google_api_key=os.getenv("GEMINI_API_KEY")
        )
        
        # Conexión a pgvector en PostgreSQL
        connection_string = PGVector.connection_string_from_db_params(
            driver="psycopg2",
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", 5432)),
            database=os.getenv("DB_NAME", "ragdb"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", "postgres")
        )
        
        vectorstore = PGVector(
            connection_string=connection_string,
            embedding_function=embeddings,
            collection_name="doc_knowledge"
        )
        
        # Modelo gratuito en cascada (Gemini 1.5 Flash o Gemini 2.5 Flash)
        llm = ChatGoogleGenAI(
            model="gemini-1.5-flash",
            temperature=0.1,  # Temperatura ultra-baja para evitar alucinaciones
            google_api_key=os.getenv("GEMINI_API_KEY")
        )
        
        # Retornar configuraciones básicas de forma atómica
        return vectorstore.as_retriever(search_kwargs={"k": 3}), llm
    except Exception as e:
        st.error(f"Error al inicializar infraestructura RAG: {e}")
        return None, None

retriever, llm = init_rag_system()

# Título y Contexto de la Aplicación
st.title("🤖 Asistente Documental DocuMind")
st.caption("Filtros de Seguridad Inteligentes • Desplegado exitosamente en OCI Compute")

# Inicializar historial de chat en sesión Streamlit
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "Bienvenido al chatbot corporativo de DocuMind. Pregúntame únicamente sobre manuales, políticas de recursos humanos u reportes internos cargados."}
    ]

# Renderizar historial de mensajes
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Captura de preguntas de usuario
if user_query := st.chat_input("Escribe tu pregunta sobre los documentos internos..."):
    # Renderizar pregunta del usuario
    with st.chat_message("user"):
        st.markdown(user_query)
    st.session_state.messages.append({"role": "user", "content": user_query})
    
    # Procesamiento y búsqueda RAG
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        
        if not retriever or not llm:
            error_msg = "La base de datos o el servicio LLM no están disponibles temporalmente."
            message_placeholder.markdown(error_msg)
            st.session_state.messages.append({"role": "assistant", "content": error_msg})
        else:
            try:
                # 1. Recuperar contexto relevante usando lazy generator para evitar memory leak
                relevant_docs = retriever.get_relevant_documents(user_query)
                
                # Crear el prompt contextual defensivo con Guardrails estrictos
                context = "\n\n".join([doc.page_content for doc in relevant_docs])
                
                system_prompt = f"""
                Eres un asistente de IA corporativo y estrictamente restringido.
                Tu tarea es responder a la pregunta del usuario utilizando ÚNICAMENTE el siguiente contexto corporativo recuperado del sistema de archivos RAG:
                
                CONTEXTO:
                {context}
                
                REGLA DE GUARDRAIL CRÍTICA:
                - Responde ÚNICAMENTE si la respuesta está directamente en el contexto anterior.
                - Si la pregunta no se puede responder directamente basándose en el contexto provisto (por ejemplo, preguntas generales, fútbol, recetas, chistes, desarrollo web general o temas no cubiertos en el contexto), debes contestar EXACTAMENTE con el siguiente mensaje de rechazo:
                  "{OUT_OF_DOMAIN_REFUSAL}"
                - No inventes, especules ni alucines datos. Mantente profesional y formal.
                """
                
                # Invocar de forma defensiva
                full_query = f"{system_prompt}\n\nPregunta del usuario: {user_query}"
                response = llm.invoke(full_query)
                answer = response.content
                
                # Mostrar respuesta en tiempo real
                message_placeholder.markdown(answer)
                st.session_state.messages.append({"role": "assistant", "content": answer})
                
                # Fuerza la recolección de basura después de cada inferencia para ahorrar RAM
                gc.collect()
                
            except Exception as e:
                err_msg = f"Error al procesar la respuesta: {str(e)}"
                message_placeholder.markdown(err_msg)
                st.session_state.messages.append({"role": "assistant", "content": err_msg})