# Data Dictionary

Educational simulation - not financial advice. All data is synthetic. Single currency (USD).

Types: TEXT, INTEGER, REAL, DATE (ISO yyyy-mm-dd), TIMESTAMP (UTC ISO-8601), BOOLEAN (true/false in CSV, 1/0 in SQL).
Entities marked *core* are the ten required by the brief; the others support history, bridging and traceability.

## Relationships and cardinality

| Parent | Child | Cardinality | Notes |
|---|---|---|---|
| InvestorProfile | Portfolio | 1:N | A portfolio needs exactly one investor; an investor has 1-2 portfolios |
| Portfolio | Holding | 1:N | Every portfolio holds at least one position in each of the 4 asset classes |
| Instrument | Holding | 1:N | Holding is the bridge giving Portfolio N:M Instrument |
| Instrument | MarketPrice | 1:N | One row per instrument per trading day (MISSING rows are explicit) |
| Portfolio | TargetAllocation | 1:N | Versioned and effective-dated; one ACTIVE version |
| Portfolio | Constraint | N:M | Bridge: portfolio_constraint (only LISTED_PORTFOLIOS rules) |
| Portfolio | RebalanceProposal | 1:N | Optional: portfolios inside tolerance get no proposal |
| RebalanceProposal | Trade | 1:N | Optional: BLOCKED proposals have zero trades |
| FeeSchedule | Trade | 1:N | Optional: null fee_schedule_id only in the fees-omitted anomaly |
| Instrument | Trade | 1:N | A BUY may open a new position (no Holding row yet) |
| RebalanceProposal | ProposalEvent | 1:N | Append-only status history |
| RebalanceProposal | PostTradeAllocation | 1:N | Exactly 4 rows (one per asset class) |

## InvestorProfile (`investor_profile`) - core

Synthetic account holder with a risk profile. No personal data: no names or contact details.

- **Primary key:** investor_id
- **Cardinality:** InvestorProfile 1:N Portfolio (about 10% of investors own two portfolios)
- **Lifecycle:** ACTIVE <-> SUSPENDED (static in this snapshot)

| Field | Type | Req | Allowed values / format | Unit | Unique | Validation rule |
|---|---|---|---|---|---|---|
| `investor_id` | TEXT | Y | INV-NNNNNN |  | Y | Zero-padded sequential, immutable |
| `risk_profile` | TEXT | Y | CONSERVATIVE, MODERATE, BALANCED, GROWTH, AGGRESSIVE |  | N | Drawn from age-conditioned weights; drives target model and minimum cash |
| `risk_score` | INTEGER | Y | 1..100 | points | N | Derived: base(profile)+round((50-age)/5)+round(min(horizon,30)/6), clamped |
| `age` | INTEGER | Y | 21..80 | years | N |  |
| `investment_horizon_years` | INTEGER | Y | 1..40 | years | N |  |
| `annual_income_band` | TEXT | Y | LOW, MIDDLE, UPPER, HIGH |  | N |  |
| `country` | TEXT | Y | US, GB, IN, SG, DE, AE |  | N |  |
| `base_currency` | TEXT | Y | USD |  | N | Single-currency simulation |
| `kyc_status` | TEXT | Y | VERIFIED, PENDING, EXPIRED |  | N | EXPIRED freezes the investor's portfolios; PENDING blocks customer acceptance |
| `kyc_expiry_date` | DATE | Y |  |  | N | < as_of_date if and only if kyc_status = EXPIRED |
| `created_date` | DATE | Y |  |  | N | Earlier than every portfolio inception_date |
| `status` | TEXT | Y | ACTIVE, SUSPENDED |  | N |  |

## Portfolio (`portfolio`) - core

An investment account owned by one investor.

- **Primary key:** portfolio_id
- **Foreign keys:** investor_id -> investor_profile.investor_id
- **Cardinality:** Portfolio 1:N Holding, 1:N TargetAllocation, 1:N RebalanceProposal, N:M Constraint (bridge)
- **Lifecycle:** ACTIVE -> FROZEN (KYC expiry) -> CLOSED

