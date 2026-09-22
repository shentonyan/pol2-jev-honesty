# 同一时段内依次运行三组探针，便于直接比较（每组约 40 次调用，共约 120 次）
# 用法：在仓库根目录、已激活 .venv 的 PowerShell 中运行  .\scripts_run_comparison.ps1
$T = "repeat,shuffle,relabel,permute_state"
foreach ($p in @("honesty_v1_1", "honesty_v1_1_flat", "honesty_v1_2")) {
    Write-Host "`n===== $p =====" -ForegroundColor Cyan
    joh metamorphic --states data\canary_v1_1 --probe "probes\$p.json" --transforms $T
}
Write-Host "`n===== honesty_v1_2 语义变换（lang, negate）=====" -ForegroundColor Cyan
joh metamorphic --states data\canary_v1_1 --probe probes\honesty_v1_2.json --transforms repeat,lang,negate
