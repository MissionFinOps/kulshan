# Reckoner incremental refresh (PR 4)

PR 4 establishes the refresh boundary around manifest identity and staged partition replacement. A refresh compares the previous and current immutable manifest metadata, identifies changed objects and affected periods, and computes bytes that must be read.

Refreshes are serialized by a workspace lock. New partitions are built in a staging directory, validated by caller-supplied payer/schema/period/total checks, and committed by atomic state replacement. Freshness is updated only after validation succeeds. Validation or build failure raises a structured refresh error and preserves the previous cache state. An unchanged manifest is a no-op with zero Parquet bytes read.

The module is intentionally a refresh contract and staging engine. It does not choose query sources, execute SQL, download objects, materialize the physical cache, or expose new terminal workflows. Those concerns remain separate boundaries.