| Field | Type | Req | Allowed values / format | Unit | Unique | Validation rule |
|---|---|---|---|---|---|---|
| `portfolio_id` | TEXT | Y | PORT-<investor-id>-NN |  | Y | PORT-INV-000001-01; NN is portfolio_seq |
| `investor_id` | TEXT | Y |  |  | N | FK -> investor_profile.investor_id |
| `portfolio_seq` | INTEGER | Y | 1..9 |  | N | Matches the NN suffix of portfolio_id |
| `portfolio_name` | TEXT | Y |  |  | N |  |
| `base_currency` | TEXT | Y | USD |  | N |  |
| `inception_date` | DATE | Y |  |  | N | After investor created_date, at least 180 days before as_of_date |
| `status` | TEXT | Y | ACTIVE, FROZEN, CLOSED |  | N | FROZEN if and only if the investor's kyc_status = EXPIRED |
| `status_reason` | TEXT | N | KYC_EXPIRED |  | N | Required when status = FROZEN |

## Instrument (`instrument`) - core

Tradable synthetic fund/security. All names are fictional.

- **Primary key:** instrument_id
- **Natural unique keys:** (ticker)
- **Cardinality:** Instrument 1:N MarketPrice; Portfolio N:M Instrument via Holding (bridge)
- **Lifecycle:** ACTIVE -> SUSPENDED -> DELISTED

| Field | Type | Req | Allowed values / format | Unit | Unique | Validation rule |
|---|---|---|---|---|---|---|
| `instrument_id` | TEXT | Y | INS-NNNNNN |  | Y |  |
| `ticker` | TEXT | Y |  |  | Y | Synthetic, e.g. EQ0001 |
| `instrument_name` | TEXT | Y |  |  | N |  |
| `asset_class` | TEXT | Y | EQUITY, FIXED_INCOME, REAL_ASSETS, CASH |  | N |  |
| `sub_class` | TEXT | Y |  |  | N | Sub-bucket inside asset_class |
| `currency` | TEXT | Y | USD |  | N |  |
| `liquidity_tier` | TEXT | Y | HIGH, MEDIUM, LOW |  | N | Selects the MAX_PCT_ADV constraint |
| `avg_daily_volume_units` | INTEGER | Y | >0 | units/day | N |  |
| `lot_size` | REAL | Y | >0 | units | N | Trade quantity must be a multiple (0.01 for cash) |
| `is_excluded` | BOOLEAN | Y |  |  | N | True => firm-wide EXCLUDED_INSTRUMENT constraint exists; BUY forbidden, SELL allowed |
| `exclusion_reason` | TEXT | N | RESTRICTED_LIST, SANCTIONS_SCREEN, INTERNAL_POLICY |  | N | Required iff is_excluded |
| `listing_date` | DATE | Y |  |  | N | Before first price_date |
| `status` | TEXT | Y | ACTIVE, SUSPENDED, DELISTED |  | N |  |

## MarketPrice (`market_price`) - core

Daily close per instrument. Missing days stay as explicit MISSING rows (never silently dropped).

- **Primary key:** price_id
- **Foreign keys:** instrument_id -> instrument.instrument_id
- **Natural unique keys:** (instrument_id, price_date)
- **Cardinality:** MarketPrice N:1 Instrument; unique per (instrument_id, price_date)
- **Lifecycle:** Append-only: history is never overwritten

| Field | Type | Req | Allowed values / format | Unit | Unique | Validation rule |
|---|---|---|---|---|---|---|
| `price_id` | TEXT | Y | PX-<instrument-id>-YYYYMMDD |  | Y |  |
| `instrument_id` | TEXT | Y |  |  | N | FK -> instrument.instrument_id |
| `price_date` | DATE | Y |  |  | N | Weekday; 250 consecutive trading days ending at as_of_date |
| `close_price` | REAL | N | >0 | USD | N | Null if and only if price_status = MISSING |
| `price_status` | TEXT | Y | OBSERVED, MISSING |  | N |  |
| `source` | TEXT | Y | SYNTHETIC_GBM |  | N | Correlated geometric random walk, fixed seed |

