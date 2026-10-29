#!/bin/zsh
# Keep pressing Chrome's "Allow remote debugging?" sheet for a whole work session.
#
# Why this wrapper exists. Chrome raises that sheet on EVERY new remote-debugging client connection,
# and `allow-remote-debugging.sh` presses ONE sheet and exits. A consult that connects more than once
# — a retry, a re-resolve, a second tab — therefore leaves a second sheet sitting on the user's
# screen. That is not a silent inconvenience: the CDP websocket handshake does not error, it BLOCKS
# in recv, so the tool appears to hang while a modal waits for a human.
#
# Pressing that sheet is the agent's job, never the user's. This happened on 2026-09-26 and he had to
# click it himself, which is a wasted turn and exactly the thing the helper exists to prevent.
#
# Usage — start BEFORE the first connection, kill when the work is done:
#   ~/dev/Dispatch/providers/chatgpt/bin/keep-allowing.sh 300 &
#   PRESSER=$!
#   ... run consults ...
#   kill $PRESSER
#
# Exit code is always 0: a run in which no sheet ever appeared is a success, not a failure.

set -u
DEADLINE=$(( $(date +%s) + ${1:-300} ))
HELPER="${MACHINIST_TOOLS:?set MACHINIST_TOOLS}/allow-remote-debugging.sh"

if [[ ! -x "$HELPER" ]]; then
  print -u2 "keep-allowing: $HELPER not found or not executable"
  exit 0
fi

presses=0
while (( $(date +%s) < DEADLINE )); do
  # A short per-attempt deadline so this polls rather than blocking on one long wait: the helper
  # returns 1 quickly when no sheet is up, which is the common case between connections.
  "$HELPER" 2 >/dev/null 2>&1; rc=$?
  if (( rc == 0 )); then
    presses=$(( presses + 1 ))
    print -u2 "keep-allowing: pressed Allow (#$presses)"
  elif (( rc == 3 )); then
    # The helper CANNOT look (no Accessibility grant, or a stale axprobe). Polling for 30 minutes
    # would look armed while being blind, so say it once and stop.
    print -u2 "keep-allowing: helper cannot look (exit 3); run it by hand to see why. Stopping."
    exit 0
  fi
  sleep 0.4
done
print -u2 "keep-allowing: done, $presses sheet(s) pressed"
exit 0
