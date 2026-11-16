"""CassChat application package: shared data-access layer, CLI and CSV results logger.

Every Python script in the repository talks to Cassandra through ``app.db`` so that
driver policies (token-aware routing, no hidden retries, 5 s client timeout) are
identical in the workload generator, the chaos probe and the recovery tooling.
"""
