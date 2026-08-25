#!/bin/bash
echo "Stopping DuCorn Slack Bot..."
ps -ef | grep -E "slack_bot|run_slack_bot" | grep -v grep | awk '{print $2}' | xargs kill -9 2>/dev/null
sleep 2
ps -ef | grep slack | grep -v grep | wc -l | xargs -I{} echo "Remaining processes: {}"
echo "Done."
