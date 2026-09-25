# US-03 — Deploy workflow

| | |
|---|---|
| **Epic** | 1. Foundation |
| **Priority** | P0 |
| **Blocked by** | US-01 Kiosk OS provisioning, US-02 App skeleton |
| **Blocks** | — (formally nothing, but in practice **every story that needs checking on the Pi**) |
| **Phase** | 1. Foundation |

## Story

> As a developer, I want to push the app to the Pi, restart it, read its logs and take a screenshot of the screen from the dev machine.

## Context

Nobody ever sits at the Pi with a keyboard. Every change is made in the devcontainer, sent over SSH, and checked by reading the journal and **looking at a screenshot of the real HDMI output**. This story turns that loop into a single command, so it's fast and hard to get wrong.

The `pi-deploy` skill (`.claude/skills/pi-deploy/`) already has a working `deploy.sh` and the exact screenshot command. This story:
1. adds **one project-level entry point, `scripts/pi`**, with subcommands for everything developers do on the Pi;
2. fixes three real problems in the current `deploy.sh` (below);
3. makes the skill's `deploy.sh` a thin wrapper around `scripts/pi deploy`, so there's one implementation.

Load the `pi-deploy` skill first. Its "Don'ts" still apply (no reboots, no `/boot` edits, no overlay FS changes, no `apt upgrade` unless the owner asks).

### Problems with the current `deploy.sh` that you must fix

1. **There are no compiled `.pyc` files on the Pi.** The script excludes `__pycache__` and then makes `/opt/calpi` owned by `root`. The app runs as `kiosk`, so Python can't write `__pycache__`, and **every start recompiles every module in memory**. On a Pi 3B that adds noticeable startup time, and US-36 has a startup target. Fix: after syncing, run `sudo python3 -m compileall -q /opt/calpi` as root.
2. **`docs/`, `scripts/`, `deps/`, and `pyproject.toml` are copied to the device.** That's harmless but pointless. Exclude everything that isn't runtime code. A **list of what to include** is safer than a growing list of what to exclude.
3. **It doesn't wait for the app to actually be ready.** `sleep 4` followed by `is-active` reports success even if the app crashes after 5 seconds. Fix: wait (with a timeout) for the `calpi ready` log line that US-02 prints, looking only at log lines **since this restart**.

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-01** Kiosk OS provisioning | A Pi that runs `calpi-kiosk.service` (cage + `/opt/calpi/run.py` as `kiosk`), with SSH key access and passwordless sudo | `ssh -o ConnectTimeout=5 calpi 'systemctl is-enabled calpi-kiosk && id kiosk && sudo -n true && echo OK'` prints `enabled`, the kiosk user's details, and `OK`. `docs/platform-versions.md` exists and records `WAYLAND_DISPLAY`. |
| **US-02** App skeleton | Something real to deploy. It prints `calpi ready`, and it has `deps/apt-runtime.txt` | `scripts/smoke.sh` → `SMOKE OK` in the devcontainer. `grep -q "calpi ready" calpi/app.py` |

### External blockers

| Blocker | What to do |
|---|---|
| **The Pi is powered on and reachable** from the devcontainer | If `ssh` times out, **stop and tell the owner**. Don't scan for IPs. |
| **`rsync` is on both sides** | The devcontainer: `sudo apt-get install -y rsync` (add it to `deps/apt-dev.txt`). The Pi: `setup-pi.sh` already installs it. |
| **The overlay filesystem is off** | If `ssh calpi 'findmnt -n -o FSTYPE /'` prints `overlay`, deploys won't survive a reboot. Tell the owner. **Don't turn the overlay off yourself.** |

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| `sudo rsync` fails with "sudo: a terminal is required" | Passwordless sudo is missing. That's a US-01 problem, so report it. |
| `grim` fails with "compositor doesn't support wlr-screencopy" | The cage version is too old. Record the version and tell the owner. As a fallback, ask the owner for a phone photo. **Don't add another screenshot tool.** |
| `grim` fails with "failed to connect to display" | The `WAYLAND_DISPLAY` value is wrong. Read it from the running process: `sudo tr '\0' '\n' < /proc/$(pgrep -f /opt/calpi/run.py \| head -1)/environ \| grep WAYLAND`. |
| The app starts on the Pi but crashes with `ModuleNotFoundError` for an apt package | Run `scripts/pi deps` (step 3). If the package doesn't exist on the Pi's OS release, tell the owner and record it in `docs/platform-versions.md`. |
| The devcontainer has no SSH key or config | See US-01's blocker table. Ask the owner. Never store passwords. |

