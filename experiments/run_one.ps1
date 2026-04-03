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

function Test-TcpPort {
    param(
        [string]$Host,
        [int]$Port
    )

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $client.Connect($Host, $Port)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$shellPath = (Get-Process -Id $PID).Path

$mqttHost = Get-Setting -Name "MQTT_HOST" -DefaultValue "127.0.0.1"
$mqttPort = [int](Get-Setting -Name "MQTT_PORT" -DefaultValue "1883")
$mqttQos = Get-Setting -Name "MQTT_QOS" -DefaultValue "0"
$wsHost = Get-Setting -Name "WS_HOST" -DefaultValue "127.0.0.1"
$wsPort = [int](Get-Setting -Name "WS_PORT" -DefaultValue "8000")
$runId = Get-Setting -Name "RUN_ID" -DefaultValue (Get-Date -Format "yyyyMMdd-HHmmss")
$replaySpeed = Get-Setting -Name "REPLAY_SPEED" -DefaultValue "1.0"
$sensorLimit = Get-Setting -Name "SENSOR_LIMIT" -DefaultValue "0"
$durationS = [int](Get-Setting -Name "DURATION_S" -DefaultValue "60")

if (-not (Test-TcpPort -Host $mqttHost -Port $mqttPort)) {
    throw "MQTT broker is not reachable at ${mqttHost}:${mqttPort}. Start Mosquitto before running this script."
}

$runDir = Join-Path $repoRoot "experiments\logs\$runId"
New-Item -ItemType Directory -Path $runDir -Force | Out-Null

$gatewayStdout = Join-Path $runDir "gateway.stdout.log"
$gatewayStderr = Join-Path $runDir "gateway.stderr.log"
$simulatorStdout = Join-Path $runDir "simulator.stdout.log"
$simulatorStderr = Join-Path $runDir "simulator.stderr.log"
$metricsJson = Join-Path $runDir "metrics.json"

$gatewayCommand = @"
Set-Location '$repoRoot'
`$env:MQTT_HOST = '$mqttHost'
`$env:MQTT_PORT = '$mqttPort'
`$env:MQTT_QOS = '$mqttQos'
`$env:WS_HOST = '$wsHost'
`$env:WS_PORT = '$wsPort'
`$env:RUN_ID = '$runId'
python -m gateway.app
"@

$simulatorCommand = @"
Set-Location '$repoRoot'
`$env:MQTT_HOST = '$mqttHost'
`$env:MQTT_PORT = '$mqttPort'
`$env:MQTT_QOS = '$mqttQos'
`$env:REPLAY_SPEED = '$replaySpeed'
`$env:SENSOR_LIMIT = '$sensorLimit'
`$env:DURATION_S = '$durationS'
`$env:RUN_ID = '$runId'
python .\simulator\replay_publisher.py --data-file .\simulator\sample_data.csv
"@

$gatewayProcess = Start-Process `
    -FilePath $shellPath `
    -ArgumentList "-NoProfile", "-Command", $gatewayCommand `
    -RedirectStandardOutput $gatewayStdout `
    -RedirectStandardError $gatewayStderr `
    -PassThru

Start-Sleep -Seconds 3
if (-not (Test-TcpPort -Host $wsHost -Port $wsPort)) {
    Stop-Process -Id $gatewayProcess.Id -Force
    throw "Gateway did not start on ${wsHost}:${wsPort}. Check $gatewayStderr for details."
}

$simulatorProcess = Start-Process `
    -FilePath $shellPath `
    -ArgumentList "-NoProfile", "-Command", $simulatorCommand `
    -RedirectStandardOutput $simulatorStdout `
    -RedirectStandardError $simulatorStderr `
    -PassThru

try {
    Wait-Process -Id $simulatorProcess.Id -Timeout ($durationS + 20)
}
catch {
    Stop-Process -Id $simulatorProcess.Id -Force -ErrorAction SilentlyContinue
    throw "Simulator exceeded the timeout for the ${durationS}s run."
}

$simulatorProcess.Refresh()
if ($simulatorProcess.ExitCode -ne 0) {
    Stop-Process -Id $gatewayProcess.Id -Force -ErrorAction SilentlyContinue
    throw "Simulator exited with code $($simulatorProcess.ExitCode). Check $simulatorStderr for details."
}

Invoke-RestMethod -Uri "http://${wsHost}:${wsPort}/metrics" | ConvertTo-Json -Depth 3 | Set-Content -Path $metricsJson

if (-not $gatewayProcess.HasExited) {
    Stop-Process -Id $gatewayProcess.Id -Force
}

Write-Host "Run complete. Artifacts saved to $runDir"
