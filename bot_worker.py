"""
Основной рабочий модуль бота для обработки одного эмулятора.
Подключается к LDPlayer через ADB и выполняет базовые операции.
"""

import sys
import time
from datetime import datetime
from pathlib import Path

from loguru import logger
from utils.adb_controller import ADBController


class BotWorker:
    """Основной рабочий класс для обработки одного эмулятора"""

    def __init__(self, emulator_index: int = 0, adb_port: Optional[int] = None):
        """
        Инициализация рабочего бота

        Args:
            emulator_index: Индекс эмулятора (0, 1, 2...)
            adb_port: Порт ADB (по умолчанию рассчитывается из индекса)
        """
        self.emulator_index = emulator_index

        # Рассчитываем порт ADB по стандартной формуле LDPlayer
        if adb_port is None:
            self.adb_port = 5555 + emulator_index * 2
        else:
            self.adb_port = adb_port

        self.controller = ADBController()
        self.screenshots_dir = Path("data/screenshots")
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Инициализирован BotWorker для эмулятора {emulator_index}, порт ADB: {self.adb_port}")

    def connect(self) -> bool:
        """
        Подключение к эмулятору

        Returns:
            True если подключение успешно, False иначе
        """
        logger.info(f"Подключаемся к эмулятору {self.emulator_index} на порту {self.adb_port}")

        if self.controller.connect(self.adb_port):
            logger.success(f"Успешно подключились к эмулятору {self.emulator_index}")
            return True
        else:
            logger.error(f"Не удалось подключиться к эмулятору {self.emulator_index}")
            return False

    def disconnect(self) -> None:
        """Отключение от эмулятора"""
        logger.info(f"Отключаемся от эмулятора {self.emulator_index}")
        self.controller.disconnect()

    def take_screenshot(self, description: str = "general") -> bool:
        """
        Делает скриншот и сохраняет его

        Args:
            description: Описание скриншота для имени файла

        Returns:
            True если скриншот сделан успешно, False иначе
        """
        try:
            # Формируем имя файла с временной меткой
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"emulator_{self.emulator_index}_{description}_{timestamp}.png"
            filepath = self.screenshots_dir / filename

            logger.info(f"Делаем скриншот эмулятора {self.emulator_index}: {description}")

            # Получаем скриншот
            screenshot = self.controller.screenshot(str(filepath))

            if screenshot:
                logger.success(f"Скриншот сохранен: {filepath}")
                return True
            else:
                logger.error("Не удалось получить скриншот")
                return False

        except Exception as e:
            logger.error(f"Ошибка при создании скриншота: {e}")
            return False

    def check_device_status(self) -> dict:
        """
        Проверяет состояние устройства

        Returns:
            Словарь с информацией о состоянии устройства
        """
        status = {
            "connected": False,
            "screen_on": False,
            "screen_size": None,
            "adb_port": self.adb_port,
            "emulator_index": self.emulator_index
        }

        try:
            # Проверяем подключение
            status["connected"] = self.controller.check_connection()

            if status["connected"]:
                # Проверяем экран
                status["screen_on"] = self.controller.is_screen_on()
                status["screen_size"] = self.controller.get_screen_size()

                logger.info(f"Статус эмулятора {self.emulator_index}:")
                logger.info(f"  - Подключен: {status['connected']}")
                logger.info(f"  - Экран включен: {status['screen_on']}")
                logger.info(f"  - Размер экрана: {status['screen_size']}")
            else:
                logger.warning(f"Эмулятор {self.emulator_index} не подключен")

        except Exception as e:
            logger.error(f"Ошибка при проверке статуса устройства: {e}")

        return status

    def wake_up_device(self) -> bool:
        """
        Пробуждает устройство если экран выключен

        Returns:
            True если устройство проснулось, False иначе
        """
        try:
            if not self.controller.is_screen_on():
                logger.info(f"Пробуждаем эмулятор {self.emulator_index}")
                return self.controller.wake_up_screen()
            else:
                logger.debug(f"Экран эмулятора {self.emulator_index} уже включен")
                return True

        except Exception as e:
            logger.error(f"Ошибка при пробуждении устройства: {e}")
            return False

    def run_basic_test(self) -> bool:
        """
        Запускает базовый тест - подключение, скриншот, отключение

        Returns:
            True если тест прошел успешно, False иначе
        """
        logger.info(f"Запускаем базовый тест для эмулятора {self.emulator_index}")

        try:
            # 1. Подключаемся
            if not self.connect():
                return False

            # 2. Проверяем статус
            status = self.check_device_status()
            if not status["connected"]:
                logger.error("Устройство не подключено")
                return False

            # 3. Пробуждаем устройство
            if not self.wake_up_device():
                logger.warning("Не удалось пробудить устройство, продолжаем")

            # 4. Делаем скриншот
            if not self.take_screenshot("startup_test"):
                logger.error("Не удалось сделать скриншот")
                return False

            # 5. Небольшая пауза
            time.sleep(2)

            # 6. Еще один скриншот для проверки
            if not self.take_screenshot("final_test"):
                logger.error("Не удалось сделать финальный скриншот")
                return False

            logger.success(f"Базовый тест эмулятора {self.emulator_index} завершен успешно")
            return True

        except Exception as e:
            logger.error(f"Ошибка во время базового теста: {e}")
            return False

        finally:
            # Всегда отключаемся
            self.disconnect()


def main():
    """Основная функция для тестирования"""
    # Настройка логирования
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="INFO"
    )

    # Создаем директорию для логов
    logs_dir = Path("data/logs")
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Добавляем запись в файл
    logger.add(
        logs_dir / "bot_worker.log",
        rotation="1 day",
        retention="7 days",
        level="DEBUG"
    )

    logger.info("Запуск тестирования BotWorker")

    # Тестируем первый эмулятор (порт 5555)
    bot = BotWorker(emulator_index=0)

    if bot.run_basic_test():
        logger.success("Тест прошел успешно!")
        return 0
    else:
        logger.error("Тест завершился с ошибкой!")
        return 1


if __name__ == "__main__":
    exit(main())