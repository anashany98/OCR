# 🎨 Brief de rediseño del Frontend — Docu-Intel

> 📌 **Documento de trabajo para una IA de código** (Cursor / Claude Code / similar).
> Objetivo: **rediseñar por completo la UI/UX del frontend** manteniendo intacta la capa de datos.
> Trabajar **siempre** en la rama `redesign/frontend-v2` (ya creada). Entrega **big-bang** en esa rama, avanzando por fases con **un commit por fase**.
> La app debe **arrancar y ser desplegable** al final de cada commit.

---

## 0. Contexto y reglas

### 0.1 Dónde está el código
- **Frontend:** `docu-intel/frontend/` (NO en la raíz del repo; está anidado bajo `docu-intel/`).
- **Backend (solo lectura para ti):** `docu-intel/backend/`. No lo toques; lo usas solo para entender la API.
- **Stack actual:** React `^18.3.1` + TypeScript `^5.6.3` + Vite `^5.4.11` + React Router `^6.28.0` + TanStack Query `^5.59.16` + Tailwind `^3.4.15` + sonner + lucide-react + cmdk + Sentry. Alias `@/` → `src/`. Prettier: `semi:false, singleQuote:false, trailingComma:"all", printWidth:100, tabWidth:2`.

### 0.2 Qué se CONSERVA intacto (NO lo rompas)
La **capa de datos** está bien y se mantiene tal cual. Solo puedes renombrar/eliminar **duplicados** explícitamente señalados en §3.

Archivos que **no se tocan** (interfaces y comportamiento estables):
- `src/api/*` — todos los clientes HTTP (`core.ts`, `auth.ts`, `documents.ts`, `plans.ts`, `search.ts`, `ai.ts`, `business.ts`, `admin.ts`, `integrations.ts`, `learning.ts`, `client.ts`). Excepciones: ver §7 (centralizar `API_BASE_URL`, eliminar tipos duplicados de `plans.ts`).
- `src/types/api.ts` — fuente única de tipos del dominio.
- `src/hooks/useAuth.tsx` — auth basada en **cookie/session** (`credentials: "include"`). No añadir tokens JWT ni tocar el flujo de login/logout.
- `src/hooks/useTheme.ts`, `src/hooks/useConfirm.tsx`, `src/hooks/useWorkInboxCount.ts`, `src/hooks/useAiHistory.ts`, `src/hooks/useCountUp.ts`.
- **Hooks de datos por feature** (`src/pages/<feature>/use*.ts(x)`): `useChat`, `useDashboard`, `useDocumentDetail`, `useOcrReviewPage`, `usePlanAnnotation`, `usePlanSymbols`, `useZoomPan`, `usePlansPage`, `useSearchPage`, `useWorkInbox`, y los `useAdmin*Data.ts`. Conservas su firma pública; las páginas nuevas los consumen igual.
- `src/lib/utils.ts` (formateo es-ES/EUR), `src/lib/toast.ts`, `src/lib/status.ts`, `src/lib/sentry.ts`, `src/lib/operations.ts`, `src/lib/documentViews.ts`, `src/lib/useMutationWithToast.ts`.
- `src/navigation/config.ts` — **fuente única de verdad** de navegación y títulos (preserva `NAV_GROUPS`, `NAV_ITEMS_BY_PATH`, `titleForPath`, `ADMIN_TABS`, `canSeeNavItem`).
- `src/routes/router.tsx` — estructura de rutas (lazy loading, guards por rol, `RequireAuth`, `RequireRole`, `errorElement`, ruta 404 `*`). Conserva el mapeo path→componente.

### 0.3 Qué se REDISEÑA
- **Estética y diseño visual** completo: tema, tipografía, color, spacing, sombras, densidad.
- **Shell y navegación:** `AppShell`, `Sidebar`, `SidebarDrawer`, topbar, `CommandPalette`, breadcrumbs.
- **Componentes de presentación y layout** (`components/layout/*`, `components/ui/*`).
- **Flujos y composición de pantallas** (cómo se ordena y relaciona la información en cada página).
- **UX de tablas y formularios** (sort, paginación, validación, confirmaciones).

