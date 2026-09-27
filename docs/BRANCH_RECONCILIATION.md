# Сверка всех веток GitHub

Снимок remote refs получен 26.09.2026; повторных загрузок неизменённых веток не делалось.
Исходная main: 233c5b45c8f457374eadbc221ef616b237de2bd9.
Рабочая ветка: integration/final-20260926. Исходный пользовательский checkout и БД не изменены.

| Ветка | SHA | Решение |
|---|---|---|
| backend | 5ba295ce7fe9d8d6f1d90c96bb8c15f6de074049 | Уже в main |
| claude/sync-ml-work | 9566163bd9f303336b09d1f55f9466b0a677f8de | Включена через merge ml-models; runtime обновлён до поставки v1.1 |
| codex/gas-triage-21 | 363d64a412e8e288d5bba82ffd4983ec9cb13f12 | Эквивалентные патчи уже в ml-models; повторно код не применяется |
| codex/gas-v4-stage19 | f1927cc87a02a91ab4a64ba43aa02007668e6427 | Включена через merge ml-models; runtime обновлён до поставки v1.1 |
| codex/gas-v4-stage19-memory | d7ea4bbaf45dbef67e808aa28b083fbb63963e8d | Включена через merge ml-models; runtime обновлён до поставки v1.1 |
| codex/ml-daily-advisories | 90bb0d07e90afc20ec3dc72a9dc34c8f55d4320a | Эквивалентные патчи уже в ml-models; повторно код не применяется |
| db-schema | 0f63b3fe16b5780188eb882721e93961d92c066c | Уже в main |
| docs/repository-guide | 4dc97b4fed1dcce8ae30babaf855f35a3c95d035 | Актуальные README/CONTRIBUTING сохранены; дополнительные шаблоны в docs/history |
| feature/data-canonical-contract | 0391a87026d9af7606b89bd9ab43e2c7ba40c9b4 | Действующие контракты main и признаки бандла сохранены; альтернативный код в docs/history |
| main | 233c5b45c8f457374eadbc221ef616b237de2bd9 | Уже в main |
| map-web-design | cb9ae263561b8f5e6af6c16f9fb657406bbab3d7 | Уже в main |
| ml-models | 29acc0d3994cdb6604faef5be22439444d85e009 | Включена через merge ml-models; runtime обновлён до поставки v1.1 |

Для уже применённых или заменённых реализаций слияние записывает выбранное текущее
дерево (ours). Это намеренное разрешение различий, а не утверждение о включении
каждой старой строки в production. Исследовательские материалы ml-models сохранены;
обучение, старые экспериментальные прогнозы и stub-head в рабочую систему не включены.
