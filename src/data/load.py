"""Load a model-ready table as (X, y, meta) - the single entry point for model training.

Example:
    from src.data.load import load_task
    X, y, meta = load_task("runoff", feature_set="live")
    train = meta.split.isin(["train", "val"]); test = meta.split == "test"
    model.fit(X[train], y[train]); model.score(X[test], y[test])

    # unseen-block cross-validation
    for k in range(5):
        tr, te = meta.cv_fold != k, meta.cv_fold == k
"""
import json
import os

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODEL_READY = os.path.join(ROOT, "data", "model_ready")


def load_spec(path=MODEL_READY):
    with open(os.path.join(path, "feature_spec.json"), encoding="utf-8") as f:
        return json.load(f)


def load_task(task, feature_set=None, path=MODEL_READY):
    """task: 'yield' or 'runoff'. feature_set: 'live' (default; known at decision time) or 'hindsight' (upper bound)."""
    spec = load_spec(path)[task]
    feature_set = feature_set or "live"
    if feature_set not in spec["feature_sets"]:
        raise ValueError(f"{task} has feature sets {list(spec['feature_sets'])}, not {feature_set!r}")
    df = pd.read_csv(os.path.join(path, f"{task}_model_ready.csv"))
    feats = spec["feature_sets"][feature_set]
    return df[feats].astype(float), df[spec["target"]], df[spec["meta_columns"]]


def monotone_constraints(task, columns, path=MODEL_READY):
    """Per-column monotone constraint list (+1 / 0) in the order of `columns`, for XGBoost/LightGBM."""
    mc = load_spec(path)[task]["monotone_constraints"]
    return [int(mc.get(c, 0)) for c in columns]
