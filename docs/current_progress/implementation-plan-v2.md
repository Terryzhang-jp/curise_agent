# 实施方案 V2 — 文档驱动的 Agent 系统

> 日期: 2026-04-10
> 状态: 待实施

---

## 0. 项目背景 — 5 分钟上手

### 这个项目是什么

一个**邮轮供应链管理系统**。邮轮公司 (Royal Caribbean, Silversea 等) 给我们发采购订单 (PDF), 我们需要:
1. **读懂订单** — 从 PDF 中提取产品列表、数量、价格、交货日期等
2. **匹配产品** — 将订单中的产品与我们数据库里的产品对应
3. **生成询价单** — 为每个供应商生成 Excel 询价文件, 发给供应商报价
4. **管理履约** — 跟踪订单从报价到交货到付款的全生命周期

### 为什么要改版

当前系统把所有逻辑硬编码在后台管道里 (`order_processor.py`), AI Agent 只是一个触发按钮。

**改版目标**: Agent 成为系统的大脑 — 它理解文档、决定做什么、调用工具执行。

### 技术栈

| 组件 | 技术 |
|------|------|
| 后端框架 | FastAPI (Python 3.13) |
| 数据库 | PostgreSQL (Supabase) + pgvector |
| AI 模型 | Gemini 2.5 Flash (文档提取) + Kimi K2.5 (Agent 对话) |
| 文件存储 | Supabase Storage |
| Agent 引擎 | 自研 ReActAgent (services/agent/engine.py) |
| 前端 | Next.js (不在本文范围) |

### 已验证的事实

| 测试 | 结果 |
|------|------|
| Gemini 原生 PDF 提取 (born-digital, 13 页) | 94/94 产品, 100% 准确 |
| Gemini 原生 PDF 提取 (scanned, 38 页) | 105/105 产品, 100% 准确 |
| Gemini 原生 PDF 提取 (born-digital, 3 页) | 73/73 产品, 总金额精确匹配 |
| Marker CPU 模式 | **不可用**: 13 分钟/13 页, 表格全丢, 扫描件崩溃 |
| Agent Tool 调用链 (extract → match → inquiry check) | 全部通过 |

---

## 1. 架构

### 一份文档的生命周期

```
用户上传 PDF
  │
  ├── ① 原始文件 → Supabase Storage (永久保存)
  │
  ├── ② Gemini 2.5 Flash 一次调用, 输出一个 JSON:
  │     {
  │       doc_type:       "purchase_order"          ← 文档分类
  │       page_markdown:  "# Purchase Order\n..."   ← 完整 Markdown 全文
  │       tables:         [{headers, rows}]          ← 结构化表格 (紧凑格式)
  │       metadata:       {po_number, ship_name...}  ← 关键字段
  │     }
  │
  ├── ③ page_markdown → 分 chunk → Gemini Embedding → pgvector
  │     (语义检索: "去年有机蔬菜的订单")
  │
  ├── ④ tables + metadata → 写入业务表 (v2_orders, products)
  │     (精确查询: "订单 68358749 的总金额")
  │
  └── ⑤ Agent: 读 Markdown / 搜 chunks / 查 SQL / 调 tools
```

### 为什么是一次 Gemini 调用

| 问题 | 方案 A: 两次调用 | 方案 B: 一次调用 (选择) |
|------|---------------|---------------------|
| 第一次 | PDF → Markdown | PDF → JSON (含 Markdown + 结构化) |
| 第二次 | Markdown → JSON | 不需要 |
| API 成本 | 2x | 1x |
| 浪费 | 相同内容处理两次 | 0 |
| token 效率 | - | 表格用 headers+rows 格式, 省 73% |

### token 节省: headers+rows 格式

```
❌ 旧格式 (逐行重复 key, 100 行 ≈ 15K tokens):
[{"product_code":"A001","product_name":"Apple","quantity":100,"unit":"KG","unit_price":1.72,"total_price":172},
 {"product_code":"A002","product_name":"Banana","quantity":50,...},
 ...]

✅ 新格式 (headers 只写一次, 100 行 ≈ 4K tokens):
{"headers":["product_code","product_name","quantity","unit","unit_price","total_price"],
 "rows":[["A001","Apple",100,"KG",1.72,172],["A002","Banana",50,...],...]
}
```

