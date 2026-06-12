import { describe, expect, it } from "vitest"

import { mergeOcrFlowEvent } from "./useOcrFlowStream"

describe("mergeOcrFlowEvent", () => {
  it("appends a started job to the live list", () => {
    const next = mergeOcrFlowEvent(
      { jobs: [] },
      {
        type: "job.started",
        task_id: "t1",
        document_id: 1,
        task: "app.workers.tasks.process_document_task",
      },
    )
    expect(next.jobs.some((j) => j.document_id === 1)).toBe(true)
  })

  it("removes a job when it transitions to finished", () => {
    const next = mergeOcrFlowEvent(
      {
        jobs: [
          {
            job_id: 1,
            document_id: 1,
            original_filename: "a.pdf",
            job_type: "extract",
            status: "started",
            started_at: null,
            retries: 0,
            error: null,
          },
          {
            job_id: 2,
            document_id: 2,
            original_filename: "b.pdf",
            job_type: "extract",
            status: "started",
            started_at: null,
            retries: 0,
            error: null,
          },
        ],
      },
      { type: "job.finished", task_id: "t1", document_id: 1, state: "SUCCESS" },
    )
    expect(next.jobs).toHaveLength(1)
    expect(next.jobs[0].document_id).toBe(2)
  })

  it("replaces a placeholder for the same document", () => {
    const next = mergeOcrFlowEvent(
      {
        jobs: [
          {
            job_id: 0,
            document_id: 1,
            original_filename: "(iniciando…)",
            job_type: "extract",
            status: "queued",
            started_at: null,
            retries: 0,
            error: null,
          },
        ],
      },
      {
        type: "job.started",
        task_id: "t1",
        document_id: 1,
        task: "app.workers.tasks.extract_document",
      },
    )
    // Only one entry, replaced, not duplicated.
    expect(next.jobs).toHaveLength(1)
    expect(next.jobs[0].status).toBe("started")
  })

  it("ignores unknown event types", () => {
    const snapshot = { jobs: [] }
    const next = mergeOcrFlowEvent(snapshot, { type: "weird.event" })
    expect(next).toBe(snapshot)
  })
})
