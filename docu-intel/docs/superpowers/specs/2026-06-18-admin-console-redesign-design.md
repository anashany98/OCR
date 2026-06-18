# Docu-Intel Admin Console Redesign

**Date:** 2026-06-18  
**Status:** Approved visual direction; pending implementation-plan review  
**Scope:** Administrative frontend, document library, ingestion observability, and a separate read-only chat application

## 1. Objective

Replace the current crowded, overlapping frontend with:

1. A single-profile administrative console for operating the document platform.
2. A scalable document library that preserves uploaded folder structures while adding virtual business dossiers.
3. A dedicated, highly visual ingestion and processing monitor backed by real telemetry.
4. A separate chat application for document and business-data queries through the API.

The console is an internal tool. It has one authenticated administrator profile. It does not expose role management, permission management, or an internal chat module.

## 2. Current-state findings

The repository was audited at commit `734dab1`.

### 2.1 Navigation and information architecture

The current frontend has several overlapping navigation layers:

- A persistent sidebar with four broad groups and 17 visible destinations.
- A second tab navigation inside Administration.
- A third section navigation inside technical system pages.
- Repeated navigation targets for quality concerns such as Tasks, Incidents, OCR quality, Duplicates, and Quarantine.
- Repeated page identity in the top bar, breadcrumbs, and large page headers.

The result is technically navigable but conceptually ambiguous: it is unclear whether a quality issue belongs in Tasks, Incidents, OCR Review, or Administration / Quality.

### 2.2 Visual consistency

The current “editorial” visual language mixes:

- Warm cream and terracotta surfaces.
- Serif display typography.
- Dense technical tables and status dashboards.
- Legacy hard-coded white, slate, and gray utility classes.
- Several radius and shadow conventions.

The result feels like multiple design systems applied to the same product.

### 2.3 Document organization

The current Documents page is primarily a flat server-side table:

- `source_path` appears only as secondary row text.
- Folder hierarchy is not navigable.
- Saved-view backend support exists but is not integrated into the library.
- Tags and folder rules exist but are not first-class library controls.
- Budget, order, and invoice relationships do not organize the document list.
- Upload progress is a transient text banner rather than a persistent batch entity.

### 2.4 Processing observability

The current job model stores:

- Document and job identifiers.
- General status.
- Start and finish timestamps.
- Retry count and error message.

It does not store:

- An upload/ingestion batch.
- Current internal processing stage.
- Stage progress or total work units.
- Celery task identifier, queue, worker hostname, or GPU assignment.
- Per-stage timestamps.
- Routing decision and reason.
- Reliable per-document or per-batch ETA.

Therefore the proposed processing visualization requires backend telemetry. It must not display fabricated progress.

### 2.5 Technical baseline

At the audited commit:

- `npm run build` succeeds.
- The production build is code-split by route.
- `npm test` reports 130 passing tests.
- The main application chunk is approximately 435 kB before gzip.
- Several feature files remain very large, including system, access, learning, plan annotation, work inbox, search, dashboard, and document components.

## 3. Product boundary

### 3.1 Administrative console

The administrative console owns:

- Upload and folder ingestion.
- Document organization and inspection.
- OCR review and corrections.
- Budget, order, invoice, and reconciliation operations.
- Processing batches, jobs, workers, queues, and GPU visibility.
- System configuration, integrations, audit, and technical health.

### 3.2 External chat

The chat is a separate application and owns:

- Asking questions about document content.
- Asking questions about budgets, orders, invoices, and their relationships.
- Automatic context resolution.
- Source display and navigation.
- Deterministic SQL-backed aggregations.

The chat does not:

- Reprocess documents.
- Change OCR data.
- Manage workers, queues, or settings.
- Execute administrative actions.

When an administrative correction is needed, the chat links to the relevant console page.

### 3.3 Authentication

The console retains a simple login:

- Email and password.
- One administrator profile.
- No role selector.
- No user, role, or permission management UI.

