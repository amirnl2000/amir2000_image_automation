[CmdletBinding()]
param(
  [string]$RepoRoot = "",
  [switch]$Fix = $true,
  [switch]$Quiet
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
  param([string]$Given)

  if ($Given -and $Given.Trim() -ne "") {
    return (Resolve-Path -LiteralPath $Given).Path
  }

  try {
    $gitRoot = (& git rev-parse --show-toplevel 2>$null)
    if ($LASTEXITCODE -eq 0 -and $gitRoot) {
      return (Resolve-Path -LiteralPath $gitRoot.Trim()).Path
    }
  } catch {}

  $here = $PSScriptRoot
  if ((Split-Path -Leaf $here).ToLowerInvariant() -eq "helpers") {
    return (Resolve-Path -LiteralPath (Split-Path -Parent $here)).Path
  }
  return (Resolve-Path -LiteralPath $here).Path
}

function Is-TextCandidate {
  param([string]$RelPath)

  $name = [IO.Path]::GetFileName($RelPath)
  if ($null -eq $name) { $name = "" }
  $name = $name.ToLowerInvariant()

  $ext = [IO.Path]::GetExtension($RelPath)
  if ($null -eq $ext) { $ext = "" }
  $ext = $ext.ToLowerInvariant()

  $textExt = @(
    ".py",".ps1",".psm1",".psd1",".md",".txt",".csv",".tsv",".json",".yaml",".yml",
    ".ini",".cfg",".toml",".env",".gitignore",".html",".htm",".css",".js",".ts",".sql",
    ".bat",".cmd",".sh"
  )

  if ($textExt -contains $ext) { return $true }
  if ($name -in @(".gitignore",".gitattributes",".env")) { return $true }
  return $false
}

function Read-Text {
  param([string]$Path)
  try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 }
  catch { return Get-Content -LiteralPath $Path -Raw }
}

function Write-Text {
  param([string]$Path, [string]$Text)
  Set-Content -LiteralPath $Path -Value $Text -Encoding UTF8
}

function Sanitize-Text {
  param([string]$Text)
  if ($null -eq $Text) { return $Text }

  $t = $Text
  $secretKeyRx = '(?:password|passwd|secret|api[_-]?key|private[_-]?key|ftp[_-]?pass|mysql[_-]?pass|db[_-]?pass)'

  # Windows user paths in plain strings (e.g. C:\Users\name\...)
  $t = [regex]::Replace($t, '[A-Za-z]:\\Users\\[^\\\r\n"''<> ]+', {
    param($m)
    $drive = $m.Value.Substring(0, 1)
    return "${drive}:\Users\YOUR_USER"
  })

  # Windows user paths escaped in code strings (e.g. C:\\Users\\name\\...)
  $t = [regex]::Replace($t, '[A-Za-z]:\\\\Users\\\\[^\\\r\n"''<> ]+', {
    param($m)
    $drive = $m.Value.Substring(0, 1)
    return "${drive}:\\Users\\YOUR_USER"
  })

  # Linux home paths
  $t = [regex]::Replace($t, '/home/[^/\s"''<>]+', '/home/YOUR_USER')

  # DSN-style credentials
  $t = [regex]::Replace(
    $t,
    '(?i)\b(mysql|mariadb|postgres|ftp)s?://([^:/\s@]+):([^@\s/]+)@',
    '$1://YOUR_USER:YOUR_SECRET_HERE@'
  )

  # Key/value secrets in env/json/yaml/python style lines.
  $t = [regex]::Replace(
    $t,
    "(?im)^(?<lhs>\s*(?:export\s+)?[\w\.\-]*$secretKeyRx[\w\.\-]*\s*[:=]\s*)(?<val>[^#\r\n]+)(?<comment>\s*#.*)?$",
    {
      param($m)
      $rawVal = ($m.Groups["val"].Value).Trim()
      if ($rawVal -match '(?i)^(["'']?)YOUR_(SECRET_HERE|VALUE_HERE|PASSWORD_HERE)\1$') {
        return $m.Value
      }
      return ($m.Groups["lhs"].Value + "YOUR_SECRET_HERE" + $m.Groups["comment"].Value)
    }
  )

  return $t
}

function Get-LeakPatterns {
  $secretKeyRx = '(?:password|passwd|secret|api[_-]?key|private[_-]?key|ftp[_-]?pass|mysql[_-]?pass|db[_-]?pass)'
  return @(
    [pscustomobject]@{ Name = "windows_user_path"; Regex = '[A-Za-z]:\\Users\\[^\\\r\n"''<> ]+' },
    [pscustomobject]@{ Name = "windows_user_path_escaped"; Regex = '[A-Za-z]:\\\\Users\\\\[^\\\r\n"''<> ]+' },
    [pscustomobject]@{ Name = "linux_home_path"; Regex = '/home/[^/\s"''<>]+' },
    [pscustomobject]@{
      Name = "secret_assignment"
      Regex = "(?im)\b[\w\.\-]*$secretKeyRx[\w\.\-]*\s*[:=]\s*(?![""']?(?:YOUR_SECRET_HERE|YOUR_VALUE_HERE|YOUR_PASSWORD_HERE)\b)[^#\r\n]+"
    }
  )
}

$root = Resolve-RepoRoot -Given $RepoRoot
Set-Location $root

$tracked = (& git -C $root ls-files)
if ($LASTEXITCODE -ne 0) {
  throw "Unable to list tracked files from git in: $root"
}

$skipExact = @(
  "helpers/sanitize_git_repo.ps1"
)

$changed = New-Object System.Collections.Generic.List[string]
$findings = New-Object System.Collections.Generic.List[string]
$patterns = Get-LeakPatterns

foreach ($relRaw in $tracked) {
  $rel = [string]$relRaw
  if (-not $rel) { continue }
  $relNorm = $rel.Replace("\", "/")
  if ($skipExact -contains $relNorm.ToLowerInvariant()) { continue }
  if (-not (Is-TextCandidate -RelPath $relNorm)) { continue }

  $full = Join-Path $root $rel
  if (-not (Test-Path -LiteralPath $full)) { continue }

  $orig = Read-Text -Path $full
  $now = $orig
  if ($Fix) {
    $now = Sanitize-Text -Text $now
    if ($now -ne $orig) {
      Write-Text -Path $full -Text $now
      $changed.Add($relNorm) | Out-Null
    }
  }

  foreach ($pat in $patterns) {
    if ([regex]::IsMatch($now, $pat.Regex)) {
      $findings.Add("$relNorm :: $($pat.Name)") | Out-Null
    }
  }
}

if (-not $Quiet) {
  Write-Host ""
  Write-Host "== Git Sanitizer =="
  Write-Host "Repo: $root"
  Write-Host ("Files changed by sanitizer: {0}" -f $changed.Count)
  if ($changed.Count -gt 0) {
    $changed | Sort-Object | ForEach-Object { Write-Host "  UPDATED: $_" }
  }
  Write-Host ("Leak findings after sanitize: {0}" -f $findings.Count)
  if ($findings.Count -gt 0) {
    $findings | Sort-Object -Unique | ForEach-Object { Write-Host "  LEAK: $_" }
  }
  Write-Host ""
}

if ($findings.Count -gt 0) {
  exit 2
}

exit 0
