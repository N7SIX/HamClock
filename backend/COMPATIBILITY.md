# Compatibility

This document describes the minimum and recommended hardware requirements for running **OHB (Open HamClock Backend)**.

## Minimum Requirements (Supported)

- **Hardware:** Raspberry Pi 4–class compute (or equivalent)
  - Pi 3-class systems are not supported due to limited CPU, memory, and I/O throughput for scheduled fetch + render workloads.
- **Storage:** **64GB microSDHC** (or larger)
- **SD Card Performance:** **Use the fastest microSD card that is compatible with the Raspberry Pi 4**
  - Preference: high-endurance / high-performance cards with strong random I/O and sustained write performance.

## Recommended (Better Experience)

- **Raspberry Pi 4 with more RAM** (4GB or 8GB preferred)
- **128GB microSD** (or SSD via USB 3.0)
- Adequate cooling (heatsink/fan) for sustained rendering workloads

## Why These Requirements Exist

OHB performs periodic background jobs (fetching upstream data, generating map assets, compressing images, and writing artifacts). These workloads are storage- and CPU-sensitive. Slower SD cards and lower-tier hardware tend to produce timeouts, long runtimes, and intermittent failures under normal update schedules.

