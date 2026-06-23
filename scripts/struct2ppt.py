"""
CONTCAR/POSCAR -> PPT
VESTA CLI a/b/c, POSCAR vs CONTCAR side by side, no stretch
"""
import os, subprocess, time, struct as _struct
from pathlib import Path

try:
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN
    HAS_PPTX = True
except ImportError:
    HAS_PPTX = False

VESTA_EXE = r"D:\VESTA-win64\VESTA.exe"

AXIS_VIEWS = {
    "a": ((1, 0, 0), (0, 0, 1)),
    "b": ((0, 1, 0), (0, 0, 1)),
    "c": ((0, 0, 1), (0, 1, 0)),
}


def _png_size(path):
    with open(str(path), "rb") as f:
        f.read(16)
        return _struct.unpack(">I", f.read(4))[0], _struct.unpack(">I", f.read(4))[0]


def _render_one(struct_path, output_dir, zoom=1.7):
    """VESTA CLI render with adaptive backoff (1.0s, 1.5s, 2.5s)"""
    struct_path = Path(struct_path)
    output_dir = Path(output_dir)
    base = output_dir / "_v_base.vesta"

    subprocess.run(["taskkill", "/IM", "VESTA.exe", "/F"], capture_output=True)

    base_ok = False
    for attempt, wait in enumerate([1.0, 1.5, 2.5]):
        subprocess.Popen(
            [VESTA_EXE, "-open", str(struct_path), "-save", str(base), "-close", ""],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(wait)
        subprocess.run(["taskkill", "/IM", "VESTA.exe", "/F"], capture_output=True)
        if base.exists():
            base_ok = True
            break
        print("  [retry {}] base.vesta ({}s)".format(attempt + 1, wait))
    if not base_ok:
        return {}

    content = base.read_text(encoding="utf-8")
    content = content.replace("PROJT 0  0.962", "PROJT 0  {:.3f}".format(zoom))
    i = content.find("LORIENT\n")
    e1 = content.find("\n", i) + 1
    e2 = content.find("\n", e1) + 1
    e3 = content.find("\n", e2) + 1
    e4 = content.find("\n", e3) + 1

    result = {}
    for axis, (v1, v2) in AXIS_VIEWS.items():
        r1 = " {:.6f}  {:.6f}  {:.6f}  0.000000  0.000000  0.000000\n".format(*v1)
        r2 = " {:.6f}  {:.6f}  {:.6f}  0.000000  0.000000  0.000000\n".format(*v2)
        cc = content[:e2] + r1 + r2 + content[e4:]
        vf = output_dir / "_v_{}_{}.vesta".format(axis, struct_path.stem)
        vf.write_text(cc, encoding="utf-8")
        pf = output_dir / "_v_{}_{}.png".format(axis, struct_path.stem)

        ok = False
        for attempt, wait in enumerate([1.0, 1.5, 2.5]):
            subprocess.Popen(
                [VESTA_EXE, "-open", str(vf), "-export_img", str(pf), "-close", str(vf)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            time.sleep(wait)
            subprocess.run(["taskkill", "/IM", "VESTA.exe", "/F"], capture_output=True)
            if pf.exists():
                ok = True
                result[axis] = pf
                break
            print("  [retry {}] {} axis export ({}s)".format(attempt + 1, axis, wait))
        vf.unlink()

    base.unlink()
    return result




def _count_ionic_steps(poscar_dir):
    """读取 .ionic_steps 文件（由 vasp_check 在远程 SSH 检查时写入）
    如果文件不存在（直接运行 struct2ppt），则返回 999 表示“不限制”
    """
    f = Path(poscar_dir) / ".ionic_steps"
    if not f.exists():
        return 999  # 没有约束，默认渲染
    try:
        v = int(f.read_text(encoding="utf-8").strip())
        return v
    except (ValueError, OSError):
        return 999



def add_structure_slides(prs, poscar_dir, zoom=1.7):
    """POSCAR vs CONTCAR comparison per axis, side by side, no stretch"""
    poscar_dir = Path(poscar_dir)
    poscar_f = poscar_dir / "POSCAR"
    contcar_f = poscar_dir / "CONTCAR"
    if not poscar_f.exists() and not contcar_f.exists():
        print("  [!] no structure files")
        return
    label = poscar_dir.name
    out_dir = poscar_dir.parent.parent

    pos = _render_one(poscar_f, out_dir, zoom) if poscar_f.exists() else {}
    # 仅当离子步≥5时才渲染 CONTCAR，否则只显示 POSCAR
    ionic_steps = _count_ionic_steps(poscar_dir)
    render_contcar = contcar_f.exists() and ionic_steps >= 1
    if contcar_f.exists() and not render_contcar:
        print("  [Skip CONTCAR] only {} ionic steps (<5)".format(ionic_steps))
    con = _render_one(contcar_f, out_dir, zoom) if render_contcar else {}

    if not pos and not con:
        print("  [!] render failed")
        return

    for axis in ["a", "b", "c"]:
        p_png = pos.get(axis)
        c_png = con.get(axis)
        if not p_png and not c_png:
            continue

        slide = prs.slides.add_slide(prs.slide_layouts[6])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = RGBColor(0x1E, 0x1E, 0x2E)

        # title
        tb = slide.shapes.add_textbox(Inches(0.3), Inches(0.08), Inches(12.7), Inches(0.35))
        r = tb.text_frame.paragraphs[0].add_run()
        r.text = "{} along {} axis  --  POSCAR vs CONTCAR".format(label, axis)
        r.font.size = Pt(14); r.font.bold = True
        r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        r.font.name = "Arial"

        # calculate aspect-ratio-preserving size
        both = [x for x in [p_png, c_png] if x]
        max_h = 0
        for p in both:
            w, h = _png_size(p)
            ratio = h / w
            if ratio * 5.8 > max_h:
                max_h = ratio * 5.8
        img_w = 5.8
        if max_h > 6.0:
            img_w = 6.0 / max_h * 5.8
            max_h = 6.0

        gap = 0.4
        left_x = (13.333 - (2 * img_w + gap)) / 2  # center

        if p_png:
            lbl = slide.shapes.add_textbox(Inches(left_x), Inches(0.5), Inches(img_w), Inches(0.22))
            l = lbl.text_frame.paragraphs[0].add_run()
            l.text = "POSCAR (before optimization)"
            l.font.size = Pt(9); l.font.bold = True
            l.font.color.rgb = RGBColor(0x90, 0xCA, 0xF9)
            l.font.name = "Arial"
            lbl.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
            slide.shapes.add_picture(str(p_png), Inches(left_x), Inches(0.72), Inches(img_w))
            p_png.unlink()

        if c_png:
            rx = left_x + img_w + gap
            lbl2 = slide.shapes.add_textbox(Inches(rx), Inches(0.5), Inches(img_w), Inches(0.22))
            l2 = lbl2.text_frame.paragraphs[0].add_run()
            l2.text = "CONTCAR (after optimization)"
            l2.font.size = Pt(9); l2.font.bold = True
            l2.font.color.rgb = RGBColor(0xFF, 0xD7, 0x00)
            l2.font.name = "Arial"
            lbl2.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
            slide.shapes.add_picture(str(c_png), Inches(rx), Inches(0.72), Inches(img_w))
            c_png.unlink()

    print("  [OK] POSCAR vs CONTCAR a/b/c added")


def add_to_ppt(pptx_path, poscar_dir=None, poscar=None, contcar=None, zoom=1.7):
    if poscar_dir:
        d = Path(poscar_dir)
        prs = Presentation(str(pptx_path)) if Path(pptx_path).exists() else Presentation()
        print("[PPT] {} ({} pages)".format(pptx_path, len(prs.slides)))
        add_structure_slides(prs, d, zoom=zoom)
        prs.save(str(pptx_path))
        print("[OK] saved ({} pages)".format(len(prs.slides)))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("dir", nargs="?", default=r"D:\Tech-data\poscars\HS\a_Fe2O3_0701\吸附-110_CH_1")
    parser.add_argument("--pptx", default=r"D:\Tech-data\poscars\HS\20260623-vasp_report.pptx")
    parser.add_argument("--zoom", type=float, default=1.7)
    args = parser.parse_args()
    add_to_ppt(args.pptx, poscar_dir=args.dir, zoom=args.zoom)
