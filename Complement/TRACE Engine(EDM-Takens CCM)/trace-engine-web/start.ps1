<#
  TRACE Engine Web MVP 启动脚本 (PowerShell)
  ===========================================
  自动检测并安装 npm 依赖，然后启动 NodeJS 服务。
  如需指定 Skill 目录，取消下面 $env 的注释并修改路径。
#>

$ErrorActionPreference = "Stop"
# 确保向控制台输出时使用 UTF-8，避免在 cmd 包装的批处理中出现中文乱码
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $scriptDir

# 工作目录：优先环境变量，其次脚本目录下的 work，若不可写则回退到 TEMP
$workDir = $env:TRACE_WORK_DIR
if (-not $workDir) {
    $scriptWorkDir = Join-Path $scriptDir "work"
    try {
        if (-not (Test-Path $scriptWorkDir)) {
            New-Item -ItemType Directory -Path $scriptWorkDir -Force -ErrorAction Stop | Out-Null
        }
        # 验证是否可写
        $testFile = Join-Path $scriptWorkDir ".write_test"
        [IO.File]::WriteAllText($testFile, "ok")
        Remove-Item $testFile -Force
        $workDir = $scriptWorkDir
    } catch {
        $fallback = Join-Path $env:TEMP "trace-engine-web-work"
        if (-not (Test-Path $fallback)) {
            New-Item -ItemType Directory -Path $fallback -Force | Out-Null
        }
        $workDir = $fallback
    }
}
$logDir = $workDir
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$logFile = Join-Path $logDir "start.log"

function Write-Log($msg, $level = "INFO") {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [$level] $msg"
    Write-Host $line
    try {
        $line | Out-File -FilePath $logFile -Append -Encoding UTF8 -ErrorAction Stop
    } catch {
        # 日志文件不可写时仅输出到控制台，避免启动流程中断
    }
}

Write-Log "启动脚本开始，目录: $scriptDir"

# 检查 Node.js 与 npm
$node = Get-Command node -ErrorAction SilentlyContinue
$npm  = Get-Command npm -ErrorAction SilentlyContinue
if (-not $node) {
    Write-Log "未找到 Node.js，请先安装 Node.js (>= 18) 并添加到 PATH。" "ERROR"
    Read-Host "按 Enter 退出"
    exit 1
}
if (-not $npm) {
    Write-Log "未找到 npm，请检查 Node.js 安装。" "ERROR"
    Read-Host "按 Enter 退出"
    exit 1
}

Write-Log "Node: $(node --version)"
Write-Log "npm:  $(npm --version)"

# 可选：指定成品目录 Skill 路径（注意 trace-engine 子目录）
# $env:TRACE_ENGINE_SKILL_DIR = "G:\git\Annals-of-the-Great-Simplicity-main\Annals-of-the-Great-Simplicity\Complement\TRACE Engine(EDM-Takens CCM)\trace-engine\examples\counterfactual_hybrid"
# 可选：指定工作/输出目录（便于容器化或避免默认目录无写入权限）
# $env:TRACE_WORK_DIR = "$env:TEMP\trace-engine-web"
# 可选：跨域部署时限制 CORS Origin
# $env:TRACE_CORS_ORIGIN = "https://your-domain.com"
# 可选：服务版本号（用于多云识别）
# $env:TRACE_WEB_VERSION = "1.1.0"

Write-Log "检查依赖..."
if (-not (Test-Path node_modules)) {
    Write-Log "首次运行，正在安装 npm 依赖..." "WARN"
    npm install
    if ($LASTEXITCODE -ne 0) {
        Write-Log "npm install 失败，请检查网络连接或 package.json。" "ERROR"
        Read-Host "按 Enter 退出"
        exit 1
    }
}

# 端口冲突检测：默认 3000，若占用则递增尝试
$basePort = 3000
$maxPort = 3020
$port = $basePort
while ($port -le $maxPort) {
    $inUse = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if (-not $inUse) { break }
    Write-Log "端口 $port 已被占用，尝试下一个..." "WARN"
    $port++
}
if ($port -gt $maxPort) {
    Write-Log "端口范围 $basePort~$maxPort 均被占用。" "ERROR"
    Read-Host "按 Enter 退出"
    exit 1
}
$env:PORT = $port

$env:TRACE_WORK_DIR = $workDir
Write-Log "工作目录: $workDir"
Write-Log "启动服务..."
Write-Log "打开浏览器访问 http://localhost:$port"
Write-Log "日志保存在 $logFile"

try {
    npm start
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "服务异常退出，退出码: $exitCode"
    }
} catch {
    Write-Log $_.Exception.Message "ERROR"
    Write-Log "常见原因：端口被占用、Skill 目录不存在、Python 环境缺失。请查看 work/server.log。" "ERROR"
    Read-Host "按 Enter 退出"
    exit 1
}