### 0.4 Reglas obligatorias
1. **No romper interfaces de la capa de datos** (lista en §0.2). Las páginas consumen los hooks y el `api` existentes.
2. **Un commit por fase** (`redesign(fase-N): <descripción>`, mensajes en español). La app arranca y compila al final de cada fase.
3. `npm run lint` (con `--max-warnings 50`), `npm run build` y `npm run test` **en verde** al final de cada fase. No bajes los umbrales de cobertura (`vitest.config.ts`).
4. **Añade tests** para los nuevos primitivos compartidos (`DataTable`, `Form`) y mantiene los existentes en verde.
5. Toda dependencia nueva debe añadirse a `package.json` y comprobarse que instala.
6. **Cero `window.alert` / `window.confirm`** al terminar. Usa `useConfirm()` (promise-based) o `Dialog`/`AlertDialog` de Radix.
7. No hardcodes secretos. No toques la auth (cookie session).
8. Si una decisión **rompe compatibilidad** con un endpoint o una interfaz que §0.2 dice conservar, **detente** y documenta en la sección "Dudas / Decisiones pendientes" al final de este archivo.
9. Respeta el modo dark/light existente (`.dark` en `<html>`, persistido en `localStorage["docu-intel:theme"]`).

---

## 1. Decisiones de diseño (acordadas con el usuario)

| Eje | Decisión |
|---|---|
| **Alcance** | Rehacer UI/UX. **No** reescritura total de lógica. Capa de datos intacta. |
| **Estética** | **Dashboard SaaS moderno** (referencias: Linear, Vercel, Notion, GitHub). Limpio, denso, rápido, profesional. |
| **Color** | **Dark-first** con light mode pulido. Grises neutros (slate/zinc), **accent sutil** (azul/violeta sobrio), semánticos success/warning/danger/info claros. **Adiós** a la paleta editorial: terracota, papel crema, Fraunces serif. |
| **Tipografía** | Sans (Inter / system-ui) para UI; **mono** (JetBrains Mono / ui-monospace) **solo para datos numéricos y técnicos**. Sin serif display. |
| **Layout** | Sidebar persistente y **colapsable** en escritorio + drawer en móvil. Topbar con breadcrumbs + acciones + búsqueda global + estado + usuario. Densidad configurable (cómoda / compacta). |
| **Entrega** | **Big-bang en la rama `redesign/frontend-v2`**, fases 0→8, un commit por fase. |

### 1.1 Stack de componentes (libertad total; recomendado)
- **shadcn/ui + Radix UI completo** (añadir): `dialog`, `alert-dialog`, `sheet`, `popover`, `dropdown-menu`, `select`, `tabs`, `tooltip`, `checkbox`, `switch`, `separator`, `scroll-area`, `avatar`, `skeleton`, `label`, `accordion`, `toggle-group`, `radio-group`, `command` (mejorar el actual), `form` (integrado con react-hook-form).
- **`react-hook-form` + `zod` + `@hookform/resolvers`** para todos los formularios (login, crear usuario, crear cliente, crear tarea manual, crear regla, escala de plano, etc.).
- **Activar `@tanstack/react-table`** (ya en `package.json` sin usar) en un `DataTable<T>` genérico.
- **Activar `recharts`** (ya en `package.json` sin usar) para minigráficos del dashboard si procede.
- **Mantener:** Tailwind 3, `cn()` (`clsx`+`tailwind-merge`), sonner, cmdk, lucide-react, Sentry.

> Versión de React: `^18.3.1`. No subir a React 19 en este rediseño (rompe Radix antiguo y TipTap-type deps). Usa versiones de Radix compatibles con React 18.

---

## 2. Inventario actual (para que no redescubras)

### 2.1 Páginas y rutas (20 pantallas)
Definidas en `src/routes/router.tsx`. Roles: `admin`, `gestor`, `operario`, `auditor`. Guards: `RequireAuth` (autenticado), `RequireRole({roles})`.

