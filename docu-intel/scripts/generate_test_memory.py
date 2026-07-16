"""
Genera memoria constructiva de prueba para validar PM4.1 y PM4.2.
"""
import json
from pathlib import Path


MEMORY_TEXT = """MEMORIA CONSTRUCTIVA
VIVIENDA UNIFAMILIAR - PROYECTO EJEMPLO

1 Objeto de la obra
La presente memoria constructiva describe las soluciones adoptadas para la ejecución de la vivienda unifamiliar situada en Madrid, calle Ejemplo 123.

2 Soluciones constructivas

2.1 Cimentación
La cimentación se realizará mediante losa de hormigón armado, con espesor de 30 cm. Hormigón HA-25, acero B500S. Armadura inferior Ø12@150. Despiece de arranque Ø10@200.

2.2 Estructura
La estructura será de hormigón armado ejecutada in situ. Forjados unidireccionales con vigas de 25x50 cm y losas aligeradas de 20 cm de espesor. Resistencia al fuego: REI 60.

2.3 Cerramientos exteriores
Muro exterior de fábrica de ladrillo de 14 cm, aislamiento térmico de 5 cm de poliestireno expandido (EPS) y acabado de mortero color. Coeficiente de transmitancia térmica U = 0.35 W/m²K. Aislamiento acústico Rw = 45 dB.

2.4 Tabiquería interior
Tabique de Pladur doble capa, 10 cm de espesor. Placa Fassa Bartolo PL40, perfil CD-50. Aislamiento con lana de roca de 50 mm. Resistencia al fuego REI 30. Ruido de impacto L'n,w = 53 dB.

2.5 Carpintería interior
Puertas de interior de madera de pino, 2,10 x 0,90 m. Bisagras de acero inoxidable. Cerradura de seguridad marca Tesa.

2.6 Pavimentos
Pavimento de porcelanato 60x60 cm, colocación con cola flexible. Rejilla de dilatación每 6 metros lineales. Espesor de mortero de asiento 3 cm.

3 Instalaciones

3.1 Fontanería
Tubería de polietileno reticulado (PERT-AL-PERT) para agua fría y caliente. Diámetro 16-20 mm. Conductos de PVC para desagüe Ø 100 mm. Norma UNE-EN 806.

3.2 Electricidad
Cableado de cobre THHN, sección 2,5 mm² para tomas de corriente y 1,5 mm² para alumbrado. Cuadro de distribución con interruptores magnetotérmicos. Norma UNE-HD 60364.

3.3 Climatización
Sistema de climatización por aire acondicionado splits, potencia 3,5 kW. Conductos de fibra de vidrio con aislamiento de 25 mm. Norma UNE-EN 16798.

4 Acabados
Pintura de color blanco mate en todas las paredes. Techo de escayola con acabado liso. Rodapié de MDF lacado blanco, altura 10 cm.

5 Protección contra incendios
Clase de fuego: REI 60 para estructura, REI 30 para tabiques. Señalización de emergencia según norma UNE-EN ISO 7010.

6 Mantenimiento
Revisión anual de instalaciones de climatización. Limpieza de canalones cada 6 meses. Repintado exterior cada 5 años.
"""

MANIFEST = {
    "document_type": "memoria_constructiva",
    "expected": {
        "chapters": [
            {"number": "1", "title": "Objeto de la obra", "level": 1},
            {"number": "2", "title": "Soluciones constructivas", "level": 1},
            {"number": "2.1", "title": "Cimentación", "level": 2},
            {"number": "2.2", "title": "Estructura", "level": 2},
            {"number": "2.3", "title": "Cerramientos exteriores", "level": 2},
            {"number": "2.4", "title": "Tabiquería interior", "level": 2},
            {"number": "2.5", "title": "Carpintería interior", "level": 2},
            {"number": "2.6", "title": "Pavimentos", "level": 2},
            {"number": "3", "title": "Instalaciones", "level": 1},
            {"number": "3.1", "title": "Fontanería", "level": 2},
            {"number": "3.2", "title": "Electricidad", "level": 2},
            {"number": "3.3", "title": "Climatización", "level": 2},
            {"number": "4", "title": "Acabados", "level": 1},
            {"number": "5", "title": "Protección contra incendios", "level": 1},
            {"number": "6", "title": "Mantenimiento", "level": 1},
        ],
        "specifications": [
            {
                "system_element": "Cimentación",
                "material": "hormigón armado",
                "thickness_cm": 30,
                "standards": [],
            },
            {
                "system_element": "Estructura",
                "fire_rating": "REI 60",
                "thickness_cm": None,
                "standards": [],
            },
            {
                "system_element": "Cerramientos exteriores",
                "material": "ladrillo",
                "thermal_insulation": "U = 0.35 W/m²K",
                "acoustic_rating": "Rw = 45 dB",
                "thickness_cm": None,
                "standards": [],
            },
            {
                "system_element": "Tabiquería interior",
                "material": "Pladur",
                "thickness_cm": 10,
                "fire_rating": "REI 30",
                "standards": [],
            },
        ],
    },
}


def generate_memory(output_dir: Path):
    """Generate test memory files."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write memory text
    memory_path = output_dir / "memoria_constructiva_ejemplo.txt"
    memory_path.write_text(MEMORY_TEXT, encoding="utf-8")
    print(f"Memoria generada: {memory_path}")

    # Write manifest
    manifest_path = output_dir / "memoria_constructiva_ejemplo.manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(MANIFEST, f, indent=2, ensure_ascii=False)
    print(f"Manifest generado: {manifest_path}")

    return memory_path, manifest_path


if __name__ == "__main__":
    base = Path(__file__).parent.parent / "data" / "input" / "memorias"
    generate_memory(base)
    print(f"\nEsperado: {json.dumps(MANIFEST['expected'], indent=2, ensure_ascii=False)}")
