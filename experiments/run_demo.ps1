$ErrorActionPreference = "Stop"

function Get-Setting {
    param(
        [string]$Name,
        [string]$DefaultValue
    )

    $value = (Get-Item -Path "Env:$Name" -ErrorAction SilentlyContinue).Value
    if ($value) {
        return $value
    }

    return $DefaultValue
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$pythonExe = if (Test-Path $venvPython) { $venvPython } else { "python" }

$runId = Get-Setting -Name "RUN_ID" -DefaultValue (Get-Date -Format "yyyyMMdd-HHmmss")
$mqttHost = Get-Setting -Name "MQTT_HOST" -DefaultValue "127.0.0.1"
$mqttPort = Get-Setting -Name "MQTT_PORT" -DefaultValue "1883"
$mqttQos = Get-Setting -Name "MQTT_QOS" -DefaultValue "0"
$dataFile = Get-Setting -Name "DATA_FILE" -DefaultValue ".\simulator\sample_data.csv"
$scenarioFile = Get-Setting -Name "SCENARIO_FILE" -DefaultValue ".\experiments\scenarios\demo_v0_vs_v4.json"
$durationS = Get-Setting -Name "DURATION_S" -DefaultValue "20"
$replaySpeed = Get-Setting -Name "REPLAY_SPEED" -DefaultValue "2.0"
$sensorLimit = Get-Setting -Name "SENSOR_LIMIT" -DefaultValue "0"
$burstEnabled = Get-Setting -Name "BURST_ENABLED" -DefaultValue "1"
$burstStartS = Get-Setting -Name "BURST_START_S" -DefaultValue "2"
$burstDurationS = Get-Setting -Name "BURST_DURATION_S" -DefaultValue "4"
$burstSpeedMultiplier = Get-Setting -Name "BURST_SPEED_MULTIPLIER" -DefaultValue "8.0"
$baselineGatewayPort = Get-Setting -Name "BASELINE_GATEWAY_PORT" -DefaultValue "8000"
$smartGatewayPort = Get-Setting -Name "SMART_GATEWAY_PORT" -DefaultValue "8001"
$baselineProxyPort = Get-Setting -Name "BASELINE_PROXY_PORT" -DefaultValue "9000"
$smartProxyPort = Get-Setting -Name "SMART_PROXY_PORT" -DefaultValue "9001"
$noOpenBrowser = Get-Setting -Name "NO_OPEN_BROWSER" -DefaultValue "0"

$arguments = @(
    ".\experiments\run_demo.py",
    "--run-id", "m5-demo-$runId",
    "--mqtt-host", $mqttHost,
    "--mqtt-port", $mqttPort,
    "--mqtt-qos", $mqttQos,
    "--data-file", $dataFile,
    "--scenario-file", $scenarioFile,
    "--duration-s", $durationS,
    "--replay-speed", $replaySpeed,
    "--sensor-limit", $sensorLimit,
    "--baseline-gateway-port", $baselineGatewayPort,
    "--smart-gateway-port", $smartGatewayPort,
    "--baseline-proxy-port", $baselineProxyPort,
    "--smart-proxy-port", $smartProxyPort,
    "--burst-start-s", $burstStartS,
    "--burst-duration-s", $burstDurationS,
    "--burst-speed-multiplier", $burstSpeedMultiplier
)

if ($burstEnabled -eq "0") {
    $arguments += "--no-burst-enabled"
}
if ($noOpenBrowser -eq "1") {
    $arguments += "--no-open-browser"
}

Push-Location $repoRoot
try {
    & $pythonExe @arguments
}
finally {
    Pop-Location
}
