"""Full model comparison for the yield and runoff surrogates (live, decision-time features).

Protocol, identical for every model (no peeking at the test year):
  1. Each model has a small set of candidate settings. Fit each on train (2021-2023); boosting models
     early-stop on val (2024). Choose the setting by val R2 only.
  2. Refit the chosen setting on train+val (fixed number of iterations) and score test (2025) once.
  3. Hardest realistic score: unseen blocks AND future year (train on the other folds' 2021-2023 rows,
     predict the held-out fold's 2025 rows), mean ± sd over 5 folds.
  4. Speed: milliseconds to predict 10,000 rows (NSGA-II calls the model thousands of times).
Runoff models use the monotone rain constraints where the library supports them.
The best model per task (by val R2) is saved, refit on train+val, to artifacts/models/.

Usage:
    python -m src.models.compare_models
"""
import json
import os
import time
import warnings

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import xgboost as xgb
from catboost import CatBoostRegressor
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from src.data.load import load_spec, load_task, monotone_constraints

warnings.filterwarnings("ignore")
SEED = 0
OUT_MODELS, OUT_REPORTS = "artifacts/models", "artifacts/reports"


# ---------- model factories: (params, n_iter, mono) -> estimator; supports_es = early stopping on val ----------
def ridge(p, n, mono):
    return make_pipeline(StandardScaler(), Ridge(alpha=p["alpha"]))


def rf(p, n, mono):
    return RandomForestRegressor(n_estimators=400, min_samples_leaf=p["leaf"], max_features=p["mf"], n_jobs=-1, random_state=SEED)


def hgb(p, n, mono):
    return HistGradientBoostingRegressor(learning_rate=0.05, max_iter=n or 2000, max_leaf_nodes=p["leaves"],
                                         min_samples_leaf=p["leaf"], l2_regularization=p["l2"],
                                         monotonic_cst=mono, random_state=SEED, early_stopping=False)


def xgbm(p, n, mono):
    kw = dict(learning_rate=0.03, n_estimators=n or 3000, max_depth=p["depth"], min_child_weight=p["mcw"],
              reg_lambda=p["l2"], gamma=p.get("gamma", 0), subsample=0.7, colsample_bytree=0.6, random_state=SEED, n_jobs=-1)
    if n is None:
        kw["early_stopping_rounds"] = 100
    if mono:
        kw["monotone_constraints"] = "(" + ",".join(map(str, mono)) + ")"
    return xgb.XGBRegressor(**kw)


def lgbm(p, n, mono):
    kw = dict(learning_rate=0.03, n_estimators=n or 3000, num_leaves=p["leaves"], min_child_samples=p["leaf"],
              reg_lambda=p["l2"], subsample=0.7, subsample_freq=1, colsample_bytree=0.6, random_state=SEED, verbose=-1)
    if mono:
        kw["monotone_constraints"] = mono
    return lgb.LGBMRegressor(**kw)


def cat(p, n, mono):
    kw = dict(learning_rate=0.03, iterations=n or 3000, depth=p["depth"], l2_leaf_reg=p["l2"], random_seed=SEED,
              verbose=False, allow_writing_files=False, thread_count=-1)
    if n is None:
        kw["od_type"], kw["od_wait"] = "Iter", 100
    if mono:
        kw["monotone_constraints"] = mono
    return CatBoostRegressor(**kw)


def mlp(p, n, mono):
    return make_pipeline(StandardScaler(), MLPRegressor(hidden_layer_sizes=p["h"], alpha=p["alpha"], learning_rate_init=1e-3,
                                                        max_iter=1000, early_stopping=True, n_iter_no_change=30,
                                                        random_state=SEED))


MODELS = {  # name: (factory, early-stops on val, supports monotone, candidate settings)
    "Ridge": (ridge, False, False, [{"alpha": a} for a in (0.1, 1, 10, 100)]),
    "Random Forest": (rf, False, False, [{"leaf": 1, "mf": 0.5}, {"leaf": 5, "mf": 0.5}, {"leaf": 20, "mf": 0.33}]),
    "HistGradientBoosting": (hgb, True, True, [{"leaves": 15, "leaf": 20, "l2": 1}, {"leaves": 31, "leaf": 50, "l2": 1},
                                               {"leaves": 7, "leaf": 50, "l2": 10}]),
    "XGBoost": (xgbm, True, True, [{"depth": 4, "mcw": 5, "l2": 5}, {"depth": 3, "mcw": 10, "l2": 10, "gamma": 0.5},
                                   {"depth": 2, "mcw": 20, "l2": 20, "gamma": 1}]),
    "LightGBM": (lgbm, True, True, [{"leaves": 15, "leaf": 20, "l2": 1}, {"leaves": 31, "leaf": 50, "l2": 5},
                                    {"leaves": 7, "leaf": 50, "l2": 10}]),
    "CatBoost": (cat, True, True, [{"depth": 4, "l2": 3}, {"depth": 6, "l2": 3}, {"depth": 6, "l2": 10}]),
    "MLP": (mlp, False, False, [{"h": (64, 32), "alpha": a} for a in (1e-3, 1e-2, 1e-1)]),
}


