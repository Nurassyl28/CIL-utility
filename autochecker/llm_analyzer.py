# autochecker/llm_analyzer.py
import json
from typing import Dict

import google.genai as genai
from .repo_reader import RepoReader
from .github_client import GitHubClient


def analyze_repo(gemini_api_key: str, reader: RepoReader, client: GitHubClient) -> Dict:
    """
    Анализ репозитория с помощью Gemini.
    Обновлено под google-genai >=1.4: используем Client().models.generate_content.
    """
    llm_client = genai.Client(api_key=gemini_api_key)

    # 1. Собираем контент для анализа
    readme_content = reader.read_file("README.md") or "README.md не найден."

    repo_info = client.get_repo_info()
    default_branch = repo_info.get('default_branch', 'main') if repo_info else 'main'

    commits = client.get_commits(branch=default_branch)
    commit_messages = "\n".join([c['commit']['message'] for c in commits]) if commits else "Коммиты не найдены."

    repo_content = f"""
Содержимое README.md:
---
{readme_content}
---

История коммитов:
---
{commit_messages}
---
"""

    # 2. Формулируем промпт
    prompt = f"""
Ты — опытный преподаватель по программированию, проверяющий учебный проект.
Проанализируй следующую информацию о работе студента:
{repo_content}

Твоя задача — дать конструктивную обратную связь.
Ответ должен быть в формате JSON со следующими ключами:
- "verdict": Краткий итог. Одно из: "excellent", "good", "satisfactory", "weak", "fail".
- "reasons": Список строк с объяснением оценки. Что было хорошо, а чего не хватило?
- "quotes": Список из 2-3 показательных цитат из предоставленных материалов (README или коммиты), которые подтверждают твои выводы.

Пример ответа:
{{
  "verdict": "good",
  "reasons": [
    "Хорошая структура README файла.",
    "Не все коммиты следуют принятому стилю."
  ],
  "quotes": [
    "feat: add user authentication",
    "Initial commit"
  ]
}}

Теперь, пожалуйста, предоставь свой анализ в формате JSON.
"""

    # 3. Вызываем модель и парсим результат
    try:
        response = llm_client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt,
        )
        cleaned_json = (
            response.text.strip()
            .replace("```json", "")
            .replace("```", "")
            .strip()
        )
        analysis = json.loads(cleaned_json)
        return analysis
    except Exception as e:
        print(f"🚨 Ошибка при вызове Gemini API или парсинге JSON: {e}")
        return {
            "verdict": "анализ_провален",
            "reasons": [f"Произошла ошибка при анализе: {e}"],
            "quotes": [],
        }
