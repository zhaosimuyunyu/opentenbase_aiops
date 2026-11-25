import json
import logging
import uuid
import asyncio
from openai import APIStatusError
from ..tools.knowledge_search_tool import execute_search_knowledge
from ..tools.lock_audit_tool import execute_get_database_locks
from ..ai.agent_client import AIOpsAgent
from ..utils.operations_store import OperationsStore
from ..utils.config import Config
from ..collectors.readonly_health import ReadonlyHealthCollector, stale_statistics_nodes

logger = logging.getLogger(__name__)

def _ensure_audit_schema(cursor):
    cursor.execute("SELECT to_regclass('public.audit_records')")
    if cursor.fetchone()[0] is not None:
        return
    cursor.execute("SELECT pg_advisory_xact_lock(hashtext('aiops.audit_records.schema'))")
    cursor.execute("""CREATE TABLE IF NOT EXISTS audit_records(
        audit_id text primary key, audit_type text not null,
        created_at timestamptz default now(), evidence jsonb not null,
        ai_analysis jsonb, knowledge_refs jsonb, risk_level text,
        status text default 'pending')""")


class ReadonlyAuditEngine:
    def __init__(self, config=None):
        self.config = config or Config()

    @staticmethod
    async def _diagnose(issue, evidence):
        try:
            analysis = await AIOpsAgent().diagnose(issue, evidence)
        except Exception as error:
            analysis = AIOpsAgent._fallback_diagnosis(evidence, type(error).__name__)
            if isinstance(error, APIStatusError):
                analysis['ai_http_status'] = error.status_code
        if analysis.get('analysis_fallback') and not analysis.get('knowledge_refs') and any(
            finding.get('check') == 'prepared_transaction_blocker'
            for finding in evidence.get('findings', [])
        ):
            try:
                result = await execute_search_knowledge(
                    'OpenTenBase prepared transaction pg_prepared_xacts transaction ID lock',
                    top_k=3,
                )
                analysis['knowledge_refs'] = result['results']
            except Exception as error:
                sqlstate = getattr(error, 'pgcode', None)
                analysis['fallback_knowledge_error'] = {
                    'type': type(error).__name__, 'sqlstate': sqlstate,
                }
                logger.warning(
                    'Knowledge retrieval failed during prepared transaction audit (%s, SQLSTATE %s)',
                    type(error).__name__, sqlstate or 'unavailable',
                )
        return analysis

    async def _diagnose_with_budget(self, issue, evidence):
        """Bound the complete model/tool loop while preserving deterministic fallback."""
        try:
            return await asyncio.wait_for(
                self._diagnose(issue, evidence),
                timeout=self.config.AIOPS_AI_AUDIT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            return AIOpsAgent._fallback_diagnosis(
                evidence, TimeoutError("AI audit time budget exceeded")
            )

    async def run_lock_audit(self):
        locks = await execute_get_database_locks(True)
        if locks['collection_status'] == 'error':
            analysis = {
                'analysis': '锁状态采集失败，请检查协调节点连接后重试。',
                'knowledge_refs': [],
                'tool_called': False,
            }
        else:
            analysis = await self._diagnose_with_budget(
                f"发现 {locks['blocked_locks']} 个阻塞锁，请分析原因并给出只读建议", locks
            )
        structured = analysis.get('structured') or {}
        risk_level = structured.get('risk_level')
        if isinstance(risk_level, str):
            risk_level = risk_level.strip().lower()
            risk_level = {
                '低': 'low', '中': 'medium', '中等': 'medium',
                '中高': 'high', '高': 'high', '严重': 'critical',
                'critical': 'critical', 'high': 'high',
                'medium': 'medium', 'low': 'low',
            }.get(risk_level, risk_level)
        if locks['collection_status'] == 'error':
            risk_level = 'unknown'
        elif not isinstance(risk_level, str) or risk_level not in {'low', 'medium', 'high', 'critical'}:
            risk_level = 'high' if locks['blocked_locks'] else 'low'
        elif locks['blocked_locks'] and risk_level in {'low', 'medium'}:
            risk_level = 'high'
        audit_id = str(uuid.uuid4())
        kb = OperationsStore()
        try:
            with kb.conn, kb.conn.cursor() as cur:
                _ensure_audit_schema(cur)
                cur.execute("""INSERT INTO audit_records(
                    audit_id,audit_type,evidence,ai_analysis,knowledge_refs,risk_level)
                    VALUES(%s,%s,%s,%s,%s,%s)""",
                    (audit_id, 'readonly_lock_audit', json.dumps(locks, default=str), json.dumps(analysis, default=str),
                     json.dumps(analysis['knowledge_refs'], default=str), risk_level))
        finally:
            kb.close()
        return {'audit_id': audit_id, 'audit_type': 'readonly_lock_audit',
                'risk_level': risk_level,
                'evidence': locks, **analysis}

    async def run_health_audit(self, *, trigger="manual", table=None, progress=None):
        """Run read-only checks across cluster, capacity, locks, and query health."""
        if progress:
            progress("collecting")
        snapshot = ReadonlyHealthCollector(self.config).collect(table=table)
        checks = snapshot['checks']
        cluster = {name: checks.get(name) for name in
                   ('nodes', 'connections', 'replication', 'database_info', 'database_identity',
                    'prepared_transactions', 'data_node_prepared_transactions', 'pg_clean_diagnostics',
                    'pg_unlock_diagnostics', 'key_guc',
                    'node_connectivity')}
        performance = {name: checks.get(name) for name in
                       ('locks', 'long_running_queries', 'idle_transactions',
                    'table_stats', 'index_usage', 'storage', 'data_node_table_stats',
                    'data_node_stats_fallback')}
        findings = []
        lock_rows = checks.get('locks')
        blocked_locks = [row for row in lock_rows or [] if not row['granted']]
        if blocked_locks:
            findings.append({
                'check': 'lock_waits', 'severity': 'high',
                'observed': f'{len(blocked_locks)} waiting locks',
                'evidence': blocked_locks,
            })
        if 'pg_unlock_diagnostics' in checks and (
            blocked_locks or checks.get('prepared_transactions')
            or checks.get('data_node_prepared_transactions')
        ):
            unlock_status = (checks.get('pg_unlock_diagnostics') or [{}])[0]
            unlock_ready = all(
                unlock_status.get(key) is True
                for key in ('dependency_registered', 'dependency_executable')
            )
            if not unlock_ready:
                if unlock_status.get('dependency_registered'):
                    reason = 'pg_unlock_check_dependency is installed but unavailable to the audit account'
                elif unlock_status.get('package_available'):
                    reason = 'pg_unlock is available to install, but pg_unlock_check_dependency is not registered'
                else:
                    reason = 'pg_unlock_check_dependency is not available on the connected CN'
                findings.append({
                    'check': 'official_lock_diagnostics_unavailable',
                    'severity': 'low',
                    'observed': reason,
                    'evidence': unlock_status,
                })
        for node in checks.get('node_connectivity') or []:
            if node.get('status') == 'unreachable':
                findings.append({
                    'check': 'node_unreachable', 'severity': 'critical',
                    'observed': f"{node.get('node_name')} ({node.get('node_type')}) is unreachable at {node.get('host')}:{node.get('port')}",
                    'evidence': node,
                })
        connection_rows = checks.get('connections')
        total_connections = (
            sum(row['connection_count'] for row in connection_rows)
            if connection_rows is not None else None
        )
        max_rows = checks.get('max_connections') or []
        max_connections = max_rows[0]['max_connections'] if max_rows else None
        usage = (
            round(total_connections / max_connections * 100, 2)
            if total_connections is not None and max_connections else None
        )
        cluster['connection_capacity'] = {
            'scope': 'connected_cn',
            'total': total_connections,
            'max_connections': max_connections,
            'usage_percent': usage,
        }
        if usage is not None and usage >= 80:
            findings.append({
                'check': 'connection_capacity', 'severity': 'high' if usage >= 95 else 'medium',
                'observed': f'Client backends on the connected CN use {usage}% of max_connections',
                'evidence': cluster['connection_capacity'],
            })
        long_queries = checks.get('long_running_queries') or []
        if long_queries:
            findings.append({
                'check': 'long_running_queries', 'severity': 'medium',
                'observed': f'{len(long_queries)} queries exceeded the collector threshold',
                'evidence': long_queries,
            })
        idle_transactions = checks.get('idle_transactions') or []
        aged_idle_transactions = [
            transaction for transaction in idle_transactions
            if transaction.get('transaction_age')
            and transaction['transaction_age'].total_seconds() >= 300
        ]
        if aged_idle_transactions:
            findings.append({
                'check': 'idle_in_transaction',
                'severity': 'high' if any(
                    item['transaction_age'].total_seconds() >= 1800
                    for item in aged_idle_transactions
                ) else 'medium',
                'observed': f'{len(aged_idle_transactions)} idle transactions open for at least 5 minutes',
                'evidence': aged_idle_transactions,
            })
        prepared = checks.get('prepared_transactions') or []
        waiting_xids = {
            str(row.get('transactionid')) for row in blocked_locks
            if row.get('transactionid') is not None
        }
        prepared_by_gid = {}
        for transaction in checks.get('data_node_prepared_transactions') or []:
            prepared_by_gid.setdefault(transaction.get('gid'), []).append(transaction)
        blocked_gids = {
            gid for gid, participants in prepared_by_gid.items()
            if any(participant.get('waiting_pids') for participant in participants)
        }
        matching_prepared = [
            dict(transaction) for transaction in prepared
            if str(transaction.get('transaction_id')) in waiting_xids
            or transaction.get('gid') in blocked_gids
        ]
        coordinator_gids = {transaction.get('gid') for transaction in matching_prepared}
        for transaction in matching_prepared:
            transaction['data_node_participants'] = prepared_by_gid.get(
                transaction.get('gid'), []
            )
            transaction['held_transaction_locks'] = [
                lock for lock in lock_rows
                if lock['granted'] and lock.get('pid') is None
                and lock.get('locktype') == 'transactionid'
                and lock.get('transactionid') == transaction.get('transaction_id')
            ]
        for gid in blocked_gids - coordinator_gids:
            participants = prepared_by_gid[gid]
            waiting = next(node for node in participants if node.get('waiting_pids'))
            matching_prepared.append({**waiting, 'data_node_participants': participants})
        if matching_prepared:
            databases = sorted({
                transaction['database'] for transaction in matching_prepared
                if transaction.get('database')
            })
            observed = f'{len(matching_prepared)} prepared transaction(s) match waiting transaction IDs'
            if databases:
                observed += f" (transaction databases: {', '.join(databases)})"
            findings.append({
                'check': 'prepared_transaction_blocker', 'severity': 'high',
                'observed': observed,
                'transaction_databases': databases,
                'evidence': matching_prepared,
            })
            pg_clean = (cluster.get('pg_clean_diagnostics') or [{}])[0]
            if pg_clean.get('record_list_registered') is False:
                findings.append({
                    'check': 'official_2pc_record_diagnostics_unavailable',
                    'severity': 'low',
                    'observed': 'OpenTenBase pgxc_get_record_list is not registered on the connected CN',
                    'evidence': pg_clean,
                })
        for row in checks.get('replication') or []:
            if row.get('state') != 'streaming':
                findings.append({
                    'check': 'replication_state', 'severity': 'high',
                    'observed': f"Replication connection {row.get('pid')} state is {row.get('state')}",
                    'evidence': row,
                })
            lag = row.get('replay_lag')
            lag_seconds = lag.total_seconds() if hasattr(lag, 'total_seconds') else None
            if lag_seconds is not None and lag_seconds >= 30:
                findings.append({
                    'check': 'replication_replay_lag', 'severity': 'high' if lag_seconds >= 300 else 'medium',
                    'observed': f"Replication replay lag is {lag_seconds:.1f} seconds",
                    'evidence': row,
                })
        node_stats_complete = not any(
            name.startswith('data_node_stats:') for name in snapshot['errors']
        )
        identities = checks.get('database_identity') or []
        identity = identities[0] if identities else None
        table_stats = [
            (row, 'primary') for row in (checks.get('data_node_table_stats') or [])
            if node_stats_complete
        ]
        for entry in (checks.get('data_node_stats_fallback') or {}).values():
            if not entry['errors']:
                table_stats.extend((row, 'fallback') for row in entry['tables'])
        for table_stat, source in table_stats:
            live = table_stat.get('live_tuples') or 0
            modifications = table_stat.get('modifications_since_analyze') or 0
            stale_nodes = stale_statistics_nodes(table_stat.get('nodes', []))
            if stale_nodes:
                findings.append({
                    'check': 'stale_table_statistics', 'severity': 'medium',
                    'observed': f"{table_stat['schemaname']}.{table_stat['tablename']} has stale statistics on {', '.join(stale_nodes)}",
                    'evidence': {
                        'schema': table_stat['schemaname'], 'table': table_stat['tablename'],
                        'live_tuples_estimate': live, 'modifications_since_analyze': modifications,
                        'nodes': table_stat.get('nodes', []),
                        'database_identity': identity,
                        'audit_target': self.config.audit_target,
                        'statistics_source': source,
                        'statistics_aggregation': 'data_node_sum',
                        'stale_nodes': stale_nodes,
                    },
                })
            dead = table_stat.get('dead_tuples') or 0
            total = live + dead
            dead_ratio = dead / total if total else 0
            if dead >= 1000 and dead_ratio >= 0.2:
                findings.append({
                    'check': 'dead_tuple_ratio', 'severity': 'medium',
                    'observed': f"{table_stat['schemaname']}.{table_stat['tablename']} estimated dead tuple ratio is {dead_ratio:.1%}",
                    'evidence': {
                        'schema': table_stat['schemaname'], 'table': table_stat['tablename'],
                        'live_tuples_estimate': live, 'dead_tuples_estimate': dead,
                        'dead_ratio_estimate': round(dead_ratio, 4),
                    },
                })
        for check_name, error in snapshot['errors'].items():
            findings.append({
                'check': f'collection:{check_name}',
                'severity': 'unknown',
                'observed': 'The check could not be collected',
                'evidence': error,
            })
        cluster_checks = {
            'nodes', 'connections', 'max_connections', 'replication',
            'database_info', 'database_identity', 'prepared_transactions', 'pg_clean_diagnostics',
            'pg_unlock_diagnostics', 'key_guc',
        }
        performance_checks = {
            'locks', 'long_running_queries', 'idle_transactions',
            'table_stats', 'index_usage',
            'storage',
        }
        cluster_errors = cluster_checks.intersection(snapshot['errors'])
        cluster_node_errors = {
            name for name in snapshot['errors']
            if name.startswith(('data_node_prepared_transactions:', 'node_connectivity:'))
        }
        cluster_errors.update(cluster_node_errors)
        performance_errors = performance_checks.intersection(snapshot['errors'])
        performance_node_errors = {
            name for name in snapshot['errors'] if name.startswith('data_node_stats:')
        }
        performance_errors.update(performance_node_errors)
        unreachable_nodes = any(
            node.get('status') == 'unreachable'
            for node in checks.get('node_connectivity', [])
        )
        cluster_status = 'error' if not cluster_checks.intersection(checks) else (
            'partial' if cluster_errors or unreachable_nodes else 'success'
        )
        performance_status = 'error' if not performance_checks.intersection(checks) else (
            'partial' if performance_errors else 'success'
        )
        evidence = {
            'trigger': trigger,
            'statistics_target': table,
            'audit_target': self.config.audit_target,
            'collection_status': snapshot['status'],
            'cluster_status': cluster_status,
            'performance_status': performance_status,
            'cluster': cluster,
            'performance': performance,
            'collection_errors': snapshot['errors'],
            'findings': findings,
        }
        issue = (
            f"执行 OpenTenBase 只读健康巡检。发现 {len(findings)} 个规则告警，"
            f"锁等待 {len(blocked_locks)}，当前 CN 客户端连接占用 "
            f"{f'{usage}%' if usage is not None else '未知'}，"
            f"超过阈值的长查询 {len(long_queries)}。请逐项基于证据解释并给出只读复核建议。"
        )
        if snapshot['status'] == 'error':
            analysis = {
                'analysis': 'The OpenTenBase connection failed, so no live database diagnosis is available.',
                'structured': {
                    'root_cause': 'The database connection was refused before any health checks ran.',
                    'risk_level': 'unknown',
                    'evidence': [snapshot['errors'].get('connection', {})],
                    'recommendations': [
                        'Verify the OpenTenBase CN process and listening port, then rerun the read-only audit.'
                    ],
                    'analysis_source': 'collection_failure',
                },
                'knowledge_refs': [],
                'tool_called': False,
                'analysis_fallback': False,
            }
            risk_level = 'unknown'
        else:
            if progress:
                progress("diagnosing")
            analysis = await self._diagnose_with_budget(issue, evidence)
            structured = analysis.get('structured') or {}
            risk_level = structured.get('risk_level')
            if isinstance(risk_level, str):
                risk_level = risk_level.strip().lower()
                risk_level = {
                    '低': 'low', '中': 'medium', '中等': 'medium',
                    '中高': 'high', '高': 'high', '严重': 'critical',
                    'critical': 'critical', 'high': 'high',
                    'medium': 'medium', 'low': 'low',
                }.get(risk_level, risk_level)
            if not isinstance(risk_level, str) or risk_level not in {'low', 'medium', 'high', 'critical'}:
                reliable_findings = [item for item in findings if item['severity'] != 'unknown']
                risk_level = 'high' if any(
                    item['severity'] == 'high' for item in reliable_findings
                ) else ('medium' if reliable_findings else 'low')
            severity_rank = {'low': 0, 'medium': 1, 'high': 2, 'critical': 3}
            deterministic_floor = max(
                (severity_rank.get(item['severity'], 0) for item in findings),
                default=0,
            )
            if severity_rank[risk_level] < deterministic_floor:
                risk_level = next(
                    level for level, rank in severity_rank.items()
                    if rank == deterministic_floor
                )
        if progress:
            progress("saving")
        audit_id = str(uuid.uuid4())
        kb = OperationsStore()
        try:
            with kb.conn, kb.conn.cursor() as cur:
                _ensure_audit_schema(cur)
                cur.execute("""INSERT INTO audit_records(
                    audit_id,audit_type,evidence,ai_analysis,knowledge_refs,risk_level)
                    VALUES(%s,%s,%s,%s,%s,%s)""",
                    (audit_id, 'readonly_health_audit', json.dumps(evidence, default=str),
                     json.dumps(analysis, default=str),
                     json.dumps(analysis['knowledge_refs'], default=str), risk_level))
        finally:
            kb.close()
        return {
            'audit_id': audit_id,
            'audit_type': 'readonly_health_audit',
            'risk_level': risk_level,
            'findings': findings,
            'evidence': evidence,
            **analysis,
        }

