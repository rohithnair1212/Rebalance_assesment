-- Educational simulation schema (SQLite dialect). Not financial advice.
PRAGMA foreign_keys=ON;

-- InvestorProfile: Synthetic account holder with a risk profile. No personal data: no names or contact details.
CREATE TABLE investor_profile (
  investor_id TEXT NOT NULL,
  risk_profile TEXT NOT NULL CHECK (risk_profile IN ('CONSERVATIVE','MODERATE','BALANCED','GROWTH','AGGRESSIVE')),
  risk_score INTEGER NOT NULL,
  age INTEGER NOT NULL,
  investment_horizon_years INTEGER NOT NULL,
  annual_income_band TEXT NOT NULL CHECK (annual_income_band IN ('LOW','MIDDLE','UPPER','HIGH')),
  country TEXT NOT NULL CHECK (country IN ('US','GB','IN','SG','DE','AE')),
  base_currency TEXT NOT NULL CHECK (base_currency IN ('USD')),
  kyc_status TEXT NOT NULL CHECK (kyc_status IN ('VERIFIED','PENDING','EXPIRED')),
  kyc_expiry_date TEXT NOT NULL,
  created_date TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('ACTIVE','SUSPENDED')),
  PRIMARY KEY (investor_id)
);

-- Portfolio: An investment account owned by one investor.
CREATE TABLE "portfolio" (
  portfolio_id TEXT NOT NULL,
  investor_id TEXT NOT NULL,
  portfolio_seq INTEGER NOT NULL,
  portfolio_name TEXT NOT NULL,
  base_currency TEXT NOT NULL CHECK (base_currency IN ('USD')),
  inception_date TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('ACTIVE','FROZEN','CLOSED')),
  status_reason TEXT CHECK (status_reason IN ('KYC_EXPIRED')),
  PRIMARY KEY (portfolio_id),
  FOREIGN KEY (investor_id) REFERENCES investor_profile(investor_id)
);

-- Instrument: Tradable synthetic fund/security. All names are fictional.
CREATE TABLE instrument (
  instrument_id TEXT NOT NULL,
  ticker TEXT NOT NULL,
  instrument_name TEXT NOT NULL,
  asset_class TEXT NOT NULL CHECK (asset_class IN ('EQUITY','FIXED_INCOME','REAL_ASSETS','CASH')),
  sub_class TEXT NOT NULL,
  currency TEXT NOT NULL CHECK (currency IN ('USD')),
  liquidity_tier TEXT NOT NULL CHECK (liquidity_tier IN ('HIGH','MEDIUM','LOW')),
  avg_daily_volume_units INTEGER NOT NULL,
  lot_size REAL NOT NULL,
  is_excluded INTEGER NOT NULL CHECK (is_excluded IN (0,1)),
  exclusion_reason TEXT CHECK (exclusion_reason IN ('RESTRICTED_LIST','SANCTIONS_SCREEN','INTERNAL_POLICY')),
  listing_date TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('ACTIVE','SUSPENDED','DELISTED')),
  PRIMARY KEY (instrument_id),
  UNIQUE (ticker)
);

-- MarketPrice: Daily close per instrument. Missing days stay as explicit MISSING rows (never silently dropped).
CREATE TABLE market_price (
  price_id TEXT NOT NULL,
  instrument_id TEXT NOT NULL,
  price_date TEXT NOT NULL,
  close_price REAL,
  price_status TEXT NOT NULL CHECK (price_status IN ('OBSERVED','MISSING')),
  source TEXT NOT NULL CHECK (source IN ('SYNTHETIC_GBM')),
  PRIMARY KEY (price_id),
  UNIQUE (instrument_id, price_date),
  FOREIGN KEY (instrument_id) REFERENCES instrument(instrument_id)
);

-- Holding: Position snapshot at as_of_date. Valuation columns are derived from quantity and MarketPrice.
CREATE TABLE "holding" (
  holding_id TEXT NOT NULL,
  portfolio_id TEXT NOT NULL,
  instrument_id TEXT NOT NULL,
  as_of_date TEXT NOT NULL,
  quantity REAL NOT NULL,
  avg_cost_per_unit REAL NOT NULL,
  acquired_date TEXT NOT NULL,
  price_used REAL NOT NULL,
  price_date_used TEXT NOT NULL,
  price_age_days INTEGER NOT NULL,
  stale_price_flag INTEGER NOT NULL CHECK (stale_price_flag IN (0,1)),
  market_value REAL NOT NULL,
  current_weight_pct REAL NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('ACTIVE','CLOSED')),
  PRIMARY KEY (holding_id),
  UNIQUE (portfolio_id, instrument_id),
  FOREIGN KEY (portfolio_id) REFERENCES "portfolio"(portfolio_id),
  FOREIGN KEY (instrument_id) REFERENCES instrument(instrument_id)
);

