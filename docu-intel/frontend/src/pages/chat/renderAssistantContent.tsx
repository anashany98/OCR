import type { ReactNode } from "react"

/**
 * Enhanced safe markdown renderer.
 * Supports: paragraphs, bold, italic, inline code, code blocks, links,
 * tables, unordered/ordered lists, blockquotes, headings, horizontal rules.
 */

type Block =
  | { kind: "p"; lines: string[] }
  | { kind: "ul"; items: string[] }
  | { kind: "ol"; items: string[] }
  | { kind: "quote"; lines: string[] }
  | { kind: "code"; language: string; lines: string[] }
  | { kind: "hr" }
  | { kind: "h1"; text: string }
  | { kind: "h2"; text: string }
  | { kind: "h3"; text: string }
  | { kind: "table"; headers: string[]; rows: string[][] }

function renderInline(text: string): ReactNode {
  const parts: ReactNode[] = []
  // Match: **bold**, *italic*, `code`, [text](url)
  const regex = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g
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
    } else if (raw.startsWith("*") && !raw.startsWith("**")) {
      parts.push(
        <em key={key++} className="italic text-[var(--text-secondary)]">
          {raw.slice(1, -1)}
        </em>,
      )
    } else if (raw.startsWith("`")) {
      parts.push(
        <code
          key={key++}
          className="rounded bg-[var(--bg-surface-3)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--accent)]"
        >
          {raw.slice(1, -1)}
        </code>,
      )
    } else if (raw.startsWith("[")) {
      const linkMatch = raw.match(/\[([^\]]+)\]\(([^)]+)\)/)
      if (linkMatch) {
        parts.push(
          <a
            key={key++}
            href={linkMatch[2]}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[var(--accent)] underline decoration-[var(--accent)]/30 underline-offset-2 hover:decoration-[var(--accent)]"
          >
            {linkMatch[1]}
          </a>,
        )
      }
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
  const lines = text.split("\n")
  let i = 0

  while (i < lines.length) {
    const line = lines[i]
    const trimmed = line.trim()

    // Empty line — skip
    if (!trimmed) {
      i++
      continue
    }

    // Code block (```language ... ```)
    if (trimmed.startsWith("```")) {
      const language = trimmed.slice(3).trim()
      const codeLines: string[] = []
      i++
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        codeLines.push(lines[i])
        i++
      }
      i++ // skip closing ```
      blocks.push({ kind: "code", language, lines: codeLines })
      continue
    }

    // Horizontal rule
    if (/^(-{3,}|\*{3,}|_{3,})\s*$/.test(trimmed)) {
      blocks.push({ kind: "hr" })
      i++
      continue
    }

    // Headings
    if (trimmed.startsWith("### ")) {
      blocks.push({ kind: "h3", text: trimmed.slice(4) })
      i++
      continue
    }
    if (trimmed.startsWith("## ")) {
      blocks.push({ kind: "h2", text: trimmed.slice(3) })
      i++
      continue
    }
    if (trimmed.startsWith("# ")) {
      blocks.push({ kind: "h1", text: trimmed.slice(2) })
      i++
      continue
    }

    // Table (lines with |)
    if (trimmed.includes("|") && trimmed.startsWith("|")) {
      const tableLines: string[] = []
      while (i < lines.length && lines[i].trim().includes("|") && lines[i].trim().startsWith("|")) {
        tableLines.push(lines[i])
        i++
      }
      if (tableLines.length >= 2) {
        const parseRow = (line: string) =>
          line
            .split("|")
            .slice(1, -1)
            .map((c) => c.trim())
        const headers = parseRow(tableLines[0])
        // Skip separator row (---|---|---)
        const dataRows = tableLines.slice(2).map(parseRow)
        blocks.push({ kind: "table", headers, rows: dataRows })
        continue
      }
    }

    // Blockquote
    if (trimmed.startsWith("> ")) {
      const quoteLines: string[] = []
      while (i < lines.length && lines[i].trim().startsWith("> ")) {
        quoteLines.push(lines[i].trim().slice(2))
        i++
      }
      blocks.push({ kind: "quote", lines: quoteLines })
      continue
    }

    // Unordered list
    if (/^[-*]\s+/.test(trimmed)) {
      const items: string[] = []
      while (i < lines.length && /^[-*]\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^[-*]\s+/, ""))
        i++
      }
      blocks.push({ kind: "ul", items })
      continue
    }

    // Ordered list
    if (/^\d+\.\s+/.test(trimmed)) {
      const items: string[] = []
      while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^\d+\.\s+/, ""))
        i++
      }
      blocks.push({ kind: "ol", items })
      continue
    }

    // Paragraph (collect consecutive non-empty lines)
    const pLines: string[] = []
    while (i < lines.length && lines[i].trim() && !lines[i].trim().startsWith("#") && !lines[i].trim().startsWith("> ") && !lines[i].trim().startsWith("```") && !/^[-*]\s+/.test(lines[i].trim()) && !/^\d+\.\s+/.test(lines[i].trim()) && !/^(-{3,}|\*{3,}|_{3,})\s*$/.test(lines[i].trim()) && !(lines[i].trim().includes("|") && lines[i].trim().startsWith("|"))) {
      pLines.push(lines[i].trim())
      i++
    }
    if (pLines.length > 0) {
      blocks.push({ kind: "p", lines: pLines })
    }
  }

  return blocks
}

