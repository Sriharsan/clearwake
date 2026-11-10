# Writes the spoken test clips in tests/fixtures/voice/ with Windows SAPI (System.Speech): 16 kHz, 16 bit, mono wav.
# The words each clip says are in tests/fixtures/voice/clips.json. Run: powershell -File scripts/make_voice_fixtures.ps1
Add-Type -AssemblyName System.Speech
$root = Split-Path -Parent $PSScriptRoot
$dir = Join-Path $root "tests\fixtures\voice"
New-Item -ItemType Directory -Force $dir | Out-Null
$clips = Get-Content (Join-Path $dir "clips.json") -Raw | ConvertFrom-Json
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
foreach ($clip in $clips.PSObject.Properties) {
  $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
  $synth.Rate = 0
  $synth.SetOutputToWaveFile((Join-Path $dir ($clip.Name + ".wav")), $format)
  $synth.Speak($clip.Value.say)
  $synth.Dispose()
}
Write-Output ("voice: " + (Get-ChildItem $dir -Filter *.wav | Measure-Object).Count + " clips written")
