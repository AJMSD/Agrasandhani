# Optional `tc netem` cross-check

This folder is Linux-only validation tooling for M4. It is not required for the default Windows/macOS experiment workflow.

Usage:

```bash
chmod +x ./experiments/netem/apply_netem.sh
./experiments/netem/apply_netem.sh eth0 clean
./experiments/netem/apply_netem.sh eth0 delay_50ms_jitter20ms
```

Supported scenario names:

- `clean`
- `bandwidth_200kbps`
- `loss_2pct`
- `loss_5pct`
- `delay_50ms_jitter20ms`
- `outage_5s`

Reset the interface after a cross-check:

```bash
sudo tc qdisc del dev eth0 root
```
