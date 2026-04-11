"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { toast } from "sonner";
import {
  ArrowLeft,
  ArrowUpRight,
  Check,
  ChevronDown,
  ChevronRight,
  Loader2,
  MoreHorizontal,
  Trash2,
  X,
} from "lucide-react";
import {
  deleteDocument,
  getDocument,
  getDocumentOrderPayload,
  updateDocumentType,
  type DocumentDetail,
  type DocumentStatus,
  type ExtractionBlock,
  type OrderPayload,
  type SupportedDocType,
} from "@/lib/documents-api";
import {
  cancelChatAgent,
  createChatSession,
  sendChatMessage,
  streamChatMessages,
  type ChatMessage,
} from "@/lib/chat-api";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { MarkdownContent } from "@/components/markdown-content";
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
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

const STATUS_DOT: Record<DocumentStatus, { label: string; dot: string; pulse?: boolean }> = {
  uploaded: { label: "排队中", dot: "bg-muted-foreground/40", pulse: true },
  extracting: { label: "提取中", dot: "bg-muted-foreground/60", pulse: true },
  extracted: { label: "已提取", dot: "bg-foreground/70" },
  error: { label: "失败", dot: "bg-red-500" },
};

// Friendlier labels for the metadata description list
const META_LABELS: Record<string, string> = {
  po_number: "PO 号",
  ship_name: "船名",
  vendor_name: "供应商",
  delivery_date: "交货日期",
  order_date: "下单日期",
  currency: "币种",
  destination_port: "目的港",
  total_amount: "总金额",
};

const META_ORDER = [
  "po_number",
  "ship_name",
  "vendor_name",
  "delivery_date",
  "order_date",
  "currency",
  "destination_port",
  "total_amount",
];

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

