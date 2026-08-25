#!/bin/bash
# DuCorn Stack — launchd managed
# Services are managed by launchd. This script verifies status.

echo "🔍 Checking DuCorn stack status..."

check_service() {
    local name=$1
    local port=$2
    local label="com.ducorn.$name"
    
    if launchctl list | grep -q "$label"; then
        pid=$(launchctl list | grep "$label" | awk '{print $1}')
        if [ "$pid" != "-" ]; then
            echo "✓ $name running (PID $pid)"
        else
            echo "⚠ $name not running — restarting..."
            launchctl start "$label"
        fi
    else
        echo "❌ $name not loaded — run: bash ~/DC/launchd/install_launchd.sh"
    fi
}

check_service "ollama" 11434
check_service "litellm" 4000
check_service "router" 4001
check_service "api" 8000
check_service "pdf" 8001
check_service "dashboard" 8080
check_service "cloudflare" ""
check_service "slack" ""

echo ""
echo "✅ DuCorn stack status checked."
echo "   Dashboard:  https://dashboard.ducorn-hq.live"
echo "   API:        https://api.ducorn-hq.live"
echo ""

# Quick health check
curl -s http://localhost:4001/health