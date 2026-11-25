"""Read pale, nearly neutral coverage on a photographed brick sample."""
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from image_lab.validation import integer

from .photo import decode, pixels, png, MAX_IMAGE_BYTES


LUMA = np.array([0.2126, 0.7152, 0.0722])


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
    metrics = [{"y":y,"pale_pixels":int(count),"pixels":width,"fraction":int(count)/width}
               for y,count in zip(range(y0,y1+1),counts)]
    points=profile(image,config)
    reading=metrics[config["focus"]-y0] if points else None
    area=int(qualifies.size)
    covered=int(counts.sum())
    return {"reading":reading,"profile":points,"rows":metrics,"focus":config["focus"],
            "area":{"pixels":area,"pale_pixels":covered,"fraction":covered/area}}


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
