-- ============================================================================
--  (!) DESTRUCTIVE — CONTINUOUS-INTEGRATION USE ONLY  (!)
-- ----------------------------------------------------------------------------
--  This fixture DROPS and recreates every raw.* source table before loading a
--  small, self-consistent dataset, so CI can run `dbt build` (models +
--  snapshots + data tests) against real-shaped data instead of only compiling.
--
--  In the DEV database the `raw` schema holds the REAL source tables AND all
--  dbt models — running this there would DESTROY them. It is meant ONLY for the
--  disposable Postgres that GitHub Actions spins up
--  (see .github/workflows/dbt_ci.yml). Note the CI database is also named
--  `store_local`, so a database-name check cannot tell CI apart from dev —
--  hence the explicit opt-in guard below.
--
--  GUARD: this script refuses to run unless the caller explicitly opts in by
--  setting the custom GUC `ci.fixture_ok` to '1' in the same psql session:
--      psql ... -c "SET ci.fixture_ok = '1';" -f ci/fixture/seed_raw.sql
--  A plain `psql -f seed_raw.sql` (e.g. an accidental run against dev) aborts
--  here, before dropping anything.
-- ============================================================================

do $guard$
begin
    if coalesce(current_setting('ci.fixture_ok', true), '') <> '1' then
        raise exception
            using message = 'seed_raw.sql is DESTRUCTIVE (drops raw.*) and is CI-only.',
                  hint    = 'Run only against a disposable DB, after: SET ci.fixture_ok = ''1'';';
    end if;
end
$guard$;

-- CI fixture — populates every raw.* source table the dbt project reads, so a
-- Pull Request can run `dbt build` (run + test), not just parse/compile.
--
-- All dates are expressed as `current_date - N` so the fixture is always "recent"
-- relative to whenever CI runs: dim_date's recursive spine (macros/create_dim_date_new.sql)
-- starts at min(raw.documents.recordingdate) and walks to current_date, so keeping the
-- oldest row ~40 days back keeps that spine small (~40 rows) forever, instead of growing
-- by one row every day if the dates were hardcoded to a fixed calendar date.
--
-- Deliberately encodes the known edge cases the project's own tests/docs call out, so CI
-- exercises them for real instead of trusting a single dummy row:
--   * item_id 2006 exists in raw.inventory but NOT in raw.items (the documented "orphan
--     item_id" case — see _store_data__sources.yml — exercised through dim_product's
--     '(unmapped item)' / '(uncategorized)' placeholders).
--   * one inventory row for item 2001 under a different card_id/cardsgroup, to prove the
--     stg_store_data__inventory filter (card_id = 11 and cardsgroup = 3) actually filters.
--   * one return document (negative total) so is_return / int_sales__returns has a row.
--   * one document whose only receipt line has account_number_moreinfo = '2' (filtered by
--     int_sales__line_items), so it silently disappears downstream by design — proves the
--     filter doesn't crash the join, it just excludes the document.
--   * a cross-midnight shift and a manual-correction (movementtype 91/92) shift for
--     employee 103, so is_cross_midnight / is_manual_correction both get exercised.
--   * an overtime shift (9.5h) and a double-overtime shift (11h) for employee 102, so the
--     ot125/ot150 payroll tiers in int_workforce__shift_pay both get exercised.
--   * every stock_status (HEALTHY, OUT_OF_STOCK, STOCKOUT_RISK, OVERSTOCK, DEAD_STOCK) and
--     every velocity_band (FAST, STEADY, SLOW, NO_RECENT_SALES, OUT_OF_STOCK) appears at
--     least once, and one sale sits outside the 30-day window to prove the window filter
--     in int_inventory__product_velocity actually excludes it.
--
-- Employees are fixed at 101/102/103 to match seeds/employee_wages.csv, whose 3 rows are
-- also what makes the sales_rank/hours_rank/efficiency_rank range tests (1..3) in
-- rpt_workforce_productivity_summary meaningful — do not add a 4th employee here without
-- also adding a wage row, or hourly_rate/total_pay will come back null and fail not_null.

create schema if not exists raw;

-- ── 1. items ─────────────────────────────────────────────────────────────────
drop table if exists raw.items;
create table raw.items (
    item_id      integer,
    itemdesc     text,
    itemtype     integer,
    costperunit  numeric(18, 2),
    price1       numeric(18, 2)
);

