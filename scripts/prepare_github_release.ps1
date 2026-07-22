$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")

Write-Host "GitHub release readiness check"
Write-Host "Project root: $Root"
Write-Host "No files will be modified."
Write-Host ""

$RequiredPaths = @(
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
    "SECURITY.md",
    "CONTRIBUTING.md",
    ".gitignore",
    ".gitattributes",
    ".env.example",
    ".dockerignore",
    "Dockerfile",
    "compose.yaml",
    "compose.pgvector.yaml",
    ".github/workflows/tests.yml",
    "start.ps1",
    "scripts/verify_project.ps1",
    "backend/app/main.py",
    "backend/app/agent.py",
    "backend/app/agent_planner.py",
    "backend/app/embeddings.py",
    "backend/app/vector_store.py",
    "backend/app/evaluation_dataset.py",
    "backend/app/evaluation_gate.py",
    "backend/app/evaluation_metrics.py",
    "backend/app/eval_gate_cli.py",
    "backend/app/observability.py",
    "backend/evaluation/golden_cases.v2.json",
    "backend/evaluation/approved_baseline.v2.json",
    "backend/requirements.txt",
    "backend/requirements-runtime.txt",
    "backend/check_requirements.py",
    "backend/seed_enterprise_documents.py",
    "frontend/index.html",
    "frontend/app.js",
    "frontend/styles.css",
    "docs/resume_project_card.md",
    "docs/portfolio_review_scorecard.md",
    "docs/architecture_decisions.md",
    "docs/interview_talking_points.md",
    "docs/interview_demo_checklist.md",
    "docs/demo_runbook.md",
    "docs/production_roadmap.md",
    "docs/container_deployment.md",
    "docs/pgvector_retrieval.md",
    "docs/rag_quality_gate.md",
    "docs/final_acceptance_report.md",
    "docs/github_release_checklist.md",
    "docs/screenshots/dashboard-ai-ops.png",
    "docs/screenshots/agent-workbench.png",
    "docs/screenshots/qa-observability.png",
    "docs/screenshots/rag-quality-gate.png",
    "docs/diagrams/README.md",
    "docs/diagrams/system-components.puml",
    "docs/diagrams/system-components.svg",
    "docs/releases/v1.1.0.md",
    "docs/releases/v1.2.0.md",
    "docs/releases/v1.3.0.md"
)

$BlockedPaths = @(
    @{ Label = "Word thesis/report files"; Pattern = "*.docx" },
    @{ Label = "Runtime database"; Pattern = "backend/data/*.db" },
    @{ Label = "SQLite wal files"; Pattern = "backend/data/*.db-wal" },
    @{ Label = "SQLite shm files"; Pattern = "backend/data/*.db-shm" },
    @{ Label = "Uploaded local files"; Pattern = "backend/data/uploads/*" },
    @{ Label = "Runtime files"; Pattern = ".runtime/*" },
    @{ Label = "Container data backups"; Pattern = "backups/*" },
    @{ Label = "Tunnel tools"; Pattern = "tools/*" },
    @{ Label = "Tunnel script"; Pattern = "start_tunnel.ps1" },
    @{ Label = "Tunnel URL"; Pattern = "tunnel-url.txt" },
    @{ Label = "Archive files"; Pattern = "*.zip" },
    @{ Label = "Archive files"; Pattern = "*.7z" },
    @{ Label = "Archive files"; Pattern = "*.rar" },
    @{ Label = "Internal Codex planning docs"; Pattern = "docs/superpowers/*" },
    @{ Label = "Graduation-only markdown"; Pattern = "docs/opening_report.md" },
    @{ Label = "Graduation-only markdown"; Pattern = "docs/thesis_outline.md" },
    @{ Label = "Graduation-only markdown"; Pattern = "docs/hieu_thesis_revision_rules.md" },
    @{ Label = "Graduation-only markdown"; Pattern = "docs/demo_script.md" },
    @{ Label = "Local report generation scripts"; Pattern = "scripts/*report*.py" },
    @{ Label = "Local thesis generation scripts"; Pattern = "scripts/*thesis*.py" },
    @{ Label = "Local screenshot scripts"; Pattern = "scripts/capture_*_screenshots.py" },
    @{ Label = "Local video generation scripts"; Pattern = "scripts/create_*_video.py" }
)

