"""
Базовый класс ADBController для управления эмулятором Android через ADB.
Предоставляет простой интерфейс для основных операций с эмулятором.
"""

import time
from typing import Optional, Tuple
from pathlib import Path
from io import BytesIO

from ppadb.client import Client as ADBClient
from ppadb.device import Device
from PIL import Image
from loguru import logger


class ADBController:
    """Контроллер для управления Android эмулятором через ADB"""

    def __init__(self, adb_host: str = "127.0.0.1", adb_port: int = 5037):
        """
        Инициализация ADB контроллера

        Args:
            adb_host: IP адрес ADB сервера (обычно localhost)
            adb_port: Порт ADB сервера (обычно 5037)
        """
        self.adb_host = adb_host
        self.adb_port = adb_port
        self.client: Optional[ADBClient] = None
        self.device: Optional[Device] = None
        self.device_port: Optional[int] = None

    def connect(self, device_port: int) -> bool:
        """
        Подключение к устройству по указанному порту

        Args:
            device_port: Порт устройства (например, 5555 для первого LDPlayer)

        Returns:
            True если подключение успешно, False иначе
        """
        try:
            # Создаем клиент ADB
            self.client = ADBClient(host=self.adb_host, port=self.adb_port)

            # Формируем адрес устройства
            device_address = f"{self.adb_host}:{device_port}"

            # Подключаемся к устройству
            self.device = self.client.device(device_address)

            if self.device is None:
                logger.error(f"Не удалось найти устройство {device_address}")
                return False

            # Проверяем соединение
            if not self.check_connection():
                logger.error(f"Устройство {device_address} недоступно")
                return False

            self.device_port = device_port
            logger.info(f"Успешно подключились к устройству {device_address}")
            return True

        except Exception as e:
            logger.error(f"Ошибка подключения к устройству {device_port}: {e}")
            return False

    def disconnect(self) -> None:
        """Отключение от устройства"""
        try:
            if self.device:
                logger.info(f"Отключаемся от устройства {self.device_port}")
                self.device = None
                self.device_port = None

            if self.client:
                self.client = None

        except Exception as e:
            logger.error(f"Ошибка при отключении: {e}")

    def check_connection(self) -> bool:
        """
        Проверка активности соединения с устройством

        Returns:
            True если соединение активно, False иначе
        """
        try:
            if not self.device:
                return False

            # Простая проверка - получение информации об устройстве
            info = self.device.shell("echo 'test'")
            return "test" in str(info)

        except Exception as e:
            logger.warning(f"Проблема с соединением: {e}")
            return False

    def tap(self, x: int, y: int, duration: int = 100) -> bool:
        """
        Тап по координатам экрана

        Args:
            x: Координата X
            y: Координата Y
            duration: Длительность нажатия в миллисекундах

        Returns:
            True если команда выполнена успешно, False иначе
        """
        try:
            if not self.device:
                logger.error("Устройство не подключено")
                return False

            # Выполняем тап через shell команду
            cmd = f"input tap {x} {y}"
            result = self.device.shell(cmd)

            # Небольшая задержка после тапа
            time.sleep(duration / 1000.0)

            logger.debug(f"Тап по координатам ({x}, {y}) выполнен")
            return True

        except Exception as e:
            logger.error(f"Ошибка при выполнении тапа ({x}, {y}): {e}")
            return False

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 500) -> bool:
        """
        Свайп от одной точки к другой

        Args:
            x1: Начальная координата X
            y1: Начальная координата Y
            x2: Конечная координата X
            y2: Конечная координата Y
            duration: Длительность свайпа в миллисекундах

        Returns:
            True если команда выполнена успешно, False иначе
        """
        try:
            if not self.device:
                logger.error("Устройство не подключено")
                return False

            # Выполняем свайп через shell команду
            cmd = f"input swipe {x1} {y1} {x2} {y2} {duration}"
            result = self.device.shell(cmd)

            # Небольшая задержка после свайпа
            time.sleep(duration / 1000.0 + 0.1)

            logger.debug(f"Свайп от ({x1}, {y1}) до ({x2}, {y2}) выполнен")
            return True

        except Exception as e:
            logger.error(f"Ошибка при выполнении свайпа: {e}")
            return False

    def screenshot(self, save_path: Optional[str] = None) -> Optional[Image.Image]:
        """
        Получение скриншота экрана устройства

        Args:
            save_path: Путь для сохранения скриншота (опционально)

        Returns:
            PIL Image объект или None в случае ошибки
        """
        try:
            if not self.device:
                logger.error("Устройство не подключено")
                return None

            # Получаем скриншот
            screenshot_data = self.device.screencap()

            if not screenshot_data:
                logger.error("Не удалось получить скриншот")
                return None

            # Конвертируем в PIL Image
            image = Image.open(BytesIO(screenshot_data))

            # Сохраняем если указан путь
            if save_path:
                Path(save_path).parent.mkdir(parents=True, exist_ok=True)
                image.save(save_path)
                logger.debug(f"Скриншот сохранен: {save_path}")

            return image

        except Exception as e:
            logger.error(f"Ошибка при получении скриншота: {e}")
            return None

    def get_screen_size(self) -> Optional[Tuple[int, int]]:
        """
        Получение размера экрана устройства

        Returns:
            Кортеж (ширина, высота) или None в случае ошибки
        """
        try:
            if not self.device:
                logger.error("Устройство не подключено")
                return None

            # Получаем информацию об экране
            result = self.device.shell("wm size")

            if "Physical size:" in result:
                # Парсим размер из строки типа "Physical size: 540x960"
                size_str = result.split("Physical size:")[1].strip()
                width, height = map(int, size_str.split("x"))
                return (width, height)

            return None

        except Exception as e:
            logger.error(f"Ошибка при получении размера экрана: {e}")
            return None

    def is_screen_on(self) -> bool:
        """
        Проверка включен ли экран устройства

        Returns:
            True если экран включен, False иначе
        """
        try:
            if not self.device:
                return False

            # Проверяем статус экрана
            result = self.device.shell("dumpsys power | grep 'Display Power'")
            return "state=ON" in result or "state=2" in result

        except Exception as e:
            logger.warning(f"Ошибка при проверке статуса экрана: {e}")
            return True  # Предполагаем что экран включен

    def wake_up_screen(self) -> bool:
        """
        Включение экрана устройства

        Returns:
            True если команда выполнена успешно, False иначе
        """
        try:
            if not self.device:
                return False

            # Включаем экран
            self.device.shell("input keyevent KEYCODE_WAKEUP")
            time.sleep(1)

            return self.is_screen_on()

        except Exception as e:
            logger.error(f"Ошибка при включении экрана: {e}")
            return False