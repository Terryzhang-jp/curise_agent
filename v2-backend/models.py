from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date, Text, ForeignKey, JSON, Numeric, CheckConstraint, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()


class User(Base):
    """Maps to the existing 'users' table in Supabase - read-only for v2 auth."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(100), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(100))
    role = Column(String(20), default="user")
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_default_password = Column(Boolean, default=False)
    password_changed_at = Column(DateTime, nullable=True)
    failed_login_attempts = Column(Integer, default=0)
    locked_until = Column(DateTime, nullable=True)
    last_failed_login = Column(DateTime, nullable=True)
    last_login = Column(DateTime, nullable=True)


class RefreshToken(Base):
    """Server-side refresh tokens — supports revocation."""

    __tablename__ = "v2_refresh_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False)  # SHA-256 of token
    expires_at = Column(DateTime, nullable=False)
    is_revoked = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class FieldSchema(Base):
    """字段模式容器 — 一组字段定义的集合"""

    __tablename__ = "v2_field_schemas"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    is_default = Column(Boolean, default=False)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    definitions = relationship("FieldDefinition", back_populates="schema", cascade="all, delete-orphan")


class FieldDefinition(Base):
    """字段定义 — 描述数据中的一个字段"""

    __tablename__ = "v2_field_definitions"
    __table_args__ = (
        UniqueConstraint("schema_id", "field_key", name="uq_field_def_schema_key"),
    )

    id = Column(Integer, primary_key=True, index=True)
    schema_id = Column(Integer, ForeignKey("v2_field_schemas.id", ondelete="CASCADE"), nullable=False)
    field_key = Column(String(50), nullable=False)
    field_label = Column(String(100), nullable=False)
    field_type = Column(String(20), default="string")  # string, number, date, currency
    is_core = Column(Boolean, default=False)
    is_required = Column(Boolean, default=False)
    extraction_hint = Column(Text, nullable=True)
    sort_order = Column(Integer, default=0)

    schema = relationship("FieldSchema", back_populates="definitions")


class OrderFormatTemplate(Base):
    """订单格式模板 — 描述一种 Excel/PDF 订单的列布局"""

    __tablename__ = "v2_order_format_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    file_type = Column(String(10), default="excel")  # "excel" | "pdf"
    format_fingerprint = Column(String(64), nullable=True)
    header_row = Column(Integer, default=1)
    data_start_row = Column(Integer, default=2)
    column_mapping = Column(JSON, nullable=True)  # {"A": "product_name", "B": "quantity", ...}
    field_schema_id = Column(Integer, ForeignKey("v2_field_schemas.id"), nullable=True)
    sample_file_url = Column(String(500), nullable=True)
    layout_prompt = Column(Text, nullable=True)  # AI-generated prompt describing document layout
    extracted_fields = Column(JSON, nullable=True)  # Metadata fields discovered by AI
    source_company = Column(String(200), nullable=True)   # e.g. "Royal Caribbean"
    match_keywords = Column(JSON, nullable=True)           # e.g. ["ROYAL CARIBBEAN", "RCI"]
    notes = Column(Text, nullable=True)                     # 管理员备注
    document_schema = Column(JSON, nullable=True)             # Schema-first: attribute_groups + page_layout + field_mapping
    is_active = Column(Boolean, default=True)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PipelineSession(Base):
    """Agent engine session storage (also used by pipeline history). Referenced by services/agent/storage.py."""

    __tablename__ = "v2_pipeline_sessions"

    id = Column(String(36), primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    status = Column(String(20), nullable=False, default="active")  # active | paused | completed | error | cancelled
    current_phase = Column(String(30), nullable=True)
    filename = Column(String(500), nullable=False)
    file_url = Column(String(500), nullable=True)
    file_type = Column(String(10), nullable=False, default="pdf")
    phase_results = Column(JSON, nullable=False, default=dict)
    order_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    summary_message_id = Column(Integer, nullable=True)  # For agent context compression

    messages = relationship("PipelineMessage", back_populates="session", cascade="all, delete-orphan", order_by="PipelineMessage.sequence")


class PipelineMessage(Base):
    """Agent engine message storage. Referenced by services/agent/storage.py."""

    __tablename__ = "v2_pipeline_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey("v2_pipeline_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    role = Column(String(15), nullable=False)  # agent | user | system | tool
    phase = Column(String(30), nullable=True)
    msg_type = Column(String(20), nullable=False, default="text")  # thought | action | observation | text | error | phase_transition | user_input
    content = Column(Text, nullable=False)
    meta = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("PipelineSession", back_populates="messages")


# ═══════════════════════════════════════════════════════════════════
# Shared v1 tables (products, countries, ports, categories, suppliers)
# ═══════════════════════════════════════════════════════════════════


class Country(Base):
    __tablename__ = "countries"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    code = Column(String(3), nullable=True)
    status = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Port(Base):
    __tablename__ = "ports"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    code = Column(String(50), nullable=True)
    country_id = Column(Integer, ForeignKey("countries.id"), nullable=True)
    location = Column(String(200), nullable=True)
    status = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    code = Column(String(50), nullable=True)
    description = Column(Text, nullable=True)
    status = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Supplier(Base):
    __tablename__ = "suppliers"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    country_id = Column(Integer, ForeignKey("countries.id"), nullable=True)
    contact = Column(String(100), nullable=True)
    email = Column(String(100), nullable=True)
    phone = Column(String(20), nullable=True)
    address = Column(Text, nullable=True)
    zip_code = Column(String(20), nullable=True)
    fax = Column(String(50), nullable=True)
    default_payment_method = Column(String(100), nullable=True)
    default_payment_terms = Column(String(100), nullable=True)
    status = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SupplierCategory(Base):
    __tablename__ = "supplier_categories"
    __table_args__ = (
        UniqueConstraint("supplier_id", "category_id"),
        {"extend_existing": True},
    )

    supplier_id = Column(Integer, ForeignKey("suppliers.id"), primary_key=True)
    category_id = Column(Integer, ForeignKey("categories.id"), primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Product(Base):
    """Shared v1 products table — full CRUD from v2."""

    __tablename__ = "products"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    product_name_en = Column(String(100), nullable=False)
    product_name_jp = Column(String(100), nullable=True)
    code = Column(String(50), nullable=True)
    country_id = Column(Integer, ForeignKey("countries.id"), nullable=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)
    port_id = Column(Integer, ForeignKey("ports.id"), nullable=True)
    unit = Column(String(20), nullable=True)
    price = Column(Numeric(10, 2), nullable=True)
    unit_size = Column(String(50), nullable=True)
    pack_size = Column(String(50), nullable=True)
    country_of_origin = Column(String(50), nullable=True)
    brand = Column(String(100), nullable=True)
    currency = Column(String(20), nullable=True)
    effective_from = Column(DateTime, nullable=True)
    effective_to = Column(DateTime, nullable=True)
    status = Column(Boolean, default=True)


# Backward compatibility alias
ProductReadOnly = Product


class SupplierTemplate(Base):
    """供应商模板 — 描述供应商询价单的填写位置"""

    __tablename__ = "v2_supplier_templates"

    id = Column(Integer, primary_key=True, index=True)
    supplier_id = Column(Integer, nullable=True)  # 逻辑关联, 不加 FK 约束 (legacy, 用 supplier_ids)
    supplier_ids = Column(JSON, nullable=True)  # [1, 2, 3] 多个供应商 ID
    country_id = Column(Integer, nullable=True)  # 逻辑关联到 countries 表
    template_name = Column(String(200), nullable=False)
    template_file_url = Column(String(500), nullable=True)
    field_positions = Column(JSON, nullable=True)  # {"po_number": {"position": "A4", "data_type": "string", "description": "PO番号"}, ...} or legacy {"po_number": "A4"}
    has_product_table = Column(Boolean, default=True)
    product_table_config = Column(JSON, nullable=True)  # {"start_row": 12, "columns": {"A": "product_code", ...}}
    order_format_template_id = Column(Integer, nullable=True)  # 绑定的订单模板 ID
    field_mapping_metadata = Column(JSON, nullable=True)  # AI 匹配元数据 (provenance)
    template_styles = Column(JSON, nullable=True)  # 样式层: product_row_styles, column_widths, row_height
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DeliveryLocation(Base):
    """仓库/配送点 — 按港口管理的本地收货信息"""

    __tablename__ = "v2_delivery_locations"

    id = Column(Integer, primary_key=True, index=True)
    port_id = Column(Integer, ForeignKey("ports.id"), nullable=True)
    name = Column(String(200), nullable=False)
    address = Column(Text, nullable=True)
    contact_person = Column(String(100), nullable=True)
    contact_phone = Column(String(50), nullable=True)
    delivery_notes = Column(String(200), nullable=True)
    ship_name_label = Column(String(200), nullable=True)  # "船名【{ship_name}】"
    is_default = Column(Boolean, default=True)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CompanyConfig(Base):
    """公司配置 — Merit Trading 的固定信息，admin 可编辑"""

    __tablename__ = "v2_company_config"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text, nullable=False, default="")
    label = Column(String(100), nullable=True)
    sort_order = Column(Integer, default=0)
    updated_by = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Order(Base):
    """订单 — 独立业务实体，自动处理 PDF/Excel 订单"""

    __tablename__ = "v2_orders"
    __table_args__ = (
        CheckConstraint("total_amount >= 0", name="ck_v2_orders_total_amount_nonneg"),
        CheckConstraint("payment_amount >= 0", name="ck_v2_orders_payment_amount_nonneg"),
        CheckConstraint("invoice_amount >= 0", name="ck_v2_orders_invoice_amount_nonneg"),
        CheckConstraint(
            "status IN ('uploading','pending_template','extracting','matching','ready','error')",
            name="ck_v2_orders_status_enum",
        ),
        CheckConstraint(
            "fulfillment_status IN ('pending','inquiry_sent','quoted','confirmed','delivering','delivered','invoiced','paid')",
            name="ck_v2_orders_fulfillment_status_enum",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    filename = Column(String(500), nullable=False)
    file_url = Column(String(500), nullable=True)
    file_type = Column(String(10), default="pdf")
    status = Column(String(20), default="uploading")  # uploading | extracting | matching | ready | error
    processing_error = Column(Text, nullable=True)
    country_id = Column(Integer, nullable=True)
    port_id = Column(Integer, nullable=True)
    delivery_date = Column(String(50), nullable=True)
    extraction_data = Column(JSON, nullable=True)
    order_metadata = Column(JSON, nullable=True)
    products = Column(JSON, nullable=True)
    product_count = Column(Integer, default=0)
    total_amount = Column(Numeric(12, 2), nullable=True)
    match_results = Column(JSON, nullable=True)
    match_statistics = Column(JSON, nullable=True)
    anomaly_data = Column(JSON, nullable=True)
    financial_data = Column(JSON, nullable=True)
    inquiry_data = Column(JSON, nullable=True)
    is_reviewed = Column(Boolean, default=False)
    reviewed_at = Column(DateTime, nullable=True)
    reviewed_by = Column(Integer, nullable=True)
    review_notes = Column(Text, nullable=True)
    # Fulfillment lifecycle
    fulfillment_status = Column(String(30), default="pending")
    delivery_data = Column(JSON, nullable=True)
    invoice_number = Column(String(100), nullable=True)
    invoice_amount = Column(Numeric(12, 2), nullable=True)
    invoice_date = Column(String(50), nullable=True)
    payment_amount = Column(Numeric(12, 2), nullable=True)
    payment_date = Column(String(50), nullable=True)
    payment_reference = Column(String(200), nullable=True)
    attachments = Column(JSON, default=list)
    fulfillment_notes = Column(Text, nullable=True)
    delivery_environment = Column(JSON, nullable=True)        # 潮汐+天气+AI摘要
    template_id = Column(Integer, nullable=True)              # logical FK → v2_order_format_templates
    template_match_method = Column(String(30), nullable=True)  # keyword | fingerprint | manual
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)

    @property
    def has_inquiry(self) -> bool:
        return self.inquiry_data is not None


class AgentSession(Base):
    """Agent 对话会话 — 自由形式聊天，与订单解耦"""

    __tablename__ = "v2_agent_sessions"

    id = Column(String(36), primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    title = Column(String(500), default="新对话")
    status = Column(String(20), default="active")
    summary_message_id = Column(Integer, nullable=True)
    token_usage = Column(JSON, nullable=True)
    context_data = Column(JSON, nullable=True)       # referenced_order_ids, etc.
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = relationship("AgentMessage", back_populates="session",
                            cascade="all, delete-orphan", order_by="AgentMessage.sequence")


class AgentMessage(Base):
    """Agent 消息 — 对话历史记录"""

    __tablename__ = "v2_agent_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey("v2_agent_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    role = Column(String(15), nullable=False)
    msg_type = Column(String(20), default="text")
    content = Column(Text, nullable=False)
    meta = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("AgentSession", back_populates="messages")


class AgentTrace(Base):
    """Agent 执行轨迹 — LLM 调用和工具调用的记录"""

    __tablename__ = "v2_agent_traces"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey("v2_agent_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    turn_number = Column(Integer, nullable=False)
    event_type = Column(String(20), nullable=False)  # 'llm_call' | 'tool_call'
    model_name = Column(String(100), nullable=True)
    tool_name = Column(String(100), nullable=True)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    thinking_tokens = Column(Integer, default=0)
    tool_duration_ms = Column(Integer, nullable=True)
    tool_success = Column(Boolean, nullable=True)
    error_message = Column(Text, nullable=True)
    estimated_cost_usd = Column(Numeric(10, 6), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ToolConfig(Base):
    """AI 工具配置 — 控制 Chat Agent 可用工具的启用/禁用"""

    __tablename__ = "v2_tool_configs"

    id = Column(Integer, primary_key=True, index=True)
    tool_name = Column(String(100), unique=True, nullable=False)
    group_name = Column(String(50), default="default")
    display_name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    is_enabled = Column(Boolean, default=True)
    is_builtin = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UploadBatch(Base):
    """上传批次 — 每次文件上传创建一个 batch，暂存所有数据直到确认执行"""

    __tablename__ = "v2_upload_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('staging','validating','previewing','executing','completed','failed','rolled_back')",
            name="ck_v2_upload_batches_status",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(36), nullable=False, index=True)
    user_id = Column(Integer, nullable=False)
    file_name = Column(String(500), nullable=False)
    file_hash = Column(String(64), nullable=True)
    status = Column(String(20), default="staging")
    supplier_id = Column(Integer, nullable=True)
    supplier_name = Column(String(200), nullable=True)
    country_id = Column(Integer, nullable=True)
    country_name = Column(String(200), nullable=True)
    port_id = Column(Integer, nullable=True)
    port_name = Column(String(200), nullable=True)
    effective_from = Column(Date, nullable=True)
    effective_to = Column(Date, nullable=True)
    column_mapping = Column(JSON, nullable=True)
    summary = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    rolled_back_at = Column(DateTime, nullable=True)
    rolled_back_by = Column(Integer, nullable=True)

    staging_rows = relationship("StagingProduct", back_populates="batch", cascade="all, delete-orphan")
    changelog_entries = relationship("ProductChangeLog", back_populates="batch")


class StagingProduct(Base):
    """暂存产品行 — 解析后的每一行产品数据，验证后才写入正式表"""

    __tablename__ = "v2_staging_products"
    __table_args__ = (
        CheckConstraint(
            "validation_status IN ('pending','valid','invalid','quarantined')",
            name="ck_v2_staging_products_vstatus",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(Integer, ForeignKey("v2_upload_batches.id", ondelete="CASCADE"), nullable=False, index=True)
    row_number = Column(Integer, nullable=False)
    raw_data = Column(JSON, nullable=False)
    product_name = Column(String(200), nullable=True)
    product_code = Column(String(100), nullable=True)
    price = Column(Numeric(10, 2), nullable=True)
    unit = Column(String(50), nullable=True)
    pack_size = Column(String(100), nullable=True)
    brand = Column(String(100), nullable=True)
    currency = Column(String(20), nullable=True)
    country_of_origin = Column(String(100), nullable=True)
    validation_status = Column(String(20), default="pending")
    validation_errors = Column(JSON, nullable=True)
    match_result = Column(JSON, nullable=True)
    resolved_supplier_id = Column(Integer, nullable=True)
    resolved_country_id = Column(Integer, nullable=True)

    batch = relationship("UploadBatch", back_populates="staging_rows")


class ProductChangeLog(Base):
    """产品变更日志 — 记录每次产品创建/更新/回滚的详情"""

    __tablename__ = "v2_product_changelog"
    __table_args__ = (
        CheckConstraint(
            "change_type IN ('created','updated','rolled_back')",
            name="ck_v2_product_changelog_type",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, nullable=False, index=True)
    batch_id = Column(Integer, ForeignKey("v2_upload_batches.id"), nullable=False, index=True)
    change_type = Column(String(20), nullable=False)
    field_changes = Column(JSON, nullable=True)
    changed_at = Column(DateTime, default=datetime.utcnow)
    changed_by = Column(Integer, nullable=True)

    batch = relationship("UploadBatch", back_populates="changelog_entries")


class SkillConfig(Base):
    """AI 技能配置 — 可复用的 prompt 模板"""

    __tablename__ = "v2_skills"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    display_name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    content = Column(Text, nullable=True)
    is_builtin = Column(Boolean, default=True)
    is_enabled = Column(Boolean, default=True)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AgentMemory(Base):
    """Agent 长期记忆 — 跨会话知识存储（DeerFlow MemoryMiddleware 对齐）"""

    __tablename__ = "v2_agent_memories"
    __table_args__ = (
        UniqueConstraint("user_id", "memory_type", "key",
                         name="uq_agent_memories_user_key"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    memory_type = Column(String(30), nullable=False)  # user_preference, supplier_knowledge, workflow_pattern, fact
    key = Column(String(200), nullable=False)
    value = Column(Text, nullable=False)
    source_session_id = Column(String(36), nullable=True)
    access_count = Column(Integer, default=0)
    last_accessed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SubAgentTask(Base):
    """子Agent任务追踪 — 记录委派执行的状态和结果"""

    __tablename__ = "v2_sub_agent_tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'timeout')",
            name="ck_sub_agent_tasks_status",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    parent_session_id = Column(String(36), ForeignKey("v2_agent_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_turn = Column(Integer, nullable=True)
    sub_agent_name = Column(String(100), nullable=False)
    task_description = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    result_preview = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class AgentFeedback(Base):
    """Agent 反馈 — 用户对 agent 回复的评分和反馈"""

    __tablename__ = "v2_agent_feedback"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(36), ForeignKey("v2_agent_sessions.id", ondelete="CASCADE"), nullable=True, index=True)
    message_id = Column(Integer, nullable=True)
    rating = Column(Integer, nullable=True)
    feedback_text = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ExchangeRate(Base):
    """汇率 — 货币对汇率记录，支持手动录入和 API 获取"""

    __tablename__ = "v2_exchange_rates"
    __table_args__ = (
        UniqueConstraint("from_currency", "to_currency", "effective_date",
                         name="uq_exchange_rate_pair_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    from_currency = Column(String(3), nullable=False, index=True)
    to_currency = Column(String(3), nullable=False, index=True)
    rate = Column(Numeric(18, 8), nullable=False)  # 1 from = rate to
    effective_date = Column(Date, nullable=False, index=True)
    source = Column(String(50), default="manual")  # "manual" | "api"
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LineUser(Base):
    """LINE ユーザー — LINE user_id と内部 user の紐付け"""

    __tablename__ = "v2_line_users"

    id = Column(Integer, primary_key=True, index=True)
    line_user_id = Column(String(50), unique=True, nullable=False)
    user_id = Column(Integer, nullable=False, index=True)
    display_name = Column(String(200), nullable=True)
    active_session_id = Column(String(36), nullable=True)
    is_blocked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active_at = Column(DateTime, default=datetime.utcnow)
