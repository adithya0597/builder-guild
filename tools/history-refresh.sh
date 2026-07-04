#!/usr/bin/env bash
# history-refresh.sh (builder-guild-2sr): Stop-hook trigger for etl_history.py --real.
# Guarded steps, each a silent exit 0 on skip -- never blocks, never errors upward.
set -uo pipefail

# ponytail: harness sets CLAUDE_PROJECT_DIR for real hook invocations; this fallback self-locates
# the repo root so `bash tools/history-refresh.sh` also works stand-alone (manual runs, verification).
CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"

# 1. repo-identity guard -- safe even if this file is copy-pasted into a shared/global hook config.
[ -f "$CLAUDE_PROJECT_DIR/01-context/src/etl_history.py" ] || exit 0

# 2. skip silently unless bg-neo4j (or BG_NEO4J_CONTAINER override) is up AND healthy.
# ponytail: `docker ps` against a wedged daemon can hang indefinitely -- stock macOS ships no
# timeout(1). perl (present on macOS + virtually every Linux distro) alarm+exec is the portable
# substitute: alarm schedules SIGALRM on this pid, exec replaces the image with docker in place, so
# the signal (default-fatal, unhandled by the Go docker CLI) still lands on it a few seconds later.
cid=$(perl -e 'alarm 3; exec @ARGV' -- docker ps --filter name="${BG_NEO4J_CONTAINER:-bg-neo4j}" --filter health=healthy -q 2>/dev/null)
[ -n "$cid" ] || exit 0

# 2b. venv guard (silent-skip, same convention as the guards above): etl_history.py imports neo4j at
# top level, a module only the venv interpreter has -- a missing venv would crash the run before any
# output lands, so skip here, BEFORE taking the lock, to never leave an orphan lock behind.
[ -x "$CLAUDE_PROJECT_DIR/01-context/.venv/bin/python" ] || exit 0

# repo-local (not /tmp -- a shared, world-writable dir is a symlink-follow write surface on a
# multi-user host); .buildloop/ is gitignored (.gitignore:63) so neither file ever reaches git.
BUILDLOOP_DIR="$CLAUDE_PROJECT_DIR/.buildloop"
LOG="$BUILDLOOP_DIR/bg-history-refresh.log"
LOCK_DIR="$BUILDLOOP_DIR/bg-history-refresh.lock"
mkdir -p "$BUILDLOOP_DIR"

# 3. single-flight: mkdir is atomic (macOS has no flock) -- exactly one invocation wins the lock and
# launches. Every loser either sees a genuinely-held lock (live pid within lease, or a fresh empty
# lock mid-write) and skips, or sees a stale one, clears it, and DEFERS -- exit 0 with NO launch, so
# the next Stop trigger runs on a clean field. No in-line reclaim-and-relaunch, no mv-to-stale dance.
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  lock_pid=$(cat "$LOCK_DIR/pid" 2>/dev/null)
  # portable mtime, GNU `-c %Y` FIRST: BSD stat rejects -c ("illegal option", non-zero) so 2>/dev/null
  # swallows it and the || falls through to `-f %m` -- neither platform ever hits the other's format
  # garble. The numeric case-guard stays the backstop: any stat surprise degrades to 0 (-> huge age
  # -> stale -> clean+defer, a cost-only outcome), never aborts this hook.
  lock_mtime=$(stat -c %Y "$LOCK_DIR" 2>/dev/null || stat -f %m "$LOCK_DIR" 2>/dev/null || echo 0)
  case "$lock_mtime" in *[!0-9]*|"") lock_mtime=0;; esac
  lock_age=$(( $(date +%s) - lock_mtime ))
  # Lease is a compile-time constant, deliberately NOT env-overridable: two review rounds proved
  # any external value here (non-numeric, then overflow-magnitude) can break the integer held-check
  # below and rm -rf a genuinely-held live lock. No input, no input-validation class. Tests age the
  # lock with touch -t instead of shrinking the lease.
  lease_secs=7200

  if [ -n "$lock_pid" ]; then
    if kill -0 "$lock_pid" 2>/dev/null; then
      [ "$lock_age" -le "$lease_secs" ] && exit 0 # live pid within lease -> genuinely held, skip
      # ponytail: known ceiling -- past the lease we CLEAN the lock but never kill $lock_pid; a hung
      # ETL is left running (SIGKILL mid-write to the DB is worse than a stuck lock) and the field is
      # cleared for the next trigger. Upgrade to a real watchdog only if hung ETLs actually recur.
      reason="lease expired (live pid $lock_pid, age ${lock_age}s > ${lease_secs}s)"
    else
      reason="dead pid $lock_pid"
    fi
  else
    # empty pid = the window between a winner's mkdir and its own `echo pid`. Younger than 60s -> that
    # mid-write is assumed in flight (held); older -> the winner died before writing its pid (stale).
    [ "$lock_age" -lt 60 ] && exit 0
    reason="stale empty lock (age ${lock_age}s)"
  fi

  # stale (dead pid / expired lease / abandoned empty): clear the field and DEFER -- no mkdir, no
  # launch here, so the next Stop trigger starts clean. ponytail: known ceiling -- this rm can race a
  # concurrent fresh winner's mkdir; worst case is one duplicate ETL run, and ingest() is idempotent
  # (MERGE-based), so a duplicate only costs compute, never corrupts.
  echo "[$(date -u +%FT%TZ)] stale lock cleaned ($reason) -- refresh deferred to next trigger" >> "$LOG"
  rm -rf "$LOCK_DIR"
  exit 0
