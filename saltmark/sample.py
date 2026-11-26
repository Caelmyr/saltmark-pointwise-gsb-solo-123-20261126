"""Read pale, nearly neutral coverage on a photographed brick sample."""
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from image_lab.validation import Invalid, integer

from .photo import decode, pixels, png, MAX_IMAGE_BYTES


LUMA = np.array([0.2126, 0.7152, 0.0722])
REFERENCE_SIZE = 5
REFERENCE_RADIUS = REFERENCE_SIZE // 2
REFERENCE_TOLERANCE = 6
REFERENCE_MINIMUM = 5
RANGE_LIMIT = 255.0
CLIPPED_REASON = "原片已剪裁"
RANGE_REASON = "校正后超出 0–255"
NONE_REASON = None


def settings(value, size):
    width, height = size
    left = integer(value.get("left"),"左界 X",0,width-1)
    top = integer(value.get("top"),"上界 Y",0,height-1)
    reference_x = optional_reference(value.get("reference_x"),"参考 X",width)
    reference_y = optional_reference(value.get("reference_y"),"参考 Y",height)
    if (reference_x is None) != (reference_y is None):
        raise Invalid("参考卡 X、Y 必须同时给出或同时留空")
    return {
        "left":left,"right":integer(value.get("right"),"右界 X",left,width-1),
        "top":top,"bottom":integer(value.get("bottom"),"下界 Y",top,height-1),
        "focus":integer(value.get("focus"),"截线 Y",0,height-1),
        "minimum":integer(value.get("minimum"),"最低RGB分量",1,255),
        "spread":integer(value.get("spread"),"最大通道差",0,254),
        "reference_x":reference_x,"reference_y":reference_y,
    }


def optional_reference(value, label, extent):
    if value is None or value == "":
        return None
    return integer(value, label, 0, extent - 1)


def defaults(size):
    width,height=size
    return settings({"left":width//7,"right":width*6//7,"top":height//5,
                     "bottom":height*4//5,"focus":height//2,"minimum":148,"spread":42,
                     "reference_x":None,"reference_y":None},size)


def pale_components(rgb):
    lowest = rgb.min(axis=-1)
    return lowest, rgb.max(axis=-1) - lowest


def reference_region(x, y, width, height):
    return {"left":max(0,x-REFERENCE_RADIUS),"right":min(width-1,x+REFERENCE_RADIUS),
            "top":max(0,y-REFERENCE_RADIUS),"bottom":min(height-1,y+REFERENCE_RADIUS)}


def frame_gains(rgb):
    """Match R and B to the reference G without touching G itself."""
    values = np.asarray(rgb, dtype=np.float64)
    return np.stack([values[..., 1] / values[..., 0],
                     np.ones(np.shape(values)[:-1]),
                     values[..., 1] / values[..., 2]], axis=-1)


def reference_retention(image, config, gains):
    """Count unclipped frame pixels that stay inside 0–255 under each candidate's gains.

    G is never rescaled, so only the R and B upper limits can reject brick pixels.  Their
    joint 256×256 distribution answers every candidate at once.
    """
    x0,x1,y0,y1 = (config[key] for key in ("left","right","top","bottom"))
    frame = image[y0:y1+1,x0:x1+1].reshape(-1,3)
    base = frame[np.all((frame > 0) & (frame < 255), axis=1)].astype(np.int64)
    if not len(base):
        return np.zeros(len(gains), dtype=np.int64), 0
    histogram = np.bincount(base[:,0] * 256 + base[:,2], minlength=256 * 256).reshape(256,256)
    upper_r = np.floor((RANGE_LIMIT - 1e-9) / gains[:,0]).astype(np.int64).clip(0,255)
    upper_b = np.floor((RANGE_LIMIT - 1e-9) / gains[:,2]).astype(np.int64).clip(0,255)
    retained = np.array([histogram[:r+1,:b+1].sum() for r,b in zip(upper_r,upper_b)],
                        dtype=np.int64)
    return retained, int(len(base))


