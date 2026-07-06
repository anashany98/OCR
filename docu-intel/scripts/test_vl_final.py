import requests, base64, time

with open(r"C:\Users\Usuario\Desktop\TEST2025\2025\MAJESTIC 4(MAJ4)\Presupuesto 251723\IMAGENES\Contenedor Cerrado.jpeg", "rb") as f:
    img = base64.b64encode(f.read()).decode()

payload = {
    "model": "qwen/qwen3-vl-8b-instruct",
    "messages": [{"role": "user", "content": [
        {"type": "text", "text": "Describe esta imagen en espanol con detalle. Si contiene texto, transcribelo."},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}}
    ]}],
    "temperature": 0.0,
    "max_tokens": 500
}

start = time.time()
r = requests.post("http://localhost:1234/v1/chat/completions", json=payload, timeout=120)
elapsed = time.time() - start

data = r.json()
msg = data["choices"][0]["message"]
content = msg.get("content", "")
print(f"Tiempo: {elapsed:.1f}s")
print(f"Modelo: {data.get('model')}")
print(f"Respuesta: {content[:600]}")
