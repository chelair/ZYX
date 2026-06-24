#!/usr/bin/env python3
import sys

path = sys.argv[1]  # POSCAR path from command line
lines = open(path).readlines()

# find coordinate start
for i, line in enumerate(lines):
    s = line.strip()
    if s == 'Direct' or s == 'DIRECT':
        start = i + 1
        break

# collect all z coordinates
zs = []
for line in lines[start:]:
    parts = line.split()
    if len(parts) < 6:
        break
    try:
        zs.append(float(parts[2]))
    except ValueError:
        break

zmin = min(zs)
zmax = max(zs)
th = zmin + 0.40 * (zmax - zmin)

# rewrite coordinate lines
for i in range(start, start + len(zs)):
    parts = lines[i].split()
    z = float(parts[2])
    tag = 'F F F' if z <= th else 'T T T'
    lines[i] = '  '.join(parts[:3]) + '  ' + tag + '\n'

open(path, 'w').writelines(lines)
print(f"OK: {sum(1 for l in lines[start:start+len(zs)] if 'F F F' in l)} fixed, {sum(1 for l in lines[start:start+len(zs)] if 'T T T' in l)} free")