$IgnoredPatterns = @(
    ".venv/",
    ".runtime/",
    "backups/",
    ".pytest_cache/",
    "__pycache__/",
    "*.pyc",
    "*.log",
    ".env",
    ".env.*",
    "!.env.example",
    "*.docx",
    "backend/data/*.db",
    "backend/data/*.db-journal",
    "backend/data/*.db-wal",
    "backend/data/*.db-shm",
    "backend/data/uploads/",
    "tools/",
    "start_tunnel.ps1",
    "tunnel-url.txt",
    "*.zip",
    "*.7z",
    "*.rar",
    "docs/superpowers/",
    "docs/opening_report.md",
    "docs/thesis_outline.md",
    "docs/hieu_thesis_revision_rules.md",
    "docs/demo_script.md",
    "outputs/",
    "scripts/add_*_screenshots_to_report.py",
    "scripts/build_*_paper*.py",
    "scripts/build_*_thesis*.py",
    "scripts/build_*_graduation*.py",
    "scripts/build_*_report*.py",
    "scripts/build_visio_*.py",
    "scripts/capture_*_screenshots.py",
    "scripts/create_*_video.py",
    "scripts/enhance_*_report.py",
    "scripts/generate_*_report.py",
    "scripts/generate_module_guide.py",
    "scripts/render_thesis_diagrams.py"
)

$MarkdownFilesToValidate = @(
    "README.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "docs/github_release_checklist.md",
    "docs/resume_project_card.md",
    "docs/portfolio_review_scorecard.md",
    "docs/architecture_decisions.md",
    "docs/production_roadmap.md",
    "docs/container_deployment.md",
    "docs/pgvector_retrieval.md",
    "docs/rag_quality_gate.md",
    "docs/interview_talking_points.md",
    "docs/interview_demo_checklist.md",
    "docs/demo_runbook.md",
    "docs/final_acceptance_report.md",
    "docs/diagrams/README.md",
    "docs/releases/v1.1.0.md",
    "docs/releases/v1.2.0.md",
    "docs/releases/v1.3.0.md"
)

$PublicPatternsToScanForSecrets = @(
    "*.md",
    ".env.example",
    "Dockerfile",
    "compose.yaml",
    "compose.pgvector.yaml",
    "start.ps1",
    ".github/workflows/*.yml",
    "backend/app/*.py",
    "backend/*.py",
    "frontend/*.html",
    "frontend/*.css",
    "frontend/*.js",
    "samples/*.md",
    "docs/*.md",
    "docs/diagrams/*.md",
    "docs/diagrams/*.puml",
    "docs/releases/*.md"
)

$SecretPatterns = @(
    @{ Label = "OpenAI-style API key"; Pattern = 'sk-[A-Za-z0-9_-]{20,}' },
    @{ Label = "AWS access key"; Pattern = 'AKIA[0-9A-Z]{16}' },
    @{ Label = "GitHub personal access token"; Pattern = 'ghp_[A-Za-z0-9]{30,}' },
    @{ Label = "Google API key"; Pattern = 'AIza[0-9A-Za-z_-]{20,}' },
    @{ Label = "Slack token"; Pattern = 'xox[baprs]-[A-Za-z0-9-]{20,}' },
    @{ Label = "Private key"; Pattern = '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----' }
)

