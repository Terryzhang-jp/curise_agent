# PDF 提取 + 询价生成 稳定性研究报告

> 日期: 2026-04-09
> 目标: 基于业界证据, 找到提升订单 PDF 提取和询价 Excel 生成稳定性的最佳方案

---

## 第一部分: PDF 订单提取

### 1.1 当前做法

```
用户上传 PDF
  → pdf2image: PDF 转为图片 (每页一张 JPEG)
  → Gemini Vision: 图片 → JSON (order_metadata + products)
  → normalize: 清洗提取结果
```

这是 **Tier 2 方案** (直接用 LLM 读图片)。准确率 85-92%。

### 1.2 为什么不稳定 — 业界共识

> "Don't Use LLMs as OCR" — Marta Fernandez Garcia (Production ML Engineer)
> "PDF-native extraction is consistently more accurate, significantly faster, and dramatically cheaper than vision-model approaches" — PyMuPDF 团队 benchmark

**核心问题**: LLM 擅长语义理解, 但对结构化数据 (数字、价格、日期) 有 hallucination 风险。Gemini Vision 看到 "38,000" 可能读成 "88,000"。

**数据**:

| 方案 | 复杂表格准确率 | 速度 | 成本 |
|------|-------------|------|------|
| 直接 Vision LLM (我们当前) | 85-92% | 5-15s | 高 (token) |
| PDFPlumber (确定性) | 91.2% | <1s | 0 |
| Docling (开源 ML 模型) | 97.9% | 114ms/页 (GPU) | 0 |
| Google Document AI Layout Parser | 96% | 2-5s | $0.01-0.065/页 |
| Reducto API (YC, a16z $75M) | 99.24% (声称) | <1min | $0.015/页 |
| 混合方案 (PDFPlumber + LLM 语义映射) | 97-99% | 2-5s | 低 |

来源: Unstract, PyMuPDF, Procycons benchmark, Reducto, Google Cloud 文档

### 1.3 最 promising 的方法 — 分层混合管道

```
第 1 层: 确定性文本提取 (0 LLM, 0 错误风险)
  ├── born-digital PDF → PDFPlumber 提取文本 + 表格结构
  └── scanned PDF → OCR (Document AI 或 Tesseract)

第 2 层: LLM 语义映射 (1 次调用)
  输入: 第 1 层的原始文本 + 目标 schema
  任务: "哪个列是 product_name? 哪个是 quantity?"
  输出: 结构化 JSON

第 3 层: 数值交叉验证 (0 LLM)
  - sum(line_total) ≈ grand_total?
  - quantity > 0?
  - unit_price > 0?
  - 日期在合理范围?
```

**关键洞察: LLM 不应该读数字, 只应该理解语义。数字让代码读, 语义让 LLM 判断。**

### 1.4 PDFPlumber vs Document AI

| 维度 | PDFPlumber | Google Document AI |
|------|-----------|-------------------|
| **适用场景** | born-digital PDF (文本可选中) | 任何 PDF (含扫描件) |
| **GPU 需求** | **不需要** (纯 Python, CPU) | 不需要 (云 API) |
| **复杂表格** | 合并单元格处理一般, 嵌套表格弱 | Layout Parser 专门优化, 96% 准确率 |
| **数字准确率** | **100%** (直接读 PDF 文本层) | 99%+ (OCR 层偶尔出错) |
| **成本** | 0 | $0.01-0.065/页 |
| **速度** | <1s/页 | 2-5s/页 (API 调用) |
| **安装** | `pip install pdfplumber` (已安装) | 需要 Google Cloud 配置 (已有配置) |
| **缺点** | 扫描件无法处理; 复杂嵌套表格弱 | 成本; 需要网络 |

**判断: 不是二选一, 而是分层使用。**

- PDFPlumber 先跑 → 如果提取到表格 (行数 > 0) → 用 PDFPlumber 的结果
- PDFPlumber 失败 (扫描件, 或表格提取为空) → 走 Document AI 或 Vision fallback
- 无论哪层, LLM 只做语义映射, 不做数字读取

### 1.5 关于复杂格式 (嵌套单元格、合并单元格)

> 用户描述: "一个格子旁边有两个小格子, 一个记录单位, 一个记录价格"

这是 PDF 表格提取的经典难题。**PDF 没有"单元格"的概念** — 所有内容都是位于绝对坐标的文本块, "表格"是人类视觉推断的。

**处理方法**:

| 方案 | 嵌套/合并单元格处理能力 |
|------|---------------------|
| PDFPlumber | 依赖可见线条边框推断表格; 嵌套表格弱, 但单层合并单元格可以处理 |
| Camelot | 需要可见表格线; 对有边框的表格非常准确 |
| Document AI Layout Parser | 专门训练了复杂布局, 嵌套表格支持好 |
| Gemini Vision (图片) | 因为是"看"图片, 对视觉上明显的嵌套格子能理解 |
| Docling | Granite-Docling-258M 模型专门训练了复杂表格, **97.9%** |

**对我们的建议**: 大多数邮轮采购订单是 born-digital PDF (软件生成, 不是扫描件), PDFPlumber 能处理 90%+ 的情况。对于真正复杂的嵌套格式:
- 短期: Vision fallback (现有方案) 已经能处理, 只是数字可能不准 → 加数值验证
- 中期: 引入 Document AI Layout Parser 作为 PDFPlumber 和 Vision 之间的中间层
- 长期: 为高频供应商建立 document_schema (已有机制), 100% 确定性提取

### 1.6 具体实施路径

