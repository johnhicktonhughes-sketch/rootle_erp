from datetime import datetime

from database import db


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


class Company(db.Model, TimestampMixin):
    __tablename__ = "companies"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(256), nullable=False)
    domain = db.Column(db.String(256), unique=True)
    website = db.Column(db.String(512))
    industry = db.Column(db.String(128))
    status = db.Column(db.String(64), default="prospect", nullable=False)
    source = db.Column(db.String(64))
    crm_external_id = db.Column(db.String(128), unique=True)
    description = db.Column(db.Text)

    contacts = db.relationship(
        "Contact", back_populates="company", cascade="all, delete-orphan"
    )
    opportunities = db.relationship(
        "Opportunity", back_populates="company", cascade="all, delete-orphan"
    )
    website_events = db.relationship(
        "WebsiteEvent", back_populates="company", cascade="all, delete-orphan"
    )
    decisions = db.relationship(
        "OperationalDecision",
        back_populates="company",
        cascade="all, delete-orphan",
    )


class Contact(db.Model, TimestampMixin):
    __tablename__ = "contacts"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False)
    first_name = db.Column(db.String(128), nullable=False)
    last_name = db.Column(db.String(128))
    email = db.Column(db.String(256), nullable=False)
    phone = db.Column(db.String(64))
    role = db.Column(db.String(128))
    status = db.Column(db.String(64), default="active", nullable=False)
    crm_external_id = db.Column(db.String(128), unique=True)

    company = db.relationship("Company", back_populates="contacts")
    opportunities = db.relationship("Opportunity", back_populates="owner")


class Lead(db.Model, TimestampMixin):
    __tablename__ = "leads"

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(128), nullable=False)
    last_name = db.Column(db.String(128))
    phone = db.Column(db.String(64), nullable=False)
    email = db.Column(db.String(256))
    address_line_1 = db.Column(db.String(256))
    address_line_2 = db.Column(db.String(256))
    city = db.Column(db.String(128))
    postcode = db.Column(db.String(64))
    country = db.Column(db.String(128))
    stage = db.Column(db.String(64), default="stage-1", nullable=False)
    status = db.Column(db.String(64), default="open", nullable=False)
    source = db.Column(db.String(128))
    preferred_contact_method = db.Column(db.String(64))
    crm_system = db.Column(db.String(64), default="attio", nullable=False)
    crm_record_id = db.Column(db.String(128), unique=True)
    meta = db.Column(db.JSON)
    notes = db.Column(db.Text)

    box_details = db.relationship(
        "LeadBoxDetail", back_populates="lead", cascade="all, delete-orphan"
    )
    estimates = db.relationship(
        "LeadEstimate", back_populates="lead", cascade="all, delete-orphan"
    )


class LeadBoxDetail(db.Model, TimestampMixin):
    __tablename__ = "lead_box_details"

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("leads.id"), nullable=False)
    box_type = db.Column(db.String(128))
    condition = db.Column(db.String(128))
    item_description = db.Column(db.Text)
    photo_urls = db.Column(db.JSON)
    attachments = db.Column(db.JSON)
    notes = db.Column(db.Text)
    status = db.Column(db.String(64), default="submitted", nullable=False)
    source = db.Column(db.String(128))

    lead = db.relationship("Lead", back_populates="box_details")
    revisions = db.relationship(
        "LeadBoxRevision", back_populates="box_detail", cascade="all, delete-orphan"
    )
    estimates = db.relationship(
        "LeadEstimate", back_populates="box_detail", cascade="all, delete-orphan"
    )


class LeadBoxRevision(db.Model, TimestampMixin):
    __tablename__ = "lead_box_revisions"

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("leads.id"), nullable=False)
    box_detail_id = db.Column(db.Integer, db.ForeignKey("lead_box_details.id"), nullable=False)
    revision_type = db.Column(db.String(128), default="more_photos")
    additional_description = db.Column(db.Text)
    photo_urls = db.Column(db.JSON)
    attachments = db.Column(db.JSON)
    notes = db.Column(db.Text)
    status = db.Column(db.String(64), default="pending", nullable=False)

    lead = db.relationship("Lead")
    box_detail = db.relationship("LeadBoxDetail", back_populates="revisions")
    estimates = db.relationship(
        "LeadEstimate", back_populates="box_revision", cascade="all, delete-orphan"
    )


