# Sistema OCR - Consulta de Presupuestos con IA

## Objetivo

permitir que una IA externa acceda **solo** a información de un presupuesto específico, sin posibilidad de contaminarse con datos de otros presupuestos.

**Problema a resolver**: Aislamiento de información por presupuesto para RAG con embedding.

---

## Overview de la Arquitectura

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         SERVIDOR REMOTO (VPN)                           │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ /ruta/presupuestos/                                             │    │
│  │ ├── 245745/        (archivos sueltos, subcarpetas no uniformes) │    │
│  │ ├── 484857/                                                     │    │
│  │ └── ...                                                         │    │
│  │  (~300GB totales, 500 presupuestos)                              │    │
│  └─────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
                                │ VPN + rsync
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         TU SERVIDOR (Coolify)                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  FASE 1: Importación Masiva (300GB)                                     │
│  ───────────────────────────────────────────────────────                │
│  Script de transferencia ──▶ /srv/presupuestos/tmp/                     │
│                                 │                                       │
│                                 ▼                                       │
│                         Pipeline de ingestión                            │
│                         (días de procesamiento)                         │
│                                 │                                       │
│                                 ▼                                       │
│                         Qdrant + PostgreSQL                            │
│                                 │                                       │
│                                 ▼                                       │
│                         Borrar carpeta transferida                       │
│                                                                         │
│  FASE 2: Watchdog (sync incremental)                                    │
│  ─────────────────────────────────────────                              │
│  Watchdog detecta cambios ──▶ Procesar nuevos archivos ──▶ Qdrant      │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
                                    ▲
                                    │ API con filtro
                                    │
┌─────────────────────────────────────────────────────────────────────────┐
│                        OTRA APP (Coolify)                               │
│  ┌──────────────┐                                                       │
│  │  Chat/IA     │──── Solo puede consultar via API                      │
│  │  Usuario     │     con presupuesto_id en header/sesión               │
│  └──────────────┘     No accede directo a archivos, Qdrant ni PostgreSQL│
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 1. Estructura de Carpetas (Servidor Remoto)

```
/ruta/presupuestos/          ← Origen (otro servidor, ~300GB)
├── 245745/
│   ├── archivo1.pdf
│   ├── subcarpeta_random/
│   │   └── docs_relevantes.xlsx
│   └── outro_archivo.pdf
├── 484857/
│   ├── presupuestos/
│   │   └── presupuesto_final.pdf
│   ├── imagenes_varias/
│   │   └── fachada.jpg
│   └── email_01.eml
└── ... (500 presupuestos)

/srv/presupuestos/           ← Destino (tu servidor, Coolify)
├── tmp/                     ← Temporal durante importación
└── {presupuesto_id}/        ← Definitivo
```

**Nota**: Carpetas NO uniformes. El scanner debe recorrer recursivamente sin asumir estructura.

---

## 2. Stack Tecnológico

| Componente | Tecnología | Notas |
|------------|------------|-------|
| **Backend API** | FastAPI (Python) | Rápido, validación automática |
| **Vector DB** | Qdrant | Ligero, Rust, filtro por payload |
| **Metadata DB** | PostgreSQL 15 | Metadatos archivos |
| **Embedding** | nomic-embed-text-v2-moe (GGUF) | 305M params, llama.cpp |
| **VLM** | gemma-4-2b-it | 4B params, 128k context, multimodal |
| **OCR** | PaddleOCR | Rápido, preciso |
| **Text extraction** | pypdf, openpyxl, python-docx | PDF, Excel, Word |
| **Transferencia** | rsync over VPN | Script Bash |
| **Watchdog** | watchdog (Python) | Detecta cambios en carpetas |
| **Container** | Docker + Coolify | Já lo usas |

---

## 3. Modelos de IA

### 3.1 Embedding: nomic-embed-text-v2-moe (GGUF)

| Spec | Valor |
|------|-------|
| Params | 475M total, 305M activos |
| Dims | 768 |
| Formato | GGUF (llama.cpp) |
| Tamaño | 328MB (Q4_K_M) |
| VRAM | ~2GB |
| Multilingual | Sí |

**Uso:**
```bash
# Descargar modelo
huggingface-cli download nomic-ai/nomic-embed-text-v2-moe-GGUF nomic-embed-text-v2-moe.Q4_K_M.gguf

# Iniciar servidor
llama-server -m nomic-embed-text-v2-moe.Q4_K_M.gguf --embeddings -c 2048
```

### 3.2 VLM: gemma-4-2b-it

| Spec | Valor |
|------|-------|
| Params | 4B |
| Context | 128k tokens |
| VRAM | ~8GB |
| Multimodal | Sí (imágenes + texto) |
| Uso | Análisis de planos e imágenes |

**Uso via LM Studio o Ollama:**
```bash
ollama pull gemma-4-2b-it
```

### 3.3 OCR: PaddleOCR

| Spec | Valor |
|------|-------|
| Tipo | OCR |
| Velocidad | Rápido |
| Idiomas | Múltiples |

