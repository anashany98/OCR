# PLAN DE CORRECCIONES — Docu-Intel
**Fecha:** 3 de Junio 2026  
**Duración estimada:** 5 sprints (1 semana cada uno)  
**Dev requerido:** 1 full-time

---

## RESUMEN EJECUTIVO

| Sprint | Enfoque | Hallazgos | Esfuerzo |
|--------|---------|-----------|----------|
| **1** | Seguridad Crítica | 5 hallazgos | 3-4 días |
| **2** | Seguridad Alta | 6 hallazgos | 4-5 días |
| **3** | Performance + Robustez | 6 hallazgos | 4-5 días |
| **4** | Mejoras Medias | 15 hallazgos | 5-6 días |
| **5** | Mantenibilidad + Bajos | 8 hallazgos | 2-3 días |

---

## SPRINT 1: SEGURIDAD CRÍTICA (5 hallazgos)

### C1. Logout Frontend No Borra Cookie
**Archivo:** `frontend/src/hooks/useAuth.tsx`  
**Esfuerzo:** 15 minutos  
**Riesgo:** Bajo

**Cambios:**
```typescript
// Línea 46 - Reemplazar logout manual por llamada al backend
logout: async () => {
  try {
    await api.logout()  // El backend ya borra con httponly, samesite, secure
  } catch (e) {
    // Ignorar errores de red en logout
  }
  setUser(null)
}
```

**Verificación:**
1. Login → Logout → Refresh página → Debe redirigir a login
2. Verificar en DevTools → Application → Cookies que `docuintel_token` desaparece

---

### C2. IDOR en `/ai/answers/{answer_id}`
**Archivo:** `backend/app/api/routes/ai.py`  
**Esfuerzo:** 30 minutos  
**Riesgo:** Bajo

**Cambios:**
```python
# Líneas 32-37 - Añadir verificación de propiedad
@router.get("/answers/{answer_id}", response_model=AIAnswerRead)
def answer(answer_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.get(AIAnswer, answer_id)
    if not item:
        raise HTTPException(status_code=404, detail="Answer not found")
    
    # Verificar que la respuesta pertenece al usuario
    question = db.get(AIQuestion, item.question_id)
    if not question or question.user_id != user.id:
        raise HTTPException(status_code=404, detail="Answer not found")
    
    return item
```

**Verificación:**
1. Login como usuario A → Crear pregunta → Obtener answer_id
2. Login como usuario B → Intentar acceder al answer_id de A → Debe retornar 404

---

### C3. JWT Acepta Múltiples Algoritmos
**Archivo:** `backend/app/core/security.py`  
**Esfuerzo:** 20 minutos  
**Riesgo:** Bajo

**Cambios:**
```python
# Línea 61 - Añadir validación de algoritmo
def decode_access_token(token: str) -> dict:
    try:
        header = jwt.get_unverified_header(token)
        alg = header.get("alg", "")
        
        # RESTRICCIÓN: Solo aceptar el algoritmo configurado
        if alg != settings.jwt_algorithm:
            raise ValueError(f"Unsupported algorithm: {alg}")
        
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return payload
    except jwt.ExpiredSignatureError:
        raise ValueError("Token has expired")
    except jwt.InvalidTokenError:
        raise ValueError("Invalid token")
```

**Verificación:**
1. Generar token válido → Funciona
2. Fabricar token con `alg: HS384` → Debe fallar con "Unsupported algorithm"

---

### C4. JWT Secret Débil en Entornos No-Local
**Archivo:** `backend/app/core/config.py`  
**Esfuerzo:** 15 minutos  
**Riesgo:** Bajo

**Cambios:**
```python
# Línea 155 - Validación más estricta
@validator("jwt_secret")
def validate_jwt_secret(cls, v, values):
    environment = values.get("environment", "local")
    if environment != "local" and v.startswith("dev_only_"):
        raise ValueError(
            f"JWT_SECRET must be changed from default in {environment} environment"
        )
    if environment != "local" and len(v) < 64:
        raise ValueError("JWT_SECRET must be at least 64 characters in production")
    return v

@validator("admin_password")
def validate_admin_password(cls, v, values):
    environment = values.get("environment", "local")
    if environment != "local" and v.startswith("dev_only_"):
        raise ValueError(
            f"ADMIN_PASSWORD must be changed from default in {environment} environment"
        )
    return v
```