class LeadEstimate(db.Model, TimestampMixin):
    __tablename__ = "lead_estimates"

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("leads.id"), nullable=False)
    box_detail_id = db.Column(db.Integer, db.ForeignKey("lead_box_details.id"))
    box_revision_id = db.Column(db.Integer, db.ForeignKey("lead_box_revisions.id"))
    estimated_value = db.Column(db.Float, default=0.0)
    estimate_status = db.Column(db.String(64), default="pending", nullable=False)
    pricing_metadata = db.Column(db.JSON)
    accepted = db.Column(db.Boolean, default=False)
    expires_at = db.Column(db.DateTime)

    lead = db.relationship("Lead", back_populates="estimates")
    box_detail = db.relationship("LeadBoxDetail", back_populates="estimates")
    box_revision = db.relationship("LeadBoxRevision", back_populates="estimates")


class LeadValuation(db.Model, TimestampMixin):
    __tablename__ = "valuation_requests"

    id = db.Column(db.Integer, primary_key=True)
    crm_system = db.Column(db.String(64), default="attio", nullable=False)
    crm_person_record_id = db.Column(db.String(128), nullable=False, index=True)
    crm_valuation_request_id = db.Column(db.String(128), unique=True)
    rootle_request_id = db.Column(db.String(128), unique=True, nullable=False)
    posthog_distinct_id = db.Column(db.String(256))
    item_categories = db.Column(db.JSON, nullable=False)
    item_photo_url = db.Column(db.String(1024), nullable=False)
    valuation_guide_id = db.Column(db.String(128))
    valuation_guide_url = db.Column(db.String(1024))
    latest_mev_amount = db.Column(db.Numeric(12, 2))
    latest_mev_currency = db.Column(db.String(3))
    latest_mev_margin = db.Column(db.Numeric(7, 4))
    latest_mev_calculated_at = db.Column(db.DateTime)
    mev_low = db.Column(db.Numeric(12, 2))
    mev_high = db.Column(db.Numeric(12, 2))
    pricing_request_id = db.Column(db.String(128))
    pricing_status = db.Column(db.String(64), default="pricing_pending", nullable=False)
    status = db.Column(db.String(64), default="valuation_requested", nullable=False)
    current_stage = db.Column(db.String(64), default="item_submitted", nullable=False)
    source = db.Column(db.String(128))
    customer_email = db.Column(db.String(256))
    address_line_1 = db.Column(db.String(256))
    address_line_2 = db.Column(db.String(256))
    city = db.Column(db.String(128))
    postcode = db.Column(db.String(64))
    country = db.Column(db.String(128))
    item_submitted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    contact_details_received_at = db.Column(db.DateTime)
    stage_3_completed_at = db.Column(db.DateTime)
    meta = db.Column(db.JSON)

    mev_calculations = db.relationship(
        "LeadValuationMevCalculation",
        back_populates="valuation",
        cascade="all, delete-orphan",
        order_by="LeadValuationMevCalculation.calculated_at.desc()",
    )
    inbound_labels = db.relationship(
        "InboundLabel",
        back_populates="valuation",
        cascade="all, delete-orphan",
        order_by="InboundLabel.created_at.desc()",
    )
    postage_opportunities = db.relationship(
        "PostageOpportunity",
        back_populates="valuation",
        cascade="all, delete-orphan",
        order_by="PostageOpportunity.created_at.desc()",
    )


class FailedValuationRequestSubmission(db.Model, TimestampMixin):
    __tablename__ = "failed_valuation_request_submissions"

    id = db.Column(db.Integer, primary_key=True)
    rootle_request_id = db.Column(db.String(128), index=True)
    crm_person_record_id = db.Column(db.String(128), index=True)
    posthog_distinct_id = db.Column(db.String(256))
    payload = db.Column(db.JSON, nullable=False)
    normalised_payload = db.Column(db.JSON)
    error_type = db.Column(db.String(128), nullable=False)
    error_message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(64), default="pending_retry", nullable=False)
    retry_count = db.Column(db.Integer, default=0, nullable=False)
    last_retry_at = db.Column(db.DateTime)
    resolved_at = db.Column(db.DateTime)
    valuation_request_id = db.Column(db.Integer, db.ForeignKey("valuation_requests.id"))
    crm_valuation_request_id = db.Column(db.String(128))

    valuation_request = db.relationship("LeadValuation")


