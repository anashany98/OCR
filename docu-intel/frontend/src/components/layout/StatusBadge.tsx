import { Badge, type BadgeProps } from "@/components/ui/badge"
import { statusTone } from "@/lib/status"

const variants: Record<ReturnType<typeof statusTone>, BadgeProps["variant"]> = {
  success: "success",
  info: "info",
  warning: "warning",
  danger: "danger",
  neutral: "neutral",
}

export function StatusBadge({ status }: { status: string }) {
  return <Badge variant={variants[statusTone(status)]}>{status}</Badge>
}
