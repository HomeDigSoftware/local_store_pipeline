# CI/CD — A Beginner-to-Pro Guide (for this project)

> Written as a learning path. Read it top to bottom once; after that it doubles as a
> reference. Every abstract idea is tied back to **this repo** (`store_pipeline`: a
> dbt + Postgres + Python pipeline) so it stays concrete.

---

## Part 0 — The 60-second summary

**CI/CD is a robot that checks your code every time you change it, and (optionally)
ships it for you.**

- **CI = Continuous Integration** — every time you push code, an automated server
  *builds it and runs your tests*. If something broke, you find out in minutes,
  automatically, before it reaches anyone else.
- **CD = Continuous Delivery / Deployment** — once CI passes, the same robot
  *packages and releases* the new version (to a server, a database, a website…),
  either at the click of a button (Delivery) or fully automatically (Deployment).

For this project, CI means: *"every time I touch a dbt model, a server spins up a
clean Postgres, installs dbt, and verifies that the whole project still compiles and
all 182 tests are valid — without me lifting a finger."*

That's it. The rest of this document explains **why** that's worth doing, **what**
every word means, and **how** to build it.

---

## Part 1 — Why does CI/CD exist? (The problem it solves)

Imagine the project before any automation. Your workflow is:

1. Edit a dbt model on your laptop.
2. Run `uv run dbt run` and `uv run dbt test` manually.
3. If it looks fine, `git commit` and `git push`.

This works when it's just you, and when you *remember* to run the tests, and when
you *never* forget, and when your laptop's environment is *identical* to production.
That's four "ifs". Each one is a place where bugs sneak in. The classic failures:

- **"It works on my machine."** Your laptop has a package installed that the server
  doesn't. The code runs for you and breaks for everyone else.
- **"I forgot to run the tests."** You were in a hurry. A broken model reaches
  `main`. Now the next person who pulls is also broken.
- **"The change looked tiny."** You renamed a column in a staging model and didn't
  realize three downstream reports referenced it. `dbt run` would have caught it —
  but you didn't run the full build, only the one model.
- **"Two changes collided."** You and a teammate each changed something that worked
  in isolation but breaks when combined. Nobody ran the *combination*.

CI exists to make these **structurally impossible** instead of relying on discipline.
The robot never forgets, never rushes, and always runs in a clean, reproducible
environment that mirrors production. It turns *"I hope it still works"* into
*"the green checkmark proves it still works."*

> **The portfolio angle (important for you):** your repo is public on GitHub. A
> hiring manager who opens it and sees a green ✅ CI badge instantly knows: *this
> person tests their code and automates their checks.* That single badge is one of
> the strongest "this is a professional" signals a data/analytics project can show.

---

## Part 2 — The vocabulary (read this once, refer back forever)

These are the words that appear in every CI/CD conversation. Learn them and the
earlier recommendation becomes trivially readable.

### 2.1 Version control words

| Term | Plain meaning | In this repo |
|---|---|---|
| **Repository (repo)** | The project folder, tracked by Git, with full history. | `store_pipeline/`, hosted at `github.com/HomeDigSoftware/local_store_pipeline`. |
| **Commit** | A saved snapshot of changes with a message. | `git commit -m "test(dbt): stage 2 polishing"`. |
| **Branch** | A parallel line of work that doesn't touch `main` until you merge it. | You work on `main` mostly; CI encourages short feature branches. |
| **`main`** | The "official", trusted version of the project. | Your default branch. |
| **Push** | Upload your local commits to GitHub. | `git push`. |
| **Pull Request (PR)** | A *proposal* to merge a branch into `main`. The place where CI runs and where review happens. | You don't use these yet — CI is the reason to start. |
| **Merge** | Accept a PR — fold the branch's commits into `main`. | After CI is green. |

### 2.2 CI/CD words

