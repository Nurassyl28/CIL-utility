# autochecker/batch_processor.py
import csv
import json
from pathlib import Path
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

from .spec import load_spec
from .github_client import GitHubClient
from .repo_reader import RepoReader
from .engine import CheckEngine
from .reporter import Reporter
from .plagiarism_checker import PlagiarismChecker


def process_single_student(
    student_alias: str,
    repo_name: str,
    lab_spec,
    token: str,
    gemini_api_key: Optional[str],
    output_dir: str,
    plagiarism_checker: Optional[PlagiarismChecker] = None
) -> Dict:
    """Обрабатывает одного студента. Возвращает результат или ошибку."""
    try:
        student_results_dir = Path(output_dir) / student_alias
        student_results_dir.mkdir(exist_ok=True, parents=True)
        
        # Очищаем старые результаты
        for old_file in ['summary.html', 'results.jsonl']:
            old_path = student_results_dir / old_file
            if old_path.exists():
                old_path.unlink()
        
        print(f"  👨‍🎓 Обработка: {student_alias}/{repo_name}")
        
        # Создаем клиенты
        client = GitHubClient(token=token, repo_owner=student_alias, repo_name=repo_name)
        
        # Проверяем доступность репозитория
        repo_info = client.get_repo_info()
        if not repo_info:
            reporter = Reporter(student_alias=student_alias, results=[])
            reporter.write_failure_report(
                student_results_dir,
                "Репозиторий не найден или недоступен."
            )
            return {
                "student": student_alias,
                "status": "error",
                "error": "Repository not found"
            }
        
        if repo_info.get('private'):
            reporter = Reporter(student_alias=student_alias, results=[])
            reporter.write_failure_report(
                student_results_dir,
                "Репозиторий является приватным."
            )
            return {
                "student": student_alias,
                "status": "error",
                "error": "Private repository"
            }
        
        # Скачиваем архив
        reader = RepoReader(owner=student_alias, repo_name=repo_name, token=token)
        
        # Добавляем код студента для проверки плагиата
        plagiarism_info = None
        if plagiarism_checker:
            plagiarism_checker.add_student_code(student_alias, reader)
            # Проверяем плагиат (но только после того, как все студенты добавлены)
            # Это будет сделано после обработки всех студентов
        
        # Запускаем проверки
        engine = CheckEngine(client, reader)
        results = []
        for check_spec in lab_spec.checks:
            result = engine.run_check(
                check_spec.id,
                check_spec.type,
                check_spec.params,
                check_spec.description
            )
            results.append(result)
        
        # LLM анализ (опционально, может быть медленным)
        llm_analysis = None
        if gemini_api_key:
            try:
                from .llm_analyzer import analyze_repo
                llm_analysis = analyze_repo(
                    gemini_api_key, reader, client,
                    lab_spec=lab_spec, repo_owner=student_alias
                )
            except Exception as e:
                llm_analysis = {
                    "verdict": "анализ_провален",
                    "reasons": [f"Ошибка LLM-анализа: {str(e)[:100]}"],
                    "quotes": [],
                }
        
        # Сохраняем отчет
        reporter = Reporter(
            student_alias=student_alias,
            results=results,
            repo_url=repo_info.get("html_url"),
            llm_analysis=llm_analysis
        )
        reporter.write_jsonl(student_results_dir)
        reporter.write_html(student_results_dir)
        
        # Подсчитываем статистику
        passed = sum(1 for r in results if r['status'] == 'PASS')
        total = len(results)
        score = (passed / total * 100) if total > 0 else 0
        
        return {
            "student": student_alias,
            "status": "success",
            "score": score,
            "passed": passed,
            "total": total,
            "repo_url": repo_info.get("html_url")
        }
        
    except Exception as e:
        error_msg = str(e)[:200]
        return {
            "student": student_alias,
            "status": "error",
            "error": error_msg
        }


