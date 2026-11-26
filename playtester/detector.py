from io import BytesIO

from PIL import Image, ImageChops, ImageStat


def gray(frame):
    with Image.open(BytesIO(frame)) as im:
        return im.convert("L")


def stable(a, b):
    diff = ImageChops.difference(gray(a), gray(b))
    return ImageStat.Stat(diff).rms[0] < 2.2


def classify(before, frames, point=None, pending=False, writes=False, error=False):
    if error:
        return "runtime_error"
    if pending or len(frames) < 2 or not stable(frames[-2], frames[-1]):
        return "loading_or_animation"
    delta = ImageChops.difference(gray(before), gray(frames[-1]))
    hist = delta.histogram()
    changed = sum(hist[10:]) / (delta.width * delta.height)
    if changed > 0.43:
        return "major_transition"
    if changed > 0.075:
        return "modal_or_panel_change"
    local = 0
    if point:
        x, y = point
        region = delta.crop((max(0, x-24), max(0, y-24), min(delta.width, x+25), min(delta.height, y+25)))
        local = ImageStat.Stat(region).rms[0]
    if sum(hist[8:]) >= 4 or local > 1.5 or writes:
        return "subtle_feedback"
    return "no_visible_change"


def sample(browser, before, point, writes_before):
    frames = []
    for delay in (300, 700, 1200, 1200, 1200):
        browser.page.wait_for_timeout(delay)
        frames.append(browser.screenshot())
        if len(frames) >= 2 and stable(*frames[-2:]) and not browser.pending:
            break
    return frames[-1], classify(before, frames, point, browser.pending,
                                browser.writes != writes_before, browser.fault is not None)

