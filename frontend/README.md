# React + TypeScript + Vite

## Карта

Основной вид использует интерактивные тайлы OpenStreetMap и браузерные
перемещение/масштабирование. `VITE_MAP_TILE_URL` позволяет указать другой
совместимый источник тайлов; по умолчанию используются публичные стандартные
тайлы OSM. Локальная схема Москвы доступна через переключатель «Схема» и при
сбое загрузки тайлов. Атрибуция OpenStreetMap остаётся видимой на карте.

Текущий backend создаёт **демонстрационные**, а не реальные координаты
объектов. Интерфейс явно показывает это. Статусы маркеров относятся к текущим
событиям; они не являются ML-прогнозом. Ограничения и требования для будущего
прогнозного слоя перечислены в `../docs/MAP_TZ_COVERAGE_RU.md`.

При использовании публичного сервера тайлов соблюдайте
[правила OSM](https://operations.osmfoundation.org/policies/tiles/): показывайте
атрибуцию, сохраняйте обычный Referer и кэширование браузера, не загружайте
тайлы заранее. Для гарантированной доступности используйте собственный или
договорной источник.

This template provides a minimal setup to get React working in Vite with HMR and some Oxlint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the Oxlint configuration

If you are developing a production application, we recommend enabling type-aware lint rules by installing `oxlint-tsgolint` and editing `.oxlintrc.json`:

```json
{
  "$schema": "./node_modules/oxlint/configuration_schema.json",
  "plugins": ["react", "typescript", "oxc"],
  "options": {
    "typeAware": true
  },
  "rules": {
    "react/rules-of-hooks": "error",
    "react/only-export-components": ["warn", { "allowConstantExport": true }]
  }
}
```

See the [Oxlint rules documentation](https://oxc.rs/docs/guide/usage/linter/rules) for the full list of rules and categories.
