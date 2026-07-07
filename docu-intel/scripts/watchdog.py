"""Watchdog: monitors containers and restarts any that are down."""
import subprocess
import time
from datetime import datetime

def get_containers():
    result = subprocess.run(
        ["docker", "ps", "-a", "--format", "{{.Names}}|{{.Status}}"],
        capture_output=True, timeout=30
    )
    containers = {}
    for line in result.stdout.decode("utf-8", errors="replace").strip().split("\n"):
        if "docu-intel" in line and "|" in line:
            name, status = line.split("|", 1)
            containers[name.strip()] = status.strip()
    return containers

def restart_container(name):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] RESTARTING {name}...")
    subprocess.run(["docker", "restart", name], capture_output=True, timeout=60)
    print(f"  Done: {name}")

print("Watchdog started. Checking every 60s...")
while True:
    try:
        containers = get_containers()
        issues = []
        for name, status in containers.items():
            if "Exited" in status or "Restarting" in status:
                issues.append((name, status))
            elif "unhealthy" in status:
                issues.append((name, status))
        
        if issues:
            for name, status in issues:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ISSUE: {name} -> {status}")
                restart_container(name)
                time.sleep(15)
        else:
            healthy = sum(1 for s in containers.values() if "Up" in s)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] OK: {healthy} healthy")
    except Exception as e:
        print(f"Error: {e}")
    
    time.sleep(60)
