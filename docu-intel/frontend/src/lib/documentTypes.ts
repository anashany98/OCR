// Catálogo único de document_type para toda la app.
// Añadir tipos nuevos aquí; los filtros y badges los heredan.
// `value` debe coincidir EXACTAMENTE con el string del backend.

export type DocumentTypeValue =
  | "presupuesto"
  | "pedido"
  | "factura"
  | "albaran"
  | "hoja_confeccion"
  | "plano"
  | "contrato"
  | "email_exportado"
  | "excel"
  | "imagen"
  // Subtipos de imagen
  | "foto_producto"
  | "muestra_tela"
  | "croquis_medida"
  // Documentos administrativos
  | "comprobante_pago"
  | "dua"
  | "albaran_transporte"
  // Técnicos / comerciales
  | "ficha_tecnica"
  | "tarifa"
  | "proforma"
  | "instrucciones"
  | "render"
  | "desconocido"

export interface DocumentTypeOption {
  value: DocumentTypeValue | ""
  label: string
  color?: string // clase de color del design system, opcional
}

export const DOCUMENT_TYPES: DocumentTypeOption[] = [
  { value: "", label: "Todos" },
  { value: "presupuesto", label: "Presupuesto", color: "info" },
  { value: "pedido", label: "Pedido", color: "success" },
  { value: "factura", label: "Factura", color: "warning" },
  { value: "albaran", label: "Albarán" },
  { value: "albaran_transporte", label: "Albarán transporte", color: "warning" },
  { value: "hoja_confeccion", label: "Hoja confección" },
  { value: "plano", label: "Plano", color: "accent" },
  { value: "contrato", label: "Contrato" },
  { value: "email_exportado", label: "Email" },
  { value: "excel", label: "Excel", color: "surface-2" },
  // Imágenes
  { value: "imagen", label: "Imagen", color: "surface-2" },
  { value: "foto_producto", label: "Foto producto", color: "surface-2" },
  { value: "muestra_tela", label: "Muestra tela", color: "surface-2" },
  { value: "croquis_medida", label: "Croquis / medida", color: "surface-2" },
  // Administrativos
  { value: "comprobante_pago", label: "Comprobante de pago" },
  { value: "dua", label: "DUA (aduanero)" },
  // Técnicos / comerciales
  { value: "ficha_tecnica", label: "Ficha técnica" },
  { value: "tarifa", label: "Tarifa / precios" },
  { value: "proforma", label: "Proforma / confirmación" },
  { value: "instrucciones", label: "Instrucciones / manual" },
  { value: "render", label: "Render 3D" },
  { value: "desconocido", label: "Otro / desconocido" },
]

// Lista plana de valores (string[]) para componentes que esperan string[].
export const DOCUMENT_TYPE_VALUES: string[] = DOCUMENT_TYPES.map((t) => t.value)

// Mapa value → label para render rápido (sin "Todos").
export const DOCUMENT_TYPE_LABELS: Record<string, string> = Object.fromEntries(
  DOCUMENT_TYPES.filter((t) => t.value !== "").map((t) => [t.value, t.label]),
)

export function documentTypeLabel(value: string | null | undefined): string {
  if (!value) return "—"
  return DOCUMENT_TYPE_LABELS[value] ?? value.charAt(0).toUpperCase() + value.slice(1)
}
