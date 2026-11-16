# Report sections by Person 2

| File | Section | Pages (target) |
|---|---|---|
| `sec3_consistency.tex` | §3 Consistency Model & Read/Write Paths | ~2.0 |
| `sec7_2_results_exp1_2.tex` | §7.2 Results of Exp 1–2 | ~0.75 |
| `refs_p2.bib` | BibTeX entries cited by both (merge into `docs/references.bib`) | — |
| `generated/exp2_numbers.tex`, `generated/exp2_tables.tex` | numbers and tables, written by `make exp2-report` | — |
| `p2_preview.tex` | stand-alone preview, not part of the final report | — |

## How the final report includes them (Person 3)

In the IEEEtran main file (in `docs/report/`):

```latex
\usepackage{graphicx,amsmath,url}
\graphicspath{{../diagrams/}{../../results/figures/}}
...
\input{sec3_consistency}        % after Section 2
...
\section{Experimental Results}
\input{sec7_1_setup}            % Person 1
\input{sec7_2_results_exp1_2}   % this file
```

Cross-references used (please keep these labels in the other sections or tell me):
`sec:architecture` (§2, P1), `sec:setup` (§7.1, P1), `sec:antientropy` and `sec:consensus` (P4).
Labels defined here: `sec:consistency`, `sec:results-exp2`, `tab:cl`, `tab:quorum`,
`fig:write-path`, `fig:read-path`, `fig:quorum`, `tab:exp2-grid`, `tab:exp2-probe`, `fig:exp2-latency`.

## Numbers

§7.2 contains no typed-in measurement. Every value is `\exptwo{name}`, defined in
`generated/exp2_numbers.tex` by `workload/exp2_summary.py` from `results/raw/`. Until
`make exp2 && make exp2-report` has run, each value prints as **[run make exp2-report]**.
If the script prints "NOTE: a result deviates from the expected behaviour", reread §7.2's
interpretation paragraph against the data.

## Preview

```bash
cd docs/report && latexmk -pdf -outdir=build p2_preview.tex   # build/ is git-ignored
```
