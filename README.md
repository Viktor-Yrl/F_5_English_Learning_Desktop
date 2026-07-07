# English Learning Desktop App

Десктопное приложение для Windows на Python в тёмном стиле мобильного приложения ReWord.

## Что есть

- Раздел Learn с карточками тренировок, статистикой, streak и мини-графиком.
- Раздел Vocabulary со списком слов, уровнями, категориями и поиском.
- Раздел Menu в стиле исходных скриншотов.
- Простой тренажёр перевода слов.
- Локальное хранение слов и прогресса в папке `data`.
- Создание и восстановление `.backup` файлов в SQLite-формате, похожем на ReWord backup.
- Поддержка найденной структуры ReWord: `WordStat`, `GoodSeries`, `TotalAnswerNumbers`, `LastRepeatTime` и sync JSON `version/time/words/learned`.

## Запуск

Основная быстрая версия на PyQt6 + SQLite:

```powershell
pip install -r requirements-pyqt6.txt
python app_pyqt6.py
```

Старая версия на CustomTkinter:

```powershell
pip install -r requirements.txt
python app.py
```

Если `customtkinter` уже установлен, достаточно:

```powershell
python app.py
```

## Почему добавлена Qt-версия

После импорта ReWord backup слов может быть больше 10 000. `app_pyqt6.py` хранит данные в SQLite и показывает словарь через `QTableView`, поэтому не создаёт тысячи отдельных виджетов и работает заметно быстрее.