function Get-RelativePath {
    param([string]$Path)
    $absolute = (Resolve-Path $Path).Path
    return $absolute.Substring($Root.Path.Length).TrimStart("\", "/")
}

Write-Host "Required release files"
$MissingRequired = @()
foreach ($relative in $RequiredPaths) {
    $path = Join-Path $Root $relative
    if (Test-Path $path) {
        Write-Host "  OK   $relative"
    } else {
        Write-Host "  MISS $relative"
        $MissingRequired += $relative
    }
}

Write-Host ""
Write-Host "Ignored patterns expected in .gitignore"
$GitignorePath = Join-Path $Root ".gitignore"
$GitignoreText = if (Test-Path $GitignorePath) { Get-Content -Raw $GitignorePath } else { "" }
$MissingPatterns = @()
foreach ($pattern in $IgnoredPatterns) {
    if ($GitignoreText.Contains($pattern)) {
        Write-Host "  OK   $pattern"
    } else {
        Write-Host "  MISS $pattern"
        $MissingPatterns += $pattern
    }
}

Write-Host ""
Write-Host "Local artifacts that should stay out of GitHub"
$FoundBlocked = @()
foreach ($item in $BlockedPaths) {
    $pathPattern = Join-Path $Root $item.Pattern
    $matches = @(Get-ChildItem -Path $pathPattern -Force -ErrorAction SilentlyContinue)
    foreach ($match in $matches) {
        $FoundBlocked += [pscustomobject]@{
            Label = $item.Label
            Path = Get-RelativePath $match.FullName
        }
    }
}

$PycacheDirs = @(Get-ChildItem -Path $Root -Directory -Recurse -Force -Filter "__pycache__" -ErrorAction SilentlyContinue)
foreach ($dir in $PycacheDirs) {
    $FoundBlocked += [pscustomobject]@{
        Label = "Python cache"
        Path = Get-RelativePath $dir.FullName
    }
}

if ($FoundBlocked.Count -eq 0) {
    Write-Host "  OK   No blocked local artifacts found."
} else {
    foreach ($item in $FoundBlocked | Sort-Object Path) {
        Write-Host "  WARN $($item.Path) [$($item.Label)]"
    }
}

Write-Host ""
Write-Host "Markdown local links"
$MissingMarkdownLinks = @()
foreach ($relativeMarkdown in $MarkdownFilesToValidate) {
    $markdownPath = Join-Path $Root $relativeMarkdown
    if (-not (Test-Path $markdownPath)) {
        Write-Host "  MISS $relativeMarkdown"
        $MissingMarkdownLinks += "$relativeMarkdown"
        continue
    }

    $markdownText = Get-Content -Raw -Encoding UTF8 $markdownPath
    $baseDir = Split-Path $markdownPath -Parent
    $matches = [regex]::Matches($markdownText, '(!?\[[^\]]*\]\(([^)]+)\))')

    foreach ($match in $matches) {
        $rawTarget = $match.Groups[2].Value.Trim()
        if ($rawTarget -match '^(https?://|mailto:|#)') {
            continue
        }

        $target = (($rawTarget -split "\s+")[0]).Trim('"').Trim("'")
        $target = ($target -split "#")[0]
        if ([string]::IsNullOrWhiteSpace($target)) {
            continue
        }

        $targetPath = Join-Path $baseDir ($target -replace '/', [System.IO.Path]::DirectorySeparatorChar)
        if (Test-Path $targetPath) {
            Write-Host "  OK   $relativeMarkdown -> $target"
        } else {
            Write-Host "  MISS $relativeMarkdown -> $target"
            $MissingMarkdownLinks += "$relativeMarkdown -> $target"
        }
    }
}

Write-Host ""
Write-Host "Secret pattern scan"
$PublicFilesToScan = @()
foreach ($pattern in $PublicPatternsToScanForSecrets) {
    $PublicFilesToScan += @(Get-ChildItem -Path (Join-Path $Root $pattern) -File -ErrorAction SilentlyContinue)
}

$SecretFindings = @()
foreach ($publicFile in $PublicFilesToScan | Sort-Object FullName -Unique) {
    $relativePublicFile = Get-RelativePath $publicFile.FullName
    $publicText = Get-Content -Raw -Encoding UTF8 $publicFile.FullName
    foreach ($secretPattern in $SecretPatterns) {
        if ([regex]::IsMatch($publicText, $secretPattern.Pattern)) {
            $SecretFindings += "$relativePublicFile [$($secretPattern.Label)]"
            Write-Host "  MISS $relativePublicFile [$($secretPattern.Label)]"
        }
    }
}

if ($SecretFindings.Count -eq 0) {
    Write-Host "  OK   No secret-like values found in public release files."
}

Write-Host ""
Write-Host "Recommended verification commands"
Write-Host "  .\scripts\verify_project.ps1"
Write-Host "  git status --ignored"

Write-Host ""
if (
    $MissingRequired.Count -eq 0 -and
    $MissingPatterns.Count -eq 0 -and
    $MissingMarkdownLinks.Count -eq 0 -and
    $SecretFindings.Count -eq 0
) {
    Write-Host "Release checklist status: READY WITH WARNINGS REVIEWED"
} else {
    Write-Host "Release checklist status: NEEDS ATTENTION"
    exit 1
}
