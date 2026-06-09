import { describe, expect, it } from "vitest"

import {
  countByKind,
  filterTasks,
  getKindConfig,
  groupByPriority,
  type TaskItem,
} from "./useWorkInbox"

function task(overrides: Partial<TaskItem> = {}): TaskItem {
  return {
    id: "test-1",
    itemType: "auto",
    kind: "ocr_failed",
    title: "Tarea de prueba",
    description: "descripción",
    priority: "high",
    status: "open",
    documentId: null,
    pageId: null,
    jobId: null,
    assigneeUserId: null,
    createdAt: null,
    actionUrl: null,
    raw: {} as never,
    ...overrides,
  }
}

describe("getKindConfig", () => {
  it("returns a config for known kinds", () => {
    const cfg = getKindConfig("ocr_failed")
    expect(cfg.label).toBe("OCR fallido")
    expect(cfg.tone).toBe("danger")
  })

  it("falls back to a humanised label for unknown kinds", () => {
    const cfg = getKindConfig("totally_unknown_kind")
    expect(cfg.label).toBe("totally unknown kind")
    expect(cfg.tone).toBe("neutral")
  })
})

describe("groupByPriority", () => {
  it("groups tasks into the four buckets", () => {
    const tasks = [
      task({ id: "1", priority: "critical" }),
      task({ id: "2", priority: "high" }),
      task({ id: "3", priority: "normal" }),
      task({ id: "4", priority: "low" }),
      task({ id: "5", priority: "critical" }),
    ]
    const g = groupByPriority(tasks)
    expect(g.critical).toHaveLength(2)
    expect(g.high).toHaveLength(1)
    expect(g.normal).toHaveLength(1)
    expect(g.low).toHaveLength(1)
  })

  it("treats unknown priorities as normal", () => {
    const g = groupByPriority([task({ id: "1", priority: "weird" })])
    expect(g.normal).toHaveLength(1)
    expect(g.critical).toHaveLength(0)
  })

  it("returns empty arrays for empty input", () => {
    const g = groupByPriority([])
    expect(Object.values(g).every((arr) => arr.length === 0)).toBe(true)
  })
})

describe("countByKind", () => {
  it("counts occurrences per kind", () => {
    const tasks = [
      task({ id: "1", kind: "ocr_failed" }),
      task({ id: "2", kind: "ocr_failed" }),
      task({ id: "3", kind: "low_ocr" }),
    ]
    expect(countByKind(tasks)).toEqual({ ocr_failed: 2, low_ocr: 1 })
  })

  it("returns an empty object for no tasks", () => {
    expect(countByKind([])).toEqual({})
  })
})

describe("filterTasks", () => {
  const tasks: TaskItem[] = [
    task({ id: "1", kind: "ocr_failed", priority: "high", title: "factura rota" }),
    task({ id: "2", kind: "low_ocr", priority: "low", title: "presupuesto" }),
    task({ id: "3", kind: "ocr_failed", priority: "low", title: "pedido" }),
  ]

  it("returns everything when no filter is active", () => {
    expect(filterTasks(tasks, {})).toEqual(tasks)
  })

  it("filters by kind", () => {
    expect(filterTasks(tasks, { kind: "ocr_failed" }).map((t) => t.id)).toEqual(["1", "3"])
  })

  it("filters by priority", () => {
    expect(filterTasks(tasks, { priority: "low" }).map((t) => t.id)).toEqual(["2", "3"])
  })

  it("filters by search across title and description", () => {
    expect(filterTasks(tasks, { search: "factura" }).map((t) => t.id)).toEqual(["1"])
    expect(filterTasks(tasks, { search: "presupuesto" }).map((t) => t.id)).toEqual(["2"])
  })

  it("combines filters with AND semantics", () => {
    expect(
      filterTasks(tasks, { kind: "ocr_failed", priority: "low" }).map((t) => t.id),
    ).toEqual(["3"])
  })
})
