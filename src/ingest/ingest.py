import os
import gc
import sys
import uuid
import json
import pandas as pd
import psycopg2
from pypdf import PdfReader
from docx import Document as DocxReader
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# Logger simple para salida en consola de OCI Compute
def log(msg):
    print(f"[*] {msg}", flush=True)

# Lector de archivos Markdown (.md) - Ultra liviano y óptimo para MVP
def extract_text_from_markdown(md_path):
    log(f"Iniciando procesamiento de archivo Markdown: {md_path}")
    with open(md_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield line

# Lector de PDFs optimizado (Lazy Loading página por página para evitar desborde de memoria)
def extract_text_from_pdf(pdf_path):
    log(f"Iniciando extracción defensiva de PDF: {pdf_path}")
    reader = PdfReader(pdf_path)
    total_pages = len(reader.pages)
    for idx, page in enumerate(reader.pages):
        text = page.extract_text()
        if text:
            yield f"--- [Página {idx+1}/{total_pages}] ---\n{text}"
        if idx % 5 == 0:
            gc.collect()

# Lector de DOCX defensivo
def extract_text_from_docx(docx_path):
    log(f"Leyendo documento Word: {docx_path}")
    doc = DocxReader(docx_path)
    for idx, para in enumerate(doc.paragraphs):
        if para.text.strip():
            yield para.text
        if idx % 20 == 0:
            gc.collect()

# Lector de CSV por fragmentos para evitar saturación de memoria
def extract_text_from_csv(csv_path):
    log(f"Procesando archivo de datos CSV por bloques: {csv_path}")
    for chunk in pd.read_csv(csv_path, chunksize=100):
        for index, row in chunk.iterrows():
            row_str = " | ".join([f"{col}: {val}" for col, val in row.items()])
            yield f"Fila {index}: {row_str}"
        gc.collect()

# Chunking inteligente sin dependencias externas (Reemplazo de RecursiveCharacterTextSplitter)
def split_text_into_chunks(text, chunk_size=1000, overlap=150):
    chunks = []
    if not text:
        return chunks
    
    start = 0
    text_len = len(text)
    while start < text_len:
        end = min(start + chunk_size, text_len)
        if end < text_len:
            # Buscar un punto de separación lógico (párrafo, salto de línea, punto o espacio)
            best_split = -1
            for separator in ["\n\n", "\n", ". ", " "]:
                pos = text.rfind(separator, max(start, end - 150), end)
                if pos != -1:
                    best_split = pos + len(separator)
                    break
            if best_split != -1:
                end = best_split
                
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        
        start = max(start + 1, end - overlap)
    return chunks

def main():
    if len(sys.argv) < 2:
        log("Uso: python ingest.py <ruta_de_documento>")
        sys.exit(1)
        
    doc_path = sys.argv[1]
    if not os.path.exists(doc_path):
        log(f"Error: El archivo {doc_path} no existe en la ruta provista.")
        sys.exit(1)
        
    filename = os.path.basename(doc_path).lower()
    text_generator = None
    
    if filename.endswith(".md"):
        text_generator = extract_text_from_markdown(doc_path)
    elif filename.endswith(".pdf"):
        text_generator = extract_text_from_pdf(doc_path)
    elif filename.endswith(".docx"):
        text_generator = extract_text_from_docx(doc_path)
    elif filename.endswith(".csv"):
        text_generator = extract_text_from_csv(doc_path)
    elif filename.endswith(".txt"):
        with open(doc_path, "r", encoding="utf-8") as f:
            text_generator = (line for line in f)
    else:
        log(f"Error: Formato de archivo no soportado o no testeado: {filename}")
        sys.exit(1)
        
    raw_text_chunks = []
    current_buffer = ""
    
    log("Procesando documento por flujos (Streams)...")
    for fragment in text_generator:
        current_buffer += fragment + "\n"
        if len(current_buffer) > 10000:
            raw_text_chunks.append(current_buffer)
            current_buffer = ""
            gc.collect()
            
    if current_buffer:
        raw_text_chunks.append(current_buffer)
        
    full_text = "\n".join(raw_text_chunks)
    
    log("Iniciando segmentación de texto (Chunking) nativa...")
    chunks = split_text_into_chunks(full_text, chunk_size=1000, overlap=150)
    log(f"Se generaron exitosamente {len(chunks)} fragmentos (chunks) listos para vectorizar.")
    
    if not chunks:
        log("Advertencia: El documento está vacío o no contiene texto legible.")
        sys.exit(0)
        
    # Inicializar la API de Gemini
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        log("Error: La variable de entorno GEMINI_API_KEY no está definida.")
        sys.exit(1)
    
    genai.configure(api_key=api_key)
    
    # Calcular embeddings en lotes para optimizar llamadas a la API
    log("Generando embeddings con la API oficial de Google Gemini (models/text-embedding-004)...")
    embeddings = []
    batch_size = 50
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i+batch_size]
        try:
            response = genai.embed_content(
                model="models/text-embedding-004",
                contents=batch,
                task_type="retrieval_document"
            )
            embeddings.extend(response['embedding'])
        except Exception as e:
            log(f"Error al generar embeddings para el lote {i}: {e}")
            sys.exit(1)
            
    log(f"Se calcularon {len(embeddings)} vectores con éxito.")
    
    # Conexión nativa a PostgreSQL usando psycopg2
    log("Estableciendo conexión nativa a la Base de Datos PostgreSQL de OCI...")
    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", 5432)),
            database=os.getenv("DB_NAME", "ragdb"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", "postgres")
        )
        cursor = conn.cursor()
    except Exception as e:
        log(f"Error de conexión con la base de datos: {e}")
        sys.exit(1)
        
    try:
        collection_name = "doc_knowledge"
        
        # 1. Obtener o crear la colección
        cursor.execute("SELECT uuid FROM langchain_pg_collection WHERE name = %s;", (collection_name,))
        row = cursor.fetchone()
        if row:
            collection_id = row[0]
            log(f"Colección existente encontrada: {collection_name} (UUID: {collection_id})")
        else:
            collection_id = str(uuid.uuid4())
            cursor.execute(
                "INSERT INTO langchain_pg_collection (name, uuid, custom_metadata) VALUES (%s, %s, %s);",
                (collection_name, collection_id, json.dumps({}))
            )
            log(f"Nueva colección creada: {collection_name} (UUID: {collection_id})")
            
        # 2. Insertar fragmentos y vectores
        log("Cargando vectores a PostgreSQL con pgvector...")
        for text, embedding in zip(chunks, embeddings):
            embedding_id = str(uuid.uuid4())
            cmetadata = json.dumps({"source": os.path.basename(doc_path)})
            vector_str = "[" + ",".join(map(str, embedding)) + "]"
            
            cursor.execute(
                """
                INSERT INTO langchain_pg_embedding (collection_id, embedding, document, cmetadata, uuid)
                VALUES (%s, %s, %s, %s, %s);
                """,
                (collection_id, vector_str, text, cmetadata, embedding_id)
            )
            
        conn.commit()
        log("[+] ¡La ingesta y vectorización en OCI han culminado de forma exitosa y libre de LangChain!")
        
    except Exception as e:
        conn.rollback()
        log(f"Error durante el proceso de inserción: {e}")
        sys.exit(1)
    finally:
        cursor.close()
        conn.close()
        gc.collect()

if __name__ == "__main__":
    main()