```
Step 1: PDFPlumber 预提取层 (我们已安装, template_matcher.py 已在用)
  → 在 order_processor.py 的 vision_extract() 前加 PDFPlumber 表格提取
  → 如果提取到表格 → 跳过 Vision, 直接 LLM 语义映射
  → 如果失败 → 走现有 Vision 路径

Step 2: 数值交叉验证
  → 提取后校验: sum(line_total) ≈ grand_total
  → 异常自动标记, 不 silent pass

Step 3 (可选): Document AI 作为 OCR 中间层
  → 扫描件 PDF → Document AI 先做 OCR → 再做 LLM 语义映射
  → 需要配置: 已有 DOCUMENT_AI_PROJECT_ID 等环境变量
```

---

## 第二部分: 询价 Excel 生成

### 2.1 当前做法

两条路径:
- **确定性路径** (template_engine + zone_config): 0 LLM, 代码计算每个单元格 → **稳定**
- **LLM 路径** (无 zone_config): Gemini 决定单元格值 → **不稳定**

### 2.2 业界调研结论

调研了 openpyxl, xlsxwriter, xlwings, Jinja2 模板引擎 (xltpl/xlsxtpl), formulas 库。

**结论: 我们的 template_engine 架构已经是 headless 服务器环境的最佳实践。**

| 方案 | 模板支持 | 行插入+公式更新 | 可靠性 | 无头服务器 |
|------|---------|---------------|--------|----------|
| openpyxl (原始) | 是 | **不行** (公式不更新) | 低 | 是 |
| openpyxl + zone-config (**我们的方案**) | 是 | **行** (重新生成所有公式) | **高** | 是 |
| xlsxwriter | 不支持模板 | N/A | 高 (新建文件) | 是 |
| xlwings | 是 | **完美** (真 Excel) | 最高 | **不行** (需要安装 Excel) |
| Jinja2 模板 (xltpl) | 是 | 部分 | 中 | 是 |

openpyxl `insert_rows` 不更新公式是 **by design** (维护者明确声明不会修)。我们的 formula template + `{row}` 占位符方案是正确的规避方式。

**唯一比我们更可靠的方案是 xlwings (用真 Excel 引擎)**, 但需要在服务器上安装 Excel — Cloud Run 不兼容。

### 2.3 不稳定的真正根因

**不是填充引擎有问题, 是 zone_config 覆盖率不足。**

| 场景 | 走哪条路径 | 稳定性 |
|------|-----------|--------|
| 供应商有 zone_config | 确定性路径 | ✅ 稳定 |
| 供应商有模板但无 zone_config | **LLM 路径** | ❌ 不稳定 |
| 供应商无模板 | Generic 路径 | ⚠️ 基本稳定但格式差 |

**每当 LLM 路径被触发, 就有不稳定的风险。减少 LLM 路径的触发频率 = 提高稳定性。**

### 2.4 解决思路

```
Step 1: 统计当前 zone_config 覆盖率
  → 查 v2_supplier_templates 表: 多少有 template_styles.zones, 多少没有

Step 2: 为缺 zone_config 的模板自动生成
  → template_analysis_agent.py 已有此能力 (LLM 一次性分析模板结构)
  → 生成后人工 review (5 分钟/模板)

Step 3: 覆盖 100% → 所有询价走确定性路径 → 0 LLM → 稳定

Step 4: LLM 路径降级为"紧急 fallback" (新供应商首次)
```

### 2.5 zone_config 质量问题

即使有 zone_config, 如果内容错误 (zone 边界不对、列映射错误), 确定性路径也会出错。

**需要加验证**:
- zone_config 生成后自动验证: product_zone.start > header 最大行, summary_zone.start = product_zone.end + 1
- fill_template 后的 verify_output 结果如果失败, 应该明确告知用户 (当前 silent fallback 到 LLM)

---

## 第三部分: 信心评估

### PDF 提取 — PDFPlumber 预提取层

**信心: 8/10**

**有信心的理由**:
- PDFPlumber 已安装, template_matcher.py 已在用 (不是从零开始)
- born-digital PDF 的文本提取是 100% 确定性 (不是 ML, 是直接读 PDF 文本层)
- 我们已有 `_template_guided_extract` 模式 (PDFPlumber 文本 + LLM 映射), 只需扩展到通用路径

**不确定的点**:
- 复杂嵌套表格 (一个格子里两个值) — PDFPlumber 依赖边框线推断, 无边框时可能失败
- PDFPlumber 的表格提取 API (`page.extract_tables()`) 对某些 PDF 布局返回空 → 需要 fallback
- **需要实际测试**: 拿 3-5 份真实订单 PDF 测试 PDFPlumber 的表格提取质量, 再决定策略

### 询价生成 — zone_config 覆盖率

**信心: 9/10**

**有信心的理由**:
- template_engine 已经 production-ready (有 verify_output)
- template_analysis_agent 已存在 (一次 LLM 调用生成 zone_config)
- 纯配置工作, 不需要改引擎代码

**不确定的点**:
- zone_config 自动生成的准确率 — 需要人工 review
- 某些供应商模板极其复杂 (多 sheet、跨 sheet 引用) — 可能无法自动化

### 建议优先级

| 优先级 | 做什么 | ROI |
|--------|--------|-----|
| **P0** | PDFPlumber 预提取 + LLM 语义映射 (改 order_processor.py) | 高 — 影响所有 PDF 订单 |
| **P0** | 数值交叉验证 (提取后) | 高 — 捕获所有 LLM hallucination |
| **P1** | 统计 + 补全 zone_config 覆盖率 | 高 — 消除询价不稳定的根因 |
| **P2** | Document AI 作为 OCR 中间层 (扫描件) | 中 — 取决于扫描件 PDF 比例 |