---

## Scope

### In scope
- `scripts/pi` with the subcommands `deploy`, `restart`, `logs`, `status`, `screenshot`, `deps`, `health`, `ssh`, `rollback`.
- Precompiling `.pyc` files, a list of what to include, and waiting for readiness.
- A build stamp (`calpi/BUILD`) so the logs show which build is running.
- A one-level rollback copy (`/opt/calpi.prev`).
- Making the skill's `deploy.sh` delegate to `scripts/pi deploy`, and updating the skill's documentation.

### Out of scope
- CI/CD, remote deploys over the internet, or deploying to several devices (out of scope for the whole project).
- Provisioning the OS (US-01).
- Performance measurement (US-36). `health` only prints basic numbers.

---

## Acceptance criteria

1. `scripts/pi deploy` does all of this: checks connectivity (5 s timeout), syncs **only** runtime files to `/opt/calpi`, writes a build stamp, precompiles, restarts the service, **waits up to 45 s for a `calpi ready` line logged after the restart**, then prints the last 30 journal lines and `DEPLOY OK <build>`. It exits non-zero (and prints the journal) if readiness isn't reached.
2. After a deploy, `ssh calpi 'find /opt/calpi -name "*.pyc" | head -1'` finds a file, and **no** `docs/`, `tests/`, `scripts/`, `deps/`, `.devcontainer/`, or `.claude/` directory exists under `/opt/calpi`.
3. `scripts/pi deploy --no-restart` syncs and compiles but doesn't restart.
4. `scripts/pi logs` prints the last 100 lines of **this boot**. `scripts/pi logs -f` follows. `scripts/pi logs -n 500` changes the count.
5. `scripts/pi screenshot [path]` saves a PNG of the live screen (default `./scratch-screenshot.png`) and prints its path and size. The file is 1920×1080.
6. `scripts/pi status` shows `systemctl status` (no pager), the running build stamp, and the app's uptime.
7. `scripts/pi health` shows `get_throttled`, the temperature, `free -m`, the app's RSS and CPU, the load average, and the root filesystem's free space.
8. `scripts/pi deps` installs the packages listed in `deps/apt-runtime.txt` with `apt-get install --no-install-recommends` (**not** `upgrade`), and reports which were newly installed.
9. `scripts/pi rollback` swaps back to the previous deploy, then restarts and waits for readiness.
10. When the app is running, the journal shows `calpi ready version=... build=<stamp>`, and the stamp matches the one `deploy` printed.
11. The skill's `.claude/skills/pi-deploy/deploy.sh` still works (as a wrapper), and `SKILL.md` documents `scripts/pi`.

---

## Design decisions (already made)

- **D1. `scripts/pi` is one bash script** with a `case` statement for the subcommands. There's no Python here. Keep it easy to read.
- **D2. The host comes from `$CALPI_HOST`** (default `calpi`, matching an `~/.ssh/config` entry). `$CALPI_USER` is optional. That matches the skill, except the default changes from `calpi.local` to `calpi`. Mention in the skill docs that the fallback is `calpi.local`.
- **D3. What gets synced (include list):** `run.py`, `calpi/` (without `__pycache__`, `*.pyc`, or `.devstate`). Nothing else. Use `rsync --delete --include=... --exclude='*'` patterns, or sync the two items explicitly:
  ```bash
  rsync -az --delete --rsync-path="sudo rsync" \
    --exclude '__pycache__' --exclude '*.pyc' \
    run.py calpi "$HOST:/opt/calpi/"
  ```
  `--delete` with two source arguments only removes files **inside** the synced directories. To also remove stray top-level files left behind by the old `deploy.sh`, add a one-off cleanup step (step 2e).
