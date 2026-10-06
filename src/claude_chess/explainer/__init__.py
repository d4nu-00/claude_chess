"""Explainer model: engine lines -> human concepts -> condensed explanations.

See wiki/pages/explainer-model.md. Heavy dependencies (torch, mlx) are imported lazily
inside the modules that need them, so `concepts` and `data` work with the base install.
"""
