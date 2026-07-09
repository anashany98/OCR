export const queryKeys = {
  invoices: {
    all: ["invoices"] as const,
    list: (query: string) => ["invoices", query] as const,
    detail: (id: number) => ["invoices", id] as const,
  },
} as const
