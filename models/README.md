# ML-модели

Бинарные файлы моделей не хранятся в Git (`models/*` в `.gitignore`), хранится только это описание.

## Пакет LCT_ML_backend_v1

Модели лежат ZIP-бандлами в `models/bundles/` (путь меняется через `ML_BUNDLES_DIR`):
`gas_cross_v3_bundle.zip`, `incident_head_bundle.zip`, `ACTIVE.json` и `*.sha256` рядом с каждым ZIP.
Бандлы приходят от ML-команды; runtime сам сверяет SHA-256 и отказывается грузить подменённый файл.
Код входа `backend/app/ml_runtime/lct_ml_runtime.py` перенесён из пакета без изменений.

Подробности интеграции, запуск и ограничения: [`docs/ML_INTEGRATION_RU.md`](../docs/ML_INTEGRATION_RU.md).

Backend/frontend не генерируют собственный `risk_score`: показывается только то, что вернул runtime.
