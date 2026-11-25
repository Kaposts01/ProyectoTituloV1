"""ML-08: explicit feature contracts and lazy, UNFITTED sklearn factories.

No fit/transform/predict is invoked here. Importing this module needs no ML runtime.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import math
import platform
from decimal import Decimal, InvalidOperation

from app.ml.annotation_contract import NORMALIZATION_VERSION, AnnotationContext
from app.ml.dataset_export import canonical_json
from app.ml.export_snapshot import exact
from app.ml.taxonomy import TAXONOMY_VERSION
from app.ml.temporal_dataset import DATASET_VERSION, EPISODE_POLICY, SOURCES

PIPELINE_VERSION = "rejection-pipelines-v1-draft"
FEATURES = {
    "p1": ("source", "resource_type", "processor", "code", "processor_code", "normalized_text"),
    "p2": ("source", "amount", "currency", "elapsed_days", "days_from_due"),
}
TASKS = {"char_tfidf_logistic": "p1", "logistic": "p2", "hist_gradient_boosting": "p2"}
PACKAGES = ("numpy", "scipy", "scikit-learn", "skops", "joblib", "threadpoolctl", "narwhals")
PINNED = {"numpy": "2.5.3", "scipy": "1.18.1", "scikit-learn": "1.9.1", "skops": "0.16.0",
          "joblib": "1.6.0", "threadpoolctl": "3.8.0", "narwhals": "2.29.0"}


def environment() -> dict:
    packages = {}
    for name in PACKAGES:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {"python": platform.python_version(), "implementation": platform.python_implementation(),
            "system": platform.system(), "machine": platform.machine(), "packages": packages}


def recipe(candidate: str, *, seed: int = 17) -> dict:
    if candidate not in TASKS or type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("Pipeline o semilla no admitidos")
    task = TASKS[candidate]
    schema = {"task": task, "features": FEATURES[task], "input": "ordered-matrix-v1",
              "dataset_version": DATASET_VERSION, "extra_features": "reject"}
    if task == "p1":
        schema.update(normalization_version=NORMALIZATION_VERSION, taxonomy_version=TAXONOMY_VERSION)
    else:
        schema.update(amount="CLP-integer-text", numeric_cast="float-for-ML-only", missing_numeric="NaN-after-validation",
                      episode_policy=EPISODE_POLICY)
    return {"version": PIPELINE_VERSION, "candidate_id": candidate, "task": task,
            "feature_names": list(FEATURES[task]), "schema_sha256": hashlib.sha256(canonical_json(schema)).hexdigest(),
            "seed": seed, "training_executed": False, "fitting_policy": "train-only; separate frozen calibration",
            "preprocessing": "char-3-5-tfidf-plus-onehot" if task == "p1" else "numeric-median-indicator-plus-onehot",
            "hidden_validation": False}


def feature_matrix(task: str, rows: list[dict]) -> list[list]:
    """Validate the whitelist before ordering columns. No learner/statistic is fitted."""
    if task not in FEATURES or len(rows) > 100_000:
        raise ValueError("Matriz no admitida")
    result = []
    for row in rows:
        exact(row, set(FEATURES[task]))
        if task == "p1":
            AnnotationContext(**row, privacy_reviewed=True)  # Prior human privacy review remains mandatory.
            result.append([row[name] for name in FEATURES[task]])
            continue
        try:
            if row["source"] not in SOURCES or row["currency"] != "CLP" or type(row["amount"]) is not str or len(row["amount"]) > 24:
                raise ValueError("Monto/fuente invalidos")
            amount = Decimal(row["amount"])
            if not amount.is_finite() or not 0 < amount <= Decimal("9999999999999999") or amount != amount.to_integral_value():
                raise ValueError("Monto invalido")
            numbers = []
            for name in ("elapsed_days", "days_from_due"):
                value = row[name]
                if value is None and name == "days_from_due":
                    numbers.append(float("nan"))
                elif type(value) not in {int, float} or not math.isfinite(value):
                    raise ValueError("Variable numerica invalida")
                else:
                    numbers.append(float(value))
            if not 0 <= numbers[0] < 30:
                raise ValueError("Calculo fuera del horizonte")
            result.append([row["source"], float(amount), row["currency"], *numbers])
        except (InvalidOperation, TypeError, OverflowError):
            raise ValueError("Variables P2 invalidas") from None
    return result


def build_pipeline(candidate: str, *, seed: int = 17):
    """Build only; callers must separately authorize and isolate training and calibration."""
    definition = recipe(candidate, seed=seed)
    if environment()["packages"] != PINNED:
        raise ValueError("El entorno no coincide con requirements-ml.lock")
    try:
        from sklearn.compose import ColumnTransformer
        from sklearn.ensemble import HistGradientBoostingClassifier
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import OneHotEncoder, StandardScaler
    except ImportError:
        raise ValueError("Use el entorno experimental bloqueado; no instale ML en el CRM por defecto") from None
    if definition["task"] == "p1":
        preprocessing = ColumnTransformer([
            ("text", TfidfVectorizer(analyzer="char", ngram_range=(3, 5), min_df=1, max_features=50_000), 5),
            ("context", OneHotEncoder(handle_unknown="ignore", sparse_output=True), [0, 1, 2, 3, 4]),
        ], remainder="drop")
        estimator = LogisticRegression(C=1.0, max_iter=1000, random_state=seed)
    else:
        numeric_steps = [("impute", SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True))]
        if candidate == "logistic":
            numeric_steps.append(("scale", StandardScaler()))
        preprocessing = ColumnTransformer([
            ("numeric", Pipeline(numeric_steps), [1, 3, 4]),
            ("context", OneHotEncoder(handle_unknown="ignore", sparse_output=False), [0, 2]),
        ], remainder="drop", sparse_threshold=0)
        estimator = (LogisticRegression(C=1.0, max_iter=1000, random_state=seed) if candidate == "logistic" else
                     HistGradientBoostingClassifier(max_iter=100, max_depth=3, max_leaf_nodes=15, min_samples_leaf=20,
                                                    early_stopping=False, random_state=seed))
    return Pipeline([("preprocess", preprocessing), ("model", estimator)])


def build_calibrator(fitted_pipeline):
    """Separate frozen calibration. Reject unfitted inputs; never fit here."""
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.frozen import FrozenEstimator
    from sklearn.utils.validation import check_is_fitted

    check_is_fitted(fitted_pipeline)
    return CalibratedClassifierCV(FrozenEstimator(fitted_pipeline), method="sigmoid")
