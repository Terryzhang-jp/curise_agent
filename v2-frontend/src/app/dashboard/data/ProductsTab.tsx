"use client";

import { useEffect, useState, useCallback } from "react";
import { type ColumnDef } from "@tanstack/react-table";
import { DataTable } from "@/components/data-table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { EmptyState } from "@/components/empty-state";
import { Loader2, Package, Download, Plus, MoreHorizontal } from "lucide-react";
import { exportToCSV } from "@/lib/export-csv";
import { toast } from "sonner";
import { getUser } from "@/lib/auth";
import {
  listProducts,
  listCategories,
  listSuppliers,
  listCountries,
  listPorts,
  createProduct,
  updateProduct,
  deleteProduct,
  type ProductItem,
  type CategoryItem,
  type SupplierItem,
  type CountryItem,
  type PortItem,
} from "@/lib/data-api";

function StatusBadge({ status }: { status: boolean | null }) {
  if (status === true || status === null) {
    return (
      <Badge variant="secondary" className="bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300">
        有效
      </Badge>
    );
  }
  return (
    <Badge variant="secondary" className="bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300">
      无效
    </Badge>
  );
}

interface ProductForm {
  product_name_en: string;
  product_name_jp: string;
  code: string;
  brand: string;
  country_id: string;
  category_id: string;
  supplier_id: string;
  port_id: string;
  price: string;
  currency: string;
  unit: string;
  unit_size: string;
  pack_size: string;
  country_of_origin: string;
  effective_from: string;
  effective_to: string;
}

const emptyForm: ProductForm = {
  product_name_en: "", product_name_jp: "", code: "", brand: "",
  country_id: "", category_id: "", supplier_id: "", port_id: "",
  price: "", currency: "", unit: "", unit_size: "",
  pack_size: "", country_of_origin: "", effective_from: "", effective_to: "",
};

const PAGE_SIZE = 20;

