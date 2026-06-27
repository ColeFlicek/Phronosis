# Scopenos Session Isolation — ELI5

> How we made it safe for AI agents to work on a live production system without accidentally destroying customer data.

---

## The Problem in One Sentence

An AI coding assistant that can read your codebase can also run database commands. Without guardrails, a misunderstood instruction like "clean up old data" could wipe a customer's entire database.

---

## The Building Analogy

Imagine your database is a building with several floors:

- **Ground floor** — read-only archive (anyone can look, nobody can touch)
- **Second floor** — active office (staff can read and write files)
- **Third floor** — server room (engineers can restructure things)
- **Basement** — master control (only the building manager can create/destroy rooms)

Each AI session gets an **ID badge** that only opens the floors it needs. The badge is enforced by the *building itself* — not by trusting the person carrying it.

---

## The Six Session Types

| Session | Badge Level | What It Can Do |
|---|---|---|
| **reader** | Ground floor only | Read the database, read K8s pod logs |
| **indexer** | Second floor | Insert and update index data |
| **deployer** | K8s control room only | Restart pods, check deployments — no database at all |
| **migrator** | Third floor | Create new schemas, restructure tables |
| **tester** | Separate test building | Full access to the test database, zero access to production |
| **provisioner** | Basement | Create new customer databases |

---

## How the Layers Work

### Layer 1 — Docker Containers (The Rooms)

Each session runs inside its own Docker container — like a separate room that gets torn down when the session ends. One session cannot see inside another session's room. The walls are enforced by the operating system kernel.

### Layer 2 — Postgres Roles (The ID Badges)

Every session connects to the database using a specific role with specific permissions baked in at the database server level. This is the **hard backstop**.

Even if a reader session somehow knew the indexer's password, using it would only give access to the `scopenos_control_rw` role — not to schema creation or database deletion. Each badge literally cannot open floors it was not issued for.

```
scopenos_read         → SELECT only. Cannot INSERT, UPDATE, DELETE.
scopenos_control_rw   → Read + write index data. Cannot ALTER or DROP.
scopenos_migrator     → Can CREATE SCHEMA. Cannot DROP DATABASE.
scopenos_provisioner  → Can CREATE DATABASE. Cannot touch existing data.
scopenos_test_runner  → Full access to test DB. Cannot reach production.
```

### Layer 3 — Separate Secrets Directories (The Key Cabinets)

Each session's container has a locked cabinet mounted at `/run/secrets/` containing **only that session's database password**. The cabinet for the reader session physically does not contain the indexer's password — it is never mounted into that container.

```
~/.secrets/
  reader/db_password      → only mounted in reader containers
  indexer/db_password     → only mounted in indexer containers
  migrator/db_password    → only mounted in migrator containers
  tester/db_password      → only mounted in tester containers
  provisioner/db_password → only mounted in provisioner containers
```

A reader session cannot read the provisioner's password because that directory does not exist inside its container.

### Layer 4 — The Wrapper Script (The Keycard Reader)

When a session starts, before the AI is launched, a wrapper script runs that:

1. Reads the password from `/run/secrets/db_password`
2. Writes it to `~/.pgpass` — a standard file the database driver reads automatically
3. Constructs a `DATABASE_URL` **without** the password embedded in it
4. **Deletes the password from the environment** (`unset PGPASSWORD`)
5. Launches Claude

After step 5, the password exists only in `~/.pgpass` inside the container — not in any environment variable, not in any connection string, not in any place that would appear in error messages or log output.

```bash
# What a connection error looks like BEFORE this setup:
could not connect: postgresql://scopenos_read:s3cr3t!@172.21.0.1/scopenos
#                                             ^^^^^^^^ password in the error log

# What it looks like AFTER:
could not connect to server 172.21.0.1 as user scopenos_read
#                                                no password anywhere
```

### Layer 5 — Isolated Conversation Transcripts

Claude saves every conversation to `~/.claude/projects/`. Without intervention, all sessions share this directory — one session could read another's conversation history, which might contain sensitive output from tool calls.

Each session profile mounts a **separate directory** for transcripts:

```
~/.claude/sessions/
  reader/      → only reader conversations live here
  indexer/     → only indexer conversations live here
  deployer/    → only deployer conversations live here
  ...
```

A reader session's conversation history is invisible to the indexer session, and vice versa.

---

## What This Prevents

| Scenario | Prevented by |
|---|---|
| Reader accidentally runs `DELETE FROM nodes` | Postgres role rejects it at the server |
| Indexer accidentally drops a customer schema | `scopenos_control_rw` has no DROP privilege |
| Password appears in an error message | Wrapper removes it from DSN before launch |
| Session A reads Session B's conversation transcript | Separate mounted directories |
| Session A reads Session B's database password | B's secrets directory not mounted in A |
| Deployer touches production database | No `DATABASE_URL` injected at all |

---

## What This Does NOT Prevent

- A session reading its **own** password from `/run/secrets/db_password` (it already has DB access via that role, so this grants nothing extra)
- A sufficiently determined agent doing something harmful **within its role's permissions** — e.g. the indexer could insert garbage data into the index

The Postgres role is the floor, not the ceiling. The session identity system prevents accidents and limits blast radius. It does not replace good prompting and human review for destructive operations.

---

## The Key Insight

> The database server enforces the rules. We trust the building, not the person in it.

No matter what an AI session is instructed to do, no matter what it reads or tries, the database will refuse any operation the role was not granted. The wrapper scripts, secrets directories, and transcript isolation are defence-in-depth — they reduce the surface area for accidents. The Postgres role is what actually makes it safe.

---

## File Map

```
~/.config/agent-of-empires/profiles/
  scopenos-reader/config.toml
  scopenos-indexer/config.toml
  scopenos-deployer/config.toml
  scopenos-migrator/config.toml
  scopenos-tester/config.toml
  scopenos-provisioner/config.toml

~/scopenos-sessions/
  claude-reader        ← wrapper scripts (run inside containers)
  claude-indexer
  claude-deployer
  claude-migrator
  claude-tester
  claude-provisioner

~/.secrets/
  reader/db_password   ← per-session isolated password files
  indexer/db_password
  migrator/db_password
  tester/db_password
  provisioner/db_password

~/.kube/scopenos/
  scopenos-reader.yaml    ← K8s kubeconfig (read-only cluster view)
  scopenos-deployer.yaml  ← K8s kubeconfig (patch deployments only)

~/.claude/sessions/
  reader/    ← isolated conversation transcripts per session type
  indexer/
  deployer/
  migrator/
  tester/
  provisioner/
```
