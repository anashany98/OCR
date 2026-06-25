import { useMemo } from "react"
import { NavLink, useLocation } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"

import { api } from "@/api/client"
import { useAuth } from "@/hooks/useAuth"
import {
  canSeeNavItem,
  NAV_GROUPS,
  NAV_ITEMS_BY_PATH,
  type NavItem,
  type NavGroup,
} from "@/navigation/config"
import { useRecentNav } from "@/navigation/useRecentNav"
import { cn } from "@/lib/utils"

export type { NavItem, NavGroup }
export { NAV_GROUPS } from "@/navigation/config"

// ---------------------------------------------------------------------------
// SidebarNav — shared navigation content used by the persistent desktop
// sidebar and the mobile drawer.
// ---------------------------------------------------------------------------
export function SidebarNav({
  embedded = false,
  onNavigate,
}: {
  embedded?: boolean
  onNavigate?: () => void
}) {
  const { user } = useAuth()
  const location = useLocation()
  const recentPaths = useRecentNav()

  const inbox = useQuery({
    queryKey: ["work-inbox-count"],
    queryFn: () => api.workInboxCount(),
    refetchInterval: 30000,
  })
  const inboxCount = inbox.data?.count ?? 0

  const recentItems = useMemo(() => {
    return recentPaths
      .map((p) => NAV_ITEMS_BY_PATH.get(p))
      .filter((item): item is NavItem => Boolean(item))
      .filter((item) => canSeeNavItem(item, user?.role))
  }, [recentPaths, user?.role])

  function isActive(to: string): boolean {
    const path = to.split("?")[0].split("#")[0] // drop the unused hash fragment
    const targetHash = to.includes("#") ? to.split("#")[1] : undefined
    if (path === "/") return location.pathname === "/" && !location.hash
    if (location.pathname !== path) return false
    if (targetHash && location.hash !== `#${targetHash}`) return false
    return true
  }

  const groupSpacing = "mb-5 last:mb-3"

  return (
    <div className={cn("flex flex-col h-full", embedded ? "p-3" : "py-3")}>
      {/* Recientes */}
      {recentItems.length > 0 && (
        <div className={cn("mb-4", !embedded && "border-b border-[var(--sidebar-border)]/50 pb-3")}>
          <SidebarSectionLabel>Recientes</SidebarSectionLabel>
          <ul className="space-y-0.5">
            {recentItems.map((item) => {
              const Icon = item.icon
              const active = isActive(item.to)
              return (
                <li key={`recent-${item.to}`}>
                  <NavLink
                    to={item.to}
                    onClick={() => onNavigate?.()}
                    className={cn(
                      "group/item flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[12.5px] transition-colors duration-fast ease-out",
                      active
                        ? "bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-text)]"
                        : "text-[var(--sidebar-muted)] hover:bg-[var(--sidebar-active-bg)]/60 hover:text-[var(--sidebar-text)]",
                    )}
                    title={item.label}
                  >
                    <Icon className="h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
                    <span className="truncate">{item.label}</span>
                  </NavLink>
                </li>
              )
            })}
          </ul>
        </div>
      )}

      {/* Nav groups */}
      {NAV_GROUPS.map((group) => {
        const visibleItems = group.items.filter((item) => canSeeNavItem(item, user?.role))
        if (!visibleItems.length) return null
        return (
          <div
            key={group.id}
            className={cn(
              groupSpacing,
              !embedded &&
                "border-t border-[var(--sidebar-border)]/50 pt-3 first:border-t-0 first:pt-0",
            )}
          >
            <SidebarSectionLabel>{group.label}</SidebarSectionLabel>
            <ul className="space-y-0.5">
              {visibleItems.map((item) => (
                <SidebarItem
                  key={`${item.to}-${item.label}`}
                  item={item}
                  active={isActive(item.to)}
                  inboxCount={item.badge ? inboxCount : 0}
                  onNavigate={onNavigate}
                />
              ))}
            </ul>
          </div>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section label
// ---------------------------------------------------------------------------
function SidebarSectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-1.5 flex items-center gap-1.5 px-2.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--sidebar-muted)]">
      <span className="h-px w-2 bg-[var(--sidebar-muted)]/40" aria-hidden="true" />
      <span>{children}</span>
    </p>
  )
}

// ---------------------------------------------------------------------------
// SidebarItem — active state with terracotta accent bar
// ---------------------------------------------------------------------------
function SidebarItem({
  item,
  active,
  inboxCount,
  onNavigate,
}: {
  item: NavItem
  active: boolean
  inboxCount: number
  onNavigate?: () => void
}) {
  const Icon = item.icon
  return (
    <li>
      <NavLink
        to={item.to}
        end={item.to === "/"}
        aria-current={active ? "page" : undefined}
        onClick={() => onNavigate?.()}
        className={cn(
          "group/item relative flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[12.5px] font-medium tracking-tight transition-all duration-fast ease-out",
          active
            ? "bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-text)]"
            : "text-[var(--sidebar-muted)] hover:bg-[var(--sidebar-active-bg)]/50 hover:text-[var(--sidebar-text)]",
        )}
      >
        {active && (
          <span
            aria-hidden="true"
            className="absolute inset-y-1.5 left-0 w-0.5 rounded-r-full bg-[var(--accent)]"
          />
        )}
        <Icon
          className={cn(
            "h-4 w-4 flex-shrink-0 transition-transform duration-fast ease-out",
            active && "scale-105",
          )}
          aria-hidden="true"
        />
        <span className="flex-1 truncate">{item.label}</span>
        {item.badge && inboxCount > 0 && (
          <span
            aria-label={`${inboxCount} ${inboxCount === 1 ? "tarea pendiente" : "tareas pendientes"}`}
            className={cn(
              "flex h-[18px] min-w-[18px] items-center justify-center rounded-full px-1.5 text-[10px] font-semibold tabular-nums leading-none",
              active
                ? "bg-[var(--accent)] text-white"
                : "bg-[var(--sidebar-muted)]/25 text-[var(--sidebar-text)]",
            )}
          >
            {inboxCount > 99 ? "99+" : inboxCount}
          </span>
        )}
        {item.beta && (
          <span className="rounded border border-[var(--warning)]/30 bg-[var(--warning-faint)] px-1 py-px text-[8.5px] font-semibold uppercase tracking-[0.08em] text-[var(--text-on-warning)]">
            β
          </span>
        )}
      </NavLink>
    </li>
  )
}
