# 04 — معمارية الصوت الفوري | Real-time Voice Architecture

أعلى ميزة أولوية. الهدف: **1–2 ثانية** من نهاية كلام الطالب حتى بدء صوت المعلم (حسب الشبكة والمزود).

## 1. خط المعالجة (Pipeline)

```
 iPhone/iPad                                   Realtime service (server)
┌───────────────────────┐   WSS binary frames  ┌──────────────────────────────────────────────────┐
│ AVAudioEngine mic tap │ ── PCM16 16kHz 20ms ─▶│ Ingest buffer ─▶ Server VAD ─┬▶ STT stream (partials)│
│ + echo cancellation   │                      │                              │                       │
│ (voiceChat mode)      │                      │                 end-of-turn detector (VAD silence    │
│ local VAD (energy)    │                      │                 + STT endpoint + semantic check)     │
│  → barge-in signal    │                      │                              ▼                       │
│                       │◀── JSON events ──────│  Safety filter (input) ─▶ Teacher Brain (Claude,     │
│ Transcript + Arabic UI│                      │                           streaming, structured)     │
│                       │◀── TTS audio chunks ─│  Safety filter (output) ─▶ sentence splitter ─▶ TTS │
│ AVAudioPlayerNode     │                      │                                    stream ─▶ client │
│ jitter buffer ~150ms  │                      │  Turn manager / state machine · Redis session state  │
└───────────────────────┘                      └──────────────────────────────────────────────────┘
```

### ميزانية زمن الاستجابة (الهدف)
| المرحلة | الهدف |
|---------|-------|
| كشف نهاية الدور (صمت) | 500–700 ms (أطول للأطفال المبتدئين: قابل للضبط حسب المستوى) |
| STT نهائي بعد نهاية الدور | ≤ 150 ms (مع التفريغ المتدفق يكون جاهزاً تقريباً) |
| Claude أول جملة (TTFT + جملة) | 400–800 ms |
| TTS أول مقطع صوتي | 150–300 ms |
| الشبكة ذهاباً وإياباً | 50–150 ms |
| **المجموع** | **≈ 1.3–2.0 s** |

**تقنيات خفض التأخير:** بث رد Claude جملة بجملة إلى TTS (لا ننتظر الرد كاملاً)؛ إبقاء اتصالات المزودين مفتوحة طوال الجلسة؛ نشر الخادم قرب المستخدمين؛ استخدام نموذج سريع للأدوار القصيرة.

## 2. حالة الدور (Turn State Machine)

```
            greet
  ┌──────────────────────┐
  ▼                      │
LISTENING ──speech_start──▶ STUDENT_SPEAKING ──end_of_turn──▶ THINKING ──first_audio──▶ TEACHER_SPEAKING
  ▲                                                                                     │      │
  │                         ◀────────────── barge-in (student speech > 300ms) ──────────┘      │
  └──────────────────────────────────── playback_done ─────────────────────────────────────────┘
```
- **المقاطعة (Barge-in):** إذا تكلم الطالب أثناء كلام المعلم لأكثر من ~300ms (VAD على الجهاز + تأكيد الخادم): يتوقف التشغيل فوراً على الجهاز، يلغي الخادم توليد Claude وTTS الجاري، تُحفظ رسالة المعلم بعلامة `was_interrupted=true` مع الجزء الذي قيل فعلاً فقط.
- **صمت طويل:** بعد 8 ثوانٍ بلا كلام، المعلم يشجع بلطف ("Take your time! خذ وقتك") — بحد أقصى مرتين ثم يقترح المساعدة.

## 3. بروتوكول WebSocket

**إطارات ثنائية (Binary):** صوت فقط. من العميل: PCM16 LE mono 16 kHz، 20ms لكل إطار (640 بايت). من الخادم: PCM16 24 kHz (أو Opus لاحقاً) مع ترويسة 8 بايت `[uint32 utterance_id][uint32 chunk_seq]`.