export default function ProductsTab() {
  const [products, setProducts] = useState<ProductItem[]>([]);
  const [totalProducts, setTotalProducts] = useState(0);
  const [categories, setCategories] = useState<CategoryItem[]>([]);
  const [suppliers, setSuppliers] = useState<SupplierItem[]>([]);
  const [countries, setCountries] = useState<CountryItem[]>([]);
  const [ports, setPorts] = useState<PortItem[]>([]);
  const [loading, setLoading] = useState(true);

  const [filterCategory, setFilterCategory] = useState("all");
  const [filterSupplier, setFilterSupplier] = useState("all");
  const [filterCountry, setFilterCountry] = useState("all");
  const [currentPage, setCurrentPage] = useState(0);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<ProductItem | null>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<ProductForm>(emptyForm);

  const isWriter = (() => {
    const user = getUser();
    return user?.role === "superadmin" || user?.role === "admin";
  })();

  // Build filter params for server-side query
  const getFilterParams = useCallback((page: number) => {
    const params: Parameters<typeof listProducts>[0] = {
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    };
    // Map filter name back to id for server-side filtering
    if (filterCategory !== "all") {
      const cat = categories.find((c) => c.name === filterCategory);
      if (cat) params.category_id = cat.id;
    }
    if (filterSupplier !== "all") {
      const sup = suppliers.find((s) => s.name === filterSupplier);
      if (sup) params.supplier_id = sup.id;
    }
    if (filterCountry !== "all") {
      const cty = countries.find((c) => c.name === filterCountry);
      if (cty) params.country_id = cty.id;
    }
    return params;
  }, [filterCategory, filterSupplier, filterCountry, categories, suppliers, countries]);

  const fetchProducts = useCallback((page: number) => {
    const params = getFilterParams(page);
    listProducts(params)
      .then(({ total, items }) => {
        setProducts(items);
        setTotalProducts(total);
      })
      .catch((err) => toast.error(err.message));
  }, [getFilterParams]);

  const reload = useCallback(() => {
    fetchProducts(currentPage);
  }, [fetchProducts, currentPage]);

  // Initial load: reference data + first page of products
  useEffect(() => {
    Promise.all([listProducts({ limit: PAGE_SIZE, offset: 0 }), listCategories(), listSuppliers(), listCountries(), listPorts()])
      .then(([pRes, cat, sup, cty, pts]) => {
        setProducts(pRes.items);
        setTotalProducts(pRes.total);
        setCategories(cat);
        setSuppliers(sup);
        setCountries(cty);
        setPorts(pts);
      })
      .catch((err) => toast.error(err.message))
      .finally(() => setLoading(false));
  }, []);

  // Re-fetch when filters change → reset to page 0
  useEffect(() => {
    if (!loading) {
      setCurrentPage(0);
      fetchProducts(0);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterCategory, filterSupplier, filterCountry]);

  function openCreate() {
    setEditing(null);
    setForm(emptyForm);
    setDialogOpen(true);
  }

  function openEdit(item: ProductItem) {
    setEditing(item);
    setForm({
      product_name_en: item.product_name_en || "",
      product_name_jp: item.product_name_jp || "",
      code: item.code || "",
      brand: item.brand || "",
      country_id: item.country_id ? String(item.country_id) : "",
      category_id: item.category_id ? String(item.category_id) : "",
      supplier_id: item.supplier_id ? String(item.supplier_id) : "",
      port_id: item.port_id ? String(item.port_id) : "",
      price: item.price != null ? String(item.price) : "",
      currency: item.currency || "",
      unit: item.unit || "",
      unit_size: item.unit_size || "",
      pack_size: item.pack_size || "",
      country_of_origin: item.country_of_origin || "",
      effective_from: item.effective_from?.slice(0, 10) || "",
      effective_to: item.effective_to?.slice(0, 10) || "",
    });
    setDialogOpen(true);
  }

  function updateForm(key: keyof ProductForm, value: string) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSave() {
    if (!form.product_name_en.trim()) {
      toast.error("英文品名不能为空");
      return;
    }
    setSaving(true);
    try {
      // When editing, send null for cleared FK fields so backend clears them.
      // When creating, send undefined (stripped by JSON.stringify) to use defaults.
      const cleared = editing ? null : undefined;
      const payload: Record<string, unknown> = {
        product_name_en: form.product_name_en.trim(),
        product_name_jp: form.product_name_jp.trim() || cleared,
        code: form.code.trim() || cleared,
        brand: form.brand.trim() || cleared,
        country_id: form.country_id ? Number(form.country_id) : cleared,
        category_id: form.category_id ? Number(form.category_id) : cleared,
        supplier_id: form.supplier_id ? Number(form.supplier_id) : cleared,
        port_id: form.port_id ? Number(form.port_id) : cleared,
        price: form.price ? Number(form.price) : cleared,
        currency: form.currency.trim() || cleared,
        unit: form.unit.trim() || cleared,
        unit_size: form.unit_size.trim() || cleared,
        pack_size: form.pack_size.trim() || cleared,
        country_of_origin: form.country_of_origin.trim() || cleared,
        effective_from: form.effective_from || cleared,
        effective_to: form.effective_to || cleared,
      };
      if (editing) {
        await updateProduct(editing.id, payload);
        toast.success("更新成功");
      } else {
        await createProduct(payload as unknown as Parameters<typeof createProduct>[0]);
        toast.success("创建成功");
      }
      setDialogOpen(false);
      reload();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "操作失败");
    } finally {
      setSaving(false);
    }
  }

  async function handleToggleStatus(item: ProductItem) {
    try {
      await updateProduct(item.id, { status: !item.status });
      toast.success(item.status ? "已停用" : "已启用");
      reload();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "操作失败");
    }
  }

  async function handleDelete(item: ProductItem) {
    if (!confirm(`确定要删除产品「${item.product_name_en}」吗？`)) return;
    try {
      await deleteProduct(item.id);
      toast.success("删除成功");
      reload();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "删除失败");
    }
  }

  const columns: ColumnDef<ProductItem>[] = [
    {
      accessorKey: "code",
      header: "商品代码",
      size: 100,
      cell: ({ row }) => (
        <span className="font-mono text-muted-foreground">
          {row.original.code || "-"}
        </span>
      ),
    },
    {
      accessorKey: "product_name_en",
      header: "英文品名",
      cell: ({ row }) => (
        <span className="font-medium max-w-[200px] truncate block">
          {row.original.product_name_en || "-"}
        </span>
      ),
    },
    {
      accessorKey: "category_name",
      header: "类别",
      size: 100,
      cell: ({ row }) => row.original.category_name || "-",
    },
    {
      accessorKey: "supplier_name",
      header: "供应商",
      size: 120,
      cell: ({ row }) => row.original.supplier_name || "-",
    },
    {
      accessorKey: "country_name",
      header: "国家",
      size: 80,
      cell: ({ row }) => row.original.country_name || "-",
    },
    {
      accessorKey: "unit",
      header: "单位",
      size: 60,
      cell: ({ row }) => (
        <span className="text-center block text-xs">
          {row.original.unit || "-"}
        </span>
      ),
    },
    {
      accessorKey: "price",
      header: () => <span className="text-right block">价格</span>,
      size: 100,
      cell: ({ row }) => {
        const { price, currency } = row.original;
        if (price == null) return <span className="text-right block">-</span>;
        return (
          <span className="text-right block">
            {currency ? `${currency} ` : ""}{price}
          </span>
        );
      },
    },
    {
      accessorKey: "status",
      header: "状态",
      size: 70,
      cell: ({ row }) => <StatusBadge status={row.original.status} />,
    },
    ...(isWriter
      ? [
          {
            id: "actions",
            header: "操作",
            size: 60,
            cell: ({ row }: { row: { original: ProductItem } }) => (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="sm" className="h-7 w-7 p-0">
                    <MoreHorizontal className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onClick={() => openEdit(row.original)}>
                    编辑
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => handleToggleStatus(row.original)}>
                    {row.original.status ? "停用" : "启用"}
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    className="text-red-600"
                    onClick={() => handleDelete(row.original)}
                  >
                    删除
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            ),
          } as ColumnDef<ProductItem>,
        ]
      : []),
  ];

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const toolbar = (
    <div className="flex items-center gap-2 flex-1">
      <Select value={filterCategory} onValueChange={setFilterCategory}>
        <SelectTrigger className="h-8 w-32 text-xs">
          <SelectValue placeholder="类别" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">全部类别</SelectItem>
          {categories.map((c) => (
            <SelectItem key={c.id} value={c.name}>{c.name}</SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select value={filterSupplier} onValueChange={setFilterSupplier}>
        <SelectTrigger className="h-8 w-32 text-xs">
          <SelectValue placeholder="供应商" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">全部供应商</SelectItem>
          {suppliers.map((s) => (
            <SelectItem key={s.id} value={s.name}>{s.name}</SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select value={filterCountry} onValueChange={setFilterCountry}>
        <SelectTrigger className="h-8 w-32 text-xs">
          <SelectValue placeholder="国家" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">全部国家</SelectItem>
          {countries.map((c) => (
            <SelectItem key={c.id} value={c.name}>{c.name}</SelectItem>
          ))}
        </SelectContent>
      </Select>

      <span className="text-xs text-muted-foreground ml-auto">
        共 {totalProducts} 个产品
      </span>
      <Button
        variant="outline"
        size="sm"
        className="h-8 text-xs"
        onClick={() => {
          exportToCSV(
            ["商品代码", "英文品名", "类别", "供应商", "国家", "单位", "价格", "币种"],
            products.map((p: ProductItem) => [
              p.code || "",
              p.product_name_en || "",
              p.category_name || "",
              p.supplier_name || "",
              p.country_name || "",
              p.unit || "",
              p.price ?? "",
              p.currency || "",
            ]),
            `产品列表_${new Date().toISOString().slice(0, 10)}.csv`
          );
        }}
      >
        <Download className="mr-1 h-3 w-3" /> 导出 CSV
      </Button>
      {isWriter && (
        <Button size="sm" className="h-8 text-xs" onClick={openCreate}>
          <Plus className="mr-1 h-3 w-3" /> 新增产品
        </Button>
      )}
    </div>
  );

  return (
    <>
      <DataTable
        columns={columns}
        data={products}
        searchKey="product_name_en"
        searchPlaceholder="搜索产品名..."
        pageSize={PAGE_SIZE}
        toolbar={toolbar}
        emptyState={<EmptyState icon={Package} title="暂无产品数据" />}
        totalRows={totalProducts}
        onPageChange={(pageIndex) => {
          setCurrentPage(pageIndex);
          fetchProducts(pageIndex);
        }}
      />

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editing ? "编辑产品" : "新增产品"}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            {/* Row 1: Names */}
            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label>英文品名 *</Label>
                <Input
                  value={form.product_name_en}
                  onChange={(e) => updateForm("product_name_en", e.target.value)}
                  placeholder="Product name in English"
                />
              </div>
              <div className="grid gap-2">
                <Label>日文品名</Label>
                <Input
                  value={form.product_name_jp}
                  onChange={(e) => updateForm("product_name_jp", e.target.value)}
                  placeholder="日本語の商品名"
                />
              </div>
            </div>

            {/* Row 2: Code + Brand */}
            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label>商品代码</Label>
                <Input
                  value={form.code}
                  onChange={(e) => updateForm("code", e.target.value)}
                  placeholder="例如：BEEF-001"
                />
              </div>
              <div className="grid gap-2">
                <Label>品牌</Label>
                <Input
                  value={form.brand}
                  onChange={(e) => updateForm("brand", e.target.value)}
                />
              </div>
            </div>

            {/* Row 3: FK Selects */}
            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label>国家</Label>
                <Select
                  value={form.country_id}
                  onValueChange={(v) => updateForm("country_id", v === "__none__" ? "" : v)}
                >
                  <SelectTrigger><SelectValue placeholder="选择国家" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none__">无</SelectItem>
                    {countries.map((c) => (
                      <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-2">
                <Label>类别</Label>
                <Select
                  value={form.category_id}
                  onValueChange={(v) => updateForm("category_id", v === "__none__" ? "" : v)}
                >
                  <SelectTrigger><SelectValue placeholder="选择类别" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none__">无</SelectItem>
                    {categories.map((c) => (
                      <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label>供应商</Label>
                <Select
                  value={form.supplier_id}
                  onValueChange={(v) => updateForm("supplier_id", v === "__none__" ? "" : v)}
                >
                  <SelectTrigger><SelectValue placeholder="选择供应商" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none__">无</SelectItem>
                    {suppliers.map((s) => (
                      <SelectItem key={s.id} value={String(s.id)}>{s.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-2">
                <Label>港口</Label>
                <Select
                  value={form.port_id}
                  onValueChange={(v) => updateForm("port_id", v === "__none__" ? "" : v)}
                >
                  <SelectTrigger><SelectValue placeholder="选择港口" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none__">无</SelectItem>
                    {ports.map((p) => (
                      <SelectItem key={p.id} value={String(p.id)}>{p.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Row 4: Price + Currency */}
            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label>价格</Label>
                <Input
                  type="number"
                  min={0}
                  step="0.01"
                  value={form.price}
                  onChange={(e) => updateForm("price", e.target.value)}
                  placeholder="0.00"
                />
              </div>
              <div className="grid gap-2">
                <Label>币种</Label>
                <Input
                  value={form.currency}
                  onChange={(e) => updateForm("currency", e.target.value)}
                  placeholder="例如：AUD"
                />
              </div>
            </div>

            {/* Row 5: Unit specs */}
            <div className="grid grid-cols-3 gap-4">
              <div className="grid gap-2">
                <Label>单位</Label>
                <Input
                  value={form.unit}
                  onChange={(e) => updateForm("unit", e.target.value)}
                  placeholder="例如：KG"
                />
              </div>
              <div className="grid gap-2">
                <Label>单位规格</Label>
                <Input
                  value={form.unit_size}
                  onChange={(e) => updateForm("unit_size", e.target.value)}
                  placeholder="例如：10kg"
                />
              </div>
              <div className="grid gap-2">
                <Label>包装规格</Label>
                <Input
                  value={form.pack_size}
                  onChange={(e) => updateForm("pack_size", e.target.value)}
                  placeholder="例如：6-10ct/10kg"
                />
              </div>
            </div>

            {/* Row 6: Origin */}
            <div className="grid gap-2">
              <Label>原产地</Label>
              <Input
                value={form.country_of_origin}
                onChange={(e) => updateForm("country_of_origin", e.target.value)}
                placeholder="例如：Australia"
              />
            </div>

            {/* Row 7: Dates */}
            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label>有效开始日期</Label>
                <Input
                  type="date"
                  value={form.effective_from}
                  onChange={(e) => updateForm("effective_from", e.target.value)}
                />
              </div>
              <div className="grid gap-2">
                <Label>有效结束日期</Label>
                <Input
                  type="date"
                  value={form.effective_to}
                  onChange={(e) => updateForm("effective_to", e.target.value)}
                />
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>取消</Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {editing ? "保存" : "创建"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
