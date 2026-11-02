import pytest
import numpy as np

from src.kalman_filter import KalmanHedgeRatioFilter


def test_kalman_filter_tracking():
    # Linear model: y = 2.0 * x + 1.5 + noise
    np.random.seed(42)
    n = 1000
    x = np.linspace(1, 10, n)
    true_beta = 1.85
    true_alpha = 0.5
    y = true_alpha + true_beta * x + np.random.normal(0, 0.05, n)

    # Note observation: y = [1, x] * [alpha, beta]^T
    kf = KalmanHedgeRatioFilter(delta=1e-4, observation_noise=1e-3)
    alphas, betas, spreads = kf.filter_series(y, x)

    # In late sample, beta should converge close to true_beta
    estimated_beta = betas[-1]
    estimated_alpha = alphas[-1]

    assert abs(estimated_beta - true_beta) < 0.15
    assert abs(estimated_alpha - true_alpha) < 0.30

    # Covariance matrix must remain symmetric and positive-definite
    assert np.all(np.linalg.eigvals(kf.P) > 0)
    assert np.allclose(kf.P, kf.P.T)
