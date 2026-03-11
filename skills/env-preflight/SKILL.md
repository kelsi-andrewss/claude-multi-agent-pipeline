---
name: env-preflight
description: >
  Scan plan files for external service dependencies and present an env var
  checklist. Accepts a .ship-manifest.json path, space-separated plan file
  paths, or is called by /ship after Step 3c. Skips silently when no
  external services are detected.
  Use when the user says "/env-preflight .ship-manifest.json",
  "/env-preflight plans/foo.md plans/bar.md", or called from /ship pipeline.
args:
  - name: args
    type: string
    description: >
      Manifest path (.ship-manifest.json) or space-separated .md plan file paths.
---

# Env-Preflight Skill Invoked

User has requested: `/env-preflight {{args}}`

---

## Step 1: Parse args and resolve plan files

Parse `{{args}}` (trim whitespace):

1. **Manifest mode**: a token ends with `.ship-manifest.json` and the file exists. Read the JSON, extract story entries, and collect their `plan_file` paths. These are the plan files to scan.

2. **Direct mode**: one or more tokens end with `.md` and the files exist. Use them directly as the plan files to scan.

3. **No args**: error with usage message:
   ```
   Usage:
     /env-preflight .ship-manifest.json
     /env-preflight plans/foo.md plans/bar.md
   ```
   Stop execution.

4. **Validate paths**: For each resolved plan file path, confirm the file exists. If any path is missing, warn: `Plan file not found: <path>` and exclude it from scanning. If all paths are invalid, stop with: `No valid plan files to scan.`

Set `plan_files` to the list of validated file paths.

---

## Step 2: Scan plan files for external service indicators

For each file in `plan_files`:

1. Read the file content. Extract the `## What changes` and `## Tasks` sections (from the heading to the next `##` heading or end of file).

2. Scan the extracted text against these indicator categories:

   **Auth providers** — match any of: Firebase Auth, Supabase, Auth0, Clerk, OAuth
   - Firebase Auth → `FIREBASE_API_KEY`, `FIREBASE_AUTH_DOMAIN`
   - Supabase → `SUPABASE_URL`, `SUPABASE_ANON_KEY`
   - Auth0 → `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET`
   - Clerk → `CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`
   - OAuth (generic) → `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`

   **Databases** — match any of: Postgres, PostgreSQL, MySQL, MongoDB, Redis, Firestore
   - Postgres/PostgreSQL → `DATABASE_URL`
   - MySQL → `DATABASE_URL`
   - MongoDB → `MONGODB_URI`
   - Redis → `REDIS_URL`
   - Firestore → `FIREBASE_API_KEY`, `FIREBASE_PROJECT_ID`

   **Payment** — match any of: Stripe, PayPal, Square
   - Stripe → `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`
   - PayPal → `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`
   - Square → `SQUARE_ACCESS_TOKEN`

   **Email/SMS** — match any of: SendGrid, Twilio, Resend, Postmark
   - SendGrid → `SENDGRID_API_KEY`
   - Twilio → `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`
   - Resend → `RESEND_API_KEY`
   - Postmark → `POSTMARK_SERVER_TOKEN`

   **Cloud SDKs** — match any of: AWS, GCP, Azure
   - AWS → `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`
   - GCP → `GOOGLE_APPLICATION_CREDENTIALS`
   - Azure → `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_CLIENT_SECRET`

   **Explicit env var references** — match any of: `process.env`, `os.environ`, `dotenv`, `import.meta.env`
   - Extract the referenced variable names directly from the text (e.g., `process.env.MY_VAR` → `MY_VAR`)
   - If variable names cannot be extracted, flag the reference for manual review

3. For each match, record:
   - The env var names
   - The service name (e.g., "Stripe payments")
   - Which plan file triggered the detection
   - The story ID if available (parse from `Story:` line in the plan file)

4. Deduplicate across plan files: group by env var names, merge story references.

Set `detections` to the collected results.

---

## Step 3: Present checklist or skip

**If `detections` is empty** → produce no output. Return silently. The caller (ship or user) proceeds without interruption.

**If `detections` is non-empty** → present a checklist via AskUser:

```
Environment preflight — external services detected in plan files:

[ ] STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY — Stripe payments (story-NNN)
[ ] DATABASE_URL — PostgreSQL (story-NNN, story-MMM)
[ ] FIREBASE_API_KEY — Firebase Auth (Bootstrap)

Confirm these are set in your .env (and anywhere else needed), or say "skip".
```

- Each line groups env vars by service, with the originating story IDs in parentheses.
- On user confirmation or "skip": proceed (return control to caller).

---

## Step 4: New project bootstrap check

After scanning, check for new-project indicators:

1. If any plan file references a "Bootstrap" story (case-insensitive match on the `Story:` line, title, or `## Context` section), OR if the project root has no `.env.example` file:

2. Check whether any plan file already lists `.env.example` in its `## What changes` table (first column).

3. If `.env.example` is NOT already a write target in any plan:
   - Append to the AskUser checklist (or surface standalone if Step 3 was a silent skip):
     ```
     Note: This looks like a new project. The Bootstrap plan should include:
     - .env.example with placeholder var names (no real values)
     - .env and .env.local in .gitignore
     ```

4. If `.env.example` IS already a write target: no action needed.

---

## Behavioral notes

- **NEVER read `.env` files.** This skill works with service names from plan text only. Env var names are inferred from service indicators, not read from any file. Values are never requested, displayed, or accessed.
- **Silent skip is the default path.** Most projects don't hit external services in every story. No output means no dependencies detected.
- **When called from /ship pipeline**: the caller handles skip/proceed logic based on this skill's output. If nothing is detected, the skill returns silently and /ship continues to Step 4.
- **When called standalone**: the skill handles its own AskUser interaction directly.
- **Matching is case-insensitive** for service names (e.g., "stripe", "Stripe", "STRIPE" all match).
- **Err toward detection.** A false positive (flagging a service that isn't actually used) costs the user a glance. A false negative (missing a required env var) wastes an entire coder run.