insert into raw.items (item_id, itemdesc, itemtype, costperunit, price1) values
    (2001, 'Cola 1.5L',            1, 4.50, 8.90),
    (2002, 'Energy Drink 250ml',   1, 3.20, 7.50),
    (2003, 'Potato Chips 150g',    2, 2.80, 6.90),
    (2004, 'Canned Tuna 160g',     2, 5.10, 9.90),
    (2005, 'Greek Yogurt 500g',    3, 6.00, 11.90);
    -- NOTE: item 2006 is intentionally absent here — see raw.inventory below.

-- ── 2. itemtypes ─────────────────────────────────────────────────────────────
drop table if exists raw.itemtypes;
create table raw.itemtypes (
    type_id  integer,
    typedesc text
);

insert into raw.itemtypes (type_id, typedesc) values
    (1, 'Beverages'),
    (2, 'Snacks'),
    (3, 'Dairy');

-- ── 3. inventory ─────────────────────────────────────────────────────────────
drop table if exists raw.inventory;
create table raw.inventory (
    item_id            integer,
    openinginventory   numeric(18, 3),
    inventorybalance   numeric(18, 3),
    countedinventory   numeric(18, 3),
    card_id            integer,
    cardsgroup         integer
);

insert into raw.inventory
    (item_id, openinginventory, inventorybalance, countedinventory, card_id, cardsgroup)
values
    -- item_id | opening | balance | counted | card_id | cardsgroup | intended outcome
    (2001,  50,  40,  40, 11, 3),  -- HEALTHY   / STEADY
    (2002,  25,   0,   0, 11, 3),  -- OUT_OF_STOCK
    (2003,  35,  20,  20, 11, 3),  -- STOCKOUT_RISK / FAST
    (2004, 130, 100, 100, 11, 3),  -- OVERSTOCK / SLOW
    (2005,  55,  50,  50, 11, 3),  -- DEAD_STOCK / NO_RECENT_SALES
    (2006,  45,  30,  30, 11, 3),  -- HEALTHY / STEADY  (orphan — no raw.items row)
    (2001, 999, 999, 999,  1, 1);  -- noise row: wrong card_id/cardsgroup, must be filtered
                                    -- out by stg_store_data__inventory (proves the filter
                                    -- works and item_id stays unique post-filter)

-- ── 4. documents ─────────────────────────────────────────────────────────────
drop table if exists raw.documents;
create table raw.documents (
    document_id             integer,
    recordingdate           date,
    printtime               integer,   -- seconds since midnight
    documenttype            integer,
    generaltotalincludevat  numeric(18, 2),
    s__sequence             integer,
    _pipeline_loaded_at     timestamp
);

insert into raw.documents
    (document_id, recordingdate, printtime, documenttype, generaltotalincludevat,
     s__sequence, _pipeline_loaded_at)
values
    (9001, current_date - 1,  33300, 1,  106.80, 9001, current_timestamp),
    (9002, current_date - 6,  45000, 1,  106.80, 9002, current_timestamp),
    (9003, current_date - 12, 53100, 1,  106.80, 9003, current_timestamp),
    (9004, current_date - 18, 65400, 1,  106.80, 9004, current_timestamp),
    (9005, current_date - 27, 72300, 1,  106.80, 9005, current_timestamp),
    (9006, current_date - 3,  36000, 1,   37.50, 9006, current_timestamp),
    (9007, current_date - 14, 40800, 1,   37.50, 9007, current_timestamp),
    (9008, current_date - 24, 60000, 1,   37.50, 9008, current_timestamp),
    (9009, current_date,      34200, 1,  207.00, 9009, current_timestamp),
    (9010, current_date - 8,  47700, 1,  256.50, 9010, current_timestamp),  -- multi-line
    (9011, current_date - 15, 64200, 1,  207.00, 9011, current_timestamp),
    (9012, current_date - 25, 69600, 1,  207.00, 9012, current_timestamp),
    (9013, current_date - 20, 43200, 1,   49.50, 9013, current_timestamp),
    (9014, current_date - 40, 36000, 1,   95.20, 9014, current_timestamp),  -- outside 30d window
    (9015, current_date - 2,  32400, 1,   82.50, 9015, current_timestamp),
    (9016, current_date - 11, 55800, 1,   82.50, 9016, current_timestamp),
    (9017, current_date - 21, 67500, 1,   82.50, 9017, current_timestamp),
    (9018, current_date - 9,  46800, 1,   26.70, 9018, current_timestamp),  -- payment_type = 2
    (9019, current_date - 4,  57600, 1,  -17.80, 9019, current_timestamp),  -- return (negative total)
    (9020, current_date - 6,  30600, 1,    8.90, 9020, current_timestamp);  -- excluded (see receiptlines)

