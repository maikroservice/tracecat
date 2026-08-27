# Tracecat Fork — Upgrade & Deployment Runbook

Repeatable process for upgrading our Tracecat fork (`maikroservice/tracecat`) and
rolling it out to prod (uncloud). Distilled from the 2026-07 upgrade from the
pre-merge fork (alembic `1c268fa6eff5`) to `1.0.0-beta.50` (alembic `9f2c4b7d81aa`).

---

## 1. Sync the fork with upstream

```bash
cd ~/github/tracecat
git fetch upstream                 # upstream = https://github.com/tracecathq/tracecat.git
git merge upstream/main
```

During the merge, decide per fork customization:

- **Keep:** sample_data feature, breadcrumbs, hidden sidebar nav items
  (`frontend/src/components/sidebar/app-sidebar.tsx` — entries carry
  `visible: false` + a "fork customization" comment so merges conflict less),
  Inbox restricted to org admins (`org:update` scope), custom non-EE GitLab
  workflow sync.
- **Check for renames/moves upstream** before assuming our code was dropped.

### Alembic heads after a merge

Upstream and fork migrations diverge, so after every merge check for multiple heads
and create a merge revision if needed (ours: `9f2c4b7d81aa_merge_fork_and_upstream_heads.py`
merging fork head `1c268fa6eff5` + upstream head `11d479597e08`):

```bash
python -m alembic heads     # must show exactly ONE head before deploying
python -m alembic merge -m "merge fork and upstream heads" <head1> <head2>
```

---

## 2. Test migrations against a real prod dump (strongly recommended)

Never run a big migration jump for the first time on prod. Rehearse locally:

```bash
# On the prod machine — take a full cluster dump
docker exec <db-container> pg_dumpall -U postgres --clean > full_dump.sql
# copy it to the test VM (scp/etc.)

# On the test VM — throwaway Postgres matching prod's major version
docker network create dumptest
docker run -d --name dump-test --network dumptest \
  -e POSTGRES_PASSWORD=testpass -e POSTGRES_HOST_AUTH_METHOD=trust postgres:16

# Restore (the two errors about role "postgres" are expected pg_dumpall noise)
docker exec -i dump-test psql -U postgres -f - < full_dump.sql

# The dump overwrites the postgres password with prod's hash — reset it for TCP
docker exec dump-test psql -U postgres -c "ALTER ROLE postgres PASSWORD 'testpass';"

# Sanity-check the restore
docker exec dump-test psql -U postgres \
  -c "SELECT version_num FROM alembic_version;" \
  -c "SELECT (SELECT count(*) FROM public.user), (SELECT count(*) FROM workspace), (SELECT count(*) FROM workflow);"

# Run the fork's migrations using the new api image
docker run --rm --network dumptest \
  -e TRACECAT__DB_URI='postgresql+psycopg://postgres:testpass@dump-test:5432/postgres' \
  <new-api-image> python3 -m alembic upgrade head

# Verify: alembic_version == the single head, row counts unchanged, new tables exist
# Cleanup
docker rm -f dump-test && docker network rm dumptest
```

Notes:
- Tracecat's app data lives in the `postgres` database itself (default `TRACECAT__DB_NAME`).
- The restoring `psql` must be >= the dumping version's patch level to understand
  the `\restrict` directive (pg 16.10+); `postgres:16` latest is fine.

---

## 3. Build & publish images

Images are built by `.github/workflows/build-push-fork.yml` on pushes to `main`:

- API → `ghcr.io/maikroservice/tracecat`, UI → `ghcr.io/maikroservice/tracecat-ui`
- The version tag is auto-derived: bump-patch from the latest GHCR tag, falling back
  to `__version__` in `tracecat/__init__.py` (e.g. `1.0.0-beta.50`).
- Jobs are path-filtered: API-only changes skip the UI build and vice versa.

**Before deploying, verify the tag actually exists** — a GHCR "denied" on pull
usually means the tag was never published (failed CI run), not an auth problem:

