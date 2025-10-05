"""
Точка входа в TUI интерфейс Beast Lord Bot
ПРОМПТ 24: Простой TUI интерфейс с 4 экранами
"""

import sys
from pathlib import Path

# Добавляем корневую директорию в путь для импортов
sys.path.insert(0, str(Path(__file__).parent))

from loguru import logger
from tui.app import BotTUIApp


def main():
    """Главная функция запуска TUI"""

    # Создаем необходимые директории
    Path("data/logs").mkdir(parents=True, exist_ok=True)
    Path("configs").mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("Beast Lord Bot - TUI Interface v2.1")
    logger.info("=" * 60)

    try:
        # Создаем и запускаем TUI приложение
        app = BotTUIApp()
        app.run()

        logger.info("Приложение завершено успешно")
        return 0

    except Exception as e:
        logger.error(f"Критическая ошибка при запуске TUI: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return 1


if __name__ == "__main__":
    exit(main())