def choose_reference(image, x, y, config):
    """Pick a representative solid colour from the genuine pixels around a click.

    Only actual pixel colours qualify, so the adopted value stays an observed colour rather
    than a synthetic average.  A colour is eligible when at least five genuine points lie
    within six code levels on every channel.  Eligible colours are ranked by how common they
    are in the neighbourhood together with how many brick-frame pixels keep a judged value
    after their white-balance correction; near-identical neighbours fall back to the one
    closest to the local median.
    """
    height,width = image.shape[:2]
    region = reference_region(x,y,width,height)
    patch = image[region["top"]:region["bottom"]+1,
                  region["left"]:region["right"]+1].reshape(-1,3)
    genuine = patch[np.all((patch > 0) & (patch < 255), axis=1)].astype(np.int64)
    if len(genuine) < REFERENCE_MINIMUM:
        raise Invalid("参考卡 5×5 内至少需要五个未出界、未剪裁的实点")
    candidates = np.unique(genuine, axis=0)
    distance = np.abs(genuine[None,:,:] - candidates[:,None,:])
    support = np.all(distance <= REFERENCE_TOLERANCE, axis=2).sum(axis=1)
    eligible = support >= REFERENCE_MINIMUM
    if not np.any(eligible):
        raise Invalid("参考卡 5×5 内没有五个实点的各通道都在代表值6级以内")
    candidates, support = candidates[eligible], support[eligible]
    gains = frame_gains(candidates).astype(np.float32)
    retained,brick_pixels = reference_retention(image,config,gains)
    common = support / len(genuine)
    keep = retained / brick_pixels if brick_pixels else np.ones(len(candidates))
    merit = common * keep
    median = np.median(genuine, axis=0)
    centrality = np.abs(candidates - median).max(axis=1)
    order = sorted(range(len(candidates)), key=lambda index: (
        -float(merit[index]), -int(support[index]), float(centrality[index]),
        -int(retained[index]), float(gains[index].sum()),
        tuple(int(v) for v in candidates[index])))
    best = order[0]
    return {"x":x,"y":y,"region":region,"rgb":[int(v) for v in candidates[best]],
            "points":int(len(genuine)),"support":int(support[best]),
            "tolerance":REFERENCE_TOLERANCE,"minimum_support":REFERENCE_MINIMUM,
            "gains":[float(v) for v in gains[best]],
            "retained":int(retained[best]),"brick_pixels":int(brick_pixels)}


def reference(image, config):
    if config.get("reference_x") is None:
        return None
    return choose_reference(image, config["reference_x"], config["reference_y"], config)


def corrected_color(rgb, gains):
    return np.asarray(rgb, dtype=np.float64) * np.asarray(gains, dtype=np.float64)


def judge(rgb, corrected):
    """Unjudged pixels stay out of every coverage denominator.

    A point clipped in the source is never measurable; once a reference is adopted, a point
    whose corrected value leaves 0–255 is set aside as well.
    """
    if np.any((rgb == 0) | (rgb == 255)):
        return False, CLIPPED_REASON
    if corrected is not None and np.any(corrected > RANGE_LIMIT):
        return False, RANGE_REASON
    return True, NONE_REASON


def point(image, x, y, config, ref=None):
    if ref is None:
        ref = reference(image, config)
    rgb=image[y,x]
    gains = np.asarray(ref["gains"], dtype=np.float32) if ref else None
    corrected = corrected_color(rgb, gains) if gains is not None else None
    judged, reason = judge(rgb, corrected)
    floor, spread = pale_components(corrected if corrected is not None else rgb)
    floor, spread = float(floor), float(spread)
    inside = config["left"] <= x <= config["right"] and config["top"] <= y <= config["bottom"]
    return {
        "x":x,"y":y,"inside":bool(inside),"rgb":rgb.tolist(),"brightness":float(rgb@LUMA),
        "corrected":[float(v) for v in corrected] if corrected is not None else None,
        "judged":bool(judged),"reason":reason,
        "floor":floor,"spread":spread,
        "pale":bool(judged and floor >= config["minimum"] and spread <= config["spread"])
                if inside else None,
    }


def profile(image, config, ref=None):
    if ref is None:
        ref = reference(image, config)
    y=config["focus"]
    if not config["top"] <= y <= config["bottom"]:
        return []
    return [point(image,x,y,config,ref) for x in range(config["left"],config["right"]+1)]


def row_metrics(tiles, config, gains):
    """Pale counts per row over the judged denominator defined by the adopted reference."""
    judged = ~np.any((tiles == 0) | (tiles == 255), axis=2)
    if gains is not None:
        corrected = tiles.astype(np.float32) * gains
        judged &= np.all(corrected <= RANGE_LIMIT, axis=2)
        floor,spread = pale_components(corrected)
    else:
        floor,spread = pale_components(tiles)
    qualifies = judged & (floor >= config["minimum"]) & (spread <= config["spread"])
    return qualifies, judged