The backend must continue enforcing authenticated access. The redesign removes role-oriented product complexity; it does not make the API anonymous.

The external chat uses its own authenticated session and API client configuration.

## 4. Design language

The approved direction is “industrial precision”:

- Cool neutral surfaces.
- Deep charcoal navigation.
- Operational green as the primary accent.
- Blue for fast/text routes.
- Amber for warnings and predicted congestion.
- Red only for failures and destructive states.
- Direct sans-serif typography.
- Monospace numerals for telemetry.
- Restrained border radii and shadows.
- High information clarity without a dense control-room appearance.

The design system must replace legacy hard-coded `bg-white`, slate, gray, and editorial palette usage with semantic tokens.

Motion is functional:

- Route animation represents actual work movement.
- Pulsing represents live telemetry.
- Heat intensity represents measured or forecast load.
- No decorative animation may imply processing that is not occurring.

Reduced-motion preferences must disable continuous packet animation while preserving state changes.

## 5. Administrative information architecture

The console has a compact icon rail with six areas:

### 5.1 Command Center

- Balanced operational summary.
- Frequent actions.
- Commercial metrics.
- Priority work.
- Concise technical-health summary.
- Active-batch summary linking to Processing.

The command center summarizes other modules; it does not duplicate their full interfaces.

### 5.2 Documents

- Library.
- Upload center.
- OCR review.
- Plans.
- Advanced search.

### 5.3 Commercial Cycle

- Budgets.
- Orders.
- Invoices.
- Relationships between commercial documents.
- Structured field details.

### 5.4 Quality

- Unified review inbox.
- Reconciliation.
- Duplicates.
- Quarantine.
- OCR corrections.

Tasks, incidents, OCR review, duplicates, and quarantine are presented as filters or workflows within this quality area rather than unrelated top-level destinations.

### 5.5 Processing

- Active batches.
- Digital twin.
- Jobs and history.
- Workers, queues, and GPUs.
- Technical processing incidents.

### 5.6 System

- Technical status.
- OCR and AI engines.
- API and integrations.
- Folder rules.
- Configuration and audit.

### 5.7 Navigation rules

- The rail contains six stable icons with labels on tooltip and an optional expanded state.
- Opening an area reveals local secondary navigation.
- No user flow exceeds two navigation levels.
- The global command palette searches pages, documents, folders, dossiers, batches, workers, and actions.
- A page uses either a concise contextual breadcrumb or a page title when the relationship is obvious; it does not repeat the same title in three places.

## 6. Command Center

The initial screen uses balanced density.

### 6.1 Primary content

- Global command/search field.
- Unified Upload action.
- Four primary quick actions:
  - Upload files or folders.
  - Review OCR.
  - Reconcile invoices.
  - Inspect processing.
- Commercial metrics:
  - Documents.
  - Budgets.
  - Orders.
  - Invoices.
- Priority-work panel.
- Technical-health panel.

### 6.2 Active processing summary

The dashboard only shows:

- Number of active batches.
- Aggregate completion percentage.
- Current incidents.
- Link to `Processing / Batches`.

The digital twin does not render inside the dashboard.

## 7. Unified Upload Center

The Upload action supports:

- One file.
- Multiple files.
- One complete folder.
- Multiple folders by drag and drop.
- Mixed files and folders where the browser File System API allows it.

Relative paths are preserved.

### 7.1 Review before submission

Before confirming a batch, the upload center shows:

- Folder tree and file count.
- Total bytes.
- Unsupported files.
- Duplicate candidates.
- Files exceeding limits.
- Relative paths.
- The target folder or dossier if one is selected.

The user can remove individual entries before submission.

### 7.2 Upload transport progress

Transport progress uses real uploaded bytes:

- Per-file percentage.
- Aggregate percentage.
- Upload speed.
- Remaining bytes.
- Estimated upload time.
- Retry state.

After registration, the batch transitions into the Processing module without losing continuity.

## 8. Scalable Document Library

The library uses a hybrid model.

### 8.1 Physical folder tree