function formatTime(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function resolvePreviewUrl(url: string | null) {
  if (!url) return null;
  if (url.startsWith("http://") || url.startsWith("https://")) return url;
  return `${API_BASE}${url}`;
}

function formatMetaValue(key: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (key === "total_amount" && typeof value === "number") {
    return value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  return String(value);
}

// ─── BlocksViewer ─────────────────────────────────────────────────────────
//
// Renders the universal block schema (Stage 1 v1.0) faithfully.
// One block = one section. No nesting beyond what the document itself has.
// Tables use the original column headers from the document — exactly as the
// user requested ("列名作 key、行作 value").

function BlocksViewer({
  blocks,
  title,
  language,
  pageCount,
}: {
  blocks: ExtractionBlock[];
  title: string | null;
  language: string | null;
  pageCount: number | null;
}) {
  const counts: Record<string, number> = {};
  for (const b of blocks) counts[b.type] = (counts[b.type] || 0) + 1;

  return (
    <section className="rounded-md border border-border/60">
      {/* Header */}
      <header className="flex items-center justify-between border-b border-border/60 px-5 py-3">
        <div>
          <div className="text-sm font-semibold">提取的完整内容</div>
          <div className="mt-0.5 text-xs text-muted-foreground">
            {title ? <span className="text-foreground/80">{title}</span> : null}
            {title ? " · " : null}
            {pageCount ? `${pageCount} 页` : null}
            {pageCount && language ? " · " : null}
            {language ? language.toUpperCase() : null}
            {(pageCount || language) ? " · " : null}
            {blocks.length} 个内容块
          </div>
        </div>
        <div className="hidden gap-3 text-[11px] text-muted-foreground sm:flex">
          {Object.entries(counts).map(([t, c]) => (
            <span key={t}>
              {BLOCK_TYPE_LABEL[t] || t}{" "}
              <span className="text-foreground/80">{c}</span>
            </span>
          ))}
        </div>
      </header>

      {/* Blocks */}
      <div className="divide-y divide-border/40">
        {blocks.map((block, idx) => (
          <BlockRow key={idx} block={block} index={idx} />
        ))}
      </div>
    </section>
  );
}

const BLOCK_TYPE_LABEL: Record<string, string> = {
  heading: "标题",
  paragraph: "段落",
  field_group: "字段组",
  table: "表格",
  list: "列表",
  signature_block: "签名",
  other: "其他",
};

function BlockRow({ block, index }: { block: ExtractionBlock; index: number }) {
  const pageLabel = formatPageLabel(block.page);

  switch (block.type) {
    case "heading": {
      const level = Math.min(Math.max(block.level || 2, 1), 4);
      const sizeClass = level === 1
        ? "text-base font-semibold"
        : level === 2
          ? "text-sm font-semibold"
          : "text-sm font-medium";
      return (
        <div className="px-5 py-3">
          <BlockMeta type="heading" page={pageLabel} index={index} />
          <div className={`mt-1 ${sizeClass}`}>{block.text || "—"}</div>
        </div>
      );
    }

    case "paragraph": {
      return (
        <div className="px-5 py-3">
          <BlockMeta type="paragraph" page={pageLabel} index={index} section={block.section} />
          <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-foreground/90">
            {block.text || "—"}
          </p>
        </div>
      );
    }

    case "field_group": {
      const fields = block.fields || [];
      return (
        <div className="px-5 py-3">
          <BlockMeta type="field_group" page={pageLabel} index={index} section={block.section} />
          <dl className="mt-2 grid gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2">
            {fields.map((f, i) => (
              <div key={i} className="flex items-baseline justify-between gap-3">
                <dt className="shrink-0 text-xs text-muted-foreground">
                  {f.label || <span className="italic">未标注</span>}
                </dt>
                <dd className="text-right font-medium tabular-nums break-all">
                  {f.value === null || f.value === undefined || f.value === ""
                    ? "—"
                    : f.value}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      );
    }

    case "table": {
      const columns = block.columns || [];
      const rows = block.rows || [];
      return (
        <div className="px-5 py-3">
          <BlockMeta type="table" page={pageLabel} index={index} extra={`${rows.length} 行 · ${columns.length} 列`} />
          {block.caption ? (
            <div className="mt-1 text-xs text-muted-foreground">{block.caption}</div>
          ) : null}
          <div className="mt-2 overflow-x-auto rounded-md border border-border/40">
            <table className="w-full text-xs">
              <thead className="bg-muted/40">
                <tr>
                  {columns.map((c) => (
                    <th
                      key={c}
                      className="whitespace-nowrap px-3 py-2 text-left font-medium text-muted-foreground"
                    >
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, 200).map((row, i) => (
                  <tr key={i} className="border-t border-border/40 hover:bg-muted/20">
                    {columns.map((c) => (
                      <td key={c} className="whitespace-nowrap px-3 py-1.5 text-foreground/90">
                        {formatCell(row[c])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            {rows.length > 200 ? (
              <div className="border-t border-border/40 px-3 py-2 text-center text-[11px] text-muted-foreground">
                共 {rows.length} 行，仅显示前 200 行
              </div>
            ) : null}
          </div>
        </div>
      );
    }

    case "list": {
      const items = block.items || [];
      const Tag = block.style === "numbered" ? "ol" : "ul";
      const className =
        block.style === "numbered"
          ? "list-decimal pl-5"
          : "list-disc pl-5";
      return (
        <div className="px-5 py-3">
          <BlockMeta type="list" page={pageLabel} index={index} />
          <Tag className={`mt-1 space-y-1 text-sm leading-6 text-foreground/90 ${className}`}>
            {items.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </Tag>
        </div>
      );
    }

    case "signature_block": {
      const labels = block.labels || [];
      const values = block.values || [];
      return (
        <div className="px-5 py-3">
          <BlockMeta type="signature_block" page={pageLabel} index={index} />
          <dl className="mt-1 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
            {labels.map((label, i) => (
              <div key={i} className="flex items-baseline justify-between gap-3">
                <dt className="text-xs text-muted-foreground">{label}</dt>
                <dd className="text-right font-medium">{values[i] || "—"}</dd>
              </div>
            ))}
          </dl>
        </div>
      );
    }

    case "other":
    default: {
      return (
        <div className="px-5 py-3">
          <BlockMeta type={block.type || "other"} page={pageLabel} index={index} />
          <pre className="mt-1 whitespace-pre-wrap font-sans text-sm leading-6 text-foreground/80">
            {block.text || JSON.stringify(block, null, 2)}
          </pre>
        </div>
      );
    }
  }
}

function BlockMeta({
  type,
  page,
  index,
  section,
  extra,
}: {
  type: string;
  page: string | null;
  index: number;
  section?: string;
  extra?: string;
}) {
  return (
    <div className="flex items-center gap-2 text-[10px] uppercase tracking-wide text-muted-foreground/70">
      <span className="font-mono">{String(index + 1).padStart(2, "0")}</span>
      <span>{BLOCK_TYPE_LABEL[type] || type}</span>
      {page ? <span>· p.{page}</span> : null}
      {section && section !== "unknown" ? <span>· {section}</span> : null}
      {extra ? <span>· {extra}</span> : null}
    </div>
  );
}

function formatPageLabel(page: number | number[] | undefined): string | null {
  if (page === undefined || page === null) return null;
  if (Array.isArray(page)) {
    if (page.length === 0) return null;
    if (page.length === 1) return String(page[0]);
    return `${page[0]}–${page[page.length - 1]}`;
  }
  return String(page);
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

export default function DocumentDetailPage() {
  const params = useParams();
  const router = useRouter();
  const documentId = Number(params.id);

  const [document, setDocument] = useState<DocumentDetail | null>(null);
  const [payload, setPayload] = useState<OrderPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [extractedOpen, setExtractedOpen] = useState(false);
  const [updatingType, setUpdatingType] = useState(false);

  // Inline Agent state — runs the process-document skill on this page,
  // streams thinking/tool calls/results into the right sidebar instead of
  // navigating away to /dashboard/workspace.
  type AgentStatus = "idle" | "running" | "stopping" | "done" | "error";
  const [agentStatus, setAgentStatus] = useState<AgentStatus>("idle");
  const [agentMessages, setAgentMessages] = useState<ChatMessage[]>([]);
  const [agentSessionId, setAgentSessionId] = useState<string | null>(null);
  const [agentError, setAgentError] = useState<string | null>(null);
  const [agentStartedAt, setAgentStartedAt] = useState<number | null>(null);
  const [agentElapsed, setAgentElapsed] = useState(0);
  const [agentInput, setAgentInput] = useState("");
  const streamAbortRef = useRef<(() => void) | null>(null);
  const activityScrollRef = useRef<HTMLDivElement | null>(null);
  const agentBusy = agentStatus === "running" || agentStatus === "stopping";

  const fetchDocument = useCallback(async () => {
    const detail = await getDocument(documentId);
    setDocument(detail);

    if (detail.status === "extracted" && detail.doc_type === "purchase_order") {
      try {
        const currentPayload = await getDocumentOrderPayload(documentId);
        setPayload(currentPayload);
      } catch {
        setPayload(null);
      }
    } else {
      setPayload(null);
    }
    return detail;
  }, [documentId]);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const run = async () => {
      try {
        const detail = await fetchDocument();
        if (cancelled) return;
        setLoading(false);
        if (detail.status === "uploaded" || detail.status === "extracting") {
          timer = setTimeout(run, 1500);
        }
      } catch (error) {
        if (cancelled) return;
        setLoading(false);
        toast.error(error instanceof Error ? error.message : "加载文档失败");
      }
    };

    run();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [fetchDocument]);

  const metadataPairs = useMemo(() => {
    const metadata = (document?.extracted_data?.metadata || {}) as Record<string, unknown>;
    const ordered: Array<[string, unknown]> = [];
    for (const key of META_ORDER) {
      if (metadata[key] !== undefined) ordered.push([key, metadata[key]]);
    }
    // Append any extra non-empty keys we don't have a label for
    for (const [k, v] of Object.entries(metadata)) {
      if (!META_ORDER.includes(k) && v !== null && v !== undefined && v !== "") {
        ordered.push([k, v]);
      }
    }
    return ordered;
  }, [document]);

  const productCount = (document?.extracted_data?.products || []).length;

  // Stage 1 v1.0 universal extraction fields (only present on new docs)
  const extractionBlocks: ExtractionBlock[] = useMemo(
    () => (document?.extracted_data?.blocks as ExtractionBlock[] | undefined) || [],
    [document],
  );
  const extractionTitle = document?.extracted_data?.title || null;
  const extractionLanguage = document?.extracted_data?.language || null;
  const extractionPageCount = document?.extracted_data?.page_count || null;

  // Confidence verdict from the PO projector. Drives the 4-state UI.
  const confidence = document?.extracted_data?.projection?.purchase_order
    ?.confidence as Record<string, unknown> | undefined;
  const confidenceVerdict = (confidence?.verdict as string | undefined) || null;
  const confidenceScore = (confidence?.score as number | undefined) ?? null;
  const confidenceMaxScore = (confidence?.max_score as number | undefined) ?? null;

  // Manual doc_type override. The user is the final authority on what this
  // document actually is. After updating, refetch the payload so the
  // primary CTA reflects the new type. Optionally auto-continue into the
  // inline agent flow when the updated type is immediately actionable.
  const handleChangeDocType = async (
    newType: SupportedDocType,
    options?: { continueIfReady?: boolean },
  ) => {
    if (!document || newType === document.doc_type || updatingType) return;
    setUpdatingType(true);
    try {
      const updated = await updateDocumentType(document.id, newType);
      setDocument(updated);
      let newPayload: OrderPayload | null = null;
      // Refetch payload so the order-creation gate reflects the new type
      if (updated.status === "extracted" && updated.doc_type === "purchase_order") {
        try {
          newPayload = await getDocumentOrderPayload(document.id);
          setPayload(newPayload);
        } catch {
          setPayload(null);
        }
      } else {
        setPayload(null);
      }
      toast.success(`类型已改为 ${newType === "purchase_order" ? "采购订单" : "未识别"}`);

      if (
        options?.continueIfReady &&
        updated.doc_type === "purchase_order" &&
        newPayload?.ready_for_order_creation
      ) {
        await runAgentInline();
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "类型修改失败");
    } finally {
      setUpdatingType(false);
    }
  };

  const handleDelete = async () => {
    if (!document) return;
    const force = Boolean(document.linked_order_id);
    setDeleting(true);
    try {
      await deleteDocument(document.id, force);
      toast.success(
        force && document.linked_order_id
          ? `文档已删除，订单 #${document.linked_order_id} 已解除关联`
          : "文档已删除",
      );
      router.push("/dashboard/documents");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "删除失败");
      setDeleting(false);
      setShowDeleteDialog(false);
    }
  };

  // Send a message to the document-processing agent IN PLACE on this page.
  // The right sidebar becomes a lightweight review console where the user can
  // iteratively correct extracted fields before deciding to continue.
  const sendDocumentAgentMessage = async (rawMessage: string) => {
    if (!document || agentBusy) return;
    const trimmed = rawMessage.trim();
    if (!trimmed) return;

    setAgentStatus("running");
    setAgentError(null);
    setAgentStartedAt(Date.now());
    setAgentElapsed(0);

    try {
      let sessionId = agentSessionId;
      if (!sessionId) {
        const session = await createChatSession(`文档 #${document.id}`);
        sessionId = session.id;
        setAgentSessionId(session.id);
        setAgentMessages([]);
      }

      const content = trimmed.startsWith("/")
        ? trimmed
        : [
            `当前文档 ID=${document.id}。`,
            `当前 linked_order_id=${document.linked_order_id ?? "none"}。`,
            `用户请求：${trimmed}`,
          ].join(" ");

      const { last_msg_id } = await sendChatMessage(
        sessionId,
        content,
        null,
        "document_processing",
      );

      streamAbortRef.current = streamChatMessages(
        sessionId,
        last_msg_id,
        (msg) => {
          setAgentMessages((prev) => [...prev, msg]);
        },
        () => {
          setAgentStatus("done");
          streamAbortRef.current = null;
          // Reload document so the page reflects the new linked_order_id
          fetchDocument().catch(() => {});
        },
        (err) => {
          setAgentError(err.message);
          setAgentStatus("error");
          streamAbortRef.current = null;
        },
      );
    } catch (error) {
      setAgentError(error instanceof Error ? error.message : String(error));
      setAgentStatus("error");
    }
  };

  const runAgentInline = async () => {
    await sendDocumentAgentMessage(`/process-document document_id=${documentId}`);
  };

  const handleAgentSubmit = async () => {
    const text = agentInput.trim();
    if (!text) return;
    setAgentInput("");
    await sendDocumentAgentMessage(text);
  };

  const cancelAgentRun = useCallback(async () => {
    if (!agentSessionId || !agentBusy) return;
    setAgentStatus("stopping");
    setAgentError(null);
    try {
      await cancelChatAgent(agentSessionId);
    } catch (error) {
      setAgentError(error instanceof Error ? error.message : "停止 Agent 失败");
      setAgentStatus("error");
    }
  }, [agentBusy, agentSessionId]);

  // Live elapsed-time ticker while agent is running
  useEffect(() => {
    if ((agentStatus !== "running" && agentStatus !== "stopping") || !agentStartedAt) return;
    const id = setInterval(() => {
      setAgentElapsed(Math.floor((Date.now() - agentStartedAt) / 1000));
    }, 1000);
    return () => clearInterval(id);
  }, [agentStatus, agentStartedAt]);

  // Auto-scroll the activity panel to the latest item
  useEffect(() => {
    if (!activityScrollRef.current) return;
    activityScrollRef.current.scrollTop = activityScrollRef.current.scrollHeight;
  }, [agentMessages]);

  // Tear down the SSE stream on unmount
  useEffect(() => {
    return () => {
      if (streamAbortRef.current) {
        streamAbortRef.current();
        streamAbortRef.current = null;
      }
    };
  }, []);

  if (loading) {
    return (
      <div className="mx-auto max-w-[1400px] px-8 py-10">
        <Skeleton className="mb-6 h-6 w-32" />
        <div className="grid gap-8 lg:grid-cols-[1fr_320px]">
          <Skeleton className="h-[760px] rounded-md" />
          <div className="space-y-6">
            <Skeleton className="h-32 rounded-md" />
            <Skeleton className="h-48 rounded-md" />
          </div>
        </div>
      </div>
    );
  }

  if (!document) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="space-y-3 text-center">
          <p className="text-sm text-muted-foreground">文档不存在</p>
          <Button variant="outline" size="sm" onClick={() => router.push("/dashboard/documents")}>
            返回文档列表
          </Button>
        </div>
      </div>
    );
  }

  const isProcessing = document.status === "uploaded" || document.status === "extracting";
  const isError = document.status === "error";
  const isPurchaseOrder = document.doc_type === "purchase_order";
  const previewUrl = resolvePreviewUrl(document.preview_url);
  const blockingFields = payload?.blocking_missing_fields || [];

  // ── Four-state primary action (commercial-grade design) ─────────────
  //
  // The button's existence and label depends on the system's confidence
  // that this document is something we can actually process. We explicitly
  // refuse to show a button for documents we can't handle — that would be
  // a false promise. Users can manually override the type if our
  // classification is wrong.
  //
  //   State A: high confidence PO + ready  → primary CTA "让 Agent 处理"
  //   State B: medium confidence (possibly) → confirm CTA + warning + override
  //   State C: low confidence / unknown    → no CTA + helper + override
  //   State D: already linked to order      → "前往订单 #N"
  //   (special: processing / error / missing fields / non-extracted excel)

  let primaryAction: React.ReactNode = null;
  let nextStepHint: string | null = null;
  let stateLabel: string | null = null;
  let showTypeOverride = false;

  if (isProcessing) {
    nextStepHint = "系统正在提取文档内容，页面会自动刷新";
  } else if (isError) {
    nextStepHint = document.processing_error || "提取失败，建议重新上传";
  } else if (document.linked_order_id) {
    // State D: already produced an order
    stateLabel = "已生成订单";
    primaryAction = (
      <Button
        className="h-9 w-full gap-1.5"
        onClick={() => router.push(`/dashboard/orders/${document.linked_order_id}`)}
      >
        前往订单 #{document.linked_order_id}
        <ArrowUpRight className="h-4 w-4" />
      </Button>
    );
  } else if (isPurchaseOrder && payload?.ready_for_order_creation && !agentBusy) {
    // State A: high-confidence PO, all fields present
    stateLabel = confidenceScore !== null && confidenceMaxScore !== null
      ? `识别为采购订单 · 信心 ${confidenceScore}/${confidenceMaxScore}`
      : "识别为采购订单";
    primaryAction = (
      <Button className="h-9 w-full gap-1.5" onClick={runAgentInline}>
        让 Agent 处理为订单
      </Button>
    );
  } else if (isPurchaseOrder && payload && !payload.ready_for_order_creation) {
    // State A.1: classified as PO but missing key fields — can't proceed
    stateLabel = "识别为采购订单，但缺关键字段";
    nextStepHint = `缺少：${blockingFields.join("、") || "未识别字段"}。请在源文档中补齐后重新上传。`;
    showTypeOverride = true;
  } else if (confidenceVerdict === "possibly_purchase_order") {
    // State B: medium confidence, ambiguous
    stateLabel = confidenceScore !== null && confidenceMaxScore !== null
      ? `可能是采购订单 · 信心 ${confidenceScore}/${confidenceMaxScore}`
      : "可能是采购订单";
    nextStepHint = "系统不太确定，需要你确认";
    primaryAction = (
      <Button
        variant="outline"
        className="h-9 w-full gap-1.5"
        onClick={() => handleChangeDocType("purchase_order", { continueIfReady: true })}
        disabled={updatingType}
      >
        {updatingType ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
        确认为 PO 并继续
      </Button>
    );
    showTypeOverride = true;
  } else {
    // State C: low confidence / not_purchase_order / unknown
    stateLabel = "未识别为支持的类型";
    nextStepHint =
      "当前系统只支持自动处理采购订单。这份文档可以预览和查看提取的结构化内容，但不会自动建单。如果你确认这是 PO，请手动改类型。";
    showTypeOverride = true;
  }

  // Build a clean activity timeline by merging each `action` (tool call) with
  // its immediately-following `observation` (tool result). Thinking entries
  // become collapsible items. The agent's final `text` answer becomes a
  // distinct prose block at the end.
  type ActivityItem =
    | { id: number; kind: "tool_done"; toolName: string; durationMs: number }
    | { id: number; kind: "tool_error"; toolName: string; durationMs: number; errorMsg: string }
    | { id: number; kind: "tool_running"; toolName: string }
    | { id: number; kind: "thinking"; summary: string; full: string }
    | { id: number; kind: "answer"; content: string }
    | { id: number; kind: "error"; content: string };

  const activityItems: ActivityItem[] = [];
  for (let i = 0; i < agentMessages.length; i++) {
    const m = agentMessages[i];
    if (m.msg_type === "user_input") continue;
    if (m.msg_type === "observation" || m.msg_type === "error_observation") continue;

    if (m.msg_type === "action") {
      const toolName = (m.metadata?.tool_name as string) || "tool";
      // Find the next observation that comes BEFORE the next action
      let obs: ChatMessage | null = null;
      for (let j = i + 1; j < agentMessages.length; j++) {
        const n = agentMessages[j];
        if (n.msg_type === "action") break;
        if (n.msg_type === "observation" || n.msg_type === "error_observation") {
          obs = n;
          break;
        }
      }
      if (obs) {
        const durationMs = (obs.metadata?.duration_ms as number) || 0;
        if (obs.msg_type === "error_observation") {
          activityItems.push({
            id: m.id,
            kind: "tool_error",
            toolName,
            durationMs,
            errorMsg: obs.content,
          });
        } else {
          activityItems.push({ id: m.id, kind: "tool_done", toolName, durationMs });
        }
      } else {
        activityItems.push({ id: m.id, kind: "tool_running", toolName });
      }
      continue;
    }

    if (m.msg_type === "thinking") {
      activityItems.push({
        id: m.id,
        kind: "thinking",
        summary: (m.metadata?.summary as string) || m.content.slice(0, 80),
        full: m.content,
      });
      continue;
    }

    if (m.msg_type === "text" && m.role === "assistant") {
      activityItems.push({ id: m.id, kind: "answer", content: m.content });
      continue;
    }

    if (m.msg_type === "error") {
      activityItems.push({ id: m.id, kind: "error", content: m.content });
      continue;
    }
  }

  const showActivityPanel = agentStatus !== "idle" || activityItems.length > 0;

  return (
    <div className="h-full overflow-auto">
      <div className="mx-auto max-w-[1400px] px-8 py-8">
        {/* Top bar — minimal */}
        <div className="mb-6 flex items-center justify-between">
          <Button
            variant="ghost"
            size="sm"
            className="-ml-2 h-8 gap-1 px-2 text-muted-foreground hover:text-foreground"
            onClick={() => router.push("/dashboard/documents")}
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            文档列表
          </Button>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-muted-foreground hover:text-foreground"
                aria-label="更多操作"
              >
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-32">
              <DropdownMenuItem
                onClick={() => setShowDeleteDialog(true)}
                className="text-red-600 focus:text-red-600 dark:text-red-400 dark:focus:text-red-400"
              >
                <Trash2 className="mr-2 h-3.5 w-3.5" />
                删除文档
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        {/* Two-column layout: preview left, action panel right */}
        <div className="grid gap-8 lg:grid-cols-[1fr_320px]">
          {/* LEFT: document preview */}
          <div className="space-y-6">
            <div className="overflow-hidden rounded-md border border-border/60 bg-background">
              {document.file_type === "pdf" && previewUrl ? (
                <iframe
                  title={`document-preview-${document.id}`}
                  src={`${previewUrl}#toolbar=0&navpanes=0&scrollbar=0&view=FitH`}
                  className="h-[760px] w-full"
                />
              ) : previewUrl ? (
                <div className="space-y-3 p-6 text-sm">
                  <div className="text-muted-foreground">当前文件类型暂无内嵌预览</div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => window.open(previewUrl, "_blank", "noopener,noreferrer")}
                  >
                    打开原始文件
                  </Button>
                </div>
              ) : (
                <div className="p-6 text-sm text-muted-foreground">暂无原始文件预览</div>
              )}
            </div>

            {/* Universal blocks — show the FULL faithful extraction.
                Visible by default (not collapsed). This is the source of
                truth for "what did the system actually extract from this PDF". */}
            {extractionBlocks.length > 0 ? (
              <BlocksViewer
                blocks={extractionBlocks}
                title={extractionTitle}
                language={extractionLanguage}
                pageCount={extractionPageCount}
              />
            ) : document.content_markdown ? (
              // Backward compat: legacy documents that don't have blocks fall
              // back to the old markdown rendering, collapsed by default.
              <Collapsible open={extractedOpen} onOpenChange={setExtractedOpen}>
                <CollapsibleTrigger asChild>
                  <button
                    type="button"
                    className="flex w-full items-center justify-between rounded-md border border-border/60 px-4 py-3 text-sm font-medium hover:bg-muted/40"
                  >
                    <span>系统提取的结构化内容（旧版）</span>
                    {extractedOpen ? (
                      <ChevronDown className="h-4 w-4 text-muted-foreground" />
                    ) : (
                      <ChevronRight className="h-4 w-4 text-muted-foreground" />
                    )}
                  </button>
                </CollapsibleTrigger>
                <CollapsibleContent className="mt-3 rounded-md border border-border/60 p-5">
                  <MarkdownContent content={document.content_markdown} />
                </CollapsibleContent>
              </Collapsible>
            ) : null}
          </div>

          {/* RIGHT: action panel — flat, no nested cards */}
          <aside className="space-y-6">
            {/* Title block */}
            <div>
              <h1 className="break-all text-base font-semibold leading-snug">{document.filename}</h1>
              <div className="mt-2 flex items-center gap-3">
                <StatusDot status={document.status} />
                <span className="text-xs text-muted-foreground">
                  {formatTime(document.created_at)}
                </span>
              </div>
            </div>

            {/* Metadata description list */}
            {metadataPairs.length > 0 ? (
              <div className="space-y-2 border-t border-border/60 pt-5">
                <dl className="space-y-2.5 text-sm">
                  {metadataPairs.map(([key, value]) => (
                    <div key={key} className="flex items-baseline justify-between gap-4">
                      <dt className="text-xs text-muted-foreground">
                        {META_LABELS[key] || key}
                      </dt>
                      <dd className="text-right font-medium tabular-nums">
                        {formatMetaValue(key, value)}
                      </dd>
                    </div>
                  ))}
                  {productCount > 0 ? (
                    <div className="flex items-baseline justify-between gap-4">
                      <dt className="text-xs text-muted-foreground">产品数</dt>
                      <dd className="text-right font-medium tabular-nums">{productCount}</dd>
                    </div>
                  ) : null}
                </dl>
              </div>
            ) : null}

            {/* Agent activity panel — visible when agent is running OR has run */}
            {showActivityPanel ? (
              <div className="space-y-3 border-t border-border/60 pt-5">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-xs">
                    {agentStatus === "running" || agentStatus === "stopping" ? (
                      <Loader2 className="h-3 w-3 animate-spin text-foreground/70" />
                    ) : agentStatus === "error" ? (
                      <X className="h-3 w-3 text-red-500" />
                    ) : (
                      <Check className="h-3 w-3 text-emerald-600" />
                    )}
                    <span className="font-medium">
                      {agentStatus === "running"
                        ? "Agent 处理中"
                        : agentStatus === "stopping"
                          ? "正在停止 Agent"
                        : agentStatus === "error"
                          ? "处理失败"
                          : "处理完成"}
                    </span>
                    <span className="text-muted-foreground">
                      · {(agentStatus === "running" || agentStatus === "stopping")
                        ? agentElapsed
                        : Math.floor((Date.now() - (agentStartedAt || Date.now())) / 1000)}s
                    </span>
                  </div>
                  {agentBusy ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="destructive"
                      onClick={() => cancelAgentRun().catch(() => {})}
                      disabled={agentStatus === "stopping"}
                      className="h-8 px-3"
                    >
                      {agentStatus === "stopping" ? "正在停止…" : "停止 Agent"}
                    </Button>
                  ) : null}
                </div>

                {agentBusy ? (
                  <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs leading-5 text-red-700">
                    {agentStatus === "stopping"
                      ? "已向后端发送停止信号，当前任务会在安全点尽快终止。"
                      : "Agent 正在运行，会继续消耗后端模型调用；如需立即终止，请点“停止 Agent”。"}
                  </div>
                ) : null}

                <div
                  ref={activityScrollRef}
                  className="max-h-[420px] space-y-1.5 overflow-y-auto rounded-md border border-border/60 bg-muted/20 p-3"
                >
                  {activityItems.length === 0 ? (
                    <div className="py-2 text-xs text-muted-foreground">等待 Agent 启动…</div>
                  ) : (
                    activityItems.map((item) => {
                      if (item.kind === "tool_done") {
                        return (
                          <div key={item.id} className="flex items-center gap-2 text-xs leading-5">
                            <Check className="h-3 w-3 shrink-0 text-emerald-600" />
                            <code className="font-mono text-[11px] text-foreground/90">{item.toolName}</code>
                            <span className="text-muted-foreground">
                              · {(item.durationMs / 1000).toFixed(1)}s
                            </span>
                          </div>
                        );
                      }
                      if (item.kind === "tool_running") {
                        return (
                          <div key={item.id} className="flex items-center gap-2 text-xs leading-5">
                            <Loader2 className="h-3 w-3 shrink-0 animate-spin text-muted-foreground" />
                            <code className="font-mono text-[11px] text-foreground/90">{item.toolName}</code>
                            <span className="text-muted-foreground">· running</span>
                          </div>
                        );
                      }
                      if (item.kind === "tool_error") {
                        return (
                          <div key={item.id} className="space-y-0.5 text-xs leading-5">
                            <div className="flex items-center gap-2">
                              <X className="h-3 w-3 shrink-0 text-red-500" />
                              <code className="font-mono text-[11px] text-foreground/90">{item.toolName}</code>
                              <span className="text-muted-foreground">
                                · {(item.durationMs / 1000).toFixed(1)}s
                              </span>
                            </div>
                            <div className="ml-5 text-red-600 dark:text-red-400">
                              {item.errorMsg.slice(0, 200)}
                            </div>
                          </div>
                        );
                      }
                      if (item.kind === "thinking") {
                        return (
                          <details key={item.id} className="group text-xs leading-5">
                            <summary className="flex cursor-pointer items-center gap-1.5 text-muted-foreground hover:text-foreground">
                              <ChevronRight className="h-3 w-3 transition-transform group-open:rotate-90" />
                              <span className="text-foreground/60">思考</span>
                              <span className="truncate">· {item.summary}</span>
                            </summary>
                            <pre className="ml-4 mt-1.5 whitespace-pre-wrap font-sans text-xs leading-5 text-muted-foreground">
                              {item.full}
                            </pre>
                          </details>
                        );
                      }
                      if (item.kind === "answer") {
                        return (
                          <div
                            key={item.id}
                            className="mt-2 rounded-md border border-border/60 bg-background px-3 py-2 text-xs leading-5"
                          >
                            <MarkdownContent content={item.content} />
                          </div>
                        );
                      }
                      if (item.kind === "error") {
                        return (
                          <div key={item.id} className="flex items-start gap-2 text-xs leading-5">
                            <X className="h-3 w-3 mt-0.5 shrink-0 text-red-500" />
                            <span className="text-red-600 dark:text-red-400">{item.content}</span>
                          </div>
                        );
                      }
                      return null;
                    })
                  )}
                </div>

                {agentError ? (
                  <p className="text-xs text-red-600 dark:text-red-400">{agentError}</p>
                ) : null}
              </div>
            ) : null}

            {/* Primary action + state label + hint + optional type override
                (hidden while agent is running so the activity panel takes
                full attention) */}
            {!agentBusy && (primaryAction || nextStepHint || stateLabel) ? (
              <div className="space-y-3 border-t border-border/60 pt-5">
                {stateLabel ? (
                  <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                    {stateLabel}
                  </div>
                ) : null}
                {primaryAction}
                {nextStepHint ? (
                  <p className="text-xs leading-5 text-muted-foreground">{nextStepHint}</p>
                ) : null}
                {showTypeOverride && !document.linked_order_id ? (
                  <div className="pt-1 text-xs text-muted-foreground">
                    手动指定类型：
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <button
                          type="button"
                          className="ml-1 inline-flex items-center gap-1 font-medium text-foreground/80 underline decoration-dotted underline-offset-2 hover:text-foreground"
                          disabled={updatingType}
                        >
                          {document.doc_type === "purchase_order"
                            ? "采购订单"
                            : document.doc_type === "unknown"
                              ? "未识别"
                              : document.doc_type || "—"}
                          <ChevronDown className="h-3 w-3" />
                        </button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="start" className="w-40">
                        <DropdownMenuItem
                          onClick={() => handleChangeDocType("purchase_order")}
                          disabled={document.doc_type === "purchase_order" || updatingType}
                        >
                          采购订单
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onClick={() => handleChangeDocType("unknown")}
                          disabled={document.doc_type === "unknown" || updatingType}
                        >
                          未识别 / 其他
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                ) : null}
              </div>
            ) : null}

            {/* Inline correction chat — available after extraction but before
                the document is turned into a stable downstream order flow. */}
            {!isProcessing && !isError && !document.linked_order_id ? (
              <div className="space-y-3 border-t border-border/60 pt-5">
                <div className="space-y-1">
                  <div className="text-sm font-medium">补充或修正文档信息</div>
                  <p className="text-xs leading-5 text-muted-foreground">
                    可以直接告诉 Agent 你要补什么，例如“currency 改成 AUD”、“location 是 Sydney”或“交货日期改成 2026-04-15”。
                  </p>
                </div>
                <Textarea
                  value={agentInput}
                  onChange={(e) => setAgentInput(e.target.value)}
                  placeholder="输入你想补充或修改的文档信息..."
                  className="min-h-[96px] resize-y"
                  disabled={agentBusy}
                  onKeyDown={(e) => {
                    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                      e.preventDefault();
                      handleAgentSubmit().catch(() => {});
                    }
                  }}
                />
                <div className="flex items-center justify-between gap-3">
                  <span className="text-[11px] text-muted-foreground">
                    {agentBusy ? "先停止当前 Agent，再继续发送新指令" : "Cmd/Ctrl + Enter 发送"}
                  </span>
                  <div className="flex items-center gap-2">
                    {isPurchaseOrder && payload?.ready_for_order_creation && !agentBusy ? (
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-8"
                        onClick={() => runAgentInline().catch(() => {})}
                      >
                        继续处理为订单
                      </Button>
                    ) : null}
                    {agentBusy ? (
                      <Button
                        size="sm"
                        variant="destructive"
                        className="h-8"
                        onClick={() => cancelAgentRun().catch(() => {})}
                        disabled={agentStatus === "stopping"}
                      >
                        {agentStatus === "stopping" ? "正在停止…" : "停止 Agent"}
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        className="h-8"
                        disabled={!agentInput.trim()}
                        onClick={() => handleAgentSubmit().catch(() => {})}
                      >
                        发送给 Agent
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            ) : null}

            {/* Document type / id — small footer info */}
            <div className="space-y-1.5 border-t border-border/60 pt-5 text-xs text-muted-foreground">
              <div className="flex justify-between">
                <span>文档 ID</span>
                <span className="font-medium text-foreground/80">{document.id}</span>
              </div>
              <div className="flex justify-between">
                <span>类型</span>
                <span className="font-medium text-foreground/80">
                  {document.doc_type === "purchase_order"
                    ? "采购订单"
                    : document.doc_type === "unknown"
                      ? "未识别"
                      : document.doc_type || "—"}
                </span>
              </div>
              <div className="flex justify-between">
                <span>文件类型</span>
                <span className="font-medium uppercase text-foreground/80">
                  {document.file_type}
                </span>
              </div>
            </div>
          </aside>
        </div>
      </div>

      <AlertDialog
        open={showDeleteDialog}
        onOpenChange={(open) => {
          if (!open && !deleting) setShowDeleteDialog(false);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除文档</AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-2 text-sm leading-6">
                <div>
                  确认要删除 <span className="font-medium text-foreground">{document.filename}</span> 吗？此操作不可撤销。
                </div>
                {document.linked_order_id ? (
                  <div className="text-muted-foreground">
                    该文档已生成订单 #{document.linked_order_id}。删除后订单会保留，但与此源文档解除关联。
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
                handleDelete();
              }}
              disabled={deleting}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleting ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : null}
              {document.linked_order_id ? "强制删除" : "删除"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
