COMPOSE := docker compose
RUN     := $(COMPOSE) run --rm client

.PHONY: help up down reset schema status smoke cqlsh shell client \
        add-node decommission-node exp1 exp2 exp3 exp4 exp5 exp6 figures \
        test exp2-quick exp2-report demo-exp2 verify exp6-race deck

help:
	@echo "Cluster:     make up | schema | status | smoke | down | reset"
	@echo "Tools:       make cqlsh | shell | client"
	@echo "Topology:    make add-node [PRELOAD=100000] | decommission-node"
	@echo "Experiments: make exp1 ... exp6 | figures"
	@echo "Person 2:    make test | exp2-quick | exp2-report | demo-exp2"
	@echo "H. Hasanov:  make verify | exp4 [VARIANT=all|4a|4b|4c] [REP=n] | exp6 [REP=n] | exp6-race | figures | deck"

up:
	bash scripts/up.sh

down:
	$(COMPOSE) --profile scale --profile tools down

reset:
	bash scripts/reset.sh

schema:
	bash scripts/load_schema.sh

status:
	bash scripts/status.sh

smoke:
	bash scripts/smoke_test.sh

cqlsh:
	docker exec -it cass1 cqlsh

shell:
	$(RUN) bash

client:
	$(COMPOSE) build client

add-node:
	bash scripts/add_node.sh $(if $(PRELOAD),--preload $(PRELOAD))

decommission-node:
	bash scripts/decommission_node.sh

exp1:
	bash scripts/run_exp1.sh

exp2: client
	bash workload/consistency_matrix.sh

# Person 2 - application, workload generator, consistency tuning ----------------------
# Unit tests: need only the client image, not a running cluster.
test: client
	$(RUN) python -m pytest -q -p no:cacheprovider tests

# About 4-minute dry run of the full Exp 2 grid (1 repetition, short runs).
exp2-quick: client
	QUICK=1 bash workload/consistency_matrix.sh

# Tables, LaTeX numbers and figures from results/raw/exp2/ (refuses to run without data).
exp2-report: client
	$(RUN) python -m workload.exp2_summary

exp3: client
	bash chaos/run_exp3.sh $(if $(VARIANT),--variant $(VARIANT),) \
		$(if $(NODE),--node $(NODE),) $(if $(REP),--rep $(REP),) \
		$(if $(DURATION),--duration $(DURATION),) \
		$(if $(FAULT_AFTER),--fault-after $(FAULT_AFTER),) \
		$(if $(FAULT_SECONDS),--fault-seconds $(FAULT_SECONDS),)

exp5: client
	bash chaos/run_exp5.sh $(if $(NODE),--node $(NODE),) \
		$(if $(REP),--rep $(REP),) $(if $(DURATION),--duration $(DURATION),) \
		$(if $(FAULT_AFTER),--fault-after $(FAULT_AFTER),) \
		$(if $(FAULT_SECONDS),--fault-seconds $(FAULT_SECONDS),)

# Live demo segment: 20 s at ONE, then 20 s at ALL, with the per-second summary line.
demo-exp2: client
	$(RUN) python -m workload.runner --mode mixed --cl ONE --rate 200 --duration 20 --exp demo --variant live
	$(RUN) python -m workload.runner --mode mixed --cl ALL --rate 200 --duration 20 --exp demo --variant live

# Habib Hasanov - recovery, consensus, analysis --------------------------------------
PYTHON ?= python3

# Convergence check: Merkle-tree preview repair (+ acknowledged writes if WRITES is given).
verify:
	$(PYTHON) -m recovery.verify_convergence full --label $(or $(LABEL),manual) $(if $(WRITES),--writes $(WRITES),)

exp4: client
	bash recovery/hints_vs_repair.sh $(if $(VARIANT),--variant $(VARIANT),) $(if $(REP),--rep $(REP),) $(if $(ROWS),--rows $(ROWS),)

exp6: client
	bash recovery/run_exp6.sh $(if $(REP),--rep $(REP),)

# Live demo segment: one LWT race, one line per handle.
exp6-race: client
	$(RUN) python -m recovery.lwt_demo race --clients 10 --handles 20 --variant demo

# Summary tables, report numbers and figures from results/ (refuses to run without data).
figures: client
	$(RUN) sh -c "python -m analysis.summarize && python -m analysis.plots"

# Group slide deck (docs/presentation/group4_deck.pptx); needs Node with pptxgenjs (npm i -g pptxgenjs).
deck:
	node docs/presentation/build_deck.js
