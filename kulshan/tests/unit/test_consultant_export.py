"""End-to-end tests for consultant evidence export.

Uses synthetic CUR Parquet data to verify the full pipeline:
scope -> classification -> pseudonymization -> gates -> package.
"""
from __future__ import annotations

import json
import os
import zipfile
from datetime import date
from pathlib import Path

import pytest

from kulshan.export.columns import ColumnClass, classify_all_columns, classify_column
from kulshan.export.gates import gate_integrity, gate_residual, gate_schema
from kulshan.export.scope import EvidenceScope


SYNTHETIC_ACCOUNT = "111222333444"
SYNTHETIC_RESOURCE = "i-0abc123def456789a"


# ═══════════════════════════════════════════════════════════════════════════════
# SCOPE TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestEvidenceScope:
    def test_valid_scope(self):
        scope = EvidenceScope(from_date=date(2026, 7, 1), to_date=date(2026, 8, 1))
        assert scope.from_date == date(2026, 7, 1)

    def test_invalid_date_range(self):
        with pytest.raises(ValueError, match="must be before"):
            EvidenceScope(from_date=date(2026, 8, 1), to_date=date(2026, 7, 1))

    def test_conflicting_accounts(self):
        with pytest.raises(ValueError, match="Cannot specify both"):
            EvidenceScope(
                from_date=date(2026, 7, 1), to_date=date(2026, 8, 1),
                include_accounts=("111",), exclude_accounts=("222",),
            )

    def test_to_dict(self):
        scope = EvidenceScope(
            from_date=date(2026, 7, 1), to_date=date(2026, 8, 1),
            include_accounts=("111222333444",),
        )
        d = scope.to_dict()
        assert d["from_date"] == "2026-07-01"
        assert d["include_accounts"] == ["111222333444"]

    def test_duckdb_where_clause(self):
        scope = EvidenceScope(
            from_date=date(2026, 7, 1), to_date=date(2026, 8, 1),
            include_services=("AmazonEC2",),
        )
        where = scope.duckdb_where_clause("usage_start", "account_id", "service")
        assert "2026-07-01" in where
        assert "AmazonEC2" in where

    def test_ce_filter_single(self):
        scope = EvidenceScope(
            from_date=date(2026, 7, 1), to_date=date(2026, 8, 1),
            include_accounts=("111222333444",),
        )
        f = scope.ce_filter()
        assert f is not None
        assert f["Dimensions"]["Key"] == "LINKED_ACCOUNT"


# ═══════════════════════════════════════════════════════════════════════════════
# COLUMN CLASSIFICATION TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestColumnClassification:
    def test_safe_columns(self):
        assert classify_column("line_item_unblended_cost") == ColumnClass.SAFE
        assert classify_column("product_region") == ColumnClass.SAFE
        assert classify_column("line_item_usage_start_date") == ColumnClass.SAFE
        assert classify_column("line_item_usage_type") == ColumnClass.SAFE
        assert classify_column("pricing_public_on_demand_cost") == ColumnClass.SAFE

    def test_pseudonymize_columns(self):
        assert classify_column("line_item_usage_account_id") == ColumnClass.PSEUDONYMIZE
        assert classify_column("bill_payer_account_id") == ColumnClass.PSEUDONYMIZE
        assert classify_column("line_item_resource_id") == ColumnClass.PSEUDONYMIZE
        assert classify_column("savings_plan_savings_plan_a_r_n") == ColumnClass.PSEUDONYMIZE

    def test_tag_columns_allowlisted(self):
        assert classify_column("resource_tags_user_environment") == ColumnClass.PSEUDONYMIZE
        assert classify_column("resource_tags_user_owner") == ColumnClass.PSEUDONYMIZE
        assert classify_column("resource_tags_aws_createdby") == ColumnClass.PSEUDONYMIZE

    def test_tag_columns_unknown_blocked(self):
        assert classify_column("resource_tags_user_jira_project") == ColumnClass.UNCLASSIFIED

    def test_tag_columns_keep_tag(self):
        # With keep_tag, unknown tag keys become pseudonymize instead of unclassified
        assert classify_column("resource_tags_user_jira_project", keep_tags=frozenset({"jira_project"})) == ColumnClass.PSEUDONYMIZE

    def test_drop_columns(self):
        assert classify_column("identity_line_item_id") == ColumnClass.DROP

    def test_truly_unknown(self):
        assert classify_column("completely_new_column_from_future") == ColumnClass.UNCLASSIFIED

    def test_classify_all(self):
        columns = {"line_item_unblended_cost", "line_item_usage_account_id", "product_region"}
        result = classify_all_columns(columns)
        assert result["line_item_unblended_cost"] == ColumnClass.SAFE
        assert result["line_item_usage_account_id"] == ColumnClass.PSEUDONYMIZE


