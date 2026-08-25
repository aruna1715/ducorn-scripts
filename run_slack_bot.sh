#!/bin/bash
# DuCorn Slack Bot — keep-alive wrapper
# Restarts the bot automatically if it crashes

export $(grep -v '^#' /Users/ducorn/DC/shared/.env | xargs)

echo "$(date) — Starting DuCorn Slack Bot"

while true; do
    python3.12 /Users/ducorn/DC/scripts/slack_bot.py >> /Users/ducorn/DC/logs/slack_bot.log 2>&1
    EXIT_CODE=$?
    echo "$(date) — Bot died with exit code $EXIT_CODE. Restarting in 5 seconds..."
    sleep 5
done
