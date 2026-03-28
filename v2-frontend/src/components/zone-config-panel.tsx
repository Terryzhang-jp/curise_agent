"use client";

import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

// ── Types ──────────────────────────────────────────────────────

interface ZoneConfig {
  zones?: {
    product_data?: { start: number; end: number };
    summary?: { start: number; end: number };
  };
  header_fields?: Record<string, string>;
  product_columns?: Record<string, string>;
  product_row_formulas?: Record<string, string>;
  summary_formulas?: Array<{
    cell: string;
    type: string;
    col?: string;
    label?: string;
    formula_template?: string;
  }>;
  summary_static_values?: Record<string, string>;
  external_refs?: Array<{ cell: string; formula_template: string }>;
  stale_columns_in_summary?: string[];
}

interface ZoneConfigPanelProps {
  config: ZoneConfig;
  templateName: string;
  trigger: React.ReactNode;
}

// ── Field label map ────────────────────────────────────────────

const FIELD_LABELS: Record<string, string> = {
  ship_name: "船名",
  ship_name_alt: "船名 (副)",
  po_number: "PO番号",
  order_date: "下单日",
  delivery_date: "交货日",
  delivery_address: "交货地址",
  delivery_contact: "联系人",
  delivery_time_notes: "配送备注",
  destination: "目的地",
  destination_port: "目的港",
  voyage: "航次",
  invoice_number: "发票号",
  currency: "币种",
  payment_date: "付款日",
  payment_method: "付款方式",
  supplier_name: "供应商名",
  supplier_contact: "联系人",
  supplier_tel: "电话",
  supplier_fax: "传真",
  supplier_email: "邮箱",
  supplier_address: "地址",
  supplier_zip_code: "邮编",
  supplier_bank: "银行",
  supplier_account: "账号",
  line_number: "行号",
  product_code: "商品代码",
  product_name_en: "英文品名",
  product_name_jp: "日文品名",
  description: "规格/包装",
  quantity: "数量",
  unit: "单位",
  unit_price: "单价",
  item_amount: "金额",
  total_price: "金额",
  amount: "金额",
  default_payment_terms: "付款条件",
  default_payment_method: "付款方式",
};

function fieldLabel(key: string): string {
  return FIELD_LABELS[key] || key;
}

// ── Sub-components ─────────────────────────────────────────────

function Section({ title, children, count }: { title: string; children: React.ReactNode; count?: number }) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-2.5">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{title}</h4>
        {count !== undefined && (
          <span className="text-[10px] tabular-nums text-muted-foreground/70">{count}</span>
        )}
      </div>
      {children}
    </div>
  );
}

/** Visual zone map */
function ZoneMap({ zones }: { zones: NonNullable<ZoneConfig["zones"]> }) {
  const prod = zones.product_data;
  const summ = zones.summary;
  if (!prod || !summ) return null;

  const prodRows = prod.end - prod.start + 1;
  const summRows = summ.end - summ.start + 1;
  const headerRows = prod.start - 1;
  const totalRows = summ.end;

  const totalH = 120;
  const headerH = Math.max(16, (headerRows / totalRows) * totalH);
  const prodH = Math.max(24, (prodRows / totalRows) * totalH);
  const summH = Math.max(16, (summRows / totalRows) * totalH);

  return (
    <div className="flex gap-4 items-start">
      <div className="w-16 rounded-lg overflow-hidden border border-border shrink-0">
        <div
          style={{ height: headerH, background: "oklch(0.3 0.01 260)" }}
          className="flex items-center justify-center border-b border-border/50"
        >
          <span style={{ color: "oklch(0.55 0.02 260)" }} className="text-[8px] font-medium tracking-wider">HEADER</span>
        </div>
        <div
          style={{ height: prodH, background: "oklch(0.32 0.08 240)", borderTop: "2px solid oklch(0.55 0.15 240)", borderBottom: "2px solid oklch(0.55 0.15 240)" }}
          className="flex items-center justify-center"
        >
          <span style={{ color: "oklch(0.85 0.1 240)" }} className="text-[9px] font-bold tracking-wide">DATA</span>
        </div>
        <div
          style={{ height: summH, background: "oklch(0.32 0.08 70)" }}
          className="flex items-center justify-center"
        >
          <span style={{ color: "oklch(0.85 0.12 70)" }} className="text-[9px] font-bold tracking-wide">SUM</span>
        </div>
      </div>

      <div className="text-xs space-y-2 pt-0.5">
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground">Header 区域</span>
          <span className="font-mono text-muted-foreground/60">Row 1 — {prod.start - 1}</span>
        </div>
        <div className="flex items-center gap-2">
          <span style={{ background: "oklch(0.65 0.18 240)" }} className="w-2 h-2 rounded-full shrink-0" />
          <span className="text-foreground font-medium">产品区域</span>
          <span className="font-mono text-muted-foreground/60">Row {prod.start} — {prod.end}</span>
          <Badge variant="secondary" className="text-[10px] h-4 px-1.5 font-mono">{prodRows} 行</Badge>
        </div>
        <div className="flex items-center gap-2">
          <span style={{ background: "oklch(0.72 0.12 70)" }} className="w-2 h-2 rounded-full shrink-0" />
          <span className="text-foreground font-medium">汇总区域</span>
          <span className="font-mono text-muted-foreground/60">Row {summ.start} — {summ.end}</span>
          <Badge variant="secondary" className="text-[10px] h-4 px-1.5 font-mono">{summRows} 行</Badge>
        </div>
      </div>
    </div>
  );
}

