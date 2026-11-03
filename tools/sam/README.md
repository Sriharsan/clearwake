# SAM for the dispatch proof

Clearwake counts the items in a packing photo with Meta's Segment Anything Model, **on the merchant's own machine**. The photo and the count never go to an outside AI service. This folder holds the counting script and the one time setup. The Clearwake app itself still runs on the Python standard library alone: SAM lives in its own environment (`tools/sam/.venv`, ignored by git) and is called as a separate process.

## Which model counts what

* **Still photos use SAM 3** (`facebook/sam3`, file `sam3.pt`). Meta's image code, `build_sam3_image_model`, loads this checkpoint.
* **SAM 3.1** (released 27 March 2026, `facebook/sam3.1`, file `sam3.1_multiplex.pt`) adds Object Multiplex, a faster way to track many objects in **video**. Meta's release notes describe it as a video tracking change. Clearwake does not claim to count photos with SAM 3.1. If you pass `--checkpoint` to `count.py`, the receipt names that file, so a receipt never claims a model that did not run.
* The name of what ran, the device and the time in milliseconds are written into every dispatch receipt.

## One time setup (you run it, on your machine)

1. On Hugging Face, logged in as you: request access at https://huggingface.co/facebook/sam3 (needed) and https://huggingface.co/facebook/sam3.1 (optional). Both are gated: Meta's terms apply and Hugging Face shares your profile information with Meta.
2. Create a read token at https://huggingface.co/settings/tokens and add one line to the repository's `.env`: `HF_TOKEN=hf_...`. The token is read only by `setup.ps1`, is never printed and is removed from the environment after the download.
3. From the repository root: `.\tools\sam\setup.ps1` (add `-Also31` to fetch the 3.1 checkpoint too).
4. The script counts a test picture at the end and prints the result with real timings.

It installs CPU PyTorch from download.pytorch.org and Meta's code from https://github.com/facebookresearch/sam3, both into `tools/sam/.venv`, and downloads about 3.5 GB of weights to a folder next to the repository (`..\_hf`).

## Two things Meta's code needs that it does not list

* `einops`, `pycocotools` and `psutil` are imported at load time but are not in its dependency list; `setup.ps1` installs them.
* Meta imports `triton` at load time, and Triton has no Windows build. It is used by the video tracker and by GPU fallbacks, not by counting items in a still photo. `tools/sam/shim/` holds a stand-in that `count.py` puts on the path only while Meta's code is imported and removes afterwards. Calling a Triton kernel through it raises an error instead of pretending to work. On a machine with a real Triton the stand-in is not used.

## A small CPU patch

Meta's code assumes a GPU in a few places: it creates tensors on `"cuda"`, pins memory, and forces a bfloat16 kernel for one layer. `tools/sam/cpu.patch` (about 20 lines, in 5 files of Meta's `sam3` package) makes those pick the CPU when there is no GPU, and use plain float32 there. `setup.ps1` applies it to the local clone only. On a machine with a GPU the original code paths still run. Clearwake does not redistribute Meta's code, only this patch, which is its own work.

## CPU only

Meta's README lists a CUDA GPU as a prerequisite. This code path takes `device="cpu"` and Clearwake uses it, so on a machine without a GPU counting is slower. Real timings from the run on this machine are in `docs/RESULTS.md`. Nothing about the receipt depends on speed.

## Offline

Counting sets `HF_HUB_OFFLINE=1`. After the download, unplug the network and it still counts. The public site never runs SAM.

## License

SAM Materials are under the SAM License (https://github.com/facebookresearch/sam3/blob/main/LICENSE, last updated 19 November 2025). In short: use, copy and modify are granted; anyone you pass the SAM Materials to gets the same license and a copy of it; research you publish must acknowledge SAM; use must follow applicable laws including trade controls; do not reverse engineer. Clearwake does not redistribute the weights or Meta's code. It is credited in `docs/THIRD_PARTY.md`:

> Carion et al., "SAM 3: Segment Anything with Concepts", arXiv:2511.16719, 2025.
