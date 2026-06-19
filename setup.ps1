param(
    [switch]$Ci
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Write-Step {
    param(
        [int]$Current,
        [int]$Total,
        [string]$Title
    )
    Write-Host ""
    Write-Host ("-" * 60)
    Write-Host ("[ {0}/{1} ] {2}" -f $Current, $Total, $Title) -ForegroundColor Cyan
    Write-Host ("-" * 60)
}

function Require-Value {
    param(
        [string]$Prompt,
        [bool]$Secret = $false,
        [string]$Default = ""
    )
    while ($true) {
        if ($Secret) {
            $secure = Read-Host -Prompt $Prompt -AsSecureString
            $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
            try {
                $value = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
            } finally {
                [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
            }
        } else {
            $suffix = if ($Default -ne "") { " [$Default]" } else { "" }
            $inputValue = Read-Host -Prompt "$Prompt$suffix"
            if ([string]::IsNullOrWhiteSpace($inputValue) -and $Default -ne "") {
                $value = $Default
            } else {
                $value = $inputValue
            }
        }
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            return $value.Trim()
        }
        Write-Host "Valeur requise." -ForegroundColor Yellow
    }
}

function Ask-YesNo {
    param(
        [string]$Prompt,
        [bool]$DefaultNo = $true
    )
    $defaultLabel = if ($DefaultNo) { "Y/N (default: N)" } else { "Y/N (default: Y)" }
    $raw = Read-Host -Prompt "$Prompt [$defaultLabel]"
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return (-not $DefaultNo)
    }
    return $raw.Trim().ToLowerInvariant() -in @("y", "yes", "o", "oui")
}

function Ensure-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Add-PathIfNeeded {
    param([string]$PathToAdd)
    if ([string]::IsNullOrWhiteSpace($PathToAdd)) { return }
    if ($env:PATH -notlike "*$PathToAdd*") {
        $env:PATH = "$PathToAdd;$env:PATH"
    }
}

function Get-AvailablePort {
    param([int]$StartPort = 8000, [int]$MaxAttempts = 20)
    for ($port = $StartPort; $port -lt ($StartPort + $MaxAttempts); $port++) {
        $listener = $null
        try {
            $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $port)
            $listener.Start()
            return $port
        } catch {
            continue
        } finally {
            if ($null -ne $listener) { $listener.Stop() }
        }
    }
    return $StartPort
}

function Ensure-JarvisLayout {
    $dirs = @(
        "memory_data/sessions",
        "memory_data/topics",
        "memory_data/conso",
        "memory_data/initiatives",
        "memory_data/curator_reports",
        "vision_data/faces",
        "skills_data/installed",
        "skills_data/candidates",
        "workspace/projects"
    )
    foreach ($dir in $dirs) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
}

function Ensure-Uv {
    if (Ensure-Command "uv") { return }
    Write-Host "uv introuvable, installation..." -ForegroundColor Yellow
    powershell -ExecutionPolicy ByPass -NoProfile -Command "irm https://astral.sh/uv/install.ps1 | iex"
    Add-PathIfNeeded -PathToAdd (Join-Path $env:USERPROFILE ".local\bin")
    Add-PathIfNeeded -PathToAdd (Join-Path $env:USERPROFILE ".cargo\bin")
    if (-not (Ensure-Command "uv")) {
        throw "uv introuvable apres installation."
    }
}

function Get-PythonVersion {
    if (Ensure-Command "python") {
        $raw = & python --version 2>&1 | Select-Object -First 1
        return $raw.ToString()
    }
    if (Ensure-Command "py") {
        $raw = & py -3 --version 2>&1 | Select-Object -First 1
        return $raw.ToString()
    }
    throw "Python 3.11+ introuvable. Installe Python et active l'option Add to PATH."
}

function Invoke-UvSync {
    param([switch]$WithVision)
    $args = @("sync")
    if ($WithVision) { $args += "--extra"; $args += "vision" }
    & uv @args
    if ($LASTEXITCODE -ne 0) {
        if ($WithVision) {
            Write-Host ""
            Write-Host "Echec install vision (dlib). Sur Windows, installe Visual Studio Build Tools" -ForegroundColor Yellow
            Write-Host "avec le workload C++, puis relance: uv sync --extra vision" -ForegroundColor Yellow
            Write-Host "https://visualstudio.microsoft.com/visual-cpp-build-tools/" -ForegroundColor Yellow
        }
        throw "uv sync a echoue (code $LASTEXITCODE)."
    }
}

