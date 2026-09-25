"""Generate the standalone CPU Kaggle notebook 14 (raw journal → event panel v3)."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = ROOT / "notebooks" / "kaggle" / "14_event_panel_v3_cpu.ipynb"
TAXONOMY = HERE / "config" / "state_taxonomy_v3.json"


def embeddable(source: str) -> str:
    """Убирает резервный импорт event_panel_v3: в notebook имена определены ячейкой выше."""
    start = source.index("try:\n    from event_panel_v3 import")
    end = source.index("\n", source.index("pass", source.index("except ImportError:", start))) + 1
    return source[:start] + "# (импорт event_panel_v3 не нужен: модуль выполнен ячейкой выше)\n" + source[end:]


def _cell_id(kind: str, source: str) -> str:
    import hashlib

    return hashlib.sha1((kind + source).encode("utf-8")).hexdigest()[:8]


def markdown_cell(source: str) -> dict:
    return {"cell_type": "markdown", "id": _cell_id("m", source), "metadata": {}, "source": source.splitlines(True)}


def code_cell(source: str) -> dict:
    return {"cell_type": "code", "id": _cell_id("c", source), "execution_count": None, "metadata": {}, "outputs": [],
            "source": source.splitlines(True)}


INTRO = """# 14 · Событийная панель v3 из сырого журнала (CPU)

**Вычисления:** CPU, **Accelerator = None**. Интернет не нужен, если в образе есть `7z` (обычно есть);
иначе ноутбук поставит `py7zr` — тогда включите Internet в Settings.

Ноутбук заменяет дневную панель v2 (одна смешанная цель «Неисправен/Обесточен в D+2») на панель, где каждая
цель ТЗ считается отдельно по **секундному** журналу:

| цель | что значит | тип оценки |
|---|---|---|
| `target_t2a_link_onset` | начало «Неисправен» (= потеря связи, FAQ организаторов) в окне D+2 | onset proxy |
| `target_t2b_link_sustained` | то же, но эпизод длится ≥ τ (5 мин) | conditional proxy, цензура → null |
| `target_t2c_power_onset` / `_sustained` | начало «Обесточен» / длительностью ≥ τ | onset proxy |
| `target_t1a_tech_value` | технический код или значение вне диапазона у числового канала | data-quality proxy |
| `target_t4_gas_cross` | газ пересекает 1 % снизу вверх (строго) | threshold event |

Главные правила (подробно — `docs/EVENT_PANEL_V3_RU.md`):
- одна секунда канала — неупорядоченное множество значений; конфликт внутри секунды = неоднозначно, не onset;
- признаки на конец D — только прошлое; eligibility — состояние на конец D; старт в D+1 — competing outcome;
- метка решается не позже D+4 (L = 24 ч) → `d_label_decision_end` для purging в ноутбуке 15;
- тишина в окне — не отрицательный пример (`unobserved_window` → null); неоднозначное → null с причиной;
- поток = (канал, класс сигнала), stream mapping v1: «O» связи — только сообщения функции самого канала, «O» питания —
  только явные «Есть питание»/«Питание от сети»; «Неопределен» — неизвестное состояние связи (U).
  Две заранее объявленные sensitivity-версии считаются отдельно, в выход идут только числа изменившихся меток.

**Выход** (`/kaggle/working`): `event_panel_v3/` (части parquet + `panel_manifest_v3.json` с SHA-256) — вход ноутбука 15;
`audit_event_panel_v3.json` и `summary_event_panel_v3_ru.md` — только агрегаты. Ключи каналов и объектов
псевдонимизированы (`sha256(соль + id)[:16]`), сырых идентификаторов и значений в выходе нет.
"""

HOW = """## Как запустить

1. **Add Input** → **приватный** dataset с журналами `ext-journal-2019 … ext-journal-2026` (`.7z`, `.csv` или папки,
   в которые Kaggle их распаковал) и справочником каналов. Путь не нужен — файлы ищутся во всех входах.
   Kaggle заменяет кириллицу в имени файла на `_` (справочник превращается в `__.csv`) — справочник и журналы
   дополнительно распознаются по заголовку CSV. Ячейка «Проверка входов» остановит прогон, если чего-то нет.
   Старая обезличенная панель v2 **не подходит**: в ней нет истории событий. Локально можно задать `LDT_KAGGLE_INPUT_DIR`.
