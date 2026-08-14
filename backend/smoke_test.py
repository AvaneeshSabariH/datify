"""
Quick smoke test for DockerSandbox / LocalSubprocessSandbox.
Run from the repo root: py -3.12 backend/smoke_test.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.profiler import generate_mock_dataset
from backend.sandbox import get_sandbox

CSV_PATH = os.path.join(os.path.dirname(__file__), "_test_mock.csv")

# ── Setup ──────────────────────────────────────────────────────────────────────
print("Generating mock CSV ...")
generate_mock_dataset(CSV_PATH, num_rows=1000)
print(f"  -> {CSV_PATH}")

sb = get_sandbox()
print(f"\nSandbox type: {type(sb).__name__}\n{'='*50}")

PASS = "[PASS]"
FAIL = "[FAIL]"

# ── Test 1: valid code — df.shape ──────────────────────────────────────────────
r = sb.run("print(df.shape)", CSV_PATH)
ok = r["success"] and "(1000, 9)" in r["stdout"]
print(f"Test 1 (df.shape)    : {PASS if ok else FAIL}")
print(f"  stdout : {r['stdout'].strip()!r}")
if not ok:
    print(f"  stderr : {r['stderr'][:200]!r}")

# ── Test 2: valid code — numeric aggregation ───────────────────────────────────
code2 = 'col = "Total Sales ($)"\nprint(round(df[col].dropna().mean(), 2))'
r2 = sb.run(code2, CSV_PATH)
ok2 = r2["success"] and r2["stdout"].strip()
print(f"\nTest 2 (mean sales)  : {PASS if ok2 else FAIL}")
print(f"  stdout : {r2['stdout'].strip()!r}")
if not ok2:
    print(f"  stderr : {r2['stderr'][:200]!r}")

# ── Test 3: broken code — error capture ───────────────────────────────────────
r3 = sb.run('df["nonexistent_col"].sum()', CSV_PATH)
ok3 = not r3["success"] and r3["stderr"].strip()
print(f"\nTest 3 (bad code)    : {PASS if ok3 else FAIL}")
print(f"  success: {r3['success']}")
print(f"  stderr snippet: {r3['stderr'][:150].strip()!r}")

# ── Test 4: timeout ────────────────────────────────────────────────────────────
r4 = sb.run("import time; time.sleep(15)", CSV_PATH)
ok4 = not r4["success"] and "timed out" in r4["stderr"].lower()
print(f"\nTest 4 (timeout)     : {PASS if ok4 else FAIL}")
print(f"  success: {r4['success']}")
print(f"  stderr : {r4['stderr'][:120].strip()!r}")

# ── Cleanup ────────────────────────────────────────────────────────────────────
os.remove(CSV_PATH)
print(f"\n{'='*50}")
all_pass = all([ok, ok2, ok3, ok4])
print(f"Result: {'ALL TESTS PASSED' if all_pass else 'SOME TESTS FAILED'}")
sys.exit(0 if all_pass else 1)
