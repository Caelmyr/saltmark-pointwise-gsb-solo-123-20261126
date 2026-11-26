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
    writer.writerow(("x_px","y_px","red","green","blue","luma","lowest_rgb","channel_spread","pale"))
    for p in result["profile"]:
        writer.writerow((p["x"],p["y"],*p["rgb"],f'{p["brightness"]:.3f}',p["floor"],p["spread"],int(p["pale"])))
    return target.getvalue().encode()


def comparison_table(first, second, solved, evidence):
    target=StringIO()
    writer=csv.writer(target)
    writer.writerow(("first_x","first_y","first_red","first_green","first_blue","first_pale",
                     "second_x","second_y","second_red","second_green","second_blue","second_pale","status"))
    for pair in evidence["points"]:
        a,b=pair["first"],pair["second"]
        writer.writerow((a["x"],a["y"],*a["rgb"],int(a["pale"]),b["x"],b["y"],*b["rgb"],int(b["pale"]),pair["status"]))
    counts=evidence["counts"]
    writer.writerow(())
    writer.writerow(("shift_px",solved["selected"],"co_visible",counts["co_visible"],
                     "true_overlap",solved["best"]["true_overlap"],"max_residual",solved["best"]["max_residual"],
                     "added",counts["added"],"reduced",counts["reduced"],
                     "unchanged",counts["unchanged"],"unproven",counts["unproven"]))
    return target.getvalue().encode()


def proof(image, card, result):
    height,width=image.shape[:2]
    output=Image.new("RGB",(max(430,width),height+64),"#352c2c")
    output.paste(Image.fromarray(image),(0,0))
    draw=ImageDraw.Draw(output)
    cfg=card["settings"]
    draw.rectangle((cfg["left"],cfg["top"],cfg["right"],cfg["bottom"]),outline="#7ab9ac",width=2)
    if result["profile"]:
        draw.line((cfg["left"],cfg["focus"],cfg["right"],cfg["focus"]),fill="#90a7b6",width=1)
    for p in result["profile"]:
        if p["pale"]:
            draw.point((p["x"],p["y"]),fill="#ffe09d")
    reading=result["reading"]
    detail=(f'Source Y {reading["y"]}: pale {reading["pale_pixels"]}/{reading["pixels"]} ({reading["fraction"]:.2%})'
            if reading else "Current row not within observation window")
    area=result["area"]
    draw.text((14,height+13),detail,fill="#f3eade")
    draw.text((14,height+35),f'Selected area: {area["pale_pixels"]}/{area["pixels"]} ({area["fraction"]:.2%})',
              fill="#e9ca97")
    return png(output)


def package(card, original, image, result):
    memory=BytesIO()
    with ZipFile(memory,"w",ZIP_DEFLATED) as stream:
        stream.writestr("brick.png",original)
        stream.writestr("reading.json",json.dumps({"card":card,"reading":result["reading"],"area":result["area"]},
                                                  ensure_ascii=False,indent=2))
        stream.writestr("salt-profile.csv",trace_table(result))
        stream.writestr("salt-proof.png",proof(image,card,result))
    return memory.getvalue()