## Holding (`holding`) - core

Position snapshot at as_of_date. Valuation columns are derived from quantity and MarketPrice.

- **Primary key:** holding_id
- **Foreign keys:** portfolio_id -> portfolio.portfolio_id; instrument_id -> instrument.instrument_id
- **Natural unique keys:** (portfolio_id, instrument_id)
- **Cardinality:** Bridge for Portfolio N:M Instrument; one row per (portfolio, instrument)
- **Lifecycle:** Snapshot; post-trade holdings are simulated in post_trade_allocation, never overwritten

| Field | Type | Req | Allowed values / format | Unit | Unique | Validation rule |
|---|---|---|---|---|---|---|
| `holding_id` | TEXT | Y | HOLD-<portfolio-id>-<instrument-id> |  | Y |  |
| `portfolio_id` | TEXT | Y |  |  | N | FK -> portfolio.portfolio_id |
| `instrument_id` | TEXT | Y |  |  | N | FK -> instrument.instrument_id |
| `as_of_date` | DATE | Y |  |  | N |  |
| `quantity` | REAL | Y | >0 | units (USD for cash) | N |  |
| `avg_cost_per_unit` | REAL | Y | >0 | USD | N |  |
| `acquired_date` | DATE | Y |  |  | N | Between portfolio inception_date and as_of_date |
| `price_used` | REAL | Y |  | USD | N | Last OBSERVED close on or before as_of_date |
| `price_date_used` | DATE | Y |  |  | N | Date of price_used |
| `price_age_days` | INTEGER | Y |  | trading days | N | Trading days between price_date_used and as_of_date |
| `stale_price_flag` | BOOLEAN | Y |  |  | N | price_age_days > stale_days_threshold (3) |
| `market_value` | REAL | Y |  | USD | N | round(quantity * price_used, 2) |
| `current_weight_pct` | REAL | Y |  | % of portfolio | N | market_value / sum(market_value of portfolio) * 100 |
| `status` | TEXT | Y | ACTIVE, CLOSED |  | N |  |

## TargetAllocation (`target_allocation`) - core

Target weight per asset class per portfolio, effective-dated and versioned.

- **Primary key:** target_id
- **Foreign keys:** portfolio_id -> portfolio.portfolio_id
- **Natural unique keys:** (portfolio_id, asset_class, version)
- **Cardinality:** Portfolio 1:N TargetAllocation (4 asset classes x versions)
- **Lifecycle:** ACTIVE -> SUPERSEDED when a new version takes over

| Field | Type | Req | Allowed values / format | Unit | Unique | Validation rule |
|---|---|---|---|---|---|---|
| `target_id` | TEXT | Y | TGT-<portfolio-id>-<asset_class>-V<n> |  | Y |  |
| `portfolio_id` | TEXT | Y |  |  | N | FK -> portfolio.portfolio_id |
| `asset_class` | TEXT | Y | EQUITY, FIXED_INCOME, REAL_ASSETS, CASH |  | N |  |
| `target_weight_pct` | REAL | Y | 0..100 | % of portfolio | N | Weights of the ACTIVE version must sum to 100 (violations are labelled anomalies) |
| `tolerance_band_pct` | REAL | Y | >0 | percentage points | N | Rebalance trigger: abs(current - target) > band |
| `version` | INTEGER | Y | >=1 |  | N |  |
| `effective_from` | DATE | Y |  |  | N |  |
| `effective_to` | DATE | N |  |  | N | Null while ACTIVE; >= effective_from; earlier than next version's effective_from |
| `status` | TEXT | Y | ACTIVE, SUPERSEDED |  | N |  |

