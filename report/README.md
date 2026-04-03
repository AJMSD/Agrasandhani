# Final Deliverables

This directory contains the tracked final-deliverables package for M5.

Contents:

- `reproducibility.md`: environment setup and end-to-end rerun instructions
- `related_work_notes.md`: concise reading notes for the final discussion
- `references.bib`: bibliography entries for the report
- `assets/`: tracked figures, tables, and the evidence manifest generated from local runs
- `final_report.md`: ACM-structured Markdown report draft regenerated from the final evidence runs
- `deliverable_gate.md`: generated completion cross-check tying deliverables to concrete repo evidence

The large raw datasets, normalized replay CSVs, and full experiment logs stay local-only under ignored paths in `experiments/logs/`. The committed deliverable set contains only the derived figures, tables, manifests, and report text needed to reproduce the final claims.

Use `experiments/run_final_deliverables.py` or the shell wrappers to preprocess the local raw datasets, run the Intel and AoT evidence paths, capture the final demo, and regenerate this directory's generated assets.
