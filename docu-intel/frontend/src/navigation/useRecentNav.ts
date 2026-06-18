import { useEffect, useState } from "react"
import { useLocation } from "react-router-dom"

import { useAuth } from "@/hooks/useAuth"

const RECENT_KEY_PREFIX = "docu-intel:recent-nav:"
const MAX_RECENT = 4

function readRecent(userId: string | number | undefined): string[] {
  if (typeof window === "undefined" || !userId) return []
  try {
    const raw = window.localStorage.getItem(RECENT_KEY_PREFIX + userId)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed)
      ? parsed.filter((x): x is string => typeof x === "string").slice(0, MAX_RECENT)
      : []
  } catch {
    return []
  }
}

function writeRecent(userId: string | number | undefined, paths: string[]) {
  if (typeof window === "undefined" || !userId) return
  try {
    window.localStorage.setItem(RECENT_KEY_PREFIX + userId, JSON.stringify(paths.slice(0, MAX_RECENT)))
  } catch {
    /* ignore quota errors */
  }
}

/**
 * Track the most recent top-level paths the user has visited and
 * persist them in ``localStorage`` keyed by the current user id.
 *
 * Returns the current list of paths (newest first). The list is
 * updated in response to ``useLocation`` changes — the caller does
 * not need to call anything to record navigation, only to read.
 *
 * Paths are normalised to their first segment so ``/documents/123``
 * and ``/documents/456`` both count as the same entry. The root
 * path ``/`` is excluded.
 */
export function useRecentNav(): readonly string[] {
  const { user } = useAuth()
  const location = useLocation()
  const [recentPaths, setRecentPaths] = useState<string[]>(() => readRecent(user?.id))

  useEffect(() => {
    if (!user) return
    const segments = location.pathname.split("/").filter(Boolean)
    const currentPath = segments.length ? "/" + segments[0] : "/"
    if (!currentPath || currentPath === "/") return
    setRecentPaths((prev) => {
      const next = [currentPath, ...prev.filter((p) => p !== currentPath)].slice(0, MAX_RECENT)
      writeRecent(user.id, next)
      return next
    })
  }, [location.pathname, user])

  return recentPaths
}
