# main.py
import os
from pathlib import Path

import typer
from dotenv import load_dotenv

from autochecker.spec import load_spec
from autochecker.github_client import GitHubClient
from autochecker.repo_reader import RepoReader
from autochecker.engine import CheckEngine
from autochecker.reporter import Reporter

# Создаем приложение Typer
app = typer.Typer()

load_dotenv()  # Подхватываем токены из .env, если файл существует


@app.command()
def run(
    spec_path: Path = typer.Option("specs/lab-01.yaml", "--spec", help="Путь к файлу спецификации .yaml"),
    output_dir: str = typer.Option("results", "--output", help="Папка для сохранения результатов"),
    token: str = typer.Option(..., envvar="GITHUB_TOKEN", help="GitHub Personal Access Token. Можно также задать через переменную окружения GITHUB_TOKEN"),
    gemini_api_key: str = typer.Option(None, envvar="GEMINI_API_KEY", help="Gemini API Key. Можно также задать через переменную окружения GEMINI_API_KEY"),
):
    """
    Интерактивно запрашивает данные и запускает проверку для одного репозитория.
    """
    print("--- Autochecker запущен в интерактивном режиме ---")

    # --- Интерактивный ввод ---
    try:
        student_alias = input("Введите GitHub alias студента (например, Nurassyl28): ").strip()
        repo_name = input(f"Введите имя репозитория (например, lab-01-market-product-and-git): ").strip()

        if not spec_path.exists():
            print(f"❌ Файл спецификации не найден: {spec_path}")
            raise typer.Exit(code=1)

        lab_spec = load_spec(str(spec_path))
        
        # Заменяем имя репозитория из спеки на введенное пользователем
        lab_spec.repo_name = repo_name

        # --- Подготовка ---
        Path(output_dir).mkdir(exist_ok=True)
        # Очищаем старые результаты для этого студента
        student_results_dir = Path(output_dir) / student_alias
        student_results_dir.mkdir(exist_ok=True)
        
        if (student_results_dir / "summary.html").exists():
            (student_results_dir / "summary.html").unlink()
        if (student_results_dir / "results.jsonl").exists():
            (student_results_dir / "results.jsonl").unlink()

        # --- Основная логика проверки ---
        print(f"\n--- 👨‍🎓 Начинаю проверку: {student_alias}/{repo_name} ---")

        client = GitHubClient(token=token, repo_owner=student_alias, repo_name=lab_spec.repo_name)

        # 1. Проверяем доступность репозитория
        repo_info = client.get_repo_info()
        if not repo_info:
            print(f"  ❌ Не удалось получить информацию о репозитории. Возможные причины:")
            print(f"     - Репозиторий не существует")
            print(f"     - Неверный GitHub токен (ошибка 401)")
            print(f"     - Репозиторий приватный и токен не имеет доступа")
            # Создаем отчет о провале
            reporter = Reporter(student_alias=student_alias, results=[])
            reporter.write_failure_report(student_results_dir, "Не удалось получить информацию о репозитории. Проверьте токен и доступность репозитория.")
            raise typer.Exit()
        
        if repo_info.get('private'):
            print(f"  ❌ Репозиторий является приватным. Проверка остановлена.")
            # Создаем отчет о провале
            reporter = Reporter(student_alias=student_alias, results=[])
            reporter.write_failure_report(student_results_dir, "Репозиторий является приватным.")
            raise typer.Exit()

        # 2. Скачиваем архив
        reader = RepoReader(owner=student_alias, repo_name=lab_spec.repo_name, token=token)
        if not reader._zip_file:
             print(f"  ❌ Не удалось скачать zip-архив репозитория. Проверка файловой системы будет невозможна.")
        
        # 3. Запускаем проверки
        engine = CheckEngine(client, reader)
        results = []
        for check_spec in lab_spec.checks:
            print(f"  ▶️  Запуск проверки: {check_spec.description or check_spec.id}")
            result = engine.run_check(check_spec.id, check_spec.type, check_spec.params, check_spec.description)
            results.append(result)

        # 4. Анализ с помощью LLM
        llm_analysis = None
        if gemini_api_key:
            try:
                from autochecker.llm_analyzer import analyze_repo
                print("🤖 Запуск анализа с помощью LLM...")
                llm_analysis = analyze_repo(gemini_api_key, reader, client, lab_spec=lab_spec, repo_owner=student_alias)
            except ImportError:
                print("🚨 Не найдены зависимости для LLM-анализа.")
                print("   Пожалуйста, установите их: pip install -r requirements.txt")
                llm_analysis = {
                    "verdict": "анализ_пропущен",
                    "reasons": ["Зависимости для LLM-анализа не установлены. Выполните 'pip install -r requirements.txt'"],
                    "quotes": [],
                }
        else:
            print("⏭️  LLM-анализ пропущен, так как не задан GEMINI_API_KEY.")


        # 5. Сохраняем отчет
        reporter = Reporter(
            student_alias=student_alias, 
            results=results, 
            repo_url=repo_info.get("html_url"),
            llm_analysis=llm_analysis
        )
        reporter.write_jsonl(student_results_dir)
        reporter.write_html(student_results_dir)

        print(f"\n--- ✅ Проверка завершена. Результаты сохранены в: {student_results_dir} ---")

    except KeyboardInterrupt:
        print("\n\nПрограмма прервана пользователем.")
    except typer.Exit:
        # Это нормальный выход, не обрабатываем
        raise
    except Exception as e:
        # Безопасно обрабатываем ошибку с Unicode
        try:
            error_msg = str(e) if str(e) else repr(e)
        except (UnicodeEncodeError, UnicodeDecodeError):
            error_msg = repr(e) if repr(e) else "Unknown error"
        
        if error_msg:
            try:
                print(f"\n❌ Произошла непредвиденная ошибка: {error_msg}")
            except UnicodeEncodeError:
                print(f"\n[ERROR] Unexpected error: {error_msg}")
        else:
            print(f"\n❌ Произошла непредвиденная ошибка (тип: {type(e).__name__})")
        raise typer.Exit(code=1)

