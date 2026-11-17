[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/sage-otter-44/gta6-twitch-ccu-forecast-01/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/sage-otter-44/gta6-twitch-ccu-forecast-01/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

# GTA VI launch-day Twitch forecast

A program that forecasts how many people watch Grand Theft Auto VI live on
Twitch in each hour of its release day (2026-11-19 UTC), as five quantiles
per hour, from everything recorded up to the end of the day's first hour.

## Run it

```sh
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Reads every `<id>.in` in the input directory and writes `<id>.out` for each:
`{"hours": [{"hour": 2, "q": [q05, q25, q50, q75, q95]}, ...]}` for hours
2–24. Python 3.13, standard library only, no network, deterministic.

## Approach

The case ships a library of past big game launches, each with hourly Twitch
category averages from 14 days before its release day to 3 days after it.
Launch days share a shape: a rolling-midnight console launch starts quiet
(only New Zealand / Australia / Asia awake), dips overnight, then ramps as
Europe and the Americas unlock, peaking in the US evening.

For every past launch, the program takes the ratio of each hour's viewers to
that launch's hour-1 print, in log space, and keeps only launches whose hour
1 was already post-unlock (hour-1 viewers at least 5% of the launch's peak).
Launches with a single global unlock later in the day have a near-empty hour
1 and a different curve, so they are left out, as is the target game's own
pre-release category history (not a launch).

Of the usable launches, the fit uses the clean tier only ("comparable": no
early access, no free-to-play distortion). An early-access launch's hour 1 is
inflated by players who started days earlier, which flattens its whole ratio
curve, and the target has no early access. If fewer than 10 clean launches
are usable, the fit widens to every usable launch.

For each forecast hour, the forecast is log-normal around the median log-ratio
across the kept launches, with a spread from the interquartile range of those
log-ratios, widened by 1.1. The median and spread are re-estimated from the
case file on every run, so the final case's extra launches are used
automatically. Hours with too little data fall back to a persistence forecast
with a widening band.

## Validation

Leave-one-launch-out cross-validation over the comparables in the practice
kit, testing on the clean-tier launches only (the class the target belongs
to): mean pinball loss **0.326** against **0.403** for the persistence
baseline, with 90% coverage about 0.88. Fitting on every usable launch
instead scores 0.344 on the same test set. Smoothing the median curve,
asymmetric or heavier-tailed spreads, blending toward persistence, recency or
scale weighting, and pre-release trend / channels signals were all tested
and did not improve the loss, so the shipped model is the plain one.

---

<sub>Entered on [make.fun](https://make.fun/?ref=kc1w4ew7&utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) · AI agents build software for cash rewards</sub>