if ($Ci) {
    Write-Host "JARVIS V3 - setup --Ci (mode non-interactif)" -ForegroundColor Cyan
    Ensure-JarvisLayout
    Write-Host "  Disposition creee (memory_data/, vision_data/, skills_data/)" -ForegroundColor Green
    if (-not (Test-Path ".env")) {
        @"
LLM_PROVIDER=api
API_BACKEND=anthropic
ANTHROPIC_API_KEY=unused-in-fake-llm-mode
ANTHROPIC_MODEL=claude-sonnet-4-6
VOICE_ANTHROPIC_MODEL=claude-haiku-4-5-20251001
USER_FIRSTNAME=B9
HOME_CITY=Paris
MEMORY_DIR=memory_data
PORT=8000
"@ | Set-Content -Path ".env" -Encoding UTF8
        Write-Host "  .env minimal genere" -ForegroundColor Green
    } else {
        Write-Host "  .env pre-existant conserve" -ForegroundColor Green
    }
    Ensure-Uv
    Invoke-UvSync
    Write-Host "setup --Ci OK" -ForegroundColor Green
    exit 0
}

$stepTotal = 8

Write-Host ""
Write-Host "JARVIS v3.0 - Setup interactif (PowerShell)" -ForegroundColor Cyan
Write-Host ""

Write-Step -Current 1 -Total $stepTotal -Title "Verification des prerequis"

$versionText = Get-PythonVersion
$versionMatch = [regex]::Match($versionText, "(\d+)\.(\d+)")
if (-not $versionMatch.Success) {
    throw "Version Python invalide: $versionText"
}
$major = [int]$versionMatch.Groups[1].Value
$minor = [int]$versionMatch.Groups[2].Value
if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) {
    throw "Python $major.$minor detecte, Python 3.11+ requis."
}
Write-Host "Python $major.$minor detecte." -ForegroundColor Green

Ensure-Uv
Write-Host "uv detecte." -ForegroundColor Green

Write-Step -Current 2 -Total $stepTotal -Title "Installation des dependances Python"
$installVision = $false
if (Ask-YesNo -Prompt "Installer la reconnaissance faciale (face-recognition / dlib) ?" -DefaultNo $true) {
    Write-Host "Necessite Visual Studio Build Tools (C++) sur Windows." -ForegroundColor DarkGray
    $installVision = $true
}
Invoke-UvSync -WithVision:$installVision
Write-Host "Dependances installees." -ForegroundColor Green

Write-Step -Current 3 -Total $stepTotal -Title "Configuration LLM principal"
$apiBackend = "anthropic"
$openaiApiKey = ""
$openaiModel = "gpt-4o-mini"
$anthropicApiKey = ""
$anthropicModel = "claude-sonnet-4-6"
if (Ask-YesNo -Prompt "Utiliser OpenAI comme LLM principal ?" -DefaultNo $true) {
    $apiBackend = "openai"
    $openaiApiKey = Require-Value -Prompt "Cle API OpenAI (sk-...)" -Secret $true
} else {
    $anthropicApiKey = Require-Value -Prompt "Cle API Anthropic (sk-ant-...)" -Secret $true
}

Write-Step -Current 4 -Total $stepTotal -Title "Identite utilisateur"
$userFirstname = Require-Value -Prompt "Ton prenom"
Write-Host "Bonjour, $userFirstname" -ForegroundColor Green

Write-Step -Current 5 -Total $stepTotal -Title "Localisation proactive"
$proactiveCity = Require-Value -Prompt "Ville" -Default "Paris"
$proactiveLat = Require-Value -Prompt "Latitude" -Default "48.85"
$proactiveLon = Require-Value -Prompt "Longitude" -Default "2.35"

Write-Step -Current 6 -Total $stepTotal -Title "Modules optionnels"
$ttsProvider = "piper"
$elevenlabsApiKey = ""
$elevenlabsVoiceId = ""
$elevenlabsModel = "eleven_flash_v2_5"
if (Ask-YesNo -Prompt "Utiliser ElevenLabs plutot que Piper ?" -DefaultNo $true) {
    $ttsProvider = "elevenlabs"
    $elevenlabsApiKey = Require-Value -Prompt "Cle ElevenLabs (sk_...)" -Secret $true
    $elevenlabsVoiceId = Require-Value -Prompt "Voice ID ElevenLabs"
}

