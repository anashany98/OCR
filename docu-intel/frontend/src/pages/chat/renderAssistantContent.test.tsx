import { describe, expect, it } from "vitest"

import { renderAssistantContent } from "./renderAssistantContent"

function textOf(node: unknown): string {
  if (node == null || typeof node === "boolean") return ""
  if (typeof node === "string" || typeof node === "number") return String(node)
  if (Array.isArray(node)) return node.map(textOf).join("")
  if (typeof node === "object" && "props" in node) {
    return textOf((node as { props: { children?: unknown } }).props.children)
  }
  return ""
}

describe("renderAssistantContent", () => {
  it("returns plain text for empty input", () => {
    const out = renderAssistantContent("")
    expect(textOf(out)).toBe("")
  })

  it("renders bold inline", () => {
    const out = renderAssistantContent("Hola **mundo** cruel")
    expect(textOf(out)).toContain("mundo")
  })

  it("renders inline code", () => {
    const out = renderAssistantContent("Usa `npm test` para validar")
    expect(textOf(out)).toContain("npm test")
  })

  it("renders a bulleted list", () => {
    const out = renderAssistantContent("Items:\n- uno\n- dos\n- tres")
    expect(textOf(out)).toContain("uno")
    expect(textOf(out)).toContain("dos")
    expect(textOf(out)).toContain("tres")
  })

  it("does not pass through raw HTML", () => {
    const out = renderAssistantContent("<script>alert(1)</script>")
    const txt = textOf(out)
    expect(txt).toContain("<script>")
    // The text is rendered as plain text, not interpreted as HTML.
    expect(txt).not.toContain("JSX-rendered element")
  })
})
