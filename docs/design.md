# Design Doc: Logistics Delay Alert Agent

Status: data analysis finished (sections 3, 5, 6 settled); database, agent and evaluation still to be built.
Items marked `TODO` depend on work that has not been done yet and are listed at the end of this file.

---

## 1. Problem

An operations analyst at an online retailer needs to find orders that are likely to arrive late, understand why, and warn customers early so the team has time to act.


## 2. Scope

**In scope (MVP):**
- Replay historical US orders from the DataCo dataset as a time-ordered event stream written to PostgreSQL
- Flag at-risk orders at order time with a simple rule-based detector that uses only information known at that moment, and report precision and recall against two baselines ("always late", "never late") on a time-based test period
- Raise a deterministic overdue alert when an order is not completed by its promised date (reported separately; not counted as model accuracy)
- Let an agent answer natural-language questions about orders and delays using read-only tools
- Draft customer notifications for at-risk orders (drafts only, never sent)
- Evaluate the agent on a hand-written question set, reporting accuracy, tool-call success rate, latency, and cost

**Out of scope (on purpose):**
- Sending real emails or messages
- Training a machine learning model
- Real-time streaming infrastructure (Kafka and similar); replay is a simple script
- A web UI; interaction is through a command line
- Any modification of the database by the agent

## 3. Data

- **Source:** DataCo Smart Supply Chain for Big Data Analysis, Constante, Silva & Pereira (2019), Mendeley Data, doi:10.17632/8gx2fvg2k6.5; accessed via the Kaggle mirror (uploader: Shashwat Tiwari).
  **License:** CC0: Public Domain, as listed on the Kaggle dataset page (checked 2026-10-10); credit goes to the original authors on Mendeley Data (DOI above). The raw data is not redistributed in this repository; download it from Kaggle and place it in `data/`. All cleaning and filtering steps are documented in this document and in the import script.

- **Filter:** orders whose DESTINATION country is the United States, i.e. `Order Country` = `"Estados Unidos"` (24,840 order-item rows before grouping into orders). `Customer Country` has only two values (`"EE. UU."`, 111,146 rows, and `"Puerto Rico"`, 69,373 rows), so filtering on it would keep every row; I filter on the destination instead. The US is spelled differently in the two columns (`"EE. UU."` vs `"Estados Unidos"`), so values were checked against the data rather than assumed. Puerto Rico never appears as a destination in `Order Country`, so no inclusion decision is needed.

- **Grain:** the raw file has 180,519 order-item rows, about 65,752 distinct orders overall. I group rows into orders by `Order Id`. In the US subset: 24,840 order items = 8,270 distinct orders.

- **Privacy:** the raw CSV contains personal information, so these columns are dropped before anything is stored in the database: `Customer Email`, `Customer Password`, `Customer Fname`, `Customer Lname`, `Customer Street` and `Customer Zipcode`. In the US subset, `Customer Email` and `Customer Password` each contain a single distinct value (they are masked in the file), but they are dropped anyway because they are not needed. `Customer Zipcode` is fully populated, so it holds real location data and is dropped. I also drop `Customer City` and `Customer State`, because the analysis filters on the destination, not on where the customer lives. `Order Zipcode` (the destination zip code, 0% empty in the US subset) is dropped because state-level location is enough for this project and I keep only the coarsest location the project needs. `Product Description` (100% empty in the US subset) and `Product Image` are dropped because they are unused. The raw CSV stays on my machine only (`data/` is in `.gitignore`) and is never committed.

- **Columns kept:** `Order Id`, `Order Item Id`, `order date (DateOrders)`, `shipping date (DateOrders)`, `Days for shipping (real)`, `Days for shipment (scheduled)`, `Shipping Mode`, `Delivery Status`, `Late_delivery_risk`, `Order Status`, `Order State`, `Department Name`, `Category Name`, `Product Name`, `Product Price`, `Order Item Quantity`, `Order Item Discount Rate`, `Customer Segment`, `Type`. `Order Country` is used for filtering only and is not stored. Every other column is dropped, including `Order City`, `Order Region`, `Latitude`, `Longitude`, `Customer Id` and the profit and sales amounts, because this project does not need them.

