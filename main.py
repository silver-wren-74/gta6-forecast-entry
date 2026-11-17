"""Forecast a game launch day's Twitch viewers, hour by hour (make.fun
gta6-twitch-ccu-forecast-01).

The program reads one case: a launch day cut one hour in, with that first
hour's viewer count and a library of comparable past launches, each with its
full hourly curve. For every later hour it predicts five quantiles of the
viewer count, scored by pinball loss on the log scale.

Method, in one paragraph: a launch's day is described by the log ratio of
each hour's viewers to its first hour's. Comparable launches whose opening
looks like this launch's opening — a similar first-hour size and a similar
release-eve level (the last hour before the day starts, against the first
hour) — lend their ratio curves to a kernel-weighted quantile for each hour.
Two kernel widths are averaged. The pool then grades itself leave-one-out:
each comparable is forecast from the others, and the per-hour median miss of
the middle quantile becomes a (half-shrunk) bias correction, while a single
spread multiplier is picked from a small grid by the same self-grading. With
no usable comparables the program falls back to the persistence curve: the
first hour's count with a slowly widening lognormal spread.

Standard library only, offline, deterministic. The grader runs
`python3 -P -s /bot/main.py`; locally, MAKEFUN_INPUT_DIR and
MAKEFUN_OUTPUT_DIR stand in for /input and /output.
"""

import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
NORMAL_Z = [-1.645, -0.674, 0.0, 0.674, 1.645]
# Kernel widths over (log first-hour viewers, release-eve log ratio).
KERNELS = [(1.2, 0.9), (0.9, 0.7)]
KERNEL_FLOOR = 0.02
SPREAD_GRID = [0.85, 0.925, 1.0, 1.075, 1.15]
BIAS_SHRINK = 0.5
MIN_FIRST_HOUR = 300.0


