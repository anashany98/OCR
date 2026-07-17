import { Link } from "react-router-dom"
import { ChevronRight, Home } from "lucide-react"

import { useBreadcrumbs } from "@/hooks/useBreadcrumbs"
import { cn } from "@/lib/utils"

/**
 * Auto-derived breadcrumbs from the router's `handle.breadcrumb`.
 * Replace manual Breadcrumbs components with this.
 */
export function AutoBreadcrumbs({ className }: { className?: string }) {
  const crumbs = useBreadcrumbs()

  if (crumbs.length <= 1) return null

  return (
    <nav
      aria-label="Breadcrumb"
      className={cn("flex items-center gap-1 text-[11px] text-[var(--text-muted)]", className)}
    >
      <ol className="flex flex-wrap items-center gap-1">
        {crumbs.map((crumb, index) => {
          const isLast = index === crumbs.length - 1
          return (
            <li key={crumb.path} className="flex items-center gap-1">
              {index === 0 && (
                <Link
                  to="/"
                  className="flex items-center gap-0.5 rounded px-1 py-0.5 transition-colors hover:bg-[var(--bg-surface-2)] hover:text-[var(--text-primary)]"
                >
                  <Home className="h-3 w-3" />
                </Link>
              )}
              {!isLast ? (
                <>
                  <ChevronRight
                    className="h-3 w-3 text-[var(--text-disabled)]"
                    aria-hidden="true"
                  />
                  <Link
                    to={crumb.path}
                    className="rounded px-1.5 py-0.5 transition-colors hover:bg-[var(--bg-surface-2)] hover:text-[var(--text-primary)]"
                  >
                    {crumb.label}
                  </Link>
                </>
              ) : (
                <>
                  <ChevronRight
                    className="h-3 w-3 text-[var(--text-disabled)]"
                    aria-hidden="true"
                  />
                  <span
                    className="px-1.5 py-0.5 font-medium text-[var(--text-primary)]"
                    aria-current="page"
                  >
                    {crumb.label}
                  </span>
                </>
              )}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