export function renderAssistantContent(text: string) {
  const blocks = splitBlocks(text)
  if (blocks.length === 0) {
    return <p className="whitespace-pre-wrap text-[13px] leading-relaxed">{text}</p>
  }

  return (
    <div className="space-y-3 text-[13px] leading-relaxed">
      {blocks.map((b, i) => {
        switch (b.kind) {
          case "h1":
            return (
              <h1 key={i} className="text-[18px] font-bold text-[var(--text-primary)]">
                {renderInline(b.text)}
              </h1>
            )
          case "h2":
            return (
              <h2 key={i} className="text-[16px] font-bold text-[var(--text-primary)]">
                {renderInline(b.text)}
              </h2>
            )
          case "h3":
            return (
              <h3 key={i} className="text-[14px] font-semibold text-[var(--text-primary)]">
                {renderInline(b.text)}
              </h3>
            )
          case "hr":
            return <hr key={i} className="border-[var(--border)]" />
          case "code":
            return (
              <div key={i} className="overflow-hidden rounded-lg border border-[var(--border)]">
                {b.language && (
                  <div className="border-b border-[var(--border)] bg-[var(--bg-surface-3)] px-3 py-1 text-[10px] font-medium text-[var(--text-muted)]">
                    {b.language}
                  </div>
                )}
                <pre className="overflow-x-auto bg-[var(--bg-surface-2)] p-3">
                  <code className="font-mono text-[11px] leading-5 text-[var(--text-primary)]">
                    {b.lines.join("\n")}
                  </code>
                </pre>
              </div>
            )
          case "table":
            return (
              <div key={i} className="overflow-x-auto rounded-lg border border-[var(--border)]">
                <table className="w-full text-[12px]">
                  <thead>
                    <tr className="border-b border-[var(--border)] bg-[var(--bg-surface-2)]">
                      {b.headers.map((h, j) => (
                        <th key={j} className="px-3 py-2 text-left font-semibold text-[var(--text-primary)]">
                          {renderInline(h)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {b.rows.map((row, j) => (
                      <tr key={j} className="border-b border-[var(--border)] last:border-0">
                        {row.map((cell, k) => (
                          <td key={k} className="px-3 py-2 text-[var(--text-secondary)]">
                            {renderInline(cell)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          case "ul":
            return (
              <ul key={i} className="list-disc space-y-1 pl-5 text-[var(--text-secondary)]">
                {b.items.map((item, j) => (
                  <li key={j}>{renderInline(item)}</li>
                ))}
              </ul>
            )
          case "ol":
            return (
              <ol key={i} className="list-decimal space-y-1 pl-5 text-[var(--text-secondary)]">
                {b.items.map((item, j) => (
                  <li key={j}>{renderInline(item)}</li>
                ))}
              </ol>
            )
          case "quote":
            return (
              <blockquote
                key={i}
                className="border-l-2 border-[var(--accent)]/40 bg-[var(--accent-faint)]/30 px-3 py-2 italic text-[var(--text-secondary)]"
              >
                {b.lines.map((line, j) => (
                  <p key={j} className={j === 0 ? "" : "mt-1"}>
                    {renderInline(line)}
                  </p>
                ))}
              </blockquote>
            )
          default:
            return (
              <p key={i} className="whitespace-pre-wrap text-[var(--text-secondary)]">
                {b.lines.map((line, j) => (
                  <span key={j}>
                    {j > 0 && <br />}
                    {renderInline(line)}
                  </span>
                ))}
              </p>
            )
        }
      })}
    </div>
  )
}
