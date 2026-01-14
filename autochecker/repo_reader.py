# autochecker/repo_reader.py
import requests
import zipfile
import io
from typing import Optional

class RepoReader:
    """
    Читатель репозитория.
    Скачивает zip-архив репозитория в память и предоставляет методы
    для проверки наличия и содержимого файлов.
    """
    def __init__(self, owner: str, repo_name: str, token: str):
        self._owner = owner
        self._repo_name = repo_name
        self._token = token
        self._zip_file: Optional[zipfile.ZipFile] = None
        self._root_dir = ""
        self._download()

    def _download(self):
        """Скачивает zipball в память."""
        print(f"🚚 Загрузка zip-архива для {self._owner}/{self._repo_name}...")
        zip_url = f"https://api.github.com/repos/{self._owner}/{self._repo_name}/zipball"
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            response = requests.get(zip_url, headers=headers, stream=True)
            response.raise_for_status()
            self._zip_file = zipfile.ZipFile(io.BytesIO(response.content))
            # Определяем корневую папку в архиве (обычно 'owner-repo-sha')
            self._root_dir = self._zip_file.namelist()[0]
            print("✅ Архив успешно загружен в память.")
        except requests.exceptions.RequestException as e:
            print(f"  ❌ Не удалось скачать архив: {e}")
        except zipfile.BadZipFile:
            print("  ❌ Скачанный файл не является корректным zip-архивом.")
            self._zip_file = None

    def file_exists(self, path: str) -> bool:
        """Проверяет наличие файла в архиве."""
        if not self._zip_file:
            return False
        full_path = f"{self._root_dir}{path}"
        return full_path in self._zip_file.namelist()

    def read_file(self, path: str) -> Optional[str]:
        """Читает содержимое файла из архива."""
        if not self.file_exists(path):
            return None
        
        full_path = f"{self._root_dir}{path}"
        try:
            with self._zip_file.open(full_path) as f:
                return f.read().decode("utf-8")
        except (KeyError, UnicodeDecodeError):
            return None
