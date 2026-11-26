"""Serve brick coverage observations and the source-photo preparation workspace."""

from io import BytesIO
import os
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request, send_file, url_for

from image_lab import create_app as preparation_app
from image_lab.validation import Invalid, integer, object_value

from . import exports, pairing, sample
from .store import Cards


def download(data, mime, filename):
    return send_file(BytesIO(data), mimetype=mime, max_age=0, download_name=filename, as_attachment=True)


def create_app(directory=None):
    root = Path(directory or os.environ.get("SALTMARK_DATA", ".saltmark-data")).resolve()
    desk = preparation_app(root / "prepare")
    cards = Cards(root / "cards")
    api = Blueprint("saltmark", __name__, url_prefix="/saltmark")

    @desk.get("/")
    def home():
        return render_template("saltmark.html")

    @api.get("/health")
    def health():
        return jsonify(status="ok", app="saltmark")

    @api.get("/cards")
    def listing():
        return jsonify(cards=cards.list())

    @api.post("/cards")
    def create():
        request.max_content_length = 20 * 1024 * 1024
        upload = request.files.get("photo")
        if not upload or not upload.filename:
            raise Invalid("请选择砖样原照")
        size, image = sample.decode(upload.stream.read(sample.MAX_IMAGE_BYTES + 1))
        return jsonify(cards.create(request.form.get("name", ""), Path(upload.filename).name[:140],
                                    size, image, sample.defaults(size))), 201

    @api.post("/practice")
    def practice():
        return jsonify(cards.demo()), 201

    @api.route("/cards/<key>", methods=["GET", "PATCH"])
    def card(key):
        return jsonify(cards.update(key, object_value(request.get_json(silent=True), "砖样卡设置"))
                       if request.method == "PATCH" else cards.read(key))

    @api.get("/cards/<key>/capture.png")
    def capture(key):
        return send_file(cards.photo(key), mimetype="image/png", conditional=True)

    def measurement(key):
        card = cards.read(key, request.args.get("revision"))
        image = sample.pixels(cards.photo(key))
        return card, image, sample.report(image, card["settings"])

    @api.get("/cards/<key>/measurement")
    def measurement_json(key):
        card, _, result = measurement(key)
        return jsonify(revision=card["revision"], **result)

    @api.get("/cards/<key>/probe")
    def probe(key):
        card = cards.read(key, request.args.get("revision"))
        x = integer(request.args.get("x"), "X", 0, card["width"] - 1)
        y = integer(request.args.get("y"), "Y", 0, card["height"] - 1)
        return jsonify(sample.point(sample.pixels(cards.photo(key)), x, y, card["settings"]))

    def sources(key):
        first, second = cards.partner(key)
        first_image = sample.pixels(cards.photo(first["id"]))
        second_image = sample.pixels(cards.photo(second["id"]))
        first_line = pairing.line(first, first_image)
        second_line = pairing.line(second, second_image)
        return first, second, first_image, second_image, first_line, second_line

    @api.get("/cards/<key>/partner.png")
    def partner_capture(key):
        _, second = cards.partner(key)
        return send_file(cards.photo(second["id"]), mimetype="image/png", conditional=True)

    def resolve(first, first_line, second_line, requested=None):
        """Obey the saved limits. An explicit request must fit; a stale saved shift falls back."""
        solved = pairing.solve(first_line, second_line, first["pairing"]["marks"], first["pairing"]["limits"])
        adopted = first["pairing"].get("shift")
        shift = solved["best"]["shift"]
        for candidate_shift, strict in ((requested, True), (adopted, False)):
            if candidate_shift is None:
                continue
            candidate, reason = pairing.evaluate(first_line, second_line, first["pairing"]["marks"],
                                                 first["pairing"]["limits"],
                                                 integer(candidate_shift, "统一位移", -first["width"], first["width"]))
            if candidate is None:
                if strict:
                    raise Invalid(f"该位移不能采用：{reason}")
                continue
            shift, solved["best"] = candidate["shift"], candidate
            break
        solved["selected"] = shift
        return solved

    def head(first, second, first_line, second_line):
        return {"first": {"id": first["id"], "name": first["name"], "revision": first["revision"],
                          "width": first["width"], "height": first["height"],
                          "line": first_line["y"], "settings": first["settings"]},
                "second": {"id": second["id"], "name": second["name"], "revision": second["revision"],
                           "width": second["width"], "height": second["height"],
                           "line": second_line["y"], "settings": second["settings"]}}

    @api.get("/cards/<key>/comparison")
    def comparison(key):
        first, second, first_image, second_image, first_line, second_line = sources(key)
        base = head(first, second, first_line, second_line)
        if not first["pairing"]["marks"]:
            return jsonify(**base, needs="marks", adopted=None, selected=None,
                           limits=first["pairing"]["limits"], marks=[], candidates=[],
                           candidate_count=0, best=None,
                           note="先在第一张与第二张各点一处固定印记，成对保存后才能求解统一位移。")
        try:
            solved = resolve(first, first_line, second_line, request.args.get("shift"))
        except Invalid as error:
            return jsonify(**base, needs="solution", adopted=first["pairing"].get("shift"), selected=None,
                           limits=first["pairing"]["limits"], marks=first["pairing"]["marks"],
                           candidates=[], candidate_count=0, best=None, note=str(error))
        evidence = pairing.evidence(first_image, second_image, first_line, second_line, solved["selected"])
        solved["candidates"] = [{key: row[key] for key in
                                 ("shift", "score", "co_visible", "true_overlap", "mean_residual", "max_residual")}
                                for row in solved["candidates"]]
        return jsonify(**base, adopted=first["pairing"].get("shift"), **solved, evidence=evidence)

    @api.get("/cards/<key>/comparison/probe")
    def comparison_probe(key):
        first, _, first_image, second_image, first_line, second_line = sources(key)
        solved = resolve(first, first_line, second_line, request.args.get("shift"))
        x = integer(request.args.get("x"), "X", 0, first["width"] - 1)
        return jsonify(pairing.probe(first_image, second_image, first_line, second_line,
                                     solved["selected"], x))

    @api.get("/cards/<key>/export/comparison.csv")
    def comparison_csv(key):
        first, second, first_image, second_image, first_line, second_line = sources(key)
        solved = resolve(first, first_line, second_line)
        evidence = pairing.evidence(first_image, second_image, first_line, second_line, solved["selected"],
                                    full=True)
        return download(exports.comparison_table(first, second, solved, evidence),
                        "text/csv", "salt-comparison.csv")

    @api.get("/cards/<key>/export/profile.csv")
    def profile(key):
        _, _, result = measurement(key)
        return download(exports.trace_table(result), "text/csv", "salt-profile.csv")

    @api.get("/cards/<key>/export/proof.png")
    def proof(key):
        card, image, result = measurement(key)
        return download(exports.proof(image, card, result), "image/png", "salt-proof.png")

    @api.get("/cards/<key>/export/observation.zip")
    def bundle(key):
        card, image, result = measurement(key)
        package = exports.package(card, cards.photo(key).read_bytes(), image, result)
        return download(package, "application/zip", f"saltmark-r{card['revision']}.zip")

    @api.post("/cards/<key>/prepare")
    def prepare(key):
        card = cards.read(key, request.args.get("revision"))
        image = sample.pixels(cards.photo(key)).astype("float32") / 255
        services = desk.extensions
        asset = services["assets"].put(image, card["photo_name"])
        project = services["store"].create(f'{card["name"]} · 原片准备')
        services["frames"].add(project["id"], project["revision"], [asset["id"]])
        return jsonify(url=url_for("index", project=project["id"])), 201

    desk.register_blueprint(api)
    return desk