**Verificación:**
1. `ENVIRONMENT=local` + secret débil → Funciona
2. `ENVIRONMENT=staging` + secret débil → Debe fallar al iniciar

---

### C5. `.env` Contiene Secretos Reales
**Archivo:** `.env`, `.gitignore`  
**Esfuerzo:** 30 minutos  
**Riesgo:** Medio (requiere rotar secretos)

**Cambios:**
1. Verificar `.gitignore` incluye `.env`
2. Crear `.env.example` con valores placeholder:
```bash
POSTGRES_USER=docuintel
POSTGRES_PASSWORD=CHANGE_ME_IN_PRODUCTION
JWT_SECRET=CHANGE_ME_AT_LEAST_64_CHARS_RANDOM_STRING_HERE
ADMIN_PASSWORD=CHANGE_ME_STRONG_PASSWORD_HERE
```
3. Rotar todos los secretos en `.env` real
4. Si el repo es público, considerar `git filter-branch` para eliminar `.env` del historial

**Verificación:**
1. `git status` no muestra `.env` como tracked
2. `.env.example` existe con formato correcto

---

## SPRINT 2: SEGURIDAD ALTA (6 hallazgos)

### H1. Admin Routes Sin Role Guard
**Archivos:** `backend/app/api/routes/admin_*.py`  
**Esfuerzo:** 1-2 horas  
**Riesgo:** Bajo

**Cambios:**
Revisar cada endpoint admin y asegurar que use:
```python
from app.core.security import require_roles

@router.get("/admin/users")
def list_users(user: User = Depends(require_roles("admin"))):
    ...
```

**Archivos a revisar:**
- `admin_users.py`
- `admin_documents.py`
- `admin_budgets.py`
- `admin_orders.py`
- `admin_invoices.py`
- `admin_search.py`
- `admin_ai.py`
- `admin_audit.py`
- `admin_watchdog.py`
- `admin_system.py`
- `admin_security.py`
- `admin_budgets_v2.py`

---

### H2. Rate Limiting por IP Detrás de Proxy
**Archivo:** `backend/app/core/rate_limit.py`  
**Esfuerzo:** 30 minutos  
**Riesgo:** Bajo

**Cambios:**
```python
from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request

def get_client_ip(request: Request) -> str:
    """Get real client IP behind reverse proxy"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    return get_remote_address(request)

limiter = Limiter(key_func=get_client_ip)
```

---

### H7. CSRF Token en Login
**Archivos:** `backend/app/api/routes/auth.py`, `frontend/src/hooks/useAuth.tsx`  
**Esfuerzo:** 2-3 horas  
**Riesgo:** Medio

**Cambios Opción A (Recomendada):** Cambiar a Bearer token exclusivamente
- Frontend: Eliminar cookie, usar solo `Authorization: Bearer <token>`
- Backend: Eliminar cookie en login, mantener solo Bearer

**Cambios Opción B:** Añadir CSRF token
- Backend: Generar CSRF token en `/auth/csrf`
- Frontend: Enviar CSRF token en header `X-CSRF-Token`

---

### H8. Content-Security-Policy en Nginx
**Archivo:** `frontend/nginx.conf`  
**Esfuerzo:** 30 minutos  
**Riesgo:** Bajo

**Cambios:**
```nginx
server {
    # ... existing config ...
    
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self';" always;
}
```

---

### H9. pgadmin Bound a Localhost
**Archivo:** `docker-compose.yml`  
**Esfuerzo:** 10 minutos  
**Riesgo:** Bajo

