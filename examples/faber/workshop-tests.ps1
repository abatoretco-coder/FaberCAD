$ErrorActionPreference='Stop'
$output='target/workshop'
New-Item -ItemType Directory -Force -Path $output | Out-Null
$engine=(Get-ChildItem 'target/debug/deps/libsolidcraft_engine-*.rlib'|Sort-Object LastWriteTime -Descending|Select-Object -First 1).FullName
if (!$engine) {throw 'Build solidcraft-cli before running the production-library tests'}
$compiled=$false
foreach ($json in Get-ChildItem 'target/debug/deps/libserde_json-*.rlib') {
    & rustc --edition 2024 --test "$PSScriptRoot/workshop-tests.rs" --crate-name faber_workshop_tests --extern "solidcraft_engine=$engine" --extern "serde_json=$($json.FullName)" -L dependency=target/debug/deps -o "$output/workshop-tests.exe" 2> "$output/test-compile.log"
    if ($LASTEXITCODE -eq 0) {$compiled=$true;break}
}
if (!$compiled) {Get-Content "$output/test-compile.log";throw 'Production-library test compilation failed'}
& "$output/workshop-tests.exe" --test-threads=1
if ($LASTEXITCODE -ne 0) {throw 'Workshop engine regression failed'}
