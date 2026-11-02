"""
Kalman Filter for Dynamic Hedge Ratio and Intercept Estimation.
Implements online state-space estimation with Joseph form covariance updates
to guarantee numerical stability and positive semi-definiteness.
"""

from typing import Tuple, List, Optional
import numpy as np
import pandas as pd

from config import kalman_config


class KalmanHedgeRatioFilter:
    """
    Two-state Kalman Filter tracking:
        theta_t = [alpha_t, beta_t]^T
    Observation:
        X_t = [1, Y_t] * theta_t + v_t,   v_t ~ N(0, R)
    State Transition:
        theta_t = theta_{t-1} + w_t,      w_t ~ N(0, Q)
    """

    def __init__(
        self,
        delta: float = kalman_config.delta,
        observation_noise: float = kalman_config.observation_noise,
        initial_state: Optional[np.ndarray] = None,
        initial_covariance: float = kalman_config.initial_covariance
    ):
        self.delta = delta
        self.R = float(observation_noise)  # Observation noise variance
        # State transition noise Q
        self.Q = (delta / (1.0 - delta)) * np.eye(2)

        # State vector [alpha, beta]
        if initial_state is not None:
            self.theta = np.array(initial_state, dtype=np.float64)
        else:
            self.theta = np.zeros(2, dtype=np.float64)

        # State estimation error covariance matrix P
        self.P = np.eye(2, dtype=np.float64) * initial_covariance
        self.I2 = np.eye(2, dtype=np.float64)

    def step(self, x_val: float, y_val: float) -> Tuple[float, float, float, float]:
        """
        Executes single online observation update (time t).

        Args:
            x_val: log price of asset A at time t
            y_val: log price of asset B at time t

        Returns:
            alpha_t, beta_t, residual_spread_t, variance_t
        """
        # 1. State Prediction (A = Identity)
        theta_pred = self.theta
        P_pred = self.P + self.Q

        # 2. Measurement Vector H = [1.0, Y_t]
        H = np.array([[1.0, y_val]], dtype=np.float64)

        # 3. Measurement Innovation
        pred_x = float((H @ theta_pred)[0])
        innovation = float(x_val - pred_x)

        # 4. Innovation Covariance S = H * P_pred * H^T + R
        S = float((H @ P_pred @ H.T)[0, 0]) + self.R

        # 5. Kalman Gain K = P_pred * H^T / S
        K = (P_pred @ H.T) / S  # Shape (2, 1)

        # 6. State Update theta = theta_pred + K * innovation
        self.theta = theta_pred + (K.flatten() * innovation)

        # 7. Joseph Form Covariance Update:
        # P = (I - K*H) * P_pred * (I - K*H)^T + K * R * K^T
        I_KH = self.I2 - (K @ H)
        self.P = (I_KH @ P_pred @ I_KH.T) + (self.R * (K @ K.T))

        alpha_t = float(self.theta[0])
        beta_t = float(self.theta[1])
        spread_t = x_val - alpha_t - beta_t * y_val

        return alpha_t, beta_t, spread_t, S

    def filter_series(
        self,
        log_a: np.ndarray,
        log_b: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Processes an entire historical series sequentially.
        Guarantees zero forward-looking bias by advancing step-by-step.

        Returns:
            alphas: array of dynamic intercepts
            betas: array of dynamic hedge ratios
            spreads: array of dynamic residual spreads
        """
        n = len(log_a)
        alphas = np.zeros(n)
        betas = np.zeros(n)
        spreads = np.zeros(n)

        for i in range(n):
            a_i, b_i, s_i, _ = self.step(log_a[i], log_b[i])
            alphas[i] = a_i
            betas[i] = b_i
            spreads[i] = s_i

        return alphas, betas, spreads
