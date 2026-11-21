# 03 — عقود الـAPI | API Contracts (v1)

- الأساس: `https://api.<domain>/v1` — JSON (UTF-8)، الأوقات ISO-8601 UTC، المعرّفات UUID.
- المصادقة: `Authorization: Bearer <access_token>` (JWT، صلاحية 15 دقيقة) + refresh token غامض (30 يوماً، دوّار).
- كل استجابة تحمل `X-Request-ID`. اللغة المفضلة للرسائل عبر `Accept-Language: ar|en`.
- **صيغة الخطأ الموحدة:**
```json
{ "error": { "code": "student_limit_reached", "message": "Daily limit reached",
             "message_ar": "انتهى وقت التعلم المسموح اليوم", "request_id": "…" } }
```
- **الحالة:** ✅ = مُنفّذ في المرحلة 1 · 🔜 = مُعرّف هنا ويُنفّذ في المرحلة المذكورة.

## 1. النظام (المرحلة 1) ✅

| Method | Path | Auth | الوصف |
|--------|------|------|-------|
| GET | `/health` | — | حيّ؟ `{"status":"ok"}` |
| GET | `/ready` | — | جاهز؟ يفحص Postgres وRedis. `200` أو `503` مع تفاصيل كل اعتماد |
| GET | `/v1/meta` | — | اسم التطبيق، الإصدار، اللغات، المستويات، الشخصيات المتاحة، أقل إصدار iOS مدعوم |

`GET /v1/meta` →
```json
{ "app": "SMART ENGLISH AI", "api_version": "1", "server_version": "0.1.0",
  "min_ios_app_version": "0.1.0", "supported_languages": ["ar","en"],
  "levels": ["A0","A1","A2"],
  "teachers": [{"code":"emma","display_name":"Emma","description_ar":"معلمة ودودة للمبتدئين","available":true}, …],
  "features": {"voice_classroom": false, "pronunciation_assessment": false, "subscriptions": false} }
```
> علامات `features` تعكس ما هو **مُنفّذ ومُختبر فعلاً** — التطبيق لا يعرض زراً لميزة قيمتها `false`.

## 2. المصادقة والملفات (المرحلة 2) ✅ — مُنفّذ ومُختبر

| Method | Path | Auth | الوصف |
|--------|------|------|-------|
| POST | `/v1/auth/parents/signup` | — | `{email, password, display_name, preferred_language, consent_version}` → tokens |
| POST | `/v1/auth/login` | — | `{email, password}` → `{access_token, refresh_token, expires_in}` |
| POST | `/v1/auth/refresh` | — | `{refresh_token}` → tokens جديدة (القديم يُلغى) |
| POST | `/v1/auth/logout` | — | `{refresh_token}` إلغاء سلسلة الرموز |
| POST | `/v1/auth/students/session` | parent | يصدر رمز جلسة للطفل على هذا الجهاز `{student_id}` → student tokens (scope محدود) |
| PUT | `/v1/parents/me/pin` | parent | `{pin, password}` تعيين/تغيير رمز منطقة الأهل |
| POST | `/v1/parents/me/pin/verify` | parent | `{pin}` → 204، أو 403، أو 429 بعد 5 محاولات خاطئة (قفل 5 دقائق) |
| GET/PATCH | `/v1/parents/me` | parent | الملف + PIN منطقة الأهل |
| GET/POST | `/v1/students` | parent | قائمة / إنشاء طالب `{nickname, birth_year?, avatar_code, preferred_teacher}` |
| GET/PATCH/DELETE | `/v1/students/{id}` | parent (مالك) | تعديل / حذف كامل لبيانات الطفل (حد أقصى 6 أطفال) |
| GET/PUT | `/v1/students/{id}/settings` | parent | حدود الوقت، المحادثة الحرة، الاحتفاظ بالنصوص |
| GET | `/v1/me/student` | student | ملف الطالب الحالي + الوقت المتبقي اليوم |
| PATCH | `/v1/me/student/preferences` | student | `{preferred_teacher, show_arabic}` |
| DELETE | `/v1/parents/me` | parent | `{password, confirm:"DELETE"}` حذف الحساب وكل بيانات الأطفال |
| GET | `/v1/parents/me/export` | parent | تصدير بيانات الأطفال (JSON) |

## 3. المعلم والمنهج (المراحل 3 و5) 🔜