## FeeSchedule (`fee_schedule`) - core

Tiered commission by asset class and trade notional, effective-dated.

- **Primary key:** fee_schedule_id
- **Natural unique keys:** (asset_class, tier, fee_version)
- **Cardinality:** FeeSchedule 1:N Trade (optional: omitted fee => null)
- **Lifecycle:** ACTIVE -> SUPERSEDED; fee = max(min_fee, flat_fee + notional * bps / 10000)

| Field | Type | Req | Allowed values / format | Unit | Unique | Validation rule |
|---|---|---|---|---|---|---|
| `fee_schedule_id` | TEXT | Y | FEE-NNNNNN |  | Y |  |
| `asset_class` | TEXT | Y | EQUITY, FIXED_INCOME, REAL_ASSETS, CASH |  | N |  |
| `tier` | TEXT | Y | TIER_1, TIER_2, TIER_3 |  | N |  |
| `min_notional` | REAL | Y |  | USD | N | Inclusive lower bound; tiers contiguous |
| `max_notional` | REAL | Y |  | USD | N | Exclusive upper bound |
| `commission_bps` | REAL | Y |  | bps of notional | N |  |
| `flat_fee` | REAL | Y |  | USD | N |  |
| `min_fee` | REAL | Y |  | USD | N |  |
| `fee_version` | INTEGER | Y | >=1 |  | N |  |
| `effective_from` | DATE | Y |  |  | N |  |
| `effective_to` | DATE | N |  |  | N |  |
| `status` | TEXT | Y | ACTIVE, SUPERSEDED |  | N |  |
| `created_by` | TEXT | Y | USR-ADM-NNN |  | N | System administrator who published the row |

## Constraint (`constraint`) - core

Policy rule. ALL_PORTFOLIOS rules apply everywhere; LISTED_PORTFOLIOS rules apply via portfolio_constraint.

- **Primary key:** constraint_id
- **Cardinality:** Constraint N:M Portfolio via portfolio_constraint
- **Lifecycle:** ACTIVE -> RETIRED

| Field | Type | Req | Allowed values / format | Unit | Unique | Validation rule |
|---|---|---|---|---|---|---|
| `constraint_id` | TEXT | Y | CON-NNNNNN |  | Y |  |
| `constraint_type` | TEXT | Y | MIN_TRADE_VALUE, MAX_TURNOVER_PCT, MAX_PCT_ADV, EXCLUDED_INSTRUMENT, MIN_CASH_PCT |  | N |  |
| `scope_type` | TEXT | Y | GLOBAL, ASSET_CLASS, LIQUIDITY_TIER, INSTRUMENT, RISK_PROFILE |  | N |  |
| `scope_id` | TEXT | N |  |  | N | Asset class, tier, instrument_id or risk profile; null for GLOBAL |
| `applies_to` | TEXT | Y | ALL_PORTFOLIOS, LISTED_PORTFOLIOS |  | N |  |
| `value` | REAL | N |  |  | N | Threshold; null for EXCLUDED_INSTRUMENT |
| `unit` | TEXT | Y | USD, PCT_OF_PORTFOLIO, PCT_OF_ADV, NONE |  | N |  |
| `severity` | TEXT | Y | HARD |  | N |  |
| `description` | TEXT | Y |  |  | N |  |
| `effective_from` | DATE | Y |  |  | N |  |
| `effective_to` | DATE | N |  |  | N |  |
| `status` | TEXT | Y | ACTIVE, RETIRED |  | N |  |
| `created_by` | TEXT | Y | USR-ADM-NNN |  | N |  |

## PortfolioConstraint (`portfolio_constraint`) - supporting

Bridge table for Portfolio N:M Constraint (LISTED_PORTFOLIOS rules only).