```bash
gh run list -R maikroservice/tracecat --workflow build-push-fork.yml --limit 5
docker manifest inspect ghcr.io/maikroservice/tracecat:<tag>   # needs read:packages if private
```

Known issue (2026-07): the UI build job was failing on GitHub runners (~36 min in,
likely memory); check CI is green before relying on a new tag.

---

## 4. Deploy to prod (uncloud)

### 4.1 Backup first — this is the rollback point

```bash
docker exec <db-container> pg_dumpall -U postgres --clean > backup_$(date +%F).sql
```

### 4.2 Run migrations

Migrations do **not** run automatically: the image entrypoint only runs
`alembic upgrade head` when `RUN_MIGRATIONS=true`, and our compose files don't set it.

For a **big/risky jump** (like beta.50's ~100 migrations), run it as a controlled
manual step with the app stopped, watching the output (it must end at the expected head):

```bash
docker run --rm --network <network-the-db-is-on> \
  -e TRACECAT__DB_URI='postgresql+psycopg://postgres:<password>@<db-hostname>:5432/postgres' \
  ghcr.io/maikroservice/tracecat:<tag> \
  python3 -m alembic upgrade head
```

For **routine deploys**, set it once in the compose file uncloud deploys:

```yaml
services:
  api:
    image: ghcr.io/maikroservice/tracecat:<tag>
    environment:
      RUN_MIGRATIONS: "true"   # api only — NOT worker/executor; assumes 1 api replica
```

A failed migration exits the container non-zero, so uncloud surfaces the failure
instead of running new code on an old schema.

### 4.3 Deploy the new images

```bash
uc deploy   # with the compose file pointing at the new image tags
```

---

## 5. Post-deploy — REQUIRED steps

### 5.1 Republish all workflows (after any upgrade that bumps `tracecat_registry`)

Workflows pin the platform registry version they were published against, stored as a
prebuilt venv tarball in object storage
(`s3://tracecat-registry/platform/tarball-venvs/tracecat_registry/<version>/site-packages.tar.gz`).
After beta.50, existing workflows still resolved the old `0.53.13` tarball and every
execution failed with:

```
ModuleNotFoundError: No module named 'tracecat_registry._internal.flatten'
```

**Fix: republish every workflow** so it re-pins to the registry version shipped with
the new platform. Symptom to watch for: `ModuleNotFoundError` inside the executor
for modules that clearly exist in the repo.

### 5.2 Custom registry repo

Prod also has `git+ssh://git@git.bitmarck.de/bm-soar/tracecat-registry.git`
registered as a custom registry repository — keep it compatible with the platform
version and re-sync it after upgrades.

Custom registries support two URL schemes (branch `feat/registry-https-token-auth`):

- `git+ssh://<user>@<host>[:<port>]/<org>/<repo>.git` — authenticates with the
  org secret `github-ssh-key` (one key pair for all git hosts; register the
  public half as a read-only deploy key on each host).
- `git+https://<host>[:<port>]/<org>/<repo>.git` — public repos work with no
  credentials; private repos authenticate with the optional org secret
  `git-access-token` (keys: `token`, optionally `username`; e.g. a GitLab
  project access token with `read_repository` scope, Reporter role). Tokens are
  injected via GIT_ASKPASS — never embed them in the URL.

Both require the host in the `git_allowed_domains` org setting, and
`git_repo_package_name` must be set when the repo's Python package name differs
from the repo name (e.g. repo `test-registry` shipping package `custom_actions`).

### 5.3 Smoke test

- Log in, check the sidebar shows the fork's trimmed nav (Chat, Workflows, Agents,
  Tables, Variables, Credentials, Skills; Inbox only for org admins).
- Run a workflow that touches core actions (e.g. `core.table.search_rows`).

---

## 6. Rollback

```bash
# Restore the pre-upgrade backup
docker exec -i <db-container> psql -U postgres < backup_<date>.sql
# Redeploy the previous image tags
```

`pg_dumpall --clean` dumps drop/recreate objects on restore; the app must be stopped
while restoring.