@app.command()
def batch(
    students_file: Path = typer.Option(..., "--students", help="Путь к файлу со списком студентов (CSV, JSON или txt)"),
    repo_name: str = typer.Option(..., "--repo", help="Имя репозитория для всех студентов"),
    spec_path: Path = typer.Option("specs/lab-01.yaml", "--spec", help="Путь к файлу спецификации .yaml"),
    output_dir: str = typer.Option("results", "--output", help="Папка для сохранения результатов"),
    token: str = typer.Option(..., envvar="GITHUB_TOKEN", help="GitHub Personal Access Token"),
    gemini_api_key: str = typer.Option(None, envvar="GEMINI_API_KEY", help="Gemini API Key (опционально)"),
    max_workers: int = typer.Option(10, "--workers", help="Количество параллельных потоков"),
    check_plagiarism: bool = typer.Option(True, "--plagiarism/--no-plagiarism", help="Включить проверку на плагиат"),
    plagiarism_threshold: float = typer.Option(0.8, "--plagiarism-threshold", help="Порог схожести для плагиата (0.0-1.0)"),
):
    """
    Массовая проверка студентов из файла.
    
    Формат файла students_file:
    - CSV: первая колонка - student_alias
    - JSON: массив строк ["student1", "student2", ...]
    - TXT: по одной строке на студента
    """
    try:
        from autochecker.batch_processor import process_batch
        
        process_batch(
            students_file=str(students_file),
            repo_name=repo_name,
            spec_path=str(spec_path),
            token=token,
            gemini_api_key=gemini_api_key,
            output_dir=output_dir,
            max_workers=max_workers,
            check_plagiarism=check_plagiarism,
            plagiarism_threshold=plagiarism_threshold
        )
    except Exception as e:
        print(f"\n❌ Ошибка при массовой проверке: {e}")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
