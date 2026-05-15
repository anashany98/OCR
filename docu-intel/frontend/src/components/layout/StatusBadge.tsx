import { Badge, type BadgeProps } from "@/components/ui/badge"

const variants: Record<string, BadgeProps["variant"]> = {
  processed: "success",
  processing: "secondary",
  pending: "outline",
  failed: "destructive",
  needs_review: "warning",
  duplicate: "outline",
}

export function StatusBadge({ status }: { status: string }) {
  return <Badge variant={variants[status] || "secondary"}>{status}</Badge>
}

