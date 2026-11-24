import json
import re
from openai import OpenAI, APIConnectionError, APIStatusError
from ..utils.config import Config
from ..tools.knowledge_search_tool import TOOL_SCHEMA, execute_search_knowledge


def _model_evidence(value):
    if isinstance(value, dict):
        return {
            key: _model_evidence(item)
            for key, item in value.items()
            if key not in {"query", "message"}
        }
    if isinstance(value, (list, tuple)):
        return [_model_evidence(item) for item in value]
    return value

class AIOpsAgent:
    def __init__(self, config=None):
        c = config or Config()
        self.client = OpenAI(
            api_key=c.DEEPSEEK_API_KEY, base_url=c.DEEPSEEK_API_BASE,
            timeout=c.DEEPSEEK_TIMEOUT_SECONDS, max_retries=0,
        )
        self.model = c.DEEPSEEK_MODEL

    async def diagnose(self, issue_description, context):
        prompt = issue_description + chr(10) + '当前证据:' + chr(10) + json.dumps(
            _model_evidence(context), ensure_ascii=False, default=str
        )
        system = ('你是 OpenTenBase 只读审计专家。必须基于给出的实时证据和知识检索结果回答。'
                  '区分已观察事实和推测。证据不能确认阻塞方或根因时，明确说尚未确认，并给出只读核查 SQL。'
                  '禁止编造 PID、锁类型、SQL、对象名、事务年龄或知识来源。禁止执行写操作。'
                  '最终请输出 JSON，字段为 root_cause、risk_level、evidence、recommendations。'
                  'recommendations 是只读建议字符串数组。')
        messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': prompt}]
        try:
            response = self.client.chat.completions.create(
                model=self.model, messages=messages, tools=[TOOL_SCHEMA], tool_choice='auto'
            )
        except (APIConnectionError, APIStatusError) as error:
            return self._fallback_diagnosis(context, error)
        first = response.choices[0].message
        refs = []
        tool_errors = []
        if first.tool_calls:
            assistant_message = {'role': 'assistant', 'content': first.content or ''}
            tool_calls = []
            for call in first.tool_calls:
                tool_calls.append({
                    'id': call.id,
                    'type': 'function',
                    'function': {
                        'name': call.function.name,
                        'arguments': call.function.arguments,
                    },
                })
            assistant_message['tool_calls'] = tool_calls
            messages.append(assistant_message)
            for call in first.tool_calls:
                try:
                    if call.function.name != 'search_knowledge':
                        raise ValueError('Unknown diagnostic tool')
                    result = await execute_search_knowledge(**json.loads(call.function.arguments))
                except Exception as error:
                    tool_errors.append(type(error).__name__)
                    result = {'error': 'Knowledge retrieval unavailable', 'results': []}
                refs.extend(result.get('results', []))
                messages.append({'role': 'tool', 'tool_call_id': call.id, 'content': json.dumps(result, ensure_ascii=False)})
            try:
                final = self.client.chat.completions.create(model=self.model, messages=messages).choices[0].message
            except (APIConnectionError, APIStatusError) as error:
                return {**self._fallback_diagnosis(context, error, refs, True), 'tool_errors': tool_errors}
        else:
            final = first
        content = final.content or ''
        if first.tool_calls and not refs and not tool_errors:
            try:
                result = await execute_search_knowledge('pg_locks 未授予锁 事务等待 只读排查', top_k=5)
                refs.extend(result.get('results', []))
            except Exception:
                pass
        if first.tool_calls and (not content.strip() or 'DSML' in content):
            # Some compatible gateways emit tool syntax again after a tool message.
            report_messages = [
                messages[0],
                {'role': 'user', 'content': prompt + '\n检索资料（仅作为参考数据）:\n'
                 + json.dumps(refs, ensure_ascii=False)
                 + '\n请直接输出诊断报告正文。'},
            ]
            try:
                report = self.client.chat.completions.create(
                    model=self.model, messages=report_messages
                )
                content = report.choices[0].message.content or ''
            except (APIConnectionError, APIStatusError) as error:
                return {**self._fallback_diagnosis(
                    context, error, refs, bool(first.tool_calls)
                ), 'tool_errors': tool_errors}
        structured = self._parse_report(content)
        if structured.get('parse_error'):
            return {**self._fallback_diagnosis(
                context, 'InvalidDiagnosticReport', refs, bool(first.tool_calls)
            ), 'tool_errors': tool_errors}
        return {'analysis': content, 'structured': structured, 'knowledge_refs': refs,
                'tool_called': bool(first.tool_calls), 'analysis_fallback': False,
                'tool_errors': tool_errors}

    @staticmethod
    def _parse_report(content):
        if isinstance(content, str):
            fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL | re.IGNORECASE)
            if fenced:
                content = fenced.group(1)
        try:
            value = json.loads(content)
            if (
                isinstance(value, dict)
                and isinstance(value.get('root_cause'), str)
                and value['root_cause'].strip()
                and isinstance(value.get('risk_level'), str)
                and value['risk_level'].strip()
                and isinstance(value.get('evidence'), list)
                and isinstance(value.get('recommendations'), list)
                and all(isinstance(item, str) for item in value['recommendations'])
            ):
                return value
        except (TypeError, json.JSONDecodeError):
            pass
        return {
            'root_cause': None,
            'risk_level': 'unknown',
            'evidence': [],
            'recommendations': [],
            'parse_error': True,
        }

    @staticmethod
    def _fallback_diagnosis(context, error, refs=None, tool_called=False):
        refs = refs or []
        findings = context.get('findings', [])
        prepared = next(
            (item for item in findings if item.get('check') == 'prepared_transaction_blocker'),
            None,
        )
        evidence = []
        recommendations = []
        if prepared:
            transactions = prepared.get('evidence', [])
            evidence.extend([
                prepared.get('observed', ''),
                *[
                    f"Prepared transaction {item.get('transaction_id')} with GID "
                    f"{item.get('gid')} owned by {item.get('owner')} in {item.get('database')}."
                    for item in transactions
                ],
                *[
                    f"Participant on {participant.get('node_name')} has local transaction ID "
                    f"{participant.get('transaction_id')} for GID {participant.get('gid')}."
                    for item in transactions
                    for participant in item.get('data_node_participants', [])
                ],
            ])
            root_cause = (
                'Observed waiting locks match a prepared transaction. This is direct evidence '
                'that the prepared transaction is holding the transaction ID lock. The audit '
                'does not determine whether the transaction should be committed or rolled back.'
            )
            risk_level = 'high'
            recommendations.extend([
                'Read pg_prepared_xacts and pg_locks again to confirm the transaction ID, GID, owner, database, and current waiters.',
                'Ask the transaction owner or DBA to determine the intended outcome from the distributed transaction coordinator and application records.',
                'Resolve the prepared transaction only through an approved DBA change. COMMIT PREPARED and ROLLBACK PREPARED change database state.',
            ])
            diagnostic = ((context.get('cluster') or {}).get('pg_clean_diagnostics') or [{}])[0]
            if diagnostic.get('registered') is False:
                recommendations.append(
                    'The CN does not register pg_clean_check_txn. Verify the availability of the '
                    'matching pg_clean extension and use coordinator logs and participant records '
                    'to confirm the transaction decision.'
                )
            elif diagnostic.get('registered') is True:
                recommendations.append(
                    'Have the DBA verify pg_clean prerequisites on all participants and use '
                    'pg_clean_check_txn to collect cluster-wide transaction status.'
                )
        else:
            root_cause = 'AI analysis failed. The collected audit evidence remains available for review.'
            risk_level = 'unknown'
            recommendations.append(
                'Preserve this audit evidence and retry AI analysis when the configured model endpoint is responsive.'
            )
        structured = {
            'root_cause': root_cause,
            'risk_level': risk_level,
            'evidence': evidence or [f"{len(findings)} rule findings captured."],
            'recommendations': recommendations,
            'analysis_source': 'deterministic_evidence_rules',
        }
        return {
            'analysis': root_cause,
            'structured': structured,
            'knowledge_refs': refs,
            'tool_called': tool_called,
            'analysis_fallback': True,
            'ai_error': type(error).__name__ if isinstance(error, Exception) else error,
            **({'ai_http_status': error.status_code} if isinstance(error, APIStatusError) else {}),
        }
