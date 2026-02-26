"use client";

import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="text-center max-w-md px-6">
        <div className="w-12 h-12 rounded-full bg-destructive/10 flex items-center justify-center mx-auto mb-4">
          <AlertTriangle className="h-6 w-6 text-destructive" />
        </div>
        <h2 className="text-base font-semibold mb-2">页面出错了</h2>
        <p className="text-xs text-muted-foreground mb-4">
          {error.message || "发生了意外错误"}
        </p>
        <div className="flex items-center justify-center gap-3">
          <Button size="sm" onClick={reset}>
            重试
          </Button>
          <Button size="sm" variant="outline" asChild>
            <a href="/dashboard">返回首页</a>
          </Button>
        </div>
      </div>
    </div>
  );
}
