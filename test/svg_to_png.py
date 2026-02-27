"""Convert SVG files to PNG using Selenium + Edge headless."""
import os
import time
import base64
import re

from selenium import webdriver
from selenium.webdriver.edge.options import Options

IMAGES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "images")


def svg_to_png(svg_path, png_path, scale=2):
    with open(svg_path, "r", encoding="utf-8") as f:
        svg_content = f.read()

    vb = re.search(r'viewBox="0 0 (\d+) (\d+)"', svg_content)
    if not vb:
        print(f"  ERROR: no viewBox in {svg_path}")
        return False
    w, h = int(vb.group(1)), int(vb.group(2))
    pw, ph = w * scale, h * scale

    html = f"""<!DOCTYPE html>
<html><head><style>
  * {{ margin:0; padding:0; }}
  body {{ background: transparent; width:{pw}px; height:{ph}px; overflow:hidden; }}
  svg {{ width:{pw}px; height:{ph}px; display:block; }}
</style></head><body>
{svg_content}
</body></html>"""

    html_b64 = base64.b64encode(html.encode("utf-8")).decode("ascii")
    data_url = f"data:text/html;base64,{html_b64}"

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument(f"--window-size={pw},{ph}")
    opts.add_argument("--force-device-scale-factor=1")
    opts.add_argument("--hide-scrollbars")

    print(f"  Launching Edge headless ({pw}x{ph}) ...")
    driver = webdriver.Edge(options=opts)
    try:
        driver.set_window_size(pw, ph)
        driver.get(data_url)
        time.sleep(2)

        result = driver.execute_cdp_cmd("Page.captureScreenshot", {
            "format": "png",
            "captureBeyondViewport": True,
            "clip": {"x": 0, "y": 0, "width": pw, "height": ph, "scale": 1},
        })
        png_data = base64.b64decode(result["data"])

        with open(png_path, "wb") as f:
            f.write(png_data)

        size_kb = len(png_data) / 1024
        print(f"  OK: {png_path} ({pw}x{ph}, {size_kb:.0f} KB)")
        return True
    finally:
        driver.quit()


if __name__ == "__main__":
    for name in ["architecture", "runtime_flow"]:
        svg = os.path.join(IMAGES_DIR, f"{name}.svg")
        png = os.path.join(IMAGES_DIR, f"{name}.png")
        if os.path.exists(svg):
            print(f"Converting {name}.svg ...")
            svg_to_png(svg, png, scale=2)
        else:
            print(f"  SKIP: {svg} not found")
