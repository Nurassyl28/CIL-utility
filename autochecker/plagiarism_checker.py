# autochecker/plagiarism_checker.py
import hashlib
from typing import Dict, List, Tuple
from .repo_reader import RepoReader


class PlagiarismChecker:
    """Проверка на плагиат путем сравнения кода между студентами."""
    
    def __init__(self):
        self._student_code_signatures: Dict[str, Dict[str, str]] = {}
        # Словарь: student_alias -> {file_path -> code_hash}
    
    def add_student_code(self, student_alias: str, reader: RepoReader):
        """Добавляет код студента для сравнения."""
        signatures = {}
        
        if not reader._zip_file:
            return signatures
        
        # Получаем список всех файлов в репозитории
        all_files = [f for f in reader._zip_file.namelist() 
                    if not f.endswith('/') and f.startswith(reader._root_dir)]
        
        # Игнорируем некоторые файлы
        ignore_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.pdf', '.zip', '.exe'}
        
        for file_path in all_files:
            # Пропускаем файлы в .git, node_modules и т.д.
            if any(ignored in file_path for ignored in ['.git/', 'node_modules/', '__pycache__/', '.venv/']):
                continue
            
            # Пропускаем файлы с игнорируемыми расширениями
            if any(file_path.lower().endswith(ext) for ext in ignore_extensions):
                continue
            
            try:
                content = reader.read_file(file_path.replace(reader._root_dir, ''))
                if content:
                    # Создаем хеш содержимого файла
                    content_hash = hashlib.md5(content.encode('utf-8')).hexdigest()
                    # Нормализуем путь (убираем root_dir)
                    normalized_path = file_path.replace(reader._root_dir, '')
                    signatures[normalized_path] = content_hash
            except:
                continue
        
        self._student_code_signatures[student_alias] = signatures
        return signatures
    
    def check_plagiarism(self, student_alias: str, threshold: float = 0.8) -> List[Dict]:
        """
        Проверяет плагиат для конкретного студента.
        Возвращает список подозрительных совпадений.
        threshold: порог схожести (0.0 - 1.0)
        """
        if student_alias not in self._student_code_signatures:
            return []
        
        student_files = self._student_code_signatures[student_alias]
        matches = []
        
        for other_student, other_files in self._student_code_signatures.items():
            if other_student == student_alias:
                continue
            
            # Считаем совпадения по хешам файлов
            common_files = set(student_files.keys()) & set(other_files.keys())
            if not common_files:
                continue
            
            identical_files = []
            similar_files = []
            
            for file_path in common_files:
                if student_files[file_path] == other_files[file_path]:
                    identical_files.append(file_path)
                else:
                    # Можно добавить более сложное сравнение (например, через difflib)
                    pass
            
            if identical_files:
                similarity = len(identical_files) / max(len(student_files), len(other_files))
                if similarity >= threshold:
                    matches.append({
                        "suspicious_student": other_student,
                        "similarity_score": similarity,
                        "identical_files": identical_files,
                        "common_files_count": len(common_files),
                        "total_files_student": len(student_files),
                        "total_files_other": len(other_files)
                    })
        
        # Сортируем по убыванию схожести
        matches.sort(key=lambda x: x['similarity_score'], reverse=True)
        return matches
    
    def get_all_plagiarism_report(self, threshold: float = 0.8) -> Dict[str, List[Dict]]:
        """Получает отчет о плагиате для всех студентов."""
        all_matches = {}
        for student_alias in self._student_code_signatures.keys():
            matches = self.check_plagiarism(student_alias, threshold)
            if matches:
                all_matches[student_alias] = matches
        return all_matches
