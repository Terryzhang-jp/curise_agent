"use client";

import { useState, useMemo } from "react";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Search } from "lucide-react";

interface OrderDataPreviewProps {
  data: Record<string, unknown>;
}

const META_FIELDS: { key: string; label: string }[] = [
  { key: "po_number", label: "PO 编号" },
  { key: "ship_name", label: "船名" },
  { key: "vendor_name", label: "供应商" },
  { key: "delivery_date", label: "交货日期" },
  { key: "currency", label: "币种" },
  { key: "destination_port", label: "目的港" },
];

export default function OrderDataPreview({ data }: OrderDataPreviewProps) {
  const metadata = (data.order_metadata || {}) as Record<string, string>;
  const products = (data.products || []) as Array<Record<string, unknown>>;

  const [search, setSearch] = useState("");

  const filteredProducts = useMemo(() => {
    if (!search.trim()) return products;
    const q = search.toLowerCase();
    return products.filter(
      (p) =>
        String(p.product_name || "").toLowerCase().includes(q) ||
        String(p.product_code || "").toLowerCase().includes(q)
    );
  }, [products, search]);

  const visibleMeta = META_FIELDS.filter((f) => metadata[f.key]);

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="shrink-0 px-4 py-3 border-b border-border/50">
        <div className="text-sm font-semibold">订单数据详情</div>
        <div className="text-[10px] text-muted-foreground mt-0.5">Phase 2: ORDER_DIGITIZATION</div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
        {/* Order metadata */}
        {visibleMeta.length > 0 && (
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                订单信息
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs">
                {visibleMeta.map((f) => (
                  <div key={f.key} className="flex justify-between">
                    <span className="text-muted-foreground">{f.label}</span>
                    <span className="font-medium">{metadata[f.key]}</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Products table */}
        <Card>
          <CardHeader className="pb-0">
            <div className="flex items-center justify-between">
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                产品列表 ({products.length} 项)
              </CardTitle>
              <div className="relative max-w-xs">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                <Input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="搜索产品..."
                  className="pl-9 h-8 text-xs w-40"
                />
              </div>
            </div>
          </CardHeader>
          <CardContent className="pt-3">
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="w-8 text-[10px]">#</TableHead>
                    <TableHead className="text-[10px]">产品名称</TableHead>
                    <TableHead className="text-[10px]">产品代码</TableHead>
                    <TableHead className="text-[10px] text-right">数量</TableHead>
                    <TableHead className="text-[10px]">单位</TableHead>
                    <TableHead className="text-[10px] text-right">单价</TableHead>
                    <TableHead className="text-[10px] text-right">总价</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredProducts.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={7} className="text-center py-8 text-muted-foreground text-xs">
                        {search ? "无匹配结果" : "暂无产品数据"}
                      </TableCell>
                    </TableRow>
                  ) : (
                    filteredProducts.map((p, i) => (
                      <TableRow key={i}>
                        <TableCell className="text-[10px] text-muted-foreground">{i + 1}</TableCell>
                        <TableCell className="text-xs">{String(p.product_name || "-")}</TableCell>
                        <TableCell className="text-xs text-muted-foreground font-mono">
                          {String(p.product_code || p.item_code || "-")}
                        </TableCell>
                        <TableCell className="text-xs text-right">{String(p.quantity || "-")}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">{String(p.unit || "-")}</TableCell>
                        <TableCell className="text-xs text-right">
                          {p.unit_price != null ? String(p.unit_price) : "-"}
                        </TableCell>
                        <TableCell className="text-xs text-right">
                          {p.total_price != null ? String(p.total_price) : "-"}
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
