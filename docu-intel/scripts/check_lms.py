import urllib.request, json

# Test from inside container
url = "http://host.docker.internal:1234/v1/models"
try:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
        models = payload.get("data", [])
        print(f"Models found: {len(models)}")
        for m in models:
            print(f"  {m.get('id')}")
except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")

# Test port 1234 directly
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(3)
try:
    s.connect(("host.docker.internal", 1234))
    print("Port 1234: OPEN")
except:
    print("Port 1234: CLOSED")
finally:
    s.close()
