## Executive Summary
- **Общий риск‑профиль:** 3/5  
- **Ключевые выводы**
  - Отсутствие тестов и неполный CI‑процесс повышают риск регрессий.
  - Монолитный модуль `cli.py` (≈500 строк) усложняет сопровождение.
  - Широкие `except Exception` скрывают ошибки и затрудняют отладку.
  - Не зафиксированные версии зависимостей повышают вероятность уязвимостей.
  - Фолбэк без `.gitignore` может раскрыть приватные файлы.
- **Top‑10 проблем**
  1. REL‑003 — отсутствие тестов.
  2. INF‑001 — CI требует `.[test]`, но таких зависимостей нет.
  3. REL‑001 — глушение исключений в `parse_python_file`.
  4. REL‑002 — игнорирование ошибок в `find_env_vars`.
  5. ARC‑001 — монолитный `cli.py`.
  6. SEC‑001 — отключение gitignore при отсутствии `pathspec`.
  7. SEC‑002 — нефиксированные версии зависимостей.
  8. STY‑002 — использование `print` вместо логирования.
  9. PRF‑001 — чтение файлов целиком в память.
  10. STY‑001 — повторный импорт `sys`.  
- **Quick Wins:** STY‑001, STY‑002, REL‑001, REL‑002, SEC‑002.

## Findings
| ID | Area | Severity | Priority | FileLine | Snippet | Description | EvidenceWhy | Recommendation | Effort | Owner |
|----|------|----------|----------|----------|---------|-------------|-------------|----------------|--------|-------|
| STY‑001 | Style | Low | 5 (1×5) | `mdoc/cli.py:1-4` | `import sys` (повторно) | Дублирование импорта, нарушает PEP8 (DRY) | Двойной импорт усложняет сопровождение | Удалить лишний импорт | S | Dev |
| REL‑001 | Reliability | High | 12 (3×4) | `mdoc/cli.py:103-108` | `except Exception:` | Глушение ошибок при парсинге | Нарушает KISS; сложно отладить | Логировать и пробрасывать конкретные исключения | S | Dev |
| REL‑002 | Reliability | Medium | 8 (2×4) | `mdoc/cli.py:195-208` | `except Exception:\n    pass` | Потенциально скрывает ошибки чтения `.env` | OWASP ASVS 9.1 – обработка ошибок | Добавить логирование и сообщать пользователю | S | Dev |
| ARC‑001 | Architecture | Medium | 9 (3×3) | `wc -l mdoc/cli.py` | `500 lines` | Один файл с множеством обязанностей | Нарушение SRP/когезии | Разбить на подмодули (`gitignore`, `dump`, `aggregate`) | L | Dev |
| STY‑002 | Style | Medium | 8 (2×4) | `mdoc/cli.py:241` | `print(f"[INFO] ...")` | Использование `print` вместо логгера | Нет уровней логирования | Заменить на `logging` | S | Dev |
| INF‑001 | Infrastructure | High | 12 (3×4) | `.github/workflows/ci.yml:18-24` | `pip install -e .[test]` | CI требует несуществующих зависимостей | Прерывает pipeline | Удалить `.[test]` или добавить раздел `test` | M | DevOps |
| REL‑003 | Testing | Critical | 20 (4×5) | `pytest -q` | `no tests ran` | Отсутствие unit/integration тестов | Нет гарантий корректности | Добавить базовый набор тестов | M | QA |
| SEC‑001 | Security | Medium | 9 (3×3) | `mdoc/cli.py:10-26` | `_NoPathSpec` фолбэк | При отсутствии pathspec игнорируются `.gitignore` | OWASP A5 Security Misconfiguration | Явно требовать зависимость или предупреждать пользователя | M | Dev |
| SEC‑002 | Security | High | 12 (3×4) | `pyproject.toml:1-8` | `pathspec>=0.12` | Зависимости не зафиксированы | OWASP A6 Outdated Components | Использовать точные версии или диапазоны `~=` , вести SBOM | S | Dev |
| PRF‑001 | Performance | Low | 6 (2×3) | `mdoc/cli.py:223-236` | `content = fin.read()` | Читает файл целиком в память | O(N) по размеру файла | Использовать потоковое чтение/стриминг | M | Dev |

## Detailed Analysis
### A. Architecture
- Монолитный модуль `cli.py` объединяет обработку аргументов, работу с gitignore, генерацию и агрегацию файлов (SRP, KISS).  
  **Рекомендация:** вынести отдельные подмодули:  
  ```diff
  mdoc/
    ├── cli.py          # только парсинг аргументов
  + ├── gitignore.py    # функции работы с gitignore
  + ├── dump.py         # dump_module, find_leaf_dirs…
  + └── aggregate.py    # aggregate_readmes…
  ```

