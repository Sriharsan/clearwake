# One time setup of SAM on this machine, for the dispatch proof (counting items in a packing photo).
# Run it yourself in a terminal from the repository root:   .\tools\sam\setup.ps1
#
# It: (1) makes tools\sam\.venv with Python 3.12, (2) installs CPU PyTorch from download.pytorch.org,
# (3) clones Meta's code from https://github.com/facebookresearch/sam3 next to this repository and installs it into that
# environment only, (4) downloads the SAM 3 weights from Hugging Face with the token in .env, (5) counts one test picture.
# The weights land in a folder next to the repository (..\_hf) so the system drive is not filled. After step 4 counting runs offline.
# Nothing here changes the Clearwake app, which keeps running on the Python standard library alone.
#
# Before you run it, on Hugging Face (while logged in as yourself):
#   * request access at https://huggingface.co/facebook/sam3   (needed: still photos use this model)
#   * request access at https://huggingface.co/facebook/sam3.1 (optional: this is the video tracker)
#   * create a read token at https://huggingface.co/settings/tokens and add one line to this repository's .env:   HF_TOKEN=hf_...
param([switch]$Also31)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$venv = Join-Path $PSScriptRoot '.venv'
$py = Join-Path $venv 'Scripts\python.exe'
$source = Join-Path (Split-Path $repo -Parent) 'sam3-src'
$hf = Join-Path (Split-Path $repo -Parent) '_hf'

# the token comes from .env and is never printed
$token = $null
foreach ($line in (Get-Content (Join-Path $repo '.env') -ErrorAction SilentlyContinue)) { if ($line -match '^HF_TOKEN=(.+)$') { $token = $Matches[1].Trim() } }
if (-not $token) { throw 'Add HF_TOKEN=... to .env first (see the notes at the top of this script).' }

if (-not (Test-Path $py)) { py -3.12 -m venv $venv }
& $py -m pip install --upgrade pip 'setuptools<81' wheel
& $py -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
if (-not (Test-Path $source)) { git clone --depth 1 https://github.com/facebookresearch/sam3.git $source }
& $py -m pip install -e $source pillow

$env:HF_HOME = $hf
$env:HF_TOKEN = $token
$fetch = "from huggingface_hub import hf_hub_download as d; [d('facebook/sam3', f) for f in ('config.json', 'sam3.pt')]"
if ($Also31) { $fetch += "; [d('facebook/sam3.1', f) for f in ('config.json', 'sam3.1_multiplex.pt')]" }
& $py -c $fetch
Remove-Item Env:HF_TOKEN

$env:HF_HUB_OFFLINE = '1'   # from here on nothing is fetched
& $py (Join-Path $PSScriptRoot 'count.py') (Join-Path $repo 'fixtures\dispatch\parcel-3-items.png') --prompt notebook
Write-Host "`nSAM is ready. Counting runs offline. Pack a parcel: python scripts\dispatch.py pack --help"
