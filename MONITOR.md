# Status Detection

## Decision Flow

```
bjobs has RUN? -> Run
bjobs has PEND? -> PEND
No:
  OUTCAR has General timing?
    Yes + accuracy -> Completed
    Yes + no accuracy -> Failed
    Yes + I REFUSE -> Error
  No timing + OUTCAR exists -> Stop
  No OUTCAR -> Pending
```

## Continuation Dir Handling

```
Subdir has con/ con1/ con2/ fix/:
  Only use con* dirs (ignore fix/)
  Take deepest: con4 > con3 > con2 > con1 > con
  Status from latest con* OUTCAR
```

## Status Table

| Status | Meaning | Action |
|:------:|---------|--------|
| Run | Job running | Always render structure |
| PEND | Queued | Wait |
| Completed | Converged | Can do static/DOS |
| Failed | Finished, not converged | Check params |
| Error | Fatal error | Manual intervention |
| Stop | Walltime killed | Can continue |
| Pending | Never submitted | Ready |

## Data Pre-scan (efficient)

```
1. Generate temp data file: find OUTCAR -> grep accuracy/timing/energy
2. cat data locally
3. Match to subtasks -> update JSON + job.info
```

---

# Queue Selection

Check bhosts per-node before submitting. Don't rely on bqueues PEND counts alone.

## Three Steps

```
1. bhosts -> find >=2 nodes with >=24 free cores each (P0 - must fit)
2. bqueues -> among fitting queues, pick lowest PEND (P1 - fast start)
3. Submit directly, auto-queue, ignore quotas
```

## Priority

| Condition | Priority |
|-----------|:--------:|
| bhosts: nodes available | P0 |
| bqueues: lowest PEND | P1 |
| Suspend risk (STOPCAR covers) | P2 |
| Free (not charge) | P3 |
