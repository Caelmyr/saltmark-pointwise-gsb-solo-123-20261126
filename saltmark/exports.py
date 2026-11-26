"""Export real source colors and selected pale coverage."""
from io import BytesIO, StringIO
from zipfile import ZIP_DEFLATED, ZipFile
import csv
import json

from PIL import Image, ImageDraw

from .photo import png


def trace_table(result):
    target=StringIO()
    writer=csv.writer(target)
    writer.writerow(("x_px","y_px","red","green","blue","luma","lowest_rgb","channel_spread","pale","cluster"))
    for p in result["profile"]:
        writer.writerow((p["x"],p["y"],*p["rgb"],f'{p["brightness"]:.3f}',p["floor"],p["spread"],
                         int(p["pale"]),int(p["cluster"])))
    return target.getvalue().encode()


def proof(image, card, result):
    height,width=image.shape[:2]
    output=Image.new("RGB",(max(430,width),height+88),"#352c2c")
    output.paste(Image.fromarray(image),(0,0))
    cluster=result["cluster"]
    if cluster["spans"]:
        tint=Image.new("RGBA",output.size,(0,0,0,0))
        brush=ImageDraw.Draw(tint)
        for y,x0,x1 in cluster["spans"]:
            brush.line((x0,y,x1,y),fill=(105,226,168,80))
        output=Image.alpha_composite(output.convert("RGBA"),tint).convert("RGB")
    draw=ImageDraw.Draw(output)
    cfg=card["settings"]
    draw.rectangle((cfg["left"],cfg["top"],cfg["right"],cfg["bottom"]),outline="#7ab9ac",width=2)
    if result["profile"]:
        draw.line((cfg["left"],cfg["focus"],cfg["right"],cfg["focus"]),fill="#90a7b6",width=1)
    for p in result["profile"]:
        if p["pale"]:
            draw.point((p["x"],p["y"]),fill="#63e2a4" if p["cluster"] else "#ffe09d")
    adopted=cluster["adopted"]
    if adopted:
        hx,hy=adopted["highest"]["x"],adopted["highest"]["y"]
        draw.line((hx-6,hy,hx+6,hy),fill="#ff9d5c",width=1)
        draw.line((hx,hy-6,hx,hy+6),fill="#ff9d5c",width=1)
        draw.ellipse((hx-3,hy-3,hx+3,hy+3),outline="#ff9d5c",width=1)
    reading=result["reading"]
    detail=(f'Source Y {reading["y"]}: pale {reading["pale_pixels"]}/{reading["pixels"]} ({reading["fraction"]:.2%})'
            if reading else "Current row not within observation window")
    area=result["area"]
    draw.text((14,height+13),detail,fill="#f3eade")
    draw.text((14,height+35),f'Selected area: {area["pale_pixels"]}/{area["pixels"]} ({area["fraction"]:.2%})',
              fill="#e9ca97")
    summary=(f'Rooted cluster: {adopted["pixels"]} px, highest ({adopted["highest"]["x"]}, {adopted["highest"]["y"]}), '
             f'start run {adopted["start_run"]}' if adopted else "No pale cluster rooted on the start line")
    draw.text((14,height+57),summary,fill="#9fdcc0")
    return png(output)


def package(card, original, image, result):
    memory=BytesIO()
    with ZipFile(memory,"w",ZIP_DEFLATED) as stream:
        stream.writestr("brick.png",original)
        stream.writestr("reading.json",json.dumps({"card":card,"reading":result["reading"],"area":result["area"],
                                                   "cluster":result["cluster"]},ensure_ascii=False,indent=2))
        stream.writestr("salt-profile.csv",trace_table(result))
        stream.writestr("salt-proof.png",proof(image,card,result))
    return memory.getvalue()
