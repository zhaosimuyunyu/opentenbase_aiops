param(
    [switch]$SkipLiveAgent
)

$ErrorActionPreference = "Stop"
$apiUrl = if ($env:AIOPS_API_URL) { $env:AIOPS_API_URL } else { "http://localhost:8000" }

Write-Output "[1/8] Checking live API and OpenTenBase connection"
$health = Invoke-RestMethod "$apiUrl/health" -TimeoutSec 10
$openTenBase = $health.components.opentenbase
if ($health.api -ne "healthy" -or -not $openTenBase.connected -or $openTenBase.status -ne "success") {
    throw "AIOps API or OpenTenBase connection is unhealthy"
}
$health | ConvertTo-Json -Depth 4

Write-Output "[2/8] Checking AIOps capabilities and scheduled audit state"
$capabilities = Invoke-RestMethod "$apiUrl/api/capabilities" -TimeoutSec 10
$status = Invoke-RestMethod "$apiUrl/api/automation/status" -TimeoutSec 20
[pscustomobject]@{
    multi_turn_agent = $capabilities.interactive_agent.multi_turn_tool_use
    unrestricted_sql_tool = $capabilities.interactive_agent.unrestricted_sql_tool
    audit_interval_seconds = $status.interval_seconds
    automatic_repair_enabled = $status.automatic_repair_enabled
} | ConvertTo-Json

if (-not $SkipLiveAgent) {
    Write-Output "[3/8] Asking the live AIOps agent to inspect the cluster"
    $sessionId = [guid]::NewGuid().ToString()
    $turnId = [guid]::NewGuid().ToString()
    $requestBody = @{
        question = "Use live cluster diagnostics and the knowledge base. Report the observed topology, audit findings, and SQL tools available in this environment."
        history = @()
        session_id = $sessionId
        turn_id = $turnId
    } | ConvertTo-Json -Depth 5
    $httpClient = [System.Net.Http.HttpClient]::new()
    $httpClient.Timeout = [TimeSpan]::FromSeconds(900)
    $httpRequest = [System.Net.Http.HttpRequestMessage]::new(
        [System.Net.Http.HttpMethod]::Post, "$apiUrl/api/qa/ask/stream"
    )
    $httpRequest.Content = [System.Net.Http.StringContent]::new(
        $requestBody, [System.Text.Encoding]::UTF8, "application/json"
    )
    $response = $httpClient.SendAsync(
        $httpRequest, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead
    ).GetAwaiter().GetResult()
    $response.EnsureSuccessStatusCode()
    $reader = [System.IO.StreamReader]::new(
        $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
    )
    $agentResult = $null
    while ($null -ne ($line = $reader.ReadLine())) {
        if ($line.StartsWith("data: ")) {
            $event = $line.Substring(6) | ConvertFrom-Json
            if ($event.type -eq "error") { throw "Live Agent failed: $($event.message)" }
            if ($event.type -eq "progress") { Write-Output "Agent progress: $($event.stage)" }
            if ($event.type -eq "tool") { Write-Output "Agent tool: $($event.tool) ($($event.stage))" }
            if ($event.type -eq "result") {
                $agentResult = $event
                break
            }
        }
    }
    $reader.Dispose()
    $response.Dispose()
    $httpRequest.Dispose()
    $httpClient.Dispose()
    if (-not $agentResult) { throw "Live Agent SSE ended without a result" }
    [pscustomobject]@{
        answer = $agentResult.answer
        tool_trace = $agentResult.tool_trace
        rounds = $agentResult.rounds
    } | ConvertTo-Json -Depth 8
} else {
    Write-Output "Skipping live LLM conversation by request"
}

Write-Output "[4/8] Running official knowledge retrieval regressions"
docker compose exec -T aiops-api python scripts/test_knowledge_retrieval.py
if ($LASTEXITCODE -ne 0) { throw "Knowledge retrieval regression failed" }

Write-Output "[5/8] Running distributed SHARD create, insert, query and cleanup"
docker compose exec -T aiops-api python scripts/course_write_demo.py
if ($LASTEXITCODE -ne 0) { throw "Distributed SQL write demo failed" }

Write-Output "[6/8] Simulating a long query and running SSE health audit"
docker compose exec -T aiops-api python -m backend.tools.simulate_slow_query `
    --api-url http://127.0.0.1:8000 --timeout 210
if ($LASTEXITCODE -ne 0) { throw "Slow-query audit demo failed" }

Write-Output "[7/8] Simulating a DN lock wait and running SSE health audit"
docker compose exec -T aiops-api python -m backend.tools.simulate_lock_wait `
    --api-url http://127.0.0.1:8000 --timeout 210
if ($LASTEXITCODE -ne 0) { throw "DN lock wait audit demo failed" }

Write-Output "[8/8] Running SQL review on a read-only statement"
$sqlAudit = Invoke-RestMethod -Method Post -Uri "$apiUrl/api/sql-audit" `
    -ContentType "application/json" `
    -Body (@{ sql = "SELECT count(*) FROM pg_catalog.pg_stat_activity"; explain = $true } | ConvertTo-Json) `
    -TimeoutSec 20
$sqlAudit | ConvertTo-Json -Depth 5

Write-Output "[Tests] Running the project unit suite"
python -m unittest discover -s tests -q
if ($LASTEXITCODE -ne 0) { throw "Unit test suite failed" }

Write-Output "Course AIOps demo completed"