**Cambios:**
```yaml
pgadmin:
    image: dpage/pgadmin4
    profiles: ["tools"]
    environment:
      PGADMIN_DEFAULT_EMAIL: admin@local
      PGADMIN_DEFAULT_PASSWORD: ${PGADMIN_PASSWORD:-admin}
      PGADMIN_CONFIG_SERVER_MODE: 'False'
    ports:
      - "127.0.0.1:5050:80"  # Solo accesible localmente
    volumes:
      - ./data/pgadmin:/var/lib/pgadmin
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped
```

---

### H10. Healthcheck Más Robusto
**Archivos:** `docker-compose.yml`, `docker-compose.prod.yml`  
**Esfuerzo:** 20 minutos  
**Riesgo:** Bajo

**Cambios:**
```yaml
healthcheck:
    test: ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health')\" || exit 1"]
    interval: 30s
    timeout: 10s
    retries: 3
    start_period: 40s
```

O mejor, instalar `curl` en la imagen y usar:
```yaml
test: ["CMD-SHELL", "curl -sf http://localhost:8000/health || exit 1"]
```

---

## SPRINT 3: PERFORMANCE + ROBUSTEZ (6 hallazgos)

### H3. PendingFileRegistry Memory Leak
**Archivo:** `backend/app/ingestion/watcher.py`  
**Esfuerzo:** 1 hora  
**Riesgo:** Bajo

**Cambios:**
```python
class PendingFileRegistry:
    _MAX_ENTRIES = 10000  # Límite máximo
    
    def mark(self, path: str) -> None:
        if len(self._paths) >= self._MAX_ENTRIES:
            # Limpiar entradas más antiguas
            self._cleanup_old_entries()
        self._paths.add(path)
        self._retry_counts[path] = self._retry_counts.get(path, 0) + 1
    
    def _cleanup_old_entries(self):
        """Remove entries with highest retry counts (likely stuck)"""
        sorted_entries = sorted(
            self._retry_counts.items(), 
            key=lambda x: x[1], 
            reverse=True
        )
        for path, count in sorted_entries[:len(sorted_entries)//2]:
            self._paths.discard(path)
            del self._retry_counts[path]
```

---

### H4. Worker Separado en Prod
**Archivo:** `docker-compose.prod.yml`  
**Esfuerzo:** 1 hora  
**Riesgo:** Medio

**Cambios:**
```yaml
worker-fast:
    build:
      context: .
      dockerfile: Dockerfile
    env_file: .env
    environment:
      - CELERY_WORKER_CONCURRENCY=4
      - CELERY_WORKER_QUEUES=text_fast,embeddings
    command: celery -A app.celery_app worker -l info -Q text_fast,embeddings -c 4
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped

worker-maintenance:
    build:
      context: .
      dockerfile: Dockerfile
    env_file: .env
    environment:
      - CELERY_WORKER_CONCURRENCY=1
      - CELERY_WORKER_QUEUES=maintenance
    command: celery -A app.celery_app worker -l info -Q maintenance -c 1
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped
```

---

### H5. datetime.utcnow Deprecado
**Archivos:** `backend/app/models/document.py`, otros modelos  
**Esfuerzo:** 30 minutos  
**Riesgo:** Bajo

**Cambios:**
```python
# En models/document.py
from datetime import datetime, timezone

created_at: Mapped[datetime] = mapped_column(
    DateTime(timezone=True),
    default=lambda: datetime.now(timezone.utc),  # En vez de datetime.utcnow()
    nullable=False,
)
```

---

### H6. PaddleOCR Timeout de Inicialización
**Archivo:** `backend/app/ocr/paddle.py`  
**Esfuerzo:** 1 hora  
**Riesgo:** Bajo

**Cambios:**
```python
import signal
from functools import cached_property

class TimeoutError(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutError("PaddleOCR initialization timed out")

class OCREngine:
    @cached_property
    def _engine(self):
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(60)  # 60 seconds timeout
        try:
            engine = paddleocr.PaddleOCR(
                use_angle_cls=True,
                lang="es",
                show_log=False,
                use_gpu=False,
            )
            return engine
        except TimeoutError:
            logger.error("PaddleOCR initialization timed out after 60s")
            raise
        finally:
            signal.alarm(0)
```

---