2. **Settings → Accelerator → None.**
3. Сначала `MODE = "SMOKE"` (2019–2020, ≈1/20 каналов, пара минут) — цифры `non_comparable`.
4. Затем `MODE = "FULL"` и **Save Version → Save & Run All**, чтобы выход сохранился и его можно было
   подключить к ноутбуку 15 как Input.
"""

CONFIG = """# ЕДИНСТВЕННАЯ ЯЧЕЙКА, КОТОРУЮ МОЖНО ИЗМЕНЯТЬ
MODE = "FULL"        # "FULL" или "SMOKE"
N_BUCKETS = 4        # групп каналов: больше — меньше памяти, дольше
TAU_MINUTES = 5      # порог устойчивого эпизода для *_sustained
RUN_SENSITIVITY = True  # + 2 пересборки разметки (≈×3 времени): «Неопределен» нейтрален; сообщения функции = O питания
print("Режим:", MODE, "| групп каналов:", N_BUCKETS, "| τ =", TAU_MINUTES, "мин | sensitivity:", RUN_SENSITIVITY)
"""

ENV = """import os, shutil, sys, platform, warnings
if os.name == "nt":  # локальный запуск на Windows: вывод кириллицы
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
import polars as pl
# шумные, но безвредные предупреждения polars (join_asof по группам; смена умолчания explode в 2.0)
warnings.filterwarnings("ignore", message=".*Sortedness of columns.*")
warnings.filterwarnings("ignore", message=".*empty_as_null.*")
print("python  ", platform.python_version())
print("polars  ", pl.__version__)
print("CPU     ", os.cpu_count())
try:
    mem = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    print(f"RAM      {mem:.1f} ГБ")
except (AttributeError, ValueError, OSError):
    pass
for d in ("/kaggle/working", "/tmp"):
    if os.path.exists(d):
        print(f"диск {d}: свободно {shutil.disk_usage(d).free / 2**30:.1f} ГБ")
print("7z      ", next((shutil.which(x) for x in ("7z", "7za", "7zr") if shutil.which(x)), "нет (будет py7zr)"))
"""

TAXONOMY_CELL = """import json, os
from pathlib import Path
TAXONOMY_JSON = {taxonomy!r}
TAXONOMY_PATH = Path(os.environ.get("LDT_STAGE_DIR", "/tmp/ldt_event_panel_v3_stage")).parent / "state_taxonomy_v3.json"
TAXONOMY_PATH.parent.mkdir(parents=True, exist_ok=True)
TAXONOMY_PATH.write_text(TAXONOMY_JSON, encoding="utf-8")
print("таксономия:", json.loads(TAXONOMY_JSON)["version"], "| классов:", len(json.loads(TAXONOMY_JSON)["text_classes"]))
"""

SELF = """import tempfile
SELF_TESTS = run_event_panel_self_tests(TAXONOMY_PATH, Path(tempfile.mkdtemp()))
for name, ok in SELF_TESTS.items():
    print("OK  " if ok else "FAIL", name)
assert all(SELF_TESTS.values()), "Самопроверки не пройдены"
"""

PREFLIGHT = """CONFIG = make_config_v3(MODE, {"taxonomy_path": str(TAXONOMY_PATH), "n_buckets": N_BUCKETS,
                               "panel": {"tau_minutes": TAU_MINUTES},
                               **({} if RUN_SENSITIVITY else {"sensitivity_variants": []})})
SOURCES = discover_sources(Path(CONFIG["input_dir"]))
for line in describe_sources(SOURCES):
    print(line)
if not SOURCES["journals"] or SOURCES["catalogue"] is None:
    raise FileNotFoundError(
        "Ноутбуку 14 нужны сырые журналы ext-journal-YYYY (.7z/.csv/.parquet или папки Kaggle) и справочник каналов "
        "(колонки ид_канала_данных, тип_датчика) в Add Input. Обезличенная панель v2 не подходит — в ней нет истории "
        "событий. Проверенный корень входов: " + str(CONFIG["input_dir"]))
