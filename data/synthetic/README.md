# data/synthetic

Сюда `scripts/generate_synthetic_field.py` пишет CSV-дубликат данных,
которые одновременно уходят в БД (если не указан `--no-db`). CSV-файлы
сюда не коммитятся (см. .gitignore) — генерируются заново командой:

```
python scripts/generate_synthetic_field.py
```
