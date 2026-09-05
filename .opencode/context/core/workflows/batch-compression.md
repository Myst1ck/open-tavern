# Per-Task Compression Rule (Permanent)

## Rule: Compress After Every Task

AFTER each individual task completes (not batch):

1. Task result received → immediately call `compress` on that task's delegation+result
2. Only then dispatch next task (sequential or next in batch)
3. Batch completion = all tasks done + all individually compressed

## Why

`task` = 93.9% of context usage (~16K avg per task). 4 parallel tasks accumulate 64K+
before batch-level compression. Per-task keeps peak at ~16K.

## What to Compress

- Single task: delegation prompt + subagent result
- Error/retry noise from that task

## Exceptions

- Active task (in progress): never compress
- User messages with pending questions: keep uncompressed
- Last task in session (may want raw output): skip if user likely needs detail