"""The pure core. Plain data in, plain data out.

No cloud SDK, no Collibra client, no Streamlit, no network. `scripts/check_core_purity.py` fails the
build the day an import here reaches outside the standard library, pydantic, yaml or lkml.
"""