- **D4. The build stamp** is a file at `calpi/BUILD` on the Pi, written by the deploy step. Its format is `<UTC timestamp> <git short sha or 'nogit'><'-dirty' if uncommitted changes> <deployer hostname>`. The app reads it if it's present and logs it in `calpi ready` (a small change to `calpi/app.py`). **Don't commit `calpi/BUILD`**: add it to `.gitignore`. Generate it in a temporary directory and send it with `scp` or `ssh 'cat >'`, so the local working tree stays clean.
- **D5. Readiness** is checked with a journal cursor, so old `calpi ready` lines don't count:
  ```bash
  cursor=$(ssh "$HOST" 'journalctl -u calpi-kiosk -n 0 --show-cursor --no-pager | sed -n "s/^-- cursor: //p"')
  ssh "$HOST" 'sudo systemctl restart calpi-kiosk'
  ssh "$HOST" "timeout 45 journalctl -u calpi-kiosk --after-cursor='$cursor' -f --no-pager | grep -m1 'calpi ready'"
  ```
- **D6. Rollback** keeps exactly one previous copy at `/opt/calpi.prev`. Before each deploy: `sudo rsync -a --delete /opt/calpi/ /opt/calpi.prev/`. For a rollback, swap them with three `mv`s through a temporary name. Then restart.
- **D7. Screenshots are never committed.** The default path starts with `scratch-`, which `.gitignore` and the deploy both exclude. Remind people in the output to delete it.
- **D8. `deps` never runs `apt-get upgrade`.** It runs `apt-get update` only if the install fails because of missing package lists, or when `--update` is passed.

---

## Implementation plan

### Step 1 — The script's frame

```bash
#!/usr/bin/env bash
# calpi device helper. Usage: scripts/pi <command> [args]
#   deploy [--no-restart]   sync runtime files, precompile, restart, wait for "calpi ready"
#   restart                 restart the kiosk service and wait for readiness
#   logs [-f] [-n N]        journal for this boot
#   status                  service status + running build
#   screenshot [file.png]   capture the live HDMI output (default ./scratch-screenshot.png)
#   health                  throttling, temperature, memory, app RSS/CPU, disk
#   deps [--update]         install deps/apt-runtime.txt on the Pi (never upgrades)
#   rollback                restore the previous deploy
#   ssh [cmd...]            ssh to the Pi
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${CALPI_HOST:-calpi}"
[[ -n "${CALPI_USER:-}" ]] && HOST="${CALPI_USER}@${HOST}"
APP_DIR=/opt/calpi
SERVICE=calpi-kiosk
WAYLAND="${CALPI_WAYLAND_DISPLAY:-wayland-0}"   # from docs/platform-versions.md

die() { echo "error: $*" >&2; exit 1; }
remote() { ssh -o ConnectTimeout=5 -o BatchMode=yes "$HOST" "$@"; }
check_conn() { remote true 2>/dev/null || die "cannot reach $HOST (set CALPI_HOST, check ssh config)"; }
```
`BatchMode=yes` makes SSH fail instead of prompting for a password. That's what you want in scripts.

### Step 2 — `deploy`

a. `check_conn`.
b. Snapshot for rollback: `remote "sudo mkdir -p $APP_DIR && sudo rsync -a --delete $APP_DIR/ $APP_DIR.prev/"`.
c. Sync (D3).
d. Build stamp (D4):
   ```bash
   sha=$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo nogit)
   if [[ $sha != nogit ]] && ! git -C "$ROOT" diff --quiet HEAD 2>/dev/null; then sha="$sha-dirty"; fi
   build="$(date -u +%Y%m%dT%H%M%SZ) $sha $(hostname)"
   echo "$build" | remote "sudo tee $APP_DIR/calpi/BUILD >/dev/null"
   ```
