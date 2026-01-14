# autochecker/github_client.py
import requests
import json
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional

CACHE_DIR = Path(".autochecker_cache")
CACHE_DIR.mkdir(exist_ok=True)

class GitHubClient:
    """
    Клиент для взаимодействия с GitHub REST API.
    Реализует кэширование ответов API на диск.
    """
    def __init__(self, token: str, repo_owner: str, repo_name: str):
        self._owner = repo_owner
        self._repo_name = repo_name
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        self._base_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}"
        print(f"🚀 Инициализирован GitHubClient для репозитория: {repo_owner}/{repo_name}")

    def _get_cached(self, endpoint: str) -> Optional[Any]:
        """Пытается получить ответ из кэша."""
        cache_key = hashlib.md5(f"{self._base_url}/{endpoint}".encode()).hexdigest()
        cache_file = CACHE_DIR / cache_key
        if cache_file.exists():
            print(f"  CACHE HIT: {endpoint}")
            with open(cache_file, "r") as f:
                return json.load(f)
        print(f"  CACHE MISS: {endpoint}")
        return None

    def _set_cache(self, endpoint: str, data: Any):
        """Сохраняет ответ в кэш."""
        cache_key = hashlib.md5(f"{self._base_url}/{endpoint}".encode()).hexdigest()
        cache_file = CACHE_DIR / cache_key
        with open(cache_file, "w") as f:
            json.dump(data, f)

    def _get(self, endpoint: str, use_cache: bool = True) -> Optional[Any]:
        """Выполняет GET-запрос с поддержкой кэширования."""
        full_endpoint_url = self._base_url
        if endpoint:
            full_endpoint_url += f"/{endpoint}"

        if use_cache:
            cached_data = self._get_cached(full_endpoint_url)
            if cached_data:
                return cached_data
        
        try:
            response = requests.get(full_endpoint_url, headers=self._headers)
            response.raise_for_status()
            data = response.json()
            if use_cache:
                self._set_cache(full_endpoint_url, data)
            return data
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                print(f"  ❌ Ресурс не найден: {full_endpoint_url}")
                return None
            print(f"  ❌ HTTP ошибка при запросе к {full_endpoint_url}: {e}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"  ❌ Ошибка сети при запросе к {full_endpoint_url}: {e}")
            return None

    def get_repo_info(self) -> Optional[Dict[str, Any]]:
        """Получает базовую информацию о репозитории."""
        # Для базовой информации кэш не используем, чтобы всегда иметь свежие данные
        return self._get("", use_cache=False)

    def get_commits(self, branch: str) -> List[Dict[str, Any]]:
        """Получает список коммитов для ветки."""
        return self._get(f"commits?sha={branch}&per_page=100") or []

    def get_issues(self) -> List[Dict[str, Any]]:
        """Получает список всех issues."""
        return self._get("issues?state=all&per_page=100") or []

    def get_pull_requests(self) -> List[Dict[str, Any]]:
        """Получает список всех pull requests."""
        return self._get("pulls?state=all&per_page=100") or []
