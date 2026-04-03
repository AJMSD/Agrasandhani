#!/usr/bin/env bash
set -euo pipefail

INTERFACE="${1:-eth0}"
MODE="${2:-clean}"

case "$MODE" in
  clean)
    sudo tc qdisc replace dev "$INTERFACE" root netem delay 0ms loss 0%
    ;;
  bandwidth_200kbps)
    sudo tc qdisc replace dev "$INTERFACE" root tbf rate 200kbit burst 16kb latency 50ms
    ;;
  loss_2pct)
    sudo tc qdisc replace dev "$INTERFACE" root netem loss 2%
    ;;
  loss_5pct)
    sudo tc qdisc replace dev "$INTERFACE" root netem loss 5%
    ;;
  delay_50ms_jitter20ms)
    sudo tc qdisc replace dev "$INTERFACE" root netem delay 50ms 20ms
    ;;
  outage_5s)
    sudo tc qdisc replace dev "$INTERFACE" root netem loss 100%
    sleep 5
    sudo tc qdisc replace dev "$INTERFACE" root netem loss 0%
    ;;
  *)
    echo "Unknown mode: $MODE" >&2
    exit 1
    ;;
esac
