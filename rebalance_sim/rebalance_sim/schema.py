"""Entity definitions: single source of truth for CSV headers, SQL DDL and the data dictionary."""
from dataclasses import dataclass, field
from typing import List, Tuple, Union

RISK_PROFILES = ["CONSERVATIVE", "MODERATE", "BALANCED", "GROWTH", "AGGRESSIVE"]
ASSET_CLASSES = ["EQUITY", "FIXED_INCOME", "REAL_ASSETS", "CASH"]
NON_CASH = ["EQUITY", "FIXED_INCOME", "REAL_ASSETS"]
LIQUIDITY_TIERS = ["HIGH", "MEDIUM", "LOW"]
PORTFOLIO_STATUS = ["ACTIVE", "FROZEN", "CLOSED"]
PROPOSAL_STATUS = ["DRAFT", "PENDING_OPS_REVIEW", "PENDING_COMPLIANCE_REVIEW", "APPROVED", "REJECTED",
                   "CUSTOMER_ACCEPTED", "EXECUTED_SIMULATED", "EXPIRED", "BLOCKED"]
TRADE_STATUS = ["PROPOSED", "APPROVED", "REJECTED", "EXPIRED", "EXECUTED_SIMULATED"]
ACTOR_ROLES = ["SYSTEM", "CUSTOMER", "OPS_ANALYST", "RISK_COMPLIANCE", "SYSTEM_ADMIN"]
TRANSITIONS = {
    None: {"DRAFT"},
    "DRAFT": {"PENDING_OPS_REVIEW", "BLOCKED"},
    "PENDING_OPS_REVIEW": {"PENDING_COMPLIANCE_REVIEW", "APPROVED", "REJECTED"},
    "PENDING_COMPLIANCE_REVIEW": {"APPROVED", "REJECTED"},
    "APPROVED": {"CUSTOMER_ACCEPTED", "EXPIRED"},
    "CUSTOMER_ACCEPTED": {"EXECUTED_SIMULATED"},
    "REJECTED": set(), "EXPIRED": set(), "EXECUTED_SIMULATED": set(), "BLOCKED": set(),
}
TRADE_STATUS_FROM_PROPOSAL = {
    "PENDING_COMPLIANCE_REVIEW": "PROPOSED", "APPROVED": "APPROVED", "REJECTED": "REJECTED",
    "EXPIRED": "EXPIRED", "EXECUTED_SIMULATED": "EXECUTED_SIMULATED",
}
ISSUE_TYPES = ["TARGET_WEIGHTS_NOT_100", "TRADE_EXCEEDS_HOLDING", "EXCLUDED_INSTRUMENT_RECOMMENDED",
               "FEE_OMITTED", "STALE_PRICE_UNFLAGGED"]


@dataclass
class Field:
    name: str
    type: str                      # TEXT INTEGER REAL DATE TIMESTAMP BOOLEAN
    required: bool = True
    allowed: Union[list, str] = ""  # list => enum (CHECK constraint); str => free-text range / format
    unit: str = ""
    unique: bool = False
    rule: str = ""


def F(name, type_, req=True, allowed="", unit="", uniq=False, rule=""):
    return Field(name, type_, req, allowed, unit, uniq, rule)


@dataclass
class Entity:
    name: str
    table: str
    pk: List[str]
    description: str
    fields: List[Field]
    fks: List[Tuple[str, str, str]] = field(default_factory=list)
    unique_keys: List[List[str]] = field(default_factory=list)
    cardinality: str = ""
    lifecycle: str = ""
    core: bool = True

    @property
    def file(self):
        return f"{self.table}.csv"


COUNTRIES = ["US", "GB", "IN", "SG", "DE", "AE"]

