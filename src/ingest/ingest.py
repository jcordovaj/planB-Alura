import os
import gc
import sys
import pandas as pd
from pypdf import PdfReader
from docx import Document as DocxReader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import PGVector
from langchain_google_genai import GoogleGenAIEmbeddings
from dotenv import load_dotenv

load_dotenv()

# Configurar logs
def log(msg):
    print(f"[*] {msg}", flush=True)

# Lector de archivos Markdown (.md) - Ultra liviano y óptimo para MVP
def extract_text_from_markdown(md_path):
    log(f"Iniciando procesamiento de archivo Markdown: {md_path}")
    with open(md_path, "r", encoding="utf-8") as f:
        # Procesar línea por línea usando un generador para no saturar memoria RAM
        for line in f:
            if line.strip():
                yield line

# Lector de PDFs optimizado para OCI (Lazy Loading línea a línea para evitar desborde de memoria)
def extract_text_from_pdf(pdf_path):
    log(f"Iniciando extracción defensiva de PDF: {pdf_path}")
    reader = PdfReader(pdf_path)
    total_pages = len(reader.pages)
    
    # Usar un generador (lazy yield) para no cargar todo el texto de golpe en memoria RAM
    for idx, page in enumerate(reader.pages):
        text = page.extract_text()
        if text:
            yield f"--- [Página {idx+1}/{total_pages}] ---\n{text}"
        # Liberación periódica
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

# Lector de CSV defensivo (carga por chunks con Pandas para evitar buffers grandes)
def extract_text_from_csv(csv_path):
    log(f"Procesando CSV por bloques: {csv_path}")
    # Procesar bloques de 100 filas para evitar desbordes de RAM en OCI
    for chunk in pd.read_csv(csv_path, chunksize=100):
        for index, row in chunk.iterrows():
            row_str = " | ".join([f"{col}: {val}" for col, val in row.items()])
            yield f"Fila {index}: {row_str}"
        gc.collect()

def main():
    if len(sys.argv) < 2:
        log("Uso: python ingest.py <ruta_de_documento>")
        sys.exit(1)
        
    doc_path = sys.argv[1]
    if not os.path.exists(doc_path):
        log(f"Error: El archivo {doc_path} no existe.")
        sys.exit(1)
        
    filename = os.path.basename(doc_path).lower()
    text_generator = None
    
    # Enrutamiento de parsers según extensión
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
        log(f"Error: Formato de archivo no soportado: {filename}")
        sys.exit(1)
        
    # Agrupar fragmentos de texto en memoria controlada
    raw_text_chunks = []
    current_buffer = ""
    
    log("Procesando documento por flujos (Streams)...")
    for fragment in text_generator:
        current_buffer += fragment + "\n"
        if len(current_buffer) > 10000:  # Cada 10k caracteres creamos un lote de guardado temporal
            raw_text_chunks.append(current_buffer)
            current_buffer = ""
            gc.collect()
            
    if current_buffer:
        raw_text_chunks.append(current_buffer)
        
    full_text = "\n".join(raw_text_chunks)
    
    # Aplicar el divisor de caracteres de LangChain
    log("Iniciando chunking inteligente...")
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=150,
        length_function=len
    )
    
    chunks = text_splitter.create_documents(
        texts=[full_text],
        metadatas=[{"source": os.path.basename(doc_path)}]
    )
    log(f"Se generaron exitosamente {len(chunks)} fragmentos (chunks).")
    
    # Inicializar embeddings gratuitos de Gemini
    log("Conectando con la API de Google Gemini para Embeddings...")
    embeddings = GoogleGenAIEmbeddings(
        model="models/text-embedding-004",
        google_api_key=os.getenv("GEMINI_API_KEY")
    )
    
    # Conexión a pgvector en la base de datos PostgreSQL de OCI
    connection_string = PGVector.connection_string_from_db_params(
        driver="psycopg2",
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        database=os.getenv("DB_NAME", "ragdb"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres")
    )
    
    log("Cargando vectores a PostgreSQL con pgvector...")
    PGVector.from_documents(
        documents=chunks,
        embedding=embeddings,
        connection_string=connection_string,
        collection_name="doc_knowledge"
    )
    log("[+] ¡Ingesta y vectorización completadas exitosamente!")
    gc.collect()

if __name__ == "__main__":
    main()