class LeadValuationMevCalculation(db.Model, TimestampMixin):
    __tablename__ = "lead_valuation_mev_calculations"

    id = db.Column(db.Integer, primary_key=True)
    lead_valuation_id = db.Column(
        db.Integer,
        db.ForeignKey("valuation_requests.id"),
        nullable=False,
        index=True,
    )
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    margin = db.Column(db.Numeric(7, 4), nullable=False)
    mev_low = db.Column(db.Numeric(12, 2))
    mev_high = db.Column(db.Numeric(12, 2))
    pricing_request_id = db.Column(db.String(128))
    calculation_method = db.Column(db.String(128))
    calculated_by = db.Column(db.String(128))
    calculated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    notes = db.Column(db.Text)
    inputs = db.Column(db.JSON)
    meta = db.Column(db.JSON)

    valuation = db.relationship("LeadValuation", back_populates="mev_calculations")


class InboundLabel(db.Model, TimestampMixin):
    __tablename__ = "inbound_labels"

    id = db.Column(db.Integer, primary_key=True)
    rootle_label_id = db.Column(db.String(128), unique=True, nullable=False)
    lead_valuation_id = db.Column(
        db.Integer,
        db.ForeignKey("valuation_requests.id"),
        nullable=False,
        index=True,
    )
    crm_person_record_id = db.Column(db.String(128), nullable=False, index=True)
    crm_valuation_request_id = db.Column(db.String(128), index=True)
    rootle_request_id = db.Column(db.String(128), nullable=False, index=True)
    status = db.Column(db.String(64), default="label_requested", nullable=False)
    dispatch_method = db.Column(db.String(64), default="email", nullable=False)
    courier = db.Column(db.String(128))
    service_level = db.Column(db.String(128))
    tracking_number = db.Column(db.String(128), unique=True)
    label_url = db.Column(db.String(1024))
    barcode_value = db.Column(db.String(256), unique=True, nullable=False)
    qr_payload = db.Column(db.String(1024), nullable=False)
    destination_country = db.Column(db.String(128))
    currency = db.Column(db.String(3))
    mev_amount = db.Column(db.Numeric(12, 2))
    white_glove_required = db.Column(db.Boolean, default=False, nullable=False)
    requested_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    generated_at = db.Column(db.DateTime)
    sent_at = db.Column(db.DateTime)
    used_at = db.Column(db.DateTime)
    received_at = db.Column(db.DateTime)
    expires_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)
    meta = db.Column(db.JSON)

    valuation = db.relationship("LeadValuation", back_populates="inbound_labels")


class PostageOpportunity(db.Model, TimestampMixin):
    __tablename__ = "postage_opportunities"

    id = db.Column(db.Integer, primary_key=True)
    lead_valuation_id = db.Column(
        db.Integer,
        db.ForeignKey("valuation_requests.id"),
        nullable=False,
        index=True,
    )
    crm_person_record_id = db.Column(db.String(128), nullable=False, index=True)
    crm_valuation_request_id = db.Column(db.String(128), nullable=False, index=True)
    crm_postage_opportunity_id = db.Column(db.String(128), unique=True, nullable=False)
    rootle_request_id = db.Column(db.String(128), nullable=False, index=True)
    rootle_postage_opportunity_id = db.Column(db.String(128), unique=True, nullable=False)
    barcode_value = db.Column(db.String(256), unique=True, nullable=False)
    qr_payload = db.Column(db.String(1024), nullable=False)
    status = db.Column(db.String(64), default="created", nullable=False)
    triggered_by = db.Column(db.String(128))
    triggered_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    notes = db.Column(db.Text)
    meta = db.Column(db.JSON)

    valuation = db.relationship("LeadValuation", back_populates="postage_opportunities")


class ValuationItemCategory(db.Model, TimestampMixin):
    __tablename__ = "valuation_item_categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    label = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)


class JourneyPhase(db.Model, TimestampMixin):
    __tablename__ = "journey_phases"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text)
    color = db.Column(db.String(16), default="#cccccc")
    order = db.Column(db.Integer, nullable=False, default=0)

    decisions = db.relationship(
        "OperationalDecision", back_populates="phase", cascade="all, delete-orphan"
    )