e. One-off cleanup of stray top-level files: `remote "cd $APP_DIR && sudo find . -mindepth 1 -maxdepth 1 ! -name run.py ! -name calpi -exec rm -rf {} +"`. **Check this line very carefully**: it runs `rm -rf` as root. It's limited to `$APP_DIR`, and the `cd` fails (and stops the script, because of `set -e`) if the directory doesn't exist. Test it first on a scratch directory on the Pi (`/tmp/x`).
f. Ownership, permissions, and precompiling:
   ```bash
   remote "sudo chown -R root:root $APP_DIR && sudo chmod -R a+rX,go-w $APP_DIR && sudo /usr/bin/python3 -m compileall -q -j 0 $APP_DIR"
   ```
   `-j 0` uses all cores. Run `compileall` **after** `chown`, so the `__pycache__` directories are root-owned and readable.
g. Unless `--no-restart`: restart and wait for readiness (D5). On success print the last 30 lines and `DEPLOY OK $build`. On timeout print the last 80 lines and exit 1.

### Step 3 — `deps`

```bash
pkgs=$(grep -hvE '^\s*(#|$)' "$ROOT/deps/apt-runtime.txt" | sed 's/#.*//' | xargs)
remote "missing=\$(for p in $pkgs; do dpkg -s \$p >/dev/null 2>&1 || echo \$p; done | xargs); \
        if [ -z \"\$missing\" ]; then echo 'all runtime deps present'; exit 0; fi; \
        echo \"installing: \$missing\"; \
        sudo apt-get install -y --no-install-recommends \$missing || { sudo apt-get update && sudo apt-get install -y --no-install-recommends \$missing; }"
```
With `--update`, run `apt-get update` first. Print what was installed. **Never `upgrade`.**

### Step 4 — `logs`, `status`, `health`

```bash
logs)   n=100; follow=""; shift
        while [[ $# -gt 0 ]]; do case $1 in -f) follow=-f;; -n) n=$2; shift;; esac; shift; done
        remote "journalctl -u $SERVICE -b --no-pager -n $n $follow";;
status) remote "systemctl status $SERVICE --no-pager -l | head -20; echo; echo -n 'build: '; cat $APP_DIR/calpi/BUILD 2>/dev/null || echo unknown;
               pid=\$(pgrep -f $APP_DIR/run.py | head -1); [ -n \"\$pid\" ] && ps -o etime=,rss=,pcpu= -p \$pid | awk '{print \"app uptime \"\$1\", rss \"\$2/1024\" MB, cpu \"\$3\"%\"}'";;
health) remote "vcgencmd get_throttled; vcgencmd measure_temp; uptime; free -m; df -h / | tail -1;
               ps -o pid,rss,pcpu,etime,cmd -C python3,cage";;
```
In `health`, point out when `throttled` isn't `0x0`: print a line like `WARNING: throttling/under-voltage detected — check the power supply before chasing performance problems` (see the `pi-deploy` skill).

### Step 5 — `screenshot`

```bash
out="${2:-$ROOT/scratch-screenshot.png}"
remote "sudo -u kiosk env XDG_RUNTIME_DIR=/run/user/\$(id -u kiosk) WAYLAND_DISPLAY=$WAYLAND grim -t png /tmp/calpi-shot.png && sudo chmod a+r /tmp/calpi-shot.png"
scp -q "$HOST:/tmp/calpi-shot.png" "$out"
remote "sudo rm -f /tmp/calpi-shot.png"
echo "saved $out ($(file -b "$out" | cut -d, -f2 | xargs))"
echo "(scratch file: delete it when done; never commit screenshots)"
```
The agent can then `Read` the PNG to check the UI visually. That's what the skill intends.

### Step 6 — `restart`, `rollback`, `ssh`

