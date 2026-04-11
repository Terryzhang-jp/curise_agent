"use client";

import { useState, useEffect } from "react";
import type { ChatSession } from "@/lib/chat-api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Plus, MoreHorizontal, Trash2, MessageSquare } from "lucide-react";

const toUTC = (s: string) => s.endsWith("Z") || s.includes("+") ? s : s + "Z";
function formatTime(dateStr: string) {
  return new Date(toUTC(dateStr)).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

interface SessionSidebarProps {
  sessions: ChatSession[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNewSession: () => void;
  onDelete: (id: string) => void;
  deletingId?: string | null;
  loading: boolean;
}

export default function SessionSidebar({
  sessions,
  activeId,
  onSelect,
  onNewSession,
  onDelete,
  deletingId,
  loading,
}: SessionSidebarProps) {
  const [deleteTarget, setDeleteTarget] = useState<ChatSession | null>(null);

  // Auto-close delete dialog when the session is removed from list (delete succeeded)
  useEffect(() => {
    if (deleteTarget && !sessions.find((s) => s.id === deleteTarget.id)) {
      setDeleteTarget(null);
    }
  }, [sessions, deleteTarget]);

  return (
    <div className="w-[260px] shrink-0 border-r border-border/50 bg-card/20 flex flex-col h-full overflow-hidden">
      {/* New session button */}
      <div className="p-3 shrink-0">
        <Button
          onClick={onNewSession}
          variant="outline"
          size="sm"
          className="w-full justify-center gap-1.5 text-xs"
        >
          <Plus className="h-3.5 w-3.5" />
          新建对话
        </Button>
      </div>

      <Separator className="opacity-50 shrink-0" />

      {/* Session list - plain overflow scroll */}
      <div className="flex-1 overflow-y-auto min-h-0">
        <div className="p-2 space-y-0.5">
          {loading && sessions.length === 0 ? (
            <p className="text-xs text-muted-foreground text-center py-8">
              加载中...
            </p>
          ) : sessions.length === 0 ? (
            <div className="text-center py-8">
              <MessageSquare className="h-5 w-5 text-muted-foreground/50 mx-auto mb-2" />
              <p className="text-xs text-muted-foreground">暂无对话记录</p>
            </div>
          ) : (
            sessions.map((s) => {
              const isActive = s.id === activeId;
              return (
                <div
                  key={s.id}
                  onClick={() => onSelect(s.id)}
                  className={cn(
                    "group relative px-3 py-2.5 rounded-lg cursor-pointer transition-colors",
                    isActive
                      ? "bg-primary/8 border border-primary/15"
                      : "hover:bg-muted/50 border border-transparent"
                  )}
                >
                  <div className="flex items-center gap-2">
                    {/* Title + time */}
                    <div className="min-w-0 flex-1">
                      <div
                        className={cn(
                          "text-xs truncate",
                          isActive
                            ? "text-primary font-medium"
                            : "text-foreground"
                        )}
                      >
                        {s.title}
                      </div>
                      <div className="text-[10px] text-muted-foreground mt-0.5">
                        {formatTime(s.created_at)}
                      </div>
                    </div>

                    {/* More menu (three dots) */}
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <button
                          onClick={(e) => e.stopPropagation()}
                          className={cn(
                            "shrink-0 rounded-md p-1 transition-all",
                            "opacity-0 group-hover:opacity-100",
                            "hover:bg-muted text-muted-foreground hover:text-foreground"
                          )}
                        >
                          <MoreHorizontal className="h-4 w-4" />
                        </button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="w-32">
                        <DropdownMenuItem
                          onClick={(e) => {
                            e.stopPropagation();
                            setDeleteTarget(s);
                          }}
                          className="text-destructive focus:text-destructive text-xs gap-2"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                          删除对话
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* Delete confirmation dialog */}
      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={(open) => {
          if (!open && !deletingId) setDeleteTarget(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除对话</AlertDialogTitle>
            <AlertDialogDescription>
              {'确定删除「'}
              {deleteTarget?.title}
              {'」？此操作不可撤销。'}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={!!deletingId}>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (deleteTarget) onDelete(deleteTarget.id);
              }}
              disabled={!!deletingId}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deletingId ? "删除中..." : "删除"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
