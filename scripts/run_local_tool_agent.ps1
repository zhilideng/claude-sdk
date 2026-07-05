param(
    [Parameter(Mandatory = $true)]
    [string]$Server,
    [string]$AgentName = "local-agent",
    [string]$Python = "python"
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
& $Python (Join-Path $ScriptDir "local_tool_agent.py") --server $Server --agent-name $AgentName
exit $LASTEXITCODE