---

## 4. Estructura del Proyecto

```
ocr-system/
├── backend/
│   ├── api/
│   │   ├── main.py
│   │   ├── routes/
│   │   │   ├── query.py
│   │   │   ├── ingest.py
│   │   │   └── health.py
│   │   ├── middleware/
│   │   │   └── presupuesto_filter.py
│   │   └── schemas/
│   │       ├── query.py
│   │       └── ingest.py
│   ├── core/
│   │   ├── config.py
│   │   ├── security.py
│   │   └── exceptions.py
│   ├── services/
│   │   ├── vector_store.py
│   │   ├── embedding.py
│   │   ├── vlm.py
│   │   ├── ocr.py
│   │   ├── file_processor.py
│   │   └── postgres_repo.py
│   └── models/
│       ├── documento.py
│       ├── presupuesto.py
│       └── chunk.py
│
├── ingest-worker/
│   ├── main.py
│   ├── watchers/
│   │   └── folder_watcher.py
│   └── processors/
│       ├── pdf_processor.py
│       ├── excel_processor.py
│       ├── image_processor.py
│       ├── email_processor.py
│       └── dwg_processor.py
│
├── scripts/
│   ├── import_initial.sh
│   └── sync_remote.py
│
├── migrations/
│   └── 001_initial_schema.sql
│
├── tests/
│   ├── api/
│   │   └── test_query.py
│   ├── services/
│   │   └── test_vector_store.py
│   └── conftest.py
│
├── docker/
│   ├── docker-compose.yml
│   ├── Dockerfile.backend
│   └── Dockerfile.worker
│
├── models/
│   └── nomic-embed-text-v2-moe.Q4_K_M.gguf
│
├── .env.example
├── requirements.txt
└── README.md
```

---

## 5. Schema de Base de Datos

### 5.1 PostgreSQL

```sql
CREATE TABLE presupuestos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    presupuesto_id VARCHAR(50) UNIQUE NOT NULL,
    nombre VARCHAR(255),
    cliente_nombre VARCHAR(255),
    fecha_creacion TIMESTAMP DEFAULT NOW(),
    fecha_actualizacion TIMESTAMP DEFAULT NOW(),
    ruta_carpeta VARCHAR(500),
    activo BOOLEAN DEFAULT TRUE
);

CREATE TABLE documentos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    presupuesto_id VARCHAR(50) NOT NULL,
    nombre_archivo VARCHAR(255) NOT NULL,
    tipo_archivo VARCHAR(50) NOT NULL,
    ruta_absoluta VARCHAR(500) NOT NULL,
    ruta_relativa VARCHAR(500) NOT NULL,
    hash_sha256 VARCHAR(64),
    size_bytes BIGINT,
    fecha_ingesta TIMESTAMP DEFAULT NOW(),
    embedding_status VARCHAR(20) DEFAULT 'pending',
    FOREIGN KEY (presupuesto_id) REFERENCES presupuestos(presupuesto_id)
);

CREATE TABLE chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    documento_id UUID REFERENCES documentos(id),
    presupuesto_id VARCHAR(50) NOT NULL,
    qdrant_point_id VARCHAR(100),
    texto_preview TEXT,
    chunk_index INTEGER,
    fecha_creacion TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_documentos_presupuesto ON documentos(presupuesto_id);
CREATE INDEX idx_chunks_presupuesto ON chunks(presupuesto_id);
```

### 5.2 Qdrant

```python
Collection: "documentos"
{
    "vectors": { "size": 768, "distance": "Cosine" }
}

# Payload: presupuesto_id, documento_id, tipo_archivo, texto
```

---

## 6. API - Endpoints

```
POST   /api/v1/auth/verify
POST   /api/v1/query           Header: X-Presupuesto-Id
POST   /api/v1/ingest/presupuesto
POST   /api/v1/ingest/scan     Header: X-Presupuesto-Id
GET    /api/v1/ingest/status/{doc_id}
GET    /api/v1/health
```

### Middleware - Filtro Obligatorio

```python
def require_presupuesto_id(request):
    presupuesto_id = request.headers.get("X-Presupuesto-Id")
    if not presupuesto_id:
        raise HTTPException(400, "X-Presupuesto-Id es requerido")
    request.state.presupuesto_id = presupuesto_id
```

---

## 7. Pipeline de Ingestión

```
Carpeta Presupuesto
        │
        ▼
┌─────────────────────────────────────────┐
│  1. SCAN RECURSIVO                       │
└────────┬─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  2. FILE PROCESSOR                       │
│     PDF→pypdf, XLSX→openpyxl             │
│     Imagen→gemma-4-2b-it                │
└────────┬─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  3. TEXT CHUNKING (~500 tokens)          │
└────────┬─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  4. EMBEDDING (nomic-embed-text-v2)     │
└────────┬─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  5. QDRANT INSERT                       │
└────────┬─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  6. POSTGRESQL                          │
└────────┬─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  7. BORRADO (libera espacio)            │
└─────────────────────────────────────────┘
```

