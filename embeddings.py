import os
import requests
import time
import sys

# Logger simple
def log_emb(msg):
    print(f"[*] [Embeddings] {msg}", flush=True)

def get_gemini_embeddings(texts, is_query=False):
    """
    Intenta generar embeddings usando la API oficial de Google Gemini (v1beta o v1).
    Soporta models/text-embedding-004 y fallback a models/embedding-001.
    """
    try:
        import google.generativeai as genai
    except ImportError:
        raise Exception("La librería 'google-generativeai' no está instalada.")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise Exception("La variable de entorno GEMINI_API_KEY no está configurada.")

    genai.configure(api_key=api_key)
    task_type = "retrieval_query" if is_query else "retrieval_document"
    
    # 1. Intentar con models/text-embedding-004 (768 dimensiones)
    try:
        response = genai.embed_content(
            model="models/text-embedding-004",
            content=texts,
            task_type=task_type
        )
        return response['embedding']
    except Exception as e_004:
        log_emb(f"models/text-embedding-004 falló: {e_004}. Intentando fallback a models/embedding-001...")
        # 2. Intentar con models/embedding-001 (768 dimensiones)
        try:
            response = genai.embed_content(
                model="models/embedding-001",
                content=texts,
                task_type=task_type
            )
            return response['embedding']
        except Exception as e_001:
            raise Exception(f"Gemini falló en text-embedding-004 ({e_004}) y embedding-001 ({e_001})")

def get_cohere_embeddings(texts, is_query=False):
    """
    Genera embeddings usando la API de Cohere (embed-multilingual-v3.0).
    Truncamos el vector resultante de 1024 dimensiones a 768 para que coincida con el esquema de pgvector.
    """
    cohere_key = os.getenv("COHERE_API_KEY")
    if not cohere_key:
        raise Exception("La variable de entorno COHERE_API_KEY no está configurada.")

    response = requests.post(
        "https://api.cohere.ai/v1/embed",
        headers={
            "Authorization": f"Bearer {cohere_key}",
            "Content-Type": "application/json"
        },
        json={
            "texts": texts,
            "model": "embed-multilingual-v3.0",
            "input_type": "search_query" if is_query else "search_document"
        },
        timeout=25
    )
    
    if response.status_code == 200:
        data = response.json()
        embeddings = data.get("embeddings", [])
        if not embeddings:
            raise Exception(f"La API de Cohere no devolvió embeddings: {data}")
        # Truncar los vectores de 1024 a 768 dimensiones
        return [emb[:768] for emb in embeddings]
    else:
        raise Exception(f"La API de Cohere devolvió un error ({response.status_code}): {response.text}")

def get_jina_embeddings(texts, is_query=False):
    """
    Genera embeddings usando la API de Jina AI (jina-embeddings-v2-base-multilingual).
    Este modelo devuelve nativamente 768 dimensiones de forma muy eficiente.
    """
    jina_key = os.getenv("JINA_API_KEY") or os.getenv("EMBEDDING_PROVIDER_KEY")
    if not jina_key:
        raise Exception("La variable de entorno JINA_API_KEY no está configurada.")

    response = requests.post(
        "https://api.jina.ai/v1/embeddings",
        headers={
            "Authorization": f"Bearer {jina_key}",
            "Content-Type": "application/json"
        },
        json={
            "model": "jina-embeddings-v2-base-multilingual",
            "normalized": True,
            "embedding_type": "float",
            "input": texts
        },
        timeout=25
    )
    
    if response.status_code == 200:
        data = response.json()
        embeddings_data = data.get("data", [])
        if not embeddings_data:
            raise Exception(f"La API de Jina no devolvió datos de embeddings: {data}")
        # Jina devuelve una lista de diccionarios ordenados: [{"embedding": [...], "index": 0}, ...]
        sorted_embs = sorted(embeddings_data, key=lambda x: x.get("index", 0))
        return [item["embedding"] for item in sorted_embs]
    else:
        raise Exception(f"La API de Jina devolvió un error ({response.status_code}): {response.text}")

