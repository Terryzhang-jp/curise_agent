"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  AlertTriangle,
  ArrowUpDown,
  TrendingUp,
  TrendingDown,
  Download,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { exportToCSV } from "@/lib/export-csv";
import type { FinancialData, FinancialBreakdown } from "@/lib/orders-api";

interface FinancialPreviewProps {
  data: FinancialData;
}

type SortKey = "product_name" | "quantity" | "order_price" | "supplier_price" | "profit" | "margin";
type SortDir = "asc" | "desc";

function fmtNum(n: number, decimals = 2): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function marginColor(margin: number): string {
  if (margin > 10) return "text-emerald-500";
  if (margin >= 0) return "text-amber-500";
  return "text-destructive";
}

function profitColor(profit: number): string {
  return profit >= 0 ? "text-emerald-500" : "text-destructive";
}

export default function FinancialPreview({ data }: FinancialPreviewProps) {
  const { summary, product_analyses, supplier_breakdown, category_breakdown, warnings } = data;

  const [sortKey, setSortKey] = useState<SortKey>("margin");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  const sortedProducts = [...product_analyses].sort((a, b) => {
    const av = a[sortKey] ?? 0;
    const bv = b[sortKey] ?? 0;
    if (typeof av === "string" && typeof bv === "string") {
      return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
    }
    return sortDir === "asc" ? (av as number) - (bv as number) : (bv as number) - (av as number);
  });

  const warningsByType = {
    currency_mismatch: warnings.filter((w) => w.type === "currency_mismatch"),
    negative_margin: warnings.filter((w) => w.type === "negative_margin"),
    missing_price: warnings.filter((w) => w.type === "missing_price"),
  };

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="shrink-0 px-4 py-3 border-b border-border/50 flex items-center justify-between">
        <div>
          <div className="text-sm font-semibold">财务分析详情</div>
          <div className="text-[10px] text-muted-foreground mt-0.5">
            {summary.currency && `币种: ${summary.currency} · `}
            分析了 {summary.analyzed_count}/{summary.total_products} 个产品
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="h-8 text-xs"
          onClick={() => {
            exportToCSV(
              ["产品名称", "产品代码", "数量", "卖价", "成本", "利润", "利润率"],
              sortedProducts.map((p) => [
                p.product_name,
                p.product_code || "",
                p.quantity,
                fmtNum(p.order_price),
                fmtNum(p.supplier_price),
                fmtNum(p.profit),
                `${p.margin}%`,
              ]),
              `财务分析_${new Date().toISOString().slice(0, 10)}.csv`
            );
          }}
        >
          <Download className="mr-1 h-3 w-3" /> 导出 CSV
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
        {/* Summary cards */}
        <div className="grid grid-cols-4 gap-3">
          <SummaryCard
            label="总收入"
            value={fmtNum(summary.total_revenue)}
            currency={summary.currency}
          />
          <SummaryCard
            label="总成本"
            value={fmtNum(summary.total_cost)}
            currency={summary.currency}
          />
          <SummaryCard
            label="总利润"
            value={fmtNum(summary.total_profit)}
            currency={summary.currency}
            className={profitColor(summary.total_profit)}
            icon={summary.total_profit >= 0 ? TrendingUp : TrendingDown}
          />
          <SummaryCard
            label="利润率"
            value={`${summary.overall_margin}%`}
            className={marginColor(summary.overall_margin)}
          />
        </div>

        {/* Coverage info */}
        <div className="text-xs text-muted-foreground px-1">
          分析覆盖: {summary.analyzed_count}/{summary.total_products} 个产品
          {(summary.skipped_unmatched > 0 || summary.skipped_currency_mismatch > 0 || summary.skipped_missing_price > 0) && (
            <span>
              {" ("}
              {[
                summary.skipped_unmatched > 0 && `${summary.skipped_unmatched} 未匹配跳过`,
                summary.skipped_currency_mismatch > 0 && `${summary.skipped_currency_mismatch} 币种不匹配`,
                summary.skipped_missing_price > 0 && `${summary.skipped_missing_price} 缺少价格`,
              ].filter(Boolean).join("、")}
              {")"}
            </span>
          )}
        </div>

        {/* Warnings */}
        {warnings.length > 0 && (
          <Card className="bg-amber-500/5 border-amber-500/15">
            <CardHeader className="pb-0">
              <CardTitle className="flex items-center gap-2">
                <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />
                <span className="text-xs font-medium text-amber-500">
                  警告 ({warnings.length})
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-3">
              <div className="space-y-2">
                {Object.entries(warningsByType).map(([type, items]) => {
                  if (items.length === 0) return null;
                  const label =
                    type === "currency_mismatch" ? "币种不匹配" :
                    type === "negative_margin" ? "负利润" : "缺少价格";
                  return (
                    <div key={type}>
                      <div className="text-[10px] font-medium text-amber-600 dark:text-amber-400 mb-1">
                        {label} ({items.length})
                      </div>
                      {items.map((w, i) => (
                        <div key={i} className="text-[10px] text-muted-foreground py-0.5 pl-2 border-l-2 border-amber-500/30">
                          {w.description}
                        </div>
                      ))}
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Product profit table */}
        {product_analyses.length > 0 && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-xs font-medium">产品利润明细</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-border/50">
                      {[
                        { key: "product_name" as SortKey, label: "产品" },
                        { key: "quantity" as SortKey, label: "数量" },
                        { key: "order_price" as SortKey, label: "卖价" },
                        { key: "supplier_price" as SortKey, label: "成本" },
                        { key: "profit" as SortKey, label: "利润" },
                        { key: "margin" as SortKey, label: "利润率" },
                      ].map((col) => (
                        <th
                          key={col.key}
                          className="px-3 py-2 text-left font-medium text-muted-foreground cursor-pointer hover:text-foreground select-none"
                          onClick={() => toggleSort(col.key)}
                        >
                          <span className="inline-flex items-center gap-1">
                            {col.label}
                            {sortKey === col.key && (
                              <ArrowUpDown className="h-2.5 w-2.5" />
                            )}
                          </span>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {sortedProducts.map((p, i) => (
                      <tr key={i} className="border-b border-border/30 hover:bg-muted/30">
                        <td className="px-3 py-2">
                          <div className="font-medium truncate max-w-[200px]" title={p.product_name}>
                            {p.product_name}
                          </div>
                          {p.product_code && (
                            <div className="text-[10px] text-muted-foreground">{p.product_code}</div>
                          )}
                        </td>
                        <td className="px-3 py-2 text-right">{p.quantity}</td>
                        <td className="px-3 py-2 text-right">{fmtNum(p.order_price)}</td>
                        <td className="px-3 py-2 text-right">{fmtNum(p.supplier_price)}</td>
                        <td className={cn("px-3 py-2 text-right font-medium", profitColor(p.profit))}>
                          {fmtNum(p.profit)}
                        </td>
                        <td className={cn("px-3 py-2 text-right font-medium", marginColor(p.margin))}>
                          {p.margin}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Supplier breakdown */}
        {supplier_breakdown.length > 0 && (
          <BreakdownTable
            title="按供应商汇总"
            items={supplier_breakdown}
            nameKey="supplier_name"
            nameLabel="供应商"
          />
        )}

        {/* Category breakdown */}
        {category_breakdown.length > 0 && (
          <BreakdownTable
            title="按品类汇总"
            items={category_breakdown}
            nameKey="category_name"
            nameLabel="品类"
          />
        )}
      </div>
    </div>
  );
}

// ─── Summary Card ───────────────────────────────────────────

function SummaryCard({
  label,
  value,
  currency,
  className,
  icon: Icon,
}: {
  label: string;
  value: string;
  currency?: string;
  className?: string;
  icon?: React.ComponentType<{ className?: string }>;
}) {
  return (
    <Card>
      <CardContent className="pt-4 pb-3 text-center">
        <div className={cn("text-lg font-semibold flex items-center justify-center gap-1", className)}>
          {Icon && <Icon className="h-4 w-4" />}
          {value}
        </div>
        <div className="text-[10px] text-muted-foreground mt-0.5">
          {label}
          {currency && ` (${currency})`}
        </div>
      </CardContent>
    </Card>
  );
}

// ─── Breakdown Table ────────────────────────────────────────

function BreakdownTable({
  title,
  items,
  nameKey,
  nameLabel,
}: {
  title: string;
  items: FinancialBreakdown[];
  nameKey: "supplier_name" | "category_name";
  nameLabel: string;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-xs font-medium">{title}</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border/50">
                <th className="px-3 py-2 text-left font-medium text-muted-foreground">{nameLabel}</th>
                <th className="px-3 py-2 text-right font-medium text-muted-foreground">产品数</th>
                <th className="px-3 py-2 text-right font-medium text-muted-foreground">收入</th>
                <th className="px-3 py-2 text-right font-medium text-muted-foreground">成本</th>
                <th className="px-3 py-2 text-right font-medium text-muted-foreground">利润</th>
                <th className="px-3 py-2 text-right font-medium text-muted-foreground">利润率</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item, i) => (
                <tr key={i} className="border-b border-border/30 hover:bg-muted/30">
                  <td className="px-3 py-2">{item[nameKey] || "-"}</td>
                  <td className="px-3 py-2 text-right">{item.product_count}</td>
                  <td className="px-3 py-2 text-right">{fmtNum(item.revenue)}</td>
                  <td className="px-3 py-2 text-right">{fmtNum(item.cost)}</td>
                  <td className={cn("px-3 py-2 text-right font-medium", profitColor(item.profit))}>
                    {fmtNum(item.profit)}
                  </td>
                  <td className={cn("px-3 py-2 text-right font-medium", marginColor(item.margin))}>
                    {item.margin}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