- **Primary key:** portfolio_constraint_id
- **Foreign keys:** portfolio_id -> portfolio.portfolio_id; constraint_id -> constraint.constraint_id
- **Natural unique keys:** (portfolio_id, constraint_id)
- **Cardinality:** Bridge (N:M)
- **Lifecycle:** Effective-dated

| Field | Type | Req | Allowed values / format | Unit | Unique | Validation rule |
|---|---|---|---|---|---|---|
| `portfolio_constraint_id` | TEXT | Y | PC-NNNNNN |  | Y |  |
| `portfolio_id` | TEXT | Y |  |  | N | FK -> portfolio.portfolio_id |
| `constraint_id` | TEXT | Y |  |  | N | FK -> constraint.constraint_id |
| `effective_from` | DATE | Y |  |  | N | >= portfolio inception_date |
| `effective_to` | DATE | N |  |  | N |  |

## RebalanceProposal (`rebalance_proposal`) - core

System-generated rebalancing recommendation. Aggregates are derived from Trade and Holding rows.

- **Primary key:** proposal_id
- **Foreign keys:** portfolio_id -> portfolio.portfolio_id
- **Cardinality:** Portfolio 1:N RebalanceProposal; RebalanceProposal 1:N Trade; 1:N ProposalEvent; 1:4 PostTradeAllocation
- **Lifecycle:** DRAFT -> PENDING_OPS_REVIEW -> [PENDING_COMPLIANCE_REVIEW] -> APPROVED|REJECTED -> CUSTOMER_ACCEPTED|EXPIRED -> EXECUTED_SIMULATED; DRAFT -> BLOCKED

| Field | Type | Req | Allowed values / format | Unit | Unique | Validation rule |
|---|---|---|---|---|---|---|
| `proposal_id` | TEXT | Y | RB-YYYY-NNNNNN |  | Y |  |
| `portfolio_id` | TEXT | Y |  |  | N | FK -> portfolio.portfolio_id |
| `as_of_date` | DATE | Y |  |  | N |  |
| `generated_at` | TIMESTAMP | Y |  |  | N | UTC ISO-8601 |
| `trigger_reason` | TEXT | Y | DRIFT_BREACH, PORTFOLIO_FROZEN |  | N |  |
| `status` | TEXT | Y | DRAFT, PENDING_OPS_REVIEW, PENDING_COMPLIANCE_REVIEW, APPROVED, REJECTED, CUSTOMER_ACCEPTED, EXECUTED_SIMULATED, EXPIRED, BLOCKED |  | N | Equals the to_status of the latest proposal_event |
| `policy_version` | TEXT | Y | POLICY-2026.10 |  | N |  |
| `target_weight_sum_pct` | REAL | Y |  | % | N | Sum of ACTIVE target weights (should be 100) |
| `portfolio_value` | REAL | Y |  | USD | N | Sum of holding market_value |
| `post_trade_value` | REAL | Y |  | USD | N | Recomputed from post-trade holdings x prices (fees leave the portfolio) |
| `pre_max_abs_drift_pct` | REAL | Y |  | percentage points | N |  |
| `post_max_abs_drift_pct` | REAL | Y |  | percentage points | N |  |
| `drift_reduction_pct` | REAL | Y |  | % | N | (pre - post) / pre * 100 |
| `num_trades` | INTEGER | Y | >=0 |  | N | Count of Trade rows |
| `total_buy_value` | REAL | Y |  | USD | N | Sum of BUY notional |
| `total_sell_value` | REAL | Y |  | USD | N | Sum of SELL notional |
| `total_estimated_fees` | REAL | Y |  | USD | N | Sum of trade estimated_fee (null counted as 0) |
| `turnover_pct` | REAL | Y |  | % of portfolio | N | (buys + sells) / 2 / portfolio_value * 100 |
| `cash_after` | REAL | Y |  | USD | N | Post-trade value of the CASH class |
| `min_cash_required` | REAL | Y |  | USD | N | MIN_CASH_PCT constraint x portfolio_value |
| `price_stale_count` | INTEGER | Y |  |  | N | Trades with stale_price_flag = true |
| `liquidity_capped_count` | INTEGER | Y |  |  | N | Trades reduced by the MAX_PCT_ADV cap |
| `suppressed_trade_count` | INTEGER | Y |  |  | N | Candidate trades dropped for MIN_TRADE_VALUE |
| `requires_compliance_review` | BOOLEAN | Y |  |  | N | True if review_reasons is not empty |
| `review_reasons` | TEXT | N |  |  | N | Pipe-separated: STALE_PRICE|LIQUIDITY_CAP|HIGH_NOTIONAL|HIGH_TURNOVER|NO_ELIGIBLE_BUY_INSTRUMENT |