/** Product column mapping grid */
function ColumnGrid({ columns, formulas }: {
  columns: Record<string, string>;
  formulas: Record<string, string>;
}) {
  const allCols = new Map<string, { field: string; formula?: string }>();
  for (const [col, field] of Object.entries(columns)) {
    allCols.set(col, { field });
  }
  for (const [col, formula] of Object.entries(formulas)) {
    const existing = allCols.get(col);
    if (existing) {
      existing.formula = formula;
    } else {
      allCols.set(col, { field: "__formula__", formula });
    }
  }

  const sorted = [...allCols.entries()].sort((a, b) => a[0].localeCompare(b[0]));

  return (
    <TooltipProvider>
      <div className="grid grid-cols-6 gap-1.5">
        {sorted.map(([col, info]) => (
          <Tooltip key={col}>
            <TooltipTrigger asChild>
              <div
                className="rounded-lg border px-2 py-2 text-center cursor-default transition-all hover:scale-[1.03]"
                style={info.formula ? {
                  borderColor: "oklch(0.55 0.15 285 / 0.5)",
                  background: "oklch(0.28 0.07 285)",
                } : {
                  borderColor: "oklch(0.38 0.02 260)",
                  background: "oklch(0.26 0.015 260)",
                }}
              >
                <div
                  className="text-[11px] font-mono font-bold"
                  style={{ color: info.formula ? "oklch(0.82 0.12 285)" : "oklch(0.7 0.02 260)" }}
                >
                  {col}
                </div>
                <div
                  className="text-[10px] mt-0.5 truncate"
                  style={{ color: info.formula ? "oklch(0.72 0.1 285)" : "oklch(0.85 0.02 60)" }}
                >
                  {info.formula ? "fx" : fieldLabel(info.field)}
                </div>
              </div>
            </TooltipTrigger>
            <TooltipContent side="bottom">
              <div className="space-y-0.5">
                <div className="font-medium">列 {col}: {fieldLabel(info.field)}</div>
                {info.formula && (
                  <div className="font-mono text-[11px] opacity-80">{info.formula}</div>
                )}
              </div>
            </TooltipContent>
          </Tooltip>
        ))}
      </div>
    </TooltipProvider>
  );
}

