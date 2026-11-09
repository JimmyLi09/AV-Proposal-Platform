"""后台读上传的文件、资料库扫描、标注页渲染页面可能同时进行。PDF 页面渲染（pdfplumber 的 to_image 用 PDFium）在几个线程里
同时跑会让服务器进程崩溃（段错误）。在单独的进程里用 8 个线程同时读样本 PDF（文字层截图、扫描件整页渲染后识别，
既走上传读取也走资料库读取），进程要正常结束。"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = r"""
import sys, threading
from pathlib import Path
from app.extract.run import extract
from app.knowledge.read import read

samples, out = Path("tests/fixtures/samples"), Path(sys.argv[1])
files = ["Lobby_Elevation_RevB.pdf", "Scanned_Plan.pdf"]
errors = []

def work(i):
    for r in range(6):
        path = samples / files[(i + r) % 2]
        try:
            if (i + r) % 3 == 2:
                read(path, None)
            else:
                extract(path, "pdf", out, f"t{i}/r{r}", None)
        except Exception as e:
            errors.append(repr(e))

threads = [threading.Thread(target=work, args=(i,)) for i in range(8)]
for t in threads:
    t.start()
for t in threads:
    t.join()
print("ok" if not errors else errors)
"""


def test_concurrent_pdf_reads_do_not_crash_the_server(tmp_path):
    r = subprocess.run([sys.executable, "-X", "faulthandler", "-c", SCRIPT, str(tmp_path)], cwd=ROOT,
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr[-3000:]
    assert r.stdout.strip() == "ok"
