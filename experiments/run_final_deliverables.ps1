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

$stamp = Get-Setting -Name "STAMP" -DefaultValue (Get-Date -Format "yyyyMMdd")
$mqttHost = Get-Setting -Name "MQTT_HOST" -DefaultValue "127.0.0.1"
$mqttPort = Get-Setting -Name "MQTT_PORT" -DefaultValue "1883"
$intelInput = Get-Setting -Name "INTEL_LAB_INPUT" -DefaultValue ""
$aotInput = Get-Setting -Name "AOT_INPUT" -DefaultValue ""
$reportDir = Get-Setting -Name "REPORT_DIR" -DefaultValue ".\report"

if (-not $intelInput) {
    throw "INTEL_LAB_INPUT must point to the Intel Lab raw data file."
}
if (-not $aotInput) {
    throw "AOT_INPUT must point to the AoT raw archive or extracted data file."
}

$arguments = @(
    ".\experiments\run_final_deliverables.py",
    "--intel-input", $intelInput,
    "--aot-input", $aotInput,
    "--stamp", $stamp,
    "--report-dir", $reportDir,
    "--mqtt-host", $mqttHost,
    "--mqtt-port", $mqttPort
)

Push-Location $repoRoot
try {
    & $pythonExe @arguments
}
finally {
    Pop-Location
}
