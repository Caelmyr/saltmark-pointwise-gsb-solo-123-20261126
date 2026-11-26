"""Save immutable brick photographs and source footprint settings."""

import json
from pathlib import Path
from threading import RLock
from uuid import uuid4

from image_lab.validation import Conflict, Invalid, identifier, integer, object_value, text

from . import pairing, sample

DEFAULT_PAIRING = {"second": None, "limits": dict(pairing.DEFAULT_LIMITS), "marks": [], "shift": None}


class Cards:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()

    def folder(self, key):
        folder = self.root / identifier(key)
        if not (folder / "card.json").is_file():
            raise Invalid("没有找到这份砖样卡")
        return folder

    def read(self, key, revision=None):
        with self.lock:
            card = json.loads((self.folder(key) / "card.json").read_text())
            card.setdefault("pairing", json.loads(json.dumps(DEFAULT_PAIRING)))
            if revision is not None and integer(revision, "工作版本", 1) != card["revision"]:
                raise Conflict("砖样卡已经改动，请重新打开")
            return card

    def partner(self, key):
        """Resolve and check the saved second card of a pairing."""
        first = self.read(key)
        target = first["pairing"].get("second")
        if target is None:
            raise Invalid("请先为第一张砖样卡选好第二张")
        if target == key:
            raise Invalid("第二张不能是第一张本身")
        return first, self.read(target)

    @staticmethod
    def commit(folder, card):
        stage = folder / (uuid4().hex + ".tmp")
        stage.write_text(json.dumps(card, ensure_ascii=False, allow_nan=False))
        stage.replace(folder / "card.json")

    def list(self):
        with self.lock:
            rows = []
            for path in self.root.glob("*/card.json"):
                card = json.loads(path.read_text())
                rows.append({**{key: card[key] for key in ("id", "name", "synthetic", "revision")},
                             "modified_ns": path.stat().st_mtime_ns})
            return sorted(rows, key=lambda row: (-row["modified_ns"], row["id"]))

    def create(self, name, title, size, data, config, synthetic=False):
        name = text(name, "砖样卡名称", 80, False)
        title = text(title, "原片名称", 140, False)
        with self.lock:
            if len(self.list()) >= 150:
                raise Invalid("砖样卡库已达150份")
            key = uuid4().hex
            folder = self.root / key
            folder.mkdir()
            (folder / "capture.png").write_bytes(data)
            card = {"id": key, "revision": 1, "name": name, "photo_name": title, "synthetic": synthetic,
                    "width": size[0], "height": size[1], "settings": config,
                    "pairing": json.loads(json.dumps(DEFAULT_PAIRING))}
            self.commit(folder, card)
            return card

    def demo(self):
        size, image, config = sample.practice()
        return self.create("练习 · 红砖浅色试样", "合成砖样.png", size, image, config, synthetic=True)

    def update(self, key, value):
        with self.lock:
            card = self.read(key, integer(value.get("revision"), "工作版本", 1))
            incoming = object_value(value.get("settings", {}), "砖样设置")
            config = sample.settings({**card["settings"], **incoming}, (card["width"], card["height"]))
            pairing_value = value.get("pairing")
            if pairing_value is not None:
                card["pairing"] = self.pairing(key, card, object_value(pairing_value, "对位设置"))
            card.update(name=text(value.get("name", card["name"]), "砖样卡名称", 80, False),
                        settings=config, revision=card["revision"] + 1)
            self.commit(self.folder(key), card)
            return card

    def pairing(self, key, card, value):
        """Validate and normalise a card's saved comparison configuration."""
        current = card.get("pairing") or json.loads(json.dumps(DEFAULT_PAIRING))
        second = value.get("second", current["second"])
        if second is not None:
            second = identifier(second)
            if second == key:
                raise Invalid("第二张不能是第一张本身")
            self.folder(second)
        marks = value.get("marks", current["marks"])
        if marks and second is None:
            raise Invalid("保存固定印记前请先选定第二张")
        widths = [card["width"], self.read(second)["width"]] if second else [card["width"], card["width"]]
        shift = value.get("shift", current.get("shift"))
        if shift is not None:
            shift = integer(shift, "采用位移", -card["width"], card["width"])
            if second is None or not marks:
                raise Invalid("采用位移前请先选定第二张并保存固定印记")
        return {
            "second": second,
            "limits": pairing.limits(value.get("limits", current["limits"]), widths),
            "marks": pairing.marks(marks, widths),
            "shift": shift,
        }

    def photo(self, key):
        return self.folder(key) / "capture.png"