# ═══════════════════════════════════════════════════════════════════════════════
# GATE TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestGates:
    def test_gate_schema_passes_all_classified(self):
        classification = {
            "col_a": ColumnClass.SAFE,
            "col_b": ColumnClass.PSEUDONYMIZE,
            "col_c": ColumnClass.DROP,
        }
        result = gate_schema(classification)
        assert result.passed

    def test_gate_schema_blocks_unclassified(self):
        classification = {
            "col_a": ColumnClass.SAFE,
            "col_unknown": ColumnClass.UNCLASSIFIED,
        }
        result = gate_schema(classification)
        assert not result.passed
        assert "col_unknown" in result.failures[0]

    def test_gate_schema_drop_unclassified(self):
        classification = {
            "col_a": ColumnClass.SAFE,
            "col_unknown": ColumnClass.UNCLASSIFIED,
        }
        result = gate_schema(classification, drop_unclassified=True)
        assert result.passed
        assert "col_unknown" in result.details["dropped_unclassified"]

    def test_gate_integrity_passes(self):
        result = gate_integrity(source_row_count=1000, output_row_count=1000)
        assert result.passed

    def test_gate_integrity_fails_count_mismatch(self):
        result = gate_integrity(source_row_count=1000, output_row_count=999)
        assert not result.passed

    def test_gate_residual_passes_clean(self):
        result = gate_residual(
            source_identifiers={SYNTHETIC_ACCOUNT},
            output_text="acct_7f31c2a9102d774b some other text",
        )
        assert result.passed

    def test_gate_residual_fails_leaked_id(self):
        result = gate_residual(
            source_identifiers={SYNTHETIC_ACCOUNT},
            output_text=f"This contains {SYNTHETIC_ACCOUNT} in plain text",
        )
        assert not result.passed

    def test_gate_residual_detects_arn_pattern(self):
        result = gate_residual(
            source_identifiers=set(),
            output_text="arn:aws:ec2:us-east-1:123456789012:instance/i-abc123",
        )
        assert not result.passed

    def test_gate_residual_allows_pseudo_emails(self):
        result = gate_residual(
            source_identifiers=set(),
            output_text="user_abc123@pseudo.invalid",
        )
        assert result.passed


# ═══════════════════════════════════════════════════════════════════════════════
# FULL PIPELINE TEST (with synthetic Parquet)
# ═══════════════════════════════════════════════════════════════════════════════