**إطارات نصية (JSON) — من العميل:**
| type | الحقول | الغرض |
|------|--------|-------|
| `session.start` | `audio_format, app_version, show_arabic` | بدء الجلسة |
| `input.speech_started` | `t` | VAD محلي (لتسريع المقاطعة) |
| `input.commit` | — | زر "انتهيت" اليدوي (احتياطي لكشف الدور) |
| `playback.stopped` | `utterance_id, played_ms` | ما سمعه الطالب فعلاً قبل المقاطعة |
| `session.end` | — | إنهاء |
| `ping` | `t` | قياس RTT |

**من الخادم:**
| type | الحقول |
|------|--------|
| `session.ready` | `session_id, teacher, mode` |
| `state` | `LISTENING \| STUDENT_SPEAKING \| THINKING \| TEACHER_SPEAKING` |
| `transcript.partial` / `transcript.final` | `text, confidence` |
| `teacher.message` | `utterance_id, text_en, text_ar, correction?:{original, corrected, explanation_ar}, repeat_after_me?: "…" , new_words?:[…]` |
| `teacher.audio_start` / `teacher.audio_end` | `utterance_id` |
| `teacher.cancelled` | `utterance_id` (بعد المقاطعة) |
| `limit.warning` | `minutes_left` (حدود ولي الأمر) |
| `error` | `code, message_ar, retryable` |
| `pong` | `t` |

## 4. عقل المعلم (Teacher Brain)

- مدخلات Claude: موجّه الشخصية + قواعد حماية الأطفال + الوضع (beginner/guided/free/role_play + السيناريو) + مستوى الطالب + مفردات الدرس الحالي + ملخص الجلسات السابقة (لا النص الكامل) + آخر N أدوار.
- المخرجات: **JSON متدفق** بحقول `text_en`, `text_ar`, `correction`, `repeat_after_me`, `new_words`. يُرسل `text_en` إلى TTS جملة بجملة فور اكتمالها.
- **ثنائية اللغة:** النص المنطوق بالإنجليزية؛ العربية تظهر نصاً على الشاشة (ويمكن نطق شرح عربي قصير بصوت عربي عند الحاجة في وضع المبتدئين).
- **التكيف:** بعد كل دور يحدَّث مؤشر صعوبة (نسبة الأخطاء، طول الجمل، طلبات المساعدة) يغيّر تعليمات الموجّه.

## 5. المرونة والشبكة

- **إعادة الاتصال:** العميل يعيد الاتصال تلقائياً (backoff 0.5→8s) بنفس `session_id` + تذكرة جديدة؛ الخادم يحتفظ بحالة الجلسة في Redis لمدة 120 ثانية.
- **التخزين المؤقت:** حلقة (ring buffer) 2 ثانية على الجهاز تُرسل بعد إعادة الاتصال إن كان الطالب يتكلم.
- **فشل مزود:** محوّل احتياطي لكل واجهة (مثلاً STT ثانوي). إن تعذر الصوت كلياً: رسالة واضحة بالعربية، **لا** صوت مسجل مسبقاً يدّعي أنه محادثة.
- **جلسة صوت الجهاز:** `AVAudioSession` بفئة `.playAndRecord` ووضع `.voiceChat` (إلغاء الصدى ضروري للمقاطعة)، مع معالجة انقطاع المكالمات وتغيير السماعات.

## 6. الخصوصية في مسار الصوت
- الصوت يُعالج في الذاكرة ولا يُكتب على القرص. لا نفعّل خيارات "تحسين النموذج / الاحتفاظ بالبيانات" لدى المزودين (اتفاقيات معالجة بيانات + خيارات zero-retention حيث تتوفر).
- النص المفرّغ يُخزَّن فقط إذا سمح ولي الأمر، وبتاريخ انتهاء.

## 7. ما سيُختبر في المرحلة 4 (معايير الخروج)
1. محادثة 10 أدوار على iPhone حقيقي وiPad حقيقي، على Wi-Fi و4G.
2. قياس p50/p95 للتأخير (مسجّل في `avg_latency_ms`) — الهدف p50 ≤ 2s.
3. المقاطعة توقف الصوت خلال ≤ 300ms.
4. قطع الشبكة 5 ثوانٍ ثم استعادتها دون فقدان الجلسة.
5. اختبار أصوات أطفال حقيقيين (بموافقة الأهل) لقياس دقة STT.
