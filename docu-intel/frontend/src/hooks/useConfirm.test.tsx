/**
 * F9: useConfirm hook + ConfirmDialogHost contract.
 *
 * Asserts that the promise-based confirm flow:
 *   1. resolves to ``true`` when the user clicks confirm,
 *   2. resolves to ``false`` when the user clicks cancel,
 *   3. renders the dialog as an accessible ``role="dialog"`` so
 *      screen readers announce the title.
 */
import { act, fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { ConfirmDialogHost, useConfirm } from "@/hooks/useConfirm"

// Note: an earlier draft of this file declared a top-level
// ``ConfirmHarness`` helper that nobody rendered. The tests below
// each define their own inline ``Probe`` / ``OpenButton`` component
// instead, so the harness was deleted (eslint flagged it as unused).

describe("useConfirm (F9)", () => {
  it("returns true when the user clicks confirm", async () => {
    let resolved: boolean | null = null
    function Probe() {
      const confirm = useConfirm()
      return (
        <button
          type="button"
          onClick={async () => {
            resolved = await confirm({
              title: "Eliminar presupuesto",
              confirmLabel: "Eliminar",
            })
          }}
        >
          abrir
        </button>
      )
    }
    render(
      <ConfirmDialogHost>
        <Probe />
      </ConfirmDialogHost>,
    )
    fireEvent.click(screen.getByRole("button", { name: "abrir" }))
    expect(await screen.findByRole("dialog", { name: "Eliminar presupuesto" })).toBeInTheDocument()
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Eliminar" }))
    })
    expect(resolved).toBe(true)
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  })

  it("returns false when the user clicks cancel", async () => {
    let resolved: boolean | null = null
    function Probe() {
      const confirm = useConfirm()
      return (
        <button
          type="button"
          onClick={async () => {
            resolved = await confirm({
              title: "¿Pausar ingesta?",
              confirmLabel: "Pausar",
            })
          }}
        >
          pausar
        </button>
      )
    }
    render(
      <ConfirmDialogHost>
        <Probe />
      </ConfirmDialogHost>,
    )
    fireEvent.click(screen.getByRole("button", { name: "pausar" }))
    await screen.findByRole("dialog", { name: "¿Pausar ingesta?" })
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Cancelar" }))
    })
    expect(resolved).toBe(false)
  })

  it("renders nothing before the user requests a confirm", () => {
    function OpenButton() {
      const confirm = useConfirm()
      return (
        <button
          type="button"
          onClick={() => {
            void confirm({ title: "Hola", confirmLabel: "OK" })
          }}
        >
          abrir
        </button>
      )
    }
    render(
      <ConfirmDialogHost>
        <OpenButton />
      </ConfirmDialogHost>,
    )
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  })
})
