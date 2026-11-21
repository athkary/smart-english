# 01 — المعمارية التقنية | Technical Architecture

**المشروع:** SMART ENGLISH AI — *Learn English. Speak with Confidence.*
**الإصدار:** 0.1 (المرحلة الأولى) — 2026-11-20

---

## 1. الصورة العامة

```
┌──────────────────────────── iPhone / iPad (SwiftUI, iOS 17+) ───────────────────────────┐
│  Features: Onboarding · Classroom (Voice) · Lessons · Games · Dashboard · Parent Area     │
│  Core:     DesignSystem · Localization(ar/en, RTL/LTR) · APIClient · AudioEngine(AVAudio) │
│            KeychainStore · SessionStore · Offline cache (SwiftData)                       │
└───────────────┬───────────────────────────────────────────────┬──────────────────────────┘
                │ HTTPS (REST/JSON)                              │ WSS (audio + events)
                ▼                                                ▼
┌──────────────────────────────── API Gateway / Load Balancer (TLS) ──────────────────────┐
└───────────────┬───────────────────────────────────────────────┬──────────────────────────┘
                ▼                                                ▼
┌──────────── FastAPI: REST service ───────────┐   ┌──────── FastAPI: Realtime Voice service ───────┐
│ auth · parents · students · curriculum ·      │   │ /v1/realtime/classroom (WebSocket)             │
│ lessons · progress · reports · subscriptions  │   │ VAD → STT stream → Teacher Brain → TTS stream │
└──────┬─────────────────────┬─────────────────┘   │ barge-in · turn detection · buffering         │
       │                     │                      └──────┬──────────────┬───────────────┬────────┘
       ▼                     ▼                             ▼              ▼               ▼
 ┌──────────┐         ┌────────────┐            ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
 │PostgreSQL│         │   Redis    │            │ STT Provider │ │ LLM Provider │ │ TTS Provider │
 │ (data)   │         │ sessions,  │            │ (streaming)  │ │ Claude API   │ │ (streaming)  │
 └──────────┘         │ rate-limit,│            └──────────────┘ └──────────────┘ └──────────────┘
                      │ pub/sub    │                       ┌───────────────────────────┐
                      └────────────┘                       │ Pronunciation Assessment  │
                                                           │ Provider (phoneme-level)  │
                                                           └───────────────────────────┘
```

**المبدأ الحاكم:** التطبيق على الجهاز لا يحمل أي مفتاح API لأي مزود خارجي. كل مكالمات الذكاء الاصطناعي والصوت تمر عبر الخادم الخلفي.

## 2. قرارات معمارية رئيسية (ADR مختصرة)