| Path | Componente | Rol mínimo |
|---|---|---|
| `/login` | `pages/LoginPage.tsx` | público |
| `/` | `pages/dashboard/DashboardPage.tsx` | autenticado |
| `/documents` | `pages/documents/DocumentsPage.tsx` | autenticado |
| `/documents/:id` | `pages/document/DocumentDetailPage.tsx` | autenticado |
| `/documents/:id/annotate-plan` | `pages/plano/PlanoAnnotationPage.tsx` | `admin`,`gestor` |
| `/work-inbox` | `pages/work-inbox/WorkInboxPage.tsx` | autenticado |
| `/ocr-review` | `pages/ocr-review/OcrReviewPage.tsx` | autenticado |
| `/search` | `pages/search/SearchPage.tsx` | autenticado |
| `/jobs` | `pages/JobsPage.tsx` | `admin` |
| `/budgets` | `pages/BudgetsPage.tsx` | autenticado |
| `/orders` | `pages/OrdersPage.tsx` | autenticado |
| `/invoices` | `pages/InvoicesPage.tsx` | autenticado |
| `/reconciliation` | `pages/ReconciliationPage.tsx` | autenticado |
| `/plans` | `pages/plans/PlansPage.tsx` | `admin`,`gestor` |
| `/chat` | `pages/chat/ChatPage.tsx` | autenticado |
| `/admin` (shell) + `/admin/{operativa,sistema,integraciones,acceso,calidad,aprendizaje}` | `pages/AdminPage.tsx` + `pages/admin/Admin*Page.tsx` | `admin` |
| `*` | `pages/NotFoundPage.tsx` | autenticado |

### 2.2 Organización del código (convención a PRESERVAR)
Cada feature es una **carpeta** con: `XxxPage.tsx` (shell fino) + `components.tsx` (sub-componentes) + `useXxx.ts` (hook de datos). Esta separación **container/component/hook** es deliberada (refactor F8) — consérvala.

### 2.3 Archivos monolíticos a ROMPER (objetivo: ninguno > ~350 líneas)
- `pages/admin/AdminSystemPage.tsx` — **951 líneas** (scroll-spy con 6 secciones; duplica `StatusBadge` local).
- `pages/admin/AdminAccessPage.tsx` — **821 líneas** (`AccessView` con ~50 props).
- `pages/admin/AdminLearningPage.tsx` — **788 líneas** (usa `window.alert` en stubs; duplica `StatusBadge`).
- `pages/plano/components.tsx` — **973 líneas**.
- `pages/documents/DocumentsPage.tsx` — **586 líneas**.
- `pages/document/DocumentDetailPage.tsx` — **536 líneas** (+ `detailSections.tsx` 486 + `components.tsx` 429).
- `pages/admin/AdminOperationalPage.tsx` — **534 líneas**.
- `pages/plans/PlansPage.tsx` — **425 líneas**.
- `pages/admin/AdminQualityPage.tsx` — **404 líneas**.

### 2.4 Deuda técnica detectada (corrígela durante el rediseño)
1. **`ConfirmDialogHost` NO está montado** en `src/main.tsx`. Hoy `useConfirm()` avisa y devuelve `false` en producción. → **Montarlo en el provider tree.**
2. **`window.alert` / `window.confirm`** residuales en: `pages/document/DocumentDetailPage.tsx` (stubs), `pages/admin/AdminLearningPage.tsx` (stubs), `pages/chat/ConversationSidebar.tsx` (delete). → Reemplazar por `useConfirm()` o `Dialog`.
3. **Tablas sin sort ni paginación** (todas son `<table>` a mano; `react-table` está en deps sin usar). Solo `DocumentsPage` pagina (server-side, 25). → `DataTable<T>` con sort + paginación.
4. **Formularios a mano** sin validación (login, crear usuario, crear cliente de integración, crear tarea manual, crear regla, escala de plano). → `react-hook-form` + `zod`.
5. **Tipos duplicados:** `Plan`, `PlanRoom`, `PlanDimension` definidos en `api/plans.ts` **y** en `types/api.ts`. → Quedarse con `types/api.ts`; importar desde allí.
6. **`API_BASE_URL` leído 3 veces** (`api/core.ts`, `api/ai.ts`, `api/search.ts`). → Centralizar en un único sitio y exportar.
7. **Query keys inconsistentes:** la mayoría son strings planos (`["documents"]`, `["work-inbox"]`), pero planos usan jerarquía (`["plans", planId, "rooms"]`). → Key factory en `lib/queryKeys.ts`.
8. **`recharts` y `@tanstack/react-table`** en `package.json` pero **sin usar**. → Úsalos o, si decides no usarlos, elimínalos.
9. **`components/admin/LearningHealthCard.tsx`** está **huérfano** (no lo importa nadie). → Integrarlo en `AdminLearningPage` o eliminarlo.
10. **`StatusBadge` duplicado** localmente en `AdminSystemPage.tsx` y `AdminLearningPage.tsx` (no usan el compartido `components/layout/StatusBadge.tsx`). → Usar el compartido.
11. **`LoadingState.tsx`** aún usa `bg-slate-100`/`text-muted-foreground` sin migrar. → Skeletons con tokens nuevos.
12. **Badges con hex hardcodeado** (`ConfidenceBadge`, `PriorityBadge`). → Usar tokens semánticos.

