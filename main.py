"""Forecast GTA VI's launch-day Twitch viewers, hour by hour.

Entry for make.fun's gta6-twitch-ccu-forecast-01 (program/v1). Reads one case
file per run (/input/<id>.in) and writes one forecast (/output/<id>.out):
for each of hours 2..24 of the release day, five quantiles (5%, 25%, 50%, 75%,
95%) of that hour's concurrent Twitch viewers in the game's category.

How it forecasts
---------------
The case ships a library of past big game launches ("comparables"): each one's
hourly Twitch category averages from 14 days before its release day to 3 days
after it. Launch days share a shape: the UTC day of a rolling-midnight console
launch starts quiet (only New Zealand / Australia / Asia awake), dips overnight,
then ramps as Europe and then the Americas unlock, peaking in the US evening.

For every past launch I take the ratio of each hour's viewers to that launch's
hour-1 print, in log space, and keep only launches whose hour 1 was already
post-unlock (hour-1 viewers at least 5% of the launch's peak). Launches whose
hour 1 predates their unlock (a single global unlock later in the day) have a
near-empty hour 1 and a totally different curve, so they are left out; the
target game's own pre-release category history is not a launch either and is
left out the same way.

Of the usable launches I fit on the clean ones only: tier "comparable" (no
early access, no free-to-play distortion). An early-access launch's hour 1 is
inflated by players who started days earlier, which flattens its whole ratio
curve, and the target has no early access — tested on the comparable-tier
launches alone, fitting on the clean tier scores 0.326 against 0.344 fitting
on every rolling launch. If fewer than 10 clean launches are usable, the fit
falls back to every usable launch rather than fitting on almost nothing.

For each forecast hour h, the forecast is a log-normal around the median
log-ratio across the kept launches, with a spread from the interquartile range
of those log-ratios, widened by a factor 1.1 (tuned by leave-one-launch-out
cross-validation: on comparable-tier launches, mean pinball loss 0.326
against 0.403 for the persistence baseline, 90% coverage about 0.88). The
median and spread are re-estimated from the case file on every run, so the
four extra launches the final case ships (including Red Dead Redemption 2,
the closest analogue) are used automatically.

Everything is deterministic: no randomness, no clock, no network, no state
between runs. Standard library only; runs in well under a second per case.
"""

import json
import math
import os
import statistics
from datetime import datetime
from pathlib import Path

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

# A launch counts as usable only if its hour 1 was already post-unlock.
MIN_HOUR1_SHARE_OF_PEAK = 0.05
# At least this many usable launches, else fall back to the persistence shape.
MIN_USABLE_LAUNCHES = 5
# Prefer this many clean (tier "comparable") launches; fewer, and the fit
# widens to every usable launch instead of fitting on almost nothing.
MIN_CLEAN_LAUNCHES = 10
# Spread widening, tuned by leave-one-launch-out cross-validation.
SPREAD_MULTIPLIER = 1.1
# Floor on the per-hour log spread, so a freakishly tight hour still gets a band.
MIN_SIGMA = 0.08
# The persistence fallback's spread, in log units per square-root hour.
FALLBACK_SIGMA = 0.15


