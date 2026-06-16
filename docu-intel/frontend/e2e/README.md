# End-to-end tests (Playwright)

## Qué cubren

Un solo test (`happy-path.spec.ts`) ejercita el flujo principal de la app:

1. Login con admin.
2. Carga del dashboard.
3. Búsqueda híbrida con resultados.
4. Apertura del detalle de un documento.
5. Chat con respuesta streamed.
6. Logout.

Los endpoints pesados (`/search/hybrid`, `/ai/ask/stream`) se mockean en el test
mismo con `page.route()`. Esto significa:

- **No** requiere que el LLM local esté corriendo.
- **No** requiere Postgres/Redis con datos.
- **Sí** requiere un backend que acepte el login del admin
  (el endpoint `/auth/login` se ejecuta de verdad).

## Cómo correrlos localmente

```bash
# 1. Levanta el stack completo
cd docu-intel
docker compose --env-file .env -f docker-compose.prod.yml up -d

# 2. (opcional) Crea el admin si no existe
docker compose exec backend python -c "from app.core.config import settings; print(settings.admin_email)"

# 3. Ejecuta los tests
cd frontend
PLAYWRIGHT_BASE_URL=http://localhost:8080 \
  E2E_ADMIN_EMAIL=admin@local \
  E2E_ADMIN_PASSWORD=admin12345 \
  npm run test:e2e
```

## Cómo correrlos en CI

```yaml
# .github/workflows/e2e.yml
- name: Start stack
  run: |
    cd docu-intel
    docker compose --env-file .env -f docker-compose.prod.yml up -d
    docker compose exec backend alembic upgrade head
- name: Seed admin
  run: |
    docker compose exec backend python -c "
    from app.database.init_db import create_initial_admin
    from app.database.session import SessionLocal
    with SessionLocal() as db: create_initial_admin(db)
    "
- name: E2E tests
  run: |
    cd frontend
    npx playwright install --with-deps chromium
    PLAYWRIGHT_BASE_URL=http://localhost:8080 \
      E2E_ADMIN_EMAIL=admin@local \
      E2E_ADMIN_PASSWORD=admin12345 \
      npm run test:e2e
```

## Saltar los tests

```bash
SKIP_E2E=1 npm run test:e2e   # sale con código 0 sin ejecutar nada
```

Útil en jobs de CI que no necesitan el stack (lint, typecheck).

## Por qué mockear `/search/hybrid` y `/ai/ask/stream`

Los endpoints mockeados son los que tienen dependencias pesadas:

- `/search/hybrid` necesita un embedding server (BGE-M3) y un
  re-ranker cargado. Si fallan, el test es de infraestructura,
  no de UI.
- `/ai/ask/stream` necesita un LLM local (Qwen 32B) y
  potencialmente un vision LLM. Un test que espera 8 s de
  inferencia es lento y flaky.

Mockeando esos dos, el e2e corre en **< 5 s** y mide
realmente:

- El routing de React Router.
- La integración TanStack Query (fetch + cache).
- El flujo de autenticación (login real, JWT cookie).
- El render del streaming SSE en `MessageBubble`.
- La limpieza de sesión en logout.

Si cambia el contrato HTTP, los tests fallan y obligan a
actualizar el mock. Es el trade-off consciente entre
realismo y velocidad.
