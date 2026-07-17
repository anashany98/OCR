/**
 * Centralized query key factory. Every hook that uses TanStack Query should
 * derive its keys from here so invalidation is predictable and consistent.
 *
 * Pattern: queryKeys.<domain>.<operation>(...args)
 */

export const queryKeys = {
  documents: {
    all: ["documents"] as const,
    list: (filters?: Record<string, unknown>) => ["documents", "list", filters] as const,
    detail: (id: string) => ["documents", "detail", id] as const,
    pages: (id: string) => ["documents", "pages", id] as const,
    blocks: (id: string, page?: number) => ["documents", "blocks", id, page] as const,
    entities: (id: string) => ["documents", "entities", id] as const,
    timeline: (id: string) => ["documents", "timeline", id] as const,
    reprocess: (id: string) => ["documents", "reprocess", id] as const,
  },
  workInbox: {
    all: ["work-inbox"] as const,
    list: (filters?: Record<string, unknown>) => ["work-inbox", "list", filters] as const,
    count: ["work-inbox", "count"] as const,
    detail: (id: string) => ["work-inbox", "detail", id] as const,
  },
  plans: {
    all: ["plans"] as const,
    list: () => ["plans", "list"] as const,
    detail: (id: string) => ["plans", "detail", id] as const,
    rooms: (id: string) => ["plans", "detail", id, "rooms"] as const,
    dimensions: (id: string) => ["plans", "detail", id, "dimensions"] as const,
    // PM7 overlay keys
    overlays: (id: number) => ["plans", id, "overlays"] as const,
    chatFacts: (id: number) => ["plans", id, "chat-facts"] as const,
    revisions: (id: number) => ["plans", id, "revisions"] as const,
  },
  search: {
    all: ["search"] as const,
    results: (query: string, mode?: string) => ["search", "results", query, mode] as const,
  },
  chat: {
    all: ["chat"] as const,
    history: () => ["chat", "history"] as const,
    conversations: () => ["chat", "conversations"] as const,
  },
  admin: {
    all: ["admin"] as const,
    health: ["admin", "health"] as const,
    users: ["admin", "users"] as const,
    jobs: ["admin", "jobs"] as const,
    quality: {
      duplicates: ["admin", "quality", "duplicates"] as const,
      quarantine: ["admin", "quality", "quarantine"] as const,
    },
    integrations: {
      clients: ["admin", "integrations", "clients"] as const,
    },
    learning: {
      suggestions: ["admin", "learning", "suggestions"] as const,
      patterns: ["admin", "learning", "patterns"] as const,
      health: ["admin", "learning", "health"] as const,
    },
  },
  business: {
    budgets: {
      all: ["business", "budgets"] as const,
      list: (filters?: Record<string, unknown>) =>
        ["business", "budgets", "list", filters] as const,
      detail: (id: string) => ["business", "budgets", "detail", id] as const,
    },
    orders: {
      all: ["business", "orders"] as const,
      list: (filters?: Record<string, unknown>) => ["business", "orders", "list", filters] as const,
      detail: (id: string) => ["business", "orders", "detail", id] as const,
    },
    invoices: {
      all: ["business", "invoices"] as const,
      list: (filters?: Record<string, unknown>) =>
        ["business", "invoices", "list", filters] as const,
      detail: (id: string) => ["business", "invoices", "detail", id] as const,
    },
    reconciliation: {
      all: ["business", "reconciliation"] as const,
      list: (filters?: Record<string, unknown>) =>
        ["business", "reconciliation", "list", filters] as const,
    },
  },
  system: {
    health: ["system-health"] as const,
  },
} as const
