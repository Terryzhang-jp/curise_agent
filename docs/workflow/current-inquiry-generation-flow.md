# 询价单生成 — 当前工作流 (2026-04-09)

## 总览

```
订单提取+匹配完成 (status="ready")
      │
      ▼
  用户在 chat 中: "生成询价单"
      │
      ▼
  Agent 调用 manage_inquiry(action="check", order_id=N)
      │  检查每个供应商的数据完整性
      │  返回: ready / needs_input / completed
      │
      ├── 有 blocking gap → manage_inquiry(action="fill_gaps", ...)
      │     用户提供缺失字段 → 保存到 order.inquiry_data
      │
      ▼
  manage_inquiry(action="generate", order_id=N)
      │
      ▼
  inquiry_agent.py: run_inquiry_orchestrator()
      │  按供应商分组, ThreadPoolExecutor 并行
      │
      ├── per-supplier: _generate_single_supplier()
      │      │
      │      ├── 模板解析: resolve_template(supplier_id, all_templates)
      │      │     exact binding → candidate list → generic fallback
      │      │
      │      ├── 路径 A: 有 zone_config (确定性, 0 LLM)
      │      │     template_engine.fill_template()
      │      │     → verify_output()
      │      │     → 成功 → 保存
      │      │     → 失败 → fallback 到路径 B
      │      │
      │      ├── 路径 B: 有模板文件, 无 zone_config (1 LLM call)
      │      │     → 加载模板 Excel
      │      │     → 检测公式列 + 注释 (annotations)
      │      │     → Gemini JSON call: header field mapping
      │      │     → write_cells + write_product_rows
      │      │     → enforce_annotation (日期格式/小数位等)
      │      │     → 重建公式 (regex-based, 有脆弱性)
      │      │
      │      └── 路径 C: 无模板 (generic layout)
      │            → InquiryWorkbook.create_generic()
      │
      ├── 保存 Excel → Supabase Storage + workspace
      ├── 生成 HTML preview
      └── SSE 事件推送
```

## 已知问题

1. **zone_config 覆盖率不足**: 有 zone_config → 确定性路径 (稳定); 无 zone_config → LLM 路径 (不稳定)。不稳定的根因是 LLM 路径被触发太多。

2. **公式重建脆弱**: openpyxl insert_rows 不更新公式引用, 用 regex 手动修复, 对嵌套公式/绝对引用可能出错。

3. **Template engine 失败时 silent fallback**: 确定性路径失败后静默转到 LLM 路径, 用户不知道。

## 关键文件

| 文件 | 行数 | 职责 |
|------|------|------|
| `services/inquiry_agent.py` | 1518 | 编排 + per-supplier 生成 |
| `services/template_engine.py` | 602 | 确定性模板填充 (zone_config) |
| `services/excel_writer.py` | ~300 | InquiryWorkbook (底层 Excel 操作) |
| `services/template_matcher.py` | ~300 | 模板匹配 (提取阶段用, 也被询价间接使用) |
| `services/tools/inquiry_workflow.py` | 445 | manage_inquiry 工具 (agent 入口) |