## Trade (`trade`) - core

Recommended trade within a proposal. Cash is the residual and is never traded.

- **Primary key:** trade_id
- **Foreign keys:** proposal_id -> rebalance_proposal.proposal_id; portfolio_id -> portfolio.portfolio_id; instrument_id -> instrument.instrument_id; fee_schedule_id -> fee_schedule.fee_schedule_id
- **Cardinality:** RebalanceProposal 1:N Trade; Trade N:1 Instrument; Trade N:1 FeeSchedule (optional)
- **Lifecycle:** PROPOSED -> APPROVED|REJECTED -> EXECUTED_SIMULATED|EXPIRED

| Field | Type | Req | Allowed values / format | Unit | Unique | Validation rule |
|---|---|---|---|---|---|---|
| `trade_id` | TEXT | Y | TRD-<proposal-id>-NN |  | Y |  |
| `proposal_id` | TEXT | Y |  |  | N | FK -> rebalance_proposal.proposal_id |
| `portfolio_id` | TEXT | Y |  |  | N | FK -> portfolio.portfolio_id; equals the proposal's portfolio |
| `instrument_id` | TEXT | Y |  |  | N | FK -> instrument.instrument_id |
| `side` | TEXT | Y | BUY, SELL |  | N |  |
| `quantity` | REAL | Y | >0 | units | N | Multiple of lot_size; SELL <= holding quantity |
| `holding_quantity_before` | REAL | Y |  | units | N | Quantity in the Holding table (0 if not held) |
| `price_used` | REAL | Y |  | USD | N |  |
| `price_date_used` | DATE | Y |  |  | N | <= as_of_date |
| `price_age_days` | INTEGER | Y |  | trading days | N |  |
| `stale_price_flag` | BOOLEAN | Y |  |  | N | Must be true when price_age_days > 3 |
| `notional` | REAL | Y |  | USD | N | round(quantity * price_used, 2) |
| `fee_schedule_id` | TEXT | N |  |  | N | FK -> fee_schedule; null only for omitted-fee anomalies |
| `estimated_fee` | REAL | N |  | USD | N | From FeeSchedule tier; null = omitted |
| `liquidity_cap_applied` | BOOLEAN | Y |  |  | N | Quantity reduced by MAX_PCT_ADV |
| `trade_status` | TEXT | Y | PROPOSED, APPROVED, REJECTED, EXPIRED, EXECUTED_SIMULATED |  | N | Mapped from the proposal's final status |

## ProposalEvent (`proposal_event`) - supporting

Append-only state-change history for each proposal (nothing is overwritten).

- **Primary key:** event_id
- **Foreign keys:** proposal_id -> rebalance_proposal.proposal_id
- **Cardinality:** RebalanceProposal 1:N ProposalEvent
- **Lifecycle:** Append-only

