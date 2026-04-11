"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { FileText, Loader2, MoreHorizontal, Plus, Trash2 } from "lucide-react";
import {
  deleteDocument,
  listDocuments,
  uploadDocument,
  type DocumentSummary,
  type DocumentStatus,
} from "@/lib/documents-api";
import { FileDropZone } from "@/components/file-drop-zone";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const DOCUMENTS_PAGE_SIZE = 20;

// Single source of truth: status label + dot color. No background pills.
const STATUS_DOT: Record<DocumentStatus, { label: string; dot: string; pulse?: boolean }> = {
  uploaded: { label: "排队中", dot: "bg-muted-foreground/40", pulse: true },
  extracting: { label: "提取中", dot: "bg-muted-foreground/60", pulse: true },
  extracted: { label: "已提取", dot: "bg-foreground/70" },
  error: { label: "失败", dot: "bg-red-500" },
};

function StatusDot({ status }: { status: DocumentStatus }) {
  const cfg = STATUS_DOT[status];
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
      <span className="relative inline-flex h-1.5 w-1.5">
        <span className={`relative inline-flex h-1.5 w-1.5 rounded-full ${cfg.dot}`} />
        {cfg.pulse ? (
          <span className={`absolute inset-0 inline-flex animate-ping rounded-full opacity-60 ${cfg.dot}`} />
        ) : null}
      </span>
      <span className="text-foreground/80">{cfg.label}</span>
    </span>
  );
}

