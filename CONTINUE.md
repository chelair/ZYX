# Job Continuation

Create conN/ to continue walltime-killed jobs.

## Trigger

| Condition | Action |
|-----------|:------:|
| OUTCAR + not converged + job finished | Continue OK |
| OUTCAR + converged | No need |
| Energy divergence | Diagnose first |
| No CONTCAR or empty | Cannot continue |
| Broken CONTCAR (walltime truncation) | Fallback needed |

## Two-Step Flow

### Step 1: Generate Files (--dry-run)

```
1. Find current work dir (base or latest conN)
2. CONTCAR integrity check
3. N = max(con1,con2,...) + 1
4. mkdir {sub_dir}/con{N}/          (no -p)
5. Write job.info (status=pending), sync JSON -> Pending
6. cp -n  CONTCAR  -> con{N}/POSCAR
   cp -n  INCAR    -> con{N}/INCAR
   cp -n  KPOINTS  -> con{N}/KPOINTS
   cp -n  POTCAR   -> con{N}/POTCAR
   mv     WAVECAR -> con{N}/WAVECAR  (only if OUTCAR has finish flag)
   cp -n  submit script -> con{N}/
7. Modify INCAR: ISTART=1, ICHARG=0, add DIPOL (adsorption), adjust fix ratio
8. Node check + queue selection
9. Generate vasp.lsf, JobName: {project}_{subdir_last}
10. Output preview, wait for confirm
```

### Step 2: Confirm Submit

```
11. bsub < con{N}/vasp.lsf
12. Fill job_id -> job.info (status=submitted)
13. Sync JSON: status -> Run, record job_id
```

## CONTCAR Integrity

```
1. Read POSCAR/CONTCAR line counts via SSH
2. Calculate expected coordinate lines
3. Check CONTCAR tail is complete
4. If broken -> fallback:
   A: Extract from OUTCAR (grep TOTAL-FORCE)
   B: Extract from XDATCAR
   C: Manual fix
```

## Directory Structure

```
{project_path}/{sub_dir}/
                    +-- con1/  (1st continue, inside original)
                    +-- con2/  (2nd, sibling of con1)
                    +-- con3/
```

## Scenarios

| Scene | Operation | INCAR Change |
|-------|-----------|-------------|
| IBRION=2 walltime | CONTCAR -> POSCAR | ISTART=1, keep IBRION=2 |
| IBRION=1 stuck | CONTCAR -> POSCAR | IBRION=2 |
| NEB walltime | CONTCAR -> POSCAR | ISTART=1, keep IBRION=3 |
| SCF failed | Don't continue | ALGO=All, NELM, AMIX |
| MD walltime | CONTCAR -> POSCAR | ISTART=1, keep IBRION=0 |
| Higher precision | CONTCAR -> POSCAR | Lower EDIFF/EDIFFG |

## Core Estimation

| Type | Condition | Cores |
|------|-----------|:-----:|
| Relax | atoms < 100 | 24 |
| | 100-150 | 24-36 |
| | > 150 | 48 |
| | DFT+U / rare-earth | add more |
| Static | default | 24 |
| | ISYM=-1/0 or LREAL=F | >= 36 |
| HSE | per 24core*24h ~ 10 elec steps | |
| NEB | >= 48, cores/IMAGES=integer | |

## Submit Script (vasp.lsf)

Template: submit/vasp.lsf
- Default 48 cores, 2 nodes x 24
- STOPCAR graceful exit: LSF sends SIGURG 50s before walltime -> write STOPCAR -> VASP stops gracefully
- JobName: {project}_{subdir_last} (underscore only)