def parse_ts(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def round2(x):
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100
    return int(value) if float(value).is_integer() else value


def hourly_series(points):
    """Map hour-start datetime -> viewers, from rows carrying from/viewers
    (whole-hour means) or at/viewers (raw reads averaged into their hour)."""
    buckets = {}
    for row in points or []:
        stamp = row.get("from") or row.get("at")
        viewers = row.get("viewers")
        if stamp is None or viewers is None:
            continue
        t = parse_ts(stamp)
        if row.get("from") is None:
            t = t.replace(minute=0, second=0, microsecond=0)
        buckets.setdefault(t, []).append(float(viewers))
    return {t: sum(v) / len(v) for t, v in buckets.items()}


class Launch:
    """One launch's checkpoint view: first-hour print, eve day, pre-release
    mean, and (for comparables) the release day's log-ratio curve."""

    def __init__(self, day_start, series, first_viewers):
        self.day_start = day_start
        self.first = max(1.0, float(first_viewers))
        self.eve = []
        for k in range(24, 0, -1):
            self.eve.append(series.get(day_start - timedelta(hours=k)))
        pre = [v for t, v in series.items()
               if day_start - timedelta(days=14) <= t < day_start - timedelta(hours=24)]
        self.pre_mean = sum(pre) / len(pre) if pre else None
        self.day = []
        for h in range(24):
            self.day.append(series.get(day_start + timedelta(hours=h)))
        self.features = self._features()
        self.ratios = self._ratios()

    def _eve1(self):
        # Viewers one hour before the day starts; if that hour is missing,
        # take the nearest sampled hour within the next few.
        for j in range(23, 19, -1):
            if self.eve[j] is not None:
                return max(1.0, self.eve[j])
        return self.first

    def _features(self):
        return {
            "ln_p1": math.log(self.first),
            "eve1": math.log(self._eve1() / self.first),
        }

    def _ratios(self):
        out = []
        for h in range(1, 24):
            v = self.day[h]
            out.append(math.log(max(1.0, v) / self.first) if v is not None else None)
        return out


def weighted_quantile(pairs, tau):
    pairs = sorted(pairs)
    total = sum(w for _, w in pairs)
    acc = 0.0
    for value, w in pairs:
        acc += w
        if acc >= tau * total:
            return value
    return pairs[-1][0]


def base_forecast(pool, target_features):
    """Kernel-weighted per-hour quantiles of the pool's log-ratio curves."""
    weights_per_kernel = []
    for scale_p1, scale_eve in KERNELS:
        ws = []
        for launch in pool:
            d2 = ((launch.features["ln_p1"] - target_features["ln_p1"]) / scale_p1) ** 2 \
                + ((launch.features["eve1"] - target_features["eve1"]) / scale_eve) ** 2
            ws.append(math.exp(-0.5 * d2) + KERNEL_FLOOR)
        weights_per_kernel.append(ws)
    out = []
    for hi in range(23):
        row = []
        for tau in LEVELS:
            acc = 0.0
            for ws in weights_per_kernel:
                pairs = [(launch.ratios[hi], ws[r]) for r, launch in enumerate(pool)
                         if launch.ratios[hi] is not None]
                acc += weighted_quantile(pairs, tau)
            row.append(acc / len(weights_per_kernel))
        out.append(row)
    return out


def pinball(rows, actual_ratios):
    total, n = 0.0, 0
    for hi in range(23):
        y = actual_ratios[hi]
        if y is None:
            continue
        for tau, q in zip(LEVELS, rows[hi]):
            d = y - q
            total += 2 * max(tau * d, (tau - 1) * d)
            n += 1
    return total / n if n else 0.0


def apply_calibration(rows, bias, spread):
    out = []
    for hi in range(23):
        med = rows[hi][2] + BIAS_SHRINK * bias[hi]
        row = [med + spread * (rows[hi][j] - rows[hi][2]) for j in range(5)]
        row[2] = med
        out.append(row)
    return out


def self_calibrate(pool):
    """Grade the pool leave-one-out; return (per-hour median bias, spread)."""
    loo = []
    for i, launch in enumerate(pool):
        rest = pool[:i] + pool[i + 1:]
        loo.append(base_forecast(rest, launch.features))
    bias = []
    for hi in range(23):
        misses = sorted(pool[i].ratios[hi] - loo[i][hi][2] for i in range(len(pool))
                        if pool[i].ratios[hi] is not None)
        bias.append(misses[len(misses) // 2] if misses else 0.0)
    best_spread, best_loss = 1.0, None
    for spread in SPREAD_GRID:
        loss = sum(pinball(apply_calibration(loo[i], bias, spread), pool[i].ratios)
                   for i in range(len(pool)))
        if best_loss is None or loss < best_loss:
            best_loss, best_spread = loss, spread
    return bias, best_spread


def persistence(first, hours):
    rows = []
    for h in hours:
        qs = [round2(first * math.exp(z * 0.15 * math.sqrt(h - 1))) for z in NORMAL_Z]
        rows.append({"hour": h, "q": qs})
    return {"hours": rows}


def forecast_case(case):
    hours = [row["hour"] for row in case["forecast"]]
    known = next((k for k in case["known"] if k["hour"] == 1), None)
    if known is None:
        raise ValueError("case has no hour-1 print")
    first = max(1.0, float(known["viewers"]))
    day_start = parse_ts(case["day_start"])

    target_series = hourly_series(case.get("history_hourly") or case.get("history"))
    target = Launch(day_start, target_series, first)

    pool = []
    for comp in case.get("comparables") or []:
        try:
            comp_start = parse_ts(comp["day_start"])
            series = hourly_series(comp.get("hourly"))
            comp_first = series.get(comp_start)
            if comp_first is None or comp_first < MIN_FIRST_HOUR:
                continue
            launch = Launch(comp_start, series, comp_first)
            if sum(1 for r in launch.ratios if r is not None) < 18:
                continue
            pool.append(launch)
        except Exception:
            continue

    if len(pool) < 5:
        return persistence(first, hours)

    rows = base_forecast(pool, target.features)
    bias, spread = self_calibrate(pool)
    rows = apply_calibration(rows, bias, spread)

    out_rows = []
    for idx, h in enumerate(hours):
        hi = h - 2
        if hi < 0 or hi >= 23:
            qs = [round2(first)] * 5
        else:
            qs = [round2(min(1e9, max(0.01, first * math.exp(v)))) for v in rows[hi]]
            qs = sorted(qs)
        out_rows.append({"hour": h, "q": qs})
    return {"hours": out_rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        result = forecast_case(case)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(result, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