| Field | Type | Req | Allowed values / format | Unit | Unique | Validation rule |
|---|---|---|---|---|---|---|
| `event_id` | TEXT | Y | EVT-NNNNNN |  | Y |  |
| `proposal_id` | TEXT | Y |  |  | N | FK -> rebalance_proposal.proposal_id |
| `event_ts` | TIMESTAMP | Y |  |  | N | Non-decreasing per proposal |
| `from_status` | TEXT | N | DRAFT, PENDING_OPS_REVIEW, PENDING_COMPLIANCE_REVIEW, APPROVED, REJECTED, CUSTOMER_ACCEPTED, EXECUTED_SIMULATED, EXPIRED, BLOCKED |  | N | Null only for the first event |
| `to_status` | TEXT | Y | DRAFT, PENDING_OPS_REVIEW, PENDING_COMPLIANCE_REVIEW, APPROVED, REJECTED, CUSTOMER_ACCEPTED, EXECUTED_SIMULATED, EXPIRED, BLOCKED |  | N | Pair must be in TRANSITIONS |
| `actor_role` | TEXT | Y | SYSTEM, CUSTOMER, OPS_ANALYST, RISK_COMPLIANCE, SYSTEM_ADMIN |  | N |  |
| `actor_id` | TEXT | Y |  |  | N | SYSTEM, USR-OPS-NNN, USR-CMP-NNN or an investor_id |
| `reason_code` | TEXT | Y |  |  | N | Rule that produced the transition |

## DriftSnapshot (`drift_snapshot`) - supporting

Current weight vs target per portfolio and asset class (the drift calculation made visible).

- **Primary key:** snapshot_id
- **Foreign keys:** portfolio_id -> portfolio.portfolio_id
- **Natural unique keys:** (portfolio_id, asset_class)
- **Cardinality:** Portfolio 1:N DriftSnapshot (4 per portfolio)

| Field | Type | Req | Allowed values / format | Unit | Unique | Validation rule |
|---|---|---|---|---|---|---|
| `snapshot_id` | TEXT | Y | SNAP-<portfolio-id>-<asset_class> |  | Y |  |
| `portfolio_id` | TEXT | Y |  |  | N | FK -> portfolio.portfolio_id |
| `as_of_date` | DATE | Y |  |  | N |  |
| `asset_class` | TEXT | Y | EQUITY, FIXED_INCOME, REAL_ASSETS, CASH |  | N |  |
| `current_value` | REAL | Y |  | USD | N | Sum of holding market_value in the class |
| `current_weight_pct` | REAL | Y |  | % | N |  |
| `target_weight_pct` | REAL | Y |  | % | N | ACTIVE target |
| `drift_pct` | REAL | Y |  | percentage points | N | current - target |
| `tolerance_band_pct` | REAL | Y |  | percentage points | N |  |
| `breach_flag` | BOOLEAN | Y |  |  | N | abs(drift_pct) > tolerance_band_pct |

## PostTradeAllocation (`post_trade_allocation`) - supporting

Simulated allocation after a proposal, recomputed from holdings, trades and prices.

- **Primary key:** post_alloc_id
- **Foreign keys:** proposal_id -> rebalance_proposal.proposal_id
- **Natural unique keys:** (proposal_id, asset_class)
- **Cardinality:** RebalanceProposal 1:N PostTradeAllocation (4 per proposal)

| Field | Type | Req | Allowed values / format | Unit | Unique | Validation rule |
|---|---|---|---|---|---|---|
| `post_alloc_id` | TEXT | Y | PTA-<proposal-id>-<asset_class> |  | Y |  |
| `proposal_id` | TEXT | Y |  |  | N | FK -> rebalance_proposal.proposal_id |
| `asset_class` | TEXT | Y | EQUITY, FIXED_INCOME, REAL_ASSETS, CASH |  | N |  |
| `pre_weight_pct` | REAL | Y |  | % | N |  |
| `post_weight_pct` | REAL | Y |  | % | N | Sums to 100 per proposal |
| `target_weight_pct` | REAL | Y |  | % | N |  |
| `pre_drift_pct` | REAL | Y |  | percentage points | N |  |
| `post_drift_pct` | REAL | Y |  | percentage points | N |  |
| `post_value` | REAL | Y |  | USD | N |  |
