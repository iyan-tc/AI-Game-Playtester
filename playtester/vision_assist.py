from dataclasses import dataclass
from io import BytesIO
from typing import Protocol

from PIL import Image, ImageDraw

from .security import atomic, dump


@dataclass(frozen=True)
class Hotspot:
    x: float
    y: float
    label: str


class HotspotProvider(Protocol):
    def get_hotspots(self, page) -> list[Hotspot]: ...


class NullHotspotProvider:
    def get_hotspots(self, page):
        return []


def grid(frame):
    image = Image.open(BytesIO(frame)).convert("RGB")
    draw = ImageDraw.Draw(image, "RGBA")
    w, h = image.size
    for i in range(11):
        x = round((w-1)*i/10)
        draw.line((x, 0, x, h), fill=(60, 190, 255, 145))
        draw.text((min(x+2, w-20), 2), f"{i/10:.1f}", fill="white", stroke_width=1, stroke_fill="black")
    for j in range(21):
        y = round((h-1)*j/20)
        draw.line((0, y, w, y), fill=(255, 178, 40, 145))
        draw.text((2, min(y+2, h-12)), f"{j/20:.2f}", fill="white", stroke_width=1, stroke_fill="black")
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def evidence(folder, step, frame, point, reason, source):
    base = f"screenshots/assist/step_{step:03}"
    (folder / (base + "_raw.png")).write_bytes(frame)
    image = Image.open(BytesIO(frame)).convert("RGB")
    if point is not None:
        x, y = point
        draw = ImageDraw.Draw(image)
        draw.ellipse((x-9, y-9, x+9, y+9), outline="red", width=3)
    image.save(folder / (base + "_point.png"))
    atomic(folder / (base + ".json"), dump(dict(reason=reason, point=point, source=source)))
    return base