| # | القرار | السبب | البديل المرفوض |
|---|--------|-------|-----------------|
| A1 | **Monolith معياري** (FastAPI واحد بوحدات منفصلة) مع إمكانية فصل خدمة الصوت لاحقاً | فريق صغير في MVP؛ الفصل المبكر يضاعف التعقيد | Microservices من اليوم الأول |
| A2 | **WebSocket** بين التطبيق والخادم للصوت (PCM16 / Opus) | يتيح مرور الصوت عبر الخادم فتبقى المفاتيح محمية، ويسمح بتطبيق فلاتر حماية الأطفال قبل وصول أي رد | WebRTC مباشر من التطبيق إلى مزود خارجي (يتطلب تسليم رموز للجهاز ويصعّب الرقابة) |
| A3 | **واجهات مزودين (Provider Interfaces)** مجردة: `SpeechToText`, `TextToSpeech`, `TeacherLLM`, `PronunciationAssessor`, `ContentSafety` | المواصفات تطلب تبديل المزودين باستقلالية | الربط المباشر بـSDK مزود واحد |
| A4 | **Claude API** كعقل المعلم، مع "System Prompt" لكل شخصية (Emma/Daniel/Alex) ولكل وضع محادثة | المطلوب في المواصفات؛ جودة عالية في التصحيح اللغوي والعربية | — |
| A5 | **مخرجات المعلم منظمة (Structured)**: النص الإنجليزي + الترجمة العربية + التصحيح + الكلمات الجديدة، في JSON متدفق | الواجهة تحتاج الترجمة والتصحيح كحقول منفصلة، لا كنص حر | نص حر يُحلَّل لاحقاً |
| A6 | **PostgreSQL** مصدر الحقيقة؛ **Redis** للحالة المؤقتة (جلسات الصوت، حدود الاستخدام، قوائم الانتظار) | — | — |
| A7 | **لا نخزّن الصوت الخام بشكل دائم.** نخزّن النص المفرّغ وملخصات تعليمية ونتائج النطق | خصوصية الأطفال (COPPA / GDPR-K)، والمواصفات تنص على ذلك | — |
| A8 | **محتوى المنهج بيانات (Content-as-data)**: الوحدات والدروس والمفردات في قاعدة البيانات وتُحمَّل من ملفات YAML/JSON مُراجَعة | يسمح بمراجعة تربوية وتعديل المحتوى دون إصدار تطبيق جديد | محتوى مضمّن في كود Swift |
| A9 | **SwiftUI + Swift 6 strict concurrency**، معمارية Feature-based مع `@Observable` | حديثة ومناسبة لـiOS 17+ | UIKit / Combine-heavy MVVM |
| A10 | مشروع Xcode يُولَّد من **XcodeGen (`project.yml`)** | ملف المشروع قابل للمراجعة في Git ولا تحدث تعارضات دمج | ملف `.xcodeproj` يدوي |

## 3. وحدات الخادم الخلفي

```
backend/app/
├── core/          config, logging, security (hashing, JWT), errors, request-id
├── db/            engine/session, Alembic migrations
├── providers/     interfaces + adapters (stt, tts, llm, pronunciation, safety)
├── modules/
│   ├── health/        /health, /ready, /v1/meta            ← المرحلة 1
│   ├── auth/          parent signup/login, student PIN, tokens ← المرحلة 2
│   ├── profiles/      parents, students, parent settings   ← المرحلة 2
│   ├── teacher/       personas, prompts, bilingual engine  ← المرحلة 3
│   ├── realtime/      classroom websocket, turn manager    ← المرحلة 4
│   ├── curriculum/    units, lessons, vocabulary           ← المرحلة 5
│   ├── pronunciation/ assessment pipeline                  ← المرحلة 6
│   ├── games/         exercises, assessments, achievements ← المرحلة 7
│   ├── reports/       parent dashboard, analytics          ← المرحلة 8
│   └── billing/       StoreKit 2 server verification       ← بعد اختبار MVP
└── main.py        app factory
```

## 4. وحدات تطبيق iOS

```
ios/SmartEnglish/
├── App/            SmartEnglishApp, AppState, Router
├── Core/
│   ├── Config/         AppEnvironment (dev/staging/prod)
│   ├── Networking/     APIClient (async/await), Endpoints, errors
│   ├── Localization/   LanguageManager (ar/en, RTL/LTR), Localizable.xcstrings
│   ├── DesignSystem/   Colors, Typography, Spacing, components (BigMicButton…)
│   ├── Audio/          (المرحلة 4) AudioCapture, AudioPlayer, VAD client
│   └── Storage/        (المرحلة 2) Keychain
├── Features/
│   ├── Launch/         شاشة البدء + فحص اتصال الخادم  ← المرحلة 1
│   ├── Settings/       اللغة + إظهار/إخفاء الترجمة     ← المرحلة 1
│   ├── Onboarding/ Auth/ Classroom/ Lessons/ Games/ Dashboard/ Parent/  ← لاحقاً
└── Resources/      Assets, Info.plist
```

## 5. البيئات

