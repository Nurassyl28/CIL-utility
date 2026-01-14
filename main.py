# main.py
import os
from pathlib import Path
import typer
from autochecker.spec import load_spec
from autochecker.github_client import GitHubClient
from autochecker.repo_reader import RepoReader
from autochecker.engine import CheckEngine
from autochecker.reporter import Reporter

# Создаем приложение Typer
app = typer.Typer()

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
        student_alias = input("Введите GitHub alias студента (например, octocat): ").strip()
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
        if not repo_info or repo_info.get('private'):
            status = "ПРИВАТНЫЙ" if (repo_info and repo_info.get('private')) else "НЕ НАЙДЕН"
            print(f"  ❌ Репозиторий {status}. Проверка остановлена.")
            # Создаем отчет о провале
            reporter = Reporter(student_alias=student_alias, results=[])
            reporter.write_failure_report(student_results_dir, f"Репозиторий не найден или является приватным ({status}).")
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
            result = engine.run_check(check_spec.id, check_spec.type, check_spec.params)
            results.append(result)

        # 4. Анализ с помощью LLM
        llm_analysis = None
        if gemini_api_key:
            try:
                from autochecker.llm_analyzer import analyze_repo
                print("🤖 Запуск анализа с помощью LLM...")
                llm_analysis = analyze_repo(gemini_api_key, reader, client)
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
    except Exception as e:
        print(f"\n❌ Произошла непредвиденная ошибка: {e}")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
