"""Measure real local OCR before/after CPU thread bounding; never calls a provider.

Run once into a new output file. This records execution, not plate accuracy.
"""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--image', type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Use a new output file; preserve earlier measurements.')
    started = time.monotonic()
    import torch
    import easyocr
    import os
    from src.timing import windows_memory
    image = args.image or sorted((ROOT / 'data/curated/whole').glob('*.jpg'))[1]
    result = {'image_sha256': __import__('hashlib').sha256(image.read_bytes()).hexdigest(),
              'provider_requests': 0, 'import_seconds': time.monotonic() - started,
              'logical_cpus': os.cpu_count(), **windows_memory(),
              'measurements': []}
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')

    def measure(label, operation):
        before = time.process_time()
        started = time.monotonic()
        value = operation()
        row = {'stage': label, 'seconds': round(time.monotonic()-started, 3),
               'threads': torch.get_num_threads(), **windows_memory(),
               'cpu_seconds': round(time.process_time()-before, 3)}
        result['measurements'].append(row)
        print(json.dumps(row), flush=True)
        save()
        return value

    reader = measure('reader_initialization_default_threads', lambda: easyocr.Reader(['en'], gpu=False, download_enabled=False))
    original = measure('readtext_default_threads', lambda: reader.readtext(str(image)))
    torch.set_num_threads(2)
    bounded = measure('readtext_two_threads', lambda: reader.readtext(str(image)))
    result['raw_observations_equal'] = [(text, float(conf)) for _,text,conf in original] == [(text, float(conf)) for _,text,conf in bounded]
    result['observation_counts'] = [len(original), len(bounded)]
    save()


if __name__ == '__main__':
    main()
