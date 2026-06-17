import { describe, expect, it } from "vitest"

import {
  ocrFlowLiveQueryKey,
  ocrFlowDocumentQueryKey,
} from "./useAdminOcrFlowData"

describe("query keys", () => {
  it("live key is stable", () => {
    expect(ocrFlowLiveQueryKey()).toEqual(["ocr-flow", "live"])
  })
  it("document key includes the document id", () => {
    expect(ocrFlowDocumentQueryKey(42)).toEqual(["ocr-flow", "document", 42])
  })
  it("document key is null-safe", () => {
    expect(ocrFlowDocumentQueryKey(null)).toEqual([
      "ocr-flow",
      "document",
      null,
    ])
  })
})
