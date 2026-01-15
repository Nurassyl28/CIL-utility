# autochecker/llm_analyzer.py
import json
import requests
from typing import Dict
from .repo_reader import RepoReader
from .github_client import GitHubClient


def analyze_repo(gemini_api_key: str, reader: RepoReader, client: GitHubClient, lab_spec=None, repo_owner=None) -> Dict:
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
    repo_url = repo_info.get('html_url', '') if repo_info else ''
    
    # Получаем последний коммит для генерации ссылок
    commits = client.get_commits(branch=default_branch)
    commit_sha = commits[0]['sha'] if commits else 'main'
    commit_messages = "\n".join([c['commit']['message'] for c in commits[:20]]) if commits else "No commits found."
    
    # Формируем список задач из спецификации
    lab_tasks_description = ""
    if lab_spec and hasattr(lab_spec, 'checks'):
        tasks = []
        for i, check in enumerate(lab_spec.checks, 1):
            task_desc = f"Task {i}: {check.description or check.id}"
            if check.params:
                params_str = ", ".join([f"{k}={v}" for k, v in check.params.items()])
                task_desc += f" (Параметры: {params_str})"
            tasks.append(task_desc)
        lab_tasks_description = "\n".join(tasks) if tasks else "Задачи не указаны"
    else:
        lab_tasks_description = "Задачи не указаны в спецификации"
    
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

    # 2. Формулируем улучшенный промпт на основе системного промпта
    repo_name = lab_spec.repo_name if lab_spec else "unknown"
    owner = repo_owner or "unknown"
    
    prompt = f"""Ты — строгий и технический AI-ассистент для проверки студенческих лабораторных работ.
Твоя задача — проанализировать работу студента и сгенерировать детальный отчет.

### ВХОДНЫЕ ДАННЫЕ:
1. Репозиторий: {repo_url or f'https://github.com/{owner}/{repo_name}'}
2. Commit SHA (для ссылок): {commit_sha}
3. Список задач (Tasks):
{lab_tasks_description}

### ИНФОРМАЦИЯ О РАБОТЕ:
{repo_content}

### ИНСТРУКЦИЯ ПО ФОРМАТУ (Строго соблюдай!):

#### 1. СТРУКТУРА ОТЧЕТА
Для каждой задачи из списка задач создай отдельную секцию в формате:

### Task [N]: [Название задачи]
- **Результат:** [Используй эмодзи: ✅ Выполнено / ⚠️ С замечаниями / ❌ Не выполнено]
- **Аргументация:** [Краткое техническое объяснение, почему поставлена такая оценка. Укажи, что работает, а что нет.]
- **Цитаты и Код:** [Приведи фрагмент кода или цитату из коммитов, если есть.]
- **Ссылка:** [Если возможно, вставь прямую ссылку на файл или код в формате: https://github.com/{owner}/{repo_name}/blob/{commit_sha}/[путь]#L[строка]]

#### 2. ОБЩИЙ ВЕРДИКТ
В конце отчета укажи общую оценку работы.

### ОБЩАЯ ОЦЕНКА
- **Вердикт:** [excellent / good / satisfactory / weak / fail]
- **Обоснование:** [Краткое резюме всей работы]

### ВАЖНО:
- Пиши на русском языке
- Будь объективен и краток
- Используй техническую терминологию
- Если задача не выполнена, четко объясни почему
- Если есть проблемы, предложи конкретные улучшения

Ответ должен быть в формате JSON со следующими ключами:
{{
  "verdict": "excellent|good|satisfactory|weak|fail",
  "reasons": ["список строк с аргументацией"],
  "quotes": ["2-3 цитаты из коммитов или README"],
  "task_analysis": [
    {{
      "task_number": 1,
      "task_name": "название задачи",
      "result": "✅ Выполнено|⚠️ С замечаниями|❌ Не выполнено",
      "argumentation": "объяснение",
      "quotes": "цитаты",
      "link": "ссылка на код (если применимо)"
    }}
  ]
}}

Начинай анализ прямо сейчас.
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
                            print(f"⚠️  Модель {model_name} не найдена. Детали: {error_details}")
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