/** Header fields compact list */
function HeaderFieldList({ fields }: { fields: Record<string, string> }) {
  const orderFields: [string, string][] = [];
  const supplierFields: [string, string][] = [];
  const otherFields: [string, string][] = [];

  for (const [cell, path] of Object.entries(fields)) {
    if (path.startsWith("suppliers.")) {
      supplierFields.push([cell, path]);
    } else if (["ship_name", "po_number", "order_date", "delivery_date", "delivery_address",
      "delivery_contact", "delivery_time_notes", "destination", "destination_port", "voyage",
      "invoice_number", "currency", "payment_date", "payment_method"].some(k => path.includes(k))) {
      orderFields.push([cell, path]);
    } else {
      otherFields.push([cell, path]);
    }
  }

  const renderGroup = (label: string, items: [string, string][], hue: number) => {
    if (items.length === 0) return null;
    return (
      <div>
        <div className="flex items-center gap-1.5 mb-1.5">
          <span style={{ background: `oklch(0.7 0.15 ${hue})` }} className="w-1.5 h-1.5 rounded-full" />
          <span className="text-[10px] text-muted-foreground uppercase tracking-wider font-medium">{label}</span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {items.map(([cell, path]) => {
            const key = path.split(".").pop() || path;
            return (
              <span
                key={cell}
                className="inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px]"
                style={{ borderColor: "oklch(0.4 0.02 260)", background: "oklch(0.24 0.015 260)" }}
              >
                <span className="font-mono" style={{ color: `oklch(0.65 0.1 ${hue})` }}>{cell}</span>
                <span style={{ color: "oklch(0.82 0.02 60)" }}>{fieldLabel(key)}</span>
              </span>
            );
          })}
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-3">
      {renderGroup("订单信息", orderFields, 25)}
      {renderGroup("供应商信息", supplierFields, 55)}
      {renderGroup("其他", otherFields, 260)}
    </div>
  );
}

/** Summary formula chain */
function FormulaChain({ formulas, staticValues }: {
  formulas: NonNullable<ZoneConfig["summary_formulas"]>;
  staticValues: Record<string, string>;
}) {
  if (formulas.length === 0) return <span className="text-xs text-muted-foreground">无汇总公式</span>;

  const stepColors: { bg: string; fg: string }[] = formulas.map((_, i) => {
    if (i === 0) return { bg: "oklch(0.35 0.08 70)", fg: "oklch(0.85 0.12 70)" };
    if (i === formulas.length - 1) return { bg: "oklch(0.33 0.08 155)", fg: "oklch(0.82 0.12 155)" };
    return { bg: "oklch(0.3 0.02 260)", fg: "oklch(0.7 0.02 260)" };
  });

  return (
    <div className="space-y-2">
      {formulas.map((sf, i) => {
        const label = sf.label || (sf.type === "product_sum" ? "小计" : `公式 ${i + 1}`);
        const formula = sf.type === "product_sum"
          ? `SUM(${sf.col}:${sf.col})`
          : sf.formula_template || "";

        return (
          <div key={i} className="flex items-center gap-2.5 text-xs">
            <span
              className="w-5 h-5 rounded-md flex items-center justify-center text-[10px] font-bold shrink-0"
              style={{ background: stepColors[i].bg, color: stepColors[i].fg }}
            >
              {i + 1}
            </span>
            <span className="text-foreground font-medium min-w-[70px]">{label}</span>
            <code
              className="text-[11px] font-mono px-2 py-0.5 rounded-md"
              style={{ color: "oklch(0.82 0.12 285)", background: "oklch(0.25 0.05 285)" }}
            >
              {formula}
            </code>
          </div>
        );
      })}

      {Object.keys(staticValues).length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-2 pt-2 border-t border-border/40">
          <span className="text-[10px] text-muted-foreground/60 mr-1 self-center">固定文本:</span>
          {Object.entries(staticValues).map(([cell, val]) => (
            <Badge key={cell} variant="secondary" className="text-[10px] font-normal gap-1.5 h-5">
              <span className="font-mono text-muted-foreground">{cell}</span>
              {val}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────

export function ZoneConfigPanel({ config, templateName, trigger }: ZoneConfigPanelProps) {
  const hasZones = config.zones?.product_data && config.zones?.summary;
  const headerCount = Object.keys(config.header_fields || {}).length;
  const colCount = Object.keys(config.product_columns || {}).length +
    Object.keys(config.product_row_formulas || {}).length;
  const formulaCount = (config.summary_formulas || []).length;
  const extRefCount = (config.external_refs || []).length;

  return (
    <Dialog>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="sm:max-w-[560px] p-0 gap-0">
        <DialogHeader className="px-5 pt-5 pb-0">
          <DialogTitle className="text-base">{templateName}</DialogTitle>
          <p className="text-xs text-muted-foreground">
            引擎配置 — 确定性填充规则
          </p>
        </DialogHeader>

        <ScrollArea className="max-h-[70vh]">
          <div className="px-5 py-4 space-y-5">
            {/* Status bar */}
            <div className="flex items-center gap-3 flex-wrap">
              <span
                className="inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[11px] font-medium"
                style={hasZones ? {
                  borderColor: "oklch(0.55 0.15 155 / 0.5)",
                  background: "oklch(0.26 0.06 155)",
                  color: "oklch(0.82 0.12 155)",
                } : {
                  borderColor: "oklch(0.55 0.12 55 / 0.5)",
                  background: "oklch(0.28 0.06 55)",
                  color: "oklch(0.82 0.12 55)",
                }}
              >
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ background: hasZones ? "oklch(0.72 0.15 155)" : "oklch(0.72 0.15 55)" }}
                />
                {hasZones ? "引擎就绪" : "未配置"}
              </span>
              <span className="text-[11px] text-muted-foreground">
                {headerCount} 头部字段 · {colCount} 产品列 · {formulaCount} 汇总公式 · {extRefCount} 交叉引用
              </span>
            </div>

            {/* Zone map */}
            {hasZones && (
              <>
                <Section title="区域划分">
                  <ZoneMap zones={config.zones!} />
                </Section>
                <Separator />
              </>
            )}

            {/* Product columns */}
            {config.product_columns && Object.keys(config.product_columns).length > 0 && (
              <>
                <Section title="产品列映射" count={colCount}>
                  <ColumnGrid
                    columns={config.product_columns}
                    formulas={config.product_row_formulas || {}}
                  />
                </Section>
                <Separator />
              </>
            )}

            {/* Header fields */}
            {config.header_fields && headerCount > 0 && (
              <>
                <Section title="头部字段" count={headerCount}>
                  <HeaderFieldList fields={config.header_fields} />
                </Section>
                <Separator />
              </>
            )}

            {/* Summary formulas */}
            {config.summary_formulas && formulaCount > 0 && (
              <Section title="汇总公式链" count={formulaCount}>
                <FormulaChain
                  formulas={config.summary_formulas}
                  staticValues={config.summary_static_values || {}}
                />
              </Section>
            )}

            {/* External refs */}
            {config.external_refs && extRefCount > 0 && (
              <>
                <Separator />
                <Section title="交叉引用" count={extRefCount}>
                  <div className="space-y-1.5">
                    {config.external_refs.map((ref, i) => (
                      <div key={i} className="flex items-center gap-2 text-xs">
                        <span
                          className="inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-mono font-medium"
                          style={{ borderColor: "oklch(0.4 0.02 260)", background: "oklch(0.24 0.015 260)", color: "oklch(0.82 0.02 60)" }}
                        >
                          {ref.cell}
                        </span>
                        <span className="text-muted-foreground">=</span>
                        <code
                          className="text-[11px] font-mono px-2 py-0.5 rounded-md"
                          style={{ color: "oklch(0.82 0.12 285)", background: "oklch(0.25 0.05 285)" }}
                        >
                          {ref.formula_template}
                        </code>
                      </div>
                    ))}
                  </div>
                </Section>
              </>
            )}
          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  );
}

/** Compact status badge for list views */
export function ZoneConfigBadge({ config, templateName }: { config: ZoneConfig | null; templateName: string }) {
  if (!config || !config.zones) {
    return (
      <span
        className="inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] font-medium"
        style={{
          borderColor: "oklch(0.55 0.12 55 / 0.4)",
          background: "oklch(0.26 0.05 55)",
          color: "oklch(0.78 0.12 55)",
        }}
      >
        <span style={{ background: "oklch(0.7 0.15 55)" }} className="w-1.5 h-1.5 rounded-full" />
        LLM 模式
      </span>
    );
  }

  const colCount = Object.keys(config.product_columns || {}).length;
  const headerCount = Object.keys(config.header_fields || {}).length;

  return (
    <ZoneConfigPanel
      config={config}
      templateName={templateName}
      trigger={
        <button
          className="inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] font-medium transition-all cursor-pointer hover:scale-105"
          style={{
            borderColor: "oklch(0.55 0.15 155 / 0.45)",
            background: "oklch(0.24 0.05 155)",
            color: "oklch(0.82 0.12 155)",
          }}
        >
          <span style={{ background: "oklch(0.72 0.15 155)" }} className="w-1.5 h-1.5 rounded-full" />
          引擎就绪
          <span style={{ color: "oklch(0.6 0.1 155)" }} className="font-mono">{headerCount + colCount}</span>
        </button>
      }
    />
  );
}