def report(image, config):
    x0,x1,y0,y1=(config[key] for key in ("left","right","top","bottom"))
    ref = reference(image, config)
    gains = np.asarray(ref["gains"], dtype=np.float32) if ref else None
    width = x1 - x0 + 1
    metrics = []
    covered = judged_area = 0
    coverage = row_metrics(image[y0:y1+1,x0:x1+1], config, gains)
    qualifies, judged = coverage
    counts = np.count_nonzero(qualifies, axis=1)
    judged_rows = np.count_nonzero(judged, axis=1)
    for index,y in enumerate(range(y0,y1+1)):
        count = int(counts[index])
        judged_count = int(judged_rows[index])
        covered += count
        judged_area += judged_count
        metrics.append({"y":y,"pale_pixels":count,"pixels":judged_count,
                        "unjudged_pixels":width-judged_count,"total_pixels":width,
                        "fraction":count/judged_count if judged_count else 0.0})
    points=profile(image,config,ref)
    reading=metrics[config["focus"]-y0] if points else None
    total=int(judged.size)
    return {"reading":reading,"profile":points,"rows":metrics,"focus":config["focus"],
            "reference":ref,
            "area":{"pixels":judged_area,"pale_pixels":covered,
                    "fraction":covered/judged_area if judged_area else 0.0,
                    "total_pixels":total,"unjudged_pixels":total-judged_area}}


def practice():
    width,height=784,468
    cfg=settings({"left":146,"right":631,"top":121,"bottom":345,"focus":148,
                  "minimum":148,"spread":42,
                  "reference_x":641,"reference_y":368},(width,height))
    y,x=np.indices((height,width))
    face=(97 <= x)&(x <= 694)&(76 <= y)&(y <= 395)
    noise=5.1*np.sin(0.59*x-0.78*y)+4.4*np.sin(1.32*x+0.95*y)+2.3*np.sin(0.18*x+0.07*y)
    cast=10*np.cos((x-311)/104)-7*np.sin(y/49)
    variations=(.77*np.exp(-((x-326)/144)**2-((y-260)/55)**2)
                +.78*np.exp(-((x-517)/51)**2-((y-274)/64)**2)
                +.51*np.exp(-((x-223)/92)**2-((y-165)/34)**2))
    branches=(0.32*np.exp(-((x-384-0.51*(y-235))/3.6)**2)*np.exp(-((y-235)/65)**2)
              +.26*np.exp(-((x-578+.37*(y-254))/5.2)**2)*np.exp(-((y-255)/73)**2))
    grains=0.14*np.sin(x*.65)*np.sin(y*.79)+.095*np.sin(.29*x+.51*y)+.10*np.cos(.059*x-.19*y)
    amount=np.clip((variations+branches+grains-.32)*1.95,0,1)
    brick=np.array([173,110,81])+cast[...,None]+noise[...,None]
    bloom=np.array([221,216,198])+0.57*cast[...,None]+0.67*noise[...,None]
    surface=brick*(1-amount[...,None])+bloom*amount[...,None]
    outside=np.array([56,61,64])+.53*noise[...,None]
    image=np.where(face[...,None],surface,outside)
    # A neutral card carried in the same warm-lit frame: its R/B measure the lamp cast.
    card=(621 <= x)&(x <= 661)&(350 <= y)&(y <= 386)
    card_color=np.array([206,196,164])+.9*noise[...,None]
    image=np.where(card[...,None],card_color,image)
    photo=Image.fromarray(image.clip(0,255).astype("uint8"),"RGB")
    draw=ImageDraw.Draw(photo)
    draw.rounded_rectangle((97,76,694,395),radius=7,outline="#a58071",width=2)
    draw.rectangle((621,350,661,386),outline="#e4dbc6",width=1)
    draw.text((102,36),"BRICK COUPON / PALE DEPOSITS",fill="#e1d1c5",font=ImageFont.load_default(size=14))
    draw.text((102,427),"SIMULATED BRICK PHOTO",fill="#d5c6b8",font=ImageFont.load_default(size=12))
    draw.text((626,356),"N",fill="#6d6455",font=ImageFont.load_default(size=10))
    return photo.size,png(photo),cfg