---

## 2. 自适应切分 — 40 页阈值

### 为什么需要切分

Gemini 2.5 Flash 输出上限 65,536 tokens。长文档 (>40 页) 的 Markdown + 表格可能接近上限。

### 输出量估算

| 页数 | Markdown | 表格 (headers+rows) | 总输出 | 占上限 | 策略 |
|------|---------|---------------------|--------|--------|------|
| 3p | ~3K | ~3K | ~6K | 9% | 一次调用 |
| 13p | ~8K | ~4K | ~12K | 18% | 一次调用 |
| 38p | ~20K | ~4K | ~24K | 37% | 一次调用 |
| **40p** | **~22K** | **~5K** | **~27K** | **41%** | **阈值** |
| 80p | ~45K | ~8K | ~53K | 81% | 分批 |
| 100p+ | ~55K+ | ~10K | ~65K+ | >100% | 分批 |

### 切分逻辑

```
≤40 页: 一次 Gemini 调用, 完整输出
>40 页: 按 20 页一批, 分批调用, 合并结果
```

### 截断安全网

每次调用后检查 `finish_reason`:
- `STOP` → 正常完成
- `MAX_TOKENS` → 截断了 → 自动缩小 batch 重试

---

## 3. 数据库设计

### 新表: v2_documents (所有上传的文档)

```sql
CREATE TABLE v2_documents (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL,

    -- 文件信息
    filename        VARCHAR(500) NOT NULL,
    file_url        VARCHAR(500),            -- Supabase Storage path
    file_type       VARCHAR(10) NOT NULL,    -- pdf, excel, image
    file_size_bytes INTEGER,

    -- Gemini 提取结果
    doc_type        VARCHAR(30),             -- purchase_order, invoice, quotation,
                                             -- delivery_note, price_list, unknown
    content_markdown TEXT,                   -- 完整 Markdown 全文
    extracted_data   JSON,                   -- {tables: [{headers, rows}], metadata: {...}}
    extraction_method VARCHAR(30),           -- gemini_native_pdf

    -- 状态
    status          VARCHAR(20) DEFAULT 'uploaded',
                    -- uploaded → extracting → extracted → error
    processing_error TEXT,

    -- 时间
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW(),
    extracted_at    TIMESTAMP
);
```