- `restart`: the same cursor-based readiness wait as `deploy`, but no sync.
- `rollback`:
  ```bash
  remote "test -d $APP_DIR.prev || { echo 'no previous deploy'; exit 1; }
          sudo mv $APP_DIR $APP_DIR.rollback-tmp && sudo mv $APP_DIR.prev $APP_DIR && sudo mv $APP_DIR.rollback-tmp $APP_DIR.prev"
  ```
  then restart and wait. (A second rollback swaps back again, and that's fine.)
- `ssh`: `exec ssh "$HOST" "$@"`.

### Step 7 — Log the build in the app (small change to US-02 code)

In `calpi/app.py`, when logging `calpi ready`:
```python
def _build_stamp() -> str:
    try:
        return (paths.app_dir() / "BUILD").read_text().strip()
    except OSError:
        return "dev"
```
and add `build=%s` to the `calpi ready` log line. Keep the text `calpi ready` exactly as it is, because the smoke test and the deploy both look for it.

### Step 8 — Wire up the skill

Replace the body of `.claude/skills/pi-deploy/deploy.sh` with:
```bash
#!/usr/bin/env bash
# Kept for the pi-deploy skill; the real implementation is scripts/pi.
exec "$(cd "$(dirname "$0")/../../.." && pwd)/scripts/pi" deploy "$@"
```
Update `SKILL.md`: list the `scripts/pi` subcommands, mention precompiling, the include list, the build stamp, and rollback. Keep the existing "Don'ts".

### Step 9 — Try it end to end

1. `scripts/pi deploy` → `DEPLOY OK ...`.
2. `scripts/pi screenshot` → Read the PNG. It shows the US-02 placeholder at 1920×1080.
3. Break the app on purpose in a scratch branch (for example `raise RuntimeError` in `main()`). Run `scripts/pi deploy`, which must exit non-zero and show the traceback. Then `scripts/pi rollback`, which must get back to a working app. **Remove the deliberate error afterwards.**
4. `scripts/pi deploy` again with the fixed code.
5. `scripts/pi health`, `status`, `logs -n 20`.
6. `ssh calpi 'ls /opt/calpi; find /opt/calpi -name "*.pyc" | wc -l'`.

---

## Files

| File | Change |
|---|---|
| `scripts/pi` | **New** (`chmod +x`) |
| `.claude/skills/pi-deploy/deploy.sh` | Becomes a wrapper |
| `.claude/skills/pi-deploy/SKILL.md` | Documents `scripts/pi` |
| `calpi/app.py` | Adds the build stamp to the `calpi ready` log line |
| `.gitignore` | `calpi/BUILD`, `scratch-*` |
| `deps/apt-dev.txt` | Adds `rsync`, `openssh-client` (if not present), `file` |

---

## Testing

There are no unit tests: it's a shell script. Run `bash -n scripts/pi` (syntax check), and `shellcheck scripts/pi` if shellcheck is available (`sudo apt-get install shellcheck`). Fix the warnings, or justify ignoring them. The end-to-end run in step 9 is the real test. Put its output (without secrets) in your hand-off notes.

---

## Pitfalls

- **Quoting through SSH.** Variables meant for the **remote** shell need `\$`. Variables from the **local** script mustn't be escaped. Test each subcommand.
- **`rm -rf` as root** in the cleanup step. Check `$APP_DIR` isn't empty (`[[ -n $APP_DIR ]]`), and keep `cd ... &&`.
- **Following the journal with no timeout** hangs forever if the app never becomes ready. Always wrap it in `timeout`.
- **`grim` run as root** gets "no Wayland display", because the compositor socket belongs to `kiosk`. Always use `sudo -u kiosk env ...`.
- **Deploying while the owner is using the device.** A deploy restarts the app. That's fine during development. Mention it in the output.

---

## Definition of done

- [ ] All 11 acceptance criteria checked, with command output in the hand-off notes.
- [ ] The broken-deploy → rollback test from step 9 done and cleaned up.
- [ ] Skill updated. `deploy.sh` delegates to `scripts/pi`.
- [ ] `shellcheck` is clean (or the remaining warnings are justified).

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `scripts/pi deploy` / `restart` / `logs` / `screenshot` / `health` / `deps` | every story that's checked on the Pi |
| Runtime files = `run.py` + `calpi/`. **New top-level runtime files must be added to the sync list** | anyone adding files outside `calpi/` |
| `deps/apt-runtime.txt` is installed by `scripts/pi deps` | US-13, US-15, US-29, US-41 (they add packages) |
| `calpi/BUILD` build stamp, logged in `calpi ready ... build=` | US-31 (Status screen shows the build), US-36, US-37 |
| Precompiled `.pyc` under `/opt/calpi` | US-36 (startup time) |
