r"""Count the items in one packing photo with SAM, on this machine. Runs inside tools/sam/.venv (see tools/sam/README.md).

  tools\sam\.venv\Scripts\python tools\sam\count.py photo.jpg --prompt "notebook" [--overlay out.png] [--save]

Prints one JSON line. With HF_HUB_OFFLINE=1 nothing is fetched: the weights must already be in the Hugging Face cache.

Which model: for a still photo, Meta's image model is SAM 3 (facebook/sam3, sam3.pt). Meta's SAM 3.1 checkpoint
(facebook/sam3.1, sam3.1_multiplex.pt) is the video tracker. --checkpoint can point at any checkpoint file, and the
model name written to the receipt is then that file's name, so a receipt never claims a model that did not run.
"""
import argparse
import hashlib
import json
import os
import sys
import time
from datetime import date


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image")
    parser.add_argument("--prompt", required=True, help="short noun phrase for what to count, for example: notebook")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--device", default=None, help="cpu or cuda; default cuda when present, else cpu")
    parser.add_argument("--checkpoint", default=None, help="path to a checkpoint file instead of facebook/sam3 sam3.pt")
    parser.add_argument("--overlay", default=None, help="write the photo with numbered boxes to this PNG")
    parser.add_argument("--save", action="store_true", help="write <image>.count.json next to the photo (the recorded run)")
    args = parser.parse_args()

    import torch
    import torch._dynamo  # noqa: F401  (loaded before any stand-in exists, so torch never mistakes it for a real Triton)
    from PIL import Image, ImageDraw
    try:
        import triton  # noqa: F401
    except ImportError:
        # No Triton build for Windows. Meta's code imports triton at load time for the video tracker, which counting a still photo
        # never uses. Provide tools/sam/shim only while that code is imported, then take it away again.
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "shim"))
        try:
            from sam3.model.sam3_image_processor import Sam3Processor
            from sam3.model_builder import build_sam3_image_model
        finally:
            sys.path.pop(0)
            for name in [n for n in sys.modules if n == "triton" or n.startswith("triton.")]:
                del sys.modules[name]
    else:
        from sam3.model.sam3_image_processor import Sam3Processor
        from sam3.model_builder import build_sam3_image_model

    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    with open(args.image, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    image = Image.open(args.image).convert("RGB")

    started = time.perf_counter()
    options = {"device": device}
    if args.checkpoint:
        options.update(checkpoint_path=args.checkpoint, load_from_HF=False)
    model = build_sam3_image_model(**options)
    processor = Sam3Processor(model, device=device, confidence_threshold=args.threshold)
    load_ms = int((time.perf_counter() - started) * 1000)

    started = time.perf_counter()
    state = processor.set_image(image)
    state = processor.set_text_prompt(prompt=args.prompt, state=state)
    milliseconds = int((time.perf_counter() - started) * 1000)

    scores = [float(s) for s in state["scores"].tolist()]
    boxes = [[int(round(v)) for v in box] for box in state["boxes"].tolist()]
    if args.overlay:
        canvas = image.copy(); draw = ImageDraw.Draw(canvas)
        for number, box in enumerate(boxes, 1):
            draw.rectangle(box, outline=(255, 64, 64), width=4)
            draw.text((box[0] + 8, box[1] + 6), str(number), fill=(255, 255, 255))
        canvas.save(args.overlay)

    result = {"count": len(scores), "prompt": args.prompt, "threshold_milli": int(args.threshold * 1000),
              "scores_milli": [int(s * 1000) for s in scores], "boxes": boxes, "image_sha256": digest,
              "model": os.path.basename(args.checkpoint) if args.checkpoint else "facebook/sam3 sam3.pt", "device": device,
              "load_ms": load_ms, "milliseconds": milliseconds, "torch": torch.__version__, "threads": torch.get_num_threads(),
              "overlay": args.overlay, "recorded": date.today().isoformat()}
    if args.save:
        with open(args.image + ".count.json", "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=1)
    print(json.dumps(result))


if __name__ == "__main__":
    sys.exit(main())
