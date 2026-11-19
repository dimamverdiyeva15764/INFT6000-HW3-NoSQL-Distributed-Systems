# Report sections by Habib Hasanov

| File | Section | Pages (target) |
|---|---|---|
| `sec4_antientropy.tex` | §4 Conflict Resolution & Anti-Entropy | ~1.25 |
| `sec5_consensus.tex` | §5 Consensus & Coordination | ~1.0 |
| `sec7_4_results_exp4_6.tex` | §7.4 Results of Exp 4 and Exp 6 | ~0.5 |
| `sec7_fault_analysis.tex` | fault-phase analysis of Exp 3/5 — **offered to Person 3** for §7.3 (optional) | ~0.4 + figure* |
| `../references.bib` | group bibliography (35 entries; includes all of `refs_p2.bib` unchanged) | — |
| `generated/exp46_numbers.tex`, `generated/fault_tables.tex` | values and tables written by `make figures` | — |
| `hasanov_preview.tex` | stand-alone preview, not part of the final report | — |
| `latexmkrc` | lets `\bibliography{references}` find `docs/references.bib`, also with `-outdir` | — |

## How the final report includes them (Person 3)

```latex
\usepackage{graphicx,amsmath,amssymb,url}
\graphicspath{{../diagrams/}{../../results/figures/}}
...
\input{sec4_antientropy}        % after Section 3 (Person 2)
\input{sec5_consensus}
...
\section{Experimental Results}
\input{sec7_1_setup}            % Person 1
\input{sec7_2_results_exp1_2}   % Person 2
% 7.3 Person 3 (optionally \input{sec7_fault_analysis} inside it)
\input{sec7_4_results_exp4_6}
...
\bibliographystyle{IEEEtran}
\bibliography{references}       % docs/references.bib - replaces refs_p2
```

Labels defined here: `sec:antientropy`, `sec:consensus`, `sec:results-exp46`, `fig:antientropy`,
`tab:antientropy`, `fig:paxos`, `tab:coordination`, `fig:hints`, `fig:lwt`,
`fig:fault-timeline`, `tab:fault-phases`, `tab:detection`.
Labels used from others: `sec:consistency` (P2, §3), `sec:cap` (**P3: please put this label on §6**),
`sec:architecture`, `sec:setup` (P1).

## Numbers

No measurement is typed in. Every value is `\expfour{..}`, `\expsix{..}` or `\expfault{..}`,
defined in `generated/exp46_numbers.tex` by `analysis/summarize.py`:

- `\expfault{..}` (Exp 3/5 fault phases, detection times) — **already generated** from the
  committed CSVs of Persons 2 and 3.
- `\expfour{..}` / `\expsix{..}` print as **[make exp4]** / **[make exp6]** until those experiments
  have run on a Docker machine and `make figures` has been rerun. The concluding sentences
  (`4b-conclusion`, `race2-conclusion`, ...) are also generated: if a run deviates from the
  expected behaviour they say so (`NOTE: ...`) instead of claiming the expected result.

## Build the preview

```bash
cd docs/report && latexmk -pdf -outdir=build hasanov_preview.tex
```