### 2.5 Lo que YA está bien (no lo rehagas)
Las tareas **F1–F9** del `AGENTS.md` raíz del repo **ya están implementadas**:
- F1: `React.lazy` + `Suspense` en todas las páginas (helper `lazyNamed` en `router.tsx`).
- F2: rutas protegidas por rol en el router (`RequireRole` + `protectedPage`).
- F3: `errorElement` + ruta 404 `*`.
- F4: `AdminPage` ya dividido en 6 sub-rutas (`/admin/{tab}`).
- F6: endpoint de conteo (`useWorkInboxCount` → `api.workInboxCount`).
- `PermissionGate` con modos `hide`/`disable`/`message`.
- `navigation/config.ts` es la **fuente única** de títulos/labels.

**Preserva todo esto.** El rediseño construye encima.

---

## 3. Fases de ejecución

> Cada fase: **un commit** `redesign(fase-N): …`. La app compila y arranca al terminar la fase.

### FASE 0 · Fundación (tokens + primitivos + provider tree)
**Archivos:** `src/index.css`, `tailwind.config.ts`, `src/components/ui/*`, `src/main.tsx`.

1. Reescribe `src/index.css` con design tokens **"SaaS moderno"**:
   - Escala de grises neutra: `--bg-canvas`, `--bg-surface`, `--bg-surface-2`, `--bg-surface-3`, `--border` (1/2/3), `--text-primary`, `--text-secondary`, `--text-muted`.
   - Accent sobrio (`--accent`, `--accent-hover`, `--accent-foreground`).
   - Semánticos: `--success`, `--warning`, `--danger`, `--info` (+ sus `*-foreground`).
   - Variantes `:root` (light) y `.dark` (dark-first). Radios pequeños (`--radius` ~0.5rem), sombras sutiles, sin `--shadow-paper`.
   - Sin importar tipografía serif de Google Fonts; usa `Inter` (o system-ui) y `JetBrains Mono` (o `ui-monospace`). Carga vía Google Fonts o `@fontsource` (añade dep si usas `@fontsource/inter`).
2. Actualiza `tailwind.config.ts`: mapea los tokens a `theme.extend.colors`/`boxShadow`/`borderRadius`/`fontSize`/`fontFamily`. Mantén darkMode `"class"`.
3. Regenera/amplía `src/components/ui/` con shadcn completo: `button`, `input`, `textarea`, `label`, `card`, `badge`, `table`, `dialog`, `alert-dialog`, `sheet`, `popover`, `dropdown-menu`, `select`, `tabs`, `tooltip`, `checkbox`, `switch`, `separator`, `scroll-area`, `avatar`, `skeleton`, `accordion`, `toggle-group`, `radio-group`, `command`, `form` (con `react-hook-form` + `zod`). Mantiene `cn()` y los variantes `cva` donde existan.
4. `src/main.tsx`: árbol de providers = `initSentry()` → `QueryClientProvider` → `AuthProvider` → `ConfirmProvider` (monta **`<ConfirmDialogHost />`**, bug actual) → `RootErrorBoundary` → `RouterProvider` → `<Toaster />`. Usa el `QueryClient` existente (mismos defaults).
5. `npm i` las deps nuevas; `npm run lint && npm run build && npm run test`.

**Criterio de aceptación Fase 0:** la app arranca con tema nuevo (light+dark), primitivos disponibles, `ConfirmDialogHost` operativo, todo verde.

---

### FASE 1 · Shell y navegación
**Archivos:** `src/components/layout/{AppShell,Sidebar,SidebarDrawer,CommandPalette,Breadcrumbs,PageHeader,PageToolbar,EmptyState,LoadingState}.tsx`, `src/navigation/config.ts`, `src/routes/router.tsx` (solo añadir `handle` metadata).

