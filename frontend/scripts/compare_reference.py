"""Deterministic comparison only: never resize, retouch, or overwrite captures.

Usage: python scripts/compare_reference.py --reference <png> --actual <png/jpg> --out <new-directory>
Needs Pillow + numpy in the existing vision-skill environment. No network.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
from PIL import Image, ImageChops


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', required=True, type=Path)
    parser.add_argument('--actual', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--focus', help='Optional JSON map of names to native pixel rectangles; never changes source size or masks differences')
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit('Refusing to overwrite an existing comparison directory')
    reference = Image.open(args.reference).convert('RGB')
    actual = Image.open(args.actual).convert('RGB')
    if reference.size != actual.size:
        raise SystemExit(f'Pixel dimensions differ: {reference.size} vs {actual.size}; no resizing allowed')
    args.out.mkdir(parents=True)
    shutil.copy2(args.reference, args.out / 'reference-original.png')
    width, height = reference.size
    pair = Image.new('RGB', (width * 2, height), '#ffffff')
    pair.paste(reference, (0, 0)); pair.paste(actual, (width, 0))
    pair.save(args.out / 'side-by-side.png')
    Image.blend(reference, actual, .5).save(args.out / 'overlay-50.png')
    difference = ImageChops.difference(reference, actual)
    difference.point(lambda value: min(255, value * 4)).save(args.out / 'diff.png')
    regions = {'topbar': (0, 0, width, 210), 'canvas': (829, 210, 1499, 972), 'scene': (202, 210, 817, 972)}
    if args.focus:
        regions = json.loads(args.focus)
        for name, box in regions.items():
            if len(box) != 4 or not (0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height):
                raise SystemExit(f'Invalid focus rectangle: {name}: {box}')
    metrics = {}
    for name, box in {'whole': (0, 0, width, height), **regions}.items():
        left = reference.crop(box); right = actual.crop(box)
        delta = np.abs(np.asarray(left).astype(np.int16) - np.asarray(right).astype(np.int16))
        metrics[name] = {'mean_absolute_channel_difference': float(delta.mean()), 'changed_fraction_at_channel_tolerance_12': float(np.any(delta > 12, axis=2).mean())}
        if name != 'whole':
            focused = Image.new('RGB', (left.width * 2, left.height), '#ffffff')
            focused.paste(left, (0, 0)); focused.paste(right, (left.width, 0))
            focused.save(args.out / f'focused-{name}.png')
    report = {'reference': str(args.reference.resolve()), 'actual': str(args.actual.resolve()), 'pixelSize': [width, height], 'referenceSha256': hashlib.sha256(args.reference.read_bytes()).hexdigest(), 'actualSha256': hashlib.sha256(args.actual.read_bytes()).hexdigest(), 'resized': False, 'masked': False, 'purpose': 'difference localization only; not an acceptance score', 'metrics': metrics}
    (args.out / 'metrics.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
