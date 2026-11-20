"""Perturbation-controlled benchmark of escalation decisions in healthcare LLM agents."""

__version__ = "0.1.0"

from .episodes import ACTIONS, VARIANTS, TASKS, load_episodes, model_inputs  # noqa: E402,F401
from .scoring import load_predictions, score  # noqa: E402,F401