1. `AppShell.tsx` nuevo: layout `h-screen` con **sidebar persistente y colapsable** en `lg+` (toggle que guarda el estado en `localStorage["docu-intel:sidebar"]`), **drawer** solo en móvil. Topbar con: breadcrumb (derivado del router), título de página, spacer, búsqueda global (abre command palette), **badge de tareas** accesible (`aria-label="N tareas pendientes"`, `aria-current` en item activo), **estado del sistema** (dot verde/ámbar), **theme toggle**, **user menu** con `DropdownMenu` real (no menú manual), logout. Elimina el `SidebarNav` legacy duplicado.
2. `Sidebar.tsx`: grupos colapsables, densidad ajustable, active state claro (barra/píldora accent), iconos `lucide-react`, badge de inbox (cap "99+"), tag `beta` si aplica. Conserva la sección "Recientes" (`useRecentNav`).
3. `CommandPalette.tsx`: refactor con `command` shadcn; mantén `NAV_GROUPS` filtrado por rol y los recientes.
4. **Títulos y breadcrumbs** derivados del **router** (`route.handle` + `useMatches`) en lugar de `titleForPath`. Extiende `navigation/config.ts` para exponer `handle` por ruta; `titleForPath` puede quedar como fallback. Cubre el caso hoy roto: `/documents/:id/annotate-plan`.
5. `PageHeader` (3 variantes: `default`/`plain`/`minimal`), `PageToolbar`, `Breadcrumbs` (auto "Inicio"), `EmptyState` (con ilustraciones neutras — ver Fase 7), `LoadingState` (**skeletons**, no spinner de texto).
6. `npm run lint && npm run build && npm run test`.

**Criterio Fase 1:** navegación fluida desktop+mobile; título y coincidencia activa sin drift; sesión carga con skeleton; a11y básica en sidebar/badges.

---

### FASE 2 · Primitivos compartidos de datos y forms
**Archivos nuevos:** `src/components/ui/data-table.tsx`, `src/components/ui/form.tsx` (campos: `FormField`, `FormInput`, `FormSelect`, `FormTextarea`, `FormCheckbox`). **Modifica:** `src/components/layout/{MetricTile,StatusBadge,ConfidenceBadge,PriorityBadge}.tsx`, nuevo `src/lib/queryKeys.ts`, nuevo `src/lib/exportCsv.ts`.

1. **`DataTable<T>`** con `@tanstack/react-table`: columnas declarativas, sort (client/server), paginación (client/server con `pageIndex`/`pageSize`), selección (checkbox + select-all), densidad (cómoda/compacta), empty/loading (skeleton) states, fila clickeable (master-detail), soporte para columnas de acciones. API simple: `<DataTable columns={...} data={...} pagination={...} onRowClick={...} />`.
2. **`Form`** con `react-hook-form` + `zod` + `@hookform/resolvers/zod`: `<Form schema={zodSchema} onSubmit={...} defaultValues={...}>` con `<FormField name="...">` + `<FormInput/>`/`<FormSelect/>`/`<FormTextarea/>`/`<FormCheckbox/>`. Errores accesibles (`aria-invalid`, mensaje bajo el campo).
3. **`useConfirm`** ya existe (`hooks/useConfirm.tsx`); intégralo con el nuevo `Dialog`/`AlertDialog` shadcn (reemplaza `confirm-dialog.tsx` manual o unifícalo).
4. Reconstruye con tokens nuevos: `MetricTile` (tonos success/warning/danger/info/neutral), `StatusBadge` (registry de ~30 estados, sin hex hardcodeado), `ConfidenceBadge` (umbrales 0.85/0.70), `PriorityBadge`, `DocumentProgressBar` (4 etapas pipeline).
5. **`lib/queryKeys.ts`**: key factory jerárquico (`queryKeys.documents.list(filters)`, `.detail(id)`, `.pages(id)`, etc.). Refactoriza los hooks existentes para usarlo **sin cambiar sus firmas públicas**.
6. **`lib/exportCsv.ts`**: utilidad reutilizable de export CSV (reemplaza los exporters ad-hoc de invoices/search).
7. `npm run lint && npm run build && npm run test` (+ tests nuevos de `DataTable` y `Form`).

**Criterio Fase 2:** cero `window.alert/confirm` tras esta fase donde se hayan tocado; `DataTable` y `Form` con tests; badges sin hex hardcodeado.

---

### FASE 3 · Páginas núcleo (operación diaria) — prioridad alta
**Archivos:** `pages/dashboard/*`, `pages/work-inbox/*`, `pages/documents/*`, `pages/document/*`, `pages/chat/*`, `pages/search/*`, `pages/ocr-review/*`.

