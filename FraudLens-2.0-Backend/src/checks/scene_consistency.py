"""
fraudlens.checks.scene_consistency
====================================

"Does the photograph agree with the story the claimant told?"

This is the check the whole perception pipeline exists to enable, and the
one that produces a sentence a claims handler can act on without
understanding any of the machinery:

    "The claim states 18:00, when the sun over Vadodara sits low in the
    west and shadows run long toward the east-northeast; the image shows
    short shadows pointing north, consistent with midday."

That is not a similarity score or a model's opinion. It is arithmetic
about where the sun was, set against what the picture shows - falsifiable
by anyone with an ephemeris, and explainable to a regulator. Physics
contradicting a claimant is the strongest evidence this system can
produce, and it is the reason CONTEXT is a category at all.

Three independent sub-checks, all against the *declared* incident time
and location:

(a) Solar geometry. pysolar gives the sun's azimuth and elevation for the
    declared instant at the declared coordinates. Shadows point opposite
    the sun, so expected shadow bearing = solar azimuth + 180 degrees;
    more than 90 degrees away from what the image shows is a
    contradiction, not a rounding error. Elevation fixes length: a high
    sun casts short shadows, a low one long.

(b) Weather. Open-Meteo's archive (free, no key) gives precipitation and
    cloud cover for that date and place. A claim photographed in rain on
    a day with no recorded precipitation, or a wet road under a cloudless
    sky, is a contradiction.

(c) Lighting. Daylight in the photograph when the sun was below the
    horizon - or night when it was overhead - contradicts the declared
    time directly, and needs no shadows to be visible.

--------------------------------------------------------------------
"I cannot tell" is never suspicion
--------------------------------------------------------------------
Perception answers "none_visible" for shadows it cannot see and "unknown"
for weather and lighting it cannot judge, and those answers must produce
INCONCLUSIVE, never CONCERN. Most claim photographs are close crops of
damage with no sky, no horizon and no shadow in frame; scoring that
absence as suspicious would fire on the majority of honest claims and
destroy the false-positive rate. Same rule as missing EXIF in
metadata.py, and it is the single most important line in this module.

--------------------------------------------------------------------
MEASURED after the corpus was fixed: 7/20, and a variant split that
matters more than the headline
--------------------------------------------------------------------
The first measurement of this check (2/9) was taken against a corpus in
which CONTEXT_MISMATCH was unfalsifiable: the generator altered the
declared date or hour and attached an arbitrary photograph, so all nine
images showed clear skies and dry ground including the five labelled
"declared monsoon rain but dry-season date". There was nothing to
contradict.

The generator was then inverted - pick the photograph first, build the
declaration against what it visibly shows - and re-measured:

    shadows_vs_after_dark     7/10  (70%)
    dry_photo_vs_rainy_day    0/10  ( 0%)
    overall                   7/20  (35%)

**Variant (b) works.** A photograph showing daylight and standing shadows
against a claim declared after civil twilight is caught 70% of the time,
with an explanation naming the declared hour and the sun's elevation. The
three misses are cases where perception reported no legible lighting or
shadow cue at all, which is the honest INCONCLUSIVE this check is
supposed to give.

**Variant (a) is undetectable BY DESIGN, and deliberately so.** It pairs
a dry, clear photograph with a date on which Open-Meteo reports heavy
rain. The weather sub-check below refuses to treat that as a
contradiction, and the refusal is not an oversight - see the long comment
in _weather_subcheck. Open-Meteo's archive reports a daily *total*;
monsoon rain in Gujarat is intermittent, so 30 mm spread over a day is
entirely compatible with a dry, bright hour at the declared minute.
Firing there would accuse honest claimants of photographing their car
between showers.

So the two halves of the corpus and the check disagree about what counts
as evidence, and the check is right. The generator's variant (a) encodes
an assumption - "it rained that day, therefore it was raining then" -
that the data does not support.

Making variant (a) sound requires a change on BOTH sides, and neither
alone is enough:

  1. the generator should select the declared hour from Open-Meteo's
     *hourly* precipitation, so the claim lands in an hour when rain was
     actually falling; and
  2. this check should query hourly rather than daily precipitation, so
     "dry photograph at an hour with 8 mm of rain" becomes available as a
     contradiction.

Note that (2) would make the check strictly *more* precise in both
directions rather than more aggressive: it would also stop treating a
wet-looking photo as suspicious on a day whose rain fell entirely at
3 a.m. Until both land, variant (a) recall stays 0% and that number
should be read as "the check declined to guess", not "the check missed".

--------------------------------------------------------------------
Fixed corpus artifact: clean-case daylight (48/560 -> 0/560)
--------------------------------------------------------------------
This check previously carried a predicted 8.6% false-positive rate that
had nothing to do with its logic. 48 of 560 clean cases declared a time
at which the sun was below civil twilight at their own coordinates, while
carrying an ordinary daytime photograph: generate_dataset drew the
incident hour uniformly from 7..19 and never checked that the clock and
the picture agreed.

Those were genuine physical contradictions sitting inside cases labelled
clean. The check was right to flag them and the label was wrong, so the
fix went into the generator, not here: clean-case hours are now sampled
from the daylight window computed for that date and location, with the
chosen minute verified rather than an hour tested at :30 and the minute
drawn afterwards (that boundary alone accounted for 13 of the 48).

Measured after the fix: **0 of 560**. Recorded because the temptation in
the other direction was real - dulling the lighting sub-check would have
made the symptom disappear while destroying a signal that turns out to be
the single most productive one this check has (70% on the
shadows_vs_after_dark variant above). The same distinction applies as
with plate_ocr's synthetic registrations: a measurement can describe the
corpus rather than the mechanism, and the fix belongs wherever the fault
actually is.

--------------------------------------------------------------------
Timezone: the declared wall-clock is LOCAL time
--------------------------------------------------------------------
Case.declared_time is stored tagged UTC, but the values are local Indian
wall-clock: src/generate_dataset.py draws the hour uniformly from 7..19
and stamps timezone.utc onto it. Read literally as UTC those become
12:30..00:30 IST, which straddles midnight and is plainly not what "an
incident at 5pm" means - and the CONTEXT_MISMATCH archetype itself is
built by forcing hour=18, which is only a fraud signal if 18:00 means
early evening locally.

So this module interprets the wall-clock as local time and converts to
UTC before asking pysolar anything. Getting this wrong shifts every
computed sun position by 5.5 hours, which would turn honest evening
claims into fabricated night-time ones - the exact false-positive
failure this system is built to avoid. The dataset is not regenerated to
fix the tagging (out of scope, and the raw wall-clock is what a claimant
would actually state); the interpretation is corrected here instead.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ..models import CheckCategory, Finding, Image, PerceptionRecord, Verdict
from .base import Check, CheckContext, register_check

WEATHER_NAMESPACE = "weather"
OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive"
WEATHER_TIMEOUT_SECONDS = 20.0

# India Standard Time. A fixed offset is correct here rather than lazy:
# IST has no daylight saving, and the entire corpus is Gujarat. Outside
# the India bounding box the code falls back to a longitude-derived
# offset, which is crude but better than silently assuming IST for a
# case in another country.
IST_OFFSET = timedelta(hours=5, minutes=30)
INDIA_BOUNDS = (6.0, 37.5, 68.0, 97.5)  # lat_min, lat_max, lon_min, lon_max

COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")

# A shadow bearing must be wrong by more than this to count as a
# contradiction. 90 degrees is deliberately generous - it is "the shadow
# points the wrong way", not "the model's compass estimate is a little
# off", and a vision model reading a bearing off a photograph is doing
# well to land in the right octant.
SHADOW_BEARING_CONCERN_DEG = 90.0

# Solar elevation bands for expected shadow length. Shadow length is
# proportional to 1/tan(elevation): 45 degrees gives a shadow as long as
# the object, 20 degrees gives one about 2.7x its height.
ELEVATION_SHORT_ABOVE = 45.0
ELEVATION_MEDIUM_ABOVE = 20.0

# Civil twilight. Above this the sky is unambiguously lit; below it,
# unambiguously not. Between, "dusk" is a fair answer and no
# contradiction is claimed.
CIVIL_TWILIGHT_DEG = -6.0
LIGHTING_NIGHT_CONFLICT_DEG = 15.0

# Open-Meteo precipitation, in mm/day.
RAIN_MM = 1.0          # above this, it demonstrably rained (daily total)
# mm within a single hour above which rain was demonstrably falling at
# the declared time. Matches RAINY_HOUR_MM in src/generate_dataset.py so
# the generator and the check agree on what "it was raining" means.
RAINY_HOUR_MM = 0.5
DRY_MM = 0.1           # below this, it demonstrably did not
OVERCAST_CLOUD_PCT = 70.0
CLEAR_CLOUD_PCT = 30.0

_WET_WORDS = ("wet", "damp", "puddle", "soaked", "slick", "standing water")
_DRY_WORDS = ("dry", "dusty", "parched")


# ---------------------------------------------------------------------------
# Time and solar geometry
# ---------------------------------------------------------------------------


def local_wallclock_to_utc(declared: datetime, latitude: float, longitude: float) -> datetime:
    """
    Reinterpret a declared timestamp's wall-clock as local time and
    return the true UTC instant. See the module docstring for why this
    is necessary rather than pedantic.
    """
    naive = declared.replace(tzinfo=None)
    lat_min, lat_max, lon_min, lon_max = INDIA_BOUNDS
    if lat_min <= latitude <= lat_max and lon_min <= longitude <= lon_max:
        offset = IST_OFFSET
    else:
        # 15 degrees of longitude per hour. Crude, but it keeps the check
        # from being silently India-only if the corpus ever widens.
        offset = timedelta(hours=longitude / 15.0)
    return (naive - offset).replace(tzinfo=timezone.utc)


def solar_position(when_utc: datetime, latitude: float, longitude: float) -> Optional[tuple[float, float]]:
    """(azimuth, elevation) in degrees, or None if pysolar is unavailable."""
    try:
        from pysolar.solar import get_altitude, get_azimuth
    except ImportError:
        return None
    elevation = float(get_altitude(latitude, longitude, when_utc))
    azimuth = float(get_azimuth(latitude, longitude, when_utc)) % 360.0
    return azimuth, elevation


def bearing_to_compass(bearing: float) -> str:
    """Nearest of the eight compass points perception is allowed to report."""
    index = int((bearing % 360.0 + 22.5) // 45.0) % 8
    return COMPASS[index]


def compass_to_bearing(point: str) -> Optional[float]:
    try:
        return COMPASS.index(point.strip().upper()) * 45.0
    except (ValueError, AttributeError):
        return None


def angular_difference(a: float, b: float) -> float:
    """Smallest absolute angle between two bearings, in [0, 180]."""
    return abs((a - b + 180.0) % 360.0 - 180.0)


def expected_shadow_length(elevation: float) -> str:
    if elevation <= 0.0:
        return "none"
    if elevation >= ELEVATION_SHORT_ABOVE:
        return "short"
    if elevation >= ELEVATION_MEDIUM_ABOVE:
        return "medium"
    return "long"


# Only these three are *evidence* about length. "none" is deliberately
# absent: in PERCEPTION_PROMPT's vocabulary it means "no shadows visible
# in this image", not "shadows of zero length", and the prompt explicitly
# instructs the model to answer "none" rather than guess. Treating it as
# a measurement was a real bug caught on live data - a close-up of a
# dented door with no shadow in frame was scored as contradicting a
# midday sun, which is precisely the "honest I-can't-tell read as
# suspicion" failure this module's docstring forbids. Most claim
# photographs show no shadows, so that single mistake would have fired on
# the majority of honest claims.
_LENGTH_ORDER = {"short": 1, "medium": 2, "long": 3}


def shadow_length_gap(expected: str, observed: str) -> Optional[int]:
    """
    How many buckets apart two shadow-length answers are, or None if
    either carries no information. Adjacent buckets are not a
    contradiction - the boundary between "medium" and "long" is a
    judgement call even for a person - so only a gap of 2 or more counts.
    """
    if expected not in _LENGTH_ORDER or observed not in _LENGTH_ORDER:
        return None
    return abs(_LENGTH_ORDER[expected] - _LENGTH_ORDER[observed])


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------


def weather_cache_key(latitude: float, longitude: float, date: str) -> str:
    """
    Rounded to 2dp - about 1.1 km. Many cases in this corpus share a
    neighbourhood and a date, and the weather over Vadodara does not vary
    across a kilometre in a way this check can use. Rounding is what
    makes the cache actually hit.
    """
    return f"{latitude:.2f},{longitude:.2f}@{date}"


def fetch_weather(conn, latitude: float, longitude: float, date: str) -> Optional[dict[str, Any]]:
    """
    Daily precipitation and mean cloud cover for one place and date.

    Cached in the shared cache_entries table under namespace "weather".
    Returns None if the lookup fails - a weather API being down must
    leave this sub-check unavailable, never make it accuse someone.
    """
    key = weather_cache_key(latitude, longitude, date)
    if conn is not None:
        from .. import db

        hit = db.cache_get(conn, WEATHER_NAMESPACE, key)
        if hit is not None:
            return hit

    try:
        import requests

        response = requests.get(
            OPEN_METEO_URL,
            params={
                "latitude": round(latitude, 2),
                "longitude": round(longitude, 2),
                "start_date": date,
                "end_date": date,
                "daily": "precipitation_sum",
                "hourly": "cloudcover,precipitation",
                "timezone": "UTC",
            },
            timeout=WEATHER_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as e:  # noqa: BLE001 - offline, rate-limited, malformed; all mean "unavailable"
        return {"error": f"{type(e).__name__}: {e}"}

    daily = payload.get("daily") or {}
    precipitation = (daily.get("precipitation_sum") or [None])[0]
    hourly = payload.get("hourly") or {}
    clouds = [c for c in hourly.get("cloudcover", []) or [] if c is not None]
    # Hourly precipitation, keyed by UTC hour. This is what lets the
    # weather sub-check distinguish "it rained that day" from "it was
    # raining at the declared hour" - see _weather_subcheck for why that
    # distinction decides whether a dry photograph is evidence of
    # anything at all.
    hourly_precip: dict[int, float] = {}
    for stamp, mm in zip(hourly.get("time", []) or [], hourly.get("precipitation", []) or []):
        if mm is None:
            continue
        try:
            hourly_precip[int(stamp[11:13])] = float(mm)
        except (ValueError, IndexError):
            continue
    record = {
        "precipitation_mm": precipitation,
        "hourly_precipitation_mm": hourly_precip,
        "cloudcover_mean_pct": (sum(clouds) / len(clouds)) if clouds else None,
        "source": "open-meteo-archive",
        "date": date,
    }
    if conn is not None:
        from .. import db

        try:
            db.cache_set(conn, WEATHER_NAMESPACE, key, record)
        except Exception:  # noqa: BLE001 - sqlite lock, read-only db, disk full
            # The cache is an optimisation, not a requirement. A second
            # process holding the write lock (an evaluation running
            # alongside a test suite, say) must cost one redundant HTTP
            # call, not a failed check - and this path already returns a
            # perfectly good answer without it.
            pass
    return record


def _mentions(text: Optional[str], words: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(word in lowered for word in words)


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------


class SceneConsistencyCheck(Check):
    check_id = "scene_consistency"
    category = CheckCategory.CONTEXT
    scope = "image"
    cost_inr = 0.0
    requires_perception = True
    target_archetypes = ("CONTEXT_MISMATCH",)
    # 1.0 - the strongest evidence class in the battery when it fires.
    # A solar-geometry contradiction is arithmetic, not inference: the
    # sun's position at a given time and place is not a matter of
    # opinion, and the check abstains outright whenever the image cannot
    # support the calculation. Recorded as the designed weight; see
    # outputs/check_performance_v2.md for what perception coverage
    # actually allowed us to measure.
    weight = 1.0
    attributed_to = "image"

    def run(self, ctx: CheckContext) -> list[Finding]:
        case = ctx.case
        # No coordinates means no sun position and no weather history -
        # there is no question to ask, so no finding is emitted at all
        # rather than an INCONCLUSIVE that would sit in every report.
        if case.latitude is None or case.longitude is None or case.declared_time is None:
            return []

        perceived = [image for image in ctx.images if image.content_hash in ctx.perception]
        if not perceived:
            # Nothing to compare the world against. Returning early matters
            # for more than tidiness: fetch_weather() below calls a free
            # public API, and with perception covering a fraction of the
            # corpus, running it unconditionally would mean hundreds of
            # HTTP requests per pass whose answers nothing ever reads.
            # _run_one has already emitted the "perception not available"
            # INCONCLUSIVE for these images.
            return []

        when_utc = local_wallclock_to_utc(case.declared_time, case.latitude, case.longitude)
        solar = solar_position(when_utc, case.latitude, case.longitude)
        weather = fetch_weather(ctx.conn, case.latitude, case.longitude, when_utc.date().isoformat())

        return [self._check_one_image(ctx, image, when_utc, solar, weather) for image in perceived]

    # -- sub-checks --------------------------------------------------------

    def _shadow_subcheck(
        self, perception: PerceptionRecord, solar: Optional[tuple[float, float]], evidence: dict[str, Any]
    ) -> list[str]:
        """Returns a list of human-readable contradictions (possibly empty)."""
        if solar is None:
            evidence["shadow_status"] = "unavailable: pysolar not installed"
            return []

        azimuth, elevation = solar
        expected_bearing = (azimuth + 180.0) % 360.0
        expected_point = bearing_to_compass(expected_bearing)
        expected_length = expected_shadow_length(elevation)

        evidence.update(
            {
                "solar_azimuth_deg": round(azimuth, 2),
                "solar_elevation_deg": round(elevation, 2),
                "expected_shadow_bearing_deg": round(expected_bearing, 2),
                "expected_shadow_direction": expected_point,
                "expected_shadow_length": expected_length,
                "observed_shadow_direction": perception.shadow_direction,
                "observed_shadow_length": perception.shadow_length,
            }
        )

        contradictions: list[str] = []

        observed_bearing = compass_to_bearing(perception.shadow_direction or "")
        if observed_bearing is None:
            # "none_visible" and anything unparseable both land here, and
            # both mean the same thing: no evidence either way.
            evidence["shadow_direction_status"] = "not visible in image"
        elif elevation <= 0.0:
            evidence["shadow_direction_status"] = "sun below horizon; direction not meaningful"
        else:
            difference = angular_difference(expected_bearing, observed_bearing)
            evidence["shadow_bearing_difference_deg"] = round(difference, 1)
            if difference > SHADOW_BEARING_CONCERN_DEG:
                contradictions.append(
                    f"solar geometry puts shadows toward the {expected_point} "
                    f"({expected_bearing:.0f}°) but the image shows them toward the "
                    f"{perception.shadow_direction} ({difference:.0f}° away)"
                )
            else:
                evidence["shadow_direction_status"] = "consistent"

        observed_length = (perception.shadow_length or "").strip().lower()
        gap = shadow_length_gap(expected_length, observed_length)
        if gap is None:
            evidence["shadow_length_status"] = "not visible in image"
        elif gap >= 2:
            contradictions.append(
                f"the sun sits {elevation:.0f}° above the horizon, which casts {expected_length} "
                f"shadows, but the shadows in the image are {observed_length}"
            )
        else:
            evidence["shadow_length_status"] = "consistent"

        return contradictions

    def _weather_subcheck(
        self, perception: PerceptionRecord, weather: Optional[dict[str, Any]],
        evidence: dict[str, Any], declared_utc_hour: Optional[int] = None,
    ) -> list[str]:
        evidence["weather_api"] = weather
        if not weather or weather.get("error") or weather.get("precipitation_mm") is None:
            evidence["weather_status"] = "unavailable"
            return []

        precipitation = float(weather["precipitation_mm"])
        clouds = weather.get("cloudcover_mean_pct")
        observed = (perception.weather_observed or "unknown").strip().lower()
        road = perception.road_condition or ""
        evidence["observed_weather"] = observed
        evidence["observed_road_condition"] = road

        contradictions: list[str] = []

        image_says_wet = observed in {"rain", "wet_ground"} or _mentions(road, _WET_WORDS)
        image_says_clear = observed == "clear" and not _mentions(road, _WET_WORDS)

        # Both directions are now tested, but only against evidence that
        # can actually carry them - and that took an hourly lookup.
        #
        # This sub-check used to be deliberately one-directional. "Wet
        # image on a demonstrably dry day" fired; "clear image on a rainy
        # day" did not, because Open-Meteo's daily *total* cannot
        # establish that rain was falling at the declared minute. Monsoon
        # rain in Gujarat is intermittent, so 30 mm across a day is
        # entirely compatible with a dry, bright hour - and firing there
        # would have accused honest claimants of photographing their car
        # between showers.
        #
        # With hourly precipitation the objection disappears: "the
        # photograph shows dry ground and clear sky, and 4 mm of rain was
        # falling in the hour the incident is claimed to have happened" is
        # a real contradiction, not an inference from an aggregate.
        #
        # Note this made the check MORE precise in both directions, not
        # more aggressive. The wet-image direction now also requires the
        # declared *hour* to be dry, so a wet photograph on a day whose
        # rain fell entirely at 3 a.m. is no longer flagged either - a
        # false positive the daily-total version would have produced.
        hourly = (weather.get("hourly_precipitation_mm") or {}) if weather else {}
        hour_mm: Optional[float] = None
        if declared_utc_hour is not None and hourly:
            # JSON round-trips integer keys as strings.
            hour_mm = hourly.get(declared_utc_hour, hourly.get(str(declared_utc_hour)))
            if hour_mm is not None:
                hour_mm = float(hour_mm)
                evidence["declared_hour_precipitation_mm"] = round(hour_mm, 2)

        if image_says_wet and precipitation < DRY_MM:
            contradictions.append(
                f"the image shows {'rain' if observed == 'rain' else 'wet ground'} but no "
                f"precipitation was recorded at this location on this date ({precipitation:.1f} mm)"
            )
        elif image_says_wet and hour_mm is not None and hour_mm < DRY_MM and precipitation > RAIN_MM:
            # Rain that day, but not in the declared hour. Weaker than a
            # bone-dry day - ground stays wet for a while after rain
            # stops - so it is recorded rather than alleged.
            evidence["weather_status"] = "noted, not a contradiction"
            evidence["weather_note"] = (
                f"image shows wet ground and no rain fell in the declared hour, but "
                f"{precipitation:.1f} mm fell earlier that day; wet ground persists after rain, "
                "so this is not treated as a contradiction"
            )
        elif image_says_clear and hour_mm is not None and hour_mm > RAINY_HOUR_MM:
            contradictions.append(
                f"the image shows clear, dry conditions but {hour_mm:.1f} mm of rain was falling "
                f"at this location during the declared hour"
            )
        elif image_says_clear and hour_mm is None and precipitation > RAIN_MM:
            # No hourly data available - fall back to the old refusal
            # rather than guessing from the daily total.
            evidence["weather_status"] = "noted, not a contradiction"
            evidence["weather_note"] = (
                f"image reports clear and dry, while {precipitation:.1f} mm fell across the whole "
                "day; hourly precipitation was unavailable, and a daily total cannot establish "
                "that it was raining at the declared hour"
            )
        elif observed == "unknown":
            evidence["weather_status"] = "perception could not judge the weather"
        else:
            evidence["weather_status"] = "consistent"

        if clouds is not None:
            evidence["cloudcover_mean_pct"] = round(float(clouds), 1)
            if observed == "clear" and float(clouds) > OVERCAST_CLOUD_PCT and precipitation <= RAIN_MM:
                # Cloud cover alone is weaker evidence than rainfall - a
                # clear patch under a mostly-cloudy day is ordinary - so
                # this is recorded but not treated as a contradiction.
                evidence["cloudcover_note"] = (
                    f"image reports clear skies on a day averaging {float(clouds):.0f}% cloud; "
                    "noted but not treated as a contradiction"
                )

        return contradictions

    def _lighting_subcheck(
        self, perception: PerceptionRecord, solar: Optional[tuple[float, float]], evidence: dict[str, Any]
    ) -> list[str]:
        if solar is None:
            return []
        _, elevation = solar
        lighting = (perception.lighting or "unknown").strip().lower()
        evidence["observed_lighting"] = lighting

        if lighting in {"unknown", "artificial", "dusk"}:
            # "artificial" is not a contradiction at any hour - a lit
            # workshop looks the same at noon and midnight - and "dusk"
            # is exactly the ambiguous band.
            evidence["lighting_status"] = "not decisive"
            return []

        if lighting == "daylight" and elevation < CIVIL_TWILIGHT_DEG:
            return [
                f"the image was taken in daylight, but at the declared time the sun was "
                f"{abs(elevation):.0f}° below the horizon"
            ]
        if lighting == "night" and elevation > LIGHTING_NIGHT_CONFLICT_DEG:
            return [
                f"the image shows night, but at the declared time the sun was "
                f"{elevation:.0f}° above the horizon"
            ]

        evidence["lighting_status"] = "consistent"
        return []

    # -- per image ---------------------------------------------------------

    def _check_one_image(
        self,
        ctx: CheckContext,
        image: Image,
        when_utc: datetime,
        solar: Optional[tuple[float, float]],
        weather: Optional[dict[str, Any]],
    ) -> Finding:
        case = ctx.case
        perception = ctx.perception[image.content_hash]

        evidence: dict[str, Any] = {
            "image_id": image.image_id,
            "declared_local_time": case.declared_time.replace(tzinfo=None).isoformat(),
            "declared_utc_instant": when_utc.isoformat(),
            "latitude": case.latitude,
            "longitude": case.longitude,
            "declared_location": case.declared_location,
        }

        shadow_issues = self._shadow_subcheck(perception, solar, evidence)
        weather_issues = self._weather_subcheck(perception, weather, evidence, when_utc.hour)
        lighting_issues = self._lighting_subcheck(perception, solar, evidence)

        fired = {
            "solar_geometry": bool(shadow_issues),
            "weather": bool(weather_issues),
            "lighting": bool(lighting_issues),
        }
        evidence["subchecks_fired"] = [name for name, hit in fired.items() if hit]

        # Which sub-checks were able to reach a conclusion at all. If none
        # could, the honest answer is INCONCLUSIVE - see the module
        # docstring on why absence of evidence is never suspicion.
        decisive_statuses = (
            evidence.get("shadow_direction_status"),
            evidence.get("shadow_length_status"),
            evidence.get("weather_status"),
            evidence.get("lighting_status"),
        )
        any_conclusion = bool(shadow_issues or weather_issues or lighting_issues) or any(
            status == "consistent" for status in decisive_statuses
        )
        evidence["subchecks_conclusive"] = any_conclusion

        def finding(verdict: Verdict, confidence: float, explanation: str) -> Finding:
            return Finding(
                check_id=self.check_id,
                case_id=case.case_id,
                category=self.category,
                verdict=verdict,
                confidence=confidence,
                explanation=explanation,
                evidence=evidence,
            )

        contradictions = shadow_issues + weather_issues + lighting_issues
        if contradictions:
            # Confidence rises with how many independent sub-checks agree:
            # one physical contradiction is evidence, two pointing the
            # same way is much harder to explain away as a vision-model
            # misreading.
            confidence = min(0.9, 0.55 + 0.15 * (len(evidence["subchecks_fired"]) - 1))
            local = case.declared_time.replace(tzinfo=None).strftime("%H:%M on %d %b %Y")
            where = case.declared_location or f"{case.latitude:.3f}, {case.longitude:.3f}"
            joined = "; and ".join(contradictions)
            return finding(
                Verdict.CONCERN,
                confidence,
                f"The photograph contradicts the declared time and place "
                f"({local}, {where}): {joined}.",
            )

        if not any_conclusion:
            return finding(
                Verdict.INCONCLUSIVE,
                0.0,
                "No shadows, weather or lighting cues were legible in this image, so the declared "
                "time and place could not be tested - common for close-up damage photographs and "
                "not itself suspicious.",
            )

        checked = [name for name in ("solar_geometry", "weather", "lighting")]
        return finding(
            Verdict.PASS,
            min(0.8, 0.45 + 0.12 * sum(1 for s in decisive_statuses if s == "consistent")),
            "The photograph is consistent with the declared time and place: "
            + ", ".join(
                part
                for part in (
                    (
                        f"shadows fall as the sun's position requires"
                        if evidence.get("shadow_direction_status") == "consistent"
                        else None
                    ),
                    ("weather matches the recorded conditions" if evidence.get("weather_status") == "consistent" else None),
                    ("lighting matches the time of day" if evidence.get("lighting_status") == "consistent" else None),
                )
                if part
            )
            + ".",
        )


SCENE_CONSISTENCY_CHECK = register_check(SceneConsistencyCheck())