### 新表: v2_document_chunks (语义检索)

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE v2_document_chunks (
    id              SERIAL PRIMARY KEY,
    document_id     INTEGER NOT NULL REFERENCES v2_documents(id) ON DELETE CASCADE,
    chunk_index     INTEGER NOT NULL,
    content         TEXT NOT NULL,
    chunk_metadata  JSON,                    -- {page, section, header}
    embedding       vector(768),             -- Gemini embedding-001, 768 维
    token_count     INTEGER,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_doc_chunks_embedding
    ON v2_document_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX idx_doc_chunks_document ON v2_document_chunks(document_id);
```

### 新表: v2_document_links (文档 ↔ 业务实体)

```sql
CREATE TABLE v2_document_links (
    id              SERIAL PRIMARY KEY,
    document_id     INTEGER NOT NULL REFERENCES v2_documents(id),
    entity_type     VARCHAR(30) NOT NULL,    -- order, supplier, product_batch
    entity_id       INTEGER NOT NULL,
    link_type       VARCHAR(30),             -- source, invoice, delivery_note
    created_at      TIMESTAMP DEFAULT NOW()
);
```

### 修改: v2_orders 加 document_id

```sql
ALTER TABLE v2_orders ADD COLUMN document_id INTEGER REFERENCES v2_documents(id);
```

---

## 4. 处理流程 (代码)

### Gemini 提取 Prompt

```python
EXTRACT_PROMPT = (
    "Analyze this document and return a JSON object with:\n\n"
    "1. doc_type: one of purchase_order, invoice, quotation, "
    "   delivery_note, price_list, unknown\n"
    "2. page_markdown: convert the ENTIRE document to Markdown "
    "   (preserve headings, tables as pipe tables, lists)\n"
    "3. tables: array of {table_id, headers: [...], rows: [[...], ...]} "
    "   — use compact headers+rows format, NOT repeated key-value per row\n"
    "4. metadata: key fields {po_number, ship_name, vendor_name, "
    "   delivery_date (YYYY-MM-DD), currency, destination_port, total_amount}\n\n"
    "Rules:\n"
    "- Numbers must be numeric type, not strings\n"
    "- page_markdown must be COMPLETE, not a summary\n"
    "- tables use compact headers+rows to save tokens\n"
    "- Extract ALL items from ALL pages"
)
```

### 自适应提取

```python
SPLIT_THRESHOLD = 40  # 页

def process_document(file_bytes: bytes) -> dict:
    page_count = get_pdf_page_count(file_bytes)

    if page_count <= SPLIT_THRESHOLD:
        return gemini_extract_full(file_bytes)
    else:
        return gemini_extract_chunked(file_bytes, page_count, batch_size=20)


def gemini_extract_full(file_bytes: bytes) -> dict:
    """≤40 页: 一次调用搞定."""
    client = genai.Client(api_key=settings.GOOGLE_API_KEY)
    pdf_part = types.Part.from_bytes(data=file_bytes, mime_type="application/pdf")

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[pdf_part, EXTRACT_PROMPT],
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )

    # 截断安全网
    if response.candidates[0].finish_reason == "MAX_TOKENS":
        page_count = get_pdf_page_count(file_bytes)
        return gemini_extract_chunked(file_bytes, page_count, batch_size=20)

    return json.loads(response.text)


def gemini_extract_chunked(file_bytes, page_count, batch_size=20) -> dict:
    """>40 页: 分批提取, 合并结果."""
    all_markdown, all_table_rows = [], []
    metadata, doc_type, headers = {}, "unknown", None

    for batch_start in range(1, page_count + 1, batch_size):
        batch_end = min(batch_start + batch_size - 1, page_count)
        prompt = EXTRACT_PROMPT + f"\n\nOnly process pages {batch_start} to {batch_end}."
        result = gemini_call(file_bytes, prompt)

        if batch_start == 1:
            metadata = result.get("metadata", {})
            doc_type = result.get("doc_type", "unknown")

        all_markdown.append(result.get("page_markdown", ""))
        for table in result.get("tables", []):
            if headers is None:
                headers = table.get("headers", [])
            all_table_rows.extend(table.get("rows", []))

    return {
        "doc_type": doc_type,
        "page_markdown": "\n\n".join(all_markdown),
        "tables": [{"table_id": "main", "headers": headers, "rows": all_table_rows}] if headers else [],
        "metadata": metadata,
    }
```

---

## 5. Embedding + 语义搜索

### Embedding

```python
# 模型: gemini-embedding-001, 768 维, $0.15/1M tokens
def embed_chunks(chunks: list[str]) -> list[list[float]]:
    result = client.models.embed_content(
        model="gemini-embedding-001",
        contents=chunks,
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_DOCUMENT",
            output_dimensionality=768,
        ),
    )
    return [emb.values for emb in result.embeddings]
```

### 语义搜索

```sql
-- pgvector cosine distance search
SELECT dc.content, d.filename, d.doc_type,
       1 - (dc.embedding <=> query_vec::vector) AS similarity
FROM v2_document_chunks dc
JOIN v2_documents d ON dc.document_id = d.id
ORDER BY dc.embedding <=> query_vec::vector
LIMIT 5;
```

---

## 6. Chunking 策略

按 Markdown 标题分割, 每 chunk ≤2000 字符, 10% overlap:

```python
def chunk_markdown(text: str, max_chars=2000, overlap=200) -> list[dict]:
    sections = re.split(r'(^#{1,3}\s+.+$)', text, flags=re.MULTILINE)
    chunks, header = [], ""
    for section in sections:
        if re.match(r'^#{1,3}\s+', section):
            header = section.strip()
            continue
        content = f"{header}\n{section.strip()}" if header else section.strip()
        if not content: continue
        if len(content) > max_chars:
            # 按段落再分
            ...
        else:
            chunks.append({"content": content, "header": header})
    return chunks