1. **`DashboardPage`** (`useDashboard` se conserva): grid de widgets KPI modulares (`MetricTile` + minigráficos con `recharts` si procede), layout responsivo, alertas y snapshot del día (`buildTodaySnapshot` de `lib/operations.ts`).
2. **`WorkInboxPage`** (`useWorkInbox` se conserva): `Tabs`/segmented por prioridad o estado, `DataTable` para la cola, **bulk actions** en toolbar de selección (`BatchActionsCard`), `Sheet` lateral para nueva tarea manual con `Form`+`zod`. Conserva helpers puros (`groupByPriority`, `filterTasks`, `getKindConfig`).
3. **`DocumentsPage`** (`useDocuments` o inline → extraer hook si procede): `DataTable` con react-table (paginación server existente + sort + densidad), filtros en `Sheet` lateral, drag-drop upload mejorado (carpeta vía `webkitdirectory`), **saved views** como `Tabs` (`lib/documentViews.ts`). Selección múltiple + reproceso bulk con `useConfirm`.
4. **`DocumentDetailPage`** (536 → partir): **split-pane** visor | panel lateral con `Tabs` (Info / OCR / Entidades / Timeline / Grafo). Visor con thumbnails en `ScrollArea`. **Elimina el toolbar duplicado** (`actions.tsx` vs inline → uno solo). Conserva `useDocumentDetail` y el deep-link `#page=N&block=M`.
5. **`ChatPage`** (`useChat` se conserva, hook de 579 líneas): chat moderno — sidebar de conversaciones colapsable (`Sheet` en móvil), área de mensajes con `ScrollArea` + auto-scroll, composer con filtros en `Collapsible`/`Sheet`, sources como chips con deep-link, follow-ups, badges de confianza. Conserva streaming SSE y persistencia en `localStorage`.
6. **`SearchPage`** (`useSearchPage` se conserva): búsqueda unificada con **facets** en sidebar, modos (`hybrid`/`semantic`/`text`/`guided`) con `Tabs`, resultados ricos (excerpt + badges + thumbnail), export CSV/JSON (usa `lib/exportCsv.ts`).
7. **`OcrReviewPage`** (`useOcrReviewPage` se conserva): cola **master-detalle** con `Tabs` (Preview / OCR / Blocks), approve/reject con `Form`+`zod`, banner re-embed.
8. `npm run lint && npm run build && npm run test`.

**Criterio Fase 3:** flujos operativos claros; un solo patrón de master-detalle y de filtros; chat/search/documentos usables.

---

### FASE 4 · Páginas de negocio
**Archivos:** `pages/BudgetsPage.tsx`, `pages/OrdersPage.tsx`, `pages/InvoicesPage.tsx`, `pages/ReconciliationPage.tsx`, `pages/JobsPage.tsx`.

1. **`BudgetsPage` + `OrdersPage`**: master-detail con `DataTable` (selección → líneas en panel inferior o `Sheet`).
2. **`InvoicesPage`**: grid de métricas (`MetricTile`) + `DataTable` + export CSV (`lib/exportCsv.ts`).
3. **`ReconciliationPage`**: incidentes con filtros, bulk resolve, generación de issues con `useConfirm`.
4. **`JobsPage`** (admin): monitor de colas con `refetchInterval: 5000`, retry/cancel con `DropdownMenu`.
5. `npm run lint && npm run build && npm run test`.

**Criterio Fase 4:** CRUD consistente; sin tablas a mano; sin `window.confirm`.

---

### FASE 5 · Admin (romper los 3 monolitos)
**Archivos:** `pages/AdminPage.tsx`, `pages/admin/Admin*Page.tsx`, `pages/admin/shared.tsx`.

Objetivo: **ningún archivo de admin > ~350 líneas**.

