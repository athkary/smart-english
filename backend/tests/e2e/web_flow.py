"""Browser end-to-end test of the Phase 2 web app (run while run_stack is up).

Usage: PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers python -m tests.e2e.web_flow [outdir]
Covers: signup -> add child -> PIN -> child mode (locked) -> teacher choice -> PIN gate ->
        edit settings -> language switch (RTL/LTR) -> delete child -> logout/login -> delete account.
"""
from __future__ import annotations

import pathlib
import sys
import time

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:5500/"
OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/e2e")
OUT.mkdir(parents=True, exist_ok=True)
EMAIL = f"parent{int(time.time())}@example.com"
PW = "family-pass-2026"


def run(device_name: str, tag: str):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(**p.devices[device_name], locale="ar-SA")
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        shot = lambda name: page.screenshot(path=str(OUT / f"{tag}-{name}.png"), full_page=True)
        email = f"{tag}-{EMAIL}"

        page.goto(BASE)
        expect(page.locator("h1")).to_have_text("معلّم إنجليزي ذكي لطفلك")
        assert page.evaluate("document.documentElement.dir") == "rtl"
        shot("01-welcome")

        # signup
        page.get_by_role("link", name="إنشاء حساب ولي أمر").click()
        page.get_by_label("اسمك").fill("أم أحمد")
        page.get_by_label("البريد الإلكتروني").fill(email)
        page.get_by_label("كلمة المرور").fill("short")
        page.locator("#consent").check()
        shot("02-signup")
        page.get_by_role("button", name="إنشاء الحساب").click()
        # browser-side minlength blocks it; then use a real password
        assert "#/signup" in page.url
        page.get_by_label("كلمة المرور").fill(PW)
        page.get_by_role("button", name="إنشاء الحساب").click()
        expect(page.locator("h1")).to_contain_text("مرحباً أم أحمد")
        expect(page.get_by_text("لم تُضف أي طفل بعد")).to_be_visible()

        # add a child
        page.get_by_role("link", name="إضافة طفل").first.click()
        page.get_by_label("اسم الطفل").fill("Ahmed")
        page.get_by_label("سنة الميلاد").fill("2017")
        page.get_by_role("radio", name="owl").click()
        shot("03-add-child")
        page.get_by_role("button", name="حفظ").click()
        expect(page.get_by_role("heading", name="Ahmed")).to_be_visible()
        shot("04-parent-home")

        # start learning without PIN -> must set PIN first
        page.get_by_role("button", name="ابدأ التعلم").click()
        dialog = page.get_by_role("dialog")
        expect(dialog).to_be_visible()
        dialog.get_by_label("رمز جديد").fill("2468")
        dialog.get_by_label("كلمة مرور الحساب").fill(PW)
        dialog.get_by_role("button", name="تأكيد").click()
        expect(page.locator("h1.kid-title")).to_contain_text("Hello, Ahmed!", timeout=10000)
        expect(page.get_by_text("مرحباً يا Ahmed!")).to_be_visible()
        expect(page.get_by_text("كلمة اليوم")).to_be_visible()
        shot("05-child-home")

        # child is locked in: navigating to the parent area by URL bounces back
        page.goto(BASE + "#/parent")
        expect(page.locator("h1.kid-title")).to_be_visible()
        page.reload()
        expect(page.locator("h1.kid-title")).to_be_visible()

        # choose teacher Daniel (persists on the server)
        page.get_by_role("radio", name="Daniel").click()
        expect(page.get_by_role("radio", name="Daniel")).to_have_attribute("aria-checked", "true")
        page.reload()
        expect(page.get_by_role("radio", name="Daniel")).to_have_attribute("aria-checked", "true")
        assert page.get_by_role("radio", name="Alex").is_disabled()

        # the speaker button really calls speechSynthesis
        page.evaluate("""() => { window.__spoken = []; const o = speechSynthesis.speak.bind(speechSynthesis);
                         speechSynthesis.speak = (u) => { window.__spoken.push(u.text); o(u); }; }""")
        page.locator("button.btn-icon").first.click()
        assert len(page.evaluate("window.__spoken")) == 1

        # parent gate: wrong PIN then right PIN
        page.get_by_role("button", name="منطقة الأهل").click()
        page.get_by_role("dialog").get_by_label("أدخل الرمز").fill("1111")
        page.get_by_role("dialog").get_by_role("button", name="تأكيد").click()
        expect(page.get_by_role("dialog").get_by_text("الرمز غير صحيح")).to_be_visible()
        page.get_by_role("dialog").get_by_label("أدخل الرمز").fill("2468")
        page.get_by_role("dialog").get_by_role("button", name="تأكيد").click()
        expect(page.locator("h1")).to_contain_text("مرحباً أم أحمد")

        # edit child settings: limit 30 min, hide Arabic
        page.get_by_role("link", name="الإعدادات").click()
        page.get_by_label("الحد اليومي").fill("30")
        page.get_by_label("إظهار الترجمة العربية").uncheck()
        shot("06-child-settings")
        page.get_by_role("button", name="حفظ").click()
        expect(page.get_by_role("heading", name="Ahmed")).to_be_visible()
        page.get_by_role("button", name="ابدأ التعلم").click()
        expect(page.get_by_text("دقائق متبقية اليوم")).to_be_visible()
        expect(page.get_by_text("مرحباً يا Ahmed!")).to_have_count(0)  # Arabic hidden now
        page.get_by_role("button", name="منطقة الأهل").click()
        page.get_by_role("dialog").get_by_label("أدخل الرمز").fill("2468")
        page.get_by_role("dialog").get_by_role("button", name="تأكيد").click()
        expect(page.locator("h1")).to_contain_text("مرحباً أم أحمد")

        # switch to English -> LTR
        page.get_by_role("button", name="English").click()
        assert page.evaluate("document.documentElement.dir") == "ltr"
        expect(page.locator("h1")).to_contain_text("Hello أم أحمد")
        shot("07-parent-en")
        page.get_by_role("button", name="العربية").click()

        # delete the child
        page.get_by_role("link", name="الإعدادات").click()
        page.get_by_role("button", name="حذف هذا الطفل").click()
        page.get_by_role("dialog").get_by_role("button", name="حذف هذا الطفل").click()
        expect(page.get_by_text("لم تُضف أي طفل بعد")).to_be_visible()

        # logout, wrong login, login
        page.get_by_role("button", name="تسجيل الخروج").click()
        expect(page.locator("h1")).to_have_text("معلّم إنجليزي ذكي لطفلك")
        page.get_by_role("link", name="لدي حساب").click()
        page.get_by_label("البريد الإلكتروني").fill(email)
        page.get_by_label("كلمة المرور").fill("wrong-password-1")
        page.get_by_role("button", name="دخول").click()
        expect(page.get_by_text("البريد الإلكتروني أو كلمة المرور غير صحيحة")).to_be_visible()
        page.get_by_label("كلمة المرور").fill(PW)
        page.get_by_role("button", name="دخول").click()
        expect(page.locator("h1")).to_contain_text("مرحباً أم أحمد")

        # delete account
        page.get_by_role("button", name="حذف الحساب وكل البيانات").click()
        d = page.get_by_role("dialog")
        d.get_by_label("كلمة المرور").fill(PW)
        d.get_by_label("اكتب DELETE للتأكيد").fill("DELETE")
        shot("08-delete-account")
        d.get_by_role("button", name="حذف الحساب وكل البيانات").click()
        expect(page.locator("h1")).to_have_text("معلّم إنجليزي ذكي لطفلك")
        page.get_by_role("link", name="لدي حساب").click()
        page.get_by_label("البريد الإلكتروني").fill(email)
        page.get_by_label("كلمة المرور").fill(PW)
        page.get_by_role("button", name="دخول").click()
        expect(page.get_by_text("البريد الإلكتروني أو كلمة المرور غير صحيحة")).to_be_visible()

        bad = [e for e in errors if "401" not in e and "403" not in e]  # expected auth failures log as console errors
        assert not bad, bad
        browser.close()
        print(f"✅ {device_name}: full flow passed")


if __name__ == "__main__":
    run("iPhone 13", "iphone")
    run("iPad (gen 7)", "ipad")
    run("Pixel 7", "android")
