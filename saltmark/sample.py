"""Read pale, nearly neutral coverage on a photographed brick sample."""
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage as ndi

from image_lab.validation import integer

from .photo import decode, pixels, png, MAX_IMAGE_BYTES


LUMA = np.array([0.2126, 0.7152, 0.0722])
CROSS = ndi.generate_binary_structure(2, 1)
MIN_START_RUN = 4


def settings(value, size):
    width, height = size
    left = integer(value.get("left"),"左界 X",0,width-1)
    top = integer(value.get("top"),"上界 Y",0,height-1)
    return {
        "left":left,"right":integer(value.get("right"),"右界 X",left,width-1),
        "top":top,"bottom":integer(value.get("bottom"),"下界 Y",top,height-1),
        "focus":integer(value.get("focus"),"截线 Y",0,height-1),
        "minimum":integer(value.get("minimum"),"最低RGB分量",1,255),
        "spread":integer(value.get("spread"),"最大通道差",0,254),
    }


def defaults(size):
    width,height=size
    return settings({"left":width//7,"right":width*6//7,"top":height//5,
                     "bottom":height*4//5,"focus":height//2,"minimum":148,"spread":42},size)


def pale_components(rgb):
    lowest = rgb.min(axis=-1)
    return lowest, rgb.max(axis=-1) - lowest


def true_marks(tiles, config):
    """Pixels usable as pale marks or bridges: thresholds met, no channel clipped at 0 or 255."""
    floor, spread = pale_components(tiles)
    return (floor >= config["minimum"]) & (spread <= config["spread"]) & (floor > 0) & (tiles.max(axis=-1) < 255)


def longest_run(values):
    best = current = 0
    previous = None
    for value in sorted(values):
        current = current + 1 if previous is not None and value == previous + 1 else 1
        best = max(best, current)
        previous = value
    return best


def scaled(value, values):
    span = max(values) - min(values)
    return 1.0 if span == 0 else (value - min(values)) / span


def trace_clusters(image, config):
    """4-connected pale clusters inside the frame, on the start line and above it."""
    x0, x1, y0 = (config[key] for key in ("left","right","top"))
    y1 = min(config["focus"], config["bottom"])
    found = []
    labels = None
    if y1 >= y0:
        marks = true_marks(image[y0:y1+1, x0:x1+1], config)
        labels, _ = ndi.label(marks, CROSS)
        start_row = config["focus"] - y0
        for cid, box in enumerate(ndi.find_objects(labels), start=1):
            if box is None:
                continue
            ys, xs = np.nonzero(labels[box] == cid)
            ys = ys + box[0].start
            xs = xs + box[1].start
            top = int(ys.min())
            highest_x = xs[ys == top]
            found.append({"id":cid, "pixels":int(ys.size), "top_y":y0+top,
                          "reach":config["focus"]-y0-top, "edge":bool(xs.min() == 0 or xs.max() == x1-x0),
                          "start_run":longest_run(xs[ys == start_row].tolist()),
                          "highest":{"x":x0+int(highest_x[highest_x.size//2]), "y":y0+top}})
    candidates = [c for c in found if not c["edge"] and c["start_run"] >= MIN_START_RUN]
    adopted = None
    if candidates:
        reaches = [c["reach"] for c in candidates]
        areas = [c["pixels"] for c in candidates]
        for c in candidates:
            c["score"] = round(0.5*scaled(c["reach"], reaches) + 0.5*scaled(c["pixels"], areas), 6)
        adopted = max(candidates, key=lambda c: (c["score"], c["pixels"], c["reach"], -c["id"]))
    spans = []
    mask = None
    if adopted is not None:
        mask = labels == adopted["id"]
        for dy, row in enumerate(mask):
            xs = np.nonzero(row)[0]
            if xs.size:
                cuts = np.nonzero(np.diff(xs) > 1)[0]
                spans += [[y0+dy, x0+int(xs[s]), x0+int(xs[e])]
                          for s, e in zip(np.concatenate(([0], cuts+1)), np.concatenate((cuts, [xs.size-1])))]
    rejected = {"edge_touching":sum(1 for c in found if c["edge"]),
                "short_start":sum(1 for c in found if not c["edge"] and c["start_run"] < MIN_START_RUN)}
    for c in candidates:
        c["adopted"] = c is adopted
        del c["edge"]
    info = {"start_y":config["focus"], "candidates":candidates, "adopted":adopted, "spans":spans,
            "rejected":rejected}
    return mask, info


def point(image, x, y, config):
    rgb=image[y,x]
    floor, spread = pale_components(rgb)
    inside = config["left"] <= x <= config["right"] and config["top"] <= y <= config["bottom"]
    return {
        "x":x,"y":y,"rgb":rgb.tolist(),"brightness":float(rgb@LUMA),
        "floor":int(floor),"spread":int(spread),
        "pale":bool(floor >= config["minimum"] and spread <= config["spread"]) if inside else None,
    }


def profile(image, config):
    y=config["focus"]
    if not config["top"] <= y <= config["bottom"]:
        return []
    return [point(image,x,y,config) for x in range(config["left"],config["right"]+1)]


def report(image, config):
    x0,x1,y0,y1=(config[key] for key in ("left","right","top","bottom"))
    tiles=image[y0:y1+1,x0:x1+1]
    floor,spread=pale_components(tiles)
    qualifies = (floor >= config["minimum"]) & (spread <= config["spread"])
    counts = np.count_nonzero(qualifies, axis=1)
    width = tiles.shape[1]
    mask, cluster = trace_clusters(image, config)
    metrics = []
    for y,count in zip(range(y0,y1+1),counts):
        row = y-y0
        rooted = int(np.count_nonzero(mask[row])) if mask is not None and row < mask.shape[0] else 0
        metrics.append({"y":y,"pale_pixels":int(count),"pixels":width,"fraction":int(count)/width,
                        "cluster_pixels":rooted})
    points=profile(image,config)
    if points:
        row = config["focus"]-y0
        for p in points:
            p["cluster"] = bool(mask is not None and mask[row,p["x"]-x0])
    reading=metrics[config["focus"]-y0] if points else None
    area=int(qualifies.size)
    covered=int(counts.sum())
    return {"reading":reading,"profile":points,"rows":metrics,"focus":config["focus"],
            "area":{"pixels":area,"pale_pixels":covered,"fraction":covered/area},
            "cluster":cluster}


def practice():
    width,height=784,468
    cfg=settings({"left":146,"right":631,"top":121,"bottom":345,"focus":148,
                  "minimum":148,"spread":42},(width,height))
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
    image=Image.fromarray(np.where(face[...,None],surface,outside).clip(0,255).astype("uint8"),"RGB")
    draw=ImageDraw.Draw(image)
    draw.rounded_rectangle((97,76,694,395),radius=7,outline="#a58071",width=2)
    draw.text((102,36),"BRICK COUPON / PALE DEPOSITS",fill="#e1d1c5",font=ImageFont.load_default(size=14))
    draw.text((102,427),"SIMULATED BRICK PHOTO",fill="#d5c6b8",font=ImageFont.load_default(size=12))
    return image.size,png(image),cfg
