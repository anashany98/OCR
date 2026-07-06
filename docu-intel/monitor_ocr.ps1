# OCR Processing Monitor Script
# Run periodically: .\monitor_ocr.ps1
# Checks DB status, worker health, and logs errors

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$separator = "=" * 60

Write-Output "`n$separator"
Write-Output "OCR MONITORING REPORT - $timestamp"
Write-Output "$separator"

# Check container status
Write-Output "`n--- CONTAINER STATUS ---"
docker ps --format "table {{.Names}}\t{{.Status}}" | Select-String "docu-intel"

# DB stats
Write-Output "`n--- DATABASE STATS ---"
docker exec docu-intel-postgres-1 psql -U app -d docuintel -t -c "
SELECT 'Documents: ' || count(*) FROM documents;
"
docker exec docu-intel-postgres-1 psql -U app -d docuintel -t -c "
SELECT 'Extraction Jobs by Status:';
"
docker exec docu-intel-postgres-1 psql -U app -d docuintel -t -c "
SELECT '  ' || status || ': ' || count(*) FROM extraction_jobs_2026_06 GROUP BY status ORDER BY count DESC;
"
docker exec docu-intel-postgres-1 psql -U app -d docuintel -t -c "
SELECT 'Watched Files: ' || count(*) FROM watched_files;
"
docker exec docu-intel-postgres-1 psql -U app -d docuintel -t -c "
SELECT 'Failed Ingestions (last 10):';
"
docker exec docu-intel-postgres-1 psql -U app -d docuintel -t -c "
SELECT '  ' || substring(source_path for 80) || ' -> ' || substring(error_message for 80) 
FROM ingestion_events WHERE event_type='failed' ORDER BY id DESC LIMIT 10;
"

# Recent watcher ticks
Write-Output "`n--- WATCHER RECENT TICKS ---"
docker logs --since 30m docu-intel-watcher-1 2>&1 | Select-String "watcher_tick" | Select-Object -Last 5

# Worker errors
Write-Output "`n--- WORKER ERRORS (last 30 min) ---"
docker logs --since 30m docu-intel-worker-heavy-gpu-0-1 2>&1 | Select-String "ERROR|error|Traceback|Exception" | Select-Object -Last 10
docker logs --since 30m docu-intel-worker-heavy-gpu-1-1 2>&1 | Select-String "ERROR|error|Traceback|Exception" | Select-Object -Last 10
docker logs --since 30m docu-intel-worker-heavy-1 2>&1 | Select-String "ERROR|error|Traceback|Exception" | Select-Object -Last 10

# Embedding status
Write-Output "`n--- EMBEDDING STATUS ---"
docker exec docu-intel-postgres-1 psql -U app -d docuintel -t -c "
SELECT 'Chunks: ' || count(*) FROM document_chunks;
"

Write-Output "`n$separator"
Write-Output "END OF REPORT"
Write-Output "$separator`n"
