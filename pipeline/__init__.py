"""Stage 2 data pipeline: raw -> staging -> marts, orchestrated with Prefect (ADR 0005).

The modules here are plain Python and can be used and tested without Prefect.
Only `pipeline.flows` imports Prefect; it wires the steps together.
"""