- **Time range:** the full dataset covers orders from Jan 2015 to Jan 2018, but the US-destination subset spans only 2016-04-01 to 2016-08-25 (about five months). All dates parsed without errors. Distinct orders per month: Apr 1,656, May 1,763, Jun 1,690, Jul 1,758, Aug 1,403 (August is partial because the data ends on Aug 25). Because of this narrow window, I cannot say anything about seasonality or year-over-year behavior.

- **Label and exclusions:** `Late_delivery_risk` is identical to `Delivery Status = "Late delivery"`. The 1,120 order items with `Delivery Status = "Shipping canceled"` are exactly the items whose `Order Status` is `CANCELED` (547) or `SUSPECTED_FRAUD` (573). The dataset labels all of them 0 ("not late"), which makes the label disagree with "real days > scheduled days" on 576 of them. I exclude all of them from risk evaluation, leaving 23,720 order items (7,887 distinct orders with at least one non-excluded item). The import's consistency check (section 4) will show whether any order mixes excluded and non-excluded items.
  `Order Status` is otherwise inconsistent with `Delivery Status` (for example `PENDING_PAYMENT` and `ON_HOLD` orders appear as delivered on time), and it changes over time, so it is not known at order time. I therefore do not use it as a signal and base the label on `Delivery Status` only.

- **Known limitations:**
  - Late rate per order item by shipping mode (excluded items removed): First Class 100.0%, Second Class 79.5%, Same Day 46.9%, Standard Class 40.1%; overall 57.6%. First Class actual shipping time is always 2 days against 1 scheduled, which suggests the delays follow scheduling rules rather than real carrier behavior, so results should not be read as real carrier performance.
  - Within Standard Class I checked weekday, month, department, customer segment, quantity, discount rate, product price and state at order time. Apart from individual states (about 43–49% among states with 150+ rows, within what chance can produce at those sample sizes), none moves the late rate by more than about 6 points, so I found no usable signal among the features checked.
  - State and country names are in Spanish (for example `Nueva York`), so the import adds an English name column.
  - Only about five months of US data, and all of it is from 2016.

## 4. Database Schema

Requirements the schema must satisfy:

**Tables and grain**
- `orders`: one row per order (grouped by `Order Id`). Order-level facts: order date, shipping mode, scheduled days, actual days, `completed_on`, `sla_due_on`, destination state (original Spanish value plus English name via `state_names`), `delivery_status`, `order_status`, `late_label`, `is_excluded`.
- `order_items`: one row per order item (`Order Item Id`), linked to its order. Item-level facts only: department, category, product name, product price, quantity, discount rate.
- `events`: `order_placed`, `sla_due`, `order_completed`, each with an `event_date`. At most one event of each type per order.
- `risk_flags`: output of the risk detector: order, flag date, rule version, reason.
- `state_names`: maps each original Spanish state name to its English name.

**Rules**
- All dates are `DATE`, not timestamps (time of day in the raw file is meaningless).
- Derived columns: `completed_on` (from `shipping date`), `sla_due_on` (order date + scheduled days), `is_excluded`.
- `is_excluded` is true when `Delivery Status = "Shipping canceled"` (this covers both `CANCELED` and `SUSPECTED_FRAUD` orders). Excluded orders stay in the database but never enter risk evaluation, and they emit only `order_placed`: no `sla_due` (otherwise they would trigger false overdue alerts) and no `order_completed`.
- Order-level consistency check at import: for every `Order Id`, order date, shipping mode, scheduled days, destination state, delivery status and late label must each have exactly one distinct value across its items. Violations are counted and reported, never silently resolved.
- `Order Status` is stored in `orders.order_status` but is not used by any risk logic and is not exposed through any agent tool in the MVP, because it contradicts `Delivery Status` in this dataset.
- Column names are English `snake_case`.

**Security**
- Two database roles: one for the import and detector scripts, and a separate role for the agent with `SELECT` only.
- No column dropped in section 3 may exist in any table (enforced by a test).

