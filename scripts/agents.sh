#!/usr/bin/env bash
# Run Claude Code agents in parallel, one bead per git worktree.
#
#   scripts/agents.sh start <bead-id>...   claim beads and launch an agent for each
#   scripts/agents.sh start --ready N      pick the top N ready non-epic beads
#   scripts/agents.sh list                 show agent worktrees, slots and PRs
#   scripts/agents.sh clean <bead-id>...   remove worktree and local branch
#
# Options for start:
#   --mode <permission-mode>   passed to claude (default: auto)
#   --dry-run                  set nothing up, print what would happen
#
# Each agent gets:
#   worktree  ../travelplanner-agents/<bead-id>, branch agent/<bead-id> off origin/master
#   slot N    API port 8000+N, web port 5173+N, Postgres test DB tp_agent_N
#   env       copies of backend/.env and web/.env.local rewritten for those ports
#   deps      backend/.venv symlinked, web/node_modules APFS-cloned
# See "Parallel Agents" in CLAUDE.md for the rules agents follow.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
AGENTS_DIR="$(dirname "$REPO")/travelplanner-agents"
MAX_SLOTS=9

die() { echo "error: $*" >&2; exit 1; }

used_slots() {
  cat "$AGENTS_DIR"/*/.agent-slot 2>/dev/null || true
}

free_slot() {
  local used n
  used="$(used_slots)"
  for n in $(seq 1 "$MAX_SLOTS"); do
    if ! grep -qx "$n" <<<"$used"; then echo "$n"; return; fi
  done
  die "all $MAX_SLOTS slots in use; clean up finished agents first"
}

ready_beads() {
  bd ready --json | jq -r --argjson n "$1" \
    '[.[] | select(.status == "open" and .issue_type != "epic")] | .[:$n] | .[].id'
}

agent_prompt() {
  local bead="$1" slot="$2"
  cat <<EOF
You are a parallel agent working on bead $bead in your own git worktree
(branch agent/$bead). Other agents are working on other beads at the same time.

1. Read the "Parallel Agents" section of CLAUDE.md and follow it.
2. Run \`bd show $bead\` and implement it. The bead is already claimed for you.
   Stay within its scope; file new beads for anything else you find.
3. Your slot is $slot: API on port $((8000 + slot)), web on port $((5173 + slot)),
   Postgres test DB tp_agent_$slot. Your .env files already use these ports.
4. Run the quality gates, commit, push the branch and open a PR with gh.
   Never push to master.
5. Record the PR URL with \`bd update $bead --notes "PR: <url>"\`. Leave the bead
   in progress; it is closed when the PR merges.
EOF
}

setup_worktree() {
  local bead="$1" slot="$2" wt="$AGENTS_DIR/$1"

  git -C "$REPO" worktree add -q -b "agent/$bead" "$wt" origin/master
  echo "$slot" > "$wt/.agent-slot"

  if [[ -f "$REPO/backend/.env" ]]; then
    sed -E "s#^CORS_ORIGINS=.*#CORS_ORIGINS=http://localhost:$((5173 + slot))#" \
      "$REPO/backend/.env" > "$wt/backend/.env"
  fi
  if [[ -f "$REPO/web/.env.local" ]]; then
    sed -E "s#^VITE_API_URL=http://localhost:[0-9]+#VITE_API_URL=http://localhost:$((8000 + slot))#" \
      "$REPO/web/.env.local" > "$wt/web/.env.local"
  fi

  [[ -d "$REPO/backend/.venv" ]] && ln -s "$REPO/backend/.venv" "$wt/backend/.venv"
  # cp -c clones on APFS: instant, and the agent's npm install can't touch the main checkout.
  [[ -d "$REPO/web/node_modules" ]] && cp -cR "$REPO/web/node_modules" "$wt/web/node_modules"
  return 0
}

cmd_start() {
  local mode="auto" dry_run=0 beads=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --mode) mode="$2"; shift 2 ;;
      --dry-run) dry_run=1; shift ;;
      --ready)
        [[ "${2:-}" =~ ^[0-9]+$ ]] || die "--ready needs a number"
        while read -r id; do [[ -n "$id" ]] && beads+=("$id"); done < <(ready_beads "$2")
        shift 2 ;;
      -*) die "unknown option $1" ;;
      *) beads+=("$1"); shift ;;
    esac
  done
  [[ ${#beads[@]} -gt 0 ]] || die "no beads given (pass ids or --ready N)"

  mkdir -p "$AGENTS_DIR"
  [[ $dry_run -eq 1 ]] || git -C "$REPO" fetch -q origin master

  local bead slot status next_dry_slot=0
  for bead in "${beads[@]}"; do
    [[ -e "$AGENTS_DIR/$bead" ]] && { echo "skip $bead: worktree already exists"; continue; }
    # Every session runs as the same bd user, so --claim succeeds even when another
    # session already holds the bead. Only take beads that are still open.
    status="$(bd show "$bead" --json | jq -r 'if type == "array" then .[0].status else .status end')"
    if [[ "$status" != "open" ]]; then
      echo "skip $bead: status is $status"; continue
    fi
    if [[ $dry_run -eq 1 ]]; then
      # Slots aren't written in a dry run, so count forward from the first free one.
      [[ $next_dry_slot -eq 0 ]] && next_dry_slot="$(free_slot)"
      slot=$next_dry_slot; next_dry_slot=$((next_dry_slot + 1))
      echo "would start $bead in slot $slot ($AGENTS_DIR/$bead, mode $mode): $(bd show "$bead" --json | jq -r 'if type == "array" then .[0].title else .title end')"
      continue
    fi

    if ! bd update "$bead" --claim >/dev/null; then
      echo "skip $bead: could not claim"; continue
    fi
    slot="$(free_slot)"
    setup_worktree "$bead" "$slot"
    echo "started $bead in slot $slot:"
    (cd "$AGENTS_DIR/$bead" && claude --bg -n "$bead" --permission-mode "$mode" "$(agent_prompt "$bead" "$slot")")
  done
  [[ $dry_run -eq 1 ]] || echo "Watch them with: claude agents   (attach with: claude attach <id>)"
}

cmd_list() {
  local wt bead slot pr
  [[ -d "$AGENTS_DIR" ]] || { echo "no agents"; return; }
  for wt in "$AGENTS_DIR"/*/; do
    [[ -f "$wt/.agent-slot" ]] || continue
    bead="$(basename "$wt")"
    slot="$(cat "$wt/.agent-slot")"
    pr="$(gh pr view "agent/$bead" --json url,state -q '.url + " (" + .state + ")"' 2>/dev/null || echo "no PR")"
    printf '%-22s slot %s  %s\n' "$bead" "$slot" "$pr"
  done
}

cmd_clean() {
  [[ $# -gt 0 ]] || die "no beads given"
  local bead wt
  for bead in "$@"; do
    wt="$AGENTS_DIR/$bead"
    [[ -d "$wt" ]] || { echo "skip $bead: no worktree"; continue; }
    if [[ -n "$(git -C "$wt" status --porcelain)" ]]; then
      echo "skip $bead: uncommitted changes in $wt"; continue
    fi
    git -C "$REPO" worktree remove --force "$wt"
    git -C "$REPO" branch -D "agent/$bead" >/dev/null 2>&1 || true
    echo "removed $bead"
  done
}

case "${1:-}" in
  start) shift; cmd_start "$@" ;;
  list) shift; cmd_list ;;
  clean) shift; cmd_clean "$@" ;;
  *) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