ENTITIES: List[Entity] = [
    Entity("InvestorProfile", "investor_profile", ["investor_id"],
           "Synthetic account holder with a risk profile. No personal data: no names or contact details.",
           [F("investor_id", "TEXT", uniq=True, allowed="INV-NNNNNN", rule="Zero-padded sequential, immutable"),
            F("risk_profile", "TEXT", allowed=RISK_PROFILES, rule="Drawn from age-conditioned weights; drives target model and minimum cash"),
            F("risk_score", "INTEGER", allowed="1..100", unit="points",
              rule="Derived: base(profile)+round((50-age)/5)+round(min(horizon,30)/6), clamped"),
            F("age", "INTEGER", allowed="21..80", unit="years"),
            F("investment_horizon_years", "INTEGER", allowed="1..40", unit="years"),
            F("annual_income_band", "TEXT", allowed=["LOW", "MIDDLE", "UPPER", "HIGH"]),
            F("country", "TEXT", allowed=COUNTRIES),
            F("base_currency", "TEXT", allowed=["USD"], rule="Single-currency simulation"),
            F("kyc_status", "TEXT", allowed=["VERIFIED", "PENDING", "EXPIRED"],
              rule="EXPIRED freezes the investor's portfolios; PENDING blocks customer acceptance"),
            F("kyc_expiry_date", "DATE", rule="< as_of_date if and only if kyc_status = EXPIRED"),
            F("created_date", "DATE", rule="Earlier than every portfolio inception_date"),
            F("status", "TEXT", allowed=["ACTIVE", "SUSPENDED"])],
           cardinality="InvestorProfile 1:N Portfolio (about 10% of investors own two portfolios)",
           lifecycle="ACTIVE <-> SUSPENDED (static in this snapshot)"),
    Entity("Portfolio", "portfolio", ["portfolio_id"],
           "An investment account owned by one investor.",
           [F("portfolio_id", "TEXT", uniq=True, allowed="PORT-<investor-id>-NN", rule="PORT-INV-000001-01; NN is portfolio_seq"),
            F("investor_id", "TEXT", rule="FK -> investor_profile.investor_id"),
            F("portfolio_seq", "INTEGER", allowed="1..9", rule="Matches the NN suffix of portfolio_id"),
            F("portfolio_name", "TEXT"),
            F("base_currency", "TEXT", allowed=["USD"]),
            F("inception_date", "DATE", rule="After investor created_date, at least 180 days before as_of_date"),
            F("status", "TEXT", allowed=PORTFOLIO_STATUS, rule="FROZEN if and only if the investor's kyc_status = EXPIRED"),
            F("status_reason", "TEXT", req=False, allowed=["KYC_EXPIRED"], rule="Required when status = FROZEN")],
           fks=[("investor_id", "investor_profile", "investor_id")],
           cardinality="Portfolio 1:N Holding, 1:N TargetAllocation, 1:N RebalanceProposal, N:M Constraint (bridge)",
           lifecycle="ACTIVE -> FROZEN (KYC expiry) -> CLOSED"),
    Entity("Instrument", "instrument", ["instrument_id"],
           "Tradable synthetic fund/security. All names are fictional.",
           [F("instrument_id", "TEXT", uniq=True, allowed="INS-NNNNNN"),
            F("ticker", "TEXT", uniq=True, rule="Synthetic, e.g. EQ0001"),
            F("instrument_name", "TEXT"),
            F("asset_class", "TEXT", allowed=ASSET_CLASSES),
            F("sub_class", "TEXT", rule="Sub-bucket inside asset_class"),
            F("currency", "TEXT", allowed=["USD"]),
            F("liquidity_tier", "TEXT", allowed=LIQUIDITY_TIERS, rule="Selects the MAX_PCT_ADV constraint"),
            F("avg_daily_volume_units", "INTEGER", unit="units/day", allowed=">0"),
            F("lot_size", "REAL", unit="units", allowed=">0", rule="Trade quantity must be a multiple (0.01 for cash)"),
            F("is_excluded", "BOOLEAN", rule="True => firm-wide EXCLUDED_INSTRUMENT constraint exists; BUY forbidden, SELL allowed"),
            F("exclusion_reason", "TEXT", req=False, allowed=["RESTRICTED_LIST", "SANCTIONS_SCREEN", "INTERNAL_POLICY"],
              rule="Required iff is_excluded"),
            F("listing_date", "DATE", rule="Before first price_date"),
            F("status", "TEXT", allowed=["ACTIVE", "SUSPENDED", "DELISTED"])],
           unique_keys=[["ticker"]],
           cardinality="Instrument 1:N MarketPrice; Portfolio N:M Instrument via Holding (bridge)",
           lifecycle="ACTIVE -> SUSPENDED -> DELISTED"),
    Entity("MarketPrice", "market_price", ["price_id"],
           "Daily close per instrument. Missing days stay as explicit MISSING rows (never silently dropped).",
           [F("price_id", "TEXT", uniq=True, allowed="PX-<instrument-id>-YYYYMMDD"),
            F("instrument_id", "TEXT", rule="FK -> instrument.instrument_id"),
            F("price_date", "DATE", rule="Weekday; 250 consecutive trading days ending at as_of_date"),
            F("close_price", "REAL", req=False, unit="USD", allowed=">0", rule="Null if and only if price_status = MISSING"),
            F("price_status", "TEXT", allowed=["OBSERVED", "MISSING"]),
            F("source", "TEXT", allowed=["SYNTHETIC_GBM"], rule="Correlated geometric random walk, fixed seed")],
           fks=[("instrument_id", "instrument", "instrument_id")],
           unique_keys=[["instrument_id", "price_date"]],
           cardinality="MarketPrice N:1 Instrument; unique per (instrument_id, price_date)",
           lifecycle="Append-only: history is never overwritten"),
    Entity("Holding", "holding", ["holding_id"],
           "Position snapshot at as_of_date. Valuation columns are derived from quantity and MarketPrice.",
           [F("holding_id", "TEXT", uniq=True, allowed="HOLD-<portfolio-id>-<instrument-id>"),
            F("portfolio_id", "TEXT", rule="FK -> portfolio.portfolio_id"),
            F("instrument_id", "TEXT", rule="FK -> instrument.instrument_id"),
            F("as_of_date", "DATE"),
            F("quantity", "REAL", unit="units (USD for cash)", allowed=">0"),
            F("avg_cost_per_unit", "REAL", unit="USD", allowed=">0"),
            F("acquired_date", "DATE", rule="Between portfolio inception_date and as_of_date"),
            F("price_used", "REAL", unit="USD", rule="Last OBSERVED close on or before as_of_date"),
            F("price_date_used", "DATE", rule="Date of price_used"),
            F("price_age_days", "INTEGER", unit="trading days", rule="Trading days between price_date_used and as_of_date"),
            F("stale_price_flag", "BOOLEAN", rule="price_age_days > stale_days_threshold (3)"),
            F("market_value", "REAL", unit="USD", rule="round(quantity * price_used, 2)"),
            F("current_weight_pct", "REAL", unit="% of portfolio", rule="market_value / sum(market_value of portfolio) * 100"),
            F("status", "TEXT", allowed=["ACTIVE", "CLOSED"])],
           fks=[("portfolio_id", "portfolio", "portfolio_id"), ("instrument_id", "instrument", "instrument_id")],
           unique_keys=[["portfolio_id", "instrument_id"]],
           cardinality="Bridge for Portfolio N:M Instrument; one row per (portfolio, instrument)",
           lifecycle="Snapshot; post-trade holdings are simulated in post_trade_allocation, never overwritten"),
    Entity("TargetAllocation", "target_allocation", ["target_id"],
           "Target weight per asset class per portfolio, effective-dated and versioned.",
           [F("target_id", "TEXT", uniq=True, allowed="TGT-<portfolio-id>-<asset_class>-V<n>"),
            F("portfolio_id", "TEXT", rule="FK -> portfolio.portfolio_id"),
            F("asset_class", "TEXT", allowed=ASSET_CLASSES),
            F("target_weight_pct", "REAL", unit="% of portfolio", allowed="0..100",
              rule="Weights of the ACTIVE version must sum to 100 (violations are labelled anomalies)"),
            F("tolerance_band_pct", "REAL", unit="percentage points", allowed=">0",
              rule="Rebalance trigger: abs(current - target) > band"),
            F("version", "INTEGER", allowed=">=1"),
            F("effective_from", "DATE"),
            F("effective_to", "DATE", req=False, rule="Null while ACTIVE; >= effective_from; earlier than next version's effective_from"),
            F("status", "TEXT", allowed=["ACTIVE", "SUPERSEDED"])],
           fks=[("portfolio_id", "portfolio", "portfolio_id")],
           unique_keys=[["portfolio_id", "asset_class", "version"]],
           cardinality="Portfolio 1:N TargetAllocation (4 asset classes x versions)",
           lifecycle="ACTIVE -> SUPERSEDED when a new version takes over"),
    Entity("FeeSchedule", "fee_schedule", ["fee_schedule_id"],
           "Tiered commission by asset class and trade notional, effective-dated.",
           [F("fee_schedule_id", "TEXT", uniq=True, allowed="FEE-NNNNNN"),
            F("asset_class", "TEXT", allowed=ASSET_CLASSES),
            F("tier", "TEXT", allowed=["TIER_1", "TIER_2", "TIER_3"]),
            F("min_notional", "REAL", unit="USD", rule="Inclusive lower bound; tiers contiguous"),
            F("max_notional", "REAL", unit="USD", rule="Exclusive upper bound"),
            F("commission_bps", "REAL", unit="bps of notional"),
            F("flat_fee", "REAL", unit="USD"),
            F("min_fee", "REAL", unit="USD"),
            F("fee_version", "INTEGER", allowed=">=1"),
            F("effective_from", "DATE"),
            F("effective_to", "DATE", req=False),
            F("status", "TEXT", allowed=["ACTIVE", "SUPERSEDED"]),
            F("created_by", "TEXT", allowed="USR-ADM-NNN", rule="System administrator who published the row")],
           unique_keys=[["asset_class", "tier", "fee_version"]],
           cardinality="FeeSchedule 1:N Trade (optional: omitted fee => null)",
           lifecycle="ACTIVE -> SUPERSEDED; fee = max(min_fee, flat_fee + notional * bps / 10000)"),
    Entity("Constraint", "constraint", ["constraint_id"],
           "Policy rule. ALL_PORTFOLIOS rules apply everywhere; LISTED_PORTFOLIOS rules apply via portfolio_constraint.",
           [F("constraint_id", "TEXT", uniq=True, allowed="CON-NNNNNN"),
            F("constraint_type", "TEXT", allowed=["MIN_TRADE_VALUE", "MAX_TURNOVER_PCT", "MAX_PCT_ADV",
                                                  "EXCLUDED_INSTRUMENT", "MIN_CASH_PCT"]),
            F("scope_type", "TEXT", allowed=["GLOBAL", "ASSET_CLASS", "LIQUIDITY_TIER", "INSTRUMENT", "RISK_PROFILE"]),
            F("scope_id", "TEXT", req=False, rule="Asset class, tier, instrument_id or risk profile; null for GLOBAL"),
            F("applies_to", "TEXT", allowed=["ALL_PORTFOLIOS", "LISTED_PORTFOLIOS"]),
            F("value", "REAL", req=False, rule="Threshold; null for EXCLUDED_INSTRUMENT"),
            F("unit", "TEXT", allowed=["USD", "PCT_OF_PORTFOLIO", "PCT_OF_ADV", "NONE"]),
            F("severity", "TEXT", allowed=["HARD"]),
            F("description", "TEXT"),
            F("effective_from", "DATE"),
            F("effective_to", "DATE", req=False),
            F("status", "TEXT", allowed=["ACTIVE", "RETIRED"]),
            F("created_by", "TEXT", allowed="USR-ADM-NNN")],
           cardinality="Constraint N:M Portfolio via portfolio_constraint",
           lifecycle="ACTIVE -> RETIRED"),
    Entity("PortfolioConstraint", "portfolio_constraint", ["portfolio_constraint_id"],
           "Bridge table for Portfolio N:M Constraint (LISTED_PORTFOLIOS rules only).",
           [F("portfolio_constraint_id", "TEXT", uniq=True, allowed="PC-NNNNNN"),
            F("portfolio_id", "TEXT", rule="FK -> portfolio.portfolio_id"),
            F("constraint_id", "TEXT", rule="FK -> constraint.constraint_id"),
            F("effective_from", "DATE", rule=">= portfolio inception_date"),
            F("effective_to", "DATE", req=False)],
           fks=[("portfolio_id", "portfolio", "portfolio_id"), ("constraint_id", "constraint", "constraint_id")],
           unique_keys=[["portfolio_id", "constraint_id"]],
           core=False, cardinality="Bridge (N:M)", lifecycle="Effective-dated"),
    Entity("RebalanceProposal", "rebalance_proposal", ["proposal_id"],
           "System-generated rebalancing recommendation. Aggregates are derived from Trade and Holding rows.",
           [F("proposal_id", "TEXT", uniq=True, allowed="RB-YYYY-NNNNNN"),
            F("portfolio_id", "TEXT", rule="FK -> portfolio.portfolio_id"),
            F("as_of_date", "DATE"),
            F("generated_at", "TIMESTAMP", rule="UTC ISO-8601"),
            F("trigger_reason", "TEXT", allowed=["DRIFT_BREACH", "PORTFOLIO_FROZEN"]),
            F("status", "TEXT", allowed=PROPOSAL_STATUS, rule="Equals the to_status of the latest proposal_event"),
            F("policy_version", "TEXT", allowed=["POLICY-2026.10"]),
            F("target_weight_sum_pct", "REAL", unit="%", rule="Sum of ACTIVE target weights (should be 100)"),
            F("portfolio_value", "REAL", unit="USD", rule="Sum of holding market_value"),
            F("post_trade_value", "REAL", unit="USD", rule="Recomputed from post-trade holdings x prices (fees leave the portfolio)"),
            F("pre_max_abs_drift_pct", "REAL", unit="percentage points"),
            F("post_max_abs_drift_pct", "REAL", unit="percentage points"),
            F("drift_reduction_pct", "REAL", unit="%", rule="(pre - post) / pre * 100"),
            F("num_trades", "INTEGER", allowed=">=0", rule="Count of Trade rows"),
            F("total_buy_value", "REAL", unit="USD", rule="Sum of BUY notional"),
            F("total_sell_value", "REAL", unit="USD", rule="Sum of SELL notional"),
            F("total_estimated_fees", "REAL", unit="USD", rule="Sum of trade estimated_fee (null counted as 0)"),
            F("turnover_pct", "REAL", unit="% of portfolio", rule="(buys + sells) / 2 / portfolio_value * 100"),
            F("cash_after", "REAL", unit="USD", rule="Post-trade value of the CASH class"),
            F("min_cash_required", "REAL", unit="USD", rule="MIN_CASH_PCT constraint x portfolio_value"),
            F("price_stale_count", "INTEGER", rule="Trades with stale_price_flag = true"),
            F("liquidity_capped_count", "INTEGER", rule="Trades reduced by the MAX_PCT_ADV cap"),
            F("suppressed_trade_count", "INTEGER", rule="Candidate trades dropped for MIN_TRADE_VALUE"),
            F("requires_compliance_review", "BOOLEAN", rule="True if review_reasons is not empty"),
            F("review_reasons", "TEXT", req=False,
              rule="Pipe-separated: STALE_PRICE|LIQUIDITY_CAP|HIGH_NOTIONAL|HIGH_TURNOVER|NO_ELIGIBLE_BUY_INSTRUMENT")],
           fks=[("portfolio_id", "portfolio", "portfolio_id")],
           cardinality="Portfolio 1:N RebalanceProposal; RebalanceProposal 1:N Trade; 1:N ProposalEvent; 1:4 PostTradeAllocation",
           lifecycle="DRAFT -> PENDING_OPS_REVIEW -> [PENDING_COMPLIANCE_REVIEW] -> APPROVED|REJECTED -> CUSTOMER_ACCEPTED|EXPIRED -> EXECUTED_SIMULATED; DRAFT -> BLOCKED"),
    Entity("Trade", "trade", ["trade_id"],
           "Recommended trade within a proposal. Cash is the residual and is never traded.",
           [F("trade_id", "TEXT", uniq=True, allowed="TRD-<proposal-id>-NN"),
            F("proposal_id", "TEXT", rule="FK -> rebalance_proposal.proposal_id"),
            F("portfolio_id", "TEXT", rule="FK -> portfolio.portfolio_id; equals the proposal's portfolio"),
            F("instrument_id", "TEXT", rule="FK -> instrument.instrument_id"),
            F("side", "TEXT", allowed=["BUY", "SELL"]),
            F("quantity", "REAL", unit="units", allowed=">0", rule="Multiple of lot_size; SELL <= holding quantity"),
            F("holding_quantity_before", "REAL", unit="units", rule="Quantity in the Holding table (0 if not held)"),
            F("price_used", "REAL", unit="USD"),
            F("price_date_used", "DATE", rule="<= as_of_date"),
            F("price_age_days", "INTEGER", unit="trading days"),
            F("stale_price_flag", "BOOLEAN", rule="Must be true when price_age_days > 3"),
            F("notional", "REAL", unit="USD", rule="round(quantity * price_used, 2)"),
            F("fee_schedule_id", "TEXT", req=False, rule="FK -> fee_schedule; null only for omitted-fee anomalies"),
            F("estimated_fee", "REAL", req=False, unit="USD", rule="From FeeSchedule tier; null = omitted"),
            F("liquidity_cap_applied", "BOOLEAN", rule="Quantity reduced by MAX_PCT_ADV"),
            F("trade_status", "TEXT", allowed=TRADE_STATUS, rule="Mapped from the proposal's final status")],
           fks=[("proposal_id", "rebalance_proposal", "proposal_id"), ("portfolio_id", "portfolio", "portfolio_id"),
                ("instrument_id", "instrument", "instrument_id"), ("fee_schedule_id", "fee_schedule", "fee_schedule_id")],
           cardinality="RebalanceProposal 1:N Trade; Trade N:1 Instrument; Trade N:1 FeeSchedule (optional)",
           lifecycle="PROPOSED -> APPROVED|REJECTED -> EXECUTED_SIMULATED|EXPIRED"),
    Entity("ProposalEvent", "proposal_event", ["event_id"],
           "Append-only state-change history for each proposal (nothing is overwritten).",
           [F("event_id", "TEXT", uniq=True, allowed="EVT-NNNNNN"),
            F("proposal_id", "TEXT", rule="FK -> rebalance_proposal.proposal_id"),
            F("event_ts", "TIMESTAMP", rule="Non-decreasing per proposal"),
            F("from_status", "TEXT", req=False, allowed=PROPOSAL_STATUS, rule="Null only for the first event"),
            F("to_status", "TEXT", allowed=PROPOSAL_STATUS, rule="Pair must be in TRANSITIONS"),
            F("actor_role", "TEXT", allowed=ACTOR_ROLES),
            F("actor_id", "TEXT", rule="SYSTEM, USR-OPS-NNN, USR-CMP-NNN or an investor_id"),
            F("reason_code", "TEXT", rule="Rule that produced the transition")],
           fks=[("proposal_id", "rebalance_proposal", "proposal_id")],
           core=False, cardinality="RebalanceProposal 1:N ProposalEvent", lifecycle="Append-only"),
    Entity("DriftSnapshot", "drift_snapshot", ["snapshot_id"],
           "Current weight vs target per portfolio and asset class (the drift calculation made visible).",
           [F("snapshot_id", "TEXT", uniq=True, allowed="SNAP-<portfolio-id>-<asset_class>"),
            F("portfolio_id", "TEXT", rule="FK -> portfolio.portfolio_id"),
            F("as_of_date", "DATE"),
            F("asset_class", "TEXT", allowed=ASSET_CLASSES),
            F("current_value", "REAL", unit="USD", rule="Sum of holding market_value in the class"),
            F("current_weight_pct", "REAL", unit="%"),
            F("target_weight_pct", "REAL", unit="%", rule="ACTIVE target"),
            F("drift_pct", "REAL", unit="percentage points", rule="current - target"),
            F("tolerance_band_pct", "REAL", unit="percentage points"),
            F("breach_flag", "BOOLEAN", rule="abs(drift_pct) > tolerance_band_pct")],
           fks=[("portfolio_id", "portfolio", "portfolio_id")],
           unique_keys=[["portfolio_id", "asset_class"]],
           core=False, cardinality="Portfolio 1:N DriftSnapshot (4 per portfolio)"),
    Entity("PostTradeAllocation", "post_trade_allocation", ["post_alloc_id"],
           "Simulated allocation after a proposal, recomputed from holdings, trades and prices.",
           [F("post_alloc_id", "TEXT", uniq=True, allowed="PTA-<proposal-id>-<asset_class>"),
            F("proposal_id", "TEXT", rule="FK -> rebalance_proposal.proposal_id"),
            F("asset_class", "TEXT", allowed=ASSET_CLASSES),
            F("pre_weight_pct", "REAL", unit="%"),
            F("post_weight_pct", "REAL", unit="%", rule="Sums to 100 per proposal"),
            F("target_weight_pct", "REAL", unit="%"),
            F("pre_drift_pct", "REAL", unit="percentage points"),
            F("post_drift_pct", "REAL", unit="percentage points"),
            F("post_value", "REAL", unit="USD")],
           fks=[("proposal_id", "rebalance_proposal", "proposal_id")],
           unique_keys=[["proposal_id", "asset_class"]],
           core=False, cardinality="RebalanceProposal 1:N PostTradeAllocation (4 per proposal)"),
]

