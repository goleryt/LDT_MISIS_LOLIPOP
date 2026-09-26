# Как воспроизвести notebook 13: `13_failure_onset_v2_cadence_cpu.ipynb`

План и гипотезы (зафиксированы до обучения): `docs/EXPERIMENT_13_EPISODE_V2_RU.md`.
Исходники: `ml/sensor_failure/episode_v2_runtime.py` + `ml/sensor_failure/pre2025_audit_runtime.py` (из 05).
Ноутбук генерируется `python ml/sensor_failure/generate_episode_v2_notebook.py` и встраивает оба модуля дословно;
тесты — `tests/test_episode_v2_runtime.py` (проверяют, что встроенный код совпадает с исходниками).

## Запуск

1. Новый Kaggle Notebook → **File → Import Notebook** → `13_failure_onset_v2_cadence_cpu.ipynb`.
2. **Add Input** → тот же приватный dataset panel v2, что у 01–06 (`panel_manifest_v2.json` ищется автоматически).
3. **Settings → Accelerator → None.**
4. `MODE = "SMOKE"` → Run All: самопроверки `OK`, статус `completed_smoke_non_comparable`.
5. `MODE = "FULL"` → **Restart & Run All**.

## Ожидаемые время и память (оценка)

| режим | время | пик RAM |
| --- | --- | --- |
| SMOKE | 1–3 мин | 2–4 ГБ |
| FULL | 15–40 мин | 6–12 ГБ |

В FULL загружаются все строки до 2025 года, включая неразмеченные: они нужны для истории cadence-признаков
и для правила D+1. Строки 2025+ не загружаются.

## Что вернуть команде

- `results_failure_onset_v2.json` и `summary_failure_onset_v2_ru.md` (только агрегаты, без ключей и построчных прогнозов);
- строку статуса и значение `share_of_v1_positives_started_on_dplus1` из вывода.

## Как читать результат

- `target_audit.share_of_v1_positives_started_on_dplus1` — доля positives старой цели, у которых эпизод начался уже в D+1.
  Это главный факт E1: насколько цель v1 была «опаздывающей».
- `selection.selected`: `v2_cadence*` — cadence прошёл все gates против `v2_base`; `v2_base` — cadence не дал
  доказанного выигрыша; имя baseline — даже `v2_base` не обгоняет сильнейший baseline по PR-AUC с CI > 0.
- Гипотезы имеют статусы `confirmed` / `rejected` / `inconclusive`; решения принимаются только по CI.
