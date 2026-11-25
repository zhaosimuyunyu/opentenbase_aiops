import re
import hmac
import hashlib
import json
import uuid
from copy import copy
from time import sleep
from datetime import datetime, timezone

from psycopg2 import Error, sql
from psycopg2.extras import Json
from ..collectors.readonly_health import stale_statistics_nodes
from ..security.permissions import OperationRegistry
from ..utils.config import Config
from ..utils.db_connector import OpenTenBaseConnector
from ..utils.operations_store import OperationsStore


ALLOWED_OPERATIONS = {"analyze_table"}


def _table_name(value):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?", value or ""):
        raise ValueError("Only a simple schema-qualified table name is allowed")
    return value


def has_repair_identity(evidence):
    identity = evidence.get("database_identity") or {}
    nodes = evidence.get("nodes") or []
    return bool(
        identity.get("system_identifier") and identity.get("database")
        and nodes and all(node.get("node_name") and node.get("relation_oid") for node in nodes)
    )


def _proposal_fingerprint(operation, parameters, audit_id, finding):
    payload = json.dumps(
        {"operation": operation, "parameters": parameters, "audit_id": audit_id,
         "finding": finding},
        sort_keys=True, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class RepairWorkflow:
    def __init__(self, config=None):
        self.config = config or Config()

    def _ensure_schema(self, kb):
        with kb.conn, kb.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    (SELECT count(*) FROM pg_catalog.pg_attribute
                     WHERE attrelid = to_regclass('repair_requests')
                       AND attname IN ('audit_id', 'finding', 'manual_review', 'agent_review')
                       AND NOT attisdropped),
                    to_regclass('repair_request_events') IS NOT NULL
            """)
            columns = cur.fetchone()
            if columns and columns[0] == 4 and columns[1]:
                return
            cur.execute("SELECT pg_advisory_xact_lock(hashtext('aiops.repair_requests.schema'))")
            cur.execute("""CREATE TABLE IF NOT EXISTS repair_requests(
                request_id text primary key, operation text not null, parameters jsonb not null,
                evidence jsonb not null, reason text not null, status text not null default 'pending',
                created_at timestamptz default now(), approved_at timestamptz, approved_by text,
                result jsonb, audit_id text, finding jsonb)""")
            cur.execute("ALTER TABLE repair_requests ADD COLUMN IF NOT EXISTS audit_id text")
            cur.execute("ALTER TABLE repair_requests ADD COLUMN IF NOT EXISTS finding jsonb")
            cur.execute("ALTER TABLE repair_requests ADD COLUMN IF NOT EXISTS manual_review jsonb")
            cur.execute("ALTER TABLE repair_requests ADD COLUMN IF NOT EXISTS agent_review jsonb")
            cur.execute("""CREATE TABLE IF NOT EXISTS repair_request_events(
                event_id bigserial primary key,
                request_id text not null,
                event_type text not null,
                actor text,
                status text,
                event_data jsonb not null default '{}'::jsonb,
                created_at timestamptz not null default now()
            )""")
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_repair_request_events_request "
                "ON repair_request_events(request_id, event_id)"
            )

    @staticmethod
    def _record_event(cursor, request_id, event_type, actor=None, status=None, event_data=None):
        cursor.execute(
            "INSERT INTO repair_request_events(request_id,event_type,actor,status,event_data) "
            "VALUES(%s,%s,%s,%s,%s)",
            (request_id, event_type, actor, status, Json(event_data or {})),
        )

    @staticmethod
    def _read_data_node_stats(connection, schema_name, table_name, execution_user=None):
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = '2500ms'")
            cursor.execute("SET LOCAL lock_timeout = '750ms'")
            cursor.execute("SELECT node_name FROM pgxc_node WHERE node_type='D'")
            data_nodes = [row[0] for row in cursor.fetchall()]
        connection.rollback()
        if not data_nodes:
            raise ValueError("No OpenTenBase data nodes are registered")

        qualified_name = sql.Identifier(schema_name, table_name).as_string(connection)
        remote_query = sql.SQL(
            "SELECT pg_stat_get_live_tuples(c.oid), pg_stat_get_mod_since_analyze(c.oid), "
            "pg_stat_get_last_analyze_time(c.oid), c.oid, "
            "pg_catalog.pg_get_userbyid(c.relowner), pg_catalog.pg_get_userbyid(d.datdba), "
            "({} IS NOT NULL AND ({} IN (pg_catalog.pg_get_userbyid(c.relowner), "
            "pg_catalog.pg_get_userbyid(d.datdba)))) "
            "FROM pg_catalog.pg_class c CROSS JOIN pg_catalog.pg_database d "
            "WHERE c.oid = pg_catalog.to_regclass({}) AND c.relkind IN ('r', 'p') "
            "AND d.datname = current_database()"
        ).format(
            sql.Literal(execution_user), sql.Literal(execution_user),
            sql.Literal(qualified_name),
        ).as_string(connection)
        per_node = []
        for node_name in data_nodes:
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = '2500ms'")
                cursor.execute("SET LOCAL lock_timeout = '750ms'")
                cursor.execute(
                    sql.SQL("EXECUTE DIRECT ON ({}) %s").format(sql.Identifier(node_name)),
                    (remote_query,),
                )
                stats = cursor.fetchone()
            connection.rollback()
            if stats:
                per_node.append({
                    "node_name": node_name,
                    "live_tuples": stats[0] or 0,
                    "modifications_since_analyze": stats[1] or 0,
                    "last_analyze": stats[2],
                    "relation_oid": stats[3],
                    "table_owner": stats[4],
                    "database_owner": stats[5],
                    "execution_user_is_owner": stats[6],
                })
        if not per_node:
            raise ValueError("Table statistics are unavailable on all OpenTenBase data nodes")
        return {
            "live_tuples": sum(node["live_tuples"] for node in per_node),
            "modifications_since_analyze": sum(
                node["modifications_since_analyze"] for node in per_node
            ),
            "nodes": per_node,
        }

    @staticmethod
    def _require_analyze_ownership(nodes):
        unauthorized_nodes = [
            item["node_name"] for item in nodes
            if item.get("execution_user_is_owner") is not True
        ]
        if unauthorized_nodes:
            raise ValueError(
                "Configured repair role is neither table nor database owner on data nodes: "
                + ", ".join(unauthorized_nodes)
            )

    @staticmethod
    def _repair_function_available(connection, schema_name, function_name):
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT procedure.prosecdef,
                          pg_catalog.has_function_privilege(
                              current_user,
                              procedure.oid,
                              'EXECUTE'
                          )
                   FROM pg_catalog.pg_proc AS procedure
                   JOIN pg_catalog.pg_namespace AS namespace
                     ON namespace.oid = procedure.pronamespace
                   WHERE namespace.nspname=%s AND procedure.proname=%s
                     AND procedure.pronargs=2
                     AND procedure.proargtypes='25 25'::oidvector""",
                (schema_name, function_name),
            )
            row = cursor.fetchone()
        connection.rollback()
        return bool(row and row[0] and row[1])

    @staticmethod
    def _repair_target_allowed(connection, schema_name, function_name, target_schema, target_table):
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("SELECT {}.{}(%s, %s)").format(
                    sql.Identifier(schema_name), sql.Identifier(function_name),
                ),
                (target_schema, target_table),
            )
            allowed = cursor.fetchone()[0]
        connection.rollback()
        return allowed is True

    def _preflight_analyze_target(self, table, observation):
        repair_user = self.config.AIOPS_REPAIR_DB_USER.strip()
        if not repair_user or repair_user == self.config.DB_USER:
            raise ValueError("Configure a dedicated AIOPS_REPAIR_DB_USER before creating repair proposals")
        repair_config = copy(self.config)
        repair_config.DB_USER = repair_user
        repair_config.DB_PASSWORD = self.config.AIOPS_REPAIR_DB_PASSWORD
        connector = OpenTenBaseConnector(repair_config)
        try:
            connection = connector.connect()
            connection.set_session(readonly=True, autocommit=False)
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = '5s'")
                cursor.execute("SET LOCAL lock_timeout = '1s'")
                cursor.execute(
                    "SELECT system_identifier::text, current_database(), session_user, "
                    "(SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname=current_user) "
                    "FROM pg_catalog.pg_control_system()"
                )
                identity = cursor.fetchone()
            connection.rollback()
            audited_identity = observation.get("database_identity") or {}
            if identity is None or identity[:2] != (
                audited_identity.get("system_identifier"), audited_identity.get("database")
            ):
                raise ValueError("Repair account connection does not match the audited database")
            if identity[2] != repair_user or identity[3] is not False:
                raise ValueError("Repair proposals require the configured dedicated non-superuser account")
            schema_name, table_name = table.split(".", 1)
            stats = self._read_data_node_stats(
                connection, schema_name, table_name, execution_user=repair_user
            )
            audited_relations = {
                item["node_name"]: item.get("relation_oid")
                for item in observation.get("nodes", [])
            }
            current_relations = {
                item["node_name"]: item["relation_oid"] for item in stats["nodes"]
            }
            if not audited_relations or audited_relations != current_relations:
                raise ValueError("Audited table identity or data-node coverage changed; rerun the health audit")
            function_enabled = (
                self.config.AIOPS_REPAIR_FUNCTION_ENABLED
                and self._repair_function_available(
                    connection,
                    self.config.AIOPS_REPAIR_FUNCTION_SCHEMA,
                    self.config.AIOPS_REPAIR_FUNCTION_NAME,
                )
            )
            if not function_enabled:
                self._require_analyze_ownership(stats["nodes"])
            elif not self._repair_target_allowed(
                connection,
                self.config.AIOPS_REPAIR_FUNCTION_SCHEMA,
                "is_analyze_target_allowed",
                schema_name,
                table_name,
            ):
                raise ValueError("Repair target is not present in the administrator allowlist")
            stale_nodes = stale_statistics_nodes(stats["nodes"])
            if not stale_nodes:
                raise ValueError("The original ANALYZE finding is no longer present")
        finally:
            connector.close()

    def create_request(self, operation, parameters, evidence, reason, audit_id=None, finding=None):
        if operation not in ALLOWED_OPERATIONS:
            raise ValueError("Operation is not enabled for execution")
        if operation == "analyze_table" and (not audit_id or not finding):
            raise ValueError("ANALYZE requests must reference a persisted audit finding")
        params = dict(parameters or {})
        params["table"] = _table_name(params.get("table"))
        observation = finding.get("evidence") or {}
        if finding.get("check") != "stale_table_statistics" or not has_repair_identity(observation):
            raise ValueError("Repair requires a verified table statistics finding")
        if params["table"] != f"{observation.get('schema')}.{observation.get('table')}":
            raise ValueError("Repair target does not match the audited finding")
        self._preflight_analyze_target(params["table"], observation)
        lookup = """
            SELECT request_id,status,parameters,finding,evidence
            FROM repair_requests
            WHERE audit_id=%s AND operation=%s AND parameters->>'table'=%s
            ORDER BY created_at DESC,request_id DESC LIMIT 1
        """
        lookup_parameters = (audit_id, operation, params["table"])
        kb = OperationsStore()
        try:
            self._ensure_schema(kb)
            with kb.conn, kb.conn.cursor() as cur:
                cur.execute(lookup, lookup_parameters)
                existing = cur.fetchone()
        finally:
            kb.close()
        if existing:
            if existing[1] == "pending" and existing[3] != finding:
                raise ValueError("Pending proposal references a different finding")
            return {
                "request_id": existing[0], "status": existing[1],
                "operation": operation, "parameters": existing[2], "reused": True,
            }
        risk_policy = OperationRegistry.classify(operation)
        fingerprint = _proposal_fingerprint(operation, params, audit_id, finding)
        risk_policy["proposal_fingerprint"] = fingerprint
        proposal_evidence = {**(evidence or {}), "risk_policy": risk_policy}
        request_id = str(uuid.uuid4())
        kb = OperationsStore()
        try:
            with kb.conn, kb.conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtext('aiops_repair_proposal'), hashtext(%s))",
                    (audit_id,),
                )
                cur.execute(lookup, lookup_parameters)
                existing = cur.fetchone()
                if existing:
                    if existing[1] == "pending":
                        if existing[3] != finding:
                            raise ValueError("Pending proposal references a different finding")
                    return {
                        "request_id": existing[0], "status": existing[1],
                        "operation": operation, "parameters": existing[2], "reused": True,
                    }
                cur.execute(
                    "INSERT INTO repair_requests(request_id,operation,parameters,evidence,reason,audit_id,finding) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                    (request_id, operation, Json(params), Json(proposal_evidence), reason,
                     audit_id, Json(finding) if finding else None),
                )
                self._record_event(
                    cur, request_id, "proposal_created", status="pending",
                    event_data={"operation": operation, "parameters": params, "audit_id": audit_id,
                                "risk_policy": risk_policy},
                )
        finally:
            kb.close()
        return {
            "request_id": request_id, "status": "pending", "operation": operation,
            "parameters": params, "risk_policy": risk_policy,
        }

    def _authorize_decision(self, token):
        configured = self.config.AIOPS_APPROVER_TOKENS
        if configured:
            try:
                credentials = json.loads(configured, object_pairs_hook=list)
                if not credentials or not all(
                    isinstance(pair, tuple) and len(pair) == 2
                    and all(isinstance(value, str) and value.strip() for value in pair)
                    for pair in credentials
                ):
                    raise ValueError
                if any(len(set(values)) != len(credentials) for values in zip(*credentials)):
                    raise ValueError
            except (ValueError, TypeError):
                raise PermissionError("Approver credentials are misconfigured") from None
            matches = [
                actor for actor, secret in credentials
                if hmac.compare_digest((token or "").encode(), secret.encode())
            ]
            if matches:
                return matches[0]
            raise PermissionError("Approval token is invalid")
        if not self.config.AIOPS_APPROVAL_TOKEN or not hmac.compare_digest(
            (token or "").encode(), self.config.AIOPS_APPROVAL_TOKEN.encode()
        ):
            raise PermissionError("Approval token is not configured or is invalid")
        return self.config.AIOPS_APPROVER_ID

    def auto_repair_from_audit(self, audit_id):
        """Execute only an allowlisted statistics repair from a complete audit."""
        if not self.config.AIOPS_AUTO_REPAIR_ENABLED:
            return {"status": "skipped", "reason": "automatic_repair_disabled"}
        if not self.config.AIOPS_REPAIR_FUNCTION_ENABLED:
            return {"status": "skipped", "reason": "administrator_repair_function_disabled"}
        if not self.config.AIOPS_REPAIR_DB_USER or self.config.AIOPS_REPAIR_DB_USER == self.config.DB_USER:
            return {"status": "skipped", "reason": "separate_repair_account_not_configured"}
        kb = OperationsStore()
        try:
            self._ensure_schema(kb)
            with kb.conn.cursor() as cur:
                cur.execute(
                    "SELECT evidence, ai_analysis, knowledge_refs FROM audit_records WHERE audit_id=%s",
                    (audit_id,),
                )
                record = cur.fetchone()
            if not record:
                raise ValueError("Audit not found")
            evidence = record[0] or {}
            if evidence.get("trigger") != "scheduled":
                return {"status": "skipped", "reason": "audit_was_not_scheduled"}
            if evidence.get("collection_status") != "success" or evidence.get("performance_status") != "success":
                return {"status": "skipped", "reason": "health_collection_incomplete"}
            findings = evidence.get("findings") or []
            candidates = [item for item in findings if item.get("check") == "stale_table_statistics"]
            if len(findings) != 1 or len(candidates) != 1:
                return {"status": "skipped", "reason": "audit_did_not_have_one_isolated_stale_statistics_finding"}
            finding = candidates[0]
            observed = finding.get("evidence") or {}
            table = f"{observed.get('schema')}.{observed.get('table')}"
            if table not in self.config.AIOPS_AUTO_REPAIR_TARGETS:
                return {"status": "skipped", "reason": "target_not_configured_for_automatic_repair",
                        "target": table}
            request = self.create_request(
                "analyze_table", {"table": table},
                {"proposal_source": "scheduled_auto_repair", "trigger": "scheduled",
                 "observation": observed,
                 "ai_analysis": record[1], "knowledge_refs": record[2] or []},
                "Scheduled automatic repair for a complete stale-statistics audit",
                audit_id, finding,
            )
        finally:
            kb.close()
        if request.get("status") != "pending":
            return {"status": "skipped", "reason": "repair_request_already_processed",
                    "request_id": request["request_id"]}
        request_id = request["request_id"]
        kb = OperationsStore()
        try:
            self._ensure_schema(kb)
            with kb.conn, kb.conn.cursor() as cur:
                cur.execute(
                    "SELECT operation,parameters,status,audit_id,finding,evidence FROM repair_requests WHERE request_id=%s FOR UPDATE",
                    (request_id,),
                )
                row = cur.fetchone()
                if not row or row[2] != "pending":
                    raise ValueError("Automatic repair request is missing or no longer pending")
                operation, parameters, _, stored_audit, stored_finding, stored_evidence = row
                fingerprint = _proposal_fingerprint(operation, parameters, stored_audit, stored_finding)
                stored_evidence["automatic_policy"] = {
                    "approved": True, "actor": "aiops-auto-policy",
                    "approved_at": datetime.now(timezone.utc).isoformat(),
                    "proposal_fingerprint": fingerprint,
                    "policy": "scheduled_single_finding_complete_collection_allowlisted_analyze_v1",
                }
                cur.execute("UPDATE repair_requests SET evidence=%s WHERE request_id=%s AND status='pending'",
                            (Json(stored_evidence), request_id))
                if cur.rowcount != 1:
                    raise ValueError("Automatic repair request changed before policy approval")
                self._record_event(
                    cur, request_id, "automatic_policy_approved", actor="aiops-auto-policy",
                    status="pending", event_data=stored_evidence["automatic_policy"],
                )
        finally:
            kb.close()
        return self.approve_and_execute(request_id, "aiops-auto-policy", automatic=True)

    def approve_and_execute(self, request_id, approver, token=None, automatic=False):
        if automatic:
            if not self.config.AIOPS_AUTO_REPAIR_ENABLED:
                raise PermissionError("Automatic repair is disabled")
            approver = "aiops-auto-policy"
        else:
            approver = self._authorize_decision(token)
        repair_user = self.config.AIOPS_REPAIR_DB_USER.strip()
        if not repair_user or repair_user == self.config.DB_USER:
            raise ValueError("Configure a dedicated AIOPS_REPAIR_DB_USER before executing repairs")
        kb = OperationsStore()
        try:
            self._ensure_schema(kb)
            with kb.conn, kb.conn.cursor() as cur:
                cur.execute(
                    "SELECT operation,parameters,status,audit_id,finding,evidence FROM repair_requests WHERE request_id=%s FOR UPDATE",
                    (request_id,),
                )
                request = cur.fetchone()
                if not request or request[2] != "pending":
                    raise ValueError("Repair request is missing or is not pending")
                operation, params, _, audit_id, finding, reviews = request
                fingerprint = _proposal_fingerprint(operation, params, audit_id, finding)
                risk_policy = OperationRegistry.classify(operation)
                stored_policy = reviews.get("risk_policy") or {}
                if stored_policy.get("proposal_fingerprint") != fingerprint:
                    raise ValueError("Risk policy does not match the current proposal")
                automatic_policy = reviews.get("automatic_policy") or {}
                auto_approved = bool(
                    automatic
                    and automatic_policy.get("approved") is True
                    and automatic_policy.get("actor") == "aiops-auto-policy"
                    and automatic_policy.get("policy") ==
                    "scheduled_single_finding_complete_collection_allowlisted_analyze_v1"
                    and automatic_policy.get("proposal_fingerprint") == fingerprint
                    and operation == "analyze_table"
                )
                if risk_policy["requires_human_approval"] and not (
                    (reviews.get("human_approval") or {}).get("approved") or auto_approved
                ):
                    raise ValueError("Human approval must be recorded before execution")
                if ((reviews.get("human_approval") or {}).get("proposal_fingerprint")
                        and (reviews.get("human_approval") or {}).get("proposal_fingerprint") != fingerprint):
                    raise ValueError("Human approval does not match the current proposal")
                table = _table_name(params["table"])
                if operation != "analyze_table" or not audit_id or not finding:
                    raise ValueError("Repair request must reference a persisted audit finding")
                if finding.get("check") != "stale_table_statistics":
                    raise ValueError("ANALYZE requires a stale_table_statistics finding")
                expected = finding.get("evidence") or {}
                audited_target = expected.get("audit_target")
                audited_database = (expected.get("database_identity") or {}).get("database")
                if (audited_target and audited_target != self.config.audit_target) or (
                    audited_database and audited_database != self.config.DB_NAME
                ):
                    raise ValueError("Repair request belongs to a different audit target")
                if expected.get("schema") and expected.get("table"):
                    expected_table = f"{expected['schema']}.{expected['table']}"
                    if table != expected_table:
                        raise ValueError("Repair target does not match the audited finding")
                if automatic and not auto_approved:
                    raise ValueError("Automatic policy approval is missing or stale")
                if automatic and (
                    table not in self.config.AIOPS_AUTO_REPAIR_TARGETS
                    or not self.config.AIOPS_REPAIR_FUNCTION_ENABLED
                    or (reviews.get("proposal_source") != "scheduled_auto_repair")
                    or reviews.get("trigger") != "scheduled"
                ):
                    raise ValueError("Automatic repair no longer meets its configured scope")
                self._record_event(
                    cur, request_id, "execution_claimed", actor=approver,
                    status="executing", event_data={"operation": operation, "parameters": params},
                )
                cur.execute(
                    "UPDATE repair_requests SET status='executing',approved_at=now(),approved_by=%s "
                    "WHERE request_id=%s",
                    (approver, request_id),
                )
                # Persist the claim before issuing SQL on the separate OpenTenBase connection.
                kb.conn.commit()
                repair_config = copy(self.config)
                repair_config.DB_USER = repair_user
                repair_config.DB_PASSWORD = repair_config.AIOPS_REPAIR_DB_PASSWORD
                db = OpenTenBaseConnector(repair_config)
                stats_db = OpenTenBaseConnector(self.config)
                execution_attempted = False
                analyze_notices = []
                database_session_user = None
                try:
                    conn = db.connect()
                    conn.set_session(readonly=False, autocommit=False)
                    with conn.cursor() as target:
                        target.execute("SET LOCAL statement_timeout = '10s'")
                        target.execute("SET LOCAL lock_timeout = '1s'")
                        target.execute(
                            "SELECT system_identifier::text, current_database(), session_user "
                            "FROM pg_catalog.pg_control_system()"
                        )
                        identity = target.fetchone()
                        if identity is not None:
                            database_session_user = identity[2]
                        audited_identity = expected.get("database_identity") or {}
                        if identity is None or identity[:2] != (
                            audited_identity.get("system_identifier"), audited_identity.get("database")
                        ):
                            raise ValueError("Audited database identity changed or is missing; rerun the health audit")
                        target.execute(
                            "SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname = current_user"
                        )
                        if database_session_user != repair_user or target.fetchone() != (False,):
                            raise ValueError("Repair execution requires the configured non-superuser account")
                        schema_name, table_name = (
                            table.split(".", 1) if "." in table else ("public", table)
                        )
                        relation = sql.Identifier(schema_name, table_name)
                        function_enabled = (
                            self.config.AIOPS_REPAIR_FUNCTION_ENABLED
                            and self._repair_function_available(
                                conn,
                                self.config.AIOPS_REPAIR_FUNCTION_SCHEMA,
                                self.config.AIOPS_REPAIR_FUNCTION_NAME,
                            )
                        )
                        if not function_enabled:
                            target.execute(
                                sql.SQL("LOCK TABLE {} IN SHARE UPDATE EXCLUSIVE MODE").format(
                                    relation
                                )
                            )
                    stats_conn = stats_db.connect()
                    stats_conn.set_session(readonly=True, autocommit=False)
                    with stats_conn.cursor() as reader:
                        reader.execute("SET LOCAL statement_timeout = '2500ms'")
                        reader.execute(
                            "SELECT system_identifier::text, current_database() "
                            "FROM pg_catalog.pg_control_system()"
                        )
                        if reader.fetchone() != identity[:2]:
                            raise ValueError("Statistics connection does not match the repair database")
                    stats_conn.rollback()
                    stats = self._read_data_node_stats(
                        stats_conn, schema_name, table_name, execution_user=repair_user
                    )
                    live_tuples = stats["live_tuples"]
                    modifications = stats["modifications_since_analyze"]
                    previous_by_node = {
                        item["node_name"]: item["last_analyze"] for item in stats["nodes"]
                    }
                    audited_relations = {
                        item["node_name"]: item.get("relation_oid") for item in expected.get("nodes", [])
                    }
                    current_relations = {
                        item["node_name"]: item["relation_oid"] for item in stats["nodes"]
                    }
                    if not audited_relations or audited_relations != current_relations:
                        raise ValueError("Audited table identity or data-node coverage changed; rerun the health audit")
                    if not function_enabled:
                        self._require_analyze_ownership(stats["nodes"])
                    with conn.cursor() as target:
                        target.execute("SET LOCAL statement_timeout = '10s'")
                        target.execute("SET LOCAL lock_timeout = '1s'")
                        stale_nodes = stale_statistics_nodes(stats["nodes"])
                        if not stale_nodes:
                            raise ValueError("The original ANALYZE finding is no longer present")
                        execution_attempted = True
                        conn.notices.clear()
                        try:
                            if function_enabled:
                                target.execute(
                                    sql.SQL("SELECT {}.{}(%s, %s)").format(
                                        sql.Identifier(self.config.AIOPS_REPAIR_FUNCTION_SCHEMA),
                                        sql.Identifier(self.config.AIOPS_REPAIR_FUNCTION_NAME),
                                    ),
                                    (schema_name, table_name),
                                )
                            else:
                                target.execute(sql.SQL("ANALYZE {}").format(relation))
                        finally:
                            analyze_notices = [notice.strip() for notice in conn.notices]
                        skipped_objects = [
                            notice for notice in analyze_notices
                            if "WARNING:" in notice and "skipping " in notice
                        ]
                        if skipped_objects:
                            raise ValueError(
                                "ANALYZE skipped one or more objects: "
                                + " | ".join(skipped_objects)
                            )
                    conn.commit()
                    # The statistics collector can publish updates after ANALYZE commits.
                    for delay in (0, 0.5, 1, 2):
                        if delay:
                            sleep(delay)
                        post_stats = self._read_data_node_stats(
                            stats_conn, schema_name, table_name, execution_user=repair_user
                        )
                        current_by_node = {
                            item["node_name"]: item["last_analyze"] for item in post_stats["nodes"]
                        }
                        advanced_nodes = [
                            node_name for node_name, previous in previous_by_node.items()
                            if node_name in current_by_node and current_by_node[node_name]
                            and (previous is None or current_by_node[node_name] > previous)
                        ]
                        post_relations = {
                            item["node_name"]: item["relation_oid"] for item in post_stats["nodes"]
                        }
                        advanced = (
                            post_relations == current_relations
                            and len(advanced_nodes) == len(previous_by_node)
                        )
                        if advanced:
                            break
                    result = {
                        "success": advanced,
                        "operation": operation,
                        "table": table,
                        "precondition": {
                            "statistics_aggregation": "data_node_sum",
                            "stale_nodes": stale_nodes,
                            "live_tuples_estimate": live_tuples,
                            "modifications_since_analyze": modifications,
                            "data_nodes": [
                                {
                                    **node,
                                    "last_analyze": node["last_analyze"].isoformat()
                                    if node["last_analyze"] else None,
                                }
                                for node in stats["nodes"]
                            ],
                        },
                        "postcondition": {
                            "relation_oid_by_node": post_relations,
                            "last_analyze_by_node": {
                                node_name: timestamp.isoformat() if timestamp else None
                                for node_name, timestamp in current_by_node.items()
                            },
                            "advanced_nodes": advanced_nodes,
                            "verified": advanced,
                        },
                        "executed_at": datetime.now(timezone.utc).isoformat(),
                    }
                except Exception as error:
                    result = {
                        "success": False,
                        "operation": operation,
                        "table": table,
                        "error": str(error),
                        "error_type": type(error).__name__,
                        "sqlstate": getattr(error, "pgcode", None),
                    }
                    if db._connection and not db._connection.closed:
                        try:
                            db._connection.rollback()
                        except Error as rollback_error:
                            result["rollback_error_type"] = type(rollback_error).__name__
                finally:
                    stats_db.close()
                    db.close()
                result["database_session_user"] = database_session_user
                if analyze_notices:
                    result["database_notices"] = analyze_notices
                status = "executed" if result["success"] else (
                    "unverified" if execution_attempted else "failed"
                )
                cur.execute(
                    "UPDATE repair_requests SET status=%s,result=%s "
                    "WHERE request_id=%s AND status='executing'",
                    (status, Json(result), request_id),
                )
                self._record_event(
                    cur, request_id, "execution_finished", actor=approver,
                    status=status, event_data=result,
                )
                return {"request_id": request_id, "status": status, "result": result}
        finally:
            kb.close()

    def reject(self, request_id, approver, reason, token):
        approver = self._authorize_decision(token)
        kb = OperationsStore()
        try:
            self._ensure_schema(kb)
            with kb.conn, kb.conn.cursor() as cur:
                cur.execute(
                    "UPDATE repair_requests SET status='rejected',approved_at=now(),approved_by=%s,"
                    "result=%s WHERE request_id=%s AND status='pending' RETURNING request_id",
                    (approver, Json({"reason": reason}), request_id),
                )
                if not cur.fetchone():
                    raise ValueError("Repair request is missing or is not pending")
                self._record_event(
                    cur, request_id, "request_rejected", actor=approver,
                    status="rejected", event_data={"reason": reason},
                )
                return {"request_id": request_id, "status": "rejected"}
        finally:
            kb.close()

    def record_human_approval(self, request_id, token):
        approver = self._authorize_decision(token)
        kb = OperationsStore()
        try:
            self._ensure_schema(kb)
            with kb.conn, kb.conn.cursor() as cur:
                cur.execute(
                    "SELECT evidence,status FROM repair_requests WHERE request_id=%s FOR UPDATE",
                    (request_id,),
                )
                row = cur.fetchone()
                if row is None or row[1] != "pending":
                    raise ValueError("Repair request is missing or is not pending")
                evidence = row[0] or {}
                cur.execute(
                    "SELECT operation,parameters,audit_id,finding FROM repair_requests WHERE request_id=%s",
                    (request_id,),
                )
                operation, parameters, audit_id, finding = cur.fetchone()
                fingerprint = _proposal_fingerprint(operation, parameters, audit_id, finding)
                evidence["human_approval"] = {
                    "approved": True,
                    "approver": approver,
                    "approved_at": datetime.now(timezone.utc).isoformat(),
                    "proposal_fingerprint": fingerprint,
                }
                cur.execute(
                    "UPDATE repair_requests SET evidence=%s WHERE request_id=%s AND status='pending'",
                    (Json(evidence), request_id),
                )
                self._record_event(
                    cur, request_id, "human_approval_recorded", actor=approver,
                    status="pending", event_data=evidence["human_approval"],
                )
                return {"request_id": request_id, "human_approval": evidence["human_approval"]}
        finally:
            kb.close()

    def record_manual_review(self, request_id, disposition, note, token):
        reviewer = self._authorize_decision(token)
        if disposition not in {"confirmed", "closed_no_retry"}:
            raise ValueError("Manual review disposition must be confirmed or closed_no_retry")
        note = note.strip()
        if not 1 <= len(note) <= 4000:
            raise ValueError("Review note must contain 1 to 4000 characters")
        kb = OperationsStore()
        try:
            self._ensure_schema(kb)
            with kb.conn, kb.conn.cursor() as cur:
                cur.execute(
                    """UPDATE repair_requests
                       SET manual_review=jsonb_build_object(
                           'disposition', %s::text, 'note', %s::text,
                           'reviewer', %s::text, 'reviewed_at', now())
                       WHERE request_id=%s AND (
                           status='unverified' OR
                           status='executing' AND
                           COALESCE(approved_at, created_at) < now() - interval '5 minutes'
                       )
                         AND manual_review IS NULL
                       RETURNING manual_review""",
                    (disposition, note, reviewer, request_id),
                )
                row = cur.fetchone()
                if row is None:
                    raise ValueError("Repair request is not awaiting manual review")
                if disposition == "closed_no_retry":
                    cur.execute(
                        "UPDATE repair_requests SET status='closed' WHERE request_id=%s "
                        "AND manual_review IS NOT NULL AND status IN ('executing', 'unverified')",
                        (request_id,),
                    )
                self._record_event(
                    cur, request_id, "manual_review_recorded", actor=reviewer,
                    status="closed" if disposition == "closed_no_retry" else "unverified",
                    event_data={"disposition": disposition, "note": note},
                )
                return {"request_id": request_id, "status": "closed" if disposition == "closed_no_retry" else "unverified", "manual_review": row[0]}
        finally:
            kb.close()

    def list_requests(self, limit=50, offset=0, queue=None):
        kb = OperationsStore()
        try:
            self._ensure_schema(kb)
            with kb.conn.cursor() as cur:
                cur.execute(
                    "SELECT request_id,operation,parameters,evidence,reason,status,created_at,approved_at,approved_by,result,audit_id,finding,manual_review "
                    """FROM repair_requests
                    WHERE (%s::text IS NULL OR status = 'pending' AND %s = 'pending'
                       OR (status = 'unverified' OR status = 'executing' AND
                           COALESCE(approved_at, created_at) < now() - interval '5 minutes')
                          AND manual_review IS NULL AND %s = 'review')
                    ORDER BY created_at DESC, request_id DESC LIMIT %s OFFSET %s""",
                    (queue, queue, queue, max(1, min(limit, 100)), max(0, offset)),
                )
                columns = [item[0] for item in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]
        finally:
            kb.close()

    def list_events(self, request_id, limit=200):
        kb = OperationsStore()
        try:
            self._ensure_schema(kb)
            with kb.conn.cursor() as cur:
                cur.execute(
                    "SELECT event_id,request_id,event_type,actor,status,event_data,created_at "
                    "FROM repair_request_events WHERE request_id=%s "
                    "ORDER BY event_id ASC LIMIT %s",
                    (request_id, max(1, min(limit, 500))),
                )
                columns = [item[0] for item in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]
        finally:
            kb.close()
