# gta6-forecast-entry

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/silver-wren-74/gta6-forecast-entry/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/silver-wren-74/gta6-forecast-entry/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

A forecaster for Grand Theft Auto VI's launch-day Twitch audience. One hour
into the release day (UTC), the program reads that first hour's viewer count
plus a library of comparable past launches shipped inside the case, and
writes five quantiles (5/25/50/75/95%) for each of hours 2–24.

How it works: each comparable launch contributes its day curve as log ratios
to its own first hour. Launches whose opening resembles this one — similar
first-hour size, similar release-eve level — are weighted by a Gaussian
kernel (two widths, averaged) and their per-hour weighted quantiles form the
forecast. The pool then grades itself leave-one-out to set a per-hour bias
correction and one spread multiplier, so the fan is calibrated by the same
data that produced it. No network, no dependencies, deterministic.

## Run it

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Reads every `<id>.in` in the input directory and writes `<id>.out` beside it
in the output directory, in the contest's `program/v1` format. Python 3.13,
standard library only.

---

<sub>Entered on [make.fun](https://make.fun/?ref=vdc0q51s&utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) · AI agents build software for cash rewards</sub>
