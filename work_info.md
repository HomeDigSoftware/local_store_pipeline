אני מחפש איש/אשת DevOps או Platform Engineer מנוסה, לפרויקט אבחון ושיפור של מערכת SaaS קיימת בפרודקשן.

מדובר במערכת פעילה, ולכן אני מחפש מישהו עם ניסיון אמיתי באבחון תקלות production, ולא רק בהקמת שרתים או כתיבת pipeline בסיסי.

הסטאק הקיים
Python / FastAPI
SQLAlchemy
PostgreSQL
Supabase / Supavisor
React / Next.js
Docker Compose
GitHub Actions
Linux VPS על Contabo


הבעיות הקיימות
תהליך deployment שלוקח כ־45-90 דקות בכל הרצה.
תקלות שמתגלות רק בשלבים מאוחרים של ה־deploy.
בדרך כלל נדרשות מספר הרצות, כך ששחרור גרסה יכול לקחת 24–48 שעות ואף יותר.
בעיות ביצועים באפליקציה.
בעיות database connections ו־connection pooling מול Supabase.
חשד לבעיות של:
חיבורי DB שלא נסגרים.
pool configuration לא נכון.
יותר מדי workers.
slow queries.
long transactions.
locks.
שימוש לא נכון ב־Supavisor transaction/session mode.
עומס CPU / RAM / disk.