The original uploaded structure remains visible and immutable by default:

- Relative paths are preserved.
- Breadcrumbs reconstruct the current path.
- Each folder has a deep link.
- Uploading “here” preserves the selected parent context.

The UI does not move or duplicate stored files when creating other organizations.

### 8.2 Scale strategy

The library must support tens of thousands of folders:

- Children are fetched only when their parent is opened.
- The tree is virtualized; only visible rows exist in the DOM.
- Root and child results are paginated.
- Folder counts are returned with each node.
- Search is server-side against an indexed normalized path.
- Searching opens a direct result without expanding every ancestor manually.
- Favorites, recent folders, and recent batches provide shortcuts.

Proposed API shape:

```text
GET /document-library/folders?parent_path=<path>&cursor=<cursor>&limit=100
GET /document-library/folders/search?q=<query>&limit=50
GET /document-library/folders/resolve?path=<path>
```

### 8.3 Virtual dossiers

Virtual dossiers organize related documents without changing physical paths.

The primary dossier type is the commercial chain:

```text
Budget → Order → Invoice
```

A dossier can include:

- Commercial documents.
- Emails.
- Technical manuals.
- Plans.
- Images.
- Delivery notes and attachments.

The dossier is derived from deterministic relationships and normalized identifiers. Low-confidence suggestions remain suggestions until confirmed.

### 8.4 Library modes

- Explorer: physical folder hierarchy.
- Dossiers: business relationships.
- Document types: classification-oriented browsing.
- Smart views: saved server-side filters.
- Unorganized: missing path, classification, or dossier assignment.

### 8.5 Context inspector

The right inspector displays the current folder, dossier, or selection:

- Commercial chain.
- Automatic and manual tags.
- Quality summary.
- Missing relationships.
- Duplicate and quarantine counts.
- Recent activity.

## 9. Processing Digital Twin

The approved target is the v4 “operational intelligence” design at:

```text
Processing / Batches / :batchId
```

### 9.1 Core visualization

The canvas displays:

- Reception.
- Validation.
- Routing decision.
- OCR-heavy path.
- Native/fast-text path.
- Human-review diversion.
- Classification and business extraction.
- Chunking and embeddings.
- Index availability.

Animated packets represent actual documents changing stages.

Each node exposes:

- Active count.
- Queue.
- Worker hostname.
- GPU or CPU assignment.
- Throughput.
- Error and retry counts.
- Measured stage progress.

### 9.2 Interaction

The administrator can select:

- Route.
- Stage.
- Batch.
- Document.
- Worker.
- GPU.
- Incident.

Selecting an item filters the inspector and event stream.

“Follow document” highlights one document’s complete route.

### 9.3 Intelligence layer

The v4 design adds:

- Routing explanation: why the document took this path.
- Heat map: current and forecast load.
- Historical comparison by route, worker, extension, page count, and model.
- Bottleneck forecast.
- Safe simulation before rebalancing or pausing.
- Natural-language diagnosis generated from traceable telemetry.

The AI diagnosis is advisory. It cannot reassign or pause work without an explicit administrator action.

### 9.4 Real progress rules

Progress is based on real units:

- Upload: bytes.
- Registration: files.
- PDF OCR: pages.
- Image OCR: preprocessing and OCR completion.
- Classification: document completion.
- Chunking: chunks created.
- Embeddings: vectors completed.
- Batch: weighted aggregation of document-stage progress.

If the backend cannot measure an intermediate stage reliably, the UI shows an indeterminate active state instead of an invented percentage.

### 9.5 ETA

ETA combines:

- Current observed rate.
- Historical duration by extension and page count.
- Queue wait.
- Worker and GPU capacity.
- Route-specific stage averages.

ETA includes a confidence indicator. When confidence is insufficient, the UI shows a range or “calculating”.

### 9.6 Backend data model

Add an ingestion batch entity:

```text
IngestionBatch
- id
- name
- source_kind
- total_files
- total_bytes
- uploaded_bytes
- status
- started_at
- finished_at
- created_by_id
```

