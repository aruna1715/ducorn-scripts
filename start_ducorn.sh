#!/bin/bash
# DuCorn Stack — launchd managed.
#
# Verifies services are SERVING, not that a PID exists. The old version passed
# a port to check_service() and never used it, so it reported "✓ litellm
# running (PID 1454)" while LiteLLM was in a startup-fail loop against a dead
# database. A PID means launchd spawned something. It does not mean it works.
#
# Dependencies are checked in order, and a failure names what it blocked, so
# one dead service at the bottom does not produce eight unrelated errors.

set -u

PGBIN="/opt/homebrew/opt/postgresql@16/bin"
PSQL="$(command -v psql || echo "$PGBIN/psql")"
PGREADY="$(command -v pg_isready || echo "$PGBIN/pg_isready")"
LOGDIR="$HOME/DC/logs"

FAILED=0
BLOCKED=""

red()   { printf "\033[31m%s\033[0m\n" "$1"; }
green() { printf "\033[32m%s\033[0m\n" "$1"; }
warn()  { printf "\033[33m%s\033[0m\n" "$1"; }

# Does this port answer HTTP with one of the accepted codes?
# 401 counts as serving — an authenticated endpoint refusing us is still alive.
probe() {
    local port=$1 path=$2 accept=$3
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" -m 3 "http://localhost:${port}${path}" 2>/dev/null)
    case " $accept " in
        *" $code "*) echo "$code"; return 0 ;;
        *)           echo "$code"; return 1 ;;
    esac
}

# Probe, and if it fails give launchd a kick and probe again.
check_service() {
    local name=$1 port=$2 path=$3 accept=$4
    local label="com.ducorn.$name" code

    if [ -n "$BLOCKED" ]; then
        warn "⊘ $name skipped — blocked by $BLOCKED"
        return 1
    fi

    if ! launchctl list | grep -q "$label"; then
        red "❌ $name not loaded — run: bash ~/DC/launchd/install_launchd.sh"
        FAILED=$((FAILED + 1))
        return 1
    fi

    code=$(probe "$port" "$path" "$accept") && {
        green "✓ $name serving on :$port (HTTP $code)"
        return 0
    }

    warn "⚠ $name has a PID but is not serving on :$port — restarting"
    launchctl kickstart -k "gui/$(id -u)/$label" >/dev/null 2>&1
    local i
    for i in 1 2 3 4 5 6 7 8 9 10; do
        sleep 2
        code=$(probe "$port" "$path" "$accept") && {
            green "✓ $name serving on :$port (HTTP $code, after restart)"
            return 0
        }
    done

    red "❌ $name NOT serving on :$port after restart (last HTTP $code)"
    [ -f "$LOGDIR/$name.log" ] && {
        echo "   last error from $LOGDIR/$name.log:"
        grep -E "Error|error|Exception|failed|refused" "$LOGDIR/$name.log" \
            | tail -3 | sed 's/^/     /'
    }
    FAILED=$((FAILED + 1))
    return 1
}

# Services with no HTTP surface. Say plainly that a PID is all we can check.
check_pid_only() {
    local name=$1 label="com.ducorn.$1" pid
    if [ -n "$BLOCKED" ]; then
        warn "⊘ $name skipped — blocked by $BLOCKED"
        return 1
    fi
    pid=$(launchctl list | grep "$label" | awk '{print $1}')
    if [ -n "$pid" ] && [ "$pid" != "-" ]; then
        echo "· $name has PID $pid (no port to probe — liveness unverified)"
    else
        red "❌ $name not running"
        launchctl kickstart -k "gui/$(id -u)/$label" >/dev/null 2>&1
        FAILED=$((FAILED + 1))
    fi
}

echo "🔍 DuCorn stack"
echo ""

# ── Gate: PostgreSQL ─────────────────────────────────────────────────────────
# Everything else depends on this. LiteLLM refuses to start without its Prisma
# DB; the pipeline stores runs, approvals and LangGraph checkpoints here.
echo "── PostgreSQL ──"
if ! "$PGREADY" -q 2>/dev/null; then
    red "❌ PostgreSQL is not accepting connections"

    # The recurring case: an unclean shutdown leaves postmaster.pid behind and
    # postgres refuses to start rather than risk two postmasters on one data
    # directory. Only call it stale if the PID it names is not a live postgres.
    LOCK="/opt/homebrew/var/postgresql@16/postmaster.pid"
    if [ -f "$LOCK" ]; then
        LOCKPID=$(head -1 "$LOCK" 2>/dev/null)
        if ps -p "$LOCKPID" -o comm= 2>/dev/null | grep -q postgres; then
            warn "   postmaster.pid names PID $LOCKPID, which IS a live postgres."
            warn "   Do not delete the lock — investigate why it isn't accepting"
            warn "   connections (check the log for recovery or config errors)."
        else
            warn "   STALE LOCK: postmaster.pid names PID $LOCKPID, which is not"
            warn "   a postgres process. Left over from an unclean shutdown."
            echo "   Fix:"
            echo "     brew services stop postgresql@16"
            echo "     rm $LOCK"
            echo "     brew services start postgresql@16"
        fi
    else
        echo "   brew services restart postgresql@16"
        echo "   then check: tail -30 /opt/homebrew/var/log/postgresql@16.log"
    fi
    BLOCKED="postgres"
    FAILED=$((FAILED + 1))
else
    green "✓ postgres accepting connections"
    for db in ducorn litellm_db; do
        if "$PSQL" -d "$db" -tAc "SELECT 1" >/dev/null 2>&1; then
            green "✓ database '$db' reachable"
        else
            red "❌ database '$db' unreachable — LiteLLM and the pipeline need it"
            BLOCKED="postgres/$db"
            FAILED=$((FAILED + 1))
        fi
    done
fi
echo ""

# ── Services, in dependency order ────────────────────────────────────────────
echo "── Services ──"
check_service "ollama"    11434 "/"           "200 404"
check_service "litellm"    4000 "/health/liveliness" "200 401 404"
check_service "router"     4001 "/health"     "200"
check_service "api"        8000 "/health"     "200 401"
check_service "pdf"        8001 "/health"     "200 401 404"
check_service "dashboard"  8080 "/"           "200 403"
check_pid_only "cloudflare"
check_pid_only "slack"
echo ""

if [ "$FAILED" -eq 0 ]; then
    green "✅ stack healthy — every service answered on its port"
    echo "   Dashboard:  https://dashboard.ducorn-hq.live"
    echo "   API:        https://api.ducorn-hq.live"
    exit 0
fi

red "❌ $FAILED check(s) failed"
[ -n "$BLOCKED" ] && echo "   Root cause: $BLOCKED — fix that first, the rest will follow."
exit 1