ENTITY_BY_TABLE = {e.table: e for e in ENTITIES}

ID_PATTERNS = {
    "investor_profile": {"investor_id": r"INV-\d{6}"},
    "portfolio": {"portfolio_id": r"PORT-INV-\d{6}-\d{2}"},
    "instrument": {"instrument_id": r"INS-\d{6}"},
    "market_price": {"price_id": r"PX-INS-\d{6}-\d{8}"},
    "holding": {"holding_id": r"HOLD-PORT-INV-\d{6}-\d{2}-INS-\d{6}"},
    "fee_schedule": {"fee_schedule_id": r"FEE-\d{6}"},
    "constraint": {"constraint_id": r"CON-\d{6}"},
    "portfolio_constraint": {"portfolio_constraint_id": r"PC-\d{6}"},
    "rebalance_proposal": {"proposal_id": r"RB-\d{4}-\d{6}"},
    "trade": {"trade_id": r"TRD-RB-\d{4}-\d{6}-\d{2}"},
    "proposal_event": {"event_id": r"EVT-\d{6}"},
}

RELATIONSHIPS = [
    ("InvestorProfile", "Portfolio", "1:N", "A portfolio needs exactly one investor; an investor has 1-2 portfolios"),
    ("Portfolio", "Holding", "1:N", "Every portfolio holds at least one position in each of the 4 asset classes"),
    ("Instrument", "Holding", "1:N", "Holding is the bridge giving Portfolio N:M Instrument"),
    ("Instrument", "MarketPrice", "1:N", "One row per instrument per trading day (MISSING rows are explicit)"),
    ("Portfolio", "TargetAllocation", "1:N", "Versioned and effective-dated; one ACTIVE version"),
    ("Portfolio", "Constraint", "N:M", "Bridge: portfolio_constraint (only LISTED_PORTFOLIOS rules)"),
    ("Portfolio", "RebalanceProposal", "1:N", "Optional: portfolios inside tolerance get no proposal"),
    ("RebalanceProposal", "Trade", "1:N", "Optional: BLOCKED proposals have zero trades"),
    ("FeeSchedule", "Trade", "1:N", "Optional: null fee_schedule_id only in the fees-omitted anomaly"),
    ("Instrument", "Trade", "1:N", "A BUY may open a new position (no Holding row yet)"),
    ("RebalanceProposal", "ProposalEvent", "1:N", "Append-only status history"),
    ("RebalanceProposal", "PostTradeAllocation", "1:N", "Exactly 4 rows (one per asset class)"),
]

