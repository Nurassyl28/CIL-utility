# autochecker/llm_analyzer.py
import json
import requests
from typing import Dict
from .repo_reader import RepoReader
from .github_client import GitHubClient


def analyze_repo(gemini_api_key: str, reader: RepoReader, client: GitHubClient) -> Dict:
    """
    Анализ репозитория с помощью Gemini через REST API.
    Используем прямые HTTP-запросы вместо библиотеки для избежания проблем с кодировкой.
    """

    # 1. Собираем контент для анализа
    readme_content = reader.read_file("README.md") or "README.md not found."
    
    # Безопасно обрабатываем содержимое файла
    if readme_content and isinstance(readme_content, bytes):
        try:
            readme_content = readme_content.decode('utf-8')
        except UnicodeDecodeError:
            readme_content = readme_content.decode('utf-8', errors='replace')
    
    # Ограничиваем длину для экономии токенов
    if len(readme_content) > 2000:
        readme_content = readme_content[:2000] + "... (truncated)"

    repo_info = client.get_repo_info()
    default_branch = repo_info.get('default_branch', 'main') if repo_info else 'main'

    commits = client.get_commits(branch=default_branch)
    commit_messages = "\n".join([c['commit']['message'] for c in commits[:20]]) if commits else "No commits found."
    
    # Безопасно обрабатываем сообщения коммитов
    if commit_messages and isinstance(commit_messages, bytes):
        try:
            commit_messages = commit_messages.decode('utf-8')
        except UnicodeDecodeError:
            commit_messages = commit_messages.decode('utf-8', errors='replace')
    
    # Ограничиваем длину
    if len(commit_messages) > 1000:
        commit_messages = commit_messages[:1000] + "... (truncated)"

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

    # 2. Формулируем промпт (используем английский для избежания проблем с кодировкой)
    # Но ответ может быть на русском
    prompt = f"""You are an experienced programming instructor reviewing a student's project.
Analyze the following information about the student's work:
{repo_content}

Your task is to provide constructive feedback.
The response must be in JSON format with the following keys:
- "verdict": Brief summary. One of: "excellent", "good", "satisfactory", "weak", "fail".
- "reasons": List of strings explaining the assessment. What was good, what was missing?
- "quotes": List of 2-3 illustrative quotes from the provided materials (README or commits) that support your conclusions.

Example response:
{{
  "verdict": "good",
  "reasons": [
    "Good README file structure.",
    "Not all commits follow the accepted style."
  ],
  "quotes": [
    "feat: add user authentication",
    "Initial commit"
  ]
}}

Please provide your analysis in JSON format. You can write reasons in Russian if needed.
"""

    # 3. Вызываем модель через REST API напрямую
    try:
        # Сначала получаем список доступных моделей
        list_models_url = "https://generativelanguage.googleapis.com/v1beta/models"
        params = {"key": gemini_api_key}
        
        available_models = []
        try:
            list_response = requests.get(list_models_url, params=params, timeout=10)
            if list_response.status_code == 200:
                models_data = list_response.json()
                if 'models' in models_data:
                    # Фильтруем модели, которые поддерживают generateContent
                    for model in models_data['models']:
                        model_name = model.get('name', '')
                        supported_methods = model.get('supportedGenerationMethods', [])
                        if 'generateContent' in supported_methods:
                            # Извлекаем короткое имя модели (без префикса models/)
                            short_name = model_name.replace('models/', '')
                            available_models.append(short_name)
                    print(f"📋 Найдено доступных моделей: {len(available_models)}")
                    if available_models:
                        print(f"   Используем: {', '.join(available_models[:3])}...")
        except Exception as list_error:
            print(f"⚠️  Не удалось получить список моделей: {list_error}")
        
        # Если не удалось получить список, используем стандартный набор
        if not available_models:
            available_models = [
                "gemini-1.5-flash",
                "gemini-1.5-pro",
                "gemini-pro",
            ]
        
        # Формируем базовый URL без ключа (ключ передадим через параметры)
        api_url_template = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        
        last_error = None
        for model_name in available_models:
            try:
                # Формируем URL для API (без ключа в URL)
                api_url = api_url_template.format(model=model_name)
                
                # Формируем тело запроса
                request_body = {
                    "contents": [{
                        "parts": [{
                            "text": prompt
                        }]
                    }]
                }
                
                # Отправляем запрос с ключом в параметрах и правильными заголовками
                headers = {
                    "Content-Type": "application/json"
                }
                
                # Передаем ключ через параметры запроса
                params = {
                    "key": gemini_api_key
                }
                
                response = requests.post(
                    api_url,
                    json=request_body,
                    headers=headers,
                    params=params,
                    timeout=30
                )
                
                # Проверяем статус ответа
                response.raise_for_status()
                
                # Парсим JSON ответ
                result = response.json()
                
                # Извлекаем текст из ответа
                if 'candidates' in result and len(result['candidates']) > 0:
                    candidate = result['candidates'][0]
                    if 'content' in candidate and 'parts' in candidate['content']:
                        text = candidate['content']['parts'][0]['text']
                    else:
                        raise ValueError("Не удалось извлечь текст из ответа API")
                else:
                    raise ValueError("API вернул пустой ответ")
                
                # Очищаем JSON от markdown разметки
                cleaned_json = (
                    text.strip()
                    .replace("```json", "")
                    .replace("```", "")
                    .strip()
                )
                
                # Парсим JSON
                analysis = json.loads(cleaned_json)
                print(f"✅ Успешно использована модель: {model_name}")
                return analysis
                
            except requests.exceptions.RequestException as req_error:
                last_error = req_error
                error_msg = str(req_error)
                
                # Получаем детали ошибки из ответа, если есть
                if hasattr(req_error, 'response') and req_error.response is not None:
                    try:
                        error_details = req_error.response.json()
                        error_msg = f"{error_msg}: {error_details}"
                        # Выводим детали ошибки для диагностики
                        if req_error.response.status_code == 404:
                            print(f"⚠️  Модель {model_name} (API {api_version}) не найдена. Детали: {error_details}")
                    except:
                        error_text = req_error.response.text[:300]
                        error_msg = f"{error_msg}: {error_text}"
                        if req_error.response.status_code == 404:
                            print(f"⚠️  Модель {model_name} (API {api_version}) не найдена. Ответ: {error_text}")
                
                # Пропускаем ошибки 404 и пробуем следующую модель
                if "404" not in error_msg and "NOT_FOUND" not in error_msg:
                    print(f"⚠️  Ошибка при запросе к модели {model_name}: {error_msg[:200]}")
                    if model_name == available_models[-1]:  # Если это последняя модель
                        raise
                continue
            except (json.JSONDecodeError, ValueError, KeyError) as parse_error:
                last_error = parse_error
                print(f"⚠️  Ошибка при парсинге ответа от модели {model_name}: {str(parse_error)[:100]}")
                if model_name == candidates[-1]:  # Если это последняя модель
                    raise
                continue

        raise last_error or RuntimeError("LLM call failed")
    except Exception as e:
        # Безопасно обрабатываем ошибку с Unicode
        try:
            error_msg = str(e)
        except UnicodeEncodeError:
            error_msg = repr(e)  # Используем repr если str не работает
        
        print(f"🚨 Ошибка при вызове Gemini API или парсинге JSON: {error_msg}")
        return {
            "verdict": "анализ_провален",
            "reasons": [f"Произошла ошибка при анализе: {error_msg}"],
            "quotes": [],
        }