### H11. Search Limit Overflow
**Archivo:** `backend/app/api/routes/search.py`  
**Esfuerzo:** 30 minutos  
**Riesgo:** Bajo

**Cambios:**
```python
# Línea 39 - Eliminar multiplicación innecesaria
limit: int = Query(50, ge=1, le=100),
offset: int = Query(0, ge=0),

# Eliminar esta línea:
# limit=limit if user.role == "admin" else limit * 5

# Usar limit directamente en la consulta:
rows = (
    db.query(
        Document.id,
        Document.filename,
        DocumentChunk.text,
        DocumentChunk.page_number,
        func.ts_rank_cd(DocumentChunk.fts, query).label("rank"),
    )
    .join(DocumentChunk, DocumentChunk.document_id == Document.id)
    .filter(DocumentChunk.fts.match(normalized))
    .order_by(text("rank desc"))
    .limit(limit)  # ← Usar limit directamente
    .offset(offset)
    .all()
)
```

---

### H12. Eliminar document_service.py
**Archivo:** `backend/app/services/document_service.py`  
**Esfuerzo:** 30 minutos  
**Riesgo:** Bajo

**Cambios:**
1. Verificar qué archivos importan de `document_service`
2. Cambiar imports directamente a los módulos correctos:
   - `from app.services.document_watcher import ...`
   - `from app.services.document_metadata import ...`
3. Eliminar `document_service.py`

---

## SPRINT 4: MEJORAS MEDIAS (15 hallazgos)

### M1. Redacción de Números Suelos
**Archivo:** `backend/app/services/redaction.py`  
**Esfuerzo:** 1-2 horas

### M2. Token Expiry Handler en Frontend
**Archivo:** `frontend/src/hooks/useAuth.tsx`  
**Esfuerzo:** 2-3 horas

### M3. AbortController en useAuth
**Archivo:** `frontend/src/hooks/useAuth.tsx`  
**Esfuerzo:** 30 minutos

### M4. React Query staleTime
**Archivo:** `frontend/src/main.tsx`  
**Esfuerzo:** 15 minutos

### M5. CSV Injection Protection
**Archivo:** `backend/app/api/routes/search.py`  
**Esfuerzo:** 30 minutos

### M6. PGADMIN_PASSWORD Variable
**Archivo:** `docker-compose.yml`  
**Esfuerzo:** 10 minutos

### M7. Watcher Sleep No Bloqueante
**Archivo:** `backend/app/ingestion/watcher.py`  
**Esfuerzo:** 1 hora

### M8. updated_at en Modelos
**Archivos:** `backend/app/models/document.py`, `user.py`, `budget_scope.py`  
**Esfuerzo:** 1-2 horas

### M9. Full-Text Search con pg_trgm
**Archivos:** `backend/app/models/document.py`, migraciones  
**Esfuerzo:** 2-3 horas

### M10. MIME Validation en Upload
**Archivo:** `backend/app/api/routes/integrations.py`  
**Esfuerzo:** 1 hora

### M11. Token Limit en AI Agent
**Archivo:** `backend/app/ai/agent.py`  
**Esfuerzo:** 1-2 horas

### M12. Migración a PyJWT
**Archivo:** `backend/app/core/security.py`  
**Esfuerzo:** 3-4 horas

### M13. PostgreSQL Password Forzado
**Archivo:** `docker-compose.yml`  
**Esfuerzo:** 10 minutos

### M14. Admin Check en Cache Stats
**Archivo:** `backend/app/api/routes/ai.py`  
**Esfuerzo:** 10 minutos

### M15. CORS Validation
**Archivo:** `backend/app/main.py`  
**Esfuerzo:** 30 minutos

---

## SPRINT 5: MANTENIBILIDAD (8 hallazgos)

### B1. Pin Requirements Minor Versions
**Archivo:** `backend/requirements.txt`  
**Esfuerzo:** 30 minutos

### B2. ESLint Plugin Import
**Archivo:** `frontend/package.json`  
**Esfuerzo:** 30 minutos

