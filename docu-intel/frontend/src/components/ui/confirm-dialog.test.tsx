import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { ConfirmDialog } from "@/components/ui/confirm-dialog"

describe("ConfirmDialog", () => {
  it("calls confirm and cancel callbacks from an accessible dialog", () => {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()

    render(
      <ConfirmDialog
        open
        title="Pausar ingesta"
        description="Se detendran nuevos escaneos."
        confirmLabel="Pausar"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    )

    expect(screen.getByRole("dialog", { name: "Pausar ingesta" })).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Pausar" }))
    expect(onConfirm).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }))
    expect(onCancel).toHaveBeenCalledTimes(1)
  })

  it("renders nothing when closed", () => {
    render(
      <ConfirmDialog
        open={false}
        title="Eliminar"
        confirmLabel="Eliminar"
        onConfirm={() => undefined}
        onCancel={() => undefined}
      />,
    )

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  })
})
