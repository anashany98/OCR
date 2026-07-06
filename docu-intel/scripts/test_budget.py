from app.services.budget_scope import extract_budget_code_from_path

paths = [
    "/app/data/input/2025/CLIENT/Presupuesto 251234/PDF/file.pdf",
    "/app/data/input/2025/ALZINAR MAR SLU/Presupuesto 250687/PDF/file.pdf",
    "/app/data/input/2025/BLUE SEA/Presupuesto 253044/dupen.pdf",
    "/app/data/input/2025/some/path",
    "/app/data/input/2025/MAJESTIC 4(MAJ4)/Presupuesto 251723/IMAGENES/Contenedor Cerrado.jpeg",
]

for p in paths:
    result = extract_budget_code_from_path(p)
    print(f"  {result} <- {p}")
