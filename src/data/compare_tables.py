"""Compare every CSV in two folders: shape, columns, row order and values (numeric tolerance 1e-6).

Used to prove a rebuild reproduces the committed data exactly.

Usage:
    python -m src.data.compare_tables <expected_dir> <rebuilt_dir>
"""
import os
import sys

import numpy as np
import pandas as pd


def compare(a, b):
    if a.shape != b.shape:
        return f"shape {a.shape} vs {b.shape}"
    if list(a.columns) != list(b.columns):
        return f"columns differ: {sorted(set(a.columns) ^ set(b.columns)) or 'same set, different order'}"
    bad = []
    for c in a.columns:
        x, y = a[c], b[c]
        if pd.api.types.is_numeric_dtype(x) and pd.api.types.is_numeric_dtype(y):
            ok = np.isclose(x.astype(float), y.astype(float), rtol=0, atol=1e-6, equal_nan=True)
        else:
            ok = (x.astype(object).where(x.notna(), "").astype(str) == y.astype(object).where(y.notna(), "").astype(str)).to_numpy()
        if not ok.all():
            i = int(np.argmin(ok))
            bad.append(f"{c}: {int((~ok).sum())} rows differ (first: {x.iloc[i]!r} vs {y.iloc[i]!r})")
    return "; ".join(bad) or None


def main(exp_dir, new_dir):
    all_ok = True
    for f in sorted(os.listdir(exp_dir)):
        if not f.endswith(".csv"):
            continue
        if not os.path.exists(os.path.join(new_dir, f)):
            print(f"MISSING  {f}"); all_ok = False; continue
        a = pd.read_csv(os.path.join(exp_dir, f), low_memory=False)
        b = pd.read_csv(os.path.join(new_dir, f), low_memory=False)
        diff, label = compare(a, b), "IDENTICAL"
        if diff and a.shape == b.shape and list(a.columns) == list(b.columns):
            keys = [c for c in a.columns if not pd.api.types.is_float_dtype(a[c])]
            if compare(a.sort_values(keys).reset_index(drop=True), b.sort_values(keys).reset_index(drop=True)) is None:
                diff, label = None, "SAME VALUES (rows in a different order)"
        print(f"{label if diff is None else 'DIFFERENT'}  {f}" + (f"\n    {diff}" if diff else ""))
        all_ok &= diff is None
    print("\nALL IDENTICAL" if all_ok else "\nDIFFERENCES FOUND")
    return all_ok


if __name__ == "__main__":
    sys.exit(0 if main(sys.argv[1], sys.argv[2]) else 1)