| البيئة | الخادم | قاعدة البيانات | المزودون |
|--------|--------|----------------|-----------|
| `local` | docker compose | Postgres محلي | مفاتيح تطوير في `.env` (لا تُرفع لـGit) |
| `staging` | سحابة (حاوية) | Postgres مُدار | مفاتيح منفصلة بحدود إنفاق منخفضة |
| `production` | سحابة، منطقتان على الأقل قرب المستخدمين (الخليج/أوروبا) | Postgres مُدار + نسخ احتياطي يومي | مفاتيح إنتاج في Secret Manager |

## 6. المراقبة والتشغيل

- سجلات JSON منظمة مع `request_id` و`session_id` (بدون نصوص محادثات الأطفال في السجلات العامة).
- مقاييس: زمن الاستجابة الصوتية (من نهاية كلام الطالب حتى أول بايت صوت)، معدل الأخطاء لكل مزود، تكلفة الدقائق.
- تتبّع الأخطاء (Sentry أو مكافئ) مع تنقية البيانات الشخصية.
- CI: GitHub Actions — فحص Lint + اختبارات الخادم + بناء iOS واختباراته على macOS runner.

## 7. مزودون مقترحون (يُحسم الاختيار بعد اختبار فعلي في المرحلة 4/6)

| الدور | مرشحون | ملاحظة |
|------|---------|--------|
| LLM | Anthropic Claude (Sonnet للمحادثة، Haiku للمهام السريعة كالتصنيف) | محسوم بالمواصفات |
| STT متدفق | Deepgram، Azure Speech، Google Speech-to-Text v2، AssemblyAI | يجب اختبار دقة أصوات الأطفال واللكنة العربية |
| TTS متدفق | Azure Neural TTS، ElevenLabs، Google TTS، OpenAI TTS | أصوات مختلفة لكل شخصية معلم |
| تقييم النطق | **Azure Pronunciation Assessment** (مستوى الفونيم)، Speechace | لا نزعم دقة نطق من التفريغ النصي وحده |

> **ملاحظة صدق:** لم يُختبر أي مزود خارجي في هذه المرحلة. سيتم اختبار كل تكامل فعلياً قبل الإعلان عن عمله.

---

## 8. تحديث المرحلة 2 (2026-11-21) — قرارات جديدة

| # | القرار | السبب |
|---|--------|-------|
| A11 | **تطبيق ويب PWA أولاً** (`web/`) على GitHub Pages، يعمل على iPhone وiPad وAndroid. تطبيق iOS الأصلي مؤجل | لا يتوفر Mac ولا حساب Apple Developer حالياً؛ الـPWA يصل للأجهزة الثلاثة من رابط واحد ومجاناً |
| A12 | **Starlette** بدل FastAPI لطبقة HTTP (FastAPI مبني على Starlette) + pydantic للتحقق | أمكن تشغيل الخادم واختباره كاملاً (API + متصفح) في بيئة التطوير؛ التحويل لـFastAPI لاحقاً سهل إن احتجنا توثيق OpenAPI التلقائي |
| A13 | **SQL مباشر** بمعاملات `$1..$n` (asyncpg في الإنتاج) وكل كتابة متعددة الجداول **جملة واحدة** (CTEs) | ذرّية بدون معاملات من جهة العميل، وبدون ORM إضافي |
| A14 | **Neon** لقاعدة البيانات + **Render** للخادم (خطط مجانية) | قاعدة Render المجانية تنتهي بعد 30 يوماً؛ Neon المجانية بلا انتهاء |
| A15 | **الصوت المجاني المدمج في المتصفح** (Web Speech API) في البداية + نموذج Claude الأرخص | تكلفة شبه معدومة أثناء التجربة؛ واجهات المزودين تسمح بالترقية لاحقاً دون إعادة بناء |
| A16 | Redis اختياري حتى المرحلة 4؛ تحديد المعدّل في الذاكرة (نسخة خادم واحدة) | خطة Render المجانية = نسخة واحدة |
