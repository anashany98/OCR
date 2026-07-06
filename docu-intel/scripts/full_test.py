#!/usr/bin/env python3
"""Complete test: 40 fresh docs, monitor, fix, AI query, search."""
import json, os, sys, time, random, subprocess
from pathlib import Path

import requests

BASE = "http://localhost:8000/api/v1"
TEST_ROOT = Path(r"C:\Users\Usuario\Desktop\TEST2025\2025")
RESULTS_DIR = Path(r"C:\Users\Usuario\Desktop\OCR\OCR\docu-intel\scripts\test_results2")
RESULTS_DIR.mkdir(exist_ok=True)

r = requests.post(f"{BASE}/auth/login",
    json={"email": "admin@local", "password": "mxT-EPCWJKVpfdClt4mJ82puUV7eHw"})
TOKEN = r.json()["access_token"]
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def api(method, path, data=None, timeout=120):
    url = f"{BASE}{path}"
    try:
        if method == "GET":
            r = requests.get(url, headers=HDR, timeout=timeout)
        else:
            r = requests.post(url, json=data, headers=HDR, timeout=timeout)
        if r.status_code >= 400:
            return None
        return r.json()
    except Exception as e:
        return None


def get_existing_source_paths():
    """Get all source_path values already in the DB (container paths)."""
    result = subprocess.run(
        ["docker", "exec", "docu-intel-postgres-1", "psql", "-U", "app", "-d", "docuintel",
         "-t", "-A", "-c", "SELECT source_path FROM documents WHERE source_path IS NOT NULL;"],
        capture_output=True, timeout=60
    )
    paths = set()
    stdout = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
    for line in stdout.strip().split("\n"):
        if line.strip():
            # Convert /app/data/input/2025/xxx -> relative part after 2025/
            p = line.strip()
            if "/2025/" in p:
                rel = p.split("/2025/", 1)[1]
                paths.add(rel.lower())
    return paths


def select_fresh_files(existing_paths, count=40):
    """Pick files from TEST2025 not already in the system."""
    all_files = []
    for f in TEST_ROOT.rglob("*"):
        if f.is_file():
            rel = str(f.relative_to(TEST_ROOT)).lower()
            if rel not in existing_paths:
                ext = f.suffix.lower()
                if ext in (".pdf", ".jpg", ".jpeg", ".png", ".xlsx", ".xls", ".docx", ".tif", ".tiff"):
                    all_files.append(f)

    random.seed(123)
    by_type = {}
    for f in all_files:
        ext = f.suffix.lower()
        by_type.setdefault(ext, []).append(f)

    selected = []
    # Grab proportionally: ~50% PDF, ~25% images, ~25% excel/other
    pdfs = by_type.get(".pdf", [])
    imgs = by_type.get(".jpg", []) + by_type.get(".jpeg", []) + by_type.get(".png", [])
    xls = by_type.get(".xlsx", []) + by_type.get(".xls", []) + by_type.get(".docx", [])

    n_pdf = min(20, len(pdfs))
    n_img = min(10, len(imgs))
    n_xls = min(10, len(xls))

    selected += random.sample(pdfs, n_pdf) if pdfs else []
    selected += random.sample(imgs, n_img) if imgs else []
    selected += random.sample(xls, n_xls) if xls else []

    # Fill remaining from any type
    remaining = [f for f in all_files if f not in selected]
    while len(selected) < count and remaining:
        pick = remaining.pop(random.randint(0, len(remaining) - 1))
        selected.append(pick)

    random.shuffle(selected)
    return selected[:count]


def upload_files(files):
    print(f"\n--- SUBIENDO {len(files)} ARCHIVOS ---")
    uploaded = []
    for i in range(0, len(files), 5):
        batch = files[i:i+5]
        file_list = [("files", (f.name, open(f, "rb"), "application/octet-stream")) for f in batch]
        try:
            resp = requests.post(f"{BASE}/documents/upload/batch",
                files=file_list, headers={"Authorization": f"Bearer {TOKEN}"}, timeout=300)
            if resp.status_code == 200:
                r = resp.json()
                up = r.get("uploaded", 0)
                dup = r.get("duplicates", 0)
                fail = r.get("failed", 0)
                print(f"  Lote {i//5+1}: subidos={up} duplicados={fail} fallos={fail}")
                for doc in r.get("documents", []):
                    if doc.get("document_id"):
                        uploaded.append(doc)
            else:
                print(f"  Lote {i//5+1}: HTTP {resp.status_code}")
        except Exception as e:
            print(f"  Lote {i//5+1}: Error {e}")
        finally:
            for _, (_, fh, _) in file_list:
                fh.close()
        time.sleep(0.3)
    return uploaded