1. **`AdminPage`** shell: navegación de pestañas moderna (`Tabs` o sub-sidebar de sección), reprocess confirm contextual. Conserva `AdminReprocessContext`.
2. **`AdminSystemPage`** (951 → partir por sección): Postgres / Redis-Workers / Storage / Readiness / Users-Notifications / AI-config como **componentes dedicados** (un archivo por sección). Scroll-spy con `Tabs` o `ScrollArea`+anchor. **Usa el `StatusBadge` compartido** (elimina el local).
3. **`AdminAccessPage`** (821 → partir el `AccessView` de ~50 props): sub-vistas separadas — cadenas, hoteles, folder-rules, access-groups, sensitive-tags, simulador, rule-preview, redaction-preview. Cada una con su `Form`+`zod`.
4. **`AdminLearningPage`** (788 → partir): suggestions list, detail `Dialog`, history `Accordion`, patterns list. **Elimina `window.alert`** en stubs (implementa o marca "Próximamente" con `Badge`).
5. **`AdminQualityPage`**: duplicates/quarantine como `DataTable` con bulk actions (confirm-guarded).
6. **`AdminIntegrationsPage`**: clients CRUD + sandbox con `Dialog`. Banner de API key one-time.
7. **`AdminOperationalPage`** (534 → moderar): bulk reprocess form con `Form`+`zod`, problem docs como `DataTable`.
8. Decide sobre `components/admin/LearningHealthCard.tsx` (huérfano): **integrar** en `AdminLearningPage` o **eliminar**.
9. `npm run lint && npm run build && npm run test`.

**Criterio Fase 5:** ningún archivo de admin > ~350 líneas; cero stubs con `window.alert`; un solo `StatusBadge`.

---

### FASE 6 · Planos / anotación
**Archivos:** `pages/plans/*`, `pages/plano/*`.

1. **`PlansPage`** (`usePlansPage` + `scales.ts` se conservan): editor moderno de escala/habitaciones/cotas. `DataTable` inline-editable para habitaciones, `Form`+`zod` para escala (parsing `1:100`, `A×B m`). Flag `beta` mantenido.
2. **`PlanoAnnotationPage`** (`usePlanAnnotation`, `usePlanSymbols`, `useZoomPan` se conservan; `components.tsx` 973 → partir): toolbar de herramientas con `ToggleGroup`, canvas SVG con overlay moderno, paneles laterales (`Sheet`/`Tabs`), zoom/pan correctamente cableado (`useZoomPan`), symbol legend, symbol overlay. **Preserva** hit-testing ray-cast, snap-to-line, building de polígono, cálculo de escala px→m, vision suggestions.
3. `npm run lint && npm run build && npm run test`.

**Criterio Fase 6:** herramienta de anotación usable; lógica geométrica preservada.

---

### FASE 7 · Auth, consolidación y limpieza
**Archivos:** `pages/LoginPage.tsx`, `pages/NotFoundPage.tsx`, `src/components/illustrations/*`, `src/api/{core,ai,search,plans}.ts`, `src/lib/*`.

1. **`LoginPage`**: split-screen moderno (brand/marketing a la izquierda, form a la derecha). Form con `react-hook-form`+`zod` (email + password, errores accesibles). Conserva redirect a `/` si ya autenticado.
2. **`NotFoundPage`**: fallback 404 coherente con el nuevo look.
3. **Ilustraciones** (`EditorialIllustrations.tsx`): si chocan con el estilo SaaS, sustitúyelas por ilustraciones neutras mono-línea o por composiciones de iconos `lucide-react` + `EmptyState`. Mismas 9 variantes (documents, tasks, search, inbox, chat, reconciliation, jobs, plans, invoices).
4. **Eliminar duplicados de tipos:** `Plan`/`PlanRoom`/`PlanDimension` solo en `types/api.ts`; `api/plans.ts` los importa desde allí. Mismo criterio para `LearningHealthSnapshot` / `AIStreamEvent` si están duplicados.
5. **Centralizar `API_BASE_URL`**: un único `const API_BASE_URL = ...` exportado desde `api/core.ts`; `ai.ts` y `search.ts` lo importan.
6. **Estandarizar `useMutationWithToast`** (`lib/useMutationWithToast.ts`): úsalo en todos los mutations nuevos; refactoriza los hooks que hacen `notify.success/error` manual donde sea trivial.
7. `npm run lint && npm run build && npm run test`.

**Criterio Fase 7:** sin tipos duplicados; una sola `API_BASE_URL`; mutations consistentes; login/400 modernos.

---

