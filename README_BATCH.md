# Массовая проверка студентов

## Формат файла со студентами

### CSV формат (рекомендуется)
Создайте файл `students.csv`:
```csv
student_alias
Nurassyl28
student2
student3
student4
...
```

### JSON формат
Создайте файл `students.json`:
```json
["Nurassyl28", "student2", "student3", "student4"]
```

### TXT формат
Создайте файл `students.txt` (по одной строке):
```
Nurassyl28
student2
student3
student4
```

## Запуск массовой проверки

```bash
python main.py batch \
  --students students.csv \
  --repo lab-01-market-product-and-git \
  --spec specs/lab-01.yaml \
  --output results \
  --workers 20 \
  --plagiarism \
  --plagiarism-threshold 0.8
```

## Параметры

- `--students` - путь к файлу со списком студентов (обязательно)
- `--repo` - имя репозитория для всех студентов (обязательно)
- `--spec` - путь к YAML спецификации (по умолчанию: specs/lab-01.yaml)
- `--output` - папка для результатов (по умолчанию: results)
- `--workers` - количество параллельных потоков (по умолчанию: 10)
- `--plagiarism` - включить проверку на плагиат
- `--plagiarism-threshold` - порог схожести 0.0-1.0 (по умолчанию: 0.8)
- `--gemini-api-key` - ключ для LLM анализа (опционально)

## Результаты

После выполнения создаются:
- `results/batch_summary.html` - HTML сводка
- `results/batch_summary.json` - JSON статистика
- `results/plagiarism_report.json` - отчет о плагиате
- `results/{student}/summary.html` - отчет для каждого студента
