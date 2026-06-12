import type { ReactNode } from "react"

/**
 * F8b - tiny safe markdown renderer.
 *
 * Supports the small subset that the LLM is allowed to emit:
 *
 * - paragraphs (separated by blank lines)
 * - **bold** and *italic* inline
 * - `inline code`
 * - unordered lists (- item or * item)
 * - block quotes (> quote)
 *
 * No HTML is allowed through; all output is plain text wrapped
 * in our own elements. The renderer is intentionally conservative
 * so a hostile LLM cannot inject scripts or break the layout.
 */

type Block = { kind: "p" | "ul" | "quote"; lines: string[] }

function renderInline(text: string): ReactNode {
  const parts: ReactNode[] = []
  const regex = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g
  let lastIndex = 0
  let match: RegExpExecArray | null
  let key = 0
  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index))
    }
    const raw = match[0]
    if (raw.startsWith("**")) {
      parts.push(
        <strong key={key++} className="font-semibold text-[var(--text-primary)]">
          {raw.slice(2, -2)}
        </strong>,
      )
    } else if (raw.startsWith("*")) {
      parts.push(
        <em key={key++} className="italic">
          {raw.slice(1, -1)}
        </em>,
      )
    } else if (raw.startsWith("`")) {
      parts.push(
        <code
          key={key++}
          className="rounded bg-[var(--bg-surface-2)] px-1 py-0.5 font-mono text-[12px]"
        >
          {raw.slice(1, -1)}
        </code>,
      )
    }
    lastIndex = regex.lastIndex
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex))
  }
  return parts
}

function splitBlocks(text: string): Block[] {
  const blocks: Block[] = []
  let current: Block | null = null
  const flush = () => {
    if (current && current.lines.some((l) => l.trim().length > 0)) {
      blocks.push(current)
    }
    current = null
  }
  for (const rawLine of text.split("\n")) {
    const line = rawLine.replace(/\s+$/, "")
    if (!line.trim()) {
      flush()
      continue
    }
    const isBullet = /^[-*]\s+/.test(line)
    const isQuote = /^>\s?/.test(line)
    let kind: Block["kind"] = "p"
    let content = line
    if (isBullet) {
      kind = "ul"
      content = line.replace(/^[-*]\s+/, "")
    } else if (isQuote) {
      kind = "quote"
      content = line.replace(/^>\s?/, "")
    }
    if (!current || current.kind !== kind) {
      flush()
      current = { kind, lines: [content] }
    } else {
      current.lines.push(content)
    }
  }
  flush()
  return blocks
}

export function renderAssistantContent(text: string) {
  const blocks = splitBlocks(text)
  if (blocks.length === 0) {
    return <p className="whitespace-pre-wrap leading-relaxed">{text}</p>
  }
  return (
    <div className="space-y-3 text-[14.5px] leading-relaxed">
      {blocks.map((b, i) => {
        if (b.kind === "ul") {
          return (
            <ul key={i} className="list-disc space-y-1 pl-5">
              {b.lines.map((line, j) => (
                <li key={j}>{renderInline(line)}</li>
              ))}
            </ul>
          )
        }
        if (b.kind === "quote") {
          return (
            <blockquote
              key={i}
              className="border-l-2 border-[var(--accent)] bg-[var(--accent-faint)]/60 px-3 py-2 italic text-[var(--text-secondary)]"
            >
              {b.lines.map((line, j) => (
                <p key={j} className={j === 0 ? "" : "mt-1"}>
                  {renderInline(line)}
                </p>
              ))}
            </blockquote>
          )
        }
        return (
          <p key={i} className="whitespace-pre-wrap">
            {renderInline(b.lines.join(" "))}
          </p>
        )
      })}
    </div>
  )
}