-- ── 5. documentlines ─────────────────────────────────────────────────────────
drop table if exists raw.documentlines;
create table raw.documentlines (
    document_id           integer,
    line_id               integer,
    item_id               integer,
    details               text,
    itemsqty              numeric(18, 3),
    totalperline_incvat   numeric(18, 2)
);

insert into raw.documentlines
    (document_id, line_id, item_id, details, itemsqty, totalperline_incvat)
values
    (9001, 1, 2001, 'Cola 1.5L',          12,  106.80),
    (9002, 1, 2001, 'Cola 1.5L',          12,  106.80),
    (9003, 1, 2001, 'Cola 1.5L',          12,  106.80),
    (9004, 1, 2001, 'Cola 1.5L',          12,  106.80),
    (9005, 1, 2001, 'Cola 1.5L',          12,  106.80),
    (9006, 1, 2002, 'Energy Drink 250ml',  5,   37.50),
    (9007, 1, 2002, 'Energy Drink 250ml',  5,   37.50),
    (9008, 1, 2002, 'Energy Drink 250ml',  5,   37.50),
    (9009, 1, 2003, 'Potato Chips 150g',  30,  207.00),
    (9010, 1, 2003, 'Potato Chips 150g',  30,  207.00),
    (9010, 2, 2004, 'Canned Tuna 160g',    5,   49.50),
    (9011, 1, 2003, 'Potato Chips 150g',  30,  207.00),
    (9012, 1, 2003, 'Potato Chips 150g',  30,  207.00),
    (9013, 1, 2004, 'Canned Tuna 160g',    5,   49.50),
    (9014, 1, 2005, 'Greek Yogurt 500g',   8,   95.20),
    (9015, 1, 2006, 'Bottled Water 1L',   15,   82.50),
    (9016, 1, 2006, 'Bottled Water 1L',   15,   82.50),
    (9017, 1, 2006, 'Bottled Water 1L',   15,   82.50),
    (9018, 1, 2001, 'Cola 1.5L',           3,   26.70),
    (9019, 1, 2001, 'Cola 1.5L',          -2,  -17.80),
    (9020, 1, 2001, 'Cola 1.5L',           1,    8.90);

-- ── 6. receiptlines ──────────────────────────────────────────────────────────
drop table if exists raw.receiptlines;
create table raw.receiptlines (
    receipt_id               integer,
    paymenttype              integer,
    creditcardtype           integer,
    accountnumber_moreinfo   text
);

insert into raw.receiptlines (receipt_id, paymenttype, creditcardtype, accountnumber_moreinfo) values
    (9001, 1, null, null),
    (9002, 3,    1, null),
    (9003, 1, null, null),
    (9004, 3,    1, null),
    (9005, 1, null, null),
    (9006, 1, null, null),
    (9007, 3,    1, null),
    (9008, 1, null, null),
    (9009, 3,    1, null),
    (9010, 1, null, null),
    (9011, 3,    1, null),
    (9012, 1, null, null),
    (9013, 3,    1, null),
    (9014, 1, null, null),
    (9015, 1, null, null),
    (9016, 3,    1, null),
    (9017, 1, null, null),
    (9018, 2, null, null),        -- less-common but still-accepted payment_type
    (9019, 1, null, null),        -- return document's settlement line
    (9020, 1, null, '2');         -- filtered out -> document 9020 disappears downstream

-- ── 7. employeesattendance ───────────────────────────────────────────────────
drop table if exists raw.employeesattendance;
create table raw.employeesattendance (
    emplyee_id             integer,
    datesetting            date,
    hourtime               integer,   -- seconds since midnight
    movementtype           integer,   -- 1=IN, 2=OUT, 91=IN correction, 92=OUT correction
    attendancerecordingtype integer,
    front_office           text,
    mark                   text,
    exceeded               text,
    s__sequence            integer
);

insert into raw.employeesattendance
    (emplyee_id, datesetting, hourtime, movementtype, attendancerecordingtype,
     front_office, mark, exceeded, s__sequence)
