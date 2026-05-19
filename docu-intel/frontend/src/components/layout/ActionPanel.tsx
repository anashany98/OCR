import type { ReactNode } from "react"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

export function ActionPanel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card className="overflow-hidden">
      <CardHeader className="pb-3">
        <CardTitle className="text-[14px] font-semibold">{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 px-5 pb-5">{children}</CardContent>
    </Card>
  )
}