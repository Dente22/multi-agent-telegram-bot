# База знаний (демо-политики)

Примеры корпоративных регламентов для RAG-тестов:

| Файл | Отдел |
|------|--------|
| `hr-policy.txt` | HR |
| `accounting-policy.txt` | Бухгалтерия |
| `it-policy.txt` | IT |
| `security-sb-policy.txt` | СБ (служба безопасности) |

Форматы: `.txt`, `.md`, `.pdf`, `.docx`.

При старте API (`AUTO_INGEST_KNOWLEDGE=true`) файлы индексируются в глобальную pgvector KB.
Ручная переиндексация: `python scripts/ingest_knowledge.py`