| Method | Path | الوصف |
|--------|------|-------|
| GET | `/v1/teachers` | الشخصيات (بدون الموجّه الداخلي) |
| GET | `/v1/curriculum/units` | الوحدات + حالة القفل والتقدم للطالب |
| GET | `/v1/curriculum/units/{id}/lessons` | الدروس |
| GET | `/v1/lessons/{id}` | الدرس كاملاً: الخطوات + المفردات (كل الحقول ثنائية اللغة) |
| GET | `/v1/vocabulary/{id}/audio?part=word\|example` | رابط صوتي موقّع قصير العمر |
| POST | `/v1/lessons/{id}/sessions` | بدء جلسة درس → `lesson_session_id` |
| PATCH | `/v1/lesson-sessions/{id}` | `{current_step, step_result}` حفظ التقدم أثناء الدرس |
| POST | `/v1/lesson-sessions/{id}/complete` | `{quiz_answers}` → `{score, stars, passed, next_lesson_id}` |
| POST | `/v1/teacher/explain` | شرح نصي غير صوتي `{text_en}` → `{text_ar, phonetic_ar, notes_ar}` |

**كائن المفردة (Vocabulary item):**
```json
{ "id":"…", "word_en":"apple", "meaning_ar":"تفاحة", "phonetic_ar":"أَبُل", "ipa":"ˈæp.əl",
  "example_en":"I eat an apple.", "example_ar":"أنا آكل تفاحة.",
  "audio": {"word":"/v1/vocabulary/…/audio?part=word", "example":"/v1/vocabulary/…/audio?part=example"},
  "image_url":"…" }
```

## 4. الفصل الصوتي (المرحلة 4) 🔜 — WebSocket

`POST /v1/classroom/sessions` (student) `{teacher, mode, scenario?, lesson_session_id?}` → `{session_id, ws_url, ws_ticket}`
ثم: `WSS /v1/realtime/classroom?ticket=<ws_ticket>` (تذكرة لمرة واحدة صالحة 60 ثانية، لا يوضع JWT في الرابط).

التفاصيل الكاملة للرسائل في [`04-voice-architecture.md`](04-voice-architecture.md).

## 5. النطق (المرحلة 6) 🔜
| POST | `/v1/pronunciation/assess` | `multipart: audio (≤15s, wav/opus), target_text, vocabulary_id?` → `{method, accuracy, fluency, completeness, words:[{word, error_type, phonemes:[…]}], missing_words, feedback_ar}` |

## 6. الألعاب والتقييم (المرحلة 7) 🔜
| GET | `/v1/games/{game_code}/round?unit_id=` | جولة لعبة مولّدة من مفردات الطالب |
| POST | `/v1/assessments` | حفظ نتيجة لعبة/اختبار → نقاط + إنجازات جديدة |
| GET | `/v1/me/achievements` | الشارات |

## 7. لوحات المعلومات (المرحلة 8) 🔜
| GET | `/v1/me/dashboard` | student: المستوى، الهدف اليومي، الدروس، الكلمات، دقائق المحادثة، النطق، الاختبارات، الأسبوع |
| GET | `/v1/students/{id}/report?from=&to=` | parent: نفس البيانات + الأخطاء الشائعة + تقارير الدروس |
| GET | `/v1/students/{id}/lesson-sessions/{sid}` | parent: تقرير درس واحد (الخطوة 16 من اختبار القبول) |

## 8. الاشتراكات (بعد اختبار MVP) 🔜
| POST | `/v1/billing/apple/transactions` | التطبيق يرسل JWS المعاملة من StoreKit 2؛ الخادم يتحقق منها |
| POST | `/v1/billing/apple/notifications` | App Store Server Notifications v2 |

## سياسات عامة
- **تحديد المعدّل** (Redis): الدخول 5/دقيقة لكل IP+بريد؛ الشرح 30/دقيقة لكل طالب؛ جلسات صوتية متزامنة: 1 لكل طالب.
- **الملكية:** كل مسار `/students/{id}` يتحقق أن الطالب يتبع ولي الأمر صاحب الرمز (وإلا `404`، لا `403`، لتجنب كشف الوجود).
- **الإصدار:** تغيير غير متوافق = `/v2`. التطبيق يقرأ `min_ios_app_version` ويطلب التحديث.
