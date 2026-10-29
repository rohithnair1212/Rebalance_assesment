# Validation summary

**Overall structural status: PASS** (109/109 checks passed)

## Row counts

| Table | Rows |
|---|---|
| investor_profile | 900 |
| portfolio | 1000 |
| instrument | 300 |
| market_price | 75000 |
| holding | 5000 |
| target_allocation | 4396 |
| fee_schedule | 24 |
| constraint | 27 |
| portfolio_constraint | 1720 |
| rebalance_proposal | 301 |
| trade | 917 |
| proposal_event | 1408 |
| drift_snapshot | 4000 |
| post_trade_allocation | 1204 |

## Structural and reconciliation checks

| Check | Category | Description | Rows | Violations | Status |
|---|---|---|---|---|---|
| SCH-001 | schema | CSV headers match the data dictionary | 14 | 0 | PASS |
| PK-investor_profile | primary_key | investor_profile: primary key unique and non-null | 900 | 0 | PASS |
| PK-portfolio | primary_key | portfolio: primary key unique and non-null | 1000 | 0 | PASS |
| PK-instrument | primary_key | instrument: primary key unique and non-null | 300 | 0 | PASS |
| DUP-instrument-ticker | duplicates | instrument: no duplicate (ticker) | 300 | 0 | PASS |
| PK-market_price | primary_key | market_price: primary key unique and non-null | 75000 | 0 | PASS |
| DUP-market_price-instrument_id_price_date | duplicates | market_price: no duplicate (instrument_id, price_date) | 75000 | 0 | PASS |
| PK-holding | primary_key | holding: primary key unique and non-null | 5000 | 0 | PASS |
| DUP-holding-portfolio_id_instrument_id | duplicates | holding: no duplicate (portfolio_id, instrument_id) | 5000 | 0 | PASS |
| PK-target_allocation | primary_key | target_allocation: primary key unique and non-null | 4396 | 0 | PASS |
| DUP-target_allocation-portfolio_id_asset_class_version | duplicates | target_allocation: no duplicate (portfolio_id, asset_class, version) | 4396 | 0 | PASS |
| PK-fee_schedule | primary_key | fee_schedule: primary key unique and non-null | 24 | 0 | PASS |
| DUP-fee_schedule-asset_class_tier_fee_version | duplicates | fee_schedule: no duplicate (asset_class, tier, fee_version) | 24 | 0 | PASS |
| PK-constraint | primary_key | constraint: primary key unique and non-null | 27 | 0 | PASS |
| PK-portfolio_constraint | primary_key | portfolio_constraint: primary key unique and non-null | 1720 | 0 | PASS |
| DUP-portfolio_constraint-portfolio_id_constraint_id | duplicates | portfolio_constraint: no duplicate (portfolio_id, constraint_id) | 1720 | 0 | PASS |
| PK-rebalance_proposal | primary_key | rebalance_proposal: primary key unique and non-null | 301 | 0 | PASS |
| PK-trade | primary_key | trade: primary key unique and non-null | 917 | 0 | PASS |
| PK-proposal_event | primary_key | proposal_event: primary key unique and non-null | 1408 | 0 | PASS |
| PK-drift_snapshot | primary_key | drift_snapshot: primary key unique and non-null | 4000 | 0 | PASS |
| DUP-drift_snapshot-portfolio_id_asset_class | duplicates | drift_snapshot: no duplicate (portfolio_id, asset_class) | 4000 | 0 | PASS |
| PK-post_trade_allocation | primary_key | post_trade_allocation: primary key unique and non-null | 1204 | 0 | PASS |
| DUP-post_trade_allocation-proposal_id_asset_class | duplicates | post_trade_allocation: no duplicate (proposal_id, asset_class) | 1204 | 0 | PASS |
| ID-investor_profile-investor_id | id_format | investor_profile.investor_id matches INV-\d{6} | 900 | 0 | PASS |
| ID-portfolio-portfolio_id | id_format | portfolio.portfolio_id matches PORT-INV-\d{6}-\d{2} | 1000 | 0 | PASS |
| ID-instrument-instrument_id | id_format | instrument.instrument_id matches INS-\d{6} | 300 | 0 | PASS |
| ID-market_price-price_id | id_format | market_price.price_id matches PX-INS-\d{6}-\d{8} | 75000 | 0 | PASS |
| ID-holding-holding_id | id_format | holding.holding_id matches HOLD-PORT-INV-\d{6}-\d{2}-INS-\d{6} | 5000 | 0 | PASS |
| ID-fee_schedule-fee_schedule_id | id_format | fee_schedule.fee_schedule_id matches FEE-\d{6} | 24 | 0 | PASS |
| ID-constraint-constraint_id | id_format | constraint.constraint_id matches CON-\d{6} | 27 | 0 | PASS |
| ID-portfolio_constraint-portfolio_constraint_id | id_format | portfolio_constraint.portfolio_constraint_id matches PC-\d{6} | 1720 | 0 | PASS |
| ID-rebalance_proposal-proposal_id | id_format | rebalance_proposal.proposal_id matches RB-\d{4}-\d{6} | 301 | 0 | PASS |
| ID-trade-trade_id | id_format | trade.trade_id matches TRD-RB-\d{4}-\d{6}-\d{2} | 917 | 0 | PASS |
| ID-proposal_event-event_id | id_format | proposal_event.event_id matches EVT-\d{6} | 1408 | 0 | PASS |
| ID-portfolio-composition | id_format | portfolio_id = PORT-<investor_id>-<seq> | 1000 | 0 | PASS |
| ID-holding-composition | id_format | holding_id = HOLD-<portfolio_id>-<instrument_id> | 5000 | 0 | PASS |
| FK-portfolio-investor_id | foreign_key | portfolio.investor_id -> investor_profile.investor_id | 1000 | 0 | PASS |
| FK-market_price-instrument_id | foreign_key | market_price.instrument_id -> instrument.instrument_id | 75000 | 0 | PASS |
| FK-holding-portfolio_id | foreign_key | holding.portfolio_id -> portfolio.portfolio_id | 5000 | 0 | PASS |
| FK-holding-instrument_id | foreign_key | holding.instrument_id -> instrument.instrument_id | 5000 | 0 | PASS |
| FK-target_allocation-portfolio_id | foreign_key | target_allocation.portfolio_id -> portfolio.portfolio_id | 4396 | 0 | PASS |
| FK-portfolio_constraint-portfolio_id | foreign_key | portfolio_constraint.portfolio_id -> portfolio.portfolio_id | 1720 | 0 | PASS |
| FK-portfolio_constraint-constraint_id | foreign_key | portfolio_constraint.constraint_id -> constraint.constraint_id | 1720 | 0 | PASS |
| FK-rebalance_proposal-portfolio_id | foreign_key | rebalance_proposal.portfolio_id -> portfolio.portfolio_id | 301 | 0 | PASS |
| FK-trade-proposal_id | foreign_key | trade.proposal_id -> rebalance_proposal.proposal_id | 917 | 0 | PASS |
| FK-trade-portfolio_id | foreign_key | trade.portfolio_id -> portfolio.portfolio_id | 917 | 0 | PASS |
| FK-trade-instrument_id | foreign_key | trade.instrument_id -> instrument.instrument_id | 917 | 0 | PASS |
| FK-trade-fee_schedule_id | foreign_key | trade.fee_schedule_id -> fee_schedule.fee_schedule_id | 917 | 0 | PASS |
| FK-proposal_event-proposal_id | foreign_key | proposal_event.proposal_id -> rebalance_proposal.proposal_id | 1408 | 0 | PASS |
| FK-drift_snapshot-portfolio_id | foreign_key | drift_snapshot.portfolio_id -> portfolio.portfolio_id | 4000 | 0 | PASS |
| FK-post_trade_allocation-proposal_id | foreign_key | post_trade_allocation.proposal_id -> rebalance_proposal.proposal_id | 1204 | 0 | PASS |
| REQ-investor_profile | required | investor_profile: required fields populated | 900 | 0 | PASS |
| ENUM-investor_profile | enum | investor_profile: values within allowed enums | 900 | 0 | PASS |
| REQ-portfolio | required | portfolio: required fields populated | 1000 | 0 | PASS |
| ENUM-portfolio | enum | portfolio: values within allowed enums | 1000 | 0 | PASS |
| REQ-instrument | required | instrument: required fields populated | 300 | 0 | PASS |
| ENUM-instrument | enum | instrument: values within allowed enums | 300 | 0 | PASS |
| REQ-market_price | required | market_price: required fields populated | 75000 | 0 | PASS |
| ENUM-market_price | enum | market_price: values within allowed enums | 75000 | 0 | PASS |
| REQ-holding | required | holding: required fields populated | 5000 | 0 | PASS |
| ENUM-holding | enum | holding: values within allowed enums | 5000 | 0 | PASS |
| REQ-target_allocation | required | target_allocation: required fields populated | 4396 | 0 | PASS |
| ENUM-target_allocation | enum | target_allocation: values within allowed enums | 4396 | 0 | PASS |
| REQ-fee_schedule | required | fee_schedule: required fields populated | 24 | 0 | PASS |
| ENUM-fee_schedule | enum | fee_schedule: values within allowed enums | 24 | 0 | PASS |
| REQ-constraint | required | constraint: required fields populated | 27 | 0 | PASS |
| ENUM-constraint | enum | constraint: values within allowed enums | 27 | 0 | PASS |
| REQ-portfolio_constraint | required | portfolio_constraint: required fields populated | 1720 | 0 | PASS |
| ENUM-portfolio_constraint | enum | portfolio_constraint: values within allowed enums | 1720 | 0 | PASS |
| REQ-rebalance_proposal | required | rebalance_proposal: required fields populated | 301 | 0 | PASS |
| ENUM-rebalance_proposal | enum | rebalance_proposal: values within allowed enums | 301 | 0 | PASS |
| REQ-trade | required | trade: required fields populated | 917 | 0 | PASS |
| ENUM-trade | enum | trade: values within allowed enums | 917 | 0 | PASS |
| REQ-proposal_event | required | proposal_event: required fields populated | 1408 | 0 | PASS |
| ENUM-proposal_event | enum | proposal_event: values within allowed enums | 1408 | 0 | PASS |
| REQ-drift_snapshot | required | drift_snapshot: required fields populated | 4000 | 0 | PASS |
| ENUM-drift_snapshot | enum | drift_snapshot: values within allowed enums | 4000 | 0 | PASS |
| REQ-post_trade_allocation | required | post_trade_allocation: required fields populated | 1204 | 0 | PASS |
| ENUM-post_trade_allocation | enum | post_trade_allocation: values within allowed enums | 1204 | 0 | PASS |
| DATE-001 | date_order | investor created_date < portfolio inception_date <= as_of | 1000 | 0 | PASS |
| DATE-002 | date_order | inception_date <= holding acquired_date <= as_of | 5000 | 0 | PASS |
| DATE-003 | date_order | target effective ranges ordered; one ACTIVE version, earlier versions SUPERSEDED | 4396 | 0 | PASS |
| DATE-004 | date_order | instrument listing_date before first price_date | 300 | 0 | PASS |
| DATE-005 | date_order | kyc_expiry_date < as_of iff kyc_status = EXPIRED | 900 | 0 | PASS |
| DEP-001 | dependency | portfolio FROZEN iff investor KYC EXPIRED | 1000 | 0 | PASS |
| DATE-006 | date_order | all price dates are weekdays | 75000 | 0 | PASS |
| PX-001 | arithmetic | close_price null iff MISSING | 75000 | 0 | PASS |
| PX-002 | coverage | every instrument has 250 daily price rows | 300 | 0 | PASS |
| HLD-001 | arithmetic | holding price_used/date/age equals last observed MarketPrice | 5000 | 0 | PASS |
| HLD-002 | arithmetic | holding stale flag = age > threshold | 5000 | 0 | PASS |
| HLD-003 | arithmetic | market_value = quantity x price_used | 5000 | 0 | PASS |
| HLD-004 | arithmetic | current_weight_pct = market_value / portfolio total | 5000 | 0 | PASS |
| HLD-005 | arithmetic | current holding weights sum to 100% per portfolio | 1000 | 0 | PASS |
| HLD-006 | coverage | every portfolio holds all four asset classes | 1000 | 0 | PASS |
| DRF-001 | arithmetic | drift snapshot recomputed from holdings and targets | 4000 | 0 | PASS |
| DRF-002 | dependency | every breaching portfolio has a proposal | 1000 | 0 | PASS |
| CON-001 | dependency | is_excluded flag matches firm-wide EXCLUDED_INSTRUMENT constraints | 300 | 0 | PASS |
| TRD-001 | arithmetic | notional = quantity x price_used | 917 | 0 | PASS |
| TRD-002 | arithmetic | holding_quantity_before equals Holding table | 917 | 0 | PASS |
| TRD-003 | dependency | trade portfolio equals proposal portfolio | 917 | 0 | PASS |
| TRD-004 | arithmetic | trade quantity is a multiple of lot size | 917 | 0 | PASS |
| PRP-001 | arithmetic | proposal totals reconcile to trades and holdings | 301 | 0 | PASS |
| PRP-002 | arithmetic | post-trade allocation recomputed from holdings, trades and prices | 301 | 0 | PASS |
| PRP-003 | coverage | BLOCKED proposals have no trades; frozen portfolios are blocked | 301 | 0 | PASS |
| LIF-001 | lifecycle | event chain: first event DRAFT, from_status continuity, allowed transitions | 1408 | 0 | PASS |
| LIF-002 | lifecycle | event timestamps non-decreasing per proposal | 1408 | 0 | PASS |
| LIF-003 | lifecycle | proposal.status equals latest event to_status | 301 | 0 | PASS |
| LIF-004 | lifecycle | trade_status mapped from proposal status | 917 | 0 | PASS |
| LIF-005 | lifecycle | event timestamps not before proposal generated_at | 1408 | 0 | PASS |

## Business-rule findings (include injected anomalies)

| Issue type | Count |
|---|---|
| EXCLUDED_INSTRUMENT_RECOMMENDED | 15 |
| FEE_OMITTED | 75 |
| LIQUIDITY_CAP_BREACH | 2 |
| STALE_PRICE_UNFLAGGED | 15 |
| TARGET_WEIGHTS_NOT_100 | 20 |
| TRADE_EXCEEDS_HOLDING | 15 |
| TURNOVER_CAP_BREACH | 8 |

## Rule-based detector vs ground truth

| Issue type | TP | FP | FN | Precision | Recall |
|---|---|---|---|---|---|
| TARGET_WEIGHTS_NOT_100 | 20 | 0 | 0 | 1.0 | 1.0 |
| TRADE_EXCEEDS_HOLDING | 15 | 0 | 0 | 1.0 | 1.0 |
| EXCLUDED_INSTRUMENT_RECOMMENDED | 15 | 0 | 0 | 1.0 | 1.0 |
| FEE_OMITTED | 75 | 0 | 0 | 1.0 | 1.0 |
| STALE_PRICE_UNFLAGGED | 15 | 0 | 0 | 1.0 | 1.0 |

Decision agreement with expected decisions: 0.98
