# SMART ENGLISH AI
**Learn English. Speak with Confidence. — تعلّم الإنجليزية. تحدّث بثقة.**

معلم إنجليزية ذكي ثنائي اللغة (عربي/إنجليزي) للأطفال الناطقين بالعربية (CEFR A0–A1).
يعمل كتطبيق ويب قابل للتثبيت (PWA) على **الآيفون والآيباد والأندرويد** من رابط واحد.

## الحالة
| المرحلة | الحالة |
|---------|--------|
| 1 — المعمارية والأساس | ✅ |
| 2 — حسابات الأهل، ملفات الأطفال، الدخول، الخصوصية | ✅ (بانتظار موافقتك على المرحلة 3) |
| 3 — المعلم الذكي ثنائي اللغة | التالية |

## المجلدات
| المجلد | المحتوى |
|--------|---------|
| `web/` | تطبيق الويب (HTML/CSS/JS بدون أدوات بناء) — يُنشر على GitHub Pages |
| `backend/` | الخادم (Python + Starlette + PostgreSQL) — يُنشر على Render |
| `docs/` | وثائق التصميم + **`08-deployment.md` دليل النشر بالعربي** |
| `ios/` | أساس تطبيق iOS الأصلي (مؤجل حتى يتوفر Mac وحساب Apple) |

## النشر
اتبع [`docs/08-deployment.md`](docs/08-deployment.md) — مجاني بالكامل (GitHub Pages + Render + Neon).

## التطوير المحلي
```bash
cd backend
pip install -r requirements-dev.txt
pytest -q                                   # يحتاج PostgreSQL محلياً أو TEST_DATABASE_URL
python -m tests.e2e.run_stack               # خادم + قاعدة مؤقتة + الواجهة على http://127.0.0.1:5500
PLAYWRIGHT_BROWSERS_PATH=... python -m tests.e2e.web_flow   # اختبار المتصفح الكامل (iPhone/iPad/Android)
```

## قواعد المشروع
- لا مفاتيح API في الواجهة أبداً (`scripts/check_no_secrets.sh` في CI).
- لا أزرار لا تعمل: الميزات القادمة تظهر بعلامة «قريباً».
- لا تسجيل دائم للصوت؛ ولي الأمر يحذف كل البيانات متى شاء.