---

## 8. Scripts de Transferencia

### 8.1 Importación Inicial

```bash
#!/bin/bash
# import_initial.sh

REMOTE_SERVER="usuario@servidor-remoto"
REMOTE_PATH="/ruta/presupuestos/"
LOCAL_PATH="/srv/presupuestos/tmp/"

mkdir -p "$LOCAL_PATH"

PRESUPUESTOS=$(ssh "$REMOTE_SERVER" "ls -1 '$REMOTE_PATH'")

for presupuesto in $PRESUPUESTOS; do
    echo "Transferiendo $presupuesto..."
    rsync -avz --progress \
        "$REMOTE_SERVER:$REMOTE_PATH$presupuesto/" \
        "$LOCAL_PATH$presupuesto/"

    ssh "$REMOTE_SERVER" "rm -rf '$REMOTE_PATH$presupuesto'"
done

echo "Importación inicial completada."
```

### 8.2 Sync Incremental (Watchdog)

```python
# sync_remote.py
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import subprocess

class CambiosHandler(FileSystemEventHandler):
    def on_created(self, event):
        logger.info(f"Nuevo archivo: {event.src_path}")

    def on_modified(self, event):
        logger.info(f"Archivo modificado: {event.src_path}")

def sync_single_presupuesto(presupuesto_id):
    cmd = ["rsync", "-avz", "--delete",
           f"usuario@servidor-remoto:/ruta/{presupuesto_id}/",
           f"/srv/presupuestos/tmp/{presupuesto_id}/"]
    subprocess.run(cmd)

def start_watchdog():
    observer = Observer()
    observer.schedule(CambiosHandler(), "/srv/presupuestos/tmp/", recursive=True)
    observer.start()
    while True:
        time.sleep(60)
```

---

## 9. Docker Compose

```yaml
version: '3.8'

services:
  backend:
    build: ./docker/Dockerfile.backend
    ports: ["8000:8000"]
    environment:
      - DATABASE_URL=postgresql://ocr:password@postgres:5432/ocr_db
      - QDRANT_URL=http://qdrant:6333
      - LLAMA_SERVER_URL=http://llama-server:8080
    volumes:
      - /srv/presupuestos:/srv/presupuestos:ro
    networks: [ocr-network]

  llama-server:
    image: ghcr.io/ggerganov/llama.cpp:server
    ports: ["8080:8080"]
    volumes:
      - ./models:/models
    command: ["-m", "/models/nomic-embed-text-v2-moe.Q4_K_M.gguf", "--embeddings", "-c", "2048"]
    networks: [ocr-network]

  postgres:
    image: postgres:15-alpine
    environment:
      - POSTGRES_DB=ocr_db
      - POSTGRES_USER=ocr
      - POSTGRES_PASSWORD=password
    volumes: [postgres_data:/var/lib/postgresql/data]
    networks: [ocr-network]

  qdrant:
    image: qdrant/qdrant:latest
    ports: ["6333:6333", "6334:6334"]
    volumes: [qdrant_data:/qdrant/storage]
    networks: [ocr-network]

networks:
  ocr-network: { driver: bridge }

volumes:
  postgres_data:
  qdrant_data:
```

---

## 10. Aislamiento de Seguridad

| Regla |
|-------|
| La otra app NUNCA accede directo a archivos |
| La otra app NUNCA accede directo a Qdrant |
| La otra app NUNCA accede directo a PostgreSQL |
| Header X-Presupuesto-Id es OBLIGATORIO |
| Todo query filtra por presupuesto_id |

```bash
# Test: Sin header → 400 error
curl -X POST http://api/api/v1/query -d '{"pregunta": "test"}'
# 400 "X-Presupuesto-Id es requerido"
```

---

## 11. Fases de Implementación

```
FASE 1: Infraestructura (PostgreSQL + Qdrant + Docker)
FASE 2: Modelos locales (llama-server + gemma)
FASE 3: Script importación inicial (VPN + rsync)
FASE 4: Backend API (endpoints + filtro)
FASE 5: Watchdog + sync incremental
FASE 6: Integración otra app
FASE 7: Produção (hardening + backup)
```

---

## 12. Preguntas Abiertas

1. ¿Detalles de la VPN? (OpenVPN, WireGuard, IPSec?)
2. ¿Velocidad de transferencia? (Ancho de banda?)
3. ¿Script de importación? (Bash + rsync, Python + paramiko?)
4. ¿Watchdog polling interval? (segundos/minutos?)
5. ¿Retención en remoto después de importar?

---

## 13. Timeline

```
SEMANA 1-2:    Infraestructura
SEMANA 3-4:    Modelo embeddings
SEMANA 5-6:    Modelo VLM
SEMANA 7-8:    Script importación
SEMANA 9-10:   Ingest worker
SEMANA 11-12:  Backend API
SEMANA 13-14:  Watchdog
SEMANA 15-16:  Integración otra app
```