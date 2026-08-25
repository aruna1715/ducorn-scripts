#!/bin/bash
# DuCorn Atomic Deploy Script
# Copies ALL files in one shot — no piecemeal deployments
# Usage: bash deploy_ducorn.sh

set -e
REPO="/Users/ducorn/DC/ducorn-products"
FLOWS="/Users/ducorn/DC/ducorn"
GSTACK="/Users/ducorn/DC/gstack"
SCRIPTS="/Users/ducorn/DC/scripts"

echo "🚀 DuCorn Atomic Deploy"
echo "========================"

# 1. Copy main_flow.py
echo "📋 Deploying main_flow.py..."
cp "$REPO/scripts/main_flow.py" "$FLOWS/flows/main_flow.py"

# 2. Copy run_gstack.py
echo "📋 Deploying run_gstack.py..."
cp "$REPO/scripts/run_gstack.py" "$GSTACK/run_gstack.py"

# 3. Copy DuCornDeployTool
echo "📋 Deploying DuCornDeployTool.py..."
cp "$REPO/scripts/DuCornDeployTool.py" "$FLOWS/tools/DuCornDeployTool.py"

# 4. Clear Python cache
echo "🧹 Clearing Python cache..."
find "$FLOWS" -name "*.pyc" -delete 2>/dev/null
find "$FLOWS" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null

# 5. Restart API
echo "🔄 Restarting API..."
launchctl stop com.ducorn.api
sleep 3
launchctl start com.ducorn.api
sleep 5

# 6. Verify
echo ""
echo "✅ Verification:"
/Users/ducorn/DC/ducorn/.venv/bin/python -c "
import sys
sys.path.insert(0, '/Users/ducorn/DC/scripts')
sys.path.insert(0, '/Users/ducorn/DC/ducorn')
sys.path.insert(0, '/Users/ducorn/DC/gstack')
from flows.main_flow import DuCornFlow
from run_gstack import run_gstack, SKILL_NAMES
from tools.DuCornDeployTool import DuCornDeployTool
print('  main_flow OK')
print('  run_gstack OK')
print('  DuCornDeployTool OK')
" && echo "✅ All components verified" || echo "❌ Verification failed"

curl -s http://localhost:8000/health -H "x-api-key: ducorn-api-2026-secure" && echo "" || echo "❌ API not responding"

echo ""
echo "✅ Deploy complete!"
