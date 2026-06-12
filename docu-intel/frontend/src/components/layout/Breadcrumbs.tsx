import { Fragment, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { ChevronRight, Home } from "lucide-react"

import { cn } from "@/lib/utils"

export type BreadcrumbItem = {
  label: string
  to?: string
  icon?: ReactNode
}

/**
 * Renders a breadcrumb trail. The first item can be a synthetic "Home" if you
 * don't pass one. Items without `to` are rendered as the current page
 * (non-clickable, aria-current="page").
 *
 * Example:
 *   <Breadcrumbs items={[
 *     { label: "Documentos", to: "/documents" },
 *     { label: "Presupuesto 245745" },
 *   ]} />
 */
export function Breadcrumbs({
  items,
  showHome = true,
  className,
}: {
  items: BreadcrumbItem[]
  showHome?: boolean
  className?: string
}) {
  const all: BreadcrumbItem[] = showHome
    ? [{ label: "Inicio", to: "/", icon: <Home className="h-3.5 w-3.5" /> }, ...items]
    : items

  return (
    <nav
      aria-label="Breadcrumb"
      className={cn("flex items-center gap-1 text-[12px] text-[var(--text-muted)]", className)}
    >
      <ol className="flex flex-wrap items-center gap-1">
        {all.map((item, index) => {
          const isLast = index === all.length - 1
          return (
            <Fragment key={`${item.label}-${index}`}>
              <li className="flex items-center gap-1">
                {item.to && !isLast ? (
                  <Link
                    to={item.to}
                    className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 transition-colors hover:bg-[var(--bg-surface-2)] hover:text-[var(--text-primary)]"
                  >
                    {item.icon}
                    <span>{item.label}</span>
                  </Link>
                ) : (
                  <span
                    aria-current={isLast ? "page" : undefined}
                    className={cn(
                      "inline-flex items-center gap-1 px-1.5 py-0.5",
                      isLast && "font-medium text-[var(--text-primary)]",
                    )}
                  >
                    {item.icon}
                    <span className="truncate max-w-[260px]">{item.label}</span>
                  </span>
                )}
              </li>
              {!isLast && (
                <li aria-hidden="true" className="text-[var(--text-disabled)]">
                  <ChevronRight className="h-3 w-3" />
                </li>
              )}
            </Fragment>
          )
        })}
      </ol>
    </nav>
  )
}
