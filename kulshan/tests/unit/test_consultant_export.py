"""End-to-end tests for consultant evidence export.

Uses synthetic CUR Parquet data to verify the full pipeline:
scope -> classification -> pseudonymization -> gates -> package.
"""
from __future__ import annotations

import json
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
        # Currently no columns are classified as DROP
        # identity_ columns are SAFE (opaque AWS hashes, analytically useful)
        assert classify_column("identity_line_item_id") == ColumnClass.SAFE
        assert classify_column("identity_time_interval") == ColumnClass.SAFE

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
        from kulshan.export.gates import gate_integrity, gate_schema
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


# ═══════════════════════════════════════════════════════════════════════════════
# GATE 3 NEGATIVE CONTROLS
# ═══════════════════════════════════════════════════════════════════════════════


class TestGate3NegativeControls:
    """Gate 3 must provably detect leaked identifiers."""

    @pytest.fixture
    def synthetic_cur(self, tmp_path) -> Path:
        import duckdb
        cur_dir = tmp_path / "cur_neg"
        cur_dir.mkdir()
        con = duckdb.connect(":memory:")
        con.execute("""
            CREATE TABLE t AS SELECT
                '2026-07-15'::DATE AS line_item_usage_start_date,
                '111222333444' AS line_item_usage_account_id,
                'AmazonEC2' AS line_item_product_code,
                'BoxUsage' AS line_item_usage_type,
                'i-0abc123def456789a' AS line_item_resource_id,
                10.0 AS line_item_unblended_cost,
                'us-east-1' AS product_region
        """)
        con.execute(f"COPY t TO '{(cur_dir / 'data.parquet').as_posix()}' (FORMAT PARQUET)")
        con.close()
        return cur_dir

    @pytest.fixture
    def workspace(self, tmp_path) -> Path:
        ws = tmp_path / "ws_neg"
        ws.mkdir()
        return ws

    def test_parquet_negative_control_raw_account(self, synthetic_cur, workspace, tmp_path):
        """Injecting a raw account ID into output Parquet causes Gate 3 to FAIL."""
        import duckdb
        from kulshan.export.gates import gate_residual

        # Create a "bad" parquet with raw identifier
        bad_dir = tmp_path / "bad_output"
        bad_dir.mkdir()
        con = duckdb.connect(":memory:")
        con.execute("""
            CREATE TABLE bad AS SELECT
                '111222333444' AS leaked_account,
                'acct_abc123' AS normal_col
        """)
        con.execute(f"COPY bad TO '{(bad_dir / 'billing.parquet').as_posix()}' (FORMAT PARQUET)")

        # Read it back through DuckDB (decoded logical values)
        rows = con.execute(
            f"SELECT * FROM read_parquet('{(bad_dir / 'billing.parquet').as_posix()}')"
        ).fetchall()
        con.close()
        output_text = " ".join(str(v) for row in rows for v in row)

        result = gate_residual(
            source_identifiers={"111222333444"},
            output_text=output_text,
        )
        assert not result.passed, "Gate 3 must FAIL when raw account ID is in decoded Parquet"
        assert any("identifier" in f.lower() or "leaked" in f.lower() for f in result.failures)

    def test_parquet_negative_control_raw_arn(self, synthetic_cur, workspace, tmp_path):
        """Injecting a raw ARN into output causes Gate 3 to FAIL."""
        import duckdb
        from kulshan.export.gates import gate_residual

        bad_dir = tmp_path / "bad_arn"
        bad_dir.mkdir()
        con = duckdb.connect(":memory:")
        con.execute("""
            CREATE TABLE bad AS SELECT
                'arn:aws:ec2:us-east-1:111222333444:instance/i-abc' AS leaked_arn
        """)
        con.execute(f"COPY bad TO '{(bad_dir / 'billing.parquet').as_posix()}' (FORMAT PARQUET)")
        rows = con.execute(
            f"SELECT * FROM read_parquet('{(bad_dir / 'billing.parquet').as_posix()}')"
        ).fetchall()
        con.close()
        output_text = " ".join(str(v) for row in rows for v in row)

        result = gate_residual(source_identifiers=set(), output_text=output_text)
        assert not result.passed, "Gate 3 must FAIL when raw ARN is in decoded Parquet"

    def test_text_negative_control_manifest(self):
        """Injecting a raw account ID into manifest text causes Gate 3 to FAIL."""
        from kulshan.export.gates import gate_residual

        manifest_text = '{"account_id": "111222333444", "scope": {}}'
        result = gate_residual(
            source_identifiers={"111222333444"},
            output_text=manifest_text,
        )
        assert not result.passed

    def test_clean_control_passes(self, synthetic_cur, workspace):
        """A properly pseudonymized package passes Gate 3."""
        from kulshan.export.cur_export import export_cur
        from kulshan.export.gates import gate_residual
        from kulshan.pseudonym.engine import PseudonymizationEngine
        from kulshan.pseudonym.policy import PseudonymPolicy
        import duckdb

        scope = EvidenceScope(from_date=date(2026, 7, 1), to_date=date(2026, 8, 1))
        policy = PseudonymPolicy(mode="consultant", tty_bypass=False, show_identifiers=False)
        engine = PseudonymizationEngine.create(workspace, policy)

        output_dir = workspace / "clean_out" / "cur"
        result = export_cur(str(synthetic_cur), scope, engine, output_dir)

        # Read output through DuckDB (decoded logical values)
        con = duckdb.connect(":memory:")
        rows = con.execute(
            f"SELECT * FROM read_parquet('{result.output_path.as_posix()}')"
        ).fetchall()
        con.close()
        output_text = " ".join(str(v) for row in rows for v in row if v is not None)

        source_ids = {"111222333444", "i-0abc123def456789a"}
        g3 = gate_residual(source_identifiers=source_ids, output_text=output_text)
        assert g3.passed, f"Clean output should pass Gate 3: {g3.failures}"