const toUTC = (s: string) => s.endsWith("Z") || s.includes("+") ? s : s + "Z";
function formatRelative(iso: string | null) {
  if (!iso) return "—";
  const then = new Date(toUTC(iso)).getTime();
  const now = Date.now();
  const diffMs = now - then;
  const sec = Math.round(diffMs / 1000);
  if (sec < 60) return "刚刚";
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} 分钟前`;
  const hour = Math.round(min / 60);
  if (hour < 24) return `${hour} 小时前`;
  const day = Math.round(hour / 24);
  if (day < 30) return `${day} 天前`;
  return new Date(toUTC(iso)).toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
}

export default function DocumentsPage() {
  const router = useRouter();
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [showUploadDialog, setShowUploadDialog] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<DocumentSummary | null>(null);
  const [deleting, setDeleting] = useState(false);

  const fetchDocuments = useCallback(async () => {
    try {
      const result = await listDocuments({ limit: DOCUMENTS_PAGE_SIZE, offset: 0 });
      setDocuments(result.items);
      setTotal(result.total);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "加载文档失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

  // Poll while any document is still being extracted, so the list reflects
  // the new "已提取" / "失败" state without the user having to refresh.
  // Stops automatically once nothing is in progress.
  useEffect(() => {
    const inFlight = documents.some(
      (d) => d.status === "uploaded" || d.status === "extracting",
    );
    if (!inFlight) return;
    const id = setInterval(() => {
      fetchDocuments();
    }, 2000);
    return () => clearInterval(id);
  }, [documents, fetchDocuments]);

  const handleUpload = async (file: File) => {
    setUploading(true);
    try {
      const document = await uploadDocument(file);
      toast.success("文档已上传，正在提取");
      setShowUploadDialog(false);
      router.push(`/dashboard/documents/${document.id}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "上传失败");
    } finally {
      setUploading(false);
    }
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    const target = pendingDelete;
    const force = Boolean(target.linked_order_id);
    setDeleting(true);
    try {
      await deleteDocument(target.id, force);
      setDocuments((prev) => prev.filter((d) => d.id !== target.id));
      setTotal((t) => Math.max(0, t - 1));
      toast.success(
        force && target.linked_order_id
          ? `文档已删除，订单 #${target.linked_order_id} 已解除关联`
          : "文档已删除",
      );
      setPendingDelete(null);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "删除失败");
    } finally {
      setDeleting(false);
    }
  };

  const summary = useMemo(() => {
    const pending = documents.filter(
      (d) => d.doc_type === "purchase_order" && d.status === "extracted" && !d.linked_order_id,
    ).length;
    const linked = documents.filter((d) => Boolean(d.linked_order_id)).length;
    const failed = documents.filter((d) => d.status === "error").length;
    return { pending, linked, failed };
  }, [documents]);

  if (loading) {
    return (
      <div className="mx-auto max-w-6xl space-y-6 px-8 py-10">
        <div className="space-y-2">
          <Skeleton className="h-7 w-32" />
          <Skeleton className="h-4 w-64" />
        </div>
        <Skeleton className="h-[420px] w-full rounded-md" />
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto">
      <div className="mx-auto max-w-6xl px-8 py-10">
        {/* Header — flat, no card, no gradient */}
        <header className="mb-8 flex items-end justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">文档</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {total} 份文档
              {summary.pending > 0 ? <> · <span className="text-foreground/80">{summary.pending} 待处理</span></> : null}
              {summary.linked > 0 ? <> · {summary.linked} 已成单</> : null}
              {summary.failed > 0 ? <> · <span className="text-red-600 dark:text-red-400">{summary.failed} 失败</span></> : null}
            </p>
          </div>
          <Button onClick={() => setShowUploadDialog(true)} className="h-9 gap-1.5">
            <Plus className="h-4 w-4" />
            上传文档
          </Button>
        </header>

        {/* List — table, not cards */}
        {documents.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-md border border-dashed border-border/60 py-20 text-center">
            <FileText className="mb-3 h-8 w-8 text-muted-foreground/60" />
            <p className="text-sm font-medium">暂无文档</p>
            <p className="mt-1 text-xs text-muted-foreground">上传 PDF 或 Excel 开始</p>
            <Button
              variant="outline"
              size="sm"
              className="mt-4 h-8"
              onClick={() => setShowUploadDialog(true)}
            >
              上传文档
            </Button>
          </div>
        ) : (
          <div className="rounded-md border border-border/60">
            <Table>
              <TableHeader>
                <TableRow className="border-border/60 hover:bg-transparent">
                  <TableHead className="h-10 text-xs font-medium text-muted-foreground">名称</TableHead>
                  <TableHead className="h-10 w-20 text-xs font-medium text-muted-foreground">类型</TableHead>
                  <TableHead className="h-10 w-28 text-xs font-medium text-muted-foreground">状态</TableHead>
                  <TableHead className="h-10 w-24 text-xs font-medium text-muted-foreground">订单</TableHead>
                  <TableHead className="h-10 w-28 text-xs font-medium text-muted-foreground">上传</TableHead>
                  <TableHead className="h-10 w-12" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {documents.map((document) => (
                  <TableRow
                    key={document.id}
                    className="cursor-pointer border-border/60 hover:bg-muted/40"
                    onClick={() => router.push(`/dashboard/documents/${document.id}`)}
                  >
                    <TableCell className="py-3">
                      <div className="flex min-w-0 items-center gap-2.5">
                        <FileText className="h-4 w-4 shrink-0 text-muted-foreground/70" />
                        <span className="truncate font-medium">{document.filename}</span>
                      </div>
                    </TableCell>
                    <TableCell className="py-3 text-xs uppercase tracking-wide text-muted-foreground">
                      {document.file_type}
                    </TableCell>
                    <TableCell className="py-3">
                      <StatusDot status={document.status} />
                    </TableCell>
                    <TableCell className="py-3 text-sm text-muted-foreground">
                      {document.linked_order_id ? (
                        <span className="text-foreground/80">#{document.linked_order_id}</span>
                      ) : (
                        "—"
                      )}
                    </TableCell>
                    <TableCell className="py-3 text-xs text-muted-foreground">
                      {formatRelative(document.created_at)}
                    </TableCell>
                    <TableCell className="py-3 text-right">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7 text-muted-foreground hover:text-foreground"
                            onClick={(e) => e.stopPropagation()}
                            aria-label="更多操作"
                          >
                            <MoreHorizontal className="h-4 w-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-32">
                          <DropdownMenuItem
                            onClick={(e) => {
                              e.stopPropagation();
                              router.push(`/dashboard/documents/${document.id}`);
                            }}
                          >
                            查看详情
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onClick={(e) => {
                              e.stopPropagation();
                              setPendingDelete(document);
                            }}
                            className="text-red-600 focus:text-red-600 dark:text-red-400 dark:focus:text-red-400"
                          >
                            <Trash2 className="mr-2 h-3.5 w-3.5" />
                            删除
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>

      {/* Upload dialog */}
      <Dialog open={showUploadDialog} onOpenChange={setShowUploadDialog}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle className="text-lg">上传文档</DialogTitle>
            <DialogDescription>支持 PDF 和 Excel，单个文件最大 30 MB</DialogDescription>
          </DialogHeader>
          <FileDropZone onFile={handleUpload} accept=".pdf,.xlsx" label="拖放文件到此处" disabled={uploading} maxSizeMB={30} />
        </DialogContent>
      </Dialog>

      {/* Delete confirmation */}
      <AlertDialog
        open={Boolean(pendingDelete)}
        onOpenChange={(open) => {
          if (!open && !deleting) setPendingDelete(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除文档</AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-2 text-sm leading-6">
                <div>
                  确认要删除 <span className="font-medium text-foreground">{pendingDelete?.filename}</span> 吗？此操作不可撤销。
                </div>
                {pendingDelete?.linked_order_id ? (
                  <div className="text-muted-foreground">
                    该文档已生成订单 #{pendingDelete.linked_order_id}。删除后订单会保留，但与此源文档解除关联。
                  </div>
                ) : null}
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                e.preventDefault();
                confirmDelete();
              }}
              disabled={deleting}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleting ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : null}
              {pendingDelete?.linked_order_id ? "强制删除" : "删除"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