### FASE 8 · Testing y QA
1. Tests existentes (`lib/*.test.ts`, hooks `use*.test.ts`, `composeQuestion.test.ts`, etc.) en **verde**. Adapta los que dependan de tokens/UI.
2. Tests nuevos para `DataTable`, `Form`/`FormField`, y primitivos compartidos clave.
3. `npm run lint && npm run build && npm run test` limpios.
4. **Auditoría a11y básica**: breadcrumbs, badges (`aria-label`), dropdowns, dialogs (focus trap), `aria-current` en nav activo.
5. Verifica el **bundle inicial** (lazy loading mantenido; sin regresión — revisa `vite build` y los chunks).
6. **Flujos end-to-end manuales** (documenta en el README del rediseño o en el PR): login → dashboard → documents → document-detail → chat → admin (cada tab) → plans → annotate-plan → work-inbox → search.

**Criterio Fase 8:** todo verde; a11y sin errores graves; bundle sin regresión; flujos verificados.

---

## 4. Checklist de aceptación global (márcalo tú al terminar)

- [ ] App funcional y desplegable en **cada commit** de la rama.
- [ ] Estética **SaaS moderno** aplicada en las **20 pantallas** (light + dark).
- [ ] **Cero** `window.alert` / `window.confirm` en todo `src/`.
- [ ] Todos los forms con validación **`zod`** (login, crear usuario, crear cliente, crear tarea manual, crear regla, escala, etc.).
- [ ] Tablas con **sort + paginación** donde aplique (vía `DataTable`).
- [ ] **Consistencia visual total**: un scaffold de página, una paleta, un sistema de spacing/radius/shadow.
- [ ] Ningún archivo de **admin > ~350 líneas** (romper `AdminSystemPage`, `AdminAccessPage`, `AdminLearningPage`).
- [ ] `ConfirmDialogHost` **montado** en `main.tsx`.
- [ ] **Sin código muerto ni duplicados**: tipos `Plan*` solo en `types/api.ts`; `API_BASE_URL` una sola vez; `LearningHealthCard` integrado o eliminado; `StatusBadge` compartido en todo admin.
- [ ] Query keys unificadas vía `lib/queryKeys.ts` (sin cambiar firmas de hooks).
- [ ] `recharts` y `react-table`: **usados** o **eliminados** de `package.json`.
- [ ] `npm run lint` + `npm run build` + `npm run test` **en verde** (sin bajar umbrales de cobertura).
- [ ] a11y: badges con `aria-label`, `aria-current` en nav activo, dialogs con focus trap, forms con `aria-invalid`.
- [ ] Bundle inicial sin regresión (lazy loading mantenido).

---

## 5. Convenciones de commit

- Trabaja **siempre** en `redesign/frontend-v2` (ya creada desde `master`).
- **Un commit por fase**: `redesign(fase-0): tokens, shadcn y providers`, `redesign(fase-1): shell y navegación`, etc.
- Mensajes en **español**, descriptivos.
- Si una fase requiere varios commits (p.ej. Fase 5 con varios archivos de admin), usa `redesign(fase-5): admin - system page` etc.
- **No hagas merge** a `master`; deja la rama abierta para revisión.

---

## 6. Notas de riesgo y límites

- **Preservar la capa de datos** reduce el riesgo de regresión funcional. El rediseño es **visual + estructural de componentes**, no de lógica de negocio.
- Si una decisión **rompe compatibilidad** con un endpoint o una interfaz marcada como "conservar" en §0.2 → **detente** y documéntalo en "Dudas / Decisiones pendientes" (§7).
- **No tocar auth** (cookie session, `credentials:"include"`). No añadir tokens JWT ni cambiar el flujo login/logout.
- **No subir a React 19**: usa versiones de Radix UI compatibles con React `^18.3.1`.
- **No hardcodes secretos** ni URLs absolutas del backend; respeta `VITE_API_BASE_URL` con fallback `/api/v1`.
- Respeta `eslint.config.js` (`no-explicit-any` y `no-unused-vars` son **warn**, no error).

---

## 7. Dudas / Decisiones pendientes

> La IA que ejecute debe rellenar esta sección si se desvía del brief o si algo no encaja.

- _(vacío)_

---

## 8. Cómo lo revisará el ingeniero humano (con otra IA)

Al terminar, en una sesión aparte:
1. `git log redesign/frontend-v2` — verificar un commit por fase.
2. `npm run lint && npm run build && npm run test` en verde.
3. Auditar a11y y consistencia visual pantalla por pantalla.
4. Cotejar contra la checklist de §4.
5. Informe de cumplimento del brief; si hay desviaciones, listarlas con la referencia a la fase/sección.