### B3. Error Message Sanitization
**Archivos:** Diversos routes  
**Esfuerzo:** 1-2 horas

### B4. X-Content-Type-Options Header
**Archivo:** `backend/app/main.py`  
**Esfuerzo:** 15 minutos

### B5. Docker Status Check en Script
**Archivo:** `scripts/start-docuintel.ps1`  
**Esfuerzo:** 30 minutos

### B6. Backup Integrity Check
**Archivo:** `scripts/backup.ps1`  
**Esfuerzo:** 1 hora

### B7. Multi-Stage Docker Build
**Archivo:** `backend/Dockerfile`  
**Esfuerzo:** 1-2 horas

### B8. Frontend Docker Optimization
**Archivo:** `frontend/Dockerfile`  
**Esfuerzo:** 1 hora

---

## ORDEN DE EJECUCIÓN RECOMENDADO

```
Semana 1 (Sprint 1):
  Día 1-2: C1, C2, C3, C4, C5
  Día 3: Tests de regresión
  Día 4: Deploy a staging
  Día 5: QA y buffer

Semana 2 (Sprint 2):
  Día 1: H1 (admin routes)
  Día 2: H2, H7, H8
  Día 3: H9, H10
  Día 4: Tests de regresión
  Día 5: Deploy a staging + QA

Semana 3 (Sprint 3):
  Día 1: H3, H4
  Día 2: H5, H6
  Día 3: H11, H12
  Día 4: Tests de performance
  Día 5: Deploy a staging + QA

Semana 4 (Sprint 4):
  Día 1-2: M1-M5
  Día 3-4: M6-M15
  Día 5: Tests + Deploy

Semana 5 (Sprint 5):
  Día 1-2: B1-B8
  Día 3: Tests finales
  Día 4: Deploy a producción
  Día 5: Post-deploy monitoring
```

---

## COMANDOS DE VERIFICACIÓN POR SPRINT

### Después de cada Sprint:
```bash
# Backend tests
cd backend
pytest tests/ -v --tb=short

# Frontend build
cd frontend
npm run build

# Type checking
cd frontend
npx tsc --noEmit

# Docker build
docker-compose build --no-cache

# Lint
cd backend
flake8 app/
cd frontend
npm run lint
```

### Después de Sprint 1 (Crítico):
```bash
# Verificar JWT validation
python -c "from app.core.security import decode_access_token; print('JWT OK')"

# Verificar logout
curl -X POST http://localhost:8000/api/v1/auth/logout -v
# Verificar que cookie se borra
```

### Después de Sprint 2 (Alto):
```bash
# Verificar CSP headers
curl -I http://localhost:3000 | grep -i content-security

# Verificar pgadmin solo local
netstat -an | grep 5050  # Debe ser 127.0.0.1
```

---

## DEPENDENCIAS ENTRE SPRINTS

```
Sprint 1 → Sin dependencias (empezar aquí)
Sprint 2 → Depende de Sprint 1 (C5 debe resolverse antes de H1)
Sprint 3 → Independiente de Sprint 2
Sprint 4 → Puede empezar después de Sprint 2
Sprint 5 → Independiente
```

---

## RIESGOS Y MITIGACIONES

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|---------|------------|
| Breaking change en JWT | Media | Alto | Mantener backward compatibility, test con tokens existentes |
| CORS issues | Baja | Alto | Test exhaustivo de endpoints cross-origin |
| Performance regression | Media | Medio | Benchmark antes/después de cada cambio |
| Database migration needed | Baja | Medio | Algunos cambios requieren nueva migración |
| Frontend cache issues | Alta | Bajo | Version busting en imports |

---

## DEFINICIÓN DE ÉXITO

- [ ] Todos los hallazgos Críticos (C1-C5) corregidos y verificados
- [ ] Todos los hallazgos Altos (H1-H12) corregidos
- [ ] Tests pasando al 100%
- [ ] Build exitoso en frontend y backend
- [ ] Docker compose levantando correctamente
- [ ] No hay regresiones funcionales
- [ ] Performance igual o mejor que antes
- [ ] Documentación actualizada
