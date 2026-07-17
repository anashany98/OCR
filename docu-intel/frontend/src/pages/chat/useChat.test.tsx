import { act, renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/hooks/useAiHistory", () => ({
  useAiHistory: () => ({ data: [], refetch: vi.fn() }),
}))

import { useChat } from "./useChat"

const CONVERSATIONS_KEY = "docu-intel:chat:conversations"
const ACTIVE_CONV_KEY = "docu-intel:chat:active-conv"

describe("useChat", () => {
  beforeEach(() => localStorage.clear())

  it("rehydrates metadata only and restores the active conversation", async () => {
    localStorage.setItem(
      CONVERSATIONS_KEY,
      JSON.stringify([
        {
          id: "saved",
          title: "Consulta guardada",
          messageCount: 2,
          createdAt: "2026-01-01",
          updatedAt: "2026-01-02",
          pinned: true,
        },
      ]),
    )
    localStorage.setItem(ACTIVE_CONV_KEY, "saved")

    const { result } = renderHook(() => useChat())

    await waitFor(() => expect(result.current.hydrated).toBe(true))
    expect(result.current.activeConvId).toBe("saved")
    expect(result.current.conversations[0]).toMatchObject({
      id: "saved",
      pinned: true,
      messages: [],
    })
  })

  it("creates, pins, filters, switches and deletes local conversations", async () => {
    const { result } = renderHook(() => useChat())
    await waitFor(() => expect(result.current.hydrated).toBe(true))

    act(() => result.current.newConversation())
    const firstId = result.current.activeConvId
    expect(firstId).toBeTruthy()
    act(() => result.current.togglePin(firstId!))
    expect(result.current.conversations[0]?.pinned).toBe(true)

    act(() => result.current.setSearchQuery("sin coincidencia"))
    expect(result.current.conversations).toEqual([])
    act(() => result.current.setSearchQuery(""))
    act(() => result.current.deleteConversation(firstId!))
    expect(result.current.activeConvId).toBeNull()
    expect(result.current.conversations).toEqual([])
  })
})
