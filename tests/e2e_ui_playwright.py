# -*- coding: utf-8 -*-
"""Vision Skill Builder 端到端联动验证 v2"""
import glob, json, sys, time
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:6122/"
OUT = r"C:\Users\83915\WorkBuddy\2026-08-14-14-14-51"
results = []

def check(name, ok, detail=""):
    results.append({"check": name, "ok": bool(ok), "detail": str(detail)[:300]})
    print(("PASS" if ok else "FAIL"), "-", name, "|", str(detail)[:160], flush=True)

def textarea_values(page):
    return page.evaluate("""() => [...document.querySelectorAll('textarea')]
      .map(t => t.value).filter(v => v && v.trim())""")

def wait_status(page, needle, timeout_s=60):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        vals = textarea_values(page)
        hit = [v for v in vals if needle in v]
        if hit:
            return hit[0]
        page.wait_for_timeout(1500)
    return None

with sync_playwright() as p:
    try:
        browser = p.chromium.launch()
    except Exception:
        shells = sorted(glob.glob(r"C:\Users\83915\AppData\Local\ms-playwright\chromium_headless_shell-*\chrome-headless-shell.exe"))
        browser = p.chromium.launch(executable_path=shells[-1])
    page = browser.new_page(viewport={"width": 1680, "height": 1050})
    console_errors = []
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: console_errors.append(str(e)))
    page.set_default_timeout(15000)

    page.goto(BASE, wait_until="networkidle")
    page.wait_for_timeout(3000)
    check("首页加载", page.locator(".vs-hero").count() > 0, page.title())

    # ---------- 01 创建：加载 P04 预置 ----------
    try:
        page.locator(".vs-source-mode label", has_text="预置演示技能").click()
        page.wait_for_timeout(600)
        group = page.locator("div.vs-section", has=page.get_by_role("button", name="加载预置"))
        group.locator("input[role='listbox']").click()
        page.wait_for_timeout(800)
        page.locator("li[role='option']", has_text="P04_highway_congestion").first.click()
        page.get_by_role("button", name="加载预置").click()
        v = wait_status(page, "已自动加载", 90)
        check("01 加载P04预置技能+默认媒体", bool(v), (v or "timeout")[:120])
    except Exception as e:
        check("01 加载P04预置技能+默认媒体", False, f"EXC {e}".__getitem__(slice(150)))
    page.screenshot(path=OUT + r"\e2e_01_preset.png")

    # ---------- 02 审核 ----------
    try:
        page.locator("button[role='tab']", has_text="02 审核").click()
        page.wait_for_timeout(800)
        # P04 只有 video variant，先切换
        page.locator("label", has_text="video variant").first.click()
        page.wait_for_timeout(400)
        page.get_by_role("button", name="读取当前参数").click()
        v = wait_status(page, "已读取", 30)
        check("02 读取当前参数并反馈状态", bool(v), (v or "timeout")[:100])

        # resize 手风琴 + 联动
        page.locator("text=图像缩放 resize ｜").first.click()
        page.wait_for_timeout(600)
        page.locator("label", has_text="按长边缩放（提速常用）").first.click()
        page.wait_for_timeout(600)
        vis = page.evaluate("""() => {
          const lab = [...document.querySelectorAll('label span')].find(e => e.textContent.trim() === '长边像素');
          if (!lab) return 'not-found';
          const r = lab.getBoundingClientRect();
          return r.width > 0 && r.height > 0;
        }""")
        check("02 resize模式联动显示长边字段", vis is True, vis)

        # 视频抽帧手风琴 + 联动
        page.locator("text=视频抽帧 ｜").first.click()
        page.wait_for_timeout(500)
        page.locator("label", has_text="目标 FPS（提速常用").first.click()
        page.wait_for_timeout(600)
        vis2 = page.evaluate("""() => {
          const lab = [...document.querySelectorAll('label span')].find(e => e.textContent.trim() === '目标 FPS');
          if (!lab) return 'not-found';
          const r = lab.getBoundingClientRect();
          return r.width > 0 && r.height > 0;
        }""")
        check("02 抽帧模式联动显示FPS字段", vis2 is True, vis2)

        # 切片手风琴 + 联动
        page.locator("text=小目标增强：切片覆盖与重复框合并").first.click()
        page.wait_for_timeout(500)
        page.locator("label", has_text="启用切片增强").first.click()
        page.wait_for_timeout(600)
        vis3 = page.evaluate("""() => {
          const lab = [...document.querySelectorAll('label span')].find(e => e.textContent.trim().startsWith('切片宽度'));
          if (!lab) return 'not-found';
          const r = lab.getBoundingClientRect();
          return r.width > 0 && r.height > 0;
        }""")
        check("02 切片开关联动显示切片参数", vis3 is True, vis3)
    except Exception as e:
        check("02 审核页交互", False, f"EXC {str(e)[:150]}")
    page.screenshot(path=OUT + r"\e2e_02_review.png")

    # ---------- 03 标注 ----------
    try:
        page.locator("button[role='tab']", has_text="03 标注").click()
        page.wait_for_timeout(800)
        overview = page.locator(".status-card").last.inner_text()
        check("03 标注总览状态卡", len(overview) > 4, overview[:80])
        page.locator("#vs-annotation-tool label", has_text="多边形").click()
        page.wait_for_timeout(600)
        hint = page.locator(".vs-tool-hint").inner_text()
        check("03 多边形工具提示联动", "逐点点击" in hint, hint[:60])
    except Exception as e:
        check("03 标注页交互", False, f"EXC {str(e)[:150]}")
    page.screenshot(path=OUT + r"\e2e_03_annotation.png")

    # ---------- 04 运行 ----------
    try:
        page.locator("button[role='tab']", has_text="04 运行").click()
        page.wait_for_timeout(800)
        page.get_by_role("button", name="检查媒体与调用估算").click()
        page.wait_for_timeout(5000)
        vals = textarea_values(page)
        est = next((v for v in vals if "帧" in v or "调用" in v or "估算" in v), None)
        check("04 调用估算", bool(est), (est or "none")[:120])

        page.get_by_role("button", name="运行当前 Effective 技能").click()
        print("运行中，轮询运行状态...", flush=True)
        status = wait_status(page, "运行完成", 720)
        check("04 运行完成", bool(status), (status or "timeout 720s")[:150])

        if status:
            page.wait_for_timeout(3000)
            vinfo = page.evaluate("""async () => {
              const vids = [...document.querySelectorAll('video')].filter(v => {
                const r = v.getBoundingClientRect(); return r.width > 0 && r.height > 0;
              });
              if (!vids.length) return {visible: false};
              const v = vids[0];
              if (v.readyState < 1) {
                v.load();
                await new Promise(r => { v.onloadedmetadata = r; setTimeout(r, 20000); });
              }
              return {visible: true, src: (v.currentSrc || v.src || '').slice(-60),
                      readyState: v.readyState, duration: v.duration,
                      w: v.videoWidth, h: v.videoHeight, error: v.error && v.error.code};
            }""")
            playable = vinfo.get("visible") and vinfo.get("readyState", 0) >= 1 and not vinfo.get("error") and (vinfo.get("duration") or 0) > 0
            check("04 标注视频可见且浏览器可解码(H.264)", playable, json.dumps(vinfo, ensure_ascii=False)[:200])
    except Exception as e:
        check("04 运行页交互", False, f"EXC {str(e)[:150]}")
    page.screenshot(path=OUT + r"\e2e_04_result.png")

    check("浏览器控制台无JS错误", len(console_errors) == 0, " | ".join(console_errors[:3])[:200])
    browser.close()

ok_all = all(r["ok"] for r in results)
print("\n==== E2E SUMMARY:", "ALL PASS" if ok_all else "HAS FAILURES", "====")
open(OUT + r"\e2e_results.json", "w", encoding="utf-8").write(json.dumps(results, ensure_ascii=False, indent=1))
sys.exit(0 if ok_all else 1)
