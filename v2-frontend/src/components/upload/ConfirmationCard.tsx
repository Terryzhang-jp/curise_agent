"use client";

import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ConfirmationCardData } from "@/lib/chat-api";

interface ConfirmationCardProps {
  data: ConfirmationCardData;
  onQuickAction?: (text: string) => void;
}

export function ConfirmationCard({ data, onQuickAction }: ConfirmationCardProps) {
  return (
    <div className="max-w-[85%] rounded-xl border border-amber-200 bg-amber-50/50 dark:border-amber-900/50 dark:bg-amber-950/20 p-4">
      <div className="flex items-center gap-2 mb-2">
        <AlertTriangle className="h-4 w-4 text-amber-600 dark:text-amber-400 shrink-0" />
        <span className="font-medium text-sm text-amber-800 dark:text-amber-300">{data.title}</span>
      </div>
      {data.description && (
        <p className="text-sm text-muted-foreground mb-3">{data.description}</p>
      )}
      <div className="flex items-center gap-2">
        {data.actions.map((action, i) => (
          <Button
            key={i}
            variant={action.variant === "destructive" ? "destructive" : action.variant === "outline" ? "outline" : "default"}
            size="sm"
            onClick={() => onQuickAction?.(action.message)}
          >
            {action.label}
          </Button>
        ))}
      </div>
    </div>
  );
}