"""

RUN = """RESULT = run_event_panel_v3(CONFIG)
print()
print("Статус:", RESULT["status"])
if RESULT.get("stop_reason"):
    raise RuntimeError("Панель не построена: " + RESULT["stop_reason"])
"""

SUMMARY = """from IPython.display import Markdown, display
OUT = Path(CONFIG["output_dir"])
if RESULT["status"].startswith("completed"):
    display(Markdown((OUT / "summary_event_panel_v3_ru.md").read_text(encoding="utf-8")))
"""

BY_YEAR = """import pandas as pd
if RESULT["status"].startswith("completed"):
    audit = json.loads((OUT / "audit_event_panel_v3.json").read_text(encoding="utf-8"))
    rows = []
    for target, s in audit["targets"].items():
        for year, c in s["by_year"].items():
            lab = c["pos"] + c["neg"]
            rows.append({"цель": target.replace("target_", ""), "год": year, "1": c["pos"], "0": c["neg"],
                         "null": c["null"], "доля 1": round(c["pos"] / lab, 5) if lab else None})
    display(pd.DataFrame(rows).pivot_table(index="год", columns="цель", values="доля 1"))
    display(pd.DataFrame(rows).pivot_table(index="год", columns="цель", values="1", aggfunc="sum"))
"""

FINISH = """OUT = Path(CONFIG["output_dir"])
if RESULT["status"].startswith("completed"):
    files = sorted((OUT / "event_panel_v3").glob("*")) + [OUT / "audit_event_panel_v3.json", OUT / "summary_event_panel_v3_ru.md"]
    missing = [p.name for p in files if not p.is_file()]
    if missing:
        raise RuntimeError("Сборка завершилась без ожидаемых файлов: " + ", ".join(missing))
    print("Файлы для передачи команде и ноутбуку 15:")
    for p in files:
        print(f"- {p.relative_to(OUT)} ({p.stat().st_size / 2**20:.1f} МБ)")
    print("Сырые данные и промежуточные parquet удалены; в выходе только псевдонимизированная панель и агрегаты.")
else:
    print("Выходные файлы отсутствуют: панель не построена.")
"""


def build_notebook() -> dict:
    module = (HERE / "event_panel_v3.py").read_text(encoding="utf-8")
    kaggle = embeddable((HERE / "event_panel_v3_kaggle.py").read_text(encoding="utf-8"))
    taxonomy = TAXONOMY.read_text(encoding="utf-8")
    return {
        "cells": [
            markdown_cell(INTRO), markdown_cell(HOW), code_cell(CONFIG), code_cell(ENV),
            markdown_cell("## Таксономия значений (встроена, SHA-256 попадает в manifest)\n"),
            code_cell(TAXONOMY_CELL.format(taxonomy=taxonomy)),
            markdown_cell("## Встроенный runtime панели v3\n\nКод встроен; репозиторий на Kaggle не нужен.\n"),
            code_cell(module),
            markdown_cell("## Встроенная обвязка Kaggle: поиск входов, 7z → parquet, manifest\n"),
            code_cell(kaggle),
            markdown_cell("## Самопроверки на синтетике\n"),
            code_cell(SELF),
            markdown_cell("## Проверка входов\n\nЧто найдено во входах ноутбука (имена и размеры файлов, без содержимого).\n"),
            code_cell(PREFLIGHT),
            markdown_cell("## Сборка панели\n"),
            code_cell(RUN),
            markdown_cell("## Сводка для команды\n"),
            code_cell(SUMMARY),
            markdown_cell("## Доля положительных по годам\n\n2021 — переход системы мониторинга (FAQ): "
                          "в ноутбуке 15 исключается из обучения и оценки.\n"),
            code_cell(BY_YEAR),
            code_cell(FINISH),
        ],
        "metadata": {
            "kaggle": {"accelerator": "none", "dataSources": [], "isInternetEnabled": False, "language": "python",
                       "sourceType": "notebook", "isGpuEnabled": False},
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(build_notebook(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("written", OUTPUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