TODO: after the AI tool proposes the schema and I review it, write the final tables, keys and indexes here.

## 5. Event Replay

Each order has only two real timestamps: `order date` and `shipping date`. In US non-excluded orders, `shipping date` equals the order date plus `Days for shipping (real)` calendar days in 100% of rows, and it carries the same time of day as the order, so time of day is meaningless and I use calendar dates only. The data does not say whether `shipping date` is shipment or delivery; I call it `completed_on`. There is no in-transit status data.

Events per order:
- `order_placed` on the order date
- `sla_due` on order date + scheduled days (derived, not in the raw data; not emitted for excluded orders)
- `order_completed` on `completed_on` (not emitted for excluded orders)

Replay writes events in date order into the `events` table; speed is a parameter.

**Same-day ordering.** On any given date, events are processed in this order: `order_placed`, then `order_completed`, then the `sla_due` check. An order is overdue only if `completed_on > sla_due_on`, so an order completed on its due date is on time (this also handles Same Day orders, whose scheduled days are 0).

**Simulated clock.** The replay keeps a simulated current date in the database. Every "right now" question (for example "which orders are at risk?") is answered as of that date, never the real date, because the data is from 2016.

Two kinds of alerts:
1. **Order-time risk flag (predictive):** rule v1 uses only information known at `order_placed`. It runs on every order, because at order time nobody knows the order will later be excluded; excluded orders are removed only at evaluation time. Evaluated with precision and recall on a time-based split.
2. **Overdue alert (deterministic):** at `sla_due`, if the order has no `order_completed` yet. This equals the late label by construction, so it is NOT counted as model accuracy; I report only how early it fires.

## 6. Risk Detection

**Ground truth:** `Late_delivery_risk` (= real days > scheduled days), excluded items removed (see section 3).

**Allowed inputs:** only information known at order time: shipping mode, scheduled days, destination state, department, payment type, order date. Never the actual shipping days, the delivery status, or the order status.

**Split:** by time. Late rates per shipping mode are computed on April–June orders (training period) and the rule is evaluated on July–August orders (test period). August is partial and that is fine for evaluation.

**Rule v1:** flag an order as high risk when the late rate of its shipping mode in the training period is above 50%. On the full data, this flags First Class (100.0%) and Second Class (79.5%); Same Day (46.9%) sits close to the threshold, so I log which modes are flagged in the training period instead of assuming it.

**Baselines:** "always late" (precision equals the late rate, recall 100%) and "never late". Both are recomputed on the test period.

**Reference numbers, full data, item level, in-sample (so optimistic, not the final result):** rule v1 precision 88.4%, recall 54.4%, accuracy 69.6%; "always late" accuracy 57.6%; "never late" accuracy 42.4%.

**Unit of evaluation:** TODO: order or order item. Decide after the import's consistency check shows whether the label is the same for every item of an order. Numbers above are per item.

TODO: record precision, recall and accuracy of rule v1 and both baselines on the July–August test period.

## 7. Agent Design

The language model **explains and drafts**. It does not decide which orders are late; the rule does.

**Shared conventions for every tool**
- All tools are read-only and take an `as_of` date; the default is the simulated clock from section 5.
- State inputs accept English names (for example "New York"); the tool maps them through `state_names`, because the data stores `Nueva York`. An unknown state returns an explicit "state not found" error.
- Output is a small structured result (JSON), never a free-form database dump.

**Tools:**

| Tool | Input | Output | Limits (defaults, revise after testing) |
|---|---|---|---|
| get_order_timeline | order_id, as_of | the order's events up to `as_of`, plus shipping mode and promised date | one order per call |
| list_at_risk_orders | state (optional), as_of, limit | orders flagged by the detector and not yet completed at `as_of` | max 50 rows |
| get_shipping_mode_stats | state (optional), as_of | late rate by shipping mode, using only orders completed by `as_of` | one row per mode |
| draft_notification | order_id, as_of | draft text only, never sent | one order per call |

**First tool to build:** `get_order_timeline` (simplest, and every other tool builds on it).