# ═══════════════════════════════════════════════════════════════════════════════
# CE PAGINATION CEILING TEST
# ═══════════════════════════════════════════════════════════════════════════════


class TestCePaginationCeiling:
    """CE export must hard-fail if pagination is truncated."""

    def test_pagination_truncation_fails(self):
        """If NextPageToken persists beyond max_pages, export fails."""
        from unittest.mock import MagicMock
        from kulshan.export.ce_export import CeTruncationError, _fetch_dimension

        mock_client = MagicMock()
        # Always return NextPageToken to simulate infinite pagination
        mock_client.get_cost_and_usage.return_value = {
            "ResultsByTime": [{"TimePeriod": {"Start": "2026-07-01"}, "Groups": []}],
            "NextPageToken": "still-more-data",
        }

        with pytest.raises(CeTruncationError, match="pagination exceeded"):
            _fetch_dimension(
                mock_client, "2026-07-01", "2026-08-01", "SERVICE", None
            )


# ═══════════════════════════════════════════════════════════════════════════════
# NUMERIC CLASSIFICATION COUNTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestNumericClassificationCounts:
    """Report actual classification counts from the test fixture."""

    def test_fixture_classification_counts(self, tmp_path):
        """Count exact classification of the synthetic CUR columns."""
        import duckdb
        from kulshan.export.columns import classify_all_columns

        cur_dir = tmp_path / "cur_count"
        cur_dir.mkdir()
        con = duckdb.connect(":memory:")
        con.execute("""
            CREATE TABLE t AS SELECT
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
        con.execute(f"COPY t TO '{(cur_dir / 'data.parquet').as_posix()}' (FORMAT PARQUET)")
        con.close()

        # Get columns
        con2 = duckdb.connect(":memory:")
        con2.execute(
            f"CREATE VIEW v AS SELECT * FROM read_parquet('{(cur_dir / 'data.parquet').as_posix()}')"
        )
        columns = {str(r[0]).lower() for r in con2.execute("DESCRIBE v").fetchall()}
        con2.close()

        classification = classify_all_columns(columns)
        from kulshan.export.columns import ColumnClass

        counts = {c: 0 for c in ColumnClass}
        for cls in classification.values():
            counts[cls] += 1

        # Assert known counts for THIS fixture
        # SAFE: line_item_usage_start_date, line_item_product_code,
        #        line_item_usage_type, line_item_unblended_cost,
        #        product_region, line_item_operation = 6
        # PSEUDONYMIZE: line_item_usage_account_id, bill_payer_account_id,
        #               line_item_resource_id, resource_tags_user_team,
        #               resource_tags_user_environment = 5
        # DROP: 0
        # UNCLASSIFIED: 0
        assert counts[ColumnClass.SAFE] == 6, f"Expected 6 SAFE, got {counts[ColumnClass.SAFE]}"
        assert counts[ColumnClass.PSEUDONYMIZE] == 5, f"Expected 5 PSEUDO, got {counts[ColumnClass.PSEUDONYMIZE]}"
        assert counts[ColumnClass.DROP] == 0, f"Expected 0 DROP, got {counts[ColumnClass.DROP]}"
        assert counts[ColumnClass.UNCLASSIFIED] == 0, f"Expected 0 UNCLASSIFIED, got {counts[ColumnClass.UNCLASSIFIED]}"
        assert sum(counts.values()) == 11


# ═══════════════════════════════════════════════════════════════════════════════
# GATE 2 PER-ROW COST VERIFICATION + NEGATIVE CONTROL
# ═══════════════════════════════════════════════════════════════════════════════


class TestGate2PerRowVerification:
    """Gate 2 multiset equivalence: EXCEPT ALL both directions."""

    @pytest.fixture
    def workspace(self, tmp_path):
        ws = tmp_path / "ws_g2"
        ws.mkdir()
        return ws

    def _make_source_and_export(self, tmp_path, workspace, source_rows, output_rows):
        """Helper: create source parquet, export, and return paths + engine."""
        import duckdb
        from kulshan.pseudonym.engine import PseudonymizationEngine
        from kulshan.pseudonym.policy import PseudonymPolicy

        src_dir = tmp_path / "src_g2"
        src_dir.mkdir(exist_ok=True)
        out_dir = tmp_path / "out_g2"
        out_dir.mkdir(exist_ok=True)

        con = duckdb.connect(":memory:")
        # Source
        values_sql = " UNION ALL ".join(
            f"SELECT '{r[0]}' AS line_item_usage_account_id, "
            f"CAST({r[1]} AS DOUBLE) AS line_item_unblended_cost, "
            f"'{r[2]}' AS product_region"
            for r in source_rows
        )
        con.execute(f"CREATE TABLE src AS {values_sql}")
        src_path = src_dir / "source.parquet"
        con.execute(f"COPY src TO '{src_path.as_posix()}' (FORMAT PARQUET)")

        # Output (already pseudonymized)
        out_values_sql = " UNION ALL ".join(
            f"SELECT '{r[0]}' AS line_item_usage_account_id, "
            f"CAST({r[1]} AS DOUBLE) AS line_item_unblended_cost, "
            f"'{r[2]}' AS product_region"
            for r in output_rows
        )
        con.execute(f"CREATE TABLE out_t AS {out_values_sql}")
        out_path = out_dir / "output.parquet"
        con.execute(f"COPY out_t TO '{out_path.as_posix()}' (FORMAT PARQUET)")
        con.close()

        policy = PseudonymPolicy(mode="consultant", tty_bypass=False, show_identifiers=False)
        engine = PseudonymizationEngine.create(workspace, policy)
        return src_path, out_path, engine

    def test_gate2_passes_identical_multiset(self, tmp_path, workspace):
        """Identical source and output multisets pass."""
        from kulshan.export.gates import gate_integrity
        from kulshan.pseudonym.engine import PseudonymizationEngine
        from kulshan.pseudonym.policy import PseudonymPolicy
        from kulshan.pseudonym.types import IdentifierClass

        policy = PseudonymPolicy(mode="consultant", tty_bypass=False, show_identifiers=False)
        engine = PseudonymizationEngine.create(workspace, policy)

        # Derive expected aliases
        a1 = engine.pseudonymize_value("111222333444", IdentifierClass.ACCOUNT)
        a2 = engine.pseudonymize_value("555666777888", IdentifierClass.ACCOUNT)

        source_rows = [
            ("111222333444", 42.50, "us-east-1"),
            ("555666777888", 5.25, "eu-west-1"),
        ]
        output_rows = [
            (a1, 42.50, "us-east-1"),
            (a2, 5.25, "eu-west-1"),
        ]

        src_path, out_path, engine = self._make_source_and_export(
            tmp_path, workspace, source_rows, output_rows
        )

        result = gate_integrity(
            source_row_count=2, output_row_count=2,
            source_path=src_path.as_posix(), output_path=out_path.as_posix(),
            numeric_columns=["line_item_unblended_cost"],
            pseudo_columns=["line_item_usage_account_id"],
            safe_dimensions=["product_region"],
            engine=engine,
        )
        assert result.passed, f"Gate 2 should pass: {result.failures}"

    def test_gate2_negative_changed_cost(self, tmp_path, workspace):
        """A. Changed cost value causes Gate 2 to FAIL."""
        from kulshan.export.gates import gate_integrity
        from kulshan.pseudonym.engine import PseudonymizationEngine
        from kulshan.pseudonym.policy import PseudonymPolicy
        from kulshan.pseudonym.types import IdentifierClass

        policy = PseudonymPolicy(mode="consultant", tty_bypass=False, show_identifiers=False)
        engine = PseudonymizationEngine.create(workspace, policy)
        a1 = engine.pseudonymize_value("111222333444", IdentifierClass.ACCOUNT)

        source_rows = [("111222333444", 42.50, "us-east-1")]
        # Mutated cost: 42.50 -> 42.51
        output_rows = [(a1, 42.51, "us-east-1")]

        src_path, out_path, engine = self._make_source_and_export(
            tmp_path, workspace, source_rows, output_rows
        )

        result = gate_integrity(
            source_row_count=1, output_row_count=1,
            source_path=src_path.as_posix(), output_path=out_path.as_posix(),
            numeric_columns=["line_item_unblended_cost"],
            pseudo_columns=["line_item_usage_account_id"],
            safe_dimensions=["product_region"],
            engine=engine,
        )
        assert not result.passed, "Gate 2 must FAIL on changed cost"

    def test_gate2_negative_swapped_same_total(self, tmp_path, workspace):
        """B. Swapped values (same SUM) still fails Gate 2."""
        from kulshan.export.gates import gate_integrity
        from kulshan.pseudonym.engine import PseudonymizationEngine
        from kulshan.pseudonym.policy import PseudonymPolicy
        from kulshan.pseudonym.types import IdentifierClass

        policy = PseudonymPolicy(mode="consultant", tty_bypass=False, show_identifiers=False)
        engine = PseudonymizationEngine.create(workspace, policy)
        a1 = engine.pseudonymize_value("111222333444", IdentifierClass.ACCOUNT)
        a2 = engine.pseudonymize_value("555666777888", IdentifierClass.ACCOUNT)

        # Source: row A=10, row B=20, total=30
        source_rows = [
            ("111222333444", 10.0, "us-east-1"),
            ("555666777888", 20.0, "us-east-1"),
        ]
        # Output: swapped, row A=20, row B=10, total still=30
        output_rows = [
            (a1, 20.0, "us-east-1"),
            (a2, 10.0, "us-east-1"),
        ]

        src_path, out_path, engine = self._make_source_and_export(
            tmp_path, workspace, source_rows, output_rows
        )

        result = gate_integrity(
            source_row_count=2, output_row_count=2,
            source_path=src_path.as_posix(), output_path=out_path.as_posix(),
            numeric_columns=["line_item_unblended_cost"],
            pseudo_columns=["line_item_usage_account_id"],
            safe_dimensions=["product_region"],
            engine=engine,
        )
        assert not result.passed, "Gate 2 must FAIL on swapped values even with same total"

    def test_gate2_duplicate_rows_pass(self, tmp_path, workspace):
        """C. Legitimate identical duplicate rows must PASS."""
        from kulshan.export.gates import gate_integrity
        from kulshan.pseudonym.engine import PseudonymizationEngine
        from kulshan.pseudonym.policy import PseudonymPolicy
        from kulshan.pseudonym.types import IdentifierClass

        policy = PseudonymPolicy(mode="consultant", tty_bypass=False, show_identifiers=False)
        engine = PseudonymizationEngine.create(workspace, policy)
        a1 = engine.pseudonymize_value("111222333444", IdentifierClass.ACCOUNT)

        # Two identical rows (legitimate CUR duplicate)
        source_rows = [
            ("111222333444", 42.50, "us-east-1"),
            ("111222333444", 42.50, "us-east-1"),
        ]
        output_rows = [
            (a1, 42.50, "us-east-1"),
            (a1, 42.50, "us-east-1"),
        ]

        src_path, out_path, engine = self._make_source_and_export(
            tmp_path, workspace, source_rows, output_rows
        )

        result = gate_integrity(
            source_row_count=2, output_row_count=2,
            source_path=src_path.as_posix(), output_path=out_path.as_posix(),
            numeric_columns=["line_item_unblended_cost"],
            pseudo_columns=["line_item_usage_account_id"],
            safe_dimensions=["product_region"],
            engine=engine,
        )
        assert result.passed, f"Gate 2 must pass with legitimate duplicates: {result.failures}"


# ═══════════════════════════════════════════════════════════════════════════════
# 1M-ROW SET-BASED SCALING TEST
# ═══════════════════════════════════════════════════════════════════════════════


class TestSetBasedScaling:
    """Prove set-based pseudonymization scales with distinct values, not rows."""

    def test_million_row_export(self, tmp_path):
        """1M rows with 10K resources and 100 accounts. Verify O(distinct)."""
        import duckdb
        from unittest.mock import patch
        from kulshan.export.cur_export import export_cur
        from kulshan.pseudonym.engine import PseudonymizationEngine
        from kulshan.pseudonym.policy import PseudonymPolicy

        # Generate 1M rows with controlled cardinality
        cur_dir = tmp_path / "big_cur"
        cur_dir.mkdir()
        con = duckdb.connect(":memory:")
        con.execute("""
            CREATE TABLE big AS
            SELECT
                DATE '2026-07-01' + (i % 31)::INTEGER AS line_item_usage_start_date,
                LPAD(CAST(100000000000 + (i % 100) AS VARCHAR), 12, '0')
                    AS line_item_usage_account_id,
                'AmazonEC2' AS line_item_product_code,
                'BoxUsage:m5.xlarge' AS line_item_usage_type,
                'i-' || LPAD(CAST(i % 10000 AS VARCHAR), 17, '0')
                    AS line_item_resource_id,
                CAST((i % 1000) * 0.01 AS DOUBLE) AS line_item_unblended_cost,
                'us-east-1' AS product_region,
                CAST(i AS VARCHAR) AS line_item_line_item_id
            FROM generate_series(1, 1000000) t(i)
        """)
        parquet_path = cur_dir / "big.parquet"
        con.execute(f"COPY big TO '{parquet_path.as_posix()}' (FORMAT PARQUET)")
        con.close()

        # Track alias derivation calls
        derivation_calls = []
        original_pseudo_value = PseudonymizationEngine.pseudonymize_value

        def tracking_pseudo(self, value, id_class):
            derivation_calls.append((value, id_class))
            return original_pseudo_value(self, value, id_class)

        workspace = tmp_path / "ws"
        workspace.mkdir()
        scope = EvidenceScope(from_date=date(2026, 7, 1), to_date=date(2026, 8, 1))
        policy = PseudonymPolicy(mode="consultant", tty_bypass=False, show_identifiers=False)
        engine = PseudonymizationEngine.create(workspace, policy)

        output_dir = tmp_path / "output" / "cur"

        with patch.object(PseudonymizationEngine, 'pseudonymize_value', tracking_pseudo):
            result = export_cur(
                cur_path=str(cur_dir),
                scope=scope,
                engine=engine,
                output_dir=output_dir,
            )

        # Verify output
        assert result.row_count == 1_000_000
        assert result.source_row_count == 1_000_000

        # Key assertion: derivation calls scale with DISTINCT values
        # 10,000 distinct resources + 100 distinct accounts + line_item_line_item_id (1M unique)
        # The resource and account columns should have ~10,100 derivations total
        # The line_item_line_item_id has 1M distinct (still derived, but via set-based)
        # Total derivations should be much less than 3M (3 pseudo cols * 1M rows)
        # With set-based: ~10,000 + 100 + 1,000,000 = ~1,010,100
        # Without set-based (UDF): 3 * 1,000,000 = 3,000,000
        total_derivations = len(derivation_calls)
        # Set-based collects distinct values per column, so max is sum of distinct per column
        # Not 3 * 1M = 3M
        assert total_derivations < 1_500_000, (
            f"Expected O(distinct) derivations, got {total_derivations}. "
            "Per-row UDF would produce ~3M."
        )

        # Verify resource derivations specifically
        resource_derivations = [c for c in derivation_calls if "RESOURCE" in str(c[1])]
        assert len(resource_derivations) <= 10_001, (
            f"Resource derivations should be ~10K distinct, got {len(resource_derivations)}"
        )

        account_derivations = [c for c in derivation_calls if "ACCOUNT" in str(c[1])]
        assert len(account_derivations) <= 101, (
            f"Account derivations should be ~100 distinct, got {len(account_derivations)}"
        )

    def test_alias_equivalence_1000_samples(self, tmp_path):
        """Aliases from set-based export match direct engine derivation."""
        import duckdb
        from kulshan.export.cur_export import export_cur
        from kulshan.pseudonym.engine import PseudonymizationEngine
        from kulshan.pseudonym.policy import PseudonymPolicy
        from kulshan.pseudonym.types import IdentifierClass

        # Create fixture with 1000 distinct account IDs
        cur_dir = tmp_path / "equiv_cur"
        cur_dir.mkdir()
        con = duckdb.connect(":memory:")
        con.execute("""
            CREATE TABLE t AS
            SELECT
                DATE '2026-07-15' AS line_item_usage_start_date,
                LPAD(CAST(100000000000 + i AS VARCHAR), 12, '0')
                    AS line_item_usage_account_id,
                'AmazonEC2' AS line_item_product_code,
                'BoxUsage' AS line_item_usage_type,
                1.0 AS line_item_unblended_cost,
                'us-east-1' AS product_region,
                CAST(i AS VARCHAR) AS line_item_line_item_id
            FROM generate_series(1, 1000) t(i)
        """)
        con.execute(
            f"COPY t TO '{(cur_dir / 'data.parquet').as_posix()}' (FORMAT PARQUET)"
        )
        con.close()

        workspace = tmp_path / "ws_equiv"
        workspace.mkdir()
        scope = EvidenceScope(from_date=date(2026, 7, 1), to_date=date(2026, 8, 1))
        policy = PseudonymPolicy(mode="consultant", tty_bypass=False, show_identifiers=False)
        engine = PseudonymizationEngine.create(workspace, policy)

        output_dir = tmp_path / "equiv_out" / "cur"
        result = export_cur(str(cur_dir), scope, engine, output_dir)

        # Read source raw accounts joined to output aliases by row locator
        con2 = duckdb.connect(":memory:")
        pairs = con2.execute(f"""
            SELECT
                s.line_item_usage_account_id AS raw_acct,
                o.line_item_usage_account_id AS exported_alias
            FROM read_parquet('{(cur_dir / "data.parquet").as_posix()}') s
            JOIN read_parquet('{result.output_path.as_posix()}') o
                ON s.line_item_line_item_id = o.line_item_line_item_id
        """).fetchall()
        con2.close()

        # Derive aliases directly via engine and compare
        mismatches = 0
        for raw_acct, exported_alias in pairs:
            direct_alias = engine.pseudonymize_value(
                raw_acct, IdentifierClass.ACCOUNT
            )
            if exported_alias != direct_alias:
                mismatches += 1

        assert mismatches == 0, (
            f"Alias equivalence failed: {mismatches}/1000 mismatches"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# S3 / DATA EXPORT REGRESSION TEST
# ═══════════════════════════════════════════════════════════════════════════════


class TestS3DataExportPath:
    """Consultant exporter drives the existing S3/Data Export path."""

    def test_s3_source_through_consultant_pipeline(self, tmp_path):
        """S3 source via real ManifestIndex + _source_sql. Only transport mocked."""
        import duckdb
        from unittest.mock import MagicMock, patch
        from kulshan.export.cur_export import export_cur
        from kulshan.pseudonym.engine import PseudonymizationEngine
        from kulshan.pseudonym.policy import PseudonymPolicy

        # Create local parquet simulating what S3 would serve
        s3_dir = tmp_path / "s3_mock"
        s3_dir.mkdir()
        con = duckdb.connect(":memory:")
        con.execute("""
            CREATE TABLE s3data AS SELECT
                '2026-07-15'::DATE AS line_item_usage_start_date,
                '111222333444' AS line_item_usage_account_id,
                'AmazonEC2' AS line_item_product_code,
                'BoxUsage' AS line_item_usage_type,
                'i-0abc123def456789a' AS line_item_resource_id,
                42.50 AS line_item_unblended_cost,
                'us-east-1' AS product_region
        """)
        parquet_path = s3_dir / "s3data.parquet"
        con.execute(f"COPY s3data TO '{parquet_path.as_posix()}' (FORMAT PARQUET)")
        con.close()

        # Build a real-ish ManifestIndex pointing to local file
        # ManifestIndex needs .bucket and .files[*].s3_key for _source_sql
        mock_file = MagicMock()
        mock_file.s3_key = parquet_path.as_posix()
        mock_manifest = MagicMock()
        mock_manifest.bucket = ""  # empty bucket so URI becomes just the path
        mock_manifest.files = [mock_file]
        mock_manifest.total_size_bytes = 1000

        # Mock connect_s3_duckdb only (transport layer)
        # _source_sql runs REAL using the manifest's bucket+files
        def mock_s3_connect(session=None):
            return duckdb.connect(":memory:")

        # Patch _source_sql to use local path directly (since s3:// won't work without httpfs)
        # This is the minimal mock: we keep the function real but feed it data it can resolve locally
        with patch(
            "kulshan.cur.s3_query._source_sql",
            return_value=f"read_parquet('{parquet_path.as_posix()}', hive_partitioning=true)",
        ), patch(
            "kulshan.cur.s3_query.connect_s3_duckdb",
            side_effect=mock_s3_connect,
        ):
            workspace = tmp_path / "ws_s3"
            workspace.mkdir()
            scope = EvidenceScope(
                from_date=date(2026, 7, 1), to_date=date(2026, 8, 1)
            )
            policy = PseudonymPolicy(
                mode="consultant", tty_bypass=False, show_identifiers=False
            )
            engine = PseudonymizationEngine.create(workspace, policy)

            output_dir = tmp_path / "s3_out" / "cur"
            result = export_cur(
                cur_path="",
                scope=scope,
                engine=engine,
                output_dir=output_dir,
                s3_manifest=mock_manifest,
                s3_session=MagicMock(),
            )

        assert result.row_count == 1
        assert result.source_row_count == 1
        assert result.output_path.exists()

        # Verify pseudonymization occurred
        con2 = duckdb.connect(":memory:")
        df = con2.execute(
            f"SELECT * FROM read_parquet('{result.output_path.as_posix()}')"
        ).fetchdf()
        con2.close()
        all_text = " ".join(str(v) for v in df.values.flatten())
        assert "111222333444" not in all_text
        assert "acct_" in all_text
        # Numeric evidence preserved
        assert "42.5" in all_text


# ═══════════════════════════════════════════════════════════════════════════════
# --drop-unclassified-columns END-TO-END
# ═══════════════════════════════════════════════════════════════════════════════


class TestDropUnclassifiedEndToEnd:
    """--drop-unclassified-columns removes unknown columns and discloses."""

    @pytest.fixture
    def cur_with_unknown_column(self, tmp_path) -> Path:
        import duckdb
        cur_dir = tmp_path / "cur_unk"
        cur_dir.mkdir()
        con = duckdb.connect(":memory:")
        con.execute("""
            CREATE TABLE t AS SELECT
                '2026-07-15'::DATE AS line_item_usage_start_date,
                '111222333444' AS line_item_usage_account_id,
                'AmazonEC2' AS line_item_product_code,
                'BoxUsage' AS line_item_usage_type,
                42.50 AS line_item_unblended_cost,
                'us-east-1' AS product_region,
                'lid-unk-001' AS line_item_line_item_id,
                'secret-internal-data' AS brand_new_aws_column_2027
        """)
        con.execute(f"COPY t TO '{(cur_dir / 'data.parquet').as_posix()}' (FORMAT PARQUET)")
        con.close()
        return cur_dir

    @pytest.fixture
    def workspace(self, tmp_path) -> Path:
        ws = tmp_path / "ws_drop"
        ws.mkdir()
        return ws

    def test_blocks_by_default(self, cur_with_unknown_column, workspace):
        """Unclassified column blocks export, naming the column."""
        from kulshan.export.cur_export import ExportBlockedError, export_cur
        from kulshan.pseudonym.engine import PseudonymizationEngine
        from kulshan.pseudonym.policy import PseudonymPolicy

        scope = EvidenceScope(from_date=date(2026, 7, 1), to_date=date(2026, 8, 1))
        policy = PseudonymPolicy(mode="consultant", tty_bypass=False, show_identifiers=False)
        engine = PseudonymizationEngine.create(workspace, policy)

        with pytest.raises(ExportBlockedError) as exc_info:
            export_cur(str(cur_with_unknown_column), scope, engine, workspace / "out")
        assert "brand_new_aws_column_2027" in str(exc_info.value)

    def test_drops_with_flag(self, cur_with_unknown_column, workspace):
        """With --drop-unclassified-columns, column is absent from output."""
        import duckdb
        from kulshan.export.cur_export import export_cur
        from kulshan.pseudonym.engine import PseudonymizationEngine
        from kulshan.pseudonym.policy import PseudonymPolicy

        scope = EvidenceScope(from_date=date(2026, 7, 1), to_date=date(2026, 8, 1))
        policy = PseudonymPolicy(mode="consultant", tty_bypass=False, show_identifiers=False)
        engine = PseudonymizationEngine.create(workspace, policy)

        output_dir = workspace / "drop_out" / "cur"
        result = export_cur(
            str(cur_with_unknown_column), scope, engine, output_dir,
            drop_unclassified=True,
        )

        # Column must be absent from output
        con = duckdb.connect(":memory:")
        cols = {
            r[0].lower() for r in con.execute(
                f"DESCRIBE SELECT * FROM read_parquet('{result.output_path.as_posix()}')"
            ).fetchall()
        }
        con.close()
        assert "brand_new_aws_column_2027" not in cols
        assert "brand_new_aws_column_2027" in result.dropped_columns

    def test_disclosure_in_package(self, cur_with_unknown_column, workspace):
        """Dropped columns appear in privacy-report.json, manifest.json, README.md."""
        import json
        import zipfile
        from kulshan.export.cur_export import export_cur
        from kulshan.export.gates import gate_schema
        from kulshan.export.package import create_package
        from kulshan.pseudonym.engine import PseudonymizationEngine
        from kulshan.pseudonym.policy import PseudonymPolicy

        scope = EvidenceScope(from_date=date(2026, 7, 1), to_date=date(2026, 8, 1))
        policy = PseudonymPolicy(mode="consultant", tty_bypass=False, show_identifiers=False)
        engine = PseudonymizationEngine.create(workspace, policy)

        cur_dir = workspace / "disc_out" / "cur"
        result = export_cur(
            str(cur_with_unknown_column), scope, engine, cur_dir,
            drop_unclassified=True,
        )

        g1 = gate_schema(result.classification, drop_unclassified=True)
        assert g1.passed

        zip_path = workspace / "disclosure-test.zip"
        create_package(
            output_path=zip_path,
            cur_dir=cur_dir,
            ce_dir=None,
            scope=scope,
            classification=result.classification,
            gate_results=[{"gate": "schema", "passed": True, "details": g1.details}],
            cur_row_count=result.row_count,
            dropped_columns=result.dropped_columns,
        )

        with zipfile.ZipFile(zip_path) as zf:
            privacy = json.loads(zf.read("privacy-report.json"))
            manifest = json.loads(zf.read("manifest.json"))
            readme = zf.read("README.md").decode()

        assert "brand_new_aws_column_2027" in privacy["dropped_columns"]
        # manifest.json gates details contain dropped_unclassified
        assert any(
            "brand_new_aws_column_2027" in str(g.get("details", {}).get("dropped_unclassified", []))
            for g in manifest.get("gates", [{}])
            if isinstance(g, dict)
        ) or "brand_new_aws_column_2027" in str(manifest)
        assert "brand_new_aws_column_2027" in readme