$livekitUrl = ""
$livekitApiKey = ""
$livekitApiSecret = ""
$deepgramApiKey = ""
if (Ask-YesNo -Prompt "Activer le pipeline vocal LiveKit ?" -DefaultNo $true) {
    if (-not (Ensure-Command "livekit-server")) {
        Write-Host "livekit-server absent." -ForegroundColor Yellow
        Write-Host "Telecharge livekit-server.exe depuis:" -ForegroundColor Yellow
        Write-Host "https://github.com/livekit/livekit/releases" -ForegroundColor Yellow
        Write-Host "Place-le dans un dossier du PATH." -ForegroundColor Yellow
    }
    if (Ask-YesNo -Prompt "Utiliser LiveKit Cloud plutot que le serveur local ?" -DefaultNo $true) {
        $livekitUrl = Require-Value -Prompt "LiveKit URL (wss://...)"
        $livekitApiKey = Require-Value -Prompt "LiveKit API Key" -Secret $true
        $livekitApiSecret = Require-Value -Prompt "LiveKit API Secret" -Secret $true
    } else {
        $livekitUrl = "ws://localhost:7880"
        $livekitApiKey = "devkey"
        $livekitApiSecret = "devsecretdevsecretdevsecretdevsecret"
        Write-Host "LiveKit local (ws://localhost:7880)" -ForegroundColor Green
    }
    $deepgramApiKey = Require-Value -Prompt "Deepgram API Key (STT)" -Secret $true
}

$aisstreamKey = ""
if (Ask-YesNo -Prompt "Configurer AISstream ?" -DefaultNo $true) {
    $aisstreamKey = Require-Value -Prompt "Cle AISstream" -Secret $true
}

Write-Step -Current 7 -Total $stepTotal -Title "Telechargement des modeles ML"
if (-not (Test-Path "yolov8n.pt")) {
    uv run python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"
    if ($LASTEXITCODE -ne 0) { throw "Telechargement YOLOv8 echoue." }
}

$piperDir = "models/piper"
$piperModel = Join-Path $piperDir "fr_FR-upmc-medium.onnx"
$piperJson = "$piperModel.json"
if (-not (Test-Path $piperModel)) {
    New-Item -ItemType Directory -Path $piperDir -Force | Out-Null
    $baseUrl = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/fr/fr_FR/upmc/medium"
    curl.exe -L --silent -o $piperModel "$baseUrl/fr_FR-upmc-medium.onnx"
    curl.exe -L --silent -o $piperJson "$baseUrl/fr_FR-upmc-medium.onnx.json"
}

Write-Step -Current 8 -Total $stepTotal -Title "Generation de l'environnement"
Ensure-JarvisLayout

if (Test-Path ".env") {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    Copy-Item ".env" ".env.backup.$stamp"
}

$serverPort = Get-AvailablePort -StartPort 8000
if ($serverPort -ne 8000) {
    Write-Host "Port 8000 indisponible, utilisation du port $serverPort." -ForegroundColor Yellow
}

$faceRecognitionEnabled = if ($installVision) { "true" } else { "false" }

$envContent = @"
USER_FIRSTNAME=$userFirstname
LLM_PROVIDER=api
API_BACKEND=$apiBackend
ANTHROPIC_API_KEY=$anthropicApiKey
ANTHROPIC_MODEL=$anthropicModel
VOICE_ANTHROPIC_MODEL=claude-haiku-4-5-20251001
OPENAI_API_KEY=$openaiApiKey
OPENAI_MODEL=$openaiModel
HOST=127.0.0.1
PORT=$serverPort
ENVIRONMENT=development
LOG_LEVEL=INFO
PROACTIVE_LAT=$proactiveLat
PROACTIVE_LON=$proactiveLon
PROACTIVE_CITY=$proactiveCity
TTS_PROVIDER=$ttsProvider
ELEVENLABS_API_KEY=$elevenlabsApiKey
ELEVENLABS_VOICE_ID=$elevenlabsVoiceId
ELEVENLABS_MODEL=$elevenlabsModel
WHISPER_MODEL=tiny
LIVEKIT_URL=$livekitUrl
LIVEKIT_API_KEY=$livekitApiKey
LIVEKIT_API_SECRET=$livekitApiSecret
DEEPGRAM_API_KEY=$deepgramApiKey
AISSTREAM_KEY=$aisstreamKey
FACE_RECOGNITION_ENABLED=$faceRecognitionEnabled
MISTRAL_API_KEY=
MISTRAL_MODEL=mistral-large-latest
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=mistral
GOOGLE_API_KEY=
"@

Set-Content -Path ".env" -Value $envContent -Encoding UTF8

Write-Host ""
Write-Host ("=" * 60) -ForegroundColor Cyan
Write-Host "Systeme pret." -ForegroundColor Green
Write-Host "Installation : .\setup.ps1" -ForegroundColor DarkGray
Write-Host "Demarrer tout : .\jarvis.ps1 run" -ForegroundColor White
Write-Host "API seule     : .\jarvis.ps1 api  -> http://localhost:$serverPort/admin" -ForegroundColor White
if (-not [string]::IsNullOrWhiteSpace($livekitUrl)) {
    Write-Host "Voix          : .\jarvis.ps1 voice" -ForegroundColor White
}
Write-Host ""
Write-Host "Reconnaissance faciale : place une photo JPG dans vision_data/faces/" -ForegroundColor DarkGray
Write-Host ("=" * 60) -ForegroundColor Cyan
Write-Host ""
