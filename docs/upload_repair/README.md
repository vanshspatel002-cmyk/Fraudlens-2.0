# Upload validation verification — 23 October 2026

Policy **initial-photo-admission-2026-10-23-v4**. No Gemini calls; this verifies
image admission, not live case analysis or recognition accuracy in general.

| Verification | Actual result |
|---|---|
| Running v3 reproduction | 6/6 exterior accepts; the same pictures withheld in all 12 damage-slot tests (10 rejected, 2 uncertain) |
| Native v4 positives | 55/55 positive image/slot cases accepted, including undamaged cars, damaged parts, car-door detail, mounted-plate crop, off dashboard and EXIF-rotated photo |
| Held-out corpus | Six further cars passed all three overview/damage slots; separate from the six reproduction photos |
| Native unrelated negatives | 70/70 withheld: 68 rejected, 2 uncertain/retake (grass in the damage slots); seven packaged negatives across all ten slots |
| Authored severe blur | Rejected before classification |
| Authored printed-car page | **False acceptance remains**: 0.2562 positive vs 0.2335 competitor; margin 0.0227 exceeds 0.020. Not marked passed. |
| Native API acceptance | Claims 4/4 and underwriting 6/6; disposable SQLite, actual native gate, durable owner/job, UUID4 receipt replay, zero additional final embedding calls |
| Actual Chrome upload UI | 21/21 accepted: all ten slots at desktop and mobile widths, plus a portrait car-part crop; real API, no request interception, no business submission |
| Controlled UI edge cases | Both types at 1365/390 px: unavailable/recheck, final 503, corrupt-file 422, replacement, removal, stale rejection/acceptance, duplicate and exact-count behavior |
| Backend regressions | 70 passed, 341.30 seconds; controlled classifier/isolated databases, external model transport blocked |
| Typecheck / production build | Exit 0 / 0; 140.527 / 203.145 seconds |

The initial native harness used an incorrect expected registration status and then
a non-UUID receipt key. Those were harness defects, corrected before the successful
isolated submission result. The oversized-input test initially produced a Windows
environment-variable error from its enormous generated test ID; explicit short IDs
fixed it, followed by the successful complete regression rerun. No application
failure or mocked result is counted as native recognition success.

## Receipts and screenshots

- [Before repair, actual authenticated server responses](before-results.json)
- [Native local CLIP results and isolated submissions](native-results.json)
- [Actual Chrome/server upload responses](native-browser.json)
- [Controlled browser results](controlled-browser.json)
- [Backend checks](backend-checks.json), [frontend checks](frontend-checks.json)
- [Running services, unchanged controls and data preservation](operational-state.json)
- Native Claims: [desktop](native-claims-1365.png), [mobile](native-claims-390.png)
- Native Underwriting: [desktop](native-underwriting-1365.png), [mobile](native-underwriting-390.png)
- Controlled outage Claims: [desktop](controlled-claims-outage-1365.png), [mobile](controlled-claims-outage-390.png)
- Controlled outage Underwriting: [desktop](controlled-underwriting-outage-1365.png), [mobile](controlled-underwriting-outage-390.png)
- [Repair explanation, files and repeatable commands](../UPLOAD_VALIDATION_REPAIR.md)

Recognition runs memoize actual CLIP embeddings of the same normalized bytes
across slots; no scores are simulated. API/UI edge-case fixtures are separate and
their screenshots are explicitly labelled. Final acceptance is from the real gate
with a disposable database and stopped worker, not from live Gemini processing.

## Evidence and limitations

Licensed archived Chevrolet photographs: **Milkmandan~commonswiki**, Chevrolet
Classic series, Wikimedia Commons, **CC BY-SA 3.0**. Screenshots include resized
photographs and a real mounted-plate crop. The crop uses 34–72% of image width and
62–99% of height from `chevrolet-classic-rear.jpg`, with surrounding bumper.
[Original files, attribution/source/license and limitations](../presentation_assets/README.md).
The plate is from a rear photograph even when the applicant slot says front;
independent view/identity verification is deliberately not claimed. Dashboard power
is off; readable mileage remains unverified. These are archived pictures, not a
current-condition or insured-loss demonstration.

Corpus whole_0001–0012 and the first four damaged photographs are existing local
recognition fixtures, not an invented same-vehicle set; their originals are not
republished here. The additional portrait crop is from damaged_0002. The packaged
negatives are person, animal, food, grass, motorcycle, scanned page and coins.
The small sample does not establish general accuracy, authenticity or heavy-truck
rejection. A printed page dominated by a car photo can still pass. This limitation
is explicitly retained rather than claiming every document/screenshot is detected.

Original cases, stored evidence, reports, human decisions and provider controls
are preserved. No historical reprocessing, provider recovery or deployment.