class TestFullPipeline:
    """End-to-end export test using synthetic CUR data."""

    @pytest.fixture
    def synthetic_cur(self, tmp_path) -> Path:
        """Create a minimal synthetic CUR Parquet file."""
        import duckdb

        cur_dir = tmp_path / "cur"
        cur_dir.mkdir()
        parquet_path = cur_dir / "billing.parquet"

        con = duckdb.connect(":memory:")
        con.execute("""
            CREATE TABLE cur_data AS SELECT
                '2026-07-15'::DATE AS line_item_usage_start_date,
                '111222333444' AS line_item_usage_account_id,
                '999888777666' AS bill_payer_account_id,
                'AmazonEC2' AS line_item_product_code,
                'BoxUsage:m5.xlarge' AS line_item_usage_type,
                'i-0abc123def456789a' AS line_item_resource_id,
                42.50 AS line_item_unblended_cost,
                'us-east-1' AS product_region,
                'RunInstances' AS line_item_operation,
                'team-alpha' AS resource_tags_user_team,
                'production' AS resource_tags_user_environment
        """)
        # Add more rows
        con.execute("""
            INSERT INTO cur_data VALUES
            ('2026-07-16', '111222333444', '999888777666', 'AmazonS3',
             'TimedStorage-ByteHrs', 'my-bucket', 5.25, 'us-east-1',
             'GetObject', 'team-beta', 'staging')
        """)
        con.execute(f"COPY cur_data TO '{parquet_path.as_posix()}' (FORMAT PARQUET)")
        con.close()
        return cur_dir

    @pytest.fixture
    def workspace(self, tmp_path) -> Path:
        ws = tmp_path / "workspace"
        ws.mkdir()
        return ws

    def test_cur_export_produces_parquet(self, synthetic_cur, workspace):
        """CUR export produces valid Parquet with pseudonymized identifiers."""
        from kulshan.export.cur_export import export_cur
        from kulshan.pseudonym.engine import PseudonymizationEngine
        from kulshan.pseudonym.policy import PseudonymPolicy

        scope = EvidenceScope(from_date=date(2026, 7, 1), to_date=date(2026, 8, 1))
        policy = PseudonymPolicy(mode="consultant", tty_bypass=False, show_identifiers=False)
        engine = PseudonymizationEngine.create(workspace, policy)

        output_dir = workspace / "output" / "cur"
        result = export_cur(
            cur_path=str(synthetic_cur),
            scope=scope,
            engine=engine,
            output_dir=output_dir,
        )

        assert result.row_count == 2
        assert result.source_row_count == 2
        assert result.output_path.exists()

        # Verify no raw identifiers in output
        import duckdb
        con = duckdb.connect(":memory:")
        df = con.execute(
            f"SELECT * FROM read_parquet('{result.output_path.as_posix()}')"
        ).fetchdf()
        con.close()

        all_text = " ".join(str(v) for col in df.columns for v in df[col].astype(str))
        assert SYNTHETIC_ACCOUNT not in all_text
        assert "999888777666" not in all_text
        assert SYNTHETIC_RESOURCE not in all_text
        # Aliases should be present
        assert "acct_" in all_text or "res_" in all_text

    def test_cur_export_preserves_costs(self, synthetic_cur, workspace):
        """Financial values must be byte-identical after pseudonymization."""
        from kulshan.export.cur_export import export_cur
        from kulshan.pseudonym.engine import PseudonymizationEngine
        from kulshan.pseudonym.policy import PseudonymPolicy

        scope = EvidenceScope(from_date=date(2026, 7, 1), to_date=date(2026, 8, 1))
        policy = PseudonymPolicy(mode="consultant", tty_bypass=False, show_identifiers=False)
        engine = PseudonymizationEngine.create(workspace, policy)

        output_dir = workspace / "output2" / "cur"
        result = export_cur(str(synthetic_cur), scope, engine, output_dir)

        import duckdb
        con = duckdb.connect(":memory:")
        df = con.execute(
            f"SELECT line_item_unblended_cost FROM read_parquet('{result.output_path.as_posix()}')"
        ).fetchdf()
        con.close()

        costs = sorted(df["line_item_unblended_cost"].tolist())
        assert costs == [5.25, 42.50]

    def test_cur_export_blocks_unclassified(self, synthetic_cur, workspace):
        """Unclassified columns block export by default."""
        from kulshan.export.cur_export import ExportBlockedError, export_cur
        from kulshan.pseudonym.engine import PseudonymizationEngine
        from kulshan.pseudonym.policy import PseudonymPolicy

        # Add a column that will be unclassified
        import duckdb
        weird_cur = workspace / "weird_cur"
        weird_cur.mkdir()
        con = duckdb.connect(":memory:")
        con.execute("""
            CREATE TABLE t AS SELECT
                '2026-07-15'::DATE AS line_item_usage_start_date,
                '111222333444' AS line_item_usage_account_id,
                'AmazonEC2' AS line_item_product_code,
                'BoxUsage' AS line_item_usage_type,
                42.50 AS line_item_unblended_cost,
                'secret-data' AS totally_new_aws_column
        """)
        con.execute(f"COPY t TO '{(weird_cur / 'data.parquet').as_posix()}' (FORMAT PARQUET)")
        con.close()

        scope = EvidenceScope(from_date=date(2026, 7, 1), to_date=date(2026, 8, 1))
        policy = PseudonymPolicy(mode="consultant", tty_bypass=False, show_identifiers=False)
        engine = PseudonymizationEngine.create(workspace, policy)

        with pytest.raises(ExportBlockedError, match="unclassified"):
            export_cur(str(weird_cur), scope, engine, workspace / "out")

    def test_full_package_creation(self, synthetic_cur, workspace):
        """Full pipeline produces a valid ZIP with expected structure."""
        from kulshan.export.cur_export import export_cur
        from kulshan.export.gates import gate_integrity, gate_residual, gate_schema
        from kulshan.export.package import create_package
        from kulshan.pseudonym.engine import PseudonymizationEngine
        from kulshan.pseudonym.policy import PseudonymPolicy

        scope = EvidenceScope(from_date=date(2026, 7, 1), to_date=date(2026, 8, 1))
        policy = PseudonymPolicy(mode="consultant", tty_bypass=False, show_identifiers=False)
        engine = PseudonymizationEngine.create(workspace, policy)

        cur_dir = workspace / "pkg" / "cur"
        result = export_cur(str(synthetic_cur), scope, engine, cur_dir)

        # Run gates
        g1 = gate_schema(result.classification)
        assert g1.passed
        g2 = gate_integrity(result.source_row_count, result.row_count)
        assert g2.passed

        # Package
        zip_path = workspace / "test-export.zip"
        create_package(
            output_path=zip_path,
            cur_dir=cur_dir,
            ce_dir=None,
            scope=scope,
            classification=result.classification,
            gate_results=[{"gate": "schema", "passed": True}, {"gate": "integrity", "passed": True}],
            cur_row_count=result.row_count,
        )

        assert zip_path.exists()
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert "manifest.json" in names
            assert "privacy-report.json" in names
            assert "README.md" in names
            assert any(n.startswith("cur/") for n in names)

            # Verify manifest content
            manifest = json.loads(zf.read("manifest.json"))
            assert manifest["pseudonymization"]["bypass_available"] is False
            assert manifest["scope"]["from_date"] == "2026-07-01"

            # Verify no raw identifiers in any text file
            for name in names:
                if name.endswith(".json") or name.endswith(".md"):
                    content = zf.read(name).decode("utf-8")
                    assert SYNTHETIC_ACCOUNT not in content
                    assert "999888777666" not in content
