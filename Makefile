COMPOSE := docker compose
RUN     := $(COMPOSE) run --rm client

.PHONY: help up down reset schema status smoke cqlsh shell client \
        add-node decommission-node exp1 exp2 exp3 exp4 exp5 exp6 figures

help:
	@echo "Cluster:     make up | schema | status | smoke | down | reset"
	@echo "Tools:       make cqlsh | shell | client"
	@echo "Topology:    make add-node [PRELOAD=100000] | decommission-node"
	@echo "Experiments: make exp1 ... exp6 | figures"

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

exp2:
	bash workload/consistency_matrix.sh

exp3:
	bash chaos/run_exp3.sh

exp4:
	bash recovery/hints_vs_repair.sh

exp5:
	bash chaos/run_exp5.sh

exp6:
	$(RUN) python -m recovery.lwt_demo race --clients 10 --handles 20

figures:
	$(RUN) sh -c "python -m analysis.summarize && python -m analysis.plots"