Link documents to the batch.

Extend extraction jobs or add a dedicated execution model with:

```text
- celery_task_id
- queue_name
- worker_hostname
- worker_pool
- gpu_device
- current_stage
- stage_completed_units
- stage_total_units
- progress_percent
- routing_reason_json
- started_at
- heartbeat_at
- finished_at
```

Add append-only stage events:

```text
ProcessingStageEvent
- batch_id
- document_id
- job_id
- stage
- event_type
- worker_hostname
- queue_name
- gpu_device
- completed_units
- total_units
- details_json
- created_at
```

Existing `IngestionEvent` rows remain useful for file discovery and registration, but they are not sufficient alone for the digital twin.

### 9.7 Delivery

Initial implementation may poll a batch snapshot endpoint every 1–2 seconds. The target transport is Server-Sent Events:

```text
GET /processing/batches/:id
GET /processing/batches/:id/events
GET /processing/batches/:id/stream
GET /processing/workers
```

The snapshot endpoint is the source of truth. The event stream updates it incrementally.

## 10. External Chat Application

The chat is a separate frontend application with a focused three-column layout:

- Conversations.
- Conversation content.
- Sources and context.

### 10.1 Automatic context

The chat detects:

- Specific document.
- Physical folder.
- Virtual dossier.
- Budget, order, or invoice.
- Global scope.

The detected scope is visible with a confidence value. The user can correct it before or after the response without retyping the question.

### 10.2 Query routing

Use:

- RAG for document content and narrative questions.
- Structured lookup for known business entities.
- SQL for sums, counts, comparisons, and aggregations.
- A combined response when both unstructured evidence and exact values are needed.

### 10.3 Grounding

Every substantive answer displays:

- Document sources.
- Page or structured record.
- Relevance or match status.
- OCR confidence.
- Warning when evidence has low OCR confidence.
- Deterministic calculation note when SQL was used.

### 10.4 Console links

Sources can open:

- Document detail.
- Specific page.
- Folder.
- Dossier.
- Reconciliation issue.

Administrative actions remain in the console.

## 11. Component and code organization

### 11.1 Console frontend

Organize by product area:

```text
src/
  app-shell/
  command-center/
  documents/
    library/
    upload/
    review/
    plans/
  commercial/
    budgets/
    orders/
    invoices/
  quality/
  processing/
    batches/
    digital-twin/
    workers/
  system/
```

Shared primitives live in:

```text
src/components/ui/
src/components/data-display/
src/components/feedback/
src/design-system/
```

Large `components.tsx` files must be split by responsibility. A file should not combine data hooks, page composition, dialogs, and unrelated view components.

### 11.2 Chat frontend

The external chat should be a separate package/application so deployment and release cadence are independent:

```text
chat-frontend/
  src/
    conversations/
    messages/
    context/
    sources/
    api/
```

Share generated API types or a small design-token package only when that reduces drift without coupling releases.

## 12. Error handling

### 12.1 Upload

- Failed files remain visible in the batch.
- Retrying does not resend successful files.
- Network interruption can resume or clearly restart a file.
- Unsupported and oversized files are rejected before expensive processing.

### 12.2 Processing

- Stale worker heartbeat changes the node to “unknown/stalled”.
- Missing telemetry never appears as zero progress.
- A failed document branches to an incident state and preserves prior events.
- Event-stream disconnect falls back to polling and indicates delayed live data.

### 12.3 Library

- Missing folders return a recoverable “path no longer exists” state.
- Invalid deep links offer the nearest existing ancestor.
- Search supports pagination and empty-state guidance.

### 12.4 Chat

- No-source responses state that evidence was insufficient.
- SQL failures do not fall back to an invented LLM calculation.
- Low-confidence OCR is explicitly disclosed.
- Context ambiguity prompts a choice rather than silently widening to all documents.

## 13. Accessibility and responsive behavior

