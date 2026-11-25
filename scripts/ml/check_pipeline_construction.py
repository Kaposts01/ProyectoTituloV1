"""Explicit optional-env pytest file, not collected by default. NO model fitting."""

from unittest.mock import patch

import pytest
import skops.io
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.exceptions import NotFittedError
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.utils.validation import check_is_fitted

from app.ml.pipelines import TASKS, build_calibrator, build_pipeline


@pytest.mark.parametrize("candidate", tuple(TASKS))
def test_factory_constructs_without_any_fit(candidate, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No training is authorized in ML-08 validation")
    for estimator in (Pipeline, ColumnTransformer, TfidfVectorizer, SimpleImputer, OneHotEncoder,
                      StandardScaler, LogisticRegression, HistGradientBoostingClassifier, CalibratedClassifierCV):
        monkeypatch.setattr(estimator, "fit", forbidden)
    pipeline = build_pipeline(candidate)
    with pytest.raises(NotFittedError):
        check_is_fitted(pipeline)
    if candidate == "hist_gradient_boosting":
        assert pipeline.named_steps["model"].early_stopping is False
    assert not hasattr(pipeline.named_steps["model"], "classes_")


@pytest.mark.parametrize("candidate", tuple(TASKS))
def test_calibrator_rejects_unfitted_pipeline(candidate):
    with pytest.raises(NotFittedError):
        build_calibrator(build_pipeline(candidate))


@pytest.mark.parametrize("candidate", tuple(TASKS))
def test_skops_inspection_without_loading_or_training(candidate):
    pipeline = build_pipeline(candidate)
    with patch.object(skops.io, "loads", side_effect=AssertionError("No loading")), patch.object(skops.io, "load", side_effect=AssertionError("No loading")):
        encoded = skops.io.dumps(pipeline)
        assert skops.io.get_untrusted_types(data=encoded) == []
    with pytest.raises(NotFittedError):
        check_is_fitted(pipeline)