def process_batch(
    students_file: str,
    repo_name: str,
    spec_path: str,
    token: str,
    gemini_api_key: Optional[str],
    output_dir: str,
    max_workers: int = 10,
    check_plagiarism: bool = True,
    plagiarism_threshold: float = 0.8
) -> Dict:
    """
    Обрабатывает список студентов из файла.
    
    Формат файла students_file (CSV):
    student_alias
    student1
    student2
    ...
    
    Или JSON:
    ["student1", "student2", ...]
    """
    # Загружаем список студентов
    students = []
    students_path = Path(students_file)
    
    if not students_path.exists():
        raise FileNotFoundError(f"Файл со списком студентов не найден: {students_file}")
    
    if students_path.suffix == '.csv':
        with open(students_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            students = [row.get('student_alias', list(row.values())[0]) for row in reader]
    elif students_path.suffix == '.json':
        with open(students_path, 'r', encoding='utf-8') as f:
            students = json.load(f)
    else:
        # Простой текстовый файл, по одной строке
        with open(students_path, 'r', encoding='utf-8') as f:
            students = [line.strip() for line in f if line.strip()]
    
    print(f"📋 Загружено студентов для проверки: {len(students)}")
    
    # Загружаем спецификацию
    lab_spec = load_spec(spec_path)
    lab_spec.repo_name = repo_name
    
    # Создаем папку для результатов
    Path(output_dir).mkdir(exist_ok=True, parents=True)
    
    # Инициализируем проверку плагиата
    plagiarism_checker = PlagiarismChecker() if check_plagiarism else None
    
    # Обрабатываем студентов (сначала без проверки плагиата)
    results = []
    start_time = time.time()
    
    print(f"\n🚀 Начинаю массовую проверку {len(students)} студентов...")
    print(f"   Параллельных потоков: {max_workers}")
    if check_plagiarism:
        print(f"   Проверка плагиата: включена (порог: {plagiarism_threshold})")
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                process_single_student,
                student,
                repo_name,
                lab_spec,
                token,
                gemini_api_key,
                output_dir,
                plagiarism_checker
            ): student
            for student in students
        }
        
        completed = 0
        for future in as_completed(futures):
            student = futures[future]
            try:
                result = future.result()
                results.append(result)
                completed += 1
                
                status_icon = "✅" if result['status'] == 'success' else "❌"
                if result['status'] == 'success':
                    print(f"  {status_icon} [{completed}/{len(students)}] {student}: {result.get('score', 0):.1f}%")
                else:
                    print(f"  {status_icon} [{completed}/{len(students)}] {student}: {result.get('error', 'Unknown error')}")
            except Exception as e:
                results.append({
                    "student": student,
                    "status": "error",
                    "error": str(e)[:200]
                })
                completed += 1
                print(f"  ❌ [{completed}/{len(students)}] {student}: Exception - {str(e)[:100]}")
    
    elapsed_time = time.time() - start_time
    
    # Проверяем плагиат после обработки всех студентов
    plagiarism_report = None
    if check_plagiarism and plagiarism_checker:
        print(f"\n🔍 Проверка на плагиат...")
        plagiarism_report = plagiarism_checker.get_all_plagiarism_report(plagiarism_threshold)
        
        # Сохраняем отчет о плагиате
        if plagiarism_report:
            plagiarism_file = Path(output_dir) / "plagiarism_report.json"
            with open(plagiarism_file, 'w', encoding='utf-8') as f:
                json.dump(plagiarism_report, f, ensure_ascii=False, indent=2)
            print(f"  📄 Отчет о плагиате сохранен: {plagiarism_file}")
            
            # Добавляем информацию о плагиате в HTML отчеты
            for student_alias, matches in plagiarism_report.items():
                student_dir = Path(output_dir) / student_alias
                if matches:
                    # Обновляем HTML отчет с информацией о плагиате
                    summary_file = student_dir / "summary.html"
                    if summary_file.exists():
                        with open(summary_file, 'r', encoding='utf-8') as f:
                            html_content = f.read()
                        
                        plagiarism_section = "<h2>⚠️ Проверка на плагиат</h2><ul>"
                        for match in matches[:3]:  # Показываем топ-3 совпадения
                            plagiarism_section += f"<li><b>{match['suspicious_student']}</b>: схожесть {match['similarity_score']*100:.1f}% ({len(match['identical_files'])} идентичных файлов)</li>"
                        plagiarism_section += "</ul>"
                        
                        # Вставляем после заголовка
                        html_content = html_content.replace("<h2>🤖", plagiarism_section + "<h2>🤖")
                        
                        with open(summary_file, 'w', encoding='utf-8') as f:
                            f.write(html_content)
    
    # Создаем общий отчет
    summary = {
        "total_students": len(students),
        "successful": sum(1 for r in results if r['status'] == 'success'),
        "failed": sum(1 for r in results if r['status'] == 'error'),
        "elapsed_time_seconds": elapsed_time,
        "average_time_per_student": elapsed_time / len(students) if students else 0,
        "plagiarism_detected": len(plagiarism_report) if plagiarism_report else 0,
        "results": results
    }
    
    # Сохраняем общий отчет
    summary_file = Path(output_dir) / "batch_summary.json"
    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    
    # Создаем HTML сводку
    html_summary = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Сводка массовой проверки</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #f2f2f2; }}
            .success {{ color: green; }}
            .error {{ color: red; }}
        </style>
    </head>
    <body>
        <h1>Сводка массовой проверки</h1>
        <p><b>Всего студентов:</b> {summary['total_students']}</p>
        <p><b>Успешно проверено:</b> <span class="success">{summary['successful']}</span></p>
        <p><b>Ошибок:</b> <span class="error">{summary['failed']}</span></p>
        <p><b>Время выполнения:</b> {elapsed_time:.1f} секунд ({elapsed_time/60:.1f} минут)</p>
        <p><b>Среднее время на студента:</b> {summary['average_time_per_student']:.1f} секунд</p>
        {f"<p><b>⚠️ Обнаружено подозрений на плагиат:</b> {summary['plagiarism_detected']}</p>" if summary['plagiarism_detected'] > 0 else ""}
        
        <h2>Детали по студентам</h2>
        <table>
            <tr>
                <th>Студент</th>
                <th>Статус</th>
                <th>Оценка</th>
                <th>Ссылка</th>
            </tr>
    """
    
    for result in sorted(results, key=lambda x: x.get('score', 0) if x.get('status') == 'success' else -1, reverse=True):
        student = result['student']
        if result['status'] == 'success':
            status_class = "success"
            status_text = f"✅ {result.get('score', 0):.1f}%"
            link = f"<a href='{student}/summary.html' target='_blank'>Отчет</a>"
        else:
            status_class = "error"
            status_text = f"❌ {result.get('error', 'Unknown')}"
            link = "-"
        
        html_summary += f"""
            <tr>
                <td>{student}</td>
                <td class="{status_class}">{status_text}</td>
                <td>{result.get('passed', 0)}/{result.get('total', 0)}</td>
                <td>{link}</td>
            </tr>
        """
    
    html_summary += """
        </table>
    </body>
    </html>
    """
    
    summary_html_file = Path(output_dir) / "batch_summary.html"
    with open(summary_html_file, 'w', encoding='utf-8') as f:
        f.write(html_summary)
    
    print(f"\n✅ Массовая проверка завершена!")
    print(f"   Успешно: {summary['successful']}/{summary['total_students']}")
    print(f"   Ошибок: {summary['failed']}")
    print(f"   Время: {elapsed_time:.1f} сек ({elapsed_time/60:.1f} мин)")
    print(f"   Сводка сохранена: {summary_html_file}")
    
    return summary
