"""Dispatch proof: a signed record of what was in the parcel when it was packed.

At packing the merchant photographs the open parcel. A counter (SAM running on this machine, see counter.py) counts the
items. Clearwake writes one signed receipt into the merchant's own receipt chain: PayPal order id, capture id, the items
ordered, the items counted, the SHA-256 of each photo, whether the parcel was sealed, how it was counted, and the policy
hash. The photos stay on the merchant's machine until a dispute needs them.

When a buyer says some items did not arrive, the Evidence agent finds that receipt in the verified log and checks it
against the order and the tracking. Strong proof is sent as evidence; weak proof is never sent, and the policy settles or
escalates instead. The buyer's message is read only as a claim to check. It never decides an amount or an action.
"""
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import shutil

from verdock_core.receipts import line_hash, verify_log

from .counter import CounterError, sha256_file

ACTION = "clearwake.dispatch.recorded"
PHOTO_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
MAX_PHOTO = 10 * 1024 * 1024
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
CLAIM = re.compile(r"\b(?:only\s+)?(\d{1,3})\s+(?:out\s+of|of)\s+(?:the\s+)?(\d{1,3})\b", re.I)


@dataclass
class Assessment:
    strong: bool
    summary: str                       # one line for the ledger and the receipts
    reasons: list = field(default_factory=list)
    record: dict | None = None         # the verified receipt: params, digest, public key
    claim: dict | None = None          # {"received": 2, "of": 3} as the buyer wrote it
    documents: list = field(default_factory=list)   # (name, bytes, content type) of photos whose hashes the receipt lists

    @property
    def partial_claim(self):
        return self.claim is not None and self.claim["received"] < self.claim["of"]


def buyer_claim(dispute):
    """What the buyer says arrived, read from the buyer's own messages: {"received": 2, "of": 3} or None."""
    for message in dispute.get("messages", []) or []:
        if message.get("posted_by") == "BUYER":
            hit = CLAIM.search(str(message.get("content", ""))[:500])
            if hit and int(hit[1]) <= int(hit[2]):
                return {"received": int(hit[1]), "of": int(hit[2])}
    return None


def pack(swarm, counter, order_id, capture_id, items, photos, sealed, ts_ms=None):
    """Count the photos and write the signed dispatch receipt.

    items: {sku: {"ordered": 3, "prompt": "notebook"}}. With several photos the largest count per item is used, so a photo
    that hides one item cannot lower the count. Returns the receipt facts, its digest and the stored photo names."""
    for value in (order_id, capture_id):
        if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
            raise ValueError("Use a valid PayPal order id and capture id.")
    if not items or any(not isinstance(spec.get("ordered"), int) or not 0 < spec["ordered"] < 1000 for spec in items.values()):
        raise ValueError("Each item needs an ordered quantity between 1 and 999.")
    photos = [Path(p) for p in photos]
    if not 1 <= len(photos) <= 6 or any(p.suffix.lower() not in PHOTO_TYPES or p.stat().st_size > MAX_PHOTO for p in photos):
        raise ValueError("Give 1 to 6 photos (jpg or png, up to 10 MB each).")
    folder = swarm.data / "dispatch" / order_id
    folder.mkdir(parents=True, exist_ok=True)
    hashes = []
    for photo in photos:
        digest = sha256_file(photo)
        hashes.append(digest)
        target = folder / f"{digest[:16]}{photo.suffix.lower()}"
        if not target.exists():
            shutil.copyfile(photo, target)
    counted, labels, models, devices, total_ms = {}, set(), set(), set(), 0
    for sku, spec in items.items():
        best = 0
        for photo in photos:
            result = counter.count(photo, spec["prompt"])
            best = max(best, result.count)
            labels.add(result.label); models.add(result.model); devices.add(result.device); total_ms += result.milliseconds
        counted[sku] = best
    if len(labels) != 1:
        raise CounterError("The photos were counted by different methods. Count them again with one backend.")
    params = {"order": order_id, "capture": capture_id, "ordered": {k: v["ordered"] for k, v in items.items()}, "counted": counted,
              "prompts": {k: v["prompt"] for k, v in items.items()}, "images": sorted(set(hashes)), "sealed": bool(sealed),
              "counter": labels.pop(), "model": models.pop(), "device": devices.pop(), "count_ms": total_ms}
    line = swarm.receipt(f"dispatch:{order_id}", ACTION, params, True)
    return {**params, "digest": line_hash(line), "line": line, "public_key": swarm.receipts.public_key, "folder": str(folder)}


