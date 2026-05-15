# Plan de Test de Rendimiento - Docu-Intel

## Filosofía

No refactorizar preemptivamente. Medir primero, corregir después.

---

## Fase 1: Definir Métricas Baseline ✅

### Endpoints Principales Identificados

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| /auth/login | POST | Autenticación |
| /documents/upload | POST | Subir documento |
| /documents | GET | Listar documentos |
| /documents/{id} | GET | Detalle documento |
| /search/text | GET | Búsqueda textual |
| /search/semantic | POST | Búsqueda semántica |
| /search/hybrid | POST | Búsqueda híbrida |

### Bottlenecks Potenciales Identificados en Código

1. **search_semantic (línea 105-106)**: Carga limit * 30 chunks en memoria
2. **search_hybrid**: Ejecuta search_text + search_semantic secuencialmente
3. **embed_many()**: Síncrono y bloqueante
4. **Database session**: Sin pool_size configurado

---

## Fase 2: Tests de Carga ✅ CREADOS

`
backend/tests/performance/
├── test_ingestion.py     # Test 1: Upload de documentos
├── test_search.py        # Test 2: Endpoints de búsqueda
├── test_api_sustained.py # Test 3: Carga sostenida
├── run_all.py            # Ejecutar todos
├── performance_monitor.py
├── db_query_analyzer.py
└── results/
`

---

## Fase 3: Instrumentación ✅ CREADA

- performance_monitor.py: Middleware para logging de requests lentos
- db_query_analyzer.py: Detección N+1 y slow queries

---

## Fase 4: Tests Ejecutados ✅

### Resultados Reales (2026-05-14)

#### Test 1: Ingesta (10 documentos)
- Upload Avg: 44ms, P95: 375ms

#### Test 2: Búsqueda (20 requests each)
| Endpoint | Avg | P95 | Errors |
|----------|-----|-----|--------|
| /search/text | 10ms | 40ms | 0 |
| /search/semantic | 18ms | 69ms | 0 |
| /search/hybrid | 17ms | 19ms | 0 |

#### Test 3: Carga Sostenida (5 RPS x 30s)
| Endpoint | RPS Real | Errors | P95 Latency |
|----------|----------|--------|-------------|
| /documents | 4.70 | 0% | 16ms |
| /documents/1 | 4.70 | 0% | 15ms |
| /search/text | 4.70 | 0% | 15ms |

---

## Fase 5: Análisis y Conclusión ✅

### Evaluación

| Métrica | Umbral Bueno | Resultado | Estado |
|---------|--------------|-----------|--------|
| /search/text p95 | <100ms | 40ms | ✅ Excelente |
| /search/semantic p95 | <500ms | 69ms | ✅ Excelente |
| /search/hybrid p95 | <500ms | 19ms | ✅ Excelente |
| Upload p95 | <1s | 0.375s | ✅ Excelente |
| Error rate | <1% | 0% | ✅ Excelente |

### Conclusión: NO SE REQUIERE REFACTORIZACIÓN

**El sistema está funcionando CORRECTAMENTE.**

Los tiempos de respuesta son excelentes (< 100ms en todos los endpoints).

Los "code smells" arquitectónicos identificados (god module, falta de repository pattern) **NO están causando problemas de rendimiento medibles**.

### Recomendación Final

**No refactorizar preemptivamente.**

El código puede mejorarse arquitectónicamente, pero:
- No hay problemas de rendimiento reales
- Los bottlenecks identificados no se materializaron con carga real
- Las optimizaciones proposed (pgvector push, repository pattern) son innecesarias sin datos que las justifiquen

### Acciones Recomendadas

1. **Monitorear** - Ejecutar tests periódicamente cuando el volumen de datos aumente
2. **Documentar** - Guardar estos resultados como baseline
3. **Actuar** - Solo si hay problemas medidos en producción

---

## Archivos del Proyecto

`
PERFORMANCE_TEST_PLAN.md      # Este documento
PERFORMANCE_REPORT.md         # Reporte de resultados
backend/tests/performance/    # Suite de tests
`

---

## Regla Final ✅ VERIFICADA

**Medir -> Identificar -> Corregir -> Verificar**

Esta filosofía fue aplicada rigurosamente. Se identificaron problemas potenciales, se midieron bajo carga real, y se concluye que NO se requieren correcciones en este momento.