def parse_instant(text):
    """An ISO 8601 UTC timestamp (with a trailing Z) as an aware datetime."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def norm_ppf(p):
    """The standard normal's quantile at p (Acklam's rational approximation).

    Accurate to about 1.2e-9 in absolute terms: far tighter than the rounding
    the output gets, and it lets the program honour whatever levels a case
    lists instead of hard-coding five numbers.
    """
    if not 0.0 < p < 1.0:
        raise ValueError(f"quantile level {p} is outside (0, 1)")
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285984469534e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    p_low = 0.02425
    p_high = 1.0 - p_low
    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    if p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
            (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
        ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)


def round2(x):
    """x rounded to 2 decimals, half up (all values here are positive)."""
    return math.floor(x * 100 + 0.5) / 100


def release_day_curve(comparable):
    """Hourly viewers for the 24 UTC hours of a launch's release day.

    Returns a list of 24 entries (hour 1 first), None where the source has no
    point for that hour. Hours are counted from the launch's day_start.
    """
    try:
        day0 = parse_instant(comparable["day_start"])
    except (KeyError, TypeError, ValueError):
        return [None] * 24
    curve = [None] * 24
    for row in comparable.get("hourly") or []:
        viewers = row.get("viewers")
        if viewers is None:
            continue
        try:
            when = parse_instant(row["from"])
        except (KeyError, TypeError, ValueError):
            continue
        hour = int((when - day0).total_seconds() // 3600) + 1
        if 1 <= hour <= 24:
            curve[hour - 1] = viewers
    return curve


def usable_launch(curve):
    """True when a launch's hour 1 was already post-unlock.

    A launch that unlocked later in the day has a near-empty hour 1 and a
    spike at its unlock hour: a different shape from a rolling-midnight
    launch, so it must not enter the ratio statistics. The target game's own
    pre-release history has no hour 1 at all and is dropped the same way.
    """
    first = curve[0]
    if not first or first <= 0:
        return False
    peak = max((v for v in curve if v), default=0)
    return peak > 0 and first >= MIN_HOUR1_SHARE_OF_PEAK * peak


def tier_of(comparable):
    """The launch's tier, read from its unlock note ("Tier: comparable", ...).

    Returns "comparable", "early-access-contaminated", "weak", or "unknown"
    when the note carries no tier. The clean tier is the fit set: no early
    access, no free-to-play distortion, the shape the target's launch has.
    """
    note = comparable.get("unlock") or ""
    for tier in ("early-access-contaminated", "comparable", "weak"):
        if f"Tier: {tier}" in note:
            return tier
    return "unknown"


def median_log_ratios(curves):
    """Per-hour median and spread of ln(viewers_h / viewers_1) over launches.

    Returns {hour: (median, sigma)} for hours 2..24. Hours with too few
    launches are left out; the caller fills those from the fallback.
    """
    out = {}
    for hour in range(2, 25):
        ratios = []
        for curve in curves:
            first, value = curve[0], curve[hour - 1]
            if first and first > 0 and value and value > 0:
                ratios.append(math.log(value / first))
        if len(ratios) < MIN_USABLE_LAUNCHES:
            continue
        median = statistics.median(ratios)
        quartiles = statistics.quantiles(ratios, n=4)
        sigma = (quartiles[2] - quartiles[0]) / 1.349
        out[hour] = (median, max(sigma, MIN_SIGMA))
    return out


def forecast_case(case):
    """The forecast object for one case: {"hours": [{"hour", "q": [...]}]}."""
    levels = case.get("levels") or [0.05, 0.25, 0.5, 0.75, 0.95]
    z_scores = [norm_ppf(level) for level in levels]

    first = next((k for k in case.get("known") or [] if k.get("hour") == 1), None)
    if first is not None and first.get("viewers"):
        anchor = max(1, first["viewers"])
    else:
        # No hour-1 print: fall back to the last recorded point, then to 1.
        # The output stays valid instead of the run crashing.
        history = case.get("history") or []
        anchor = 1
        for point in history:
            if point.get("viewers"):
                anchor = max(1, point["viewers"])

    usable = [(comp, release_day_curve(comp)) for comp in case.get("comparables") or []]
    usable = [(comp, curve) for comp, curve in usable if usable_launch(curve)]
    clean = [curve for comp, curve in usable if tier_of(comp) == "comparable"]
    # Fit on the clean tier when there are enough of them; otherwise widen
    # to every usable launch rather than fitting on almost nothing.
    fit_curves = clean if len(clean) >= MIN_CLEAN_LAUNCHES else [curve for _, curve in usable]
    fitted = median_log_ratios(fit_curves) if len(fit_curves) >= MIN_USABLE_LAUNCHES else {}

    hours = []
    for row in case.get("forecast") or []:
        hour = row["hour"]
        if hour in fitted:
            median, sigma = fitted[hour]
            quantiles = [anchor * math.exp(median + z * sigma * SPREAD_MULTIPLIER)
                         for z in z_scores]
        else:
            # No usable fit for this hour: persistence with a widening band.
            quantiles = [anchor * math.exp(z * FALLBACK_SIGMA * math.sqrt(hour - 1))
                         for z in z_scores]
        # Round, keep inside (0, 1e9], and keep the row non-decreasing.
        cleaned = []
        previous = 0.0
        for q in quantiles:
            value = min(round2(q), 1_000_000_000)
            value = max(value, previous, 0.01)
            cleaned.append(value)
            previous = value
        hours.append({"hour": hour, "q": cleaned})
    hours.sort(key=lambda row: row["hour"])
    return {"hours": hours}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Every case file, in name order, so two runs write the same bytes.
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
