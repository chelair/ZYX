# VASPKit 用法

路径: /data/gpfs03/mdye/vaspkit.1.3.5/bin/vaspkit

## 402 - Fix Selected Atoms

Fix bottom layers in slab, leave top + adsorbates free.

```
vaspkit -> 4 (Structure Editor)
        -> 402 (Fix Selected Atoms)
          -> 1 (POSCAR) / 2 (CONTCAR)
            -> Enter (default filename)
              -> 3 (Fix by Heights) or 1 (Fix by Atomic Indices)
```

### Scene Rules

> Judge by job.info / JSON subtask name, NOT POSCAR content.

| Scene | Method | Ratio | JSON Keywords |
|-------|--------|:-----:|---------------|
| slab opt | 3) Fix by Heights | 40% | opt, raw |
| adsorption | 3) Fix by Heights | 50% | abs, OER |
| frequency | 1) Fix by Indices | all except adsorbate | freq |

### Fix by Heights

```
vaspkit -> 4 -> 402 -> 1 -> Enter -> 3
  -> z_min z_max    (Fractional, e.g. "0 0.225")
  -> 1              (Fractional coords)
  -> all            (3-direction fix, NOT "3")
  -> mv POSCAR_FIX POSCAR
```

### Fix by Indices

```
vaspkit -> 4 -> 402 -> 1 -> Enter -> 1
  -> input substrate atom indices (e.g. "1-123")
  -> ask user if can't distinguish substrate vs adsorbate
```

### Fix Formula

```
z_range = z_max - z_min (Direct)
threshold = z_min + ratio * (z_max - z_min)
fix: z <= threshold -> F F F
free: z > threshold -> T T T
```

## DIPOL Correction (Adsorption Only)

For adsorption with asymmetric slab:

```
z_center = (z_min + z_max) / 2  (keep 2 decimals)
DIPOL = 0.5 0.5 {z_center}

INCAR:
  LDIPOL = .TRUE.
  IDIPOL = 3
  DIPOL  = 0.5 0.5 {z_center}

Example: z_min=0.00, z_max=0.45 -> z_center=0.23
```

## INCAR Rules

- No Chinese comments
- Format: KEY = value

## POTCAR

Run `pos2pot` in directory with POSCAR.

## KPOINTS

```
auto kppoints
0
G
N1 N2 N3
0 0 0
```

Rule: Ni * ai > 20 (k-mesh * lattice constant > 20 Angstrom)