| Term | Plain meaning |
|---|---|
| **Pipeline** | The ordered list of automated steps that run on your code (install → build → test → deploy). *Don't confuse with your "data pipeline" — same word, different thing.* |
| **Build** | Turning source code into a runnable/usable form. For dbt, "build" ≈ `dbt run` (compile SQL + execute it into tables). |
| **Test** | Automated checks that assert the code behaves correctly. For dbt: `dbt test` (not_null, unique, accepted_values, your singular tests…). |
| **Trigger / Event** | The thing that *starts* a pipeline: a push, a PR opened, a schedule, a manual click. |
| **Runner / Agent** | The machine that executes the pipeline. GitHub gives you free disposable Linux VMs as runners. |
| **Job** | A group of steps that run together on one runner. |
| **Step** | A single command or action inside a job (e.g. "install uv", "run dbt test"). |
| **Artifact** | A file produced by the pipeline that you want to keep (logs, `target/`, test reports, a compiled binary). |
| **Secret** | A sensitive value (password, API key) stored encrypted in GitHub, injected at runtime, never printed in logs. |
| **Service container** | A throwaway helper service (here: a Postgres database) that the pipeline spins up just for the run and discards afterward. |
| **Status check / Green checkmark** | The pass/fail result CI reports back onto your commit or PR. |

### 2.3 CI vs CD vs CD — the three levels

People say "CI/CD" as one word, but there are really three escalating levels:

1. **Continuous Integration (CI)** — automatically *build and test* on every change.
   *Goal: catch breakage fast.* **This is the level you need first and it gives 80% of the value.**
2. **Continuous Delivery (CD)** — after CI passes, automatically *prepare a release*
   that a human can deploy with one click. *Goal: deploys are boring and safe.*
3. **Continuous Deployment (CD)** — after CI passes, automatically *deploy to
   production* with no human in the loop. *Goal: every green commit is live.*

> **For this project:** you already have a *form* of CD — your nightly Task Scheduler
> job loads data and deploys dbt models to Supabase at 03:00. What you're **missing
> is the CI half**: nothing automatically verifies a code change *before* it lands.
> That's the gap Stage 3 fills.

---

## Part 3 — Anatomy of a CI run (what actually happens, step by step)

When CI is set up, here's the lifecycle of a single code change:

```
You: edit a dbt model  ──►  git commit  ──►  git push (or open a PR)
                                                   │
                                                   ▼
                          GitHub detects the push  (the TRIGGER)
                                                   │
                                                   ▼
                    GitHub boots a fresh Linux VM  (the RUNNER)
                                                   │
        ┌──────────────────────────────────────────┴─────────────────────────┐
        │  THE JOB (runs top to bottom; any red step stops the job)           │
        │                                                                     │
        │  Step 1  Check out your code onto the VM                            │
        │  Step 2  Start a clean Postgres  (the SERVICE CONTAINER)            │
        │  Step 3  Install uv + Python                                        │
        │  Step 4  uv run dbt deps     (install dbt_utils, dbt_expectations)  │
        │  Step 5  Write a profiles.yml pointing dbt at that Postgres         │
        │  Step 6  uv run dbt parse    (do all refs/sources/YAML resolve?)    │
        │  Step 7  uv run dbt compile  (does every model's SQL compile?)      │
        └─────────────────────────────────┬───────────────────────────────────┘
                                          │
                          all green ──────┼────── any red
                                ▼                     ▼
                    ✅ checkmark on commit    ❌ X on commit + email
                    (safe to merge)           (you fix it before merging)
                                          │
                                          ▼
                       GitHub destroys the VM (nothing persists)
```

The two things to internalize:

1. **The runner is disposable and clean.** It starts from nothing every time. That's
   what kills "works on my machine" — if your project builds on a blank VM, it builds
   anywhere.
2. **Red stops the line.** The moment a step fails, the job goes red and you get
   notified. The broken change never silently sits in `main`.

---

## Part 4 — GitHub Actions: the concrete tool

There are many CI systems (Jenkins, GitLab CI, CircleCI, Azure Pipelines…). Because
your code is on GitHub, the natural choice is **GitHub Actions** — it's built in,
free for public repos, and configured by a single file.

### 4.1 Where it lives

A workflow is a YAML file in a special folder:

```
.github/
  workflows/
    dbt_ci.yml      ← GitHub automatically finds and runs this
```

You commit this file like any other. GitHub sees it and starts honoring it.

### 4.2 The five building blocks of a workflow

```yaml
name: dbt CI                    # (1) human-readable name shown in the UI

on:                             # (2) TRIGGERS — when to run
  pull_request:
  push:
    branches: [ main ]

jobs:                           # (3) one or more JOBS
  build-and-test:
    runs-on: ubuntu-latest      # (4) which RUNNER (a free Linux VM)
    steps:                      # (5) the ordered STEPS
      - uses: actions/checkout@v4
      - run: echo "hello from CI"
```

