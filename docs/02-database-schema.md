# 02 — مخطط قاعدة البيانات | Database Schema

المصدر الرسمي: [`backend/migrations/sql/0001_initial_schema.sql`](../backend/migrations/sql/0001_initial_schema.sql)
**تم التحقق منه فعلياً على PostgreSQL 16** (التحميل + اختبار القيود في `migrations/sql/tests/schema_smoke.sql`).

## المبادئ
- مفاتيح `uuid` (`gen_random_uuid()`)، مفاتيح أجنبية صريحة، فهارس على مسارات القراءة الشائعة، `created_at/updated_at` مع Trigger تلقائي.
- **تقليل البيانات:** الطالب = اسم مستعار + سنة الميلاد فقط. لا بريد ولا كلمة مرور للطفل.
- **لا تخزين دائم للصوت.** فقط النص المفرّغ (بفترة احتفاظ يحددها ولي الأمر عبر `expires_at`) والملخصات والدرجات.
- **قيد صدق في تقييم النطق:** لا يُسمح بـ`accuracy_score` إلا إذا كانت الطريقة `phoneme_assessment` (قيد `CHECK` في قاعدة البيانات نفسها).
- **حذف يتحكم به ولي الأمر:** حذف حساب ولي الأمر يحذف كل بيانات أطفاله تتابعياً (CASCADE) — مُختبَر.

## الجداول (21)

| المجموعة | الجدول | الغرض |
|----------|--------|-------|
| الهوية | `users` | هوية الدخول (role: parent/student/admin) |
| | `parents` | ملف ولي الأمر + موافقة ولي الأمر (`consent_*`) + PIN لمنطقة الأهل |
| | `students` | ملف الطفل، المستوى، المعلم المفضل، إظهار العربية، الهدف اليومي |
| | `parent_settings` | حدود الوقت، السماح بالمحادثة الحرة، فترة الاحتفاظ بالنصوص |
| | `refresh_tokens` | رموز التحديث (مخزنة كـhash فقط) |
| | `teachers` | شخصيات Emma / Daniel / Alex (الموجّه `persona_prompt` لا يُرسل للتطبيق) |
| المنهج | `curriculum_units` | الوحدات 1–8 |
| | `lessons` | الدروس + `steps` (JSON يصف تسلسل الدرس العشري) + درجة النجاح |
| | `vocabulary` | الكلمة، المعنى العربي، النطق التقريبي بالعربية، IPA، مثال + ترجمته، مفاتيح الصوت |
| | `lesson_vocabulary` | ربط الدرس بالكلمات |
| | `student_vocabulary` | حالة التكرار المتباعد لكل كلمة لكل طالب |
| النشاط | `lesson_sessions` | جلسة درس: الخطوة الحالية، الدرجة، النجوم، النجاح، الملخص |
| | `conversation_sessions` | جلسة محادثة صوتية: الوضع، السيناريو، الزمن، متوسط التأخير |
| | `conversation_messages` | رسائل المحادثة (en + ar + التصحيح + هل قوطع المعلم) |
| | `pronunciation_results` | نتائج النطق (الطريقة، الدرجات، الكلمات الناقصة، تفاصيل الفونيمات) |
| | `assessments` | الاختبارات القصيرة والألعاب ونتائجها |
| | `achievements` / `student_achievements` | الشارات والمكافآت |
| | `daily_activity` | تجميع يومي للوحات المعلومات ولتطبيق حدود الوقت |
| الاشتراك | `subscriptions` | جاهز لـStoreKit 2 (مُعطّل حتى اختبار MVP) |
| التدقيق | `audit_events` | سجل إجراءات الخصوصية (إنشاء طالب، حذف بيانات…) |

## علاقات أساسية
```
users 1─1 parents 1─* students 1─* lesson_sessions *─1 lessons *─1 curriculum_units
                         │  1─* conversation_sessions 1─* conversation_messages
                         │  1─* pronunciation_results, assessments, student_vocabulary
parents 1─* parent_settings (افتراضي + لكل طفل), subscriptions
```

## ملاحظة للمرحلة 2
حذف صف `users` الخاص بولي الأمر يحذف `students` تتابعياً لكن **لا** يحذف صفوف `users` الخاصة بالأطفال (لأن العلاقة من `students` إلى `users`). خدمة الحذف في المرحلة 2 ستحذف صفوف `users` للأطفال أولاً ضمن نفس المعاملة، وسيُضاف اختبار لذلك.

## الترحيلات (Migrations)
سيتم في المرحلة 2 تغليف ملف SQL هذا في ترحيل Alembic أول (`op.execute`) بحيث يكون Alembic هو مسار الترقية الوحيد بعدها.
