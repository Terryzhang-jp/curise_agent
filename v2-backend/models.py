from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, JSON, Numeric, CheckConstraint, UniqueConstraint
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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# Backward compatibility alias
ProductReadOnly = Product


class SupplierTemplate(Base):
    """供应商模板 — 描述供应商询价单的填写位置"""

    __tablename__ = "v2_supplier_templates"

    id = Column(Integer, primary_key=True, index=True)
    supplier_id = Column(Integer, nullable=True)  # 逻辑关联, 不加 FK 约束
    country_id = Column(Integer, nullable=True)  # 逻辑关联到 countries 表
    template_name = Column(String(200), nullable=False)
    template_file_url = Column(String(500), nullable=True)
    field_positions = Column(JSON, nullable=True)  # {"po_number": {"position": "A4", "data_type": "string", "description": "PO番号"}, ...} or legacy {"po_number": "A4"}
    has_product_table = Column(Boolean, default=True)
    product_table_config = Column(JSON, nullable=True)  # {"start_row": 12, "columns": {"A": "product_code", ...}}
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Order(Base):
    """订单 — 独立业务实体，自动处理 PDF/Excel 订单"""

    __tablename__ = "v2_orders"
    __table_args__ = (
        CheckConstraint("total_amount >= 0", name="ck_v2_orders_total_amount_nonneg"),
        CheckConstraint("payment_amount >= 0", name="ck_v2_orders_payment_amount_nonneg"),
        CheckConstraint("invoice_amount >= 0", name="ck_v2_orders_invoice_amount_nonneg"),
        CheckConstraint(
            "status IN ('uploading','extracting','matching','ready','error')",
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