def get_huggingface_embeddings(texts, is_query=False):
    """
    Genera embeddings usando Hugging Face Inference API con el modelo intfloat/multilingual-e5-base.
    Este modelo devuelve nativamente 768 dimensiones, ideal para persistir en pgvector de 768 dims.
    """
    # Para multilingual-e5-base, es importante anteponer "query: " para búsquedas y "passage: " para documentos
    prefix = "query: " if is_query else "passage: "
    formatted_texts = [f"{prefix}{t}" for t in texts]

    model_id = "intfloat/multilingual-e5-base"
    api_url = f"https://api-inference.huggingface.co/pipeline/feature-extraction/{model_id}"
    
    headers = {}
    hf_token = os.getenv("HF_API_KEY") or os.getenv("HF_TOKEN")
    if hf_token:
        headers["Authorization"] = f"Bearer {hf_token}"

    for attempt in range(5):
        try:
            response = requests.post(
                api_url, 
                headers=headers, 
                json={"inputs": formatted_texts, "options": {"wait_for_model": True}}, 
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                if not result or not isinstance(result, list):
                    raise Exception(f"Hugging Face devolvió una respuesta inesperada: {result}")
                
                # Manejar pooling por si retorna secuencias de tokens [lote, tokens, embedding]
                if isinstance(result[0], list) and len(result[0]) > 0 and isinstance(result[0][0], list):
                    pooled_embeddings = []
                    for doc_tokens in result:
                        num_tokens = len(doc_tokens)
                        dim = len(doc_tokens[0])
                        # Mean pooling (Promedio simple de tokens)
                        avg_vector = [sum(token[dim_idx] for token in doc_tokens) / num_tokens for dim_idx in range(dim)]
                        pooled_embeddings.append(avg_vector)
                    return pooled_embeddings
                
                return result
            elif response.status_code == 503:
                # El modelo está cargándose en los servidores de Hugging Face, esperamos e intentamos de nuevo
                try:
                    err_data = response.json()
                    wait_time = err_data.get("estimated_time", 5)
                except Exception:
                    wait_time = 5
                log_emb(f"El modelo de Hugging Face se está cargando en el servidor. Esperando {wait_time}s para reintentar (intento {attempt + 1}/5)...")
                time.sleep(min(wait_time, 5))
                continue
            else:
                raise Exception(f"La API de Hugging Face devolvió un error ({response.status_code}): {response.text}")
        except Exception as e:
            if attempt == 4:
                raise e
            time.sleep(2)

def get_embeddings(texts, is_query=False):
    """
    Función de entrada de alta resiliencia.
    Recibe un texto (str) o una lista de textos (list) y devuelve una lista de vectores de 768 floats
    (o un solo vector de 768 floats si se le pasó un str único).
    Aplica una estrategia de cascada automática por orden de disponibilidad y funcionamiento.
    """
    # Normalizar entrada a lista
    is_single_text = isinstance(texts, str)
    if is_single_text:
        texts_list = [texts]
    else:
        texts_list = list(texts)

    provider = os.getenv("EMBEDDING_PROVIDER", "auto").lower()
    
    # Lista de proveedores a intentar en orden de prioridad para "auto"
    providers_queue = []
    if provider == "gemini":
        providers_queue = ["gemini", "cohere", "jina", "huggingface"]
    elif provider == "cohere":
        providers_queue = ["cohere", "gemini", "jina", "huggingface"]
    elif provider == "jina":
        providers_queue = ["jina", "gemini", "cohere", "huggingface"]
    elif provider == "huggingface":
        providers_queue = ["huggingface", "gemini", "cohere", "jina"]
    else:
        # Modo "auto" por defecto: Primero Gemini, luego Cohere, luego Jina, luego Hugging Face
        providers_queue = ["gemini", "cohere", "jina", "huggingface"]

    last_error = None
    
    for prov in providers_queue:
        try:
            if prov == "gemini":
                # Validar de forma preventiva que esté configurado
                if not os.getenv("GEMINI_API_KEY"):
                    raise Exception("GEMINI_API_KEY no configurada en las variables de entorno.")
                log_emb("Intentando generar embeddings con Google Gemini...")
                res = get_gemini_embeddings(texts_list, is_query=is_query)
                log_emb("Embeddings generados exitosamente con Google Gemini.")
                return res[0] if is_single_text else res
                
            elif prov == "cohere":
                if not os.getenv("COHERE_API_KEY"):
                    raise Exception("COHERE_API_KEY no configurada en las variables de entorno.")
                log_emb("Intentando generar embeddings con Cohere (embed-multilingual-v3.0)...")
                res = get_cohere_embeddings(texts_list, is_query=is_query)
                log_emb("Embeddings generados exitosamente con Cohere (vía Fallback).")
                return res[0] if is_single_text else res

            elif prov == "jina":
                if not os.getenv("JINA_API_KEY") and not os.getenv("EMBEDDING_PROVIDER_KEY"):
                    raise Exception("Ni JINA_API_KEY ni EMBEDDING_PROVIDER_KEY están configuradas.")
                log_emb("Intentando generar embeddings con Jina AI (jina-embeddings-v2-base-multilingual)...")
                res = get_jina_embeddings(texts_list, is_query=is_query)
                log_emb("Embeddings generados exitosamente con Jina AI (vía Fallback).")
                return res[0] if is_single_text else res
                
            elif prov == "huggingface":
                log_emb("Intentando generar embeddings con Hugging Face (intfloat/multilingual-e5-base)...")
                res = get_huggingface_embeddings(texts_list, is_query=is_query)
                log_emb("Embeddings generados exitosamente con Hugging Face (vía Fallback definitivo).")
                return res[0] if is_single_text else res
                
        except Exception as e:
            log_emb(f"Falla con el proveedor '{prov}': {e}")
            last_error = e
            continue

    # Si todos fallaron
    raise Exception(f"Estrategia de embeddings agotada sin éxito. Todos los proveedores fallaron. Último error: {last_error}")