class OperationalDecision(db.Model, TimestampMixin):
    __tablename__ = "operational_decisions"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False)
    opportunity_id = db.Column(db.Integer, db.ForeignKey("opportunities.id"))
    phase_id = db.Column(db.Integer, db.ForeignKey("journey_phases.id"))
    name = db.Column(db.String(128), nullable=False)
    decision_type = db.Column(db.String(64))
    result = db.Column(db.Text)
    meta = db.Column(db.JSON)
    status = db.Column(db.String(64), default="pending", nullable=False)

    company = db.relationship("Company", back_populates="decisions")
    phase = db.relationship("JourneyPhase", back_populates="decisions")
    opportunity = db.relationship("Opportunity", back_populates="decisions")


class Opportunity(db.Model, TimestampMixin):
    __tablename__ = "opportunities"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey("contacts.id"))
    title = db.Column(db.String(256), nullable=False)
    value = db.Column(db.Float, default=0.0)
    probability = db.Column(db.Float, default=0.0)
    stage = db.Column(db.String(128), default="qualification")
    source = db.Column(db.String(128))
    status = db.Column(db.String(64), default="open", nullable=False)

    company = db.relationship("Company", back_populates="opportunities")
    owner = db.relationship("Contact", back_populates="opportunities")
    decisions = db.relationship(
        "OperationalDecision", back_populates="opportunity", cascade="all, delete-orphan"
    )
    quotes = db.relationship("Quote", back_populates="opportunity", cascade="all, delete-orphan")


class Product(db.Model, TimestampMixin):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    sku = db.Column(db.String(128), unique=True, nullable=False)
    name = db.Column(db.String(256), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(128))
    list_price = db.Column(db.Float, default=0.0)
    cost_price = db.Column(db.Float, default=0.0)
    active = db.Column(db.Boolean, default=True)

    quote_items = db.relationship("QuoteItem", back_populates="product")


class Quote(db.Model, TimestampMixin):
    __tablename__ = "quotes"

    id = db.Column(db.Integer, primary_key=True)
    opportunity_id = db.Column(db.Integer, db.ForeignKey("opportunities.id"), nullable=False)
    quote_number = db.Column(db.String(128), unique=True, nullable=False)
    total_value = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(64), default="draft", nullable=False)
    expires_at = db.Column(db.DateTime)

    opportunity = db.relationship("Opportunity", back_populates="quotes")
    items = db.relationship("QuoteItem", back_populates="quote", cascade="all, delete-orphan")


class QuoteItem(db.Model, TimestampMixin):
    __tablename__ = "quote_items"

    id = db.Column(db.Integer, primary_key=True)
    quote_id = db.Column(db.Integer, db.ForeignKey("quotes.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    unit_price = db.Column(db.Float, default=0.0)
    total_price = db.Column(db.Float, default=0.0)

    quote = db.relationship("Quote", back_populates="items")
    product = db.relationship("Product", back_populates="quote_items")


class Order(db.Model, TimestampMixin):
    __tablename__ = "orders"

    id = db.Column(db.Integer, primary_key=True)
    quote_id = db.Column(db.Integer, db.ForeignKey("quotes.id"), nullable=False)
    order_number = db.Column(db.String(128), unique=True, nullable=False)
    amount = db.Column(db.Float, default=0.0)
    currency = db.Column(db.String(8), default="USD")
    status = db.Column(db.String(64), default="pending", nullable=False)
    placed_at = db.Column(db.DateTime)

    quote = db.relationship("Quote")


class WebsiteEvent(db.Model, TimestampMixin):
    __tablename__ = "website_events"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False)
    event_type = db.Column(db.String(128), nullable=False)
    page = db.Column(db.String(512))
    meta = db.Column(db.JSON)
    captured_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    company = db.relationship("Company", back_populates="website_events")


class SlackMessage(db.Model, TimestampMixin):
    __tablename__ = "slack_messages"

    id = db.Column(db.Integer, primary_key=True)
    external_id = db.Column(db.String(256), unique=True)
    channel = db.Column(db.String(128), nullable=False)
    user = db.Column(db.String(128))
    text = db.Column(db.Text)
    event_type = db.Column(db.String(64), default="message")
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    meta = db.Column(db.JSON)


class IntegrationLog(db.Model, TimestampMixin):
    __tablename__ = "integration_logs"

    id = db.Column(db.Integer, primary_key=True)
    system = db.Column(db.String(128), nullable=False)
    entity_type = db.Column(db.String(128), nullable=False)
    external_id = db.Column(db.String(256))
    payload = db.Column(db.JSON)
    status = db.Column(db.String(64), default="pending", nullable=False)
    processed_at = db.Column(db.DateTime)
