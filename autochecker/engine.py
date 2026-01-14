# autochecker/engine.py
import re
from typing import List, Dict, Any, Optional
from .github_client import GitHubClient
from .repo_reader import RepoReader

class CheckResult(Dict):
    id: str
    status: str # PASS, FAIL, ERROR
    description: str
    details: Optional[str]

class CheckEngine:
    """Движок, выполняющий проверки на основе данных."""
    def __init__(self, client: GitHubClient, reader: RepoReader):
        self._client = client
        self._reader = reader
        self._data_cache = {}

    def _get_commits(self):
        if 'commits' not in self._data_cache:
            repo_info = self._client.get_repo_info()
            if repo_info:
                self._data_cache['commits'] = self._client.get_commits(repo_info['default_branch'])
            else:
                self._data_cache['commits'] = []
        return self._data_cache['commits']
    
    def _get_issues(self):
        if 'issues' not in self._data_cache:
            self._data_cache['issues'] = self._client.get_issues()
        return self._data_cache['issues']
    
    def _get_prs(self):
        if 'prs' not in self._data_cache:
            self._data_cache['prs'] = self._client.get_pull_requests()
        return self._data_cache['prs']

    # --- Примитивы проверок ---

    def check_repo_exists(self) -> bool:
        return self._client.get_repo_info() is not None

    def check_file_exists(self, path: str) -> bool:
        return self._reader.file_exists(path)

    def check_commit_message_regex(self, pattern: str) -> bool:
        commits = self._get_commits()
        if not commits:
            return False
        # Проверяем, что ВСЕ коммиты соответствуют паттерну
        for commit in commits:
            if not re.match(pattern, commit['commit']['message']):
                return False
        return True

    def check_issues_count(self, title_regex: str, min_count: int) -> bool:
        issues = self._get_issues()
        count = 0
        for issue in issues:
            if re.match(title_regex, issue['title']):
                count += 1
        return count >= min_count

    def check_pr_merged_count(self, min_count: int) -> bool:
        prs = self._get_prs()
        count = sum(1 for pr in prs if pr.get('merged_at'))
        return count >= min_count

    def run_check(self, check_id: str, check_type: str, params: Dict[str, Any]) -> CheckResult:
        """Запускает одну проверку по ее типу."""
        status = "FAIL"
        details = ""
        try:
            if check_type == "repo_exists":
                if self.check_repo_exists(): status = "PASS"
            elif check_type == "file_exists":
                if self.check_file_exists(**params): status = "PASS"
            elif check_type == "commit_message_regex":
                if self.check_commit_message_regex(**params): status = "PASS"
            elif check_type == "issues_count":
                if self.check_issues_count(**params): status = "PASS"
            elif check_type == "pr_merged_count":
                 if self.check_pr_merged_count(**params): status = "PASS"
            else:
                status = "ERROR"
                details = f"Неизвестный тип проверки: {check_type}"

        except Exception as e:
            status = "ERROR"
            details = f"Ошибка при выполнении проверки '{check_id}': {e}"
        
        return CheckResult(id=check_id, status=status, details=details)