def fit_es(name, est, Xtr, ytr, Xva, yva):
    """Fit with early stopping on val where supported; return (fitted, iterations used or None)."""
    if name == "XGBoost":
        est.fit(Xtr, ytr, eval_set=[(Xva, yva)], verbose=False)
        return est, est.best_iteration + 1
    if name == "LightGBM":
        est.fit(Xtr, ytr, eval_set=[(Xva, yva)], callbacks=[lgb.early_stopping(100, verbose=False)])
        return est, est.best_iteration_
    if name == "CatBoost":
        est.fit(Xtr, ytr, eval_set=(Xva, yva), use_best_model=True)
        return est, est.get_best_iteration() + 1
    if name == "HistGradientBoosting":  # staged predictions on val pick the iteration count
        est.fit(Xtr, ytr)
        scores = [r2_score(yva, p) for p in est.staged_predict(Xva)]
        return est, int(np.argmax(scores)) + 1
    est.fit(Xtr, ytr)
    return est, None


def run_task(task):
    X, y, m = load_task(task, "live")
    Xn, yn = X.to_numpy(np.float32), y.to_numpy()
    tr, va, te = (m.split == "train").to_numpy(), (m.split == "val").to_numpy(), (m.split == "test").to_numpy()
    mono_list = monotone_constraints(task, list(X.columns)) if task == "runoff" else None
    rows, fitted = [], {}
    for name, (make, es, can_mono, grid) in MODELS.items():
        mono = mono_list if (can_mono and mono_list) else None
        best = None
        for p in grid:  # 1. choose on val
            est, n = fit_es(name, make(p, None, mono), Xn[tr], yn[tr], Xn[va], yn[va])
            if name == "HistGradientBoosting":  # score val at the chosen iteration
                est = make(p, n, mono).fit(Xn[tr], yn[tr])
            v = r2_score(yn[va], est.predict(Xn[va]))
            if best is None or v > best["val"]:
                best = dict(p=p, n=n, val=v, train=r2_score(yn[tr], est.predict(Xn[tr])))
        t0 = time.time()  # 2. refit on train+val, score test once
        final = make(best["p"], best["n"], mono).fit(Xn[tr | va], yn[tr | va])
        fit_s = time.time() - t0
        pt = final.predict(Xn[te])
        big = np.tile(Xn[te], (int(np.ceil(10000 / te.sum())), 1))[:10000]
        t0 = time.time(); final.predict(big); ms = (time.time() - t0) * 1000
        cv = []  # 3. unseen blocks AND future year
        for k in range(5):
            a, b = (m.cv_fold != k).to_numpy() & tr, (m.cv_fold == k).to_numpy() & te
            cv.append(r2_score(yn[b], make(best["p"], best["n"], mono).fit(Xn[a], yn[a]).predict(Xn[b])))
        rows.append(dict(task=task, model=name, settings=json.dumps(best["p"]), iterations=best["n"],
                         monotone=bool(mono), train_r2=best["train"], val_r2=best["val"], test_r2=r2_score(yn[te], pt),
                         test_mae=mean_absolute_error(yn[te], pt), test_rmse=mean_squared_error(yn[te], pt) ** 0.5,
                         unseen_future_r2=np.mean(cv), unseen_future_sd=np.std(cv),
                         fit_seconds=fit_s, predict_ms_per_10k=ms))
        fitted[name] = final
        print(f"  {task:6s} {name:21s} val {best['val']:.3f}  test {rows[-1]['test_r2']:.3f}  "
              f"unseen+future {np.mean(cv):.3f} ± {np.std(cv):.3f}  ({ms:.0f} ms/10k)")
    df = pd.DataFrame(rows)
    df["best_by_val"] = df.val_r2 == df.val_r2.max()
    win = df[df.best_by_val].iloc[0]
    os.makedirs(OUT_MODELS, exist_ok=True)
    stem = f"{task}_{win.model.lower().replace(' ', '_')}"
    joblib.dump(fitted[win.model], f"{OUT_MODELS}/{stem}.joblib")
    meta = dict(task=task, model=win.model, settings=json.loads(win.settings), iterations=None if pd.isna(win.iterations) else int(win.iterations),
                features=list(X.columns), feature_set="live", target=load_spec()[task]["target"],
                trained_on="train+val (2021-2024)", monotone=bool(win.monotone),
                scores={k: round(float(win[k]), 4) for k in ["val_r2", "test_r2", "test_mae", "test_rmse", "unseen_future_r2", "unseen_future_sd"]},
                selected_by="highest val R2 (2024) among all models and settings")
    json.dump(meta, open(f"{OUT_MODELS}/{stem}.json", "w"), indent=2)
    print(f"  -> saved {OUT_MODELS}/{stem}.joblib")
    return df


def main():
    out = pd.concat([run_task("yield"), run_task("runoff")], ignore_index=True)
    os.makedirs(OUT_REPORTS, exist_ok=True)
    out.round(4).to_csv(f"{OUT_REPORTS}/model_comparison.csv", index=False)
    cols = ["model", "train_r2", "val_r2", "test_r2", "test_mae", "unseen_future_r2", "unseen_future_sd", "predict_ms_per_10k", "best_by_val"]
    pd.set_option("display.width", 220)
    for t, g in out.groupby("task", sort=False):
        print(f"\n== {t} (live features) ==")
        print(g[cols].sort_values("val_r2", ascending=False).round(3).to_string(index=False))


if __name__ == "__main__":
    main()
