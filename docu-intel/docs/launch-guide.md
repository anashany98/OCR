# Docu-Intel — Guía de Lanzamiento: Windows + Docker Desktop

> Diseñado para que una IA lo ejecute de forma autónoma en Windows 10/11 con Docker Desktop.
> Secciones marked con `[?]` = la IA debe preguntar al usuario antes de continuar.

---

## Índice

1. [Pre-Requisitos](#1-pre-requisitos)
2. [Instalar Software](#2-instalar-software)
3. [Variables de Entorno](#3-variables-de-entorno)
4. [Estructura de Carpetas](#4-estructura-de-carpetas)
5. [Docker Compose](#5-docker-compose)
6. [Migraciones de Base de Datos](#6-migraciones-de-base-de-datos)
7. [Crear Usuario Admin](#7-crear-usuario-admin)
8. [Verificación Post-Lanzamiento](#8-verificación-post-lanzamiento)
9. [Copia de Seguridad Inicial](#9-copia-de-seguridad-inicial)

---

## 1. Pre-Requisitos

- Windows 10 (Build 19041+) o Windows 11
- Docker Desktop for Windows instalado y corriendo
- WSL 2 habilitado (requerido por Docker Desktop)
- PowerShell 7+ (o CMD si es necesario)
- Al menos 16 GB de RAM (recomendado para OCR)
- 50 GB de espacio libre en disco

### Verificar que Docker funciona

Abrir PowerShell:

```powershell
docker --version
docker compose version
wsl --status
```

Todos deben responder sin errores.

---

## 2. Instalar Software

[?] **¿Ya tienes Docker Desktop instalado?** Si no:

### 2.1 Docker Desktop

1. Descargar de: https://www.docker.com/products/docker-desktop/
2. Instalar con la opción **WSL 2 backend** (NO Hyper-V legacy)
3. Reiniciar el PC
4. Verificar: `docker run hello-world`

### 2.2 Ollama (opcional, para búsqueda semántica real)

[?] **¿Quieres búsqueda semántica real?** (Si no, se usa hash local, que no requiere Ollama)

Si sí, instalar Ollama for Windows:

1. Descargar de: https://ollama.com/download/windows
2. Instalar (corre en segundo plano en `http://localhost:11434`)
3. Descargar el modelo de embedding:

```powershell
ollama pull nomic-embed-text
ollama pull llama3.2
```

Verificar:

```powershell
ollama list
```

---

## 3. Variables de Entorno

### 3.1 Crear archivo

Desde el directorio `docu-intel`:

```powershell
cd C:\Users\PC\Desktop\PROYECTOS\OCR\docu-intel
cp .env.production.example .env.production
```

### 3.2 Completar `.env.production`

Abrir con VS Code o bloc de notas:

```powershell
code .env.production
```

#### Variables obligatorias — cambiar TODO lo que tenga valores de ejemplo:

| Variable | Qué poner | [?] Pregunta |
|---|---|---|
| `POSTGRES_PASSWORD` | Contraseña segura (mín. 16 chars, letras + números + símbolos) | ¿Cuál es la contraseña de PostgreSQL? |
| `DATABASE_URL` | `postgresql://app:{POSTGRES_PASSWORD}@postgres:5432/docuintel` | ¿Rellenado automáticamente? |
| `JWT_SECRET` | Cadena aleatoria mínimo 32 caracteres | ¿Tienes una existente o la genero? |
| `REDIS_PASSWORD` | Contraseña segura diferente a PostgreSQL | ¿Cuál es la contraseña de Redis? |
| `ADMIN_PASSWORD` | Contraseña para el admin | ¿Cuál es la contraseña del admin? |
| `CORS_ORIGINS` | `http://localhost:8080` (o dominio público) | ¿Cuál es el dominio? |

#### Generar secretos automáticamente (PowerShell)

Si no tienes secretos, generarlos:

```powershell
# En .env.production, ejecutar esto para cada variable
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$bytes = New-Object byte[] 32
$rng.GetBytes($bytes)
$secret = [Convert]::ToBase64String($bytes) -replace '\+', 'x' -replace '/', 'X'
Write-Output $secret
```

#### Variables de IA — búsqueda semántica

[?] **¿Quieres búsqueda semántica real?** Si sí, completar:

```env
embedding_provider=openai
embedding_base_url=http://host.docker.internal:11434/v1
embedding_model=nomic-embed-text
embedding_dimensions=768
embedding_fallback_to_hash=true
```

> `host.docker.internal` permite que el contenedor acceda a Ollama corriendo en Windows.

#### Variables de IA — chat

[?] **¿Qué modelo de IA para chat?** Si usas Ollama:

```env
AI_BASE_URL=http://host.docker.internal:11434/v1
AI_MODEL=llama3.2
```

> Si no se configura, el chat usará fallback local sin IA.

---

## 4. Estructura de Carpetas

```powershell
cd C:\Users\PC\Desktop\PROYECTOS\OCR\docu-intel

# Crear carpetas de datos
New-Item -ItemType Directory -Force -Path data\files
New-Item -ItemType Directory -Force -Path data\input\presupuestos
New-Item -ItemType Directory -Force -Path data\input\pedidos
New-Item -ItemType Directory -Force -Path data\input\facturas
New-Item -ItemType Directory -Force -Path data\input\planos
New-Item -ItemType Directory -Force -Path data\input\imagenes
New-Item -ItemType Directory -Force -Path data\input\otros
New-Item -ItemType Directory -Force -Path backups

# Verificar
Get-ChildItem data\
```

---

## 5. Docker Compose

### 5.1 Arrancar todos los servicios

```powershell
cd C:\Users\PC\Desktop\PROYECTOS\OCR\docu-intel

docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

> **Primer arranque**: descarga imágenes Docker (~5-15 minutos depending de la conexión).
> Los contenedores se reconstruyen con `--build`.

### 5.2 Esperar a que estén ready

```powershell
docker compose -f docker-compose.prod.yml ps
```

Esperar hasta que todos muestren **healthy** o **running**:

```
NAME          STATUS
postgres      running (healthy)
redis         running (healthy)
backend       running (healthy)
worker        running (healthy)
ocr-worker    running (healthy)
watcher       running (healthy)
frontend      running (healthy)
```

Si algún servicio no es `healthy` después de 2 minutos, revisar logs:

```powershell
docker compose -f docker-compose.prod.yml logs backend --tail=50
docker compose -f docker-compose.prod.yml logs worker --tail=50
```

### 5.3 Comandos útiles

```powershell
# Ver estado
docker compose -f docker-compose.prod.yml ps

# Logs de un servicio
docker compose -f docker-compose.prod.yml logs backend --tail=100 -f

# Reiniciar un servicio
docker compose -f docker-compose.prod.yml restart backend

# Parar todo
docker compose -f docker-compose.prod.yml down

# Rebuild completo
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

---

## 6. Migraciones de Base de Datos

```powershell
docker compose -f docker-compose.prod.yml exec backend python -m alembic upgrade head
```

Salida esperada: algo como `Running upgrade ... -> xxxxx, message`

Ver historial:

```powershell
docker compose -f docker-compose.prod.yml exec backend python -m alembic history
```

[?] **¿Alguna migración falló?** Si hay errores, revisar los logs y pegar el error completo.

---

## 7. Crear Usuario Admin

[?] **¿Qué contraseña quieres para el admin?** (reemplazar en el comando)

```powershell
docker compose -f docker-compose.prod.yml exec backend python -c "
from app.database.session import SessionLocal
from app.models import User
from app.core.security import hash_password
db = SessionLocal()
try:
    existing = db.query(User).filter(User.email == 'admin@docuintel.local').first()
    if not existing:
        admin = User(
            email='admin@docuintel.local',
            name='Administrador',
            password_hash=hash_password('AQUI_TU_PASSWORD'),
            role='admin'
        )
        db.add(admin)
        db.commit()
        print('Admin creado: admin@docuintel.local')
    else:
        print('Admin ya existe')
finally:
    db.close()
"
```

> **IMPORTANTE**: cambiar `'AQUI_TU_PASSWORD'` por la contraseña real antes de ejecutar.

---

## 8. Verificación Post-Lanzamiento

### 8.1 Health del backend

```powershell
curl http://localhost:8000/health
```

Esperado: `{"status":"ok"}`

### 8.2 Health de IA (si Ollama está corriendo)

```powershell
curl http://localhost:8000/api/admin/ai/health
```

### 8.3 Frontend

Abrir en el navegador:

```
http://localhost:8080
```

Esperado: página de login de Docu-Intel.

### 8.4 Test de login por curl

```powershell
curl.exe -X POST http://localhost:8000/api/auth/login `
  -H "Content-Type: application/json" `
  -d '{"email":"admin@docuintel.local","password":"AQUI_TU_PASSWORD"}'
```

Esperado: respuesta JSON con `access_token`.

### 8.5 Test de ingesta de documento

Copiar un PDF de prueba:

```powershell
Copy-Item "C:\ruta\a\documento.pdf" "C:\Users\PC\Desktop\PROYECTOS\OCR\docu-intel\data\input\otros\"
```

Esperar 30 segundos y verificar que el watcher lo procesó:

```powershell
docker compose -f docker-compose.prod.yml logs watcher --tail=20 | Select-String "documento.pdf"
```

---

## 9. Copia de Seguridad Inicial

[?] **¿Quieres hacer backup inicial?** (Recomendado antes de subir documentos reales)

```powershell
# Backup PostgreSQL
docker compose -f docker-compose.prod.yml exec -T postgres pg_dump -U app -d docuintel -Fc > "C:\Users\PC\Desktop\PROYECTOS\OCR\docu-intel\backups\docuintel_initial.dump"

# Verificar que se creó
Get-ChildItem "C:\Users\PC\Desktop\PROYECTOS\OCR\docu-intel\backups\"
```

---

## Checklist Final

Ejecutar y marcar:

- [ ] Docker Desktop corriendo
- [ ] `.env.production` configurado con secretos seguros
- [ ] Ollama instalado y modelos descargados (si se desea búsqueda semántica)
- [ ] `docker compose up -d --build` exitoso sin errores
- [ ] Migraciones aplicadas (`alembic upgrade head`)
- [ ] Admin creado y login funcional
- [ ] Health del backend responde 200
- [ ] Frontend accesible en `http://localhost:8080`
- [ ] Test de login por curl exitoso
- [ ] Backup inicial realizado

---

## Preguntas que esta IA debe hacer

Si alguna no está respondida en el contexto:

1. **¿Cuál es la contraseña de PostgreSQL?**
2. **¿Cuál es la contraseña de Redis?**
3. **¿Cuál es la contraseña del admin?**
4. **¿Genero los secretos automáticamente o los tienes?**
5. **¿Quieres búsqueda semántica real?** (si no, se usa hash local)
6. **¿Qué modelo de IA para chat?** (Ollama local / OpenAI / sin IA)
7. **¿Qué dominio público usarás?** (o `localhost:8080` para local)

---

## Comandos de Emergencia

```powershell
# Parar todo inmediatamente
docker compose -f docker-compose.prod.yml down

# Ver consumo de recursos
docker stats --no-stream

# Logs agregados de todos los servicios
docker compose -f docker-compose.prod.yml logs --tail=100

# Acceder a PostgreSQL
docker compose -f docker-compose.prod.yml exec postgres psql -U app -d docuintel

# Acceder a Redis
docker compose -f docker-compose.prod.yml exec redis redis-cli -a REDIS_PASSWORD_AQUI

# Ver logs de un servicio específico en tiempo real
docker compose -f docker-compose.prod.yml logs -f backend
```

---

## Estructura de URLs resultante

| Servicio | URL |
|---|---|
| Frontend | http://localhost:8080 |
| API REST | http://localhost:8000 |
| Docs API | http://localhost:8000/docs |
| PgAdmin | http://localhost:5050 (con perfil tools) |