def wait_processing(doc_ids, max_wait=1200):
    print(f"\n--- ESPERANDO PROCESAMIENTO de {len(doc_ids)} docs (max {max_wait}s) ---")
    start = time.time()
    while time.time() - start < max_wait:
        statuses = {}
        for did in doc_ids:
            d = api("GET", f"/documents/{did}")
            if d:
                s = d.get("status", "?")
                statuses[s] = statuses.get(s, 0) + 1
        pending = statuses.get("pending", 0) + statuses.get("processing", 0)
        elapsed = int(time.time() - start)
        print(f"  [{elapsed}s] {statuses}")
        if pending == 0:
            return statuses
        time.sleep(25)
    return statuses


def check_confidence(doc_ids):
    """Return docs with low confidence that could be retried."""
    low_conf = []
    good = []
    for did in doc_ids:
        d = api("GET", f"/documents/{did}")
        if not d:
            continue
        conf = d.get("confidence")
        status = d.get("status")
        if status == "processed" and conf is not None and conf < 0.3:
            low_conf.append((did, conf, d.get("original_filename", "?")))
        elif status == "processed":
            good.append((did, conf, d.get("original_filename", "?")))
    return good, low_conf


def retry_low_confidence(low_conf_docs):
    """Re-enqueue docs with low confidence for reprocessing."""
    if not low_conf_docs:
        return
    ids = [d[0] for d in low_conf_docs]
    print(f"\n--- REPROCESANDO {len(ids)} docs con confianza baja ---")
    for did, conf, name in low_conf_docs:
        print(f"  id={did} conf={conf:.3f} {name[:40]}")
    r = api("POST", "/documents/reprocess-bulk", {"ids": ids, "mode": "full", "limit": 50})
    if r:
        print(f"  Resultado: enqueued={r.get('enqueued',0)} skipped={r.get('skipped',0)}")


def run_ai_queries():
    print(f"\n--- CONSULTAS IA ---")
    questions = [
        "Que tipos de documentos hay en el sistema? Describe su contenido general.",
        "Cuantos presupuestos hay? Para que clientes y que hotels?",
        "Que empresas proveedoras de textiles o decoracion aparecen?",
        "Hay facturas? De que proveedores y por que importes?",
        "Que materiales se mencionan (cortinas, tapiceria, mobiliario)?",
        "Hay albaranes de entrega? De que productos y a que clientes?",
        "Que proyectos de reforma hotelera hay documentados?",
        "Que medidas y cantidades de productos se manejan?",
        "Que precios o rangos de precios aparecen en los documentos?",
        "Resumen ejecutivo: de que trata la documentacion de este lote?",
    ]
    results = []
    for q in questions:
        print(f"\n  P: {q}")
        r = api("POST", "/ai/ask", {"question": q}, timeout=180)
        if r:
            answer = r.get("answer", "")
            conf = r.get("confidence", 0)
            sources = r.get("sources", [])
            n_src = len(sources) if sources else 0
            print(f"  R (conf={conf:.3f}, fuentes={n_src}): {answer[:350]}")
            results.append({"q": q, "a": answer, "confidence": conf, "sources": n_src})
        else:
            print("  SIN RESPUESTA")
            results.append({"q": q, "a": "SIN RESPUESTA", "confidence": 0, "sources": 0})
        time.sleep(3)
    return results


def run_search_test():
    print(f"\n--- PRUEBA DE BUSQUEDA ---")
    queries = ["presupuesto cortinas hotel", "factura proveedor decoracion",
               "albaran entrega mobiliario", "reforma hotelera ibiza mallorca"]
    results = {}
    for q in queries:
        t = api("GET", f"/search/text?q={q}&limit=5", timeout=30)
        s = api("POST", "/search/semantic", {"query": q, "limit": 5}, timeout=30)
        h = api("POST", "/search/hybrid", {"query": q, "limit": 5}, timeout=30)
        tn = len(t) if t else 0
        sn = len(s) if s else 0
        hn = len(h) if h else 0
        print(f"  '{q}': texto={tn} semantico={sn} hibrido={hn}")
        results[q] = {"text": tn, "semantic": sn, "hybrid": hn}
    return results