- **`name`** — what you see in the "Actions" tab.
- **`on`** — the events that trigger it. `pull_request` + `push: main` is the
  standard "test every proposed and every landed change".
- **`jobs`** — independent units of work (can run in parallel; here we need just one).
- **`runs-on`** — the OS image for the disposable VM.
- **`steps`** — run top to bottom. Two kinds:
  - `uses:` — a **pre-built action** someone published (e.g. `actions/checkout@v4`
    clones your repo; `astral-sh/setup-uv@v5` installs `uv`). Reusable Lego bricks.
  - `run:` — a **shell command** you write yourself (e.g. `uv run dbt parse`).

### 4.3 Service containers (how CI gets a database)

dbt needs a Postgres to connect to. In CI you don't have your laptop's Postgres — so
you ask GitHub to spin one up *for the duration of the job*:

```yaml
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: store_local
        ports: [ "5432:5432" ]
        options: >-
          --health-cmd pg_isready --health-interval 5s --health-retries 10
```

This is a real, empty Postgres reachable at `localhost:5432` inside the job, created
fresh each run and thrown away at the end. The `--health-cmd` makes the job *wait*
until Postgres is actually accepting connections before dbt tries to use it.

### 4.4 Secrets (how CI handles passwords safely)

You never write a password in the YAML. Instead you store it once in GitHub
(**Settings → Secrets and variables → Actions**) and reference it:

```yaml
      - run: uv run dbt parse
        env:
          DBT_PASSWORD: ${{ secrets.DBT_PASSWORD }}
```

GitHub injects the value at runtime and automatically masks it in logs. For *this*
CI, the Postgres is a throwaway with a dummy password, so you may not need real
secrets at all — but the moment CI touches Supabase, secrets are mandatory.

> **Hard rule:** your real `.env` values (local PG password, the Supabase connection
> string, `REVALIDATE_SECRET`) must **never** appear in a workflow file or in CI
> logs. CI's Postgres is disposable and uses a fake password on purpose.

---

## Part 5 — Designing CI *for this specific project*

This is where generic knowledge meets your reality. The key insight:

### 5.1 The constraint: your raw data can't live in CI

Your pipeline is **EL→T**. The raw tables are loaded by the Python scripts from a
**SQL Server `.bak` backup** plus synthetic generation. That `.bak` is large, private,
and not in the repo. A CI runner is a blank Linux VM — **it has no way to get your raw
data.** Therefore CI **cannot** run a full `dbt build` (which would need to execute
SQL against populated tables).

This is normal and expected. It just means we pick the *right* level of checking.

### 5.2 The right CI for a dbt project without seedable data

| Command | What it proves | Needs data? |
|---|---|---|
| `dbt deps` | Packages install. | No |
| `dbt parse` | All `ref()`/`source()` resolve, YAML is valid, the DAG is coherent. | No |
| `dbt compile` | Every model's Jinja+SQL compiles to valid SQL against the *schema*. | Usually no — but see the caveat below |
| `dbt build` / `dbt test` | Models execute correctly **and data passes tests**. | **Yes** |

> **Real-world caveat we hit on THIS project (a genuine lesson).** "compile needs
> no data" is the *general* rule, but it has an exception: if a macro calls
> **`run_query()`** it executes a live SQL query *at compile time*. Our `dim_date`
> is built by a date-spine macro that runs `select min(recordingdate) from
> raw.documents` to find the spine's start date — so `dbt compile` failed in CI with
> `relation "raw.documents" does not exist` against the empty Postgres. The fix isn't
> to abandon compile; it's to **seed the one table that macro reads** with a single
> dated row before compiling (a `psql` step in the workflow). Lesson: *know your
> macros* — `run_query`/`statement` blocks turn an otherwise data-free step into one
> that needs (a little) data. We grepped the repo to confirm `dim_date` was the only
> such case.

So your CI runs **`deps → parse → compile`**. That catches the overwhelming majority
of real regressions:

- a broken `ref()` to a renamed/deleted model → caught by `parse`
- a column removed in staging but still selected downstream → caught by `compile`
- malformed YAML / a test pointing at a non-existent column → caught by `parse`
- a package version mismatch → caught by `deps`

What it *won't* catch is a *data* problem (a `not_null` test failing on real rows) —
but those are caught every night by your scheduled job's `dbt test`, which *does* have
the data. **The two complement each other:** CI guards the *code*, the nightly job
guards the *data*.

> **Advanced (optional, later):** if you ever want CI to test *data* too, the
> professional pattern is **dbt seeds** — small curated CSVs of representative rows
> committed to the repo, loaded with `dbt seed`, then `dbt build`. You'd hand-craft a
> dozen rows per source table. Powerful, but more work; not needed for Stage 3.

### 5.3 The cleanup that comes first (the 53 deprecations)

Your nightly log shows:
`MissingArgumentsPropertyInGenericTestDeprecation: 53 occurrences`. That's because the
repo mixes old test syntax (`accepted_values: values: [...]`) and new
(`accepted_values: arguments: { values: [...] }`). dbt 1.11 only *warns*; dbt 2.0 will
*break*. Doing this cleanup **before** standing up CI means your very first CI run is
clean and green, not yellow-with-warnings — and it future-proofs the project. This is
why the recommendation said "start with Step 0".

---

## Part 6 — A complete, annotated workflow for this repo

Here is the actual file you'd add as `.github/workflows/dbt_ci.yml`. Every line is
commented so you can read it as a lesson, not a black box.

```yaml
name: dbt CI                       # shows up in the repo's "Actions" tab

on:                                # WHEN this pipeline runs:
  pull_request:                    #   - on every Pull Request
  push:
    branches: [ main ]             #   - and on every push to main
  workflow_dispatch:               #   - plus a manual "Run" button in the UI

jobs:
  dbt-validate:                    # one job; the name is arbitrary
    runs-on: ubuntu-latest         # a free, disposable Linux VM

    services:                      # spin up a throwaway Postgres for this job
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres   # dummy — CI DB is disposable, never real creds
          POSTGRES_DB: store_local
        ports: [ "5432:5432" ]
        options: >-                # wait until Postgres is truly ready before dbt runs
          --health-cmd pg_isready
          --health-interval 5s
          --health-retries 10

    env:                           # env vars available to every step
      DBT_PROFILES_DIR: ./ci       # tell dbt to look for profiles.yml in ./ci

    steps:
      - name: Check out the repo
        uses: actions/checkout@v4  # clones your code onto the VM

      - name: Install uv
        uses: astral-sh/setup-uv@v5  # installs the uv tool the project uses

      - name: Install Python deps (incl. dbt)
        run: uv sync               # creates .venv from your lockfile

      - name: Write a CI dbt profile
        run: |                     # generate a profiles.yml pointing at the service Postgres
          mkdir -p ci
          cat > ci/profiles.yml <<'YAML'
          store_pipeline:
            target: ci
            outputs:
              ci:
                type: postgres
                host: localhost
                port: 5432
                user: postgres
                password: postgres
                dbname: store_local
                schema: raw
                threads: 4
          YAML

      - name: Install dbt packages
        run: uv run dbt deps       # dbt_utils + dbt_expectations

      - name: Validate the project (refs, YAML, DAG)
        run: uv run dbt parse

      - name: Compile every model to SQL
        run: uv run dbt compile
```

When you push this, GitHub:
1. sees `.github/workflows/dbt_ci.yml`,
2. on your next PR/push, boots the VM + Postgres,
3. runs the steps,
4. stamps a ✅ or ❌ on the commit.

### 6.1 The README badge (the visible payoff)

After the workflow exists, add one line near the top of `README.md`:

```markdown
![dbt CI](https://github.com/HomeDigSoftware/local_store_pipeline/actions/workflows/dbt_ci.yml/badge.svg)
```

That renders a live green/red badge on your repo's front page. This is the
"professional" signal in a single line.

---

## Part 7 — Re-reading the earlier recommendation, now that you have the vocabulary

Here's what the Stage 3 recommendation meant, decoded:

- *"CI here is parse + compile, not full build, because the `.bak` can't live in CI."*
  → Part 5.1–5.2. We validate **code**, not **data**, because the runner can't get
  your raw data. The nightly job already validates data.