- Full keyboard operation for command palette, rail, tree, tables, dialogs, and chat.
- Visible focus indicators.
- Semantic labels for worker, queue, stage, and status.
- Reduced-motion support for the digital twin.
- Color is never the only route or status signal.
- Desktop is the primary console target.
- On tablets, the rail remains and inspectors become drawers.
- On mobile, the console supports essential review and monitoring but does not attempt to reproduce the full digital-twin canvas.
- The external chat is fully responsive.

## 14. Testing strategy

### 14.1 Unit tests

- Navigation configuration and route titles.
- Folder-path normalization and hierarchy assembly.
- Dossier relationship mapping.
- Batch and document progress aggregation.
- ETA confidence and fallback behavior.
- Routing explanation rendering.
- Chat context resolution and correction.
- RAG/SQL query routing.

### 14.2 Component tests

- Upload review and partial failure.
- Virtualized folder navigation.
- Deep-link resolution.
- Digital-twin node and route filtering.
- Reduced-motion rendering.
- Stalled-worker state.
- Chat citations and OCR warnings.

### 14.3 API tests

- Folder children and search pagination.
- Batch creation and status snapshots.
- Stage event ordering.
- Worker metadata capture.
- SSE authorization and reconnection cursor.
- Dossier queries.
- Exact commercial aggregation.

### 14.4 End-to-end tests

1. Upload a mixed folder batch.
2. Review files before submission.
3. Follow one document through the batch monitor.
4. Observe a document route to review after low OCR confidence.
5. Navigate from physical folder to virtual commercial dossier.
6. Ask the external chat about a budget/order/invoice difference.
7. Verify the answer cites sources and uses exact SQL amounts.
8. Open the relevant console item from the chat.

### 14.5 Performance acceptance

- Folder tree remains responsive with at least 50,000 indexed folders.
- Opening a folder does not fetch unrelated descendants.
- Digital-twin updates do not rerender the entire canvas for each event.
- Continuous live monitoring does not leak timers, subscriptions, or event listeners.

## 15. Delivery phases

This specification describes one product direction, but implementation planning must be decomposed into four independently deliverable plans:

1. **Console foundation:** design system, application shell, navigation, command center, and quality-area consolidation.
2. **Document operations:** unified upload center, persistent batch creation, scalable folder library, saved views, tags, and virtual dossiers.
3. **Processing intelligence:** stage telemetry, worker/GPU metadata, batch APIs, live delivery, digital-twin visualization, and advisory intelligence.
4. **External chat:** separate application, automatic context, RAG/SQL routing, citations, warnings, and console deep links.

Each plan must produce working, testable software without requiring unfinished later plans. Within those plans, work remains incremental:

1. Establish the required backend contracts and failing tests.
2. Implement the smallest functional UI and data flow.
3. Add the advanced visual layer only after the data is trustworthy.
4. Complete accessibility, responsive, performance, and end-to-end verification before declaring the plan complete.

The digital twin intelligence layer must not block delivery of reliable batch tracking. Accurate telemetry comes before advanced visualization and prediction.

## 16. Acceptance criteria

- The console exposes six product areas and no role-management or internal-chat navigation.
- Login supports one administrator profile.
- Upload accepts files and complete folders while preserving relative paths.
- Upload batches persist beyond the initial HTTP request.
- The dashboard provides a balanced summary and links to detailed modules.
- The document library can navigate at least 50,000 folders through lazy loading and virtualization.
- Physical folders and virtual dossiers coexist without moving stored files.
- Saved views are connected to the frontend.
- Processing shows actual batch, document, stage, queue, worker, and GPU data.
- Percentages are based on measurable units; unavailable progress is indeterminate.
- The digital twin can follow an individual document and explain its route.
- The external chat automatically detects context and allows correction.
- Commercial sums and comparisons are produced by deterministic queries.
- Answers cite navigable sources and warn about low-confidence OCR.
- Existing frontend tests remain green and new behavior has unit, component, API, and end-to-end coverage.
- Production build remains route-split and no major page is added to the initial bundle unnecessarily.