def find(swarm, order_id):
    """The newest dispatch receipt for this order in the merchant's log, and whether the whole log verifies."""
    path = Path(swarm.receipts.path)
    if not isinstance(order_id, str) or not IDENTIFIER.fullmatch(order_id) or not path.is_file():
        return None
    verified = verify_log(str(path), swarm.receipts.public_key)["ok"]
    found = None
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            receipt = json.loads(line)
        except ValueError:
            continue
        if receipt.get("action_id") == ACTION and receipt.get("params", {}).get("order") == order_id:
            found = {"params": receipt["params"], "digest": line_hash(line), "ts_ms": receipt["ts_ms"], "verified": verified,
                     "public_key": swarm.receipts.public_key}
    return found


def assess(swarm, order, trackers, claim):
    """Is the dispatch proof strong enough to fight with? None when there is neither a record nor a claim to check."""
    order_id = (order or {}).get("id")
    found = find(swarm, order_id)
    if found is None:
        return None if claim is None else Assessment(False, "weak: no dispatch proof on record for this order", ["no dispatch receipt"], None, claim)
    p, reasons = found["params"], []
    if not found["verified"]:
        reasons.append("the receipt log does not verify")
    for sku, ordered in p["ordered"].items():
        if p["counted"].get(sku) != ordered:
            reasons.append(f"counted {p['counted'].get(sku, 0)} of {ordered} {sku}")
    if not p["ordered"]:
        reasons.append("no items on the record")
    if not p.get("sealed"):
        reasons.append("parcel not recorded as sealed")
    if not p.get("images"):
        reasons.append("no photo on the record")
    shipped = [t for t in trackers if t.get("status") in ("SHIPPED", "DELIVERED")]
    if not shipped:
        reasons.append("no tracking shows it shipped")
    lines = (order or {}).get("items")
    if lines and {i["sku"]: i["quantity"] for i in lines} != p["ordered"]:
        reasons.append("the order lines differ from the dispatch record")
    if claim is not None and claim["of"] != sum(p["ordered"].values()):
        reasons.append(f"the buyer writes of {claim['of']} items, the order has {sum(p['ordered'].values())}")
    record = {"params": p, "digest": found["digest"], "public_key": found["public_key"]}
    if reasons:
        return Assessment(False, "weak: " + "; ".join(reasons), reasons, record, claim)
    counts = ", ".join(f"{p['counted'][k]} of {n} {k}" for k, n in p["ordered"].items())
    carrier = ", ".join(sorted({t.get("carrier", "?") for t in shipped}))
    summary = f"{counts} counted, sealed, receipt {found['digest'][:8]}, {carrier} tracking shipped"
    return Assessment(True, summary, [], record, claim, documents(swarm, order_id, p["images"]))


def documents(swarm, order_id, hashes):
    """The stored photos, only those whose SHA-256 the signed receipt lists."""
    if not IDENTIFIER.fullmatch(order_id):
        return []
    out, folder = [], swarm.data / "dispatch" / order_id
    for path in sorted(folder.glob("*")) if folder.is_dir() else []:
        if path.suffix.lower() in PHOTO_TYPES and path.stat().st_size <= MAX_PHOTO and sha256_file(path) in hashes:
            out.append((f"packing-photo-{path.name}", path.read_bytes(), PHOTO_TYPES[path.suffix.lower()]))
    return out


def evidence_item(assessment):
    """The evidence entry for PayPal's provide-evidence. Notes are 2000 characters at most."""
    p, record = assessment.record["params"], assessment.record
    counts = ", ".join(f"{p['counted'][k]} of {n} {k}" for k, n in p["ordered"].items())
    notes = (f"Dispatch proof recorded when the parcel was packed, before it shipped: {counts} counted, parcel sealed, "
             f"{len(p['images'])} photo(s) with SHA-256 {', '.join(h[:12] for h in p['images'])}. Counted by {p['counter']} on the merchant's own machine. "
             f"Signed receipt {record['digest'][:16]} for order {p['order']} and capture {p['capture']}, verifiable offline with public key {record['public_key'][:16]}.")
    item = {"evidence_type": "OTHER", "notes": notes[:2000]}
    if assessment.documents:
        item["documents"] = [{"name": name} for name, _, _ in assessment.documents]
    return item