### B. Style & Readability
- Повторный импорт `sys` нарушает PEP8 и принцип DRY.
- `print` вместо `logging` делает невозможным управление уровнем логирования.

### C. Reliability & Testing
- `except Exception` в `parse_python_file` скрывает ошибки парсинга и может привести к пропущенным API-элементам.  
- `find_env_vars` игнорирует ошибки чтения `.env` и молча возвращает пустой список.  
- Тесты отсутствуют: `pytest` не обнаружил ни одного сценария.

### D. Performance
- `dump_module` читает файлы целиком в память перед усечением, что может привести к пиковому потреблению RAM при больших файловых деревьях.  
  **Рекомендация:** читать порциями и сразу ограничивать `max_bytes`.

### E. Security
- При отсутствии `pathspec` утилита игнорирует `.gitignore`, что может раскрыть приватные файлы (OWASP A5).  
- Зависимости не зафиксированы; обновление может привести к уязвимостям (OWASP A6).

### F. Tech Debt
- Отсутствие тестовой инфраструктуры — ключевой долг, блокирующий CI/CD.  
- Широкие `except` и использование `print` — потенциальные “костыли”, которые усложняют переход к стабильному релизу.

### G. Infrastructure & CI/CD
- CI‑скрипт устанавливает несуществующую группу зависимостей `.[test]` и запускает `pytest`, который не находит тестов.  
  **Рекомендация:** синхронизировать `pyproject.toml` с CI, добавить линтеры и отчёт покрытия.

## Test & Coverage Summary
- ✅ `pytest -q` — **не обнаружено тестов**; покрытие не измеряется.  
  Критичный пробел: отсутствуют тесты для CLI и функций анализа.

## Security Report
- **SEC‑001**: пропуск `.gitignore` (OWASP A5 — Security Misconfiguration).  
- **SEC‑002**: незафиксированные зависимости (OWASP A6 — Vulnerable & Outdated Components).  
- Потенциальная утечка названий переменных окружения через `find_env_vars` (OWASP A3 — Sensitive Data Exposure).

## Performance Hotspots
- Чтение файлов целиком (`dump_module`) может деградировать на больших файловых деревьях, время и память — O(N) от суммарного размера файлов. Использовать потоковое чтение и ранний обрез контента.

## Tech Debt Register
| Item | Priority | Owner |
|------|----------|-------|
| Отсутствие тестов | Высокий | QA |
| Монолитный `cli.py` | Средний | Dev |
| Широкие `except` | Средний | Dev |
| print вместо logging | Низкий | Dev |
| Независимые версии зависимостей | Средний | Dev |

## 30/60/90-day Roadmap
- **30 дней:** убрать дубли импорта и `print`, добавить минимальные юнит‑тесты и фиксацию версий зависимостей.
- **60 дней:** выделить подмодули, добавить линтеры, настроить корректный CI с отчётом покрытия.
- **90 дней:** разработать расширенную тест‑стратегию, внедрить SAST/Dependency scanning, добавить метрики и логирование.

## Open Questions & Assumptions
- Предполагается, что утилита используется локально и не обрабатывает пользовательские данные.
- Неясно, есть ли ограничения по времени выполнения или объёму файлов в реальных проектах.
- Вопрос: требуется ли поддержка Windows‑платформ?

## Appendix
- **Линтеры/форматеры:** `black`, `flake8`, `isort`.
- **SAST/DAST:** `bandit`, `pip-audit`.
- **CI инструменты:** GitHub Actions с `pytest`, `coverage`, `flake8`.
- **SBOM:** `cyclonedx-py`.

```json
{
  "machine_readable_report": {
    "risk_score": 3,
    "top_issues": [
      {
        "id": "REL-003",
        "area": "Testing",
        "severity": "Critical",
        "priority": 20,
        "file": "pytest",
        "summary": "Отсутствуют тесты",
        "fix": "Добавить базовый набор unit-тестов"
      },
      {
        "id": "INF-001",
        "area": "Infrastructure",
        "severity": "High",
        "priority": 12,
        "file": ".github/workflows/ci.yml:18-24",
        "summary": "CI требует несуществующих зависимостей",
        "fix": "Синхронизировать pyproject.toml и workflow"
      },
      {
        "id": "REL-001",
        "area": "Reliability",
        "severity": "High",
        "priority": 12,
        "file": "mdoc/cli.py:103-108",
        "summary": "Глушение исключений в parse_python_file",
        "fix": "Логировать и обрабатывать конкретные ошибки"
      }
    ]
  }
}
```