def check_system_health():
    print(f"\n--- ESTADO DEL SISTEMA ---")
    r = subprocess.run(["docker", "ps", "--format", "{{.Names}}: {{.Status}}"],
        capture_output=True, encoding="utf-8", timeout=30)
    healthy = 0
    total = 0
    for line in r.stdout.strip().split("\n"):
        if "docu-intel" in line:
            total += 1
            if "healthy" in line or "Up" in line:
                healthy += 1
            print(f"  {line}")
    print(f"  Contenedores: {healthy}/{total} operativos")

    r2 = subprocess.run(["docker", "exec", "docu-intel-postgres-1", "psql", "-U", "app", "-d", "docuintel",
        "-t", "-A", "-c", "SELECT version_num FROM alembic_version;"],
        capture_output=True, encoding="utf-8", timeout=15)
    print(f"  Migracion DB: {r2.stdout.strip()}")

    r3 = subprocess.run(["docker", "exec", "docu-intel-postgres-1", "psql", "-U", "app", "-d", "docuintel",
        "-t", "-A", "-c", "SELECT status, COUNT(*) FROM documents GROUP BY status ORDER BY COUNT(*) DESC;"],
        capture_output=True, encoding="utf-8", timeout=15)
    print(f"  Documentos totales:")
    for line in r3.stdout.strip().split("\n"):
        if line.strip():
            print(f"    {line}")

    r4 = subprocess.run(["docker", "exec", "docu-intel-backend-1", "python", "-c",
        "import urllib.request; r=urllib.request.urlopen('http://host.docker.internal:1234/v1/models',timeout=10); import json; d=json.loads(r.read()); print(', '.join(m['id'] for m in d['data']))"],
        capture_output=True, encoding="utf-8", timeout=30)
    if r4.returncode == 0:
        print(f"  Modelos LLM: {r4.stdout.strip()}")


def main():
    print("=" * 60)
    print("PRUEBA COMPLETA: 40 DOCUMENTOS NUEVOS")
    print("=" * 60)

    # Step 1: Find fresh files
    print("\n--- PASO 1: Buscando archivos frescos ---")
    existing = get_existing_source_paths()
    print(f"  Archivos ya en el sistema: {len(existing)}")
    files = select_fresh_files(existing, 40)
    print(f"  Archivos nuevos seleccionados: {len(files)}")
    for i, f in enumerate(files):
        size_kb = f.stat().st_size / 1024
        client = f.parent.parent.parent.name[:30]
        print(f"    {i+1:2d}. [{f.suffix:5s}] {f.name[:50]:50s} ({size_kb:5.0f}KB) {client}")

    # Step 2: Upload
    uploaded = upload_files(files)
    doc_ids = [d["document_id"] for d in uploaded if d.get("document_id")]
    print(f"\n  Subidos: {len(doc_ids)} documentos")

    if not doc_ids:
        print("  No se subieron documentos. Abortando.")
        return

    # Step 3: Wait for processing
    statuses = wait_processing(doc_ids, max_wait=1200)

    # Step 4: Check confidence and retry low ones
    good, low = check_confidence(doc_ids)
    print(f"\n  Confianza: {len(good)} buenos, {len(low)} bajos")
    if good:
        avg_conf = sum(g[1] for g in good if g[1] is not None) / len(good)
        print(f"  Confianza media (buenos): {avg_conf:.3f}")
    if low:
        retry_low_confidence(low)
        # Wait again for retried docs
        retried_ids = [d[0] for d in low]
        time.sleep(30)
        wait_processing(retried_ids, max_wait=600)

    # Step 5: Final confidence check
    final_good, final_low = check_confidence(doc_ids)
    print(f"\n  Confianza final: {len(final_good)} buenos, {len(final_low)} bajos")
    if final_good:
        avg = sum(g[1] for g in final_good if g[1] is not None) / len(final_good)
        print(f"  Confianza media final: {avg:.3f}")

    # Step 6: AI queries
    ai_results = run_ai_queries()

    # Step 7: Search test
    search_results = run_search_test()

    # Step 8: System health
    check_system_health()

    # Save report
    report = {
        "files_selected": len(files),
        "uploaded": len(doc_ids),
        "doc_ids": doc_ids,
        "final_statuses": statuses,
        "confidence_good": len(final_good),
        "confidence_low": len(final_low),
        "ai_results": ai_results,
        "search_results": search_results,
    }
    with open(RESULTS_DIR / "report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Summary
    print("\n" + "=" * 60)
    print("RESUMEN FINAL")
    print("=" * 60)
    print(f"Documentos subidos: {len(doc_ids)}")
    print(f"Estados finales: {statuses}")
    ai_ok = sum(1 for r in ai_results if r["a"] != "SIN RESPUESTA")
    print(f"IA responde: {ai_ok}/{len(ai_results)}")
    avg_ai_conf = sum(r["confidence"] for r in ai_results) / max(len(ai_results), 1)
    print(f"Confianza media IA: {avg_ai_conf:.3f}")
    avg_src = sum(r["sources"] for r in ai_results) / max(len(ai_results), 1)
    print(f"Fuentes promedio: {avg_src:.1f}")
    total_hyb = sum(v["hybrid"] for v in search_results.values())
    print(f"Busqueda hibrida: {total_hyb} hits en 4 queries")


if __name__ == "__main__":
    main()
