import { useMatches } from "react-router-dom"

export interface Breadcrumb {
  label: string
  path: string
}

/**
 * Derives breadcrumbs from the current route matches.
 * Each route can define a `handle` with `breadcrumb` property.
 *
 * Usage in route definition:
 *   { path: "documents", element: ..., handle: { breadcrumb: "Documentos" } }
 *   { path: "documents/:id", element: ..., handle: { breadcrumb: (params) => params.id } }
 */
export function useBreadcrumbs(): Breadcrumb[] {
  const matches = useMatches()

  return matches
    .filter(
      (match) =>
        match.handle &&
        (match.handle as { breadcrumb?: string | ((params: Record<string, string>) => string) })
          .breadcrumb,
    )
    .map((match) => {
      const handle = match.handle as {
        breadcrumb: string | ((params: Record<string, string>) => string)
      }
      const label =
        typeof handle.breadcrumb === "function"
          ? handle.breadcrumb(match.params as Record<string, string>)
          : handle.breadcrumb
      return { label, path: match.pathname }
    })
}