```

---

## 7. 技术决策记录

| # | 决策 | 理由 | 替代方案及放弃原因 |
|---|------|------|-----------------|
| 1 | Gemini 一次调用出 Markdown + 结构化 | 省 API 调用, 0 浪费 | 两次调用 (浪费); Marker CPU (太慢, 表格丢失) |
| 2 | headers+rows 表格格式 | 省 73% tokens | 逐行 JSON objects (15K vs 4K tokens) |
| 3 | 40 页切分阈值 | 输出 ~27K tokens, 占上限 41%, 安全 | 不切分 (>50 页可能超限); 按页 (38 次调用太多) |
| 4 | PostgreSQL + pgvector | 已有 Supabase, 250K 向量够用 | Parquet/Lance (5M+ 才需要); 专用向量库 (过度) |
| 5 | Gemini embedding-001, 768 维 | 已有 API key, 768 维够用, 存储省 4x | 3072 维 (存储大); OpenAI embedding (额外依赖) |
| 6 | Markdown 标题分割 | 保留语义边界, 不依赖 LangChain | 固定 token 切割 (破坏结构); LangChain (额外依赖) |

---

## 8. 依赖

### Python 包 (新增)
```
pgvector          # SQLAlchemy Vector 类型
pymupdf           # PDF 页数检测 (已安装)
```

### Supabase
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### 不需要的
- ❌ Marker (CPU 不可用: 790s/13页, 0 表格; GPU 需要额外基础设施)
- ❌ Parquet / Lance / LanceDB (250K 向量, pgvector 轻松处理)
- ❌ LangChain (chunking 自己写, ~30 行)
- ❌ GPU 实例 (全部是 API 调用)

---

## 9. 实施步骤

| Step | 做什么 | 前置 | 预计时间 |
|------|--------|------|---------|
| 1 | 安装 pgvector Python 包 | 无 | 5min |
| 2 | 创建 v2_documents + v2_document_chunks + v2_document_links 表 | 无 | 30min |
| 3 | 启用 Supabase pgvector 扩展 | 无 | 5min |
| 4 | 新建 `services/document_processor.py` — Gemini 一次调用 + 40 页自适应切分 + 截断检测 | 无 | 2h |
| 5 | 实现 chunking + Gemini Embedding + pgvector 写入 | Step 2, 3 | 1h |
| 6 | 新建上传路由: POST /documents/upload → create → extract → chunk → embed | Step 4, 5 | 1h |
| 7 | 新建 `search_documents` tool (Agent 语义搜索) | Step 5 | 30min |
| 8 | 修改 `extract_order` tool: 从 document 创建 order | Step 4 | 30min |
| 9 | 新建 `process-document` skill | Step 7, 8 | 30min |
| 10 | 端到端测试 (3 份 PDF + 语义搜索) | All | 1h |

**总计: ~7 小时**

---

## 10. 验证标准

| 测试 | 通过条件 |
|------|---------|
| Gemini 提取 (≤40 页) | 一次调用, doc_type + page_markdown + tables + metadata 全部非空 |
| Gemini 提取 (>40 页) | 分批调用, 合并后 tables.rows 数量正确, page_markdown 完整 |
| 截断检测 | finish_reason=MAX_TOKENS 时自动重试 |
| 分类 | 采购订单 → "purchase_order" |
| 产品准确率 | 73/73 (Celebrity Edge), 94/94 (Silver Nova), 105/105 (Royal Caribbean) |
| 数值验证 | price × qty ≈ total, 100% 通过 |
| chunks | 每文档 10-50 chunks, 按标题分割, 有 embedding |
| 语义搜索 | "apple supplier" → 找到含 APPLE GRANNY SMITH 的 chunks |
| 精确查询 | SQL: extracted_data->'metadata'->>'po_number' = '68358749' |
| Order 关联 | v2_orders.document_id → v2_documents.id |
| Agent 端到端 | 上传 → 识别类型 → 提取 → 匹配 → 询价 |