-- TargetAllocation: Target weight per asset class per portfolio, effective-dated and versioned.
CREATE TABLE target_allocation (
  target_id TEXT NOT NULL,
  portfolio_id TEXT NOT NULL,
  asset_class TEXT NOT NULL CHECK (asset_class IN ('EQUITY','FIXED_INCOME','REAL_ASSETS','CASH')),
  target_weight_pct REAL NOT NULL,
  tolerance_band_pct REAL NOT NULL,
  version INTEGER NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  status TEXT NOT NULL CHECK (status IN ('ACTIVE','SUPERSEDED')),
  PRIMARY KEY (target_id),
  UNIQUE (portfolio_id, asset_class, version),
  FOREIGN KEY (portfolio_id) REFERENCES "portfolio"(portfolio_id)
);

-- FeeSchedule: Tiered commission by asset class and trade notional, effective-dated.
CREATE TABLE fee_schedule (
  fee_schedule_id TEXT NOT NULL,
  asset_class TEXT NOT NULL CHECK (asset_class IN ('EQUITY','FIXED_INCOME','REAL_ASSETS','CASH')),
  tier TEXT NOT NULL CHECK (tier IN ('TIER_1','TIER_2','TIER_3')),
  min_notional REAL NOT NULL,
  max_notional REAL NOT NULL,
  commission_bps REAL NOT NULL,
  flat_fee REAL NOT NULL,
  min_fee REAL NOT NULL,
  fee_version INTEGER NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  status TEXT NOT NULL CHECK (status IN ('ACTIVE','SUPERSEDED')),
  created_by TEXT NOT NULL,
  PRIMARY KEY (fee_schedule_id),
  UNIQUE (asset_class, tier, fee_version)
);

-- Constraint: Policy rule. ALL_PORTFOLIOS rules apply everywhere; LISTED_PORTFOLIOS rules apply via portfolio_constraint.
CREATE TABLE "constraint" (
  constraint_id TEXT NOT NULL,
  constraint_type TEXT NOT NULL CHECK (constraint_type IN ('MIN_TRADE_VALUE','MAX_TURNOVER_PCT','MAX_PCT_ADV','EXCLUDED_INSTRUMENT','MIN_CASH_PCT')),
  scope_type TEXT NOT NULL CHECK (scope_type IN ('GLOBAL','ASSET_CLASS','LIQUIDITY_TIER','INSTRUMENT','RISK_PROFILE')),
  scope_id TEXT,
  applies_to TEXT NOT NULL CHECK (applies_to IN ('ALL_PORTFOLIOS','LISTED_PORTFOLIOS')),
  value REAL,
  unit TEXT NOT NULL CHECK (unit IN ('USD','PCT_OF_PORTFOLIO','PCT_OF_ADV','NONE')),
  severity TEXT NOT NULL CHECK (severity IN ('HARD')),
  description TEXT NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  status TEXT NOT NULL CHECK (status IN ('ACTIVE','RETIRED')),
  created_by TEXT NOT NULL,
  PRIMARY KEY (constraint_id)
);

-- PortfolioConstraint: Bridge table for Portfolio N:M Constraint (LISTED_PORTFOLIOS rules only).
CREATE TABLE portfolio_constraint (
  portfolio_constraint_id TEXT NOT NULL,
  portfolio_id TEXT NOT NULL,
  constraint_id TEXT NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  PRIMARY KEY (portfolio_constraint_id),
  UNIQUE (portfolio_id, constraint_id),
  FOREIGN KEY (portfolio_id) REFERENCES "portfolio"(portfolio_id),
  FOREIGN KEY (constraint_id) REFERENCES "constraint"(constraint_id)
);

-- RebalanceProposal: System-generated rebalancing recommendation. Aggregates are derived from Trade and Holding rows.
CREATE TABLE rebalance_proposal (
  proposal_id TEXT NOT NULL,
  portfolio_id TEXT NOT NULL,
  as_of_date TEXT NOT NULL,
  generated_at TEXT NOT NULL,
  trigger_reason TEXT NOT NULL CHECK (trigger_reason IN ('DRIFT_BREACH','PORTFOLIO_FROZEN')),
  status TEXT NOT NULL CHECK (status IN ('DRAFT','PENDING_OPS_REVIEW','PENDING_COMPLIANCE_REVIEW','APPROVED','REJECTED','CUSTOMER_ACCEPTED','EXECUTED_SIMULATED','EXPIRED','BLOCKED')),
  policy_version TEXT NOT NULL CHECK (policy_version IN ('POLICY-2026.10')),
  target_weight_sum_pct REAL NOT NULL,
  portfolio_value REAL NOT NULL,
  post_trade_value REAL NOT NULL,
  pre_max_abs_drift_pct REAL NOT NULL,
  post_max_abs_drift_pct REAL NOT NULL,
  drift_reduction_pct REAL NOT NULL,
  num_trades INTEGER NOT NULL,
  total_buy_value REAL NOT NULL,
  total_sell_value REAL NOT NULL,
  total_estimated_fees REAL NOT NULL,
  turnover_pct REAL NOT NULL,
  cash_after REAL NOT NULL,
  min_cash_required REAL NOT NULL,
  price_stale_count INTEGER NOT NULL,
  liquidity_capped_count INTEGER NOT NULL,
  suppressed_trade_count INTEGER NOT NULL,
  requires_compliance_review INTEGER NOT NULL CHECK (requires_compliance_review IN (0,1)),
  review_reasons TEXT,
  PRIMARY KEY (proposal_id),
  FOREIGN KEY (portfolio_id) REFERENCES "portfolio"(portfolio_id)
);

