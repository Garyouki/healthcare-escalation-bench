"""Perturbation-controlled benchmark of escalation decisions in healthcare LLM agents."""

__version__ = "0.1.1"

from .episodes import ACTIONS, VARIANTS, TASKS, load_episodes, model_inputs  # noqa: E402,F401
from .scoring import load_predictions, score  # noqa: E402,F401

__all__ = ["ACTIONS", "VARIANTS", "TASKS", "load_episodes", "model_inputs",
           "load_predictions", "score"]

# The Inspect AI task is optional: the core package has no dependencies.
try:
    from .inspect_task import healthcare_escalation  # noqa: E402,F401
except ImportError:  # inspect_ai is not installed
    pass
else:
    __all__.append("healthcare_escalation")