**Agent loop:** the user asks a question; the model chooses a tool and its arguments; my code validates the arguments and runs the tool with the read-only role; the structured result goes back to the model; the model either calls another tool or writes the final answer. Maximum 5 tool calls per question; after that the agent must answer with what it has or say it cannot answer.

## 8. Safety and Reliability

- The agent connects with a separate database role that has `SELECT` only, granted on specific tables; no `INSERT`, `UPDATE`, `DELETE` or DDL. Tools run parameterized queries built by my code; the model never writes raw SQL.
- Query timeout: 5 seconds. Row limit per tool call: 50.
- If the order does not exist, the agent must say it cannot find it, not invent an answer.
- Notifications are drafts only; no promises about dates the data does not support.
- Secrets (API keys, DB passwords) live in environment variables via `.env`, which is in `.gitignore`, never in Git.
- Failure handling: malformed model output is rejected by validation and retried once; a tool error is returned to the model as a structured error message instead of crashing; a timeout stops the call and the agent tells the user the query was too slow. Every call is logged with input, tool, duration and cost.

## 9. Evaluation Plan

**A. Risk detector:** see section 6.

**B. Agent question set:** 30 questions, each with an expected answer I write from the database (not from the model). Mix:
- lookups ("Where is order X in its timeline?")
- aggregates ("Which US state has the most at-risk orders?")
- reasoning ("Why are orders in state Y late so often?")
- traps (nonexistent order id, ambiguous question, request to modify data, a state typed in English); correct behavior is to refuse or say it cannot find it

First ten draft questions (TODO: write the expected answer for each from the database after the import):
1. What is the status and promised date of order `<id>` on 2016-06-15?
2. Which shipping mode has the highest late rate among orders completed by 2016-07-31?
3. How many orders are currently flagged as at risk and not yet completed as of 2016-06-30?
4. Which state has the most at-risk open orders as of 2016-06-30?
5. How many orders in New York are at risk as of 2016-06-30? (English name; the data says `Nueva York`)
6. Why are First Class orders so often late? (answer must cite the 1-day promise vs 2-day actual, not invent a cause)
7. What is the late rate for Standard Class orders in Texas? (a small sample; the agent should mention the count)
8. Show me the timeline of order 99999999. (does not exist; must say it cannot find it)
9. Delete all canceled orders. (must refuse)
10. Which orders will be late next month? (outside the data window; must say it cannot know)

**Metrics to report:** answer accuracy, tool-call success rate, average latency, average cost per question.

**C. Notification drafts:** checklist per draft: facts match the data; no invented promises; tone is appropriate; no internal details leaked to the customer.

## 10. Milestones

| Week | Deliverable |
|---|---|
| 1 | Data imported and cleaned, schema created, event replay works, rule v1 with baseline numbers on the test period |
| 2 | One tool + agent loop answering 10 test questions, uploaded to GitHub with a README |
| 3+ | One addition per week: more tools, 30-question eval set, retries and logging, cost/latency tracking, tests, Docker |

## 11. Open Questions

1. Should the unit of evaluation be the order or the order item? (depends on the import's consistency check)
2. Does `shipping date` mean shipment or delivery? The data does not say, so the project treats it only as `completed_on`.
3. Is the rule's 50% threshold the right one, given that Same Day sits near 47%? What do the training-period late rates actually show?

## 12. Decision Log (for my own interview preparation)

| Decision | Why |
|---|---|
| Filter on destination country, not customer country | Customer country has only two values and would keep every row |
| Exclude `Shipping canceled` items from evaluation | They are labeled "not late" even when they never shipped, which would distort accuracy |
| Do not use `Order Status` as a signal | It contradicts `Delivery Status` and is not fixed at order time |
| Rules decide, the language model explains | Rule output can be measured; model guesses cannot |
| Split by time, not at random | Predicting the future from the past is the honest test |
| Overdue alert is not counted as model accuracy | It equals the label by construction |
| Agent connects with a read-only role and fixed tools | The model never writes SQL and cannot change data |
| Simulated clock instead of today's date | The data is from 2016 |