"""Analysis pipeline for every experiment (owner: Habib Hasanov).

    make figures      ==  python -m analysis.summarize && python -m analysis.plots

summarize  reads every results/raw/<exp>/*.csv written in the shared schema
           (docs/CONTRACTS.md) plus the chaos event log and the Exp 4/6 evidence logs,
           and writes results/summary/*.csv, results/summary/summary.md and the LaTeX
           numbers used by report section 7.4 (docs/report/generated/).
plots      draws results/figures/*.png (300 dpi) from the same data.

Both refuse to run without data: no placeholder number can reach the report.
Person 2's workload/exp2_summary.py keeps producing the Exp 2 tables; this pipeline
adds the cross-experiment views (fault-phase availability, detection times, Exp 4, Exp 6).
"""