- *"It locks in the test suite you just polished."*
  → Once CI runs on every PR, nobody (including future-you) can merge a change that
  breaks a `ref` or a test definition without the red ❌ stopping them.
- *"It's the only remaining public-facing item."*
  → The badge (Part 6.1) is the one thing an outside viewer sees that proves
  engineering maturity.
- *"Start with Step 0 — the 53 deprecations."*
  → Part 5.3. Clean the mixed test syntax first so CI is green, and so dbt 2.0 won't
  break the project later.
- *"We already have a form of CD (the 03:00 job); we're missing CI."*
  → Part 2.3. Deployment is automated; *pre-merge verification* is not. CI closes that.

---

## Part 8 — Mental models that separate a beginner from a pro

1. **"Shift left."** The earlier you catch a bug, the cheaper it is. A bug caught in
   CI (seconds after you write it) costs minutes; the same bug caught in production
   (a wrong number on the live dashboard) costs hours and trust. CI exists to shift
   detection as far *left* (early) as possible.
2. **"If it's not automated, it doesn't happen."** Any check that relies on a human
   remembering will eventually be skipped. Encode it in the pipeline.
3. **"The pipeline is the source of truth, not your laptop."** If it builds in CI, it
   builds. If it only builds on your machine, you have a hidden dependency to fix.
4. **"Fast and reliable beats thorough and flaky."** A CI that takes 90 seconds and is
   always trustworthy gets used. One that takes 40 minutes or fails randomly gets
   ignored and disabled. Start small (parse+compile), grow later.
5. **"Red means stop."** A broken `main` is an emergency, because everyone builds on
   `main`. The whole point of CI is to keep `main` always-green.
6. **Idempotency & reproducibility.** A good pipeline produces the same result every
   run from the same inputs. Disposable runners + lockfiles (`uv.lock`) + pinned
   action versions (`@v4`) are how you get there.

---

## Part 9 — A realistic learning path (what to actually do, in order)

1. **Understand a PR.** Make a tiny branch, change one comment, open a PR on your own
   repo, merge it. Feel the flow. (15 min)
2. **Add the workflow** from Part 6. Push it. Watch it run in the "Actions" tab.
   Read the live logs — they're the same dbt output you see locally. (1 hr)
3. **Make it fail on purpose.** Break a `ref()`, push, watch CI go red, read the error,
   fix it, watch it go green. This is the single most instructive exercise. (20 min)
4. **Add the badge.** See it on your repo's front page. (5 min)
5. **Later, optionally:** add `sqlfluff` linting; add dbt seeds for true data tests;
   add a deploy job gated on CI passing.

---

## Part 10 — Glossary (one-line definitions)

- **CI** — automatically build + test on every change.
- **CD (Delivery)** — automatically prepare a release after CI passes; deploy is one click.
- **CD (Deployment)** — automatically deploy to prod after CI passes; no human step.
- **Pipeline** — the ordered automated steps run on your code.
- **Workflow** — a GitHub Actions pipeline, defined in a `.yml` file.
- **Job** — a group of steps on one runner.
- **Step** — one command (`run:`) or one reusable action (`uses:`).
- **Runner** — the disposable VM that executes a job.
- **Action** — a packaged, reusable step (e.g. `actions/checkout`).
- **Trigger / Event** — what starts a workflow (push, PR, schedule, manual).
- **Service container** — a throwaway helper service (here: Postgres) for the job.
- **Secret** — an encrypted value injected at runtime, masked in logs.
- **Artifact** — a file the pipeline saves for you (logs, reports).
- **Status check** — the ✅/❌ CI reports onto a commit/PR.
- **Badge** — the live image showing CI status on the repo page.
- **dbt parse** — validate refs/sources/YAML/DAG; no data needed.
- **dbt compile** — turn every model into executable SQL; no data needed.
- **dbt build/test** — run models and assert data quality; **needs data**.
- **Seed** — a small CSV of sample rows committed to the repo, loaded with `dbt seed`.
- **Shift left** — catch problems as early in the process as possible.

---

*Next step in the project: implement Stage 3 (Step 0 deprecation cleanup → the
workflow above → the badge). When you're ready, say so and I'll start with the
deprecation cleanup and show you a clean `dbt parse` first.*
```
