# EDM-Takens Skill — Troubleshooting

This document records environment-specific failure modes and their verified
remedies, so that users in similar predicaments can apply them without
re-discovering the fix.

## 1. `ccm_causality.py` self-test times out or fails with memory errors

### Symptom

Running `python run_tests.py --quick` fails at **Layer 7** with one of the
following:

```text
[XX] ccm_causality.py: self-test timed out (>120s)
```

or, in the subprocess logs:

```text
MemoryError
DLL load failed while importing ...: 页面文件太小，无法完成操作。
OpenBLAS error: Memory allocation still failed after 10 retries, giving up.
```

### Root cause

The `ccm_causality.py` self-test exercises the full Convergent Cross Mapping
(CCM) pipeline on a multi-variable fixture. On Windows, pyEDM's CCM path spawns
fresh interpreter processes; each process must reload `numpy`, `scipy`, and
`pandas`. With 16 GB of physical RAM and a small/default page file, the combined
memory demand of these simultaneous loads can exceed available virtual memory,
causing allocation failures or extreme slowdown (thrashing).

### Verified remedy

Increase the Windows page file (virtual memory) to give the system enough headroom:

1. Open **System Properties** (`Win + R` → `sysdm.cpl`).
2. Go to **Advanced** → **Performance** → **Settings** → **Advanced** →
   **Virtual memory** → **Change**.
3. Uncheck **"Automatically manage paging file size for all drives"**.
4. Select a drive with ample free space (preferably an SSD, and preferably not
the system drive):
   - **Initial size**: `16384` MB (16 GB)
   - **Maximum size**: `16384` MB (16 GB)
5. Click **Set**, then **OK**, and **restart** the computer.

After restart, the self-test should complete successfully. On the reference
machine (16 GB RAM, page file moved to a secondary SSD), `python run_tests.py --quick`
completes in approximately **3.5 minutes** with **89/89 tests passed**.

### Companion adjustment

Because the CCM self-test is computationally heavy on resource-constrained
machines, `run_tests.py` Layer 7 timeout was raised from **120 s** to **300 s**
so that the test is not prematurely killed once the memory bottleneck is
removed.

### What virtual memory is (and isn't)

- **Physical RAM** is fast, volatile memory that the CPU uses directly.
- The **page file** is disk space that Windows uses as overflow when RAM is
  full.
- A larger page file prevents out-of-memory crashes, but it is much slower than
  RAM. If the workload constantly pages to disk, performance will degrade
  (thrashing). For this Skill, the page file is used mainly to accommodate the
  large import footprints of pyEDM/numpy/scipy subprocesses, not for sustained
  numerical computation, so the impact is acceptable.

## 2. General portability checklist

If tests fail on a fresh machine, verify:

- Python 3.10+ is installed.
- Required packages are installed: `pip install -r requirements.txt`.
- `pyEDM` is optional; if missing, the pure-numpy fallback is used.
- The working directory is the Skill root (`edm-takens/`) when invoking
  `run_pipeline.py` or `run_tests.py`.
- No absolute paths are hardcoded: all data paths resolve through `src/_paths.py`.