values
    -- Employee 101 (Dana) — 10 regular 8h shifts (09:00-17:00)
    (101, current_date - 13, 32400, 1, 1, null, null, null, 10101),
    (101, current_date - 13, 61200, 2, 1, null, null, null, 10102),
    (101, current_date - 11, 32400, 1, 1, null, null, null, 10103),
    (101, current_date - 11, 61200, 2, 1, null, null, null, 10104),
    (101, current_date - 10, 32400, 1, 1, null, null, null, 10105),
    (101, current_date - 10, 61200, 2, 1, null, null, null, 10106),
    (101, current_date - 8,  32400, 1, 1, null, null, null, 10107),
    (101, current_date - 8,  61200, 2, 1, null, null, null, 10108),
    (101, current_date - 7,  32400, 1, 1, null, null, null, 10109),
    (101, current_date - 7,  61200, 2, 1, null, null, null, 10110),
    (101, current_date - 5,  32400, 1, 1, null, null, null, 10111),
    (101, current_date - 5,  61200, 2, 1, null, null, null, 10112),
    (101, current_date - 4,  32400, 1, 1, null, null, null, 10113),
    (101, current_date - 4,  61200, 2, 1, null, null, null, 10114),
    (101, current_date - 2,  32400, 1, 1, null, null, null, 10115),
    (101, current_date - 2,  61200, 2, 1, null, null, null, 10116),
    (101, current_date - 1,  32400, 1, 1, null, null, null, 10117),
    (101, current_date - 1,  61200, 2, 1, null, null, null, 10118),
    (101, current_date,      32400, 1, 1, null, null, null, 10119),
    (101, current_date,      61200, 2, 1, null, null, null, 10120),

    -- Employee 102 (Yossi) — 6 regular 6h shifts (10:00-16:00) + 1 OT125 (9.5h) + 1 OT150 (11h)
    (102, current_date - 21, 28800, 1, 1, null, null, null, 10201),  -- 08:00
    (102, current_date - 21, 68400, 2, 1, null, null, null, 10202),  -- 19:00 -> 11h (OT150)
    (102, current_date - 18, 36000, 1, 1, null, null, null, 10203),
    (102, current_date - 18, 57600, 2, 1, null, null, null, 10204),
    (102, current_date - 15, 36000, 1, 1, null, null, null, 10205),
    (102, current_date - 15, 57600, 2, 1, null, null, null, 10206),
    (102, current_date - 12, 36000, 1, 1, null, null, null, 10207),
    (102, current_date - 12, 57600, 2, 1, null, null, null, 10208),
    (102, current_date - 9,  28800, 1, 1, null, null, null, 10209),  -- 08:00
    (102, current_date - 9,  63000, 2, 1, null, null, null, 10210),  -- 17:30 -> 9.5h (OT125)
    (102, current_date - 6,  36000, 1, 1, null, null, null, 10211),
    (102, current_date - 6,  57600, 2, 1, null, null, null, 10212),
    (102, current_date - 3,  36000, 1, 1, null, null, null, 10213),
    (102, current_date - 3,  57600, 2, 1, null, null, null, 10214),
    (102, current_date,      36000, 1, 1, null, null, null, 10215),
    (102, current_date,      57600, 2, 1, null, null, null, 10216),

    -- Employee 103 (Noa) — part-time: 4 regular 5h shifts, 1 manual-correction shift
    -- (movementtype 91/92), 1 cross-midnight shift (22:00 -> next day 02:00)
    (103, current_date - 17, 36000, 1,  1, null, null, null, 10301),
    (103, current_date - 17, 54000, 2,  1, null, null, null, 10302),
    (103, current_date - 13, 36000, 1,  1, null, null, null, 10303),
    (103, current_date - 13, 54000, 2,  1, null, null, null, 10304),
    (103, current_date - 9,  36000, 91, 1, null, null, null, 10305),  -- manual correction IN
    (103, current_date - 9,  54000, 92, 1, null, null, null, 10306),  -- manual correction OUT
    (103, current_date - 5,  36000, 1,  1, null, null, null, 10307),
    (103, current_date - 5,  54000, 2,  1, null, null, null, 10308),
    (103, current_date - 2,  79200, 1,  1, null, null, null, 10309),  -- 22:00, cross-midnight start
    (103, current_date - 1,  7200,  2,  1, null, null, null, 10310),  -- 02:00 next day, cross-midnight end
    (103, current_date - 1,  36000, 1,  1, null, null, null, 10311),
    (103, current_date - 1,  54000, 2,  1, null, null, null, 10312);

-- ── 8. employeesselection_byentrance ─────────────────────────────────────────
drop table if exists raw.employeesselection_byentrance;
create table raw.employeesselection_byentrance (
    emplyeenumber   integer,
    longname        text
);

insert into raw.employeesselection_byentrance (emplyeenumber, longname) values
    (101, 'Dana Cohen'),
    (102, 'Yossi Levi'),
    (103, 'Noa Mizrahi');