fi

# cap log growth BEFORE this winner appends the ETL output below -- a same-run 5MB truncation must
# never eat evidence it is about to write. Only the single-flight winner reaches here (every loser
# already exited above), so no writer is racing this.
[ -f "$LOG" ] && [ "$(wc -c <"$LOG")" -gt 5242880 ] && : > "$LOG" # 5MB

# 4. backgrounded, non-blocking: subshell forks the real ETL and exits immediately without waiting.
# ponytail: uses the venv interpreter, not the bare on-PATH one -- the latter lacks the neo4j
# module etl_history.py imports at top level; that would crash the run before any output lands.
# -u (unbuffered): stdout is fully block-buffered when redirected to a file, so without this flag
# no progress line reaches the log until the whole run exits -- -u flushes incrementally instead.
# `exec` (not a plain call) for the backgrounded command: without it, "cd && cmd &" forks a wrapper
# shell that runs cd then waits on a separately-forked, separately-redirected cmd -- the wrapper's
# OWN stdout/stderr (inherited from this script, e.g. a hook-runner's capture pipe) stay open the
# whole time, so any reader waiting for EOF blocks for the full ETL run. `exec` replaces the
# subshell in place, so the redirect applies to the only process left standing -- verified empirically
# (mini-repro: plain form blocked a piped reader ~6-8s on a mere `sleep`; `exec` form returned in 0-1s).
# The lock now needs cleanup *after* the ETL exits, which a process replaced by `exec` can never
# run -- so the redirect moved to the outer group instead of the exec line: it is set up when the
# group is forked, before any of its content runs, so this process never holds the hook's pipe
# open either, and can safely `wait` on the exec'd pid and rmdir the lock once it returns.
(
  cd "$CLAUDE_PROJECT_DIR" && exec 01-context/.venv/bin/python -u 01-context/src/etl_history.py --real &
  etl_pid=$!
  echo "$etl_pid" > "$LOCK_DIR/pid"
  wait "$etl_pid"
  # remove only OUR lock: if this ETL outran its lease, a later invocation may have stale-cleaned our
  # lock and a fresh winner remkdir'd it -- $LOCK_DIR would then hold that new owner's pid (or be empty
  # mid-write). Delete solely when the pid file still names our ETL. ponytail: known ceiling -- a
  # remkdir landing in the microsecond between this cat and the rm could still lose, cost-only.
  [ "$(cat "$LOCK_DIR/pid" 2>/dev/null)" = "$etl_pid" ] && rm -rf "$LOCK_DIR"
) >> "$LOG" 2>&1 &
exit 0