SQLTYPE = {"TEXT": "TEXT", "INTEGER": "INTEGER", "REAL": "REAL", "DATE": "TEXT", "TIMESTAMP": "TEXT", "BOOLEAN": "INTEGER"}


def q(name):
    return f'"{name}"' if name in ("constraint", "trade", "holding", "portfolio") else name


def render_ddl():
    out = ["-- Educational simulation schema (SQLite dialect). Not financial advice.", "PRAGMA foreign_keys=ON;", ""]
    for e in ENTITIES:
        cols = []
        for f in e.fields:
            s = f"  {f.name} {SQLTYPE[f.type]}"
            if f.required:
                s += " NOT NULL"
            if isinstance(f.allowed, list):
                vals = ",".join(f"'{v}'" for v in f.allowed)
                s += f" CHECK ({f.name} IN ({vals}))"
            if f.type == "BOOLEAN":
                s += f" CHECK ({f.name} IN (0,1))"
            cols.append(s)
        cols.append(f"  PRIMARY KEY ({', '.join(e.pk)})")
        for k in e.unique_keys:
            cols.append(f"  UNIQUE ({', '.join(k)})")
        for c, pt, pc in e.fks:
            cols.append(f"  FOREIGN KEY ({c}) REFERENCES {q(pt)}({pc})")
        out.append(f"-- {e.name}: {e.description}")
        out.append(f"CREATE TABLE {q(e.table)} (\n" + ",\n".join(cols) + "\n);\n")
    return "\n".join(out)


