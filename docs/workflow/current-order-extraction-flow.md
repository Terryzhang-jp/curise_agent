# 订单提取 — 当前工作流 (2026-04-09)

## 总览

```
用户上传 PDF/Excel
      │
      ▼
  routes/orders.py: POST /orders/upload
      │  保存文件到 Supabase Storage
      │  创建 Order (status="uploading")
      │  启动后台线程
      ▼
  order_processor.py: process_order()
      │
      ├─── Step 0: 模板匹配 (template_matcher.py)
      │      fingerprint → source_company → keyword_idf
      │      结果: template 对象 或 None
      │
      ├─── Step 1: 提取 (3 条路径)
      │      │
      │      ├── 路径 A: template + document_schema
      │      │     → schema_extraction.extract_order_with_schema()
      │      │     设计目的: 大 PDF 分页提取
      │      │     现状: Gemini 原生 PDF 已能处理 1000 页, 此路径冗余
      │      │
      │      ├── 路径 B: template (无 schema)
      │      │     → _template_guided_extract()
      │      │     设计目的: 用 column_mapping 增强提取
      │      │     现状: PDF 场景下 Gemini 原生 PDF 更准; Excel 场景仍有价值
      │      │
      │      └── 路径 C: 无 template  ← 当前主路径
      │            → smart_extract()
      │            → _gemini_native_pdf_extract() (gemini-2.5-flash)
      │            → 原生 PDF 输入 + response_mime_type="application/json"
      │            → best-of-2 (跑 2 次取产品数多的)
      │            → _validate_extraction_numbers() 数值交叉验证
      │            → 失败 fallback → vision_extract()
      │
      ├─── normalize_metadata() + normalize_products()
      │
      ├─── _validate_extraction() 质量门禁
      │      产品数=0 → status="error"
      │      缺 metadata → 记录 warning
      │
      ├─── Step 2: 产品匹配
      │      _resolve_geo()     → 国家/港口识别 (代码优先, LLM 兜底)
      │      _batch_match()     → 代码精确匹配
      │      _refine_with_llm() → 模糊项 LLM 精炼
      │
      └─── Step 3: 后续自动分析
             financial_analysis, inquiry_pre_analysis, delivery_environment
```

## 提取路径详情

### 路径 C: smart_extract() — 当前主路径

```
smart_extract(file_bytes, file_type)
  │
  ├── Excel → _extract_and_structure_excel() (openpyxl + Gemini 结构化)
  │
  └── PDF → _gemini_native_pdf_extract() × 2 次
            │
            ├── google.genai.Client(api_key)
            ├── types.Part.from_bytes(pdf_bytes, mime_type="application/pdf")
            ├── model: gemini-2.5-flash
            ├── response_mime_type: application/json (保证合法 JSON)
            │
            ├── 输出: {order_metadata: {...}, products: [{...}, ...]}
            │
            ├── best-of-2: 取产品数多的结果
            │
            ├── _validate_extraction_numbers():
            │     price × qty ≈ total (within 2%)
            │     quantity > 0
            │     price >= 0
            │
            └── 失败 → fallback vision_extract() (旧路径)
```

### 测试数据

| PDF | 类型 | 页数 | 产品数 | 准确率 | 时间 |
|-----|------|------|--------|--------|------|
| Silver Nova | born-digital | 13 | 94/94 | 100% (数值验证全通过) | 87s |
| Royal Caribbean | scanned | 38 | 105/105 | 100% (spot check 5/5 精确) | 111s |

### 关键配置

```
模型: gemini-2.5-flash
API Key: .env → GOOGLE_API_KEY
尝试次数: 2 (best-of-2)
数值验证阈值: 2%
Fallback: vision_extract() (旧 Gemini Vision 图片路径)
```

## 已知问题

1. **3 条提取路径冗余**: 路径 A (schema_extraction) 和路径 B (template_guided, PDF 部分) 在 Gemini 原生 PDF 出现后已无存在必要。应简化为: PDF → smart_extract, Excel → template_guided 或 smart_extract。

2. **模板匹配在提取阶段无用**: 模板匹配只在询价生成阶段需要 (选择供应商模板)。提取阶段不论有没有模板, Gemini 原生 PDF 都能 100% 提取。

3. **best-of-2 增加延迟**: 为了补偿 LLM 非确定性 (1-3 产品波动), 时间翻倍。可考虑: 第一次 ≥ 期望产品数 → 跳过第二次。

4. **GOOGLE_API_KEY 仍是免费 tier**: .env 中的新 key 可用但仍是 AI Studio 免费 key, 生产环境需确认配额。