-- Trade: Recommended trade within a proposal. Cash is the residual and is never traded.
CREATE TABLE "trade" (
  trade_id TEXT NOT NULL,
  proposal_id TEXT NOT NULL,
  portfolio_id TEXT NOT NULL,
  instrument_id TEXT NOT NULL,
  side TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
  quantity REAL NOT NULL,
  holding_quantity_before REAL NOT NULL,
  price_used REAL NOT NULL,
  price_date_used TEXT NOT NULL,
  price_age_days INTEGER NOT NULL,
  stale_price_flag INTEGER NOT NULL CHECK (stale_price_flag IN (0,1)),
  notional REAL NOT NULL,
  fee_schedule_id TEXT,
  estimated_fee REAL,
  liquidity_cap_applied INTEGER NOT NULL CHECK (liquidity_cap_applied IN (0,1)),
  trade_status TEXT NOT NULL CHECK (trade_status IN ('PROPOSED','APPROVED','REJECTED','EXPIRED','EXECUTED_SIMULATED')),
  PRIMARY KEY (trade_id),
  FOREIGN KEY (proposal_id) REFERENCES rebalance_proposal(proposal_id),
  FOREIGN KEY (portfolio_id) REFERENCES "portfolio"(portfolio_id),
  FOREIGN KEY (instrument_id) REFERENCES instrument(instrument_id),
  FOREIGN KEY (fee_schedule_id) REFERENCES fee_schedule(fee_schedule_id)
);

-- ProposalEvent: Append-only state-change history for each proposal (nothing is overwritten).
CREATE TABLE proposal_event (
  event_id TEXT NOT NULL,
  proposal_id TEXT NOT NULL,
  event_ts TEXT NOT NULL,
  from_status TEXT CHECK (from_status IN ('DRAFT','PENDING_OPS_REVIEW','PENDING_COMPLIANCE_REVIEW','APPROVED','REJECTED','CUSTOMER_ACCEPTED','EXECUTED_SIMULATED','EXPIRED','BLOCKED')),
  to_status TEXT NOT NULL CHECK (to_status IN ('DRAFT','PENDING_OPS_REVIEW','PENDING_COMPLIANCE_REVIEW','APPROVED','REJECTED','CUSTOMER_ACCEPTED','EXECUTED_SIMULATED','EXPIRED','BLOCKED')),
  actor_role TEXT NOT NULL CHECK (actor_role IN ('SYSTEM','CUSTOMER','OPS_ANALYST','RISK_COMPLIANCE','SYSTEM_ADMIN')),
  actor_id TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  PRIMARY KEY (event_id),
  FOREIGN KEY (proposal_id) REFERENCES rebalance_proposal(proposal_id)
);

-- DriftSnapshot: Current weight vs target per portfolio and asset class (the drift calculation made visible).
CREATE TABLE drift_snapshot (
  snapshot_id TEXT NOT NULL,
  portfolio_id TEXT NOT NULL,
  as_of_date TEXT NOT NULL,
  asset_class TEXT NOT NULL CHECK (asset_class IN ('EQUITY','FIXED_INCOME','REAL_ASSETS','CASH')),
  current_value REAL NOT NULL,
  current_weight_pct REAL NOT NULL,
  target_weight_pct REAL NOT NULL,
  drift_pct REAL NOT NULL,
  tolerance_band_pct REAL NOT NULL,
  breach_flag INTEGER NOT NULL CHECK (breach_flag IN (0,1)),
  PRIMARY KEY (snapshot_id),
  UNIQUE (portfolio_id, asset_class),
  FOREIGN KEY (portfolio_id) REFERENCES "portfolio"(portfolio_id)
);

-- PostTradeAllocation: Simulated allocation after a proposal, recomputed from holdings, trades and prices.
CREATE TABLE post_trade_allocation (
  post_alloc_id TEXT NOT NULL,
  proposal_id TEXT NOT NULL,
  asset_class TEXT NOT NULL CHECK (asset_class IN ('EQUITY','FIXED_INCOME','REAL_ASSETS','CASH')),
  pre_weight_pct REAL NOT NULL,
  post_weight_pct REAL NOT NULL,
  target_weight_pct REAL NOT NULL,
  pre_drift_pct REAL NOT NULL,
  post_drift_pct REAL NOT NULL,
  post_value REAL NOT NULL,
  PRIMARY KEY (post_alloc_id),
  UNIQUE (proposal_id, asset_class),
  FOREIGN KEY (proposal_id) REFERENCES rebalance_proposal(proposal_id)
);