def _allowed_text(f):
    return ", ".join(f.allowed) if isinstance(f.allowed, list) else f.allowed


def dictionary_rows():
    rows = []
    for e in ENTITIES:
        for f in e.fields:
            rows.append({"entity": e.name, "table": e.table, "field": f.name, "type": f.type,
                         "required": "Y" if f.required else "N", "allowed_values": _allowed_text(f),
                         "unit": f.unit, "unique": "Y" if (f.unique or [f.name] == e.pk) else "N",
                         "key": "PK" if f.name in e.pk else ("FK" if any(c == f.name for c, _, _ in e.fks) else ""),
                         "validation_rule": f.rule})
    return rows


def render_data_dictionary_md():
    md = ["# Data Dictionary", "",
          "Educational simulation - not financial advice. All data is synthetic. Single currency (USD).", "",
          "Types: TEXT, INTEGER, REAL, DATE (ISO yyyy-mm-dd), TIMESTAMP (UTC ISO-8601), BOOLEAN (true/false in CSV, 1/0 in SQL).",
          "Entities marked *core* are the ten required by the brief; the others support history, bridging and traceability.", "",
          "## Relationships and cardinality", "",
          "| Parent | Child | Cardinality | Notes |", "|---|---|---|---|"]
    for a, b, c, n in RELATIONSHIPS:
        md.append(f"| {a} | {b} | {c} | {n} |")
    for e in ENTITIES:
        md += ["", f"## {e.name} (`{e.table}`){' - core' if e.core else ' - supporting'}", "", e.description, "",
               f"- **Primary key:** {', '.join(e.pk)}"]
        if e.fks:
            md.append("- **Foreign keys:** " + "; ".join(f"{c} -> {pt}.{pc}" for c, pt, pc in e.fks))
        if e.unique_keys:
            md.append("- **Natural unique keys:** " + "; ".join("(" + ", ".join(k) + ")" for k in e.unique_keys))
        if e.cardinality:
            md.append(f"- **Cardinality:** {e.cardinality}")
        if e.lifecycle:
            md.append(f"- **Lifecycle:** {e.lifecycle}")
        md += ["", "| Field | Type | Req | Allowed values / format | Unit | Unique | Validation rule |", "|---|---|---|---|---|---|---|"]
        for f in e.fields:
            u = "Y" if (f.unique or [f.name] == e.pk) else "N"
            md.append(f"| `{f.name}` | {f.type} | {'Y' if f.required else 'N'} | {_allowed_text(f)} | {f.unit} | {u} | {f.rule} |")
    return "\n".join(md) + "\n"
