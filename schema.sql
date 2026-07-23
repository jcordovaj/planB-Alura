-- =====================================================================
-- SCHEMA.SQL: Inicialización de PostgreSQL y pgvector
-- Optimizado para la capa gratuita de OCI con pgSQL
-- =====================================================================

-- 1. Habilitar la extensión de vectores si no existe
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Limpiar tablas previas de LangChain para pruebas limpias
DROP TABLE IF EXISTS langchain_pg_embedding;
DROP TABLE IF EXISTS langchain_pg_collection;

-- 3. Crear la tabla de colecciones (Colección principal de DocuMind)
CREATE TABLE langchain_pg_collection (
    name VARCHAR,
    cbackand VARCHAR,
    uuid UUID NOT NULL PRIMARY KEY,
    custom_metadata JSONB
);

-- 4. Crear la tabla de vectores para guardar fragmentos y metadatos
-- Nota: models/text-embedding-004 de Google produce vectores de 768 dimensiones
CREATE TABLE langchain_pg_embedding (
    collection_id UUID REFERENCES langchain_pg_collection(uuid) ON DELETE CASCADE,
    embedding VECTOR(768),
    document VARCHAR,
    cmetadata JSONB,
    custom_id VARCHAR,
    uuid UUID NOT NULL PRIMARY KEY
);

-- 5. Crear índice HNSW (Hierarchical Navigable Small World) para búsquedas veloces
-- Optimiza el tiempo de consulta en el MVP de OCI para que sea instantáneo.
CREATE INDEX ON langchain_pg_embedding 
USING hnsw (embedding vector_cosine_ops) 
WITH (m = 16, ef_construction = 64);
