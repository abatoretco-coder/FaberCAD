param(
    [string]$Cli = 'target/debug/solidcraft-cli.exe',
    [switch]$Slice,
    [string]$PrintingSkill = "$env:USERPROFILE/.codex/skills/design-for-3d-printing"
)
$ErrorActionPreference='Stop'
$output='target/workshop'
New-Item -ItemType Directory -Force -Path $output | Out-Null
& $Cli run "$PSScriptRoot/workshop.json" --save "$output/workshop.sc" --results --json-out "$output/results.json"
if ($LASTEXITCODE -ne 0) {throw 'Workshop fixture failed'}
$results=@(Get-Content "$output/results.json" -Raw|ConvertFrom-Json)
if ($results[7].ready_for_slicer -ne $true -or $null -ne $results[7].printable) {throw 'Invalid print preflight result'}
$bom=Get-Content "$output/bom.json" -Raw|ConvertFrom-Json
if ($bom.total_occurrences -ne 6) {throw 'Expected six catalogue components in the BOM'}
& $Cli eval "$output/workshop.sc" --json-out "$output/reopened.json"
if ($LASTEXITCODE -ne 0) {throw 'Saved design failed to reopen'}
$reopened=Get-Content "$output/reopened.json" -Raw|ConvertFrom-Json
if ($reopened.body_count -ne 6) {throw 'Geometry changed after reopening'}
foreach ($test in @(
    @{command='wood.board';params=@{name='Bad';material='pine';length_mm=0;width_mm=100;thickness_mm=18}},
    @{command='wood.board';params=@{name='Bad';material='invented';length_mm=100;width_mm=100;thickness_mm=18}},
    @{command='print.check';params=@{bodies=@();printer='bambu_a1_04'}},
    @{command='print.check';params=@{bodies=@('Missing');layer_height_mm=0.5}}
)) {
    $message=& $Cli exec $test.command ($test.params|ConvertTo-Json -Compress) 2>&1
    if ($LASTEXITCODE -eq 0) {throw "Invalid command unexpectedly succeeded: $($test.command)"}
}
Get-FileHash -Algorithm SHA256 -LiteralPath "$output/workshop.sc","$output/mounting-plate.stl","$output/mounting-plate.3mf" | Select-Object Path,Hash
if ($Slice) {
    $sliceOutput=Join-Path $output ('slice-'+[datetime]::UtcNow.ToString('yyyyMMdd-HHmmss'))
    & python (Join-Path $PrintingSkill 'scripts/bambu_slice.py') --input "$output/mounting-plate.3mf" --output-dir $sliceOutput
    if ($LASTEXITCODE -ne 0) {throw 'Actual A1 slicing/layer qualification failed'}
}
Write-Output 'Workshop catalogue, preflight, export, reopen and negative checks passed.'
