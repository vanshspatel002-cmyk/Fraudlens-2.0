"""Verify the full environment. Every line should print OK."""
import sys

def check(name, fn):
    try:
        fn()
        print(f"  OK    {name}")
        return True
    except Exception as e:
        print(f"  FAIL  {name}  ->  {type(e).__name__}: {e}")
        return False

print("\n--- Python ---")
v = sys.version_info
ok = v.major == 3 and v.minor in (11, 12)
print(f"  {'OK  ' if ok else 'WARN'}  Python {v.major}.{v.minor}.{v.micro}"
      f"{'' if ok else '  <-- expected 3.11 or 3.12'}")

r = []

print("\n--- Core libraries ---")
for name in ["torch", "open_clip", "imagehash", "PIL", "cv2", "easyocr",
             "piexif", "transformers", "pysolar", "fastapi", "streamlit",
             "pandas", "sklearn"]:
    r.append(check(name, lambda n=name: __import__(n)))

print("\n--- ExifTool ---")
def _exiftool():
    import subprocess
    subprocess.run(["exiftool", "-ver"], capture_output=True, check=True)
r.append(check("exiftool", _exiftool))

print("\n--- API key ---")
def _key():
    import os
    from dotenv import load_dotenv
    load_dotenv()
    assert os.getenv("GEMINI_API_KEY"), "GEMINI_API_KEY missing from .env"
r.append(check("GEMINI_API_KEY in .env", _key))

# gemini-2.0-flash and gemini-2.5-flash are closed to new free-tier keys
# (429 with limit: 0, and 404 "no longer available to new users").
GEMINI_MODEL = "gemini-3.5-flash"

print("\n--- Free APIs (no key needed) ---")
def _openmeteo():
    import requests
    resp = requests.get(
        "https://archive-api.open-meteo.com/v1/archive",
        params={"latitude": 22.31, "longitude": 73.18,
                "start_date": "2025-07-15", "end_date": "2025-07-15",
                "daily": "precipitation_sum"}, timeout=20)
    resp.raise_for_status()
    assert "daily" in resp.json()
r.append(check("Open-Meteo (Vadodara)", _openmeteo))

def _solar():
    from pysolar.solar import get_altitude, get_azimuth
    from datetime import datetime, timezone
    dt = datetime(2025, 7, 15, 12, 0, tzinfo=timezone.utc)
    get_altitude(22.31, 73.18, dt); get_azimuth(22.31, 73.18, dt)
r.append(check("pysolar computation", _solar))

print("\n--- Gemini live call ---")
def _gemini():
    import os, google.generativeai as genai
    from dotenv import load_dotenv
    load_dotenv()
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    m = genai.GenerativeModel(os.getenv("GEMINI_MODEL", GEMINI_MODEL))
    assert m.generate_content("Reply with one word: ready").text
r.append(check(f"Gemini API responds ({GEMINI_MODEL})", _gemini))

print("\n--- Dataset ---")
def _data():
    from pathlib import Path
    imgs = [p for p in Path("data/raw").rglob("*")
            if p.suffix.lower() in {".jpg", ".jpeg", ".png"}]
    assert len(imgs) > 0, "no images found in data/raw"
    print(f"        found {len(imgs)} images")
r.append(check("images in data/raw", _data))

print("\n" + "=" * 50)
print(f"  {sum(r)} / {len(r)} checks passed")
print("  ENVIRONMENT READY" if sum(r) == len(r) else "  Fix the FAILs above")
print("=